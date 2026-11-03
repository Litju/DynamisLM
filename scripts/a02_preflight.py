"""Verify the frozen A0.2 prompts with the pinned CPU tokenizer; never loads model weights."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dynamislm.serialization import canonical_json
from scripts import a0_engine, a02_engine, a02_experiment, res403_tool_protocol

ROOT = Path(__file__).resolve().parents[1]
E_ROOT = Path("/mnt/e/DynamisLM-A0")
BASELINE_REPORT = (
    E_ROOT / "reports/a01/diagnostic/res541-a01-a0-diagnostic-20261028-041649508364-remote.json"
)
TOKENIZER_DIR = E_ROOT / "a01/tokenizer"
TEMPLATE_DATES = {
    "historical": datetime(2026, 10, 28, tzinfo=UTC),
    "a02": datetime(2026, 11, 3, tzinfo=UTC),
}
TOKENIZER_PINS = json.loads((ROOT / "experiments/a02/tokenizer-files-v1.json").read_text())["files"]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _date_function(value: datetime) -> Callable[[str], str]:
    return value.strftime


def _render(
    tokenizer: Any, messages: list[dict[str, str]], date: datetime
) -> tuple[list[int], str]:
    kwargs = {"enable_thinking": False, "strftime_now": _date_function(date)}
    token_ids = tokenizer.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=True, **kwargs
    )
    rendered = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True, **kwargs
    )
    if tokenizer.encode(rendered, add_special_tokens=False) != token_ids:
        raise ValueError("official Jinja rendering does not reproduce tokenizer IDs")
    return token_ids, rendered


def _action_content(action: dict[str, Any]) -> str:
    encoded = canonical_json({"name": "registered_science", "arguments": action})
    return (
        f"<tool_call>{encoded}</tool_call>"
        if action["kind"] == "request_analysis"
        else canonical_json(action)
    )


def _tool_event(case: dict[str, Any]) -> str:
    authority = case["authority"]
    event = {
        "origin": "application_guard_refusal"
        if authority["boundary"] == "COMPOSITE_OBJECTIVE_NOT_REPRESENTED_BY_ONE_QUALIFIED_ANALYSIS"
        else "trusted_executor_result",
        "outcome": authority["outcome"],
        "reason_codes": authority["reason_codes"],
        "value": authority.get("value"),
        "unit": authority.get("unit"),
        "claim_scope": "NUMERICAL_CHANGE_ONLY"
        if authority["outcome"] == "RESULT"
        else "NO_RESULT_AUTHORIZED",
    }
    return json.dumps(event, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _model_event(event: dict[str, Any]) -> str:
    payload = {
        "origin": event["origin"],
        "outcome": event["outcome"],
        "reason_codes": event["reason_codes"],
        "value": event["value"],
        "unit": event["unit"],
        "claim_scope": "NUMERICAL_CHANGE_ONLY"
        if event["outcome"] == "RESULT"
        else "NO_RESULT_AUTHORIZED",
    }
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _final_messages(
    *,
    user_text: str,
    action_text: str,
    event_text: str,
    origin: str,
) -> list[dict[str, str]]:
    request = res403_tool_protocol.UntrustedUserInputEvent(user_text)
    action = res403_tool_protocol.ModelActionProposalEvent(action_text)
    prefix = res403_tool_protocol.render_transcript(
        [
            res403_tool_protocol.SystemInstructionEvent(
                (ROOT / "experiments/a02/system-final-v1.txt").read_text().rstrip("\n")
            ),
            request,
            action,
        ]
    )
    if json.loads(event_text).get("origin") != origin:
        raise ValueError("tool event origin mismatch")
    return [*prefix, {"role": "tool", "content": event_text}]


def run(tokenizer_dir: Path = TOKENIZER_DIR, output: Path | None = None) -> dict[str, Any]:
    mount = subprocess.check_output(
        ["findmnt", "-n", "-o", "SOURCE", "--target", "/mnt/e"], text=True
    ).strip()
    if mount != "E:\\" or not Path("/mnt/e").is_mount():
        raise ValueError("Windows E: must be mounted at /mnt/e before A0.2 staging")
    tokenizer_dir = tokenizer_dir.resolve()
    if not tokenizer_dir.is_relative_to(E_ROOT) or not tokenizer_dir.is_dir():
        raise ValueError("pinned tokenizer must be read from /mnt/e/DynamisLM-A0")
    if any(not (tokenizer_dir / name).is_file() for name in TOKENIZER_PINS):
        raise ValueError("pinned four-file tokenizer snapshot required")
    assets = {name: sha256((tokenizer_dir / name).read_bytes()) for name in TOKENIZER_PINS}
    if assets != TOKENIZER_PINS:
        raise ValueError("tokenizer asset hashes differ from the reviewed A0.1 pins")
    from transformers import AutoTokenizer  # type: ignore[import-not-found]

    tokenizer = AutoTokenizer.from_pretrained(
        tokenizer_dir, local_files_only=True, trust_remote_code=False, use_fast=True
    )
    if sha256(tokenizer.chat_template.encode()) != TOKENIZER_PINS["chat_template.jinja"]:
        raise ValueError("loaded official SmolLM3 chat template differs from its pinned file")

    historical_doc = json.loads((ROOT / "experiments/a02/historical-inputs-v1.json").read_text())
    historical = historical_doc["cases"]
    baseline = json.loads(BASELINE_REPORT.read_text())
    baseline_by_id = {row["case_id"]: row for row in baseline["model_outputs"]["cases"]}
    if set(baseline_by_id) != {row["case_id"] for row in historical}:
        raise ValueError("historical report case set differs from the 16-case frozen manifest")
    old_system = (ROOT / "experiments/a01/system-prompt-v1.txt").read_text().rstrip("\n")
    historical_rows = []
    for row in historical:
        messages = [
            {"role": "system", "content": old_system},
            {"role": "user", "content": row["user_message"]},
        ]
        ids, rendered = _render(tokenizer, messages, TEMPLATE_DATES["historical"])
        recorded = baseline_by_id[row["case_id"]]
        if ids != recorded["prompt_token_ids"]:
            raise ValueError(f"A0.1 prompt token IDs changed for {row['case_id']}")
        if len(ids) > 1024:
            raise ValueError(
                f"historical prompt exceeds its fixed 1024-token limit: {row['case_id']}"
            )
        historical_rows.append(
            {
                "case_id": row["case_id"],
                "user_message_sha256": row["user_message_sha256"],
                "rendered_prompt": rendered,
                "rendered_prompt_sha256": sha256(rendered.encode()),
                "prompt_token_ids": ids,
                "prompt_token_ids_sha256": sha256(canonical_json(ids).encode()),
                "prompt_tokens": len(ids),
                "output_token_limit": 64,
                "historical_prompt_replay": "EXACT_A01_TOKEN_ID_MATCH",
            }
        )

    historical_final_rows = []
    historical_user_by_id = {row["case_id"]: row["user_message"] for row in historical}
    historical_cases = {case.case_id: case for case in a02_experiment.load_historical_cases()}
    history_margin = "x " * 64
    for case_id, case in historical_cases.items():
        context = a0_engine._build_context(case)
        expected_intent = a0_engine.oracle_intent(context)
        action_text = json.dumps(
            a0_engine._model_intent_wire(expected_intent), sort_keys=True, separators=(",", ":")
        )
        engine_row = a02_engine.execute_historical(case_id, action_text, "a02-preflight-" + case_id)
        final_messages = _final_messages(
            user_text=historical_user_by_id[case_id],
            action_text=action_text,
            event_text=_model_event(engine_row["event"]),
            origin=engine_row["event"]["origin"],
        )
        final_ids, final_rendered = _render(tokenizer, final_messages, TEMPLATE_DATES["a02"])
        margin_ids = len(tokenizer.encode(history_margin, add_special_tokens=False))
        if len(final_ids) + margin_ids > 1024:
            raise ValueError(
                f"historical final prompt exceeds its bound: {case_id}; "
                f"prompt={len(final_ids)} reserved_action={margin_ids}"
            )
        historical_final_rows.append(
            {
                "case_id": case_id,
                "rendered_prompt": final_rendered,
                "rendered_prompt_sha256": sha256(final_rendered.encode()),
                "prompt_token_ids": final_ids,
                "prompt_token_ids_sha256": sha256(canonical_json(final_ids).encode()),
                "prompt_tokens": len(final_ids),
                "reserved_action_margin_tokens": margin_ids,
                "final_output_token_limit": 64,
            }
        )

    action_system = (ROOT / "experiments/a02/system-action-v1.txt").read_text().rstrip("\n")
    new_cases = json.loads((ROOT / "experiments/a02/cases-v1.json").read_text())["cases"]
    new_rows = []
    final_rows = []
    margin = "x " * 128
    for case in new_cases:
        user_text = canonical_json(case["request"])
        user_message = res403_tool_protocol.render_transcript(
            [res403_tool_protocol.UntrustedUserInputEvent(user_text)]
        )[0]
        action_messages = [
            {"role": "system", "content": action_system},
            user_message,
        ]
        ids, rendered = _render(tokenizer, action_messages, TEMPLATE_DATES["a02"])
        action_raw = _action_content(case["expected_action"])
        action_tokens = tokenizer.encode(action_raw, add_special_tokens=False)
        if len(ids) > 1024 or len(action_tokens) + 1 > 128:
            raise ValueError(
                f"A02 action prompt/output exceeds the frozen limit: {case['case_id']}; "
                f"prompt={len(ids)} expected_action_tokens={len(action_tokens) + 1}"
            )
        new_rows.append(
            {
                "case_id": case["case_id"],
                "request_sha256": case["request_sha256"],
                "rendered_prompt": rendered,
                "rendered_prompt_sha256": sha256(rendered.encode()),
                "prompt_token_ids": ids,
                "prompt_token_ids_sha256": sha256(canonical_json(ids).encode()),
                "prompt_tokens": len(ids),
                "expected_action_token_count_including_eos": len(action_tokens) + 1,
                "action_output_token_limit": 128,
            }
        )
        action_event = _action_content(case["expected_action"])
        # The runtime checks the actual final prompt again after the model action.
        event = _tool_event(case)
        final_messages = _final_messages(
            user_text=a02_experiment.final_request_text(case["request"]),
            action_text=action_event,
            event_text=event,
            origin=(
                "application_guard_refusal"
                if case["category"] == "CONTRADICTORY"
                else "trusted_executor_result"
            ),
        )
        final_ids, final_rendered = _render(tokenizer, final_messages, TEMPLATE_DATES["a02"])
        margin_ids = len(tokenizer.encode(margin, add_special_tokens=False))
        if len(final_ids) + margin_ids > 1024:
            raise ValueError(
                f"A02 worst-case final prompt exceeds 1024 tokens: {case['case_id']}; "
                f"prompt={len(final_ids)} reserved_action={margin_ids}"
            )
        final_rows.append(
            {
                "case_id": case["case_id"],
                "rendered_prompt": final_rendered,
                "rendered_prompt_sha256": sha256(final_rendered.encode()),
                "prompt_token_ids": final_ids,
                "prompt_token_ids_sha256": sha256(canonical_json(final_ids).encode()),
                "prompt_tokens": len(final_ids),
                "reserved_action_margin_tokens": margin_ids,
                "final_output_token_limit": 64,
            }
        )

    if output is None:
        output = E_ROOT / "a02" / "preflight-v1.json"
    output = output.resolve()
    if not output.is_relative_to(E_ROOT):
        raise ValueError("preflight artifact must be written to Windows E:")
    output.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "schema": "RES541_A02_TOKENIZER_PREFLIGHT_V1",
        "status": "READY_FOR_OWNER_GATE",
        "tokenizer_revision": "a07cc9a04f16550a088caea529712d1d335b0ac1",
        "tokenizer_files": assets,
        "chat_template_sha256": sha256(tokenizer.chat_template.encode()),
        "template_dates": {
            key: value.strftime("%d %B %Y") for key, value in TEMPLATE_DATES.items()
        },
        "historical_cases": historical_rows,
        "historical_final_cases": historical_final_rows,
        "new_action_cases": new_rows,
        "new_final_cases": final_rows,
        "historical_count": len(historical_rows),
        "new_case_count": len(new_rows),
        "model_weights_loaded": False,
        "gpu_allocated": False,
    }
    if output.exists():
        existing = json.loads(output.read_text(encoding="utf-8"))
        if canonical_json(existing) != canonical_json(document):
            raise ValueError("existing A02 preflight differs; refusing to overwrite it")
        return {"path": str(output), "sha256": sha256(output.read_bytes()), "cases": 26}
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"path": str(output), "sha256": sha256(output.read_bytes()), "cases": 26}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tokenizer-dir", type=Path, default=TOKENIZER_DIR)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.tokenizer_dir, args.output), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
