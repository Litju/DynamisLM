"""Resumable V3 zero-shot worker with hash-chained evidence checkpoints (RES-541).

Runs the two preregistered zero-shot arms (native generation and grammar-constrained choice)
over a deterministic work list: every held-out example with both arms paired, then the ten
exposed development cases as diagnostics. The first work unit is the in-run qualification:
cached versus uncached option scores on the first three held-out examples.

Evidence is an append-only JSONL checkpoint. Each line commits to its predecessor's hash, is
flushed and fsynced before the next item starts, and is verified on resume. Only a torn final
line (an interrupted write) is discarded; any other inconsistency fails closed. Before each item
the worker checks that its worst-case cost fits the remaining deadline and otherwise stops at a
clean item boundary, so a session can end without losing committed evidence.

The model backend is an interface: the HF backend runs the pinned model on GPU in an
authorized session; tests run the same code with a tiny real Transformers model or a fake.
"""

from __future__ import annotations

import json
import math
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from scripts import a02_v3_constrained as constrained
from scripts import a02_v3_contract as v3
from scripts import a02_v3_decision as decision
from scripts import a02_v3_score as score
from scripts import a02_v3_synthetic as synthetic

CHECKPOINT_SCHEMA = "RES541_A02_V3_CHECKPOINT_LINE_V1"
EXPOSED_SCHEMA = "RES541_A02_V3_EXPOSED_RECORD_V1"
QUALIFICATION_SCHEMA = "RES541_A02_V3_CACHE_QUALIFICATION_V1"
GENESIS = "0" * 64
QUALIFICATION_EXAMPLES = 3
# Training-split indices used to qualify the cached decoder. They are never evaluated, so cache
# correctness is established before any protected held-out request is touched. Two have three
# observations, which is the largest option tree.
CALIBRATION_INDICES = (2, 5, 7)
QUALIFICATION_TOLERANCE_NATS = 1e-3
ARMS = decision.ZERO_SHOT_ARMS


class CheckpointError(ValueError):
    """The checkpoint is corrupt, forked or inconsistent with the preregistered work."""


@dataclass(frozen=True)
class WorkItem:
    key: str  # "HELDOUT:<seed>:<index>", "EXPOSED:<case_id>" or "QUALIFICATION"
    arm: str

    @property
    def id(self) -> str:
        return f"{self.key}|{self.arm}"


class WorkerBackend(Protocol):
    model_identity: dict[str, str]
    tokenizer: Any

    def generate_native(
        self, prompt_ids: Sequence[int], max_new_tokens: int
    ) -> tuple[list[int], str, bool]:
        """Greedy generation: (token ids, decoded text without special tokens, truncated)."""
        ...

    def cached_scorer(self) -> constrained.SequenceLogprob: ...

    def reference_scorer(self) -> constrained.SequenceLogprob: ...


def work_list_sha256(items: Sequence[WorkItem]) -> str:
    return v3.sha256(v3.canonical([item.id for item in items]).encode())


def calibration_examples(protocol: dict[str, Any]) -> list[dict[str, Any]]:
    """Non-held-out examples for cache qualification; disjoint from every protected example."""
    spec = protocol["data"]["training"]
    declared = protocol["data"]["calibration"]
    if (declared["split"], declared["seed"], declared["indices"]) != (
        spec["split"],
        spec["seed"],
        list(CALIBRATION_INDICES),
    ):
        raise CheckpointError("calibration examples differ from the preregistered selection")
    examples = [
        example
        for example in synthetic.generate(spec["split"], spec["seed"], max(CALIBRATION_INDICES) + 1)
        if example["index"] in CALIBRATION_INDICES
    ]
    protected = {decision.example_id(e) for e in decision.heldout_examples(protocol)}
    if len(examples) != QUALIFICATION_EXAMPLES or any(
        decision.example_id(e) in protected
        or e["split"] == protocol["data"]["heldout_evaluation"]["split"]
        for e in examples
    ):
        raise CheckpointError("calibration examples must be non-held-out")
    return examples


def work_items(protocol: dict[str, Any]) -> list[WorkItem]:
    items = [WorkItem("QUALIFICATION", "ZERO_SHOT_CONSTRAINED")]
    for example in decision.heldout_examples(protocol):
        items.extend(WorkItem(decision.example_id(example), arm) for arm in ARMS)
    for case_id in v3.load_profile()["case_ids"]:
        items.extend(WorkItem(f"EXPOSED:{case_id}", arm) for arm in ARMS)
    pinned = protocol["execution"]["work_list"]
    if len(items) != pinned["items"] or work_list_sha256(items) != pinned["sha256"]:
        raise CheckpointError("the work list differs from the preregistered ordered list")
    return items


# --------------------------------------------------------------------------- checkpoint


def _line_hash(entry: dict[str, Any]) -> str:
    return v3.sha256(v3.canonical(entry).encode())


def read_checkpoint(path: Path, items: Sequence[WorkItem]) -> dict[str, Any]:
    """Verify a checkpoint; return committed entries and whether a torn tail was dropped."""
    if not path.exists():
        return {"entries": [], "head": GENESIS, "torn_tail_discarded": False}
    data = path.read_bytes()
    lines = data.split(b"\n")
    torn = False
    if lines and lines[-1] != b"":
        # The last line was never newline-terminated: an interrupted append.
        torn = True
        lines = lines[:-1]
    else:
        lines = lines[:-1]
    expected = [item.id for item in items]
    entries: list[dict[str, Any]] = []
    head = GENESIS
    for seq, raw in enumerate(lines):
        try:
            line = v3.json_object(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise CheckpointError(f"checkpoint line {seq} is corrupt") from exc
        digest = line.pop("line_sha256", None)
        if (
            line.get("schema") != CHECKPOINT_SCHEMA
            or line.get("seq") != seq
            or line.get("prev_sha256") != head
            or digest != _line_hash(line)
        ):
            raise CheckpointError(f"checkpoint chain breaks at line {seq}")
        if seq >= len(expected) or line.get("item") != expected[seq]:
            raise CheckpointError(f"checkpoint line {seq} is not the preregistered next item")
        entries.append(line)
        head = digest
    return {"entries": entries, "head": head, "torn_tail_discarded": torn}


def check_identity(entries: Sequence[dict[str, Any]], protocol: dict[str, Any]) -> None:
    """Every committed record must come from the preregistered model, profile and protocol."""
    model = protocol["candidate_model"]
    for entry in entries:
        record = entry["record"]
        if record.get("schema") == QUALIFICATION_SCHEMA:
            expected = {"model_id": model["id"], "model_revision": model["revision"]}
        else:
            expected = {
                "model_id": model["id"],
                "model_revision": model["revision"],
                "contract_profile_sha256": protocol["contract_profile_sha256"],
                "protocol_sha256": decision.protocol_sha256(),
            }
        for key, value in expected.items():
            if record.get(key) != value:
                raise CheckpointError(f"checkpoint identity drift at {entry['item']}: {key}")


def _append(path: Path, entry: dict[str, Any]) -> str:
    digest = _line_hash(entry)
    data = (v3.canonical({**entry, "line_sha256": digest}) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    return digest


def _truncate_torn_tail(path: Path) -> None:
    data = path.read_bytes()
    keep = data[: data.rfind(b"\n") + 1]
    with path.open("r+b") as handle:
        handle.truncate(len(keep))
        handle.flush()
        os.fsync(handle.fileno())


# --------------------------------------------------------------------------- execution


def _sources(protocol: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Every work key's source (held-out example or exposed case), built once per run."""
    sources = {decision.example_id(e): e for e in decision.heldout_examples(protocol)}
    sources.update({f"EXPOSED:{cid}": case for cid, case in score._cases().items()})
    return sources


def _run_arm(
    backend: WorkerBackend, arm: str, request: dict[str, Any], profile: dict[str, Any]
) -> dict[str, Any]:
    prompt = v3.build_action_prompt(backend.tokenizer, request)
    if prompt["prompt_tokens"] > profile["decoding"]["action_max_prompt_tokens"]:
        raise ValueError("V3 prompt exceeds the profile prompt bound")
    started = time.monotonic()
    if decision.ARM_DECODER[arm] == "native":
        ids, text, truncated = backend.generate_native(
            prompt["prompt_token_ids"], profile["decoding"]["action_max_new_tokens"]
        )
        extra: dict[str, Any] = {}
    else:
        result = constrained.decode(
            request=request,
            prompt_ids=prompt["prompt_token_ids"],
            encode=lambda t: list(backend.tokenizer.encode(t, add_special_tokens=False)),
            chooser=constrained.model_chooser(backend.cached_scorer()),
        )
        ids, text, truncated = result["token_ids"], result["text"], False
        extra = {"choices": result["choices"], "scorer_calls": result["scorer_calls"]}
    return {
        "raw_output": text,
        "truncated": truncated,
        "generated_token_ids_sha256": v3.sha256(v3.canonical(ids).encode()),
        "rendered_prompt_sha256": prompt["rendered_prompt_sha256"],
        "seconds": round(time.monotonic() - started, 3),
        **extra,
    }


def qualify_cache(backend: WorkerBackend, protocol: dict[str, Any]) -> dict[str, Any]:
    """Score every option with cached and uncached bindings on non-held-out calibration examples."""
    rows = []
    for example in calibration_examples(protocol):
        request = example["request"]
        prompt = v3.build_action_prompt(backend.tokenizer, request)

        def encode(text: str) -> list[int]:
            return list(backend.tokenizer.encode(text, add_special_tokens=False))

        runs = {}
        for name, scorer in (
            ("cached", backend.cached_scorer()),
            ("uncached", backend.reference_scorer()),
        ):
            runs[name] = constrained.decode(
                request=request,
                prompt_ids=prompt["prompt_token_ids"],
                encode=encode,
                chooser=constrained.model_chooser(scorer),
            )
        cached = [v for c in runs["cached"]["choices"] for v in c["scores"]]
        uncached = [v for c in runs["uncached"]["choices"] for v in c["scores"]]
        diff = max((abs(a - b) for a, b in zip(cached, uncached, strict=True)), default=0.0)
        rows.append(
            {
                "example_id": decision.example_id(example),
                "max_abs_score_difference": diff,
                "same_action": runs["cached"]["action"] == runs["uncached"]["action"],
                "options_scored": len(cached),
            }
        )
    passed = all(
        r["same_action"] and r["max_abs_score_difference"] <= QUALIFICATION_TOLERANCE_NATS
        for r in rows
    )
    return {
        "schema": QUALIFICATION_SCHEMA,
        "tolerance_nats": QUALIFICATION_TOLERANCE_NATS,
        "calibration": "non-held-out training-split examples; no protected request is touched",
        "model_id": backend.model_identity["id"],
        "model_revision": backend.model_identity["revision"],
        "examples": rows,
        "passed": passed,
    }


def _record_for(
    item: WorkItem,
    protocol: dict[str, Any],
    backend: WorkerBackend,
    profile: dict[str, Any],
    sources: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    source = sources[item.key]
    request = source["request"]
    output = _run_arm(backend, item.arm, request, profile)
    if item.key.startswith("EXPOSED:"):
        return {
            "schema": EXPOSED_SCHEMA,
            "case_id": item.key.removeprefix("EXPOSED:"),
            "arm": item.arm,
            "decoder": decision.ARM_DECODER[item.arm],
            "request_sha256": decision.request_sha256(request),
            "raw_output_sha256": v3.sha256(output["raw_output"].encode("utf-8", "surrogatepass")),
            "model_id": backend.model_identity["id"],
            "model_revision": backend.model_identity["revision"],
            "contract_profile_sha256": protocol["contract_profile_sha256"],
            "protocol_sha256": decision.protocol_sha256(),
            **output,
        }
    record = decision.make_record(
        protocol=protocol,
        arm=item.arm,
        example=source,
        raw_output=output["raw_output"],
        truncated=output["truncated"],
        model=backend.model_identity,
    )
    return {**record, **{k: v for k, v in output.items() if k not in record}}


def run_worker(
    *,
    protocol: dict[str, Any],
    items: Sequence[WorkItem],
    checkpoint: Path,
    backend: WorkerBackend,
    deadline: float,
    item_cost_bounds: dict[str, float],
    clock: Callable[[], float] = time.monotonic,
    stop_after: int | None = None,
) -> dict[str, Any]:
    """Advance the checkpoint through ``items`` until done, the deadline, or ``stop_after``."""
    if not items or items[0].key != "QUALIFICATION":
        raise CheckpointError("the work list must begin with cache qualification")
    if backend.model_identity != protocol["candidate_model"]:
        raise CheckpointError("backend model identity differs from the preregistered model")
    profile = v3.load_profile()
    sources = _sources(protocol)
    state = read_checkpoint(checkpoint, items)
    check_identity(state["entries"], protocol)
    if state["torn_tail_discarded"]:
        _truncate_torn_tail(checkpoint)
    entries, head = state["entries"], state["head"]
    if entries and entries[0]["item"] == items[0].id and not entries[0]["record"]["passed"]:
        return {"status": "QUALIFICATION_FAILED", "committed": len(entries), "head": head}
    done = 0
    for seq in range(len(entries), len(items)):
        item = items[seq]
        bound = item_cost_bounds[item.arm if item.key != "QUALIFICATION" else "QUALIFICATION"]
        if not math.isfinite(bound) or clock() + bound > deadline:
            return {"status": "PAUSED_AT_DEADLINE", "committed": seq, "head": head}
        if stop_after is not None and done >= stop_after:
            return {"status": "STOPPED", "committed": seq, "head": head}
        if item.key == "QUALIFICATION":
            record = qualify_cache(backend, protocol)
        else:
            record = _record_for(item, protocol, backend, profile, sources)
        entry = {
            "schema": CHECKPOINT_SCHEMA,
            "seq": seq,
            "prev_sha256": head,
            "item": item.id,
            "record": record,
        }
        head = _append(checkpoint, entry)
        done += 1
        if item.key == "QUALIFICATION" and not record["passed"]:
            return {"status": "QUALIFICATION_FAILED", "committed": seq + 1, "head": head}
    return {"status": "COMPLETE", "committed": len(items), "head": head}


# --------------------------------------------------------------------------- CPU scoring


def score_checkpoint(protocol: dict[str, Any], checkpoint: Path) -> dict[str, Any]:
    """Complete CPU scoring of a finished checkpoint: decision rule plus exposed diagnostics."""
    items = work_items(protocol)
    state = read_checkpoint(checkpoint, items)
    if state["torn_tail_discarded"] or len(state["entries"]) != len(items):
        raise CheckpointError("checkpoint is incomplete; scoring requires every item")
    records = {
        item.id: entry["record"] for item, entry in zip(items, state["entries"], strict=True)
    }
    qualification = records[items[0].id]
    if not qualification["passed"]:
        raise CheckpointError("cache qualification failed; no arm result counts")
    evidence = {
        arm: [records[i.id] for i in items if i.arm == arm and i.key.startswith("HELDOUT:")]
        for arm in ARMS
    }
    exposed: dict[str, list[dict[str, Any]]] = {arm: [] for arm in ARMS}
    for item in items:
        if not item.key.startswith("EXPOSED:"):
            continue
        record = records[item.id]
        raw = record["raw_output"]
        if record["raw_output_sha256"] != v3.sha256(raw.encode("utf-8", "surrogatepass")):
            raise CheckpointError(f"exposed raw output hash differs: {item.id}")
        exposed[item.arm].append(
            score.score_case(record["case_id"], raw, action_truncated=bool(record["truncated"]))
        )
    return {
        "checkpoint_head": state["head"],
        "qualification": qualification,
        "decision": decision.decide(evidence, protocol),
        "exposed_development_diagnostics": {
            arm: score.aggregate(rows) for arm, rows in exposed.items()
        },
    }


# --------------------------------------------------------------------------- HF backend


class HFWorkerBackend:
    """Pinned-model backend: greedy native generation and cached/uncached option scoring."""

    def __init__(self, model: Any, tokenizer: Any, identity: dict[str, str]):
        self.model = model
        self.tokenizer = tokenizer
        self.model_identity = identity

    def generate_native(
        self, prompt_ids: Sequence[int], max_new_tokens: int
    ) -> tuple[list[int], str, bool]:
        import torch  # type: ignore[import-not-found]

        tensor = torch.tensor([list(prompt_ids)], device=self.model.device)
        with torch.inference_mode():
            output = self.model.generate(
                tensor,
                attention_mask=torch.ones_like(tensor),
                max_new_tokens=max_new_tokens,
                do_sample=False,
                num_beams=1,
                pad_token_id=self.tokenizer.pad_token_id,
            )
        ids = [int(t) for t in output[0, len(prompt_ids) :].tolist()]
        eos = self.tokenizer.eos_token_id
        truncated = len(ids) >= max_new_tokens and (not ids or ids[-1] != eos)
        text = self.tokenizer.decode(ids, skip_special_tokens=True)
        return ids, text, truncated

    def cached_scorer(self) -> constrained.SequenceLogprob:
        return constrained.CachedSequenceLogprob(constrained.HFIncrementalBackend(self.model))

    def reference_scorer(self) -> constrained.SequenceLogprob:
        return constrained.hf_sequence_logprob(self.model)


def main() -> int:  # pragma: no cover - remote entry point in an authorized session
    import argparse

    from transformers import AutoTokenizer  # type: ignore[import-not-found]

    from scripts.a02_v3_precision import PrecisionAudit, load_model

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--precision", choices=("float16", "float32"), default="float16")
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--seconds", type=float, required=True)
    parser.add_argument("--cost-bounds", type=str, required=True)
    args = parser.parse_args()
    deadline = time.monotonic() + args.seconds
    protocol = decision.load_protocol()
    tokenizer = AutoTokenizer.from_pretrained(str(args.snapshot), local_files_only=True)
    model = load_model(args.snapshot, args.precision)
    audit = PrecisionAudit(model, args.precision)
    backend = HFWorkerBackend(model, tokenizer, protocol["candidate_model"])
    status = run_worker(
        protocol=protocol,
        items=work_items(protocol),
        checkpoint=args.checkpoint,
        backend=backend,
        deadline=deadline,
        item_cost_bounds=json.loads(args.cost_bounds),
    )
    status["precision_audit"] = audit.report()
    audit.close()
    print(json.dumps(status, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
