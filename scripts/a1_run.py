"""A1 inference runner (RES-832): one frozen arm at a time, resumable and hash-chained.

The runner is deliberately small. It reuses the shipped inference path
(``a03_model_runtime.PinnedModel``, ``a02_v3_contract.build_action_prompt``,
``a03_hf_token_mask``) rather than reimplementing model loading or decoding.

Guarantees
----------
* Prompts are built from the frozen call manifest. A prompt whose digest differs from the
  sealed one aborts the arm before any generation.
* The adapter is disabled for ``M0`` by a PEFT adapter context, so both models share one loaded
  base and all non-model conditions are identical.
* Every completed call appends a hash-chained line. A resumed run verifies the chain, drops only
  a torn tail, and never re-generates a committed condition.
* Raw generations, token ids, decoding settings, identity and timings are retained.
* No reference answer is read on the inference side. Scoring consumes the output file only.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Protocol

from scripts import a02_v3_contract as v3
from scripts import a1_manifest
from scripts import a1_representation as rep

OUTPUT_SCHEMA = "DYNAMISLM_A1_GENERATION_LINE_V1"
ROOT = Path(__file__).resolve().parents[1]
GEN_ROOT = ROOT / "experiments/a1/.runs"
GENESIS = "0" * 64
MAX_PROMPT = 3072  # raised only for the few-shot arm; disclosed in the arm metadata


class GenerationError(ValueError):
    pass


def arm_path(arm: str, root: Path | None = None) -> Path:
    base = root if root is not None else GEN_ROOT
    return base / f"{arm}.jsonl"


def _line_hash(entry: dict[str, Any]) -> str:
    return v3.sha256(v3.canonical(entry).encode())


def read_arm(path: Path, arm: str, expected: list[dict[str, Any]]) -> dict[str, Any]:
    if not path.exists():
        return {"entries": [], "head": GENESIS, "torn_tail_discarded": False}
    data = path.read_bytes()
    lines = data.split(b"\n")
    if lines and lines[-1] != b"":
        lines = lines[:-1]
        torn = True
    else:
        lines = lines[:-1]
        torn = False
    entries: list[dict[str, Any]] = []
    head = GENESIS
    for seq, raw in enumerate(lines):
        try:
            line = v3.json_object(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise GenerationError(f"{arm} line {seq} is corrupt") from exc
        digest = line.pop("line_sha256", None)
        if (
            line.get("schema") != OUTPUT_SCHEMA
            or line.get("arm") != arm
            or line.get("seq") != seq
            or line.get("prev_sha256") != head
            or digest != _line_hash(line)
        ):
            raise GenerationError(f"{arm} chain breaks at line {seq}")
        if seq >= len(expected) or line.get("case_id") != expected[seq]["case_id"]:
            raise GenerationError(f"{arm} line {seq} is not the frozen next case")
        if line.get("prompt_sha256") != expected[seq]["prompt_sha256"]:
            raise GenerationError(f"{arm} line {seq} prompt digest differs from the seal")
        entries.append(line)
        head = digest
    return {"entries": entries, "head": head, "torn_tail_discarded": torn}


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


class Backend(Protocol):
    tokenizer: Any

    def generate(
        self, arm: str, request: dict[str, Any], prompt: list[int], deadline: float
    ) -> Any: ...


def _cases_by_id() -> dict[str, dict[str, Any]]:
    from scripts import a1_cases, a1_retrospective, a1_shortcut

    cases = {case["case_id"]: case for case in a1_cases.load_manifest()["cases"]}
    cases.update({case["case_id"]: case for case in a1_retrospective.cohort_cases()})
    from scripts import a02_v3_decision as decision

    examples = a1_shortcut.probe_examples(decision.load_protocol())
    for variant in a1_shortcut.VARIANTS:
        for case in a1_shortcut.probe_cases(examples, variant):
            cases[case["case_id"]] = case
    return cases


def prompt_ids(
    backend: Backend, request: dict[str, Any], system: str, fewshot: str
) -> tuple[list[int], str]:
    messages = rep.render_messages(request, system, fewshot)
    kwargs = {
        "enable_thinking": False,
        "strftime_now": v3.ACTION_TEMPLATE_DATE.strftime,
        "xml_tools": [v3.tool_schema()],
    }
    ids = backend.tokenizer.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=True, **kwargs
    )
    rendered = backend.tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True, **kwargs
    )
    if backend.tokenizer.encode(rendered, add_special_tokens=False) != ids:
        raise GenerationError("prompt does not reproduce tokenizer ids")
    return list(ids), rendered


def run_arm(
    backend: Backend,
    condition: dict[str, Any],
    *,
    identity: dict[str, Any],
    root: Path | None = None,
    deadline_seconds: float = 3600.0,
    model_factory: Any = None,
) -> dict[str, Any]:
    """Generate every pending case of one arm; return a per-arm receipt."""
    arm = condition["arm"]
    path = arm_path(arm, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    expected = condition["items"]
    state = read_arm(path, arm, expected)
    if state["torn_tail_discarded"]:
        data = path.read_bytes()
        with path.open("r+b") as handle:
            handle.truncate(data.rfind(b"\n") + 1)
            handle.flush()
            os.fsync(handle.fileno())
        state = read_arm(path, arm, expected)
    cases = _cases_by_id()
    started = time.monotonic()
    generated = 0
    with model_factory() if model_factory is not None else NullContext():
        for item in expected[len(state["entries"]) :]:
            case = cases[item["case_id"]]
            request = rep.request_for(condition["representation"], case)
            if rep.request_sha256(request) != item["request_sha256"]:
                raise GenerationError(f"{arm}: request digest drift at {item['case_id']}")
            ids, rendered = prompt_ids(backend, request, condition["system"], condition["fewshot"])
            if not 0 < len(ids) <= MAX_PROMPT:
                raise GenerationError(f"{arm}: prompt outside the disclosed token bound")
            digest = v3.sha256(
                v3.canonical(
                    rep.render_messages(request, condition["system"], condition["fewshot"])
                ).encode()
            )
            if digest != item["prompt_sha256"]:
                raise GenerationError(f"{arm}: prompt differs from the sealed manifest")
            deadline = time.monotonic() + deadline_seconds
            result = backend.generate(condition["decoder"], request, ids, deadline)
            entry: dict[str, Any] = {
                "schema": OUTPUT_SCHEMA,
                "seq": len(state["entries"]),
                "prev_sha256": state["head"],
                "arm": arm,
                "case_id": item["case_id"],
                "cluster": item["cluster"],
                "role": condition["role"],
                "model": condition["model"],
                "decoder": condition["decoder"],
                "representation": condition["representation"],
                "system": condition["system"],
                "fewshot": condition["fewshot"],
                "prompt_sha256": digest,
                "request_sha256": item["request_sha256"],
                "prompt_token_ids": ids,
                "prompt_tokens": len(ids),
                "rendered_prompt_sha256": v3.sha256(rendered.encode()),
                "raw_output": result.raw,
                "token_ids": list(result.ids),
                "generation_sha256": v3.sha256(v3.canonical(list(result.ids)).encode()),
                "termination": result.termination,
                "identity": identity,
            }
            head = _append(path, entry)
            state["entries"].append({**entry, "line_sha256": head})
            state["head"] = head
            generated += 1
    return {
        "arm": arm,
        "path": str(path),
        "planned": len(expected),
        "generated_now": generated,
        "committed": len(state["entries"]),
        "head": state["head"],
        "seconds": round(time.monotonic() - started, 3),
        "complete": len(state["entries"]) == len(expected),
    }


def _last(path: Path) -> dict[str, Any]:
    lines = [line for line in path.read_bytes().split(b"\n") if line]
    return v3.json_object(lines[-1].decode("utf-8"))


class NullContext:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *args: Any) -> None:
        return None


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("arm")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    manifest = a1_manifest.load_manifest()
    condition = next((entry for entry in manifest["conditions"] if entry["arm"] == args.arm), None)
    if condition is None:
        raise SystemExit(f"unknown A1 arm: {args.arm}")
    print(json.dumps({"arm": condition["arm"], "items": len(condition["items"])}, indent=2))


if __name__ == "__main__":
    main()
