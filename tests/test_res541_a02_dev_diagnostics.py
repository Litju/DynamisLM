from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from scripts import a02_dev_diagnostics


def _write_bundle(root: Path) -> None:
    root.mkdir(parents=True)
    remote = {
        "schema": "RES541_A02_REMOTE_REPORT_V1",
        "status": "COMPLETE",
        "source": {"run_id": root.name},
        "cases": [
            {
                "case_id": "a02-valid-numerical",
                "protocol": "new",
                "action_generation": {
                    "prompt_text": "<|im_start|>system\nno tools declared<|im_end|>",
                    "prompt_sha256": "a" * 64,
                    "prompt_tokens": 50,
                    "generated_tokens": 128,
                    "truncated": True,
                    "raw_text": '{"action":{"kind":"request_analysis"',
                },
                "final_generation": {
                    "prompt_tokens": 40,
                    "generated_tokens": 64,
                    "truncated": True,
                    "raw_text": '{"origin":"trusted_executor_result","payload":"..."}',
                },
            }
        ],
    }
    remote_bytes = json.dumps(remote, sort_keys=True).encode()
    (root / "remote-report.json").write_bytes(remote_bytes)
    verified = {
        "schema": "RES541_A02_VERIFIED_REPORT_V2",
        "remote_report_sha256": hashlib.sha256(remote_bytes).hexdigest(),
        "terminal_outcome": "STAGE_A_SCIENTIFIC_NO_GO",
        "case_results": [
            {
                "case_id": "a02-valid-numerical",
                "application_event_origin": "application_guard_refusal",
                "model_intent_correct": False,
                "error_taxonomy": ["MODEL_ACTION_INVALID", "ACTION_OUTPUT_TRUNCATED"],
            }
        ],
        "metrics": {
            "model_action_parse_valid": {"numerator": 0, "denominator": 10},
            "new_model_action_exact_match": {"numerator": 0, "denominator": 10},
            "critical_semantic_intent_accuracy": {"numerator": 0, "denominator": 8},
            "expected_numeric_execution_accuracy": {"numerator": 0, "denominator": 9},
            "refusal_reason_code_agreement": {"numerator": 0, "denominator": 17},
            "final_answer_grounding_under_fixed_rule": {"numerator": 0, "denominator": 26},
            "application_guard_refusals": 1,
            "error_taxonomy_counts": {"ACTION_OUTPUT_TRUNCATED": 1},
        },
    }
    (root / "verified-v2.json").write_text(json.dumps(verified, sort_keys=True))
    (root / "verified.json").write_text("{}")
    files = []
    for name in ("remote-report.json", "verified.json", "verified-v2.json"):
        data = (root / name).read_bytes()
        files.append(
            {
                "name": name,
                "local_path": str(root / name),
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    (root / "artifact-hashes.json").write_text(
        json.dumps(
            {
                "schema": "RES541_A02_ARTIFACT_HASHES_V1",
                "run_id": root.name,
                "files": files,
            }
        )
    )


def test_diagnose_distinguishes_missing_native_tool_and_final_echo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(a02_dev_diagnostics, "E_ROOT", tmp_path.resolve())
    run_dir = tmp_path / "synthetic-run"
    _write_bundle(run_dir)

    result = a02_dev_diagnostics.diagnose(run_dir)

    assert result["new_case_prompt_diagnostics"] == {
        "case_count": 1,
        "native_tool_schema_present": 0,
        "system_override_present": 1,
        "truncated_actions": 1,
        "schema_invalid_actions": 1,
        "final_transcript_echoes": 1,
    }
    row: dict[str, Any] = result["cases"][0]
    assert row["action_parse_error"] == "invalid action JSON"
    assert row["error_taxonomy"] == ["MODEL_ACTION_INVALID", "ACTION_OUTPUT_TRUNCATED"]


def test_diagnose_rejects_tampered_report_even_when_manifest_is_updated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(a02_dev_diagnostics, "E_ROOT", tmp_path.resolve())
    run_dir = tmp_path / "synthetic-run"
    _write_bundle(run_dir)
    (run_dir / "remote-report.json").write_text("{}")

    with pytest.raises(ValueError, match="artifact hash mismatch: remote-report.json"):
        a02_dev_diagnostics.diagnose(run_dir)


def test_diagnose_rejects_unsafe_manifest_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(a02_dev_diagnostics, "E_ROOT", tmp_path.resolve())
    run_dir = tmp_path / "synthetic-run"
    _write_bundle(run_dir)
    manifest = json.loads((run_dir / "artifact-hashes.json").read_bytes())
    manifest["files"][0]["name"] = "../remote-report.json"
    (run_dir / "artifact-hashes.json").write_text(json.dumps(manifest))

    with pytest.raises(ValueError, match="unsafe or duplicate path"):
        a02_dev_diagnostics.diagnose(run_dir)
