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


def _split(ids: Sequence[int]) -> tuple[str, str]:
    text = "".join(_REVERSE[i] for i in ids)
    prompt, _, action = text.rpartition(ASSISTANT)
    user = prompt.split("<user>", 1)[1]
    return TARGETS[user], action


class _Backend:
    """Fast deterministic fake: native emits gold or bare JSON, chosen by request content."""

    model_identity = PROTOCOL["candidate_model"]

    def __init__(self, *, reference_offset: float = 0.0) -> None:
        self.tokenizer = _Tokenizer()
        self.reference_offset = reference_offset
        self.native_calls = 0

    def generate_native(
        self, prompt_ids: Sequence[int], max_new_tokens: int
    ) -> tuple[list[int], str, bool]:
        target, _ = _split(list(prompt_ids))
        self.native_calls += 1
        framed = int(v3.sha256(target.encode())[:4], 16) % 2 == 0
        text = target if framed else target[len(v3.OPEN) : -len(v3.CLOSE)]
        return _chunk_ids(text), text, False

    def _scorer(self, offset: float) -> constrained.SequenceLogprob:
        def score_ids(ids: Sequence[int], start: int) -> float:
            target, action = _split(ids)
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
