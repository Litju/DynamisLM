"""Read-only case diagnostics for a hash-verified A0.2 development run."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any

from scripts import a0_engine, res403_tool_protocol

E_ROOT = Path("/mnt/e/DynamisLM-A0").resolve()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path.name}")
    return value


def _verified_bundle(run_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    root = run_dir.resolve()
    if not root.is_relative_to(E_ROOT) or not root.is_dir():
        raise ValueError("A0.2 development evidence must be read from E:")
    manifest = _read_json(root / "artifact-hashes.json")
    if (
        manifest.get("schema") != "RES541_A02_ARTIFACT_HASHES_V1"
        or manifest.get("run_id") != root.name
        or not isinstance(manifest.get("files"), list)
    ):
        raise ValueError("A0.2 artifact manifest does not bind this run directory")
    seen: set[str] = set()
    for record in manifest["files"]:
        if not isinstance(record, dict):
            raise ValueError("A0.2 artifact manifest has an invalid file record")
        name = record.get("name")
        if (
            not isinstance(name, str)
            or PurePosixPath(name).name != name
            or name in seen
            or record.get("local_path") != str(root / name)
        ):
            raise ValueError("A0.2 artifact manifest contains an unsafe or duplicate path")
        seen.add(name)
        data = (root / name).read_bytes()
        if len(data) != record.get("bytes") or hashlib.sha256(data).hexdigest() != record.get(
            "sha256"
        ):
            raise ValueError(f"A0.2 artifact hash mismatch: {name}")
    required = {"remote-report.json", "verified.json", "verified-v2.json"}
    if not required <= seen:
        raise ValueError("A0.2 artifact manifest omits a required scoring artifact")
    remote = _read_json(root / "remote-report.json")
    verified = _read_json(root / "verified-v2.json")
    if hashlib.sha256((root / "remote-report.json").read_bytes()).hexdigest() != verified.get(
        "remote_report_sha256"
    ):
        raise ValueError("CPU score does not bind the retained remote report")
    if (
        remote.get("schema") != "RES541_A02_REMOTE_REPORT_V1"
        or remote.get("status") != "COMPLETE"
        or verified.get("schema") != "RES541_A02_VERIFIED_REPORT_V2"
        or not isinstance(remote.get("cases"), list)
    ):
        raise ValueError("remote inference report is incomplete")
    return remote, verified


def diagnose(run_dir: Path) -> dict[str, Any]:
    remote, verified = _verified_bundle(run_dir)
    case_results = verified.get("case_results")
    if not isinstance(case_results, list) or any(not isinstance(row, dict) for row in case_results):
        raise ValueError("CPU-scored case results are missing")
    scored = {row.get("case_id"): row for row in case_results}
    if len(scored) != len(case_results):
        raise ValueError("CPU-scored case results contain duplicate identifiers")
    rows = []
    for case in remote["cases"]:
        case_id = case.get("case_id")
        score = scored.get(case_id)
        if not isinstance(case_id, str) or score is None:
            raise ValueError("remote and CPU-scored case coverage differs")
        action = case.get("action_generation")
        final = case.get("final_generation")
        if not isinstance(action, dict) or not isinstance(final, dict):
            raise ValueError(f"generation record is missing: {case_id}")
        raw_action = action.get("raw_text")
        raw_final = final.get("raw_text")
        if not isinstance(raw_action, str) or not isinstance(raw_final, str):
            raise ValueError(f"raw generation text is missing: {case_id}")
        try:
            if case.get("protocol") == "new":
                parsed_kind = res403_tool_protocol.parse_action(raw_action).kind
            else:
                parsed_kind = a0_engine.parse_model_intent(raw_action).decision.value
            parse_error = None
        except (TypeError, ValueError) as exc:
            parse_error = str(exc)
            parsed_kind = None
        rendered_prompt = action.get("prompt_text")
        if not isinstance(rendered_prompt, str):
            raise ValueError(f"rendered model prompt is missing: {case_id}")
        rows.append(
            {
                "case_id": case_id,
                "protocol": case.get("protocol"),
                "action_prompt_sha256": action.get("prompt_sha256"),
                "action_prompt_tokens": action.get("prompt_tokens"),
                "action_prompt_uses_system_override": "## Metadata" not in rendered_prompt,
                "action_prompt_contains_native_tool_schema": "<tools>" in rendered_prompt,
                "action_generated_tokens": action.get("generated_tokens"),
                "action_truncated": action.get("truncated"),
                "action_parse_error": parse_error,
                "parsed_action_kind": parsed_kind,
                "raw_action_prefix": raw_action[:180],
                "final_prompt_tokens": final.get("prompt_tokens"),
                "final_generated_tokens": final.get("generated_tokens"),
                "final_truncated": final.get("truncated"),
                "final_echoes_transcript_envelope": raw_final.lstrip().startswith('{"origin":'),
                "raw_final_prefix": raw_final[:180],
                "application_origin": score.get("application_event_origin"),
                "model_intent_correct": score.get("model_intent_correct"),
                "error_taxonomy": score.get("error_taxonomy", []),
            }
        )
    if len({row["case_id"] for row in rows}) != len(rows) or set(scored) != {
        row["case_id"] for row in rows
    }:
        raise ValueError("remote and CPU-scored case coverage differs")
    metrics = verified.get("metrics")
    if not isinstance(metrics, dict):
        raise ValueError("CPU score metrics are missing")
    new_rows = [row for row in rows if row["protocol"] == "new"]
    return {
        "schema": "RES541_A02_DEVELOPMENT_DIAGNOSTICS_V1",
        "run_id": remote.get("source", {}).get("run_id"),
        "remote_report_sha256": verified["remote_report_sha256"],
        "terminal_outcome": verified.get("terminal_outcome"),
        "metrics": {
            name: metrics.get(name)
            for name in (
                "model_action_parse_valid",
                "new_model_action_exact_match",
                "critical_semantic_intent_accuracy",
                "expected_numeric_execution_accuracy",
                "refusal_reason_code_agreement",
                "final_answer_grounding_under_fixed_rule",
                "application_guard_refusals",
                "error_taxonomy_counts",
            )
        },
        "new_case_prompt_diagnostics": {
            "case_count": len(new_rows),
            "native_tool_schema_present": sum(
                row["action_prompt_contains_native_tool_schema"] for row in new_rows
            ),
            "system_override_present": sum(
                row["action_prompt_uses_system_override"] for row in new_rows
            ),
            "truncated_actions": sum(row["action_truncated"] is True for row in new_rows),
            "schema_invalid_actions": sum(
                row["action_parse_error"] is not None for row in new_rows
            ),
            "final_transcript_echoes": sum(row["final_echoes_transcript_envelope"] for row in rows),
        },
        "cases": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    print(json.dumps(diagnose(args.run_dir), ensure_ascii=True, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
