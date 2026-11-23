"""Prepare and verify a fixed, exposed N/C0/C1 inference qualification."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from dynamislm import LongitudinalRecordOrigin, build_longitudinal_record, canonical_json
from dynamislm.longitudinal.statistics import RES69_ABSOLUTE_CHANGE_OPERATION
from dynamislm.training_data.synthetic_science import make_support
from scripts import a02_v3_contract as v3
from scripts import a02_v3_decision as historical
from scripts import a03_d0_runtime as d0
from scripts import a03_d0_sample as sample
from scripts import a03_prospective_run as runner
from scripts import a03_scientific_admission as admission
from scripts.a02_v3_preflight import load_pinned_tokenizer
from scripts.a03_benchmark_seal import EXPOSED_RESEARCH_CLI_QUESTION
from scripts.a03_prospective_score import _output_commit
from scripts.a03_token_decoder import TokenMask, Vocabulary

SOURCE_CASE = "research-cli"
D0_CASE = "HELDOUT:5410:62"


def inputs() -> tuple[bytes, bytes]:
    # Reconstruct the already exposed RES-747 development demonstration.
    source = make_support(SOURCE_CASE, (0.25, 0.375)).analysis_input
    record = build_longitudinal_record(
        source.athlete, source.entries, LongitudinalRecordOrigin.SYNTHETIC_DETERMINISTIC
    )
    bound = admission.BoundRequest(EXPOSED_RESEARCH_CLI_QUESTION, source, (record,))
    qualified = [
        runner.observation_binding(
            bound,
            i,
            entry.observation.provenance.source_artifacts[0].content_digest.removeprefix("sha256:"),
        )
        for i, entry in enumerate(bound.entries)
    ]
    historical_request = next(
        case["request"]
        for case in sample.select(historical.heldout_examples(historical.load_protocol()))
        if historical.example_id(case) == D0_CASE
    )
    # The historical prompt's synthetic row has no RES-62 binding in this workload.
    unresolved = [
        {
            "alias": f"observation-{i}",
            "binding": "UNRESOLVED",
            **dict.fromkeys(
                (
                    "source_sha256",
                    "record_sha256",
                    "observation_sha256",
                    "device",
                    "protocol",
                    "unit",
                )
            ),
        }
        for i in range(1, len(historical_request["observations"]) + 1)
    ]
    cases = (
        (SOURCE_CASE, bound, qualified),
        (
            "d0-62-unresolved",
            admission.BoundRequest(historical_request["question"], None, ()),
            unresolved,
        ),
    )
    requests = []
    sources = []
    for item_id, binding, observations in cases:
        requests.append(
            {
                **binding.model_request(),
                "item_id": item_id,
                "observations": observations,
            }
        )
        sources.append({"item_id": item_id, "bound": canonical_json(binding)})
    request_bytes, source_bytes = (
        "".join(v3.canonical(row) + "\n" for row in rows).encode() for rows in (requests, sources)
    )
    return request_bytes, source_bytes


def authority_controls(bound: admission.BoundRequest) -> dict[str, Any]:
    action = {
        "analysis_class": "SCALAR_ABSOLUTE_CHANGE",
        "operation": RES69_ABSOLUTE_CHANGE_OPERATION.stable_id,
        "observation_ids": v3.observation_ids(bound.model_request()),
    }
    refused = {}
    for measurement, relationship, reason in (
        (["NUMERICAL_CHANGE"], ["CAUSAL_EVIDENCE"], "RES70_UNSUPPORTED_CAUSAL_CLAIM"),
        (["PRACTICAL_OR_DECISION_MEANINGFULNESS"], [], "RES70_UNSUPPORTED_CLAIM_ESCALATION"),
    ):
        raw = v3.format_action(
            {**action, "target_claims": {"measurement": measurement, "relationship": relationship}}
        )

        def unexpected(operation: str) -> bool:
            raise ValueError(f"unauthorized proposal reached the dispatch boundary: {operation}")

        decision = admission.submit_scientific_action_v3(bound, raw, permit_dispatch=unexpected)
        if (
            decision.outcome != "REFUSED"
            or decision.execution_authorized
            or decision.operation_executed
            or decision.result is not None
            or reason not in decision.reason_codes
        ):
            raise ValueError(f"authority control failed: {decision}")
        refused[reason] = list(decision.reason_codes)
    return refused


def verify(
    blind: Path, output: Path, manifest_sha256: str, commit_sha256: str, snapshot: Path
) -> dict[str, Any]:
    manifest = v3.json_object(runner.verified_bytes(blind / "run.json", manifest_sha256).decode())
    if manifest["mode"] != runner.QUALIFICATION:
        raise ValueError("qualification requires the development-only real-model manifest")
    requests = runner.verified_bytes(blind / "requests.jsonl", manifest["blind_requests_sha256"])
    sources = runner.verified_bytes(blind / "sources.jsonl", manifest["sources_sha256"])
    if (requests, sources) != inputs():
        raise ValueError("exposed qualification workload differs")
    items, work = runner.verify_run(manifest, requests, sources)
    tokenizer = load_pinned_tokenizer(snapshot)
    mask = TokenMask(Vocabulary.from_pinned(snapshot))
    entries = _output_commit(output, manifest, commit_sha256, items, work, tokenizer, mask)
    cases: dict[str, Any] = {item.item_id: {} for item in items}
    by_id = {item.item_id: item.bound for item in items}
    for entry, scheduled in zip(entries, work, strict=True):
        row = entry["record"]
        trace = admission.submit_scientific_action_v3(by_id[scheduled.key], row["raw"])
        cases[scheduled.key][scheduled.arm] = {
            **row,
            "authority": {
                "outcome": trace.outcome,
                "reason_codes": trace.reason_codes,
                "execution_authorized": trace.execution_authorized,
                "operation_executed": trace.operation_executed,
            },
        }
    for case in cases.values():
        n, c1 = case["N"], case["C1"]
        case["paired"] = {
            "raw_equal": n["raw"] == c1["raw"],
            "tokens_equal": n["ids"] == c1["ids"],
            "preserves_compatible_native": (
                n["ids"] == c1["ids"] and c1["diagnostics"]["mask_accepted"]
                if n["diagnostics"]["mask_accepted"]
                else None
            ),
        }
    return {
        "mode": runner.QUALIFICATION,
        "manifest_sha256": manifest_sha256,
        "output_commit_sha256": commit_sha256,
        "authority_controls": authority_controls(by_id[SOURCE_CASE]),
        "complete_generation": all(
            row["termination"] in ("MODEL_EOS", "C0_GRAMMAR_COMPLETE")
            and row["diagnostics"]["strict_syntax"]
            and (scheduled.arm != "C1" or row["diagnostics"]["mask_accepted"])
            for row, scheduled in zip((entry["record"] for entry in entries), work, strict=True)
        ),
        "cases": cases,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("blind", type=Path)
    prepare.add_argument("--device", choices=("cpu", "cuda"), required=True)
    check = commands.add_parser("verify")
    check.add_argument("blind", type=Path)
    check.add_argument("output", type=Path)
    check.add_argument("--manifest-sha256", required=True)
    check.add_argument("--commit-sha256", required=True)
    check.add_argument("--tokenizer", type=Path, required=True)
    args = parser.parse_args()
    blind = runner.restricted(args.blind)
    if args.command == "prepare":
        requests, sources = inputs()
        manifest = runner.run_manifest(runner.QUALIFICATION, requests, sources, device=args.device)
        for name, data in (("requests.jsonl", requests), ("sources.jsonl", sources)):
            with (blind / name).open("xb") as stream:
                stream.write(data)
        d0.write(blind / "run.json", manifest)
        print(d0.digest(blind / "run.json"))
    else:
        result = verify(
            blind,
            runner.restricted(args.output),
            args.manifest_sha256,
            args.commit_sha256,
            args.tokenizer,
        )
        print(v3.canonical(result))
        if not result["complete_generation"]:
            raise SystemExit("qualification contains incomplete or invalid model outputs")


if __name__ == "__main__":
    main()
