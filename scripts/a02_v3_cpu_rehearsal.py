"""Explicit offline pre-generation rehearsal; never produces model evidence."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from scripts import a02_v3_contract as v3
from scripts import a02_v3_decision as decision
from scripts import a02_v3_worker as worker


class GenerationBoundaryError(Exception):
    """CPU execution reached the first weight-dependent operation."""


class CPUBackend:
    def __init__(self, tokenizer: Any, identity: dict[str, str]) -> None:
        self.tokenizer = tokenizer
        self.model_identity = identity

    def generate_native(
        self, prompt_ids: Sequence[int], max_new_tokens: int
    ) -> tuple[list[int], str, bool]:
        raise GenerationBoundaryError

    def cached_scorer(self) -> Any:
        return self.score

    def reference_scorer(self) -> Any:
        return self.score

    def score(self, ids: Sequence[int], prefix: int) -> float:
        raise GenerationBoundaryError


def rehearse(tokenizer_path: Path, checkpoint: Path) -> dict[str, Any]:
    profile = v3.load_profile()
    for name, digest in profile["tokenizer"]["files"].items():
        if v3.sha256((tokenizer_path / name).read_bytes()) != digest:
            raise ValueError("offline pinned tokenizer identity differs")
    from transformers import AutoTokenizer  # type: ignore[import-not-found]

    tokenizer = AutoTokenizer.from_pretrained(
        tokenizer_path, local_files_only=True, trust_remote_code=False
    )
    protocol = decision.load_protocol()
    items = worker.work_items(protocol)
    sources = worker._sources(protocol)
    backend = CPUBackend(tokenizer, protocol["candidate_model"])
    counts: Counter[str] = Counter()
    maximum = 0
    for item in items:
        requests = (
            [example["request"] for example in worker.calibration_examples(protocol)]
            if item.key == "QUALIFICATION"
            else [sources[item.key]["request"]]
        )
        for request in requests:
            prompt = v3.build_action_prompt(tokenizer, request)
            maximum = max(maximum, prompt["prompt_tokens"])
            if prompt["prompt_tokens"] > profile["decoding"]["action_max_prompt_tokens"]:
                raise ValueError("rehearsal prompt exceeds frozen token budget")
            try:
                worker._run_arm(backend, item.arm, request, profile)
            except GenerationBoundaryError:
                pass
            else:
                raise AssertionError("rehearsal did not reach generation boundary")
        counts["QUALIFICATION" if item.key == "QUALIFICATION" else item.arm] += 1
    if len(items) != 581:
        raise ValueError("frozen workload count differs")
    record = {"schema": "RES541_CPU_REHEARSAL_ONLY_V1", "synthetic": True}
    worker._append(
        checkpoint,
        {
            "schema": worker.CHECKPOINT_SCHEMA,
            "seq": 0,
            "prev_sha256": worker.GENESIS,
            "item": items[0].id,
            "record": record,
        },
    )
    state = worker.read_checkpoint(checkpoint, items)
    if state["entries"][0]["record"] != record:
        raise AssertionError("synthetic checkpoint recovery differs")
    try:
        worker.check_identity(state["entries"], protocol)
    except worker.CheckpointError:
        pass
    else:
        raise AssertionError("synthetic checkpoint accepted as model evidence")
    return {
        "items": len(items),
        "distribution": dict(counts),
        "max_prompt_tokens": maximum,
        "checkpoint_recovered": True,
        "actual_model_evaluations": 0,
    }
