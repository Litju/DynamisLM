from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from scripts import a02_v3_constrained as constrained
from scripts import a02_v3_contract as v3
from scripts import a02_v3_decision as decision
from scripts import a02_v3_gold as gold
from scripts import a02_v3_score as score
from scripts import a02_v3_worker as worker

PROTOCOL = decision.load_protocol()
ITEMS = worker.work_items(PROTOCOL)
ASSISTANT = "<assistant>"
COSTS = {"QUALIFICATION": 10.0, "ZERO_SHOT_UNCONSTRAINED": 1.0, "ZERO_SHOT_CONSTRAINED": 1.0}


def _targets() -> dict[str, str]:
    targets: dict[str, str] = {}
    for example in decision.heldout_examples(PROTOCOL):
        targets[v3.user_message(example["request"])] = example["target_text"]
    for example in worker.calibration_examples(PROTOCOL):
        targets[v3.user_message(example["request"])] = example["target_text"]
    for case in score._cases().values():
        action = gold.derive_gold(case["request"])["action"]
        path = constrained.decode(
            request=case["request"],
            prompt_ids=[],
            encode=lambda t: [ord(c) for c in t],
            chooser=constrained.target_chooser(action),
        )
        targets[v3.user_message(case["request"])] = path["text"]
    return targets


TARGETS = _targets()


_REVERSE: dict[int, str] = {}


def _chunk_ids(text: str) -> list[int]:
    ids = []
    for start in range(0, len(text), 8):
        piece = text[start : start + 8]
        token = int(v3.sha256(piece.encode())[:12], 16)  # content-derived, run-independent
        if _REVERSE.setdefault(token, piece) != piece:
            raise AssertionError("fake tokenizer hash collision")
        ids.append(token)
    return ids


class _Tokenizer:
    """Deterministic 8-character chunk tokenizer with exact decoding."""

    def apply_chat_template(self, messages: Any, *, tokenize: bool, **_: Any) -> Any:
        text = "".join(f"<{m['role']}>{m['content']}" for m in messages) + ASSISTANT
        return self.encode(text) if tokenize else text

    def encode(self, text: str, add_special_tokens: bool = False) -> list[int]:
        return _chunk_ids(text)


def _user(ids: Sequence[int]) -> str:
    text = "".join(_REVERSE[i] for i in ids)
    prompt, _, _ = text.rpartition(ASSISTANT)
    return prompt.split("<user>", 1)[1]


def _split(ids: Sequence[int]) -> tuple[str, str]:
    text = "".join(_REVERSE[i] for i in ids)
    _, _, action = text.rpartition(ASSISTANT)
    return TARGETS[_user(ids)], action


class _Backend:
    """Fast deterministic fake: native emits gold or bare JSON, chosen by request content."""

    model_identity = PROTOCOL["candidate_model"]

    def __init__(self, *, reference_offset: float = 0.0) -> None:
        self.tokenizer = _Tokenizer()
        self.reference_offset = reference_offset
        self.native_calls = 0
        self.touched: list[str] = []  # user message of every request the model was shown

    def generate_native(
        self, prompt_ids: Sequence[int], max_new_tokens: int
    ) -> tuple[list[int], str, bool]:
        target, _ = _split(list(prompt_ids))
        self.touched.append(_user(list(prompt_ids)))
        self.native_calls += 1
        framed = int(v3.sha256(target.encode())[:4], 16) % 2 == 0
        text = target if framed else target[len(v3.OPEN) : -len(v3.CLOSE)]
        return _chunk_ids(text), text, False

    def _scorer(self, offset: float) -> constrained.SequenceLogprob:
        def score_ids(ids: Sequence[int], start: int) -> float:
            target, action = _split(ids)
            self.touched.append(_user(ids))
            return (0.0 if target.startswith(action) else -1.0) + offset * (len(ids) - start)

        return score_ids

    def cached_scorer(self) -> constrained.SequenceLogprob:
        return self._scorer(0.0)

    def reference_scorer(self) -> constrained.SequenceLogprob:
        return self._scorer(self.reference_offset)


def _without_timing(path: Path) -> list[Any]:
    """Committed evidence without measured wall-clock fields, which legitimately vary.

    Chain hashes cover those fields, so they are dropped too; read_checkpoint has already
    verified each file's own chain.
    """
    entries = worker.read_checkpoint(path, ITEMS)["entries"]
    return [
        {
            **{k: v for k, v in e.items() if k != "prev_sha256"},
            "record": {k: v for k, v in e["record"].items() if k != "seconds"},
        }
        for e in entries
    ]


def _run(path: Path, backend: Any = None, **kwargs: Any) -> dict[str, Any]:
    return worker.run_worker(
        protocol=PROTOCOL,
        items=ITEMS,
        checkpoint=path,
        backend=backend or _Backend(),
        deadline=kwargs.pop("deadline", float("inf")),
        item_cost_bounds=COSTS,
        **kwargs,
    )


@pytest.fixture(scope="module")
def complete(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("complete") / "checkpoint.jsonl"
    assert _run(path)["status"] == "COMPLETE"
    return path


def test_work_list_is_deterministic_paired_and_complete() -> None:
    assert ITEMS[0] == worker.WorkItem("QUALIFICATION", "ZERO_SHOT_CONSTRAINED")
    assert len(ITEMS) == 1 + 2 * 280 + 2 * 10
    assert ITEMS == worker.work_items(PROTOCOL)
    assert len({item.id for item in ITEMS}) == len(ITEMS)
    heldout = [i for i in ITEMS if i.key.startswith("HELDOUT:")]
    assert [i.arm for i in heldout[:2]] == list(worker.ARMS)


def test_complete_run_scores_entirely_on_cpu(complete: Path) -> None:
    report = worker.score_checkpoint(PROTOCOL, complete)
    assert report["qualification"]["passed"] is True
    result = report["decision"]
    assert result["ZERO_SHOT_CONSTRAINED"]["exact"] == 1.0
    assert 0.0 < result["ZERO_SHOT_UNCONSTRAINED"]["strict_valid"] < 1.0
    assert result["decision"] == "ADOPT_REPAIRED_CONTRACT_WITH_CONSTRAINED_DECODING"
    exposed = report["exposed_development_diagnostics"]["ZERO_SHOT_CONSTRAINED"]
    assert exposed["intent_exact"] == {"numerator": 10, "denominator": 10}
    assert exposed["unauthorized_executions"] == 0


def test_interrupted_and_resumed_run_equals_uninterrupted_run(
    tmp_path: Path, complete: Path
) -> None:
    path = tmp_path / "checkpoint.jsonl"
    first = _run(path, stop_after=40)
    assert first == {"status": "STOPPED", "committed": 40, "head": first["head"]}
    second = _run(path, stop_after=200)
    assert second["committed"] == 240
    assert _run(path)["status"] == "COMPLETE"
    assert _without_timing(path) == _without_timing(complete)


def test_torn_final_write_is_discarded_and_recovered(tmp_path: Path, complete: Path) -> None:
    path = tmp_path / "checkpoint.jsonl"
    _run(path, stop_after=25)
    with path.open("ab") as handle:
        handle.write(b'{"schema":"RES541_A02_V3_CHECKPOINT_LINE_V1","seq":25,"prev')
    state = worker.read_checkpoint(path, ITEMS)
    assert state["torn_tail_discarded"] is True and len(state["entries"]) == 25
    assert _run(path)["status"] == "COMPLETE"
    assert _without_timing(path) == _without_timing(complete)


def test_corrupted_or_forked_checkpoint_fails_closed(tmp_path: Path, complete: Path) -> None:
    lines = complete.read_bytes().split(b"\n")[:30]
    edited = tmp_path / "edited.jsonl"
    record = json.loads(lines[5])
    record["record"]["raw_output"] = "tampered"
    edited.write_bytes(b"\n".join([*lines[:5], json.dumps(record).encode(), *lines[6:]]) + b"\n")
    with pytest.raises(worker.CheckpointError, match="chain breaks at line 5"):
        worker.read_checkpoint(edited, ITEMS)

    dropped = tmp_path / "dropped.jsonl"
    dropped.write_bytes(b"\n".join([*lines[:5], *lines[6:]]) + b"\n")
    with pytest.raises(worker.CheckpointError, match="chain breaks at line 5"):
        worker.read_checkpoint(dropped, ITEMS)

    garbage = tmp_path / "garbage.jsonl"
    garbage.write_bytes(b"\n".join([*lines[:3], b"not json"]) + b"\n")
    with pytest.raises(worker.CheckpointError, match="line 3 is corrupt"):
        worker.read_checkpoint(garbage, ITEMS)

    reordered = list(reversed(ITEMS))
    with pytest.raises(worker.CheckpointError, match="not the preregistered next item"):
        worker.read_checkpoint(complete, reordered)


def test_deadline_pauses_at_a_clean_item_boundary(tmp_path: Path, complete: Path) -> None:
    now = [0.0]

    def clock() -> float:
        now[0] += 0.5
        return now[0]

    path = tmp_path / "checkpoint.jsonl"
    paused = _run(path, deadline=40.0, clock=clock)
    assert paused["status"] == "PAUSED_AT_DEADLINE"
    assert 0 < paused["committed"] < len(ITEMS)
    assert len(worker.read_checkpoint(path, ITEMS)["entries"]) == paused["committed"]
    assert _run(path)["status"] == "COMPLETE"
    assert _without_timing(path) == _without_timing(complete)


def test_deadline_shorter_than_qualification_commits_nothing(tmp_path: Path) -> None:
    path = tmp_path / "checkpoint.jsonl"
    assert _run(path, deadline=5.0, clock=lambda: 0.0)["committed"] == 0
    assert not path.exists()


def test_failed_cache_qualification_blocks_all_arm_results(tmp_path: Path) -> None:
    path = tmp_path / "checkpoint.jsonl"
    bad = _Backend(reference_offset=0.01)
    assert _run(path, backend=bad)["status"] == "QUALIFICATION_FAILED"
    assert len(worker.read_checkpoint(path, ITEMS)["entries"]) == 1
    assert _run(path)["status"] == "QUALIFICATION_FAILED"  # resume never proceeds
    with pytest.raises(worker.CheckpointError, match="incomplete"):
        worker.score_checkpoint(PROTOCOL, path)


def test_incomplete_or_tampered_evidence_cannot_be_scored(tmp_path: Path, complete: Path) -> None:
    partial = tmp_path / "partial.jsonl"
    _run(partial, stop_after=10)
    with pytest.raises(worker.CheckpointError, match="incomplete"):
        worker.score_checkpoint(PROTOCOL, partial)


def test_records_bind_provenance_for_decision_evidence(complete: Path) -> None:
    entries = worker.read_checkpoint(complete, ITEMS)["entries"]
    record = next(e["record"] for e in entries if e["item"].startswith("HELDOUT:"))
    assert record["schema"] == decision.RECORD_SCHEMA
    assert record["protocol_sha256"] == decision.protocol_sha256()
    assert record["model_revision"] == PROTOCOL["candidate_model"]["revision"]
    assert len(record["generated_token_ids_sha256"]) == 64
    constrained_record = next(
        e["record"]
        for e in entries
        if e["item"].endswith("|ZERO_SHOT_CONSTRAINED") and e["item"].startswith("HELDOUT:")
    )
    assert constrained_record["choices"] and constrained_record["scorer_calls"] > 0


# ---- calibration before protected evidence --------------------------------------------

PROTECTED_USERS = {v3.user_message(e["request"]) for e in decision.heldout_examples(PROTOCOL)}
CALIBRATION_USERS = {v3.user_message(e["request"]) for e in worker.calibration_examples(PROTOCOL)}
EXPOSED_USERS = {v3.user_message(c["request"]) for c in score._cases().values()}


def test_calibration_examples_are_non_heldout_and_within_the_planned_option_bound() -> None:
    examples = worker.calibration_examples(PROTOCOL)
    assert [e["split"] for e in examples] == ["TRAIN"] * worker.QUALIFICATION_EXAMPLES
    assert not {decision.example_id(e) for e in examples} & {
        decision.example_id(e) for e in decision.heldout_examples(PROTOCOL)
    }
    assert not CALIBRATION_USERS & (PROTECTED_USERS | EXPOSED_USERS)
    # The plan prices qualification at the preflight maximum; a calibration example above it
    # would silently exceed the budgeted time.
    heldout_max = max(
        constrained.max_scorer_calls(e["request"]) for e in decision.heldout_examples(PROTOCOL)
    )
    assert max(constrained.max_scorer_calls(e["request"]) for e in examples) <= heldout_max


def test_cache_qualification_only_ever_shows_the_model_calibration_requests(
    tmp_path: Path,
) -> None:
    backend = _Backend()
    _run(tmp_path / "checkpoint.jsonl", backend=backend, stop_after=1)
    assert backend.touched and set(backend.touched) <= CALIBRATION_USERS
    assert not set(backend.touched) & (PROTECTED_USERS | EXPOSED_USERS)


def test_no_protected_request_is_shown_before_qualification_has_passed(tmp_path: Path) -> None:
    backend = _Backend()
    _run(tmp_path / "checkpoint.jsonl", backend=backend, stop_after=3)
    first_protected = next(i for i, u in enumerate(backend.touched) if u in PROTECTED_USERS)
    assert all(u in CALIBRATION_USERS for u in backend.touched[:first_protected])
    assert first_protected > 0


def test_failed_qualification_never_exposes_any_protected_request(tmp_path: Path) -> None:
    backend = _Backend(reference_offset=0.01)
    assert _run(tmp_path / "checkpoint.jsonl", backend=backend)["status"] == "QUALIFICATION_FAILED"
    assert backend.touched and set(backend.touched) <= CALIBRATION_USERS
    resumed = _Backend()
    assert _run(tmp_path / "checkpoint.jsonl", backend=resumed)["status"] == "QUALIFICATION_FAILED"
    assert resumed.touched == [] and resumed.native_calls == 0


def test_a_work_list_without_leading_qualification_is_refused(tmp_path: Path) -> None:
    with pytest.raises(worker.CheckpointError, match="begin with cache qualification"):
        worker.run_worker(
            protocol=PROTOCOL, items=ITEMS[1:], checkpoint=tmp_path / "c.jsonl",
            backend=_Backend(), deadline=float("inf"), item_cost_bounds=COSTS,
        )  # fmt: skip


# ---- adversarial checkpoint and identity faults ---------------------------------------


def _rewrite(source: Path, destination: Path, mutate: Any, upto: int = 12) -> None:
    """Re-chain a checkpoint after ``mutate``: a forgery that passes every hash check."""
    head, lines = worker.GENESIS, []
    for seq, line in enumerate(source.read_bytes().split(b"\n")[:upto]):
        entry = json.loads(line)
        entry.pop("line_sha256")
        mutate(seq, entry)
        entry.update(seq=seq, prev_sha256=head)
        head = worker._line_hash(entry)
        lines.append(v3.canonical({**entry, "line_sha256": head}))
    destination.write_text("\n".join(lines) + "\n")


@pytest.mark.parametrize(
    ("seq", "key"),
    [
        (0, "model_revision"),  # the qualification itself ran on another revision
        (3, "model_revision"),
        (3, "model_id"),
        (4, "contract_profile_sha256"),
        (4, "protocol_sha256"),
    ],
)
def test_rechained_identity_drift_is_refused_before_any_new_item(
    tmp_path: Path, complete: Path, seq: int, key: str
) -> None:
    def drift(n: int, entry: dict[str, Any]) -> None:
        if n == seq:
            entry["record"][key] = "drifted"

    forged = tmp_path / "forged.jsonl"
    _rewrite(complete, forged, drift)
    assert len(worker.read_checkpoint(forged, ITEMS)["entries"]) == 12  # hashes are consistent
    backend = _Backend()
    before = forged.read_bytes()
    with pytest.raises(worker.CheckpointError, match=f"identity drift at .*: {key}"):
        _run(forged, backend=backend)
    assert backend.touched == [] and forged.read_bytes() == before


def test_a_backend_for_another_model_revision_is_refused(tmp_path: Path) -> None:
    drifted = _Backend()
    drifted.model_identity = {**PROTOCOL["candidate_model"], "revision": "0" * 40}

    with pytest.raises(worker.CheckpointError, match="backend model identity differs"):
        _run(tmp_path / "checkpoint.jsonl", backend=drifted)
    assert not (tmp_path / "checkpoint.jsonl").exists()


def test_a_duplicated_record_is_refused_not_skipped(tmp_path: Path, complete: Path) -> None:
    lines = complete.read_bytes().split(b"\n")[:12]
    duplicate = tmp_path / "duplicate.jsonl"
    duplicate.write_bytes(b"\n".join([*lines[:6], lines[5], *lines[6:]]) + b"\n")
    with pytest.raises(worker.CheckpointError, match="chain breaks at line 6"):
        worker.read_checkpoint(duplicate, ITEMS)
    with pytest.raises(worker.CheckpointError):
        _run(duplicate)


def test_a_newline_terminated_corrupt_tail_is_not_mistaken_for_a_torn_write(
    tmp_path: Path, complete: Path
) -> None:
    lines = complete.read_bytes().split(b"\n")[:8]
    path = tmp_path / "checkpoint.jsonl"
    path.write_bytes(b"\n".join([*lines, b'{"seq": 8, "garbage": true}']) + b"\n")
    with pytest.raises(worker.CheckpointError, match="chain breaks at line 8"):
        worker.read_checkpoint(path, ITEMS)
    before = path.read_bytes()
    with pytest.raises(worker.CheckpointError):
        _run(path)
    assert path.read_bytes() == before  # nothing was truncated, appended or repaired


def test_a_checkpoint_longer_than_the_work_list_is_refused(tmp_path: Path, complete: Path) -> None:
    with pytest.raises(worker.CheckpointError, match="not the preregistered next item"):
        worker.read_checkpoint(complete, ITEMS[:50])
