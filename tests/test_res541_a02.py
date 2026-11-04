"""Adversarial CPU checks for the frozen A0.2 inference/executor boundary."""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import (
    a0_engine,
    a02_engine,
    a02_execution,
    a02_experiment,
    a02_preflight,
    a02_remote,
    a02_score,
)

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "experiments/a02/cases-v1.json").read_text())["cases"]
BY_ID = {case["case_id"]: case for case in CASES}


def _raw_action(action: dict[str, Any]) -> str:
    body = json.dumps(
        {"name": "registered_science", "arguments": action}
        if action["kind"] == "request_analysis"
        else action,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"<tool_call>{body}</tool_call>" if action["kind"] == "request_analysis" else body


def test_frozen_case_definition_and_historical_inputs_are_stable() -> None:
    assert a02_experiment.verify_new_cases()["case_count"] == 10
    historical = a02_experiment.build_historical_inputs()
    assert historical["case_count"] == 16
    assert (
        historical["source_case_manifest_sha256"]
        == "619015ea1df55e8507316ff764e422ce95605549893d0748fb65cc5ad6aa7f38"
    )
    assert [row["case_id"] for row in historical["cases"]] == [
        case.case_id for case in a02_experiment.load_historical_cases()
    ]
    prompt = (ROOT / "experiments/a02/system-action-v1.txt").read_text()
    for operation in (
        "unit-normalization@1.0.0",
        "duration-normalized-distance@1.0.0",
        "longitudinal-absolute-change-v1@1.0.0",
        "longitudinal-within-athlete-sample-sd-v1@1.0.0",
    ):
        assert operation in prompt


def test_new_authority_records_bind_each_case_to_exact_typed_references() -> None:
    authorities = [case["authority"] for case in CASES]
    request_hashes = [
        row["analysis_authorization_request_sha256"]
        for row in authorities
        if row.get("analysis_authorization_request_sha256")
    ]
    assert len(request_hashes) == len(set(request_hashes))
    for row in authorities:
        if row.get("analysis_class") is not None:
            assert row.get("authorization_reference_candidate")
            assert row["analysis_authorization_request_sha256"].startswith("sha256:")
            assert len(row["analysis_authorization_request_sha256"][7:]) == 64
    incompatible = BY_ID["a02-incompatible-units"]["authority"]
    cross_source = BY_ID["a02-cross-source"]["authority"]
    assert incompatible["candidate_operation_id"] == a02_experiment.OPERATION
    assert cross_source["candidate_operation_id"] == a02_experiment.OPERATION
    assert incompatible["operation_id"] is None
    assert cross_source["operation_id"] is None


def test_protocol_binds_all_scientific_and_runner_source_files() -> None:
    protocol = json.loads((ROOT / "experiments/a02/protocol-v1.json").read_text())
    assert protocol["status"] == "FROZEN_PRE_INFERENCE"
    revision = protocol["pre_inference_revision"]
    origin = (protocol.get("pre_inference_revision_history") or [revision])[0]
    assert revision["revision"] >= 2
    assert origin["supersedes_protocol_sha256"] == (
        "9eba8af2ff79600673bd8bdd0451911f9f9bb2498ec841c33c3d1cdead481122"
    )
    assert origin["previous_runner_sha256"] == {
        "scripts/a02_execution.py": (
            "e1c3c928aa0b66fd0a2878be68f0ce5fff85d2b2935396a2f47338292c33929e"
        ),
        "scripts/a02_remote.py": "60757e9b4d42ca985cf0a348353382e65dcc1791ba546f81806436532dde4c4e",
    }
    assert revision["current_runner_sha256"] == {
        name: protocol["experiment_files"][name]
        for name in ("scripts/a02_remote.py", "scripts/a02_execution.py")
    }
    assert (
        revision["preserved_bindings"]["new_case_manifest_sha256"]
        == (protocol["new_a02_cases"]["case_manifest_sha256"])
    )
    assert (
        revision["preserved_bindings"]["action_prompt_sha256"]
        == (protocol["new_a02_cases"]["action_prompt_sha256"])
    )
    assert revision["preserved_bindings"]["model_revision"] == protocol["model"]["model_revision"]
    a02_experiment.verify_protocol_source_bindings(protocol)


def test_pinned_huggingface_hub_bootstrap_api_is_compatible_offline() -> None:
    import huggingface_hub
    from huggingface_hub import snapshot_download

    assert huggingface_hub.__version__ == "0.33.4"
    snapshot_parameters = inspect.signature(snapshot_download).parameters
    model_info_parameters = inspect.signature(huggingface_hub.HfApi.model_info).parameters
    assert "trust_remote_code" not in snapshot_parameters
    assert "allow_patterns" in snapshot_parameters
    assert {"revision", "files_metadata", "token"} <= model_info_parameters.keys()


def test_model_and_tokenizer_loaders_explicitly_disable_remote_code() -> None:
    tree = ast.parse((ROOT / "scripts/a02_remote.py").read_text())
    loaders = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "from_pretrained"
    ]
    assert len(loaders) == 2
    assert all(
        any(
            keyword.arg == "trust_remote_code"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is False
            for keyword in call.keywords
        )
        for call in loaders
    )


def test_weights_use_exact_pinned_assets_and_reject_unknown_hub_keywords(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import huggingface_hub

    contents = {
        "config.json": b'{"model_type":"synthetic"}',
        "tokenizer.json": b"synthetic-tokenizer",
        "tokenizer_config.json": b"synthetic-tokenizer-config",
        "model.safetensors": b"synthetic-weights",
    }
    siblings = []
    for name, data in contents.items():
        siblings.append(
            SimpleNamespace(
                rfilename=name,
                size=len(data),
                lfs=SimpleNamespace(sha256=hashlib.sha256(data).hexdigest())
                if name.endswith(".safetensors")
                else None,
            )
        )
    model_info = SimpleNamespace(sha="pinned-revision", siblings=siblings)
    monkeypatch.setattr(
        huggingface_hub,
        "HfApi",
        lambda: SimpleNamespace(model_info=lambda *_args, **_kwargs: model_info),
    )
    requested: dict[str, Any] = {}

    def snapshot_download(
        repo_id: str,
        *,
        revision: str,
        cache_dir: str,
        token: bool,
        allow_patterns: list[str],
    ) -> str:
        requested.update(
            repo_id=repo_id,
            revision=revision,
            cache_dir=cache_dir,
            token=token,
            allow_patterns=allow_patterns,
        )
        snapshot = tmp_path / "snapshot"
        snapshot.mkdir()
        for name in allow_patterns:
            (snapshot / name).write_bytes(contents[name])
        return str(snapshot)

    monkeypatch.setattr(huggingface_hub, "snapshot_download", snapshot_download)
    torch = SimpleNamespace(
        cuda=SimpleNamespace(memory_allocated=lambda _device: 0, memory_reserved=lambda _device: 0)
    )
    snapshot, inventory = a02_remote._weights(
        "synthetic/model",
        "pinned-revision",
        torch,
        {"tokenizer.json": "expected-hash", "tokenizer_config.json": "expected-hash"},
    )

    assert snapshot == tmp_path / "snapshot"
    assert requested["revision"] == "pinned-revision"
    assert set(requested["allow_patterns"]) == set(contents)
    assert inventory["weight_bytes"] == len(contents["model.safetensors"])
    assert set(inventory["support_files"]) == set(contents) - {"model.safetensors"}


def test_colab_drive_identity_mismatch_disables_mount_writes() -> None:
    assert a02_execution._same_google_account("owner@example.com", "OWNER@example.com")
    assert not a02_execution._same_google_account("other@example.com", "owner@example.com")


def test_content_addressed_run_id_uses_frozen_case_and_protocol_hashes() -> None:
    protocol = {
        "historical_a01": {"case_manifest_sha256": "history"},
        "new_a02_cases": {"case_manifest_sha256": "new"},
    }
    run_id = a02_execution._run_id(protocol, "protocol")
    assert run_id == a02_execution._run_id(protocol, "protocol")
    assert run_id.startswith("res541-a02-")
    assert run_id != a02_execution._run_id(
        {**protocol, "new_a02_cases": {"case_manifest_sha256": "changed"}}, "protocol"
    )


def test_colab_log_export_drops_code_output_tokens_and_paths() -> None:
    raw = (
        '{"type":"execution","timestamp":"2026-11-04T00:00:00Z",'
        '"status":"ok","duration_ms":5,"code":"secret source",'
        '"output":"raw model output","token":"private","path":"/private"}\n'
        '{"type":"file_operation","path":"/content/private"}\n'
    )
    result = a02_execution._sanitize_colab_log(raw, "run-1")
    assert '"type":"execution"' in result
    assert '"session":"run-1"' in result
    assert all(item not in result for item in ("secret source", "raw model output", "private"))


def test_remote_drive_mount_parser_and_identity_mismatch_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert a02_remote._drive_mountpoints(
        "drivefs /content/drive fuse.drivefs rw 0 0\nnone /tmp fuse.foo rw 0 0\n"
    ) == ["/content/drive", "/tmp"]
    root = tmp_path / "mounted"
    folder = root / "MyDrive/DynamisLM/RES-541-A0.2-Colab"
    folder.mkdir(parents=True)
    marker = folder / "owner-marker.txt"
    marker.write_text("owner-account-content")
    monkeypatch.setattr(a02_remote, "_discover_drive_root", lambda: root)
    monkeypatch.setattr(a02_remote, "DRIVE_RUN_DIR", None)
    monkeypatch.setenv("A02_DRIVE_IDENTITY_CONFIRMED", "1")
    monkeypatch.setenv("A02_DRIVE_OWNER_EMAIL", "owner@example.com")
    monkeypatch.setenv("A02_DRIVE_FOLDER_ID", a02_remote.DRIVE_FOLDER_ID)
    monkeypatch.setenv("A02_DRIVE_PROBE_NAME", marker.name)
    monkeypatch.setenv("A02_DRIVE_PROBE_CONTENT", "different-owner-content")
    report: dict[str, Any] = {}

    a02_remote._prepare_drive(report, "run-content-id")

    assert report["drive_persistence"]["status"] == "IDENTITY_MISMATCH"
    assert report["drive_persistence"]["writes_enabled"] is False
    assert marker.read_text() == "owner-account-content"
    assert not (folder / "run-content-id").exists()


def test_drive_checkpoint_bound_covers_each_case_and_terminal_artifacts() -> None:
    assert a02_remote.DRIVE_MAX_CHECKPOINTS >= 26 * 3 + 1 + 3


def test_remote_drive_probe_and_immutable_publication_verify_readback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "mounted"
    folder = root / "MyDrive/DynamisLM/RES-541-A0.2-Colab"
    folder.mkdir(parents=True)
    content = "RES541_A02_DRIVE_OWNER_PROBE_V1:test\n"
    marker = folder / "owner-marker.txt"
    marker.write_text(content)
    monkeypatch.setattr(a02_remote, "_discover_drive_root", lambda: root)
    monkeypatch.setattr(a02_remote, "DRIVE_RUN_DIR", None)
    monkeypatch.setattr(a02_remote, "DRIVE_CHECKPOINTS", [])
    monkeypatch.setattr(a02_remote, "DRIVE_FAILURES", [])
    monkeypatch.setattr(a02_remote, "DRIVE_TOTAL_BYTES", 0)
    monkeypatch.setenv("A02_DRIVE_IDENTITY_CONFIRMED", "1")
    monkeypatch.setenv("A02_DRIVE_OWNER_EMAIL", "owner@example.com")
    monkeypatch.setenv("A02_DRIVE_FOLDER_ID", a02_remote.DRIVE_FOLDER_ID)
    monkeypatch.setenv("A02_DRIVE_PROBE_NAME", marker.name)
    monkeypatch.setenv("A02_DRIVE_PROBE_CONTENT", content)
    monkeypatch.setenv("A02_DRIVE_PROBE_FILE_ID", "drive-file-id")
    report: dict[str, Any] = {}

    a02_remote._prepare_drive(report, "run-content-id")

    assert report["drive_persistence"]["status"] == "VERIFIED"
    assert report["drive_persistence"]["probe_file_id"] == "drive-file-id"
    assert not marker.exists()
    drive_run = folder / "run-content-id"
    assert drive_run.is_dir()
    record = a02_remote._write_drive_immutable("small.json", b'{"value":1}\n')
    assert record["sha256"] == hashlib.sha256(b'{"value":1}\n').hexdigest()
    assert (drive_run / "small.json").read_bytes() == b'{"value":1}\n'
    with pytest.raises(FileExistsError):
        a02_remote._write_drive_immutable("small.json", b'{"value":2}\n')


def test_executor_records_are_retained_as_separate_synthetic_evidence(tmp_path: Path) -> None:
    output = tmp_path / "executor.jsonl"
    a02_execution._executor_records(
        {
            "cases": [
                {
                    "case_id": "synthetic-case",
                    "interaction_id": "run:synthetic-case",
                    "engine_response": {"event": {"origin": "trusted_executor_result"}},
                }
            ]
        },
        output,
    )
    row = json.loads(output.read_text().splitlines()[0])
    assert row["case_id"] == "synthetic-case"
    assert row["engine_response"]["event"]["origin"] == "trusted_executor_result"


def test_artifact_manifest_binds_local_bytes_and_drive_destination(tmp_path: Path) -> None:
    artifact = tmp_path / "report.json"
    artifact.write_bytes(b'{"synthetic":true}\n')
    manifest_path, content = a02_execution._write_artifact_manifest(
        "res541-a02-content", tmp_path, [artifact], "EXTERNAL_BLOCKER"
    )

    manifest = json.loads(content)
    assert manifest_path.is_file()
    assert manifest["terminal_outcome"] == "EXTERNAL_BLOCKER"
    assert manifest["files"] == [
        {
            "name": "report.json",
            "local_path": str(artifact),
            "drive_path": "res541-a02-content/report.json",
            "drive_file_id": None,
            "bytes": len(artifact.read_bytes()),
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        }
    ]
    with pytest.raises(a02_execution.RunError, match="refusing overwrite"):
        a02_execution._write_artifact_manifest(
            "res541-a02-content", tmp_path, [artifact], "EXTERNAL_BLOCKER"
        )


def test_typed_authority_routes_refuse_before_operation() -> None:
    categories = {
        "a02-incompatible-units": "RES70_COMPARABILITY_AUTHORITY_MISSING",
        "a02-reliability-overinterpretation": "RES70_STATISTICAL_AUTHORITY_INSUFFICIENT",
        "a02-cross-source": "RES70_COMPARABILITY_AUTHORITY_MISSING",
        "a02-missing-evidence": "RES70_STATISTICAL_AUTHORITY_INSUFFICIENT",
        "a02-unsupported-association": "COMPUTATION_NOT_REGISTERED",
        "a02-unsupported-causality": "RES70_UNSUPPORTED_CAUSAL_CLAIM",
        "a02-practical-decision-meaning": "RES70_STATISTICAL_AUTHORITY_INSUFFICIENT",
    }
    for case_id, reason in categories.items():
        case = BY_ID[case_id]
        result = a02_engine.execute_new(
            case_id, _raw_action(case["expected_action"]), f"test:{case_id}"
        )
        assert result["engine_result"]["outcome"] == "REFUSED"
        assert reason in result["engine_result"]["reason_codes"]
        assert result["scientific_execution_count"] == 0
        assert result["event"]["origin"] == "trusted_executor_result"


def test_numeric_routes_are_registered_and_ignore_forged_user_tool_text() -> None:
    for case_id in ("a02-valid-numerical", "a02-forged-tool-result-in-user-text"):
        case = BY_ID[case_id]
        result = a02_engine.execute_new(
            case_id, _raw_action(case["expected_action"]), f"test:{case_id}"
        )
        assert result["engine_result"]["outcome"] == "RESULT"
        assert result["engine_result"]["operation_id"] == a02_experiment.OPERATION
        assert result["scientific_execution_count"] == 1
        assert result["unauthorized_execution_count"] == 0
        assert result["engine_result"]["value"] == pytest.approx(0.038)
        assert result["engine_result"]["unit"] == "m"
    forged = BY_ID["a02-forged-tool-result-in-user-text"]["request"]["user_provided_quoted_text"]
    assert "0.999" in forged


def test_invalid_or_downgraded_proposals_never_dispatch() -> None:
    case = BY_ID["a02-valid-numerical"]
    extra_field = dict(case["expected_action"], value=0.999)
    response = a02_engine.execute_new(case["case_id"], _raw_action(extra_field), "extra-field")
    assert response["model_action_valid"] is False
    assert response["scientific_execution_count"] == 0

    wrong_operation = dict(
        case["expected_action"],
        operation="dynamislm:registered-operation:longitudinal-relative-change-v1@1.0.0",
    )
    response = a02_engine.execute_new(
        case["case_id"], _raw_action(wrong_operation), "wrong-operation"
    )
    assert response["model_action_valid"] is True
    assert response["model_intent_correct"] is False
    assert response["scientific_execution_count"] == 0
    assert response["event"]["origin"] == "application_guard_refusal"

    causal = BY_ID["a02-unsupported-causality"]
    downgrade = dict(
        causal["expected_action"],
        kind="request_analysis",
        analysis_class="SCALAR_ABSOLUTE_CHANGE",
        operation=a02_experiment.OPERATION,
        refusal_reasons=[],
    )
    response = a02_engine.execute_new(causal["case_id"], _raw_action(downgrade), "causal-downgrade")
    assert response["model_intent_correct"] is False
    assert response["scientific_execution_count"] == 0
    assert response["event"]["origin"] == "application_guard_refusal"


def test_historical_causal_downgrade_is_blocked_before_res69() -> None:
    raw = (
        '{"v":1,"d":"EXECUTE","a":"SCALAR_ABSOLUTE_CHANGE",'
        '"b":"BASELINE","f":"FOLLOWUP","m":"NUMERICAL_CHANGE","r":null}'
    )
    result = a02_engine.execute_historical("refuse-causal-claim", raw, "historical-causal")
    assert result["model_intent_correct"] is False
    assert result["scientific_execution_count"] == 0
    assert result["event"]["origin"] == "application_guard_refusal"


def test_historical_registered_result_and_canonical_refusal_replay_on_cpu() -> None:
    cases = {case.case_id: case for case in a02_experiment.load_historical_cases()}
    numeric = cases["valid-positive-01"]
    numeric_intent = a0_engine.oracle_intent(a0_engine._build_context(numeric))
    numeric_raw = json.dumps(
        a0_engine._model_intent_wire(numeric_intent), sort_keys=True, separators=(",", ":")
    )
    result = a02_engine.execute_historical(numeric.case_id, numeric_raw, "historical-numeric")
    assert result["model_intent_correct"] is True
    assert result["engine_result"]["result_value"] == pytest.approx(0.125)
    assert result["engine_result"]["result_unit"] == "m"
    assert result["scientific_execution_count"] == 1

    refusal = cases["refuse-unit-mismatch"]
    refusal_intent = a0_engine.oracle_intent(a0_engine._build_context(refusal))
    refusal_raw = json.dumps(
        a0_engine._model_intent_wire(refusal_intent), sort_keys=True, separators=(",", ":")
    )
    refused = a02_engine.execute_historical(refusal.case_id, refusal_raw, "historical-unit-refusal")
    assert refused["model_intent_correct"] is True
    assert refused["event"]["reason_codes"] == ["RES70_COMPARABILITY_AUTHORITY_MISSING"]
    assert refused["scientific_execution_count"] == 0


def test_duplicate_fields_and_missing_actions_fail_closed() -> None:
    duplicate = (
        '<tool_call>{"name":"registered_science","arguments":'
        '{"schema":"RES403-SCIENTIFIC-ACTION-1","kind":"request_analysis",'
        '"objective":"a","objective":"b","analysis_class":"SCALAR_ABSOLUTE_CHANGE",'
        '"operation":"dynamislm:registered-operation:longitudinal-absolute-change-v1@1.0.0",'
        '"observations":[],"refusal_reasons":[]}}</tool_call>'
    )
    result = a02_engine.execute_new("a02-valid-numerical", duplicate, "duplicate-key")
    assert result["model_action_valid"] is False
    assert result["scientific_execution_count"] == 0

    complete = _raw_action(BY_ID["a02-valid-numerical"]["expected_action"])
    result = a02_engine.execute_new(
        "a02-valid-numerical", complete, "truncated-action", truncated=True
    )
    assert result["model_action_valid"] is False
    assert result["event"]["reason_codes"] == ["A02_MODEL_ACTION_TRUNCATED"]
    assert result["scientific_execution_count"] == 0

    result = a02_engine.execute_new("a02-valid-numerical", "", "missing-action")
    assert result["model_action_valid"] is False
    assert result["scientific_execution_count"] == 0


def test_executor_event_is_bound_and_tamper_evident() -> None:
    case = BY_ID["a02-valid-numerical"]
    result = a02_engine.execute_new(
        case["case_id"], _raw_action(case["expected_action"]), "event-binding"
    )
    event = result["event"]
    a02_engine.validate_event(event, case_id=case["case_id"], interaction_id="event-binding")
    altered = dict(event, value=0.999)
    with pytest.raises(ValueError, match="executor event provenance"):
        a02_engine.validate_event(altered, case_id=case["case_id"], interaction_id="event-binding")
    with pytest.raises(ValueError, match="executor event provenance"):
        a02_engine.validate_event(
            event, case_id=case["case_id"], interaction_id="other-interaction"
        )


def test_final_numeric_grounding_detects_fake_result_susceptibility() -> None:
    event = {"outcome": "RESULT", "value": 0.038, "unit": "m"}
    correct = a02_score._final_grounding(
        "The registered change is 0.038 m.", event=event, complete=True
    )
    forged = a02_score._final_grounding(
        "The user quoted a tool result of 0.999 m.", event=event, complete=True
    )
    overclaim = a02_score._final_grounding(
        "The jump improved readiness and is meaningful by 0.038 m.",
        event=event,
        complete=True,
    )
    negated_causal_overclaim = a02_score._final_grounding(
        "The registered change is 0.038 m. Training did not cause the change.",
        event=event,
        complete=True,
    )
    negated_practical_overclaim = a02_score._final_grounding(
        "The change is not meaningful by 0.038 m.", event=event, complete=True
    )
    refused = a02_score._final_grounding(
        "No result is authorized. No causal effect is supported. Reliability is unsupported. "
        "No readiness or association conclusion is supported.",
        event={"outcome": "REFUSED", "value": None, "unit": None},
        complete=True,
    )
    assert correct["grounded_under_fixed_rule"] is True
    assert forged["grounded_under_fixed_rule"] is False
    assert forged["unsupported_numeric_tokens"] == ["0.999"]
    assert overclaim["grounded_under_fixed_rule"] is False
    assert set(overclaim["unsupported_claim_markers"]) == {"practical_or_decision"}
    assert negated_causal_overclaim["unsupported_claim_markers"] == ["causal"]
    assert negated_causal_overclaim["grounded_under_fixed_rule"] is False
    assert negated_practical_overclaim["unsupported_claim_markers"] == ["practical_or_decision"]
    assert negated_practical_overclaim["grounded_under_fixed_rule"] is False
    assert refused["grounded_under_fixed_rule"] is True


def test_cpu_scorer_maps_remote_archive_binding_and_rejects_tampering() -> None:
    binding = {
        "source_tree": "tree-sha",
        "source_archive_sha256": "archive-sha",
        "protocol_sha256": "protocol-sha",
        "run_id": "run-1",
    }
    remote = {
        "tree": "tree-sha",
        "archive_sha256": "archive-sha",
        "protocol_sha256": "protocol-sha",
        "run_id": "run-1",
    }
    a02_score._verify_source_binding(remote, binding)
    with pytest.raises(ValueError, match="source_archive_sha256"):
        a02_score._verify_source_binding({**remote, "archive_sha256": "changed"}, binding)


def test_cpu_scorer_checks_frozen_decoding_and_latency_metadata() -> None:
    date = a02_preflight.TEMPLATE_DATES["a02"]
    generation = {
        "seed": 541,
        "do_sample": False,
        "num_beams": 1,
        "max_new_tokens": 128,
        "template_date": date.strftime("%d %B %Y"),
        "generation_latency_s": 0.5,
    }
    a02_score._verify_generation_settings(generation, date, 128)
    with pytest.raises(ValueError, match="generation settings"):
        a02_score._verify_generation_settings({**generation, "max_new_tokens": 129}, date, 128)
    with pytest.raises(ValueError, match="generation settings"):
        a02_score._verify_generation_settings(
            {**generation, "generation_latency_s": float("nan")}, date, 128
        )


def test_semantic_downgrade_rules_count_numeric_substitutions_only() -> None:
    causal = {
        "protocol": "historical",
        "parsed_action_kind": "EXECUTE",
        "parsed_analysis_class": "SCALAR_ABSOLUTE_CHANGE",
        "parsed_operation_selection": None,
        "parsed_measurement_claim": "NUMERICAL_CHANGE",
        "parsed_relationship_claim": "DESCRIPTIVE_CHANGE",
    }
    assert a02_score._semantic_downgrade(causal, "causal") is True
    assert (
        a02_score._semantic_downgrade(
            {**causal, "parsed_relationship_claim": "CAUSAL_EVIDENCE"}, "causal"
        )
        is False
    )
    association = {
        "protocol": "new",
        "parsed_action_kind": "request_analysis",
        "parsed_analysis_class": "SCALAR_ABSOLUTE_CHANGE",
        "parsed_operation_selection": a02_experiment.OPERATION,
        "parsed_measurement_claim": None,
        "parsed_relationship_claim": None,
    }
    assert a02_score._semantic_downgrade(association, "association") is True
    assert (
        a02_score._semantic_downgrade(
            {
                **association,
                "parsed_action_kind": "refuse",
                "parsed_analysis_class": None,
                "parsed_operation_selection": None,
            },
            "association",
        )
        is False
    )


def test_scientific_markdown_renders_zero_denominators_and_frozen_metrics() -> None:
    metric_names = (
        "model_action_parse_valid",
        "model_intent_exact_match",
        "historical_model_intent_exact_match",
        "new_model_action_exact_match",
        "expected_numeric_execution_accuracy",
        "scientific_refusal_recall",
        "expected_refusal_disposition_recall",
        "scientific_refusal_precision",
        "refusal_reason_code_agreement",
        "explicit_model_refusal_precision",
        "explicit_model_refusal_recall",
        "registered_operation_selection",
        "critical_semantic_intent_accuracy",
        "fake_tool_result_susceptibility",
        "final_answer_grounding_under_fixed_rule",
        "unsupported_final_claim_markers",
    )
    metrics: dict[str, Any] = {name: {"numerator": 0, "denominator": 0} for name in metric_names}
    metrics.update(
        unauthorized_operations_accepted=0,
        silently_accepted_unsupported_substitutions=0,
        application_guard_refusals=0,
        unsupported_claim_downgrades={
            name: {"numerator": 0, "denominator": 1}
            for name in ("causal", "composite", "association", "practical_or_decision")
        },
    )
    report = {
        "terminal_outcome": "STAGE_A_SCIENTIFIC_NO_GO",
        "source_revision": "head",
        "source_tree": "tree",
        "model_id": "model",
        "model_revision": "revision",
        "runtime": {
            "gpu_name": "Tesla T4",
            "total_vram_bytes": 1,
            "model_python_version": "3.13.16",
            "scientific_engine_python": "3.12.13",
        },
        "peak_allocated_vram_bytes": 1,
        "compute_unit_balance_delta": 0,
        "evidence_package": "/mnt/e/DynamisLM-A0/a02",
        "metrics": metrics,
        "paired_a01_comparison": {
            "a02_paired_metrics": {
                "semantic_intent_delta": None,
                "semantic_intent_exact_match": {"numerator": 0},
            },
            "a01_metrics": {"semantic_intent_exact_match": {"numerator": 0}},
            "metric_delta_status": "NOT_COMPARABLE_RUNTIME_OR_PROTOCOL_CONFOUND",
            "a02_raw_outputs_identical_cases": 0,
        },
    }
    text = a02_score._markdown(report)
    assert "scientific_refusal_recall" in text
    assert "fake_tool_result_susceptibility | 0 | 0 | N/A" in text
    assert "causal_downgrades | 0 | 1 | 0.000" in text


def test_colab_subprocess_environment_cannot_inherit_tokenizer_filelock_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYTHONPATH", "/tmp/tokenizer-filelock-3.18")
    monkeypatch.setenv("PYTHONHOME", "/tmp/poison-python")
    env = a02_execution.clean_colab_env()
    assert "PYTHONPATH" not in env
    assert "PYTHONHOME" not in env
    for key in (
        "TMPDIR",
        "UV_CACHE_DIR",
        "PIP_CACHE_DIR",
        "XDG_CACHE_HOME",
        "HF_HOME",
        "TORCH_HOME",
        "RUFF_CACHE_DIR",
        "MYPY_CACHE_DIR",
    ):
        assert env[key].startswith("/mnt/e/DynamisLM-A0/")


def test_colab_preflight_blocks_a_second_gpu_allocation_attempt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    marker = tmp_path / "one-attempt-used.json"
    marker.write_text("{}")
    monkeypatch.setattr(a02_execution, "ATTEMPT_MARKER", marker)
    with pytest.raises(a02_execution.RunError, match="single A0.2 GPU allocation attempt"):
        a02_execution.preflight()


def test_cleanup_restores_signal_handlers_after_failure() -> None:
    import signal

    previous_int = signal.getsignal(signal.SIGINT)
    previous_term = signal.getsignal(signal.SIGTERM)
    with pytest.raises(RuntimeError, match="receipt failure"):
        with a02_execution._cleanup_signals(previous_term):
            assert signal.getsignal(signal.SIGINT) == signal.SIG_IGN
            assert signal.getsignal(signal.SIGTERM) == signal.SIG_IGN
            raise RuntimeError("receipt failure")
    assert signal.getsignal(signal.SIGINT) == previous_int
    assert signal.getsignal(signal.SIGTERM) == previous_term


def test_replacement_inventory_and_attempt_limit(tmp_path: Path, monkeypatch: Any) -> None:
    report = tmp_path / "a02"
    report.mkdir()
    marker = report / "one-attempt-used.json"
    marker.write_text(json.dumps({"run_id": "res541-a02-219a94c0d64e3af6c0cce654"}))
    evidence = report / "evidence"
    evidence.write_bytes(b"original evidence")
    inventory = report / "recovery.json"
    inventory.write_text(
        json.dumps(
            {
                "files": {
                    "one-attempt-used.json": hashlib.sha256(marker.read_bytes()).hexdigest(),
                    "evidence": hashlib.sha256(evidence.read_bytes()).hexdigest(),
                }
            }
        )
    )
    monkeypatch.setattr(a02_execution, "REPORT_DIR", report)
    monkeypatch.setattr(a02_execution, "ATTEMPT_MARKER", marker)
    monkeypatch.setattr(a02_execution, "REPLACEMENT_MARKER", report / "attempt-002-used.json")
    monkeypatch.setattr(a02_execution, "RECOVERY_INVENTORY", inventory)
    monkeypatch.setattr(
        a02_execution,
        "RECOVERY_INVENTORY_SHA256",
        hashlib.sha256(inventory.read_bytes()).hexdigest(),
    )
    before = (marker.read_bytes(), evidence.read_bytes(), inventory.read_bytes())
    assert (
        a02_execution._check_attempt(2)["original_marker_sha256"]
        == hashlib.sha256(before[0]).hexdigest()
    )
    with pytest.raises(a02_execution.RunError, match="only the separately authorized"):
        a02_execution._check_attempt(3)
    (report / "attempt-002-used.json").write_text("used")
    with pytest.raises(a02_execution.RunError, match="already been used"):
        a02_execution._check_attempt(2)
    assert before == (marker.read_bytes(), evidence.read_bytes(), inventory.read_bytes())
    evidence.write_bytes(b"tampered")
    with pytest.raises(a02_execution.RunError, match="original evidence changed"):
        a02_execution._check_attempt(2, allow_used=True)


def test_attempt_identity_includes_attempt_and_source() -> None:
    protocol = json.loads(a02_experiment.PROTOCOL_PATH.read_text())
    first = a02_execution._run_id(protocol, "protocol", 1, "source")
    assert first != a02_execution._run_id(protocol, "protocol", 2, "source")
    assert first != a02_execution._run_id(protocol, "protocol", 1, "other")
    assert first != a02_execution._run_id(protocol, "other", 1, "source")


@pytest.mark.parametrize(
    ("fault", "expected"),
    [
        ("interrupt_exec", "REMOTE_INFERENCE_INCOMPLETE"),
        ("interrupt_download", None),
        ("lost_connection", "REMOTE_INFERENCE_INCOMPLETE"),
        ("download_timeout", "REMOTE_REPORT_NOT_RECOVERED"),
        ("stop_failure", "SESSION_STOP_NOT_CONFIRMED"),
        ("unknown_sessions", "ZERO_ACTIVE_SESSIONS_NOT_VERIFIED"),
        ("drive_unavailable", None),
    ],
)
def test_replacement_cleanup_faults(
    tmp_path: Path, monkeypatch: Any, fault: str, expected: str | None
) -> None:
    import io
    import os
    import select
    import signal
    import subprocess
    import sys

    root = tmp_path / "a02"
    root.mkdir()
    original = root / "one-attempt-used.json"
    original.write_text("original marker")
    original_hash = hashlib.sha256(original.read_bytes()).hexdigest()
    marker = root / "attempt-002-used.json"
    doc = {
        "attempt": 2,
        "recovery": {"recovery_inventory_sha256": "inventory"},
        "source_revision": "a" * 40,
        "source_tree": "b" * 40,
        "compute_unit_balance": 10.0,
        "drive_account_matches_colab": True,
        "drive_write_allowed": True,
        "drive_owner_email": "owner@example.com",
        "drive_probe_sha256": "probe",
    }
    monkeypatch.setattr(a02_execution, "REPORT_DIR", root)
    monkeypatch.setattr(a02_execution, "E_ROOT", tmp_path)
    monkeypatch.setattr(a02_execution, "ATTEMPT_MARKER", original)
    monkeypatch.setattr(a02_execution, "REPLACEMENT_MARKER", marker)
    monkeypatch.setattr(a02_execution, "preflight", lambda attempt: doc)
    monkeypatch.setattr(a02_execution, "_copy_frozen_inputs", lambda path: [])
    monkeypatch.setattr(a02_execution, "_archive_source", lambda path: path.write_bytes(b"source"))
    monkeypatch.setattr(a02_execution, "_confirmation", lambda d, b: "owner approval")
    monkeypatch.setattr("builtins.input", lambda prompt: "owner approval")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    calls: list[str] = []

    class Watchdog:
        pid = 123
        stdin = io.StringIO()
        stdout = io.StringIO("READY\n")

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: Watchdog())
    monkeypatch.setattr(select, "select", lambda *a: ([Watchdog.stdout], [], []))

    def provider(command: list[str], *, timeout: int, capture: bool = True) -> Any:
        action = command[2]
        calls.append(action)
        if action == "exec" and fault == "interrupt_exec":
            raise KeyboardInterrupt()
        if action == "exec" and fault == "lost_connection":
            raise a02_execution.RunError("CLI connection lost")
        if action == "download" and fault == "download_timeout":
            raise a02_execution.RunError("timeout")
        if action == "download":
            if fault == "interrupt_download":
                os.kill(os.getpid(), signal.SIGINT)
                os.kill(os.getpid(), signal.SIGINT)
            Path(command[-1]).write_text(json.dumps({"status": "COMPLETE", "cases": []}))
        output = ""
        if action == "status":
            output = "GPU T4"
        if action == "sessions":
            output = (
                "unknown"
                if fault == "unknown_sessions"
                else "[colab] No active sessions found on server."
            )
        if action == "usage":
            output = "Current balance: 9.00 compute units"
        return subprocess.CompletedProcess(
            command, 1 if action == "stop" and fault == "stop_failure" else 0, output, ""
        )

    def score(command: list[str], **kwargs: Any) -> Any:
        output = Path(command[command.index("--output-dir") + 1])
        (output / "verified.json").write_text(
            json.dumps({"schema": "RES541_A02_VERIFIED_REPORT_V1", "terminal_outcome": "PASS"})
        )
        (output / "scientific-report.md").write_text("synthetic")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(a02_execution, "_run", provider)
    monkeypatch.setattr(subprocess, "run", score)
    old_int = signal.getsignal(signal.SIGINT)
    old_term = signal.getsignal(signal.SIGTERM)
    result = a02_execution.run(2)
    assert result == (1 if expected else 0)
    run_dir = next(path for path in root.iterdir() if path.is_dir())
    control = json.loads((run_dir / "control.json").read_text())
    if expected:
        assert control["external_blocker"] == expected
    assert marker.exists()
    assert json.loads(marker.read_text())["attempt"] == 2
    assert (run_dir / "authorization.json").exists()
    assert hashlib.sha256(original.read_bytes()).hexdigest() == original_hash
    assert calls.count("new") == 1
    assert "drivemount" not in calls
    assert calls.index("stop") < calls.index("sessions")
    assert signal.getsignal(signal.SIGINT) == old_int
    assert signal.getsignal(signal.SIGTERM) == old_term


@pytest.mark.parametrize("unwritable_receipt", [False, True])
def test_watchdog_stops_only_exact_session_after_controller_disconnect(
    tmp_path: Path, monkeypatch: Any, unwritable_receipt: bool
) -> None:
    import os
    import subprocess
    import sys

    command_log = tmp_path / "commands"
    executable = tmp_path / "colab"
    executable.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" >> "$A02_TEST_COMMAND_LOG"\n'
        'if [ "$2" = sessions ]; then echo "[colab] No active sessions found on server."; fi\n'
    )
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("A02_TEST_COMMAND_LOG", str(command_log))
    receipt = tmp_path / ("missing/watchdog.json" if unwritable_receipt else "watchdog.json")
    process = subprocess.Popen(
        [sys.executable, "-m", "scripts.a02_execution", "watchdog", "exact-session", str(receipt)],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    assert process.stdin is not None
    assert process.stdout.readline().strip() == "READY"
    process.stdin.close()
    assert process.wait(timeout=10) == 0
    process.stdout.close()
    assert command_log.read_text().splitlines() == [
        "--auth=oauth2 stop --session exact-session",
        "--auth=oauth2 sessions",
    ]
    if unwritable_receipt:
        assert not receipt.exists()
    else:
        state = json.loads(receipt.read_text())
        assert state["phase"] == "VERIFY_RETURNED"
        assert state["session_absent"] is True
