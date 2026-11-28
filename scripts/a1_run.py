"""A1 inference runner (RES-832): one frozen arm at a time, resumable and hash-chained.

The runner is deliberately small. It reuses the shipped inference path
(``a03_model_core.generate``, ``a03_hf_token_mask.hf_prefix_mask``) rather than reimplementing
model loading or decoding.

Two input modes
---------------
``payload``  the transported work order carries the exact model-visible request and the exact
             rendered chat messages for every frozen call. The runner tokenizes those messages
             and refuses any item whose request digest or message digest differs from the
             manifest. This is how a remote T4 executes without the authored case cohort or gold.
``local``    the caller supplies no work order, so requests are rendered from the frozen cases
             on this machine. Used only by the CPU rehearsal and the contract tests.

Guarantees
----------
* A prompt whose digest differs from the sealed one aborts the arm before any generation.
* Every completed call appends a hash-chained line; resumption verifies the chain, drops only a
  torn tail, and never re-generates a committed call.
* The generation deadline is the cumulative session deadline, not a per-call reset. Teardown and
  evidence packaging are reserved by the caller, so a call can never run past the session budget.
* Raw generations, token ids, decoding settings, identity and timings are retained.
* No reference answer is read on the inference side. Scoring consumes the output file only.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Protocol

from scripts import a02_v3_contract as v3
from scripts import a1_chain
from scripts import a1_representation as rep

ROOT = Path(__file__).resolve().parents[1]
GEN_ROOT = ROOT / "experiments/a1/.runs"
GENESIS = a1_chain.GENESIS
OUTPUT_SCHEMA = a1_chain.OUTPUT_SCHEMA
MAX_PROMPT = 4096  # disclosed A1 bound; 2,689 is the longest frozen few-shot prompt
MIN_CALL_SECONDS = 30.0  # a call started with less than this is not started at all


class GenerationError(ValueError):
    pass


def arm_path(arm: str, root: Path | None = None) -> Path:
    return a1_chain.arm_path(arm, root if root is not None else GEN_ROOT)


def read_arm(path: Path, arm: str, expected: list[dict[str, Any]]) -> dict[str, Any]:
    return a1_chain.read_arm(path, arm, expected)


class Backend(Protocol):
    tokenizer: Any

    def generate(
        self, arm: str, request: dict[str, Any], prompt: list[int], deadline: float
    ) -> Any: ...


def _local_cases() -> dict[str, dict[str, Any]]:
    """Local-only case inventory. A payload run never reaches this function."""
    from scripts import a02_v3_decision as decision
    from scripts import a1_cases, a1_shortcut

    cases = {case["case_id"]: case for case in a1_cases.load_manifest()["cases"]}
    examples = a1_shortcut.probe_examples(decision.load_protocol())
    for variant in a1_shortcut.VARIANTS:
        for case in a1_shortcut.probe_cases(examples, variant):
            cases[case["case_id"]] = case
    return cases


class TokenizingBackend(Protocol):
    tokenizer: Any


def prompt_ids(backend: TokenizingBackend, messages: list[dict[str, str]]) -> tuple[list[int], str]:
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


def _item_inputs(
    item: dict[str, Any], condition: dict[str, Any], work: dict[str, Any] | None
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """The exact request and messages for one frozen call, verified against the manifest."""
    if work is not None:
        entry = work.get(item["case_id"])
        if entry is None:
            raise GenerationError(
                f"{condition['arm']}: {item['case_id']} is absent from the work order"
            )
        request = entry["request"]
        messages = entry["messages"]
        if rep.request_sha256(request) != item["request_sha256"]:
            raise GenerationError(f"{condition['arm']}: request digest drift at {item['case_id']}")
        if v3.sha256(v3.canonical(messages).encode()) != item["prompt_sha256"]:
            raise GenerationError(f"{condition['arm']}: prompt differs from the sealed manifest")
        return request, messages
    if condition.get("role") == "SMOKE":
        raise GenerationError("A1 smoke conditions require their transported messages")

    case = _local_cases()[item["case_id"]]
    request = rep.request_for(condition["representation"], case)
    if rep.request_sha256(request) != item["request_sha256"]:
        raise GenerationError(f"{condition['arm']}: request digest drift at {item['case_id']}")
    messages = rep.render_messages(request, condition["system"], condition["fewshot"])
    if v3.sha256(v3.canonical(messages).encode()) != item["prompt_sha256"]:
        raise GenerationError(f"{condition['arm']}: prompt differs from the sealed manifest")
    return request, messages


def run_arm(
    backend: Backend,
    condition: dict[str, Any],
    *,
    identity: dict[str, Any],
    root: Path | None = None,
    deadline_seconds: float = 3600.0,
    work: dict[str, Any] | None = None,
    session_deadline: float | None = None,
    model_factory: Any = None,
) -> dict[str, Any]:
    """Generate every pending case of one arm; return a per-arm receipt.

    ``session_deadline`` is an absolute ``time.monotonic()`` value for the whole session. When it
    is supplied, no call starts unless at least ``MIN_CALL_SECONDS`` remain, so evidence
    packaging and teardown are never starved. ``deadline_seconds`` remains the per-arm bound used
    by the local rehearsal.
    """
    arm = condition["arm"]
    path = arm_path(arm, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    expected = condition["items"]
    state = a1_chain.read_arm(path, arm, expected)
    if state["torn_tail_discarded"]:
        a1_chain.truncate_torn_tail(path)
        state = a1_chain.read_arm(path, arm, expected)
    deadline = (
        session_deadline if session_deadline is not None else (time.monotonic() + deadline_seconds)
    )
    # A session deadline reserves teardown and packaging time, so a call is not started unless a
    # minimum slice remains. A per-arm deadline (local rehearsal, contract tests) has no such
    # reserve and is governed only by its own bound.
    reserve = MIN_CALL_SECONDS if session_deadline is not None else 0.0
    started = time.monotonic()
    generated = 0
    stopped_early = False
    with model_factory() if model_factory is not None else _null_context():
        for item in expected[len(state["entries"]) :]:
            remaining = deadline - time.monotonic()
            if remaining <= reserve:
                stopped_early = True
                break
            request, messages = _item_inputs(item, condition, work)
            ids, rendered = prompt_ids(backend, messages)
            if not 0 < len(ids) <= MAX_PROMPT:
                raise GenerationError(f"{arm}: prompt outside the disclosed token bound")
            digest = v3.sha256(v3.canonical(messages).encode())
            if digest != item["prompt_sha256"]:
                raise GenerationError(f"{arm}: prompt differs from the sealed manifest")
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
            head = a1_chain.append(path, entry)
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
        "stopped_early": stopped_early,
        "complete": len(state["entries"]) == len(expected),
    }


def _null_context() -> Any:
    class _Null:
        def __enter__(self) -> None:
            return None

        def __exit__(self, *args: Any) -> None:
            return None

    return _Null()


def main() -> None:
    import argparse

    from scripts import a1_manifest

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("arm")
    args = parser.parse_args()
    manifest = a1_manifest.load_manifest()
    condition = next((entry for entry in manifest["conditions"] if entry["arm"] == args.arm), None)
    if condition is None:
        raise SystemExit(f"unknown A1 arm: {args.arm}")
    print(
        __import__("json").dumps(
            {"arm": condition["arm"], "items": len(condition["items"])}, indent=2
        )
    )


if __name__ == "__main__":
    main()
