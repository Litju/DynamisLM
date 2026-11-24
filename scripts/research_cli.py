"""Run the DynamisLM synthetic research CLI."""

from __future__ import annotations

import argparse
import json
import platform
import sys
from importlib.metadata import version
from pathlib import Path

import dynamislm as d
from dynamislm.longitudinal.statistics import RES69_ABSOLUTE_CHANGE_OPERATION
from dynamislm.training_data.synthetic_science import make_support
from scripts import a02_v3_contract as v3
from scripts.a03_scientific_admission import BoundRequest, submit_scientific_action_v3
from scripts.a03_token_decoder import Grammar
from scripts.research_ask import (
    SCHEMA as ASK_SCHEMA,
)
from scripts.research_ask import (
    UnsupportedRuntimeError,
    ask,
    human_report,
    open_runtime,
    prepare_request,
    verify_base,
)
from scripts.research_scenarios import packaged_scenario

DISTRIBUTION = "dynamislm-research"
SCENARIOS = (
    "absolute-change",
    "missing-evidence",
    "unsupported-operation",
    "causal-escalation",
    "practical-escalation",
)


def demo(case: str) -> tuple[dict[str, object], int]:
    support = make_support("research-cli", (0.25, 0.375))
    source = support.analysis_input
    record = d.build_longitudinal_record(
        source.athlete, source.entries, d.LongitudinalRecordOrigin.SYNTHETIC_DETERMINISTIC
    )
    bound = BoundRequest(
        "What is the absolute change between these two synthetic readings?",
        source,
        () if case == "missing-evidence" else (record,),
    )
    analysis = "SCALAR_ABSOLUTE_CHANGE"
    operation = RES69_ABSOLUTE_CHANGE_OPERATION.stable_id
    measurement = ["NUMERICAL_CHANGE"]
    relationship = []
    match case:
        case "unsupported-operation":
            analysis, operation = "WITHIN_ATHLETE_ASSOCIATION", v3.NONE
        case "causal-escalation":
            relationship = ["CAUSAL_EVIDENCE"]
        case "practical-escalation":
            measurement = ["PRACTICAL_OR_DECISION_MEANINGFULNESS"]

    request = bound.model_request()
    document = {
        "name": v3.TOOL_NAME,
        "arguments": {
            "analysis_class": analysis,
            "observation_ids": v3.observation_ids(request),
            "operation": operation,
            "target_claims": {"measurement": measurement, "relationship": relationship},
        },
    }
    raw = v3.OPEN + json.dumps(document, separators=(",", ":")) + v3.CLOSE
    if not Grammar(request).accepts(raw.encode()):
        raise RuntimeError("synthetic proposal differs from the registered V3 grammar")
    decision = submit_scientific_action_v3(bound, raw)
    analysis_decision = decision.analysis_authorization
    claim_decision = decision.claim_authority
    result = decision.result
    return {
        "origin": "SYNTHETIC_DETERMINISTIC",
        "proposal_origin": "SCRIPTED",
        "case": case,
        "request": v3.visible_request(request),
        "source_record_hash": d.canonical_hash(record) if bound.records else None,
        "proposal": raw,
        "admission": {
            "outcome": decision.outcome,
            "trusted_admission": decision.trusted_admission,
            "reason_codes": decision.reason_codes,
            "execution_authorized": decision.execution_authorized,
            "operation_executed": decision.operation_executed,
            "analysis_status": analysis_decision.status if analysis_decision else None,
            "claim_status": claim_decision.status if claim_decision else None,
            "allowed_measurement_levels": (
                claim_decision.allowed_measurement_levels if claim_decision else ()
            ),
            "allowed_relationship_levels": (
                claim_decision.allowed_relationship_levels if claim_decision else ()
            ),
        },
        "result": None
        if result is None
        else {
            "operation": result.operation.stable_id,
            "estimates": [
                {
                    "value": estimate.value,
                    "unit": estimate.unit.display_label,
                    "estimand": estimate.estimand.stable_id,
                }
                for estimate in result.estimates
            ],
            "canonical_hash": d.canonical_hash(result),
        },
    }, 0 if decision.outcome == "GROUNDED_RESULT" else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=version(DISTRIBUTION))
    commands = parser.add_subparsers(dest="command", required=True)
    example = commands.add_parser("demo", help="run a scripted CPU demonstration")
    example.add_argument("scenario", choices=SCENARIOS)
    commands.add_parser("identity", help="show the packaged source and artifact identity")
    inquiry = commands.add_parser("ask", help="run C1 on a packaged synthetic scenario")
    inquiry.add_argument("--scenario", required=True)
    inquiry.add_argument("--question", required=True)
    inquiry.add_argument("--bundle", type=Path, required=True)
    inquiry.add_argument("--base", type=Path, required=True)
    inquiry.add_argument("--device", metavar="cpu|cuda", required=True)
    base = commands.add_parser("verify-base", help="hash the exact local base snapshot")
    base.add_argument("--base", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "verify-base":
        try:
            print(v3.canonical(verify_base(args.base)))
        except (OSError, ValueError) as exc:
            print(v3.canonical({"status": "INTEGRITY_FAILURE", "reason": str(exc)}))
            return 3
        return 0
    if args.command == "ask":
        try:
            scenario = packaged_scenario(args.scenario)
            prepare_request(scenario, args.question)
            runtime = open_runtime(args.bundle, args.base, args.device)
            receipt, code = ask(scenario, args.question, runtime)
        except (OSError, ValueError) as exc:
            unsupported = isinstance(exc, UnsupportedRuntimeError)
            code = 4 if unsupported else 3
            receipt = {
                "schema": ASK_SCHEMA,
                "question": args.question,
                "scenario": {"id": args.scenario},
                "proposal": {"raw": None, "token_ids": []},
                "admission": {
                    "outcome": "UNSUPPORTED_RUNTIME" if unsupported else "INTEGRITY_FAILURE",
                    "parse_status": "NOT_REACHED",
                    "reason_codes": ["RUNTIME_UNSUPPORTED" if unsupported else "INPUT_INTEGRITY"],
                    "detail": str(exc),
                    "execution_authorized": False,
                    "operation_executed": False,
                },
                "result": None,
                "claim_ceiling": {"measurement": [], "relationship": []},
                "identity": None,
            }
        print(v3.canonical(receipt))
        print(human_report(receipt), file=sys.stderr)
        return code

    if not (
        platform.python_implementation() == "CPython"
        and sys.version_info[:2] == (3, 13)
        and sys.platform == "linux"
        and platform.machine() == "x86_64"
    ):
        parser.error("supported environment is Linux x86_64 with CPython 3.13")
    if args.command == "identity":
        print(Path(__file__).with_name("_research_identity.json").read_text().rstrip())
        return 0
    receipt, code = demo(args.scenario)
    print(v3.canonical(receipt))
    return code


if __name__ == "__main__":
    sys.exit(main())
