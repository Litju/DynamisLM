"""CPU-only end-to-end replay of the remote worker report through the scientific scorer."""

from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from scripts import (
    a0_engine,
    a02_engine,
    a02_execution,
    a02_experiment,
    a02_preflight,
    a02_prompt,
    a02_recover,
    a02_remote,
    a02_score,
)

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = json.loads(a02_experiment.PROTOCOL_PATH.read_text())
TOKENIZER_DIR = a02_execution.E_ROOT / "a01/tokenizer"
TOKENIZER_PREFLIGHT = a02_execution.REPORT_DIR / "preflight-v1.json"
HAS_LOCAL_EVIDENCE = (
    TOKENIZER_DIR.is_dir()
    and TOKENIZER_PREFLIGHT.is_file()
    and (TOKENIZER_DIR / "tokenizer.json").is_file()
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def _generation(
    tokenizer: Any,
    messages: list[dict[str, str]],
    raw_text: str,
    template_date: datetime,
    max_new_tokens: int,
    *,
    frozen_prompt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prompt_ids, prompt_text = a02_preflight._render(tokenizer, messages, template_date)
    generated_ids = [*tokenizer.encode(raw_text, add_special_tokens=False), tokenizer.eos_token_id]
    return {
        "seed": 541,
        "do_sample": False,
        "num_beams": 1,
        "max_new_tokens": max_new_tokens,
        "prompt_text": prompt_text,
        "prompt_sha256": _sha(prompt_text.encode()),
        "prompt_token_ids": prompt_ids,
        "prompt_token_ids_sha256": (
            frozen_prompt["prompt_token_ids_sha256"]
            if frozen_prompt is not None
            else _sha(a02_score.canonical(prompt_ids).encode())
        ),
        "prompt_tokens": len(prompt_ids),
        "raw_text": raw_text,
        "raw_with_special_tokens": tokenizer.decode(generated_ids, skip_special_tokens=False),
        "generated_token_ids": generated_ids,
        "generated_token_ids_sha256": _sha(a02_score.canonical(generated_ids).encode()),
        "generated_tokens": len(generated_ids),
        "eos_seen": True,
        "truncated": False,
        "first_token_latency_s": 0.0,
        "generation_latency_s": 0.0,
        "template_date": template_date.strftime("%d %B %Y"),
    }


def _synthetic_action(
    kind: str, case_id: str, case: dict[str, Any], historical_case: Any | None = None
) -> str:
    if kind == "new":
        action = case["expected_action"]
        body = json.dumps(
            {"name": "registered_science", "arguments": action}
            if action["kind"] == "request_analysis"
            else action,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        return f"<tool_call>{body}</tool_call>" if action["kind"] == "request_analysis" else body
    if historical_case is None:
        raise ValueError(f"missing synthetic historical authority case: {case_id}")
    intent = a0_engine.oracle_intent(a0_engine._build_context(historical_case))
    return json.dumps(a0_engine._model_intent_wire(intent), sort_keys=True, separators=(",", ":"))


def _executor_response(
    kind: str, case_id: str, raw_action: str, interaction_id: str
) -> dict[str, Any]:
    if kind == "historical":
        return a02_engine.execute_historical(case_id, raw_action, interaction_id)
    return a02_engine.execute_new(case_id, raw_action, interaction_id)


def _synthetic_case(
    tokenizer: Any,
    run_id: str,
    kind: str,
    case_id: str,
    case: dict[str, Any],
    frozen: dict[str, dict[str, Any]],
    historical_case: Any | None = None,
) -> dict[str, Any]:
    raw_action = _synthetic_action(kind, case_id, case, historical_case)
    interaction_id = f"{run_id}:{case_id}"
    engine_response = _executor_response(kind, case_id, raw_action, interaction_id)
    event = engine_response["event"]
    summary = {
        "origin": event["origin"],
        "outcome": event["outcome"],
        "reason_codes": event["reason_codes"],
        "value": event.get("value"),
        "unit": event.get("unit"),
        "claim_scope": "NUMERICAL_CHANGE_ONLY"
        if event["outcome"] == "RESULT"
        else "NO_RESULT_AUTHORIZED",
    }
    final_text = (
        f"Authorized change: {event['value']} {event['unit']}."
        if event["outcome"] == "RESULT"
        else "No result is authorized from the supplied evidence."
    )
    if kind == "historical":
        user_message = case["user_message"]
        final_user_text = user_message
        action_messages = [
            {
                "role": "system",
                "content": (ROOT / "experiments/a01/system-prompt-v1.txt").read_text().rstrip("\n"),
            },
            {"role": "user", "content": user_message},
        ]
        request_sha = case["user_message_sha256"]
        action_date = a02_preflight.TEMPLATE_DATES["historical"]
        action_limit = PROTOCOL["historical_a01"]["decoding"]["max_new_tokens"]
    else:
        request = case["request"]
        request_text = a02_remote._canonical(request)
        user_message = a02_remote._message_envelope("untrusted_user_input", request_text)
        final_user_text = a02_remote._final_request_text(request)
        action_messages = a02_prompt.build_action_messages(
            request,
            (ROOT / "experiments/a02/system-action-v1.txt").read_text().rstrip("\n"),
        )
        request_sha = case["request_sha256"]
        action_date = a02_preflight.TEMPLATE_DATES["a02"]
        action_limit = a02_remote.ACTION_TOKENS
    final_messages = [
        {
            "role": "system",
            "content": (ROOT / "experiments/a02/system-final-v1.txt").read_text().rstrip("\n"),
        },
        {
            "role": "user",
            "content": a02_remote._message_envelope("untrusted_user_input", final_user_text),
        },
        {
            "role": "assistant",
            "content": a02_remote._message_envelope("model_action_proposal", raw_action),
        },
        {"role": "tool", "content": a02_remote._canonical(summary)},
    ]
    return {
        "case_id": case_id,
        "protocol": kind,
        "request_sha256": request_sha,
        "final_user_text": final_user_text,
        "final_user_text_sha256": _sha(final_user_text.encode()),
        "interaction_id": interaction_id,
        "user_message": user_message,
        "action_generation": _generation(
            tokenizer,
            action_messages,
            raw_action,
            action_date,
            action_limit,
            frozen_prompt=frozen[case_id],
        ),
        "engine_response": engine_response,
        "engine_roundtrip_ms": 0.0,
        "final_generation": _generation(
            tokenizer,
            final_messages,
            final_text,
            a02_preflight.TEMPLATE_DATES["a02"],
            a02_remote.FINAL_TOKENS,
        ),
        "case_status": "COMPLETE",
    }


def _runtime_inventory() -> dict[str, Any]:
    return {
        "python": "3.13.16",
        "implementation": "CPython",
        "python_build": ["main", "2026-10-01 00:00:00"],
        "python_compiler": "synthetic CPU rehearsal",
        "python_full_version": "3.13.16 (synthetic CPU rehearsal)",
        "python_executable": "/usr/local/bin/python3.13",
        "soabi": "cpython-313-x86_64-linux-gnu",
        "gil_disabled": False,
        "gil_enabled": True,
        "debug_build": False,
        "system": "Linux",
        "machine": "x86_64",
        "torch": "2.11.0+cu130",
        "torch_cuda_runtime": "13.0",
        "device_count": 1,
        "gpu_name": "Tesla T4",
        "compute_capability": [7, 5],
        "total_vram_bytes": 16 * 1024**3,
        "gpu_uuid": "GPU-SYNTHETIC-CPU-REHEARSAL",
        "driver_inventory": "GPU-SYNTHETIC-CPU-REHEARSAL, 0.0, Tesla T4",
    }


def _package_inventory() -> dict[str, dict[str, Any]]:
    expected = {
        line.split("==", 1)[0]: line.split("==", 1)[1]
        for line in (ROOT / "experiments/a0/requirements-colab.txt").read_text().splitlines()
        if line and not line.startswith("#")
    }
    root = "/content/a02/inference-venv/lib/python3.13/site-packages"
    return {
        name: {
            "distribution_version": version,
            "module_version": None if name == "typing_extensions" else version,
            "module_origin": f"{root}/{module.replace('.', '/')}/__init__.py",
            "distribution_origin": root,
        }
        for name, module in a02_remote.PACKAGE_MODULES.items()
        for version in (expected[name],)
    }


@pytest.mark.skipif(not HAS_LOCAL_EVIDENCE, reason="attempt-3 retained E: evidence required")
def test_attempt4_lineage_rechecks_attempt3_without_changing_its_disposition() -> None:
    lineage = a02_execution._verify_attempt4_lineage()
    assert lineage["attempt_3_disposition"] == "A02_ATTEMPT3_EVIDENCE_VALIDATION_FAILED"
    assert lineage["attempt_3_scientific_decision"] == "NONE"
    assert lineage["attempt_3_recovery_manifest_sha256"] == (
        a02_execution.THIRD_RECOVERY_BUNDLE_MANIFEST_SHA256
    )


def _synthetic_remote_report(
    tokenizer: Any,
    run_id: str,
    source_revision: str,
    source_tree: str,
    archive_sha256: str,
    protocol_sha256: str,
    run_preflight_sha256: str,
    token_preflight: dict[str, Any],
) -> dict[str, Any]:
    historical_inputs = json.loads(
        (ROOT / "experiments/a02/historical-inputs-v1.json").read_text()
    )["cases"]
    historical_cases = {row["case_id"]: row for row in historical_inputs}
    new_cases = {
        row["case_id"]: row
        for row in json.loads((ROOT / "experiments/a02/cases-v1.json").read_text())["cases"]
    }
    historical_authority = {case.case_id: case for case in a02_experiment.load_historical_cases()}
    frozen = {
        row["case_id"]: row
        for row in [*token_preflight["historical_cases"], *token_preflight["new_action_cases"]]
    }
    cases = [
        *[
            _synthetic_case(
                tokenizer,
                run_id,
                "historical",
                case_id,
                case,
                frozen,
                historical_authority[case_id],
            )
            for case_id, case in historical_cases.items()
        ],
        *[
            _synthetic_case(tokenizer, run_id, "new", case_id, case, frozen)
            for case_id, case in new_cases.items()
        ],
    ]
    expected_packages = _package_inventory()
    system_site = "/usr/local/lib/python3.13/site-packages"
    runtime_inventory = _runtime_inventory()
    runtime = {
        "model_python": "3.13.16 (synthetic CPU rehearsal)",
        "model_python_version": "3.13.16",
        "scientific_engine_python": "3.12.13",
        "torch": "2.11.0+cu130",
        "torch_module": {
            "version": "2.11.0+cu130",
            "distribution_version": "2.11.0+cu130",
            "origin": f"{system_site}/torch/__init__.py",
            "distribution_origin": system_site,
        },
        "torch_cuda_runtime": "13.0",
        "packages": expected_packages,
        "gpu_name": "Tesla T4",
        "compute_capability": [7, 5],
        "total_vram_bytes": 16 * 1024**3,
        "free_vram_before_weights_bytes": 12 * 1024**3,
        "runtime_inventory": runtime_inventory,
        "weight_dtype": "float16",
        "historical_action_decoding": {
            **PROTOCOL["historical_a01"]["decoding"],
            "template_date": "28 October 2026",
        },
        "new_action_decoding": {
            **PROTOCOL["new_a02_cases"]["action_decoding"],
            "template_date": "03 November 2026",
        },
        "final_decoding": {
            **PROTOCOL["new_a02_cases"]["final_decoding"],
            "template_date": "03 November 2026",
        },
    }
    weights = [
        {
            "name": name,
            "bytes": size,
            "sha256": digest,
            "hub_lfs_sha256": digest,
        }
        for name, (size, digest) in a02_recover.WEIGHTS.items()
    ]
    return {
        "schema": "RES541_A02_REMOTE_REPORT_V1",
        "status": "COMPLETE",
        "source": {
            "run_id": run_id,
            "revision": source_revision,
            "tree": source_tree,
            "archive_sha256": archive_sha256,
            "protocol_sha256": protocol_sha256,
            "preflight_sha256": run_preflight_sha256,
        },
        "runtime_inventory_before_model": runtime_inventory,
        "runtime": runtime,
        "model": {
            "id": PROTOCOL["model"]["model_id"],
            "revision": PROTOCOL["model"]["model_revision"],
            "tokenizer_revision": PROTOCOL["model"]["tokenizer_revision"],
            "tokenizer_files": PROTOCOL["model"]["tokenizer_files"],
            "chat_template_sha256": _sha(tokenizer.chat_template.encode()),
            "load_seconds": 0.0,
            "weight_bytes": sum(row["bytes"] for row in weights),
            "weight_files": weights,
            "support_files": {},
            "allocated_before_model_bytes": 0,
            "reserved_before_model_bytes": 0,
        },
        "cases": cases,
        "drive_persistence": {"status": "NOT_MOUNTED", "writes_enabled": False},
        "partial_case_count": 26,
        "peak_allocated_vram_bytes": 7 * 1024**3,
        "peak_reserved_vram_bytes": 8 * 1024**3,
        "runtime_seconds": 0.0,
        "total_prompt_tokens": sum(
            row["action_generation"]["prompt_tokens"] + row["final_generation"]["prompt_tokens"]
            for row in cases
        ),
        "total_generated_tokens": sum(
            row["action_generation"]["generated_tokens"]
            + row["final_generation"]["generated_tokens"]
            for row in cases
        ),
        "process_max_rss": 0,
    }


@pytest.mark.skipif(
    not HAS_LOCAL_EVIDENCE, reason="pinned CPU tokenizer and A02 preflight on E: required"
)
def test_synthetic_worker_report_runs_through_full_cpu_scorer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("USE_TORCH", "0")
    monkeypatch.setenv("USE_TF", "0")
    monkeypatch.setenv("USE_FLAX", "0")
    transformers = pytest.importorskip("transformers")
    tokenizer = transformers.AutoTokenizer.from_pretrained(
        TOKENIZER_DIR,
        local_files_only=True,
        trust_remote_code=False,
        use_fast=True,
    )
    token_preflight = json.loads(TOKENIZER_PREFLIGHT.read_bytes())
    with tempfile.TemporaryDirectory(
        prefix="res541-a02-cpu-rehearsal-", dir=a02_execution.E_ROOT / "tmp"
    ) as temp:
        run_dir = Path(temp)
        run_id = "res541-a02-004-synthetic-cpu-rehearsal"
        source_revision = "a" * 40
        source_tree = "b" * 40
        source_archive = run_dir / "source.tar"
        source_archive.write_bytes(b"synthetic source archive; no model or GPU work")
        archive_sha256 = _sha(source_archive.read_bytes())
        active_sessions = [
            {
                "name": "synthetic-unrelated-session",
                "endpoint": "gpu-a100-s-synthetic-unrelated",
                "hardware": "A100",
            }
        ]
        assignments = [
            {
                "endpoint": active_sessions[0]["endpoint"],
                "accelerator": "Accelerator.A100",
                "variant": "AssignmentVariant.GPU",
            }
        ]
        usage_output = (
            "Current balance: 10.00 compute units\nUsage rate: 0.00/hr\nActive assignments: 1"
        )
        session_list = (
            "[synthetic-unrelated-session] gpu-a100-s-synthetic-unrelated | Hardware: A100 "
            "| Shape: Standard | Variant: GPU"
        )
        lineage_facts = {
            "attempt_1_marker_sha256": a02_execution.ATTEMPT4_CONTRACT["lineage"][
                "attempt_1_marker_sha256"
            ],
            "attempt_2_marker_sha256": a02_execution.ATTEMPT4_CONTRACT["lineage"][
                "attempt_2_marker_sha256"
            ],
            "attempt_3_marker_sha256": a02_execution.ATTEMPT4_CONTRACT["lineage"][
                "attempt_3_marker_sha256"
            ],
            "attempt_2_inventory_sha256": a02_execution.RECOVERY_INVENTORY_SHA256,
            "attempt_3_inventory_sha256": a02_execution.THIRD_RECOVERY_SHA256,
            "attempt_3_recovery_manifest_sha256": (
                a02_execution.THIRD_RECOVERY_BUNDLE_MANIFEST_SHA256
            ),
            "attempt_3_disposition": "A02_ATTEMPT3_EVIDENCE_VALIDATION_FAILED",
            "attempt_3_scientific_decision": "NONE",
            "attempt_3_historical_scorer_failure": a02_execution.ATTEMPT4_CONTRACT["lineage"][
                "attempt_3_historical_scorer_failure"
            ],
            "attempt_3_recovery_source_revision": a02_execution.ATTEMPT4_CONTRACT["lineage"][
                "attempt_3_recovery_source_revision"
            ],
            "attempt_3_historical_adapted_scorer_sha256": _sha(
                b"synthetic historical admission adapter"
            ),
            "execution_contract_sha256": a02_execution._contract_sha256(),
        }
        recovery = {
            "schema": "RES541_A02_ATTEMPT4_LINEAGE_V1",
            "previous_run_id": a02_execution.THIRD_RUN_ID,
            "recovery_inventory_sha256": a02_execution.THIRD_RECOVERY_SHA256,
            **lineage_facts,
            "lineage_sha256": _sha(a02_score.canonical(lineage_facts).encode()),
        }
        doc = {
            "schema": "RES541_A02_ATTEMPT4_PREFLIGHT_V1",
            "attempt": 4,
            "recovery": recovery,
            "source_revision": source_revision,
            "source_tree": source_tree,
            "git_clean": True,
            "authentication": "OAUTH2_ACCOUNT_SESSION_VERIFIED",
            "compute_unit_balance": 10.0,
            "usage_rate_cu_per_hour": 0.0,
            "active_assignment_count": 1,
            "active_session_count": 1,
            "a02_active_session_count": 0,
            "active_sessions": active_sessions,
            "provider_assignments": assignments,
            "usage_output": usage_output,
            "session_list": session_list,
            "quota_snapshot_sha256": _sha(
                a02_score.canonical(
                    {
                        "usage_output": usage_output,
                        "session_list": session_list,
                        "provider_assignments": assignments,
                    }
                ).encode()
            ),
            "execution_contract_sha256": a02_execution._contract_sha256(),
            "requested_gpu": "T4",
            "e_mount_source": "E:\\",
            "host_model_weights": "NOT_PRESENT_IN_CHECKED_CACHE",
            "drive_account_matches_colab": True,
            "drive_owner_email": "owner@example.com",
            "drive_probe_sha256": "c" * 64,
        }
        run_preflight_path = run_dir / "preflight.json"
        run_preflight_path.write_bytes(_json_bytes(doc))
        binding = a02_execution._binding(run_id, source_archive, doc, run_preflight_path)
        phrase = a02_execution._confirmation(doc, binding)
        authorization_path = run_dir / "authorization.json"
        authorization = {
            "schema": "RES541_A02_AUTHORIZATION_V2",
            "attempt": 4,
            "binding": binding,
            "owner_confirmation": phrase,
            "recorded_utc": "2026-11-05T00:00:00+00:00",
            "execution_contract": a02_execution.ATTEMPT4_CONTRACT,
        }
        authorization_path.write_bytes(_json_bytes(authorization))
        marker_path = run_dir / "attempt-004-used.json"
        marker = {
            "schema": "RES541_A02_ATTEMPT4_USED_V1",
            "attempt": 4,
            "authorization_sha256": _sha(authorization_path.read_bytes()),
            "recovery": recovery,
            "run_id": run_id,
            "source_revision": source_revision,
            "binding_sha256": _sha(a02_score.canonical(binding).encode()),
            "owner_confirmation_sha256": _sha(phrase.encode()),
            "recorded_utc": "2026-11-05T00:00:00+00:00",
            "execution_contract_sha256": a02_execution._contract_sha256(),
            "lineage_sha256": recovery["lineage_sha256"],
        }
        marker_path.write_bytes(_json_bytes(marker))
        monkeypatch.setattr(a02_execution, "FOURTH_MARKER", marker_path)
        monkeypatch.setattr(
            a02_execution, "_check_attempt", lambda attempt, allow_used=False: recovery
        )

        remote_path = run_dir / "remote-report.json"
        monkeypatch.setattr(a02_remote, "REMOTE_REPORT", remote_path)
        monkeypatch.setattr(a02_remote, "DRIVE_RUN_DIR", None)
        remote = _synthetic_remote_report(
            tokenizer,
            run_id,
            source_revision,
            source_tree,
            archive_sha256,
            binding["protocol_sha256"],
            binding["preflight_sha256"],
            token_preflight,
        )
        a02_remote._write_report(remote)
        remote_bytes = remote_path.read_bytes()
        persisted_remote = json.loads(remote_bytes)
        assert persisted_remote["schema"] == "RES541_A02_REMOTE_REPORT_V1"
        assert _sha(remote_bytes) == _sha(_json_bytes(persisted_remote))

        target_endpoint = "gpu-t4-s-synthetic-a02-target"
        remaining_assignments = [
            {
                "endpoint": active_sessions[0]["endpoint"],
                "accelerator": "Accelerator.A100",
                "variant": "AssignmentVariant.GPU",
            }
        ]
        assignments_output = json.dumps(
            {
                "endpoint": "https://colab.research.google.com/tun/m/assignments",
                "assignments": remaining_assignments,
            },
            sort_keys=True,
        )
        control = {
            "schema": "RES541_A02_CONTROL_RECEIPT_V2",
            "preflight": doc,
            "preflight_path": str(run_preflight_path),
            "binding": binding,
            "session": run_id,
            "owner_confirmation": True,
            "owner_confirmation_text": phrase,
            "owner_confirmation_preflight": doc,
            "allocation_attempted": True,
            "one_attempt_marker": str(marker_path),
            "one_attempt_marker_sha256": _sha(marker_path.read_bytes()),
            "stop_exit_code": 0,
            "target_endpoint": target_endpoint,
            "status_after_allocation": (
                f"[{run_id}] {target_endpoint} | Hardware: T4 | Shape: Standard | "
                "Variant: GPU | Status: IDLE"
            ),
            "target_absent_after_stop": True,
            "session_absent_after_stop": False,
            "session_list_after_stop": session_list,
            "sessions_exit_code_after_stop": 0,
            "sessions_stderr_after_stop": "",
            "provider_assignment_exit_code": 0,
            "provider_assignment_stderr_after_stop": "",
            "provider_assignment_output_after_stop": assignments_output,
            "provider_assignment_output_sha256": _sha(assignments_output.encode()),
            "watchdog_phase": "DISARMED",
            "usage_after_exit_code": 0,
            "compute_unit_balance_after": 10.0,
            "compute_unit_balance_delta": 0.0,
        }
        control_path = run_dir / "control.json"
        control_path.write_bytes(_json_bytes(control))
        output_dir = run_dir / "scientific-score"
        result = a02_score.verify_run(
            remote_path,
            control_path,
            TOKENIZER_PREFLIGHT,
            output_dir,
        )
        verified = json.loads((output_dir / "verified.json").read_bytes())
        assert result["terminal_outcome"] == "STAGE_A_SCIENTIFIC_NO_GO"
        assert len(verified["case_results"]) == 26
        assert verified["remote_report_sha256"] == _sha(remote_bytes)
        assert verified["metrics"]["model_action_parse_valid"] == {
            "numerator": 26,
            "denominator": 26,
        }
        assert verified["metrics"]["model_intent_exact_match"] == {
            "numerator": 26,
            "denominator": 26,
        }
        assert verified["metrics"]["expected_numeric_execution_accuracy"] == {
            "numerator": 9,
            "denominator": 9,
        }
        assert verified["metrics"]["refusal_reason_code_agreement"] == {
            "numerator": 16,
            "denominator": 17,
        }
        assert verified["metrics"]["final_answer_grounding_under_fixed_rule"] == {
            "numerator": 26,
            "denominator": 26,
        }
        practical = next(
            row for row in verified["case_results"] if row["case_id"] == "refuse-practical-meaning"
        )
        assert practical["expected_reason_match"] is False
        assert practical["expected_reason_codes"] == ["RES70_COMPARABILITY_AUTHORITY_MISSING"]
        assert practical["executor_event"]["reason_codes"] == [
            "RES70_STATISTICAL_AUTHORITY_INSUFFICIENT",
            "RES70_UNSUPPORTED_CLAIM_ESCALATION",
        ]
        assert (output_dir / "scientific-report.md").is_file()
