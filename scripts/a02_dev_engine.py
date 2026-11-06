"""CPU-only V2 development intent gate and frozen A02 executor adapter."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from scripts import a02_dev_protocol, a02_engine


def execute_development_v2(
    case_id: str, raw: object, interaction_id: str, *, truncated: bool = False
) -> dict[str, Any]:
    cases = {
        case["case_id"]: case
        for case in json.loads(a02_engine.NEW_CASES_PATH.read_bytes())["cases"]
    }
    if case_id not in cases:
        raise ValueError("unknown frozen A02 case")
    request_sha = cases[case_id]["request_sha256"]
    action_payload = raw if isinstance(raw, str) else a02_engine.canonical(raw)
    action_sha = a02_engine.sha256(action_payload.encode("utf-8"))

    def guard(reason: str, *, valid: bool, parse_error: str | None = None) -> dict[str, Any]:
        event = a02_engine._event(
            case_id=case_id,
            interaction_id=interaction_id,
            request_sha256=request_sha,
            action_sha256=action_sha,
            origin="application_guard_refusal",
            outcome="REFUSED",
            reason_codes=[reason],
            operation_id=None,
            authorization_reference=None,
            metadata={
                "dispatch_count": 0,
                **({"parse_error": parse_error} if parse_error else {}),
            },
        )
        return {
            "case_id": case_id,
            "request_sha256": request_sha,
            "action_sha256": action_sha,
            "model_action_valid": valid,
            "model_intent_correct": False,
            "scientific_execution_count": 0,
            "authority_stages": [],
            "engine_result": None,
            "event": event,
        }

    if truncated:
        return guard("A02_MODEL_ACTION_TRUNCATED", valid=False)
    try:
        action = a02_dev_protocol.parse_intent(raw)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return guard("A02_MODEL_ACTION_INVALID", valid=False, parse_error=type(exc).__name__)
    if a02_engine.canonical(action) != a02_engine.canonical(
        a02_dev_protocol.expected_intent(case_id)
    ):
        return guard("A02_REQUEST_SEMANTICS_MISMATCH", valid=True)

    # The V2 proposal keeps both claim axes before the frozen authority path runs.
    replay = a02_engine.execute_new(
        case_id,
        a02_dev_protocol.legacy_action_text(action),
        interaction_id,
    )
    if replay.get("model_intent_correct") is not True:
        raise ValueError("V2 intent projection differs from the frozen A02 case adapter")
    replay_event = replay["event"]
    event = a02_engine._event(
        case_id=case_id,
        interaction_id=interaction_id,
        request_sha256=request_sha,
        action_sha256=action_sha,
        origin=replay_event["origin"],
        outcome=replay_event["outcome"],
        reason_codes=replay_event["reason_codes"],
        operation_id=replay_event.get("operation_id"),
        authorization_reference=replay_event.get("authorization_reference"),
        value=replay_event.get("value"),
        unit=replay_event.get("unit"),
        metadata=replay_event.get("metadata"),
    )
    replay["action_sha256"] = action_sha
    replay["event"] = event
    return replay


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true")
    args = parser.parse_args()
    if not args.serve:
        parser.error("the deterministic development executor is a JSON-lines service; use --serve")
    for line in sys.stdin:
        request = json.loads(line)
        try:
            if request.get("kind") != "development_v2":
                raise ValueError("unknown A02 development case kind")
            result = execute_development_v2(
                request["case_id"],
                request.get("raw_action"),
                request["interaction_id"],
                truncated=request.get("truncated") is True,
            )
        except Exception as exc:
            result = {
                "case_id": request.get("case_id"),
                "executor_error": type(exc).__name__,
                "error_message": str(exc),
                "scientific_execution_count": 0,
            }
        print(a02_engine.canonical(result), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
