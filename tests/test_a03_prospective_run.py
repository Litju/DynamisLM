from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from scripts import a02_v3_constrained as c0
from scripts import a02_v3_contract as v3
from scripts import a03_prospective_run as runner
from scripts import a03_scientific_admission as admission
from scripts.a03_d0_runtime import EOS
from scripts.a03_token_decoder import TokenMask, Vocabulary

from dynamislm.serialization import canonical_json

ABSTAIN: dict[str, Any] = {
    "analysis_class": "NONE",
    "observation_ids": [],
    "operation": "NONE",
    "target_claims": {"measurement": [], "relationship": []},
}


def as_jsonl(*rows: dict[str, Any]) -> bytes:
    return "".join(v3.canonical(row) + "\n" for row in rows).encode()


def blinded_request(
    item: str, bound: admission.BoundRequest, observations: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "item_id": item,
        "question": bound.question,
        "observations": observations,
        "requested_claims": bound.model_request()["requested_claims"],
    }


def source_row(item: str, bound: admission.BoundRequest) -> dict[str, Any]:
    return {"item_id": item, "bound": canonical_json(bound)}


def action_text(action: dict[str, Any], request: dict[str, Any]) -> str:
    return str(
        c0.decode(
            request=request,
            prompt_ids=[],
            encode=lambda text: list(text.encode()),
            chooser=c0.target_chooser(action),
        )["text"]
    )


class Scripted:
    def __init__(self, outputs: dict[tuple[str, str], str]):
        self.outputs = outputs
        self.pieces = {index: raw for index, raw in enumerate(sorted(set(outputs.values())), 300)}
        self.piece_ids = {raw: index for index, raw in self.pieces.items()}
        self.mask = TokenMask(Vocabulary({i: raw.encode() for i, raw in self.pieces.items()}, EOS))
        self.tokenizer = self
        self.calls: list[tuple[str, str, tuple[int, ...]]] = []

    def encode(self, raw: str, *, add_special_tokens: bool) -> list[int]:
        assert not add_special_tokens
        return [self.piece_ids[raw]] if raw in self.piece_ids else list(raw.encode())

    def decode(self, ids: list[int], *, skip_special_tokens: bool) -> str:
        assert skip_special_tokens
        return "".join(self.pieces[token] for token in ids if token != EOS)

    def apply_chat_template(
        self, messages: list[dict[str, str]], *, tokenize: bool, **_: Any
    ) -> str | list[int]:
        rendered = messages[1]["content"]
        return self.encode(rendered, add_special_tokens=False) if tokenize else rendered

    def generate(
        self, arm: str, request: dict[str, Any], prompt: list[int], deadline: float
    ) -> runner.Generation:
        self.calls.append((request["question"], arm, tuple(prompt)))
        raw = self.outputs[request["question"], arm]
        ids = self.encode(raw, add_special_tokens=False)
        return (
            runner.Generation(ids, raw, "C0_GRAMMAR_COMPLETE")
            if arm == "C0"
            else (runner.Generation([*ids, EOS], raw, "MODEL_EOS"))
        )


def test_scripted_run_prefix_and_exact_inputs(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    bound = admission.BoundRequest("Synthetic RES-746 runner fixture without evidence", None, ())
    request = blinded_request("dev-1", bound, [])
    requests, sources = as_jsonl(request), as_jsonl(source_row("dev-1", bound))
    manifest = runner.run_manifest(runner.DEV, requests, sources)
    raw = action_text(ABSTAIN, bound.model_request())
    backend = Scripted({(bound.question, arm): raw for arm in runner.ARMS})
    with pytest.raises(ValueError, match="differ"):
        runner.run(manifest, requests + b" ", sources, tmp_path, backend, seconds=1)
    partial = runner.run(manifest, requests, sources, tmp_path, backend, seconds=1e-12)
    assert partial["status"] == "INCOMPLETE"
    assert not (tmp_path / "output-commit.json").exists()
    with pytest.raises(ValueError, match="prefix digest"):
        runner.run(manifest, requests, sources, tmp_path, backend, seconds=1)
    result = runner.run(
        manifest,
        requests,
        sources,
        tmp_path,
        backend,
        seconds=10,
        resume_sha256=partial["prefix_sha256"],
    )
    assert result["status"] == "COMMITTED"
    items, work = runner.verify_run(manifest, requests, sources)
    state, _ = runner.verify_output_records(
        tmp_path / "outputs.jsonl",
        manifest,
        items,
        work,
        backend,
        backend.mask,
    )
    rows = state["entries"]
    assert [row["item"] for row in rows] == [item.id for item in work]
    assert [arm for _, arm, _ in backend.calls] == [item.arm for item in work]
    assert len({ids for _, _, ids in backend.calls}) == 1
    assert all(row["record"]["diagnostics"]["strict_syntax"] for row in rows)
    assert all(
        row["record"]["diagnostics"]["mask_accepted"] for row in rows if "|C0" not in row["item"]
    )
    with pytest.raises(ValueError, match="immutable"):
        runner.run(manifest, requests, sources, tmp_path, backend, seconds=1)


def test_runner_rejects_gold_fields_and_torn_evidence(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    bound = admission.BoundRequest("Synthetic RES-746 torn-run fixture", None, ())
    request = blinded_request("dev-1", bound, [])
    requests, sources = as_jsonl(request), as_jsonl(source_row("dev-1", bound))
    with pytest.raises(ValueError, match="expected fields"):
        runner.load_items(as_jsonl({**request, "judgment": {}}), sources)
    manifest = runner.run_manifest(runner.DEV, requests, sources)
    backend = Scripted({})
    checkpoint = tmp_path / "outputs.jsonl"
    checkpoint.write_bytes(b'{"seq":')
    checkpoint.chmod(0o600)
    with pytest.raises(ValueError, match="torn checkpoint"):
        runner.run(
            manifest,
            requests,
            sources,
            tmp_path,
            backend,
            seconds=1,
            resume_sha256=v3.sha256(checkpoint.read_bytes()),
        )
    assert checkpoint.read_bytes() == b'{"seq":'
    assert not backend.calls


def test_fixed_real_model_workload_cannot_enter_the_prospective_denominator() -> None:
    from scripts import a03_real_model_qualification as qualification

    requests, sources = qualification.inputs()
    items = runner.load_items(requests, sources, mode=runner.QUALIFICATION)
    assert len(runner.work_items(items)) == 6
    assert len(items[0].bound.entries) == 2
    assert items[1].ids == ["observation-1"] and not items[1].bound.entries
    for request, source in zip(runner.jsonl(requests), runner.jsonl(sources), strict=True):
        with pytest.raises(ValueError, match="exposed A0.2 or development"):
            runner.load_items(as_jsonl(request), as_jsonl(source), mode=runner.PROSPECTIVE)
    assert set(qualification.authority_controls(items[0].bound)) == {
        "RES70_UNSUPPORTED_CAUSAL_CLAIM",
        "RES70_UNSUPPORTED_CLAIM_ESCALATION",
    }
