"""Run the DynamisLM synthetic research demonstration."""

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
    args = parser.parse_args()
    if not (
        platform.python_implementation() == "CPython"
        and sys.version_info[:2] == (3, 12)
        and sys.platform == "linux"
        and platform.machine() == "x86_64"
    ):
        parser.error("supported environment is Linux x86_64 with CPython 3.12")
    if args.command == "identity":
        print(Path(__file__).with_name("_research_identity.json").read_text().rstrip())
        return 0
    receipt, code = demo(args.scenario)
    print(v3.canonical(receipt))
    return code
