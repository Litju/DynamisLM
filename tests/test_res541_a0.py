from __future__ import annotations

import hashlib
import json
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from jinja2 import Environment, nodes
from jinja2.ext import Extension
from jinja2.parser import Parser
from scripts import a0_colab, a0_colab_entry, a0_colab_inference, a0_engine


class _GenerationExtension(Extension):
    # Jinja reads extension tags from this class attribute during registration.
    tags = {"generation"}  # noqa: RUF012

    def parse(self, parser: Parser) -> nodes.CallBlock:
        lineno = next(parser.stream).lineno
        body = parser.parse_statements(("name:endgeneration",), drop_needle=True)
        node = nodes.CallBlock(self.call_method("_identity"), [], [], body)
        node.set_lineno(lineno)
        return node

    def _identity(self, caller: Callable[[], str]) -> str:
        return caller()


def _oracle_outputs() -> dict[str, object]:
    model_cases: list[dict[str, object]] = []
    for case in a0_engine.load_cases():
        context = a0_engine._build_context(case)
        model_cases.append(
            {
                "case_id": case.case_id,
                "raw_text": json.dumps(
                    a0_engine._model_intent_wire(a0_engine.oracle_intent(context)),
                    separators=(",", ":"),
                ),
                "prompt_sha256": "0" * 64,
                "prompt_tokens": 32,
                "generated_tokens": 18,
                "latency_ms": 100.0,
                "first_token_latency_ms": 20.0,
                "failure_category": None,
            }
        )
    return {
        "schema": a0_engine.OUTPUT_SCHEMA,
        "status": "COMPLETE",
        "intent_schema": a0_engine.INTENT_SCHEMA,
        "model_id": "HuggingFaceTB/SmolLM3-3B",
        "model_revision": "a07cc9a04f16550a088caea529712d1d335b0ac1",
        "cases": model_cases,
    }


def test_a0_cpu_oracle_exercises_exact_operation_and_registered_refusals() -> None:
    cases = a0_engine.load_cases()
    assert len(cases) == 16
    report = a0_engine.score_outputs(_oracle_outputs(), source_revision="a" * 40)

    assert report["status"] == "PASS"
    assert report["scope"] == "SYNTHETIC_DEVELOPMENT_ONLY"
    metrics = report["metrics"]
    assert isinstance(metrics, dict)
    assert metrics["typed_intent_valid"] == {"numerator": 16, "denominator": 16}
    assert metrics["registered_tool_dispatch_success"] == {"numerator": 7, "denominator": 7}
    assert metrics["refusal_precision"] == {
        "true_positive": 9,
        "false_positive": 0,
        "denominator": 9,
    }
    assert metrics["refusal_recall"] == {
        "true_positive": 9,
        "false_negative": 0,
        "denominator": 9,
    }
    rows = report["cases"]
    assert isinstance(rows, list)
    assert all(row["outcome_matches_expectation"] for row in rows)
    assert all(row["intent_matches_expectation"] for row in rows)
    assert all(row["result_value"] is None for row in rows if row["outcome"] == "REFUSED")


def test_invalid_model_output_stays_a_safety_fallback_not_a_scientific_refusal() -> None:
    outputs = _oracle_outputs()
    model_cases = cast(list[dict[str, object]], outputs["cases"])
    cases_by_id = {str(item["case_id"]): item for item in model_cases}
    expected_refusal = next(
        case for case in a0_engine.load_cases() if case.expectation.outcome == "REFUSED"
    )
    expected_result = next(
        case for case in a0_engine.load_cases() if case.expectation.outcome == "RESULT"
    )
    cases_by_id[expected_refusal.case_id]["raw_text"] = "{"
    cases_by_id[expected_result.case_id]["raw_text"] = "{"

    report = a0_engine.score_outputs(outputs, source_revision="d" * 40)
    rows = cast(list[dict[str, object]], report["cases"])
    rows_by_id = {str(row["case_id"]): row for row in rows}
    metrics = cast(dict[str, object], report["metrics"])

    assert rows_by_id[expected_refusal.case_id]["outcome"] == "REFUSED"
    assert rows_by_id[expected_refusal.case_id]["reason_codes"] == ("A0_MODEL_INTENT_INVALID",)
    assert metrics["refusal_precision"] == {
        "true_positive": 8,
        "false_positive": 0,
        "denominator": 8,
    }
    assert metrics["refusal_recall"] == {
        "true_positive": 8,
        "false_negative": 1,
        "denominator": 9,
    }
    assert metrics["model_output_parse_invalid"] == {"numerator": 2, "denominator": 16}


def test_model_output_cannot_supply_a_number_or_extra_field() -> None:
    outputs = _oracle_outputs()
    model_cases = outputs["cases"]
    assert isinstance(model_cases, list)
    model_cases[0]["raw_text"] = json.dumps(
        {
            **json.loads(str(model_cases[0]["raw_text"])),
            "value": 999.0,
        }
    )

    report = a0_engine.score_outputs(outputs, source_revision="b" * 40)
    rows = cast(list[dict[str, object]], report["cases"])
    first = rows[0]

    assert first["outcome"] == "REFUSED"
    assert first["reason_codes"] == ("A0_MODEL_INTENT_INVALID",)
    assert first["result_value"] is None
    assert first["analysis_dispatched"] is False


def test_swapped_entry_references_fail_closed_after_authorization() -> None:
    outputs = _oracle_outputs()
    model_cases = outputs["cases"]
    assert isinstance(model_cases, list)
    intent = json.loads(str(model_cases[0]["raw_text"]))
    intent["b"], intent["f"] = (
        intent["f"],
        intent["b"],
    )
    model_cases[0]["raw_text"] = json.dumps(intent)

    report = a0_engine.score_outputs(outputs, source_revision="c" * 40)
    rows = cast(list[dict[str, object]], report["cases"])
    first = rows[0]

    assert first["outcome"] == "REFUSED"
    codes = cast(tuple[str, ...], first["reason_codes"])
    assert "RES70_REGISTRY_INTEGRITY_FAILURE" in codes
    assert first["result_value"] is None


def test_unknown_analysis_class_is_rejected_by_typed_boundary() -> None:
    case = a0_engine.load_cases()[0]
    context = a0_engine._build_context(case)
    intent = a0_engine._model_intent_wire(a0_engine.oracle_intent(context))
    intent["a"] = "MODEL_WRITTEN_PYTHON"

    with pytest.raises(ValueError, match="typed value"):
        a0_engine.parse_model_intent(json.dumps(intent))


@pytest.mark.parametrize("version", [True, 1.0, "1", 2])
def test_intent_schema_version_must_be_the_integer_one(version: object) -> None:
    case = a0_engine.load_cases()[0]
    intent = a0_engine._model_intent_wire(a0_engine.oracle_intent(a0_engine._build_context(case)))
    intent["v"] = version  # type: ignore[assignment]

    with pytest.raises(ValueError, match="typed value"):
        a0_engine.parse_model_intent(json.dumps(intent))


def test_colab_quota_gate_requires_positive_balance_and_no_active_assignment() -> None:
    usage = "Current balance: 262.07 compute units\nActive assignments: 0"
    assert a0_colab._parse_usage_output(usage) == "262.07"
    assert a0_colab._confirmation_phrase("262.07").endswith(
        "max=900s | cases=16 | tokens=64 | gpu=T4"
    )
    with pytest.raises(a0_colab.RunError, match="positive compute-unit balance"):
        a0_colab._parse_usage_output("Current balance: 0.00 compute units\nActive assignments: 0")
    with pytest.raises(a0_colab.RunError, match="active assignment"):
        a0_colab._parse_usage_output("Current balance: 262.07 compute units\nActive assignments: 1")
    assert a0_colab._is_mission_branch("res-541-a0", f"origin/{a0_colab.BRANCH}")
    assert not a0_colab._is_mission_branch("other-work", "origin/main")


@pytest.mark.parametrize(
    ("status", "runner_exit", "stop_exit", "session_listed", "error"),
    [
        ("NO_GO", 1, 1, True, "teardown could not be verified"),
        ("UNKNOWN", 0, 0, False, "unknown status"),
    ],
)
def test_colab_run_requires_teardown_and_known_report_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    runner_exit: int,
    stop_exit: int,
    session_listed: bool,
    error: str,
) -> None:
    revision = "e" * 40
    run_id: str | None = None
    monkeypatch.setattr(a0_colab, "_check_clean_pushed_revision", lambda: revision)
    monkeypatch.setattr(a0_colab, "_case_count", lambda: 16)
    monkeypatch.setattr(a0_colab, "_usage", lambda: ("100.0", ""))
    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt: a0_colab._confirmation_phrase("100.0"),
    )

    def fake_run(
        command: list[str],
        *,
        cwd: Path,
        check: bool,
        capture_output: bool = False,
        text: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal run_id
        if command[1] == "version":
            return subprocess.CompletedProcess(command, 0, "Version: 0.7.5", "")
        if command[2] == "run":
            run_id = command[6]
            return subprocess.CompletedProcess(command, runner_exit, "", "")
        if command[2] == "download":
            report_path = Path(command[-1])
            report_path.write_text(
                json.dumps(
                    {
                        "schema": a0_colab.REPORT_SCHEMA,
                        "status": status,
                        "source_revision": revision,
                        "cases": [],
                    }
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[2] == "stop":
            return subprocess.CompletedProcess(command, stop_exit, "", "")
        if command[2] == "sessions":
            output = str(run_id) if session_listed and run_id is not None else ""
            return subprocess.CompletedProcess(command, 0, output, "")
        raise AssertionError(f"unexpected Colab command: {command!r}")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(a0_colab.RunError, match=error):
        a0_colab.run(tmp_path)


def test_colab_model_prompt_preparation_stays_within_the_approved_case_bound(
    tmp_path: Path,
) -> None:
    path = tmp_path / "prepared.json"
    path.write_text(json.dumps(a0_engine.prepare_cases()), encoding="utf-8")

    cases = a0_colab_inference._load_prepared(path)

    assert len(cases) == 16
    assert all("Available synthetic evidence:" in case["user_message"] for case in cases)


def test_token_streamer_ignores_prompt_and_times_first_generated_token() -> None:
    streamer = a0_colab_inference.TimingStreamer()
    streamer.put(object())
    assert streamer.first_token_at is None
    streamer.put(object())
    assert streamer.first_token_at is not None


def test_pinned_uv_check_accepts_build_metadata_but_requires_the_exact_release() -> None:
    assert a0_colab_entry._uv_version_matches("uv 0.12.2 (x86_64-unknown-linux-gnu)", "0.12.2")
    assert not a0_colab_entry._uv_version_matches("uv 0.12.20 (x86_64-unknown-linux-gnu)", "0.12.2")


def test_pinned_smollm3_template_uses_no_thinking_mode_on_cpu() -> None:
    template_path = Path(__file__).parent / "fixtures" / "a0" / "smollm3_chat_template.jinja"
    template = template_path.read_text(encoding="utf-8")
    assert hashlib.sha256(template.encode("utf-8")).hexdigest() == (
        "4e618188ce6320b8de679a0eddd11072bc58a6cc03a24f09db4cd4bad62274c7"
    )

    class CpuTokenizer:
        def apply_chat_template(
            self,
            messages: list[dict[str, str]],
            *,
            tokenize: bool,
            add_generation_prompt: bool,
            return_dict: bool,
            return_tensors: str,
            enable_thinking: bool,
        ) -> str:
            assert (tokenize, return_dict, return_tensors) == (True, True, "pt")
            environment = Environment(extensions=[_GenerationExtension])
            return environment.from_string(template).render(
                messages=messages,
                add_generation_prompt=add_generation_prompt,
                enable_thinking=enable_thinking,
                strftime_now=lambda _format: "22 October 2026",
            )

    prompt = a0_colab_inference._apply_chat_template(
        CpuTokenizer(),
        [
            {"role": "system", "content": a0_colab_inference.SYSTEM_PROMPT},
            {"role": "user", "content": "synthetic CPU template check"},
        ],
    )

    assert "Reasoning Mode: /no_think" in prompt
    assert "Reasoning Mode: /think" not in prompt
    assert prompt.endswith("<|im_start|>assistant\n<think>\n\n</think>\n")


def test_remote_subprocess_failure_diagnostic_is_bounded_and_scrubbed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    long_stdout = "verbose " * 400
    stderr = (
        "Authorization: Bearer opaque-secret\n"
        "oauth_token=private-refresh-value\n"
        "OAuth credential leaked: private-oauth-key\n"
        "download failed: /cache/model-00001-of-00002.safetensors"
    )

    def failed_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 17, long_stdout, stderr)

    monkeypatch.setattr(subprocess, "run", failed_run)
    with pytest.raises(a0_colab_entry.A0Error) as caught:
        a0_colab_entry._run(
            ["installer"],
            cwd=None,
            env=None,
            deadline=time.monotonic() + 60,
            timeout=10,
            stage="INFERENCE_ENVIRONMENT",
        )

    error = caught.value
    assert error.stage == "INFERENCE_ENVIRONMENT"
    assert error.subprocess_exit_code == 17
    diagnostic = cast(str, error.subprocess_diagnostic)
    assert len(diagnostic) <= a0_colab_entry.MAX_SUBPROCESS_DIAGNOSTIC_CHARS
    assert "opaque-secret" not in diagnostic
    assert "private-refresh-value" not in diagnostic
    assert "private-oauth-key" not in diagnostic
    assert "model-00001-of-00002.safetensors" not in diagnostic
    assert "[MODEL_FILE_REDACTED]" in diagnostic

    report_path = tmp_path / "failure.json"
    a0_colab_entry._write_failure(
        report_path,
        revision="f" * 40,
        stage=error.stage,
        category=error.category,
        elapsed_seconds=1.0,
        preflight=None,
        model_download_stage_entered=False,
        subprocess_exit_code=error.subprocess_exit_code,
        subprocess_diagnostic=error.subprocess_diagnostic,
    )
    failure = cast(dict[str, object], json.loads(report_path.read_text(encoding="utf-8")))[
        "subprocess_failure"
    ]
    assert failure == {
        "stage": "INFERENCE_ENVIRONMENT",
        "exit_code": 17,
        "diagnostic": diagnostic,
    }

    def missing_executable(
        _command: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("bootstrap tool is missing")

    monkeypatch.setattr(subprocess, "run", missing_executable)
    with pytest.raises(a0_colab_entry.A0Error) as launch_failure:
        a0_colab_entry._run(
            ["missing-tool"],
            cwd=None,
            env=None,
            deadline=time.monotonic() + 60,
            timeout=10,
            stage="PYTHON_312_BOOTSTRAP",
        )
    assert launch_failure.value.category == "SUBPROCESS_LAUNCH_FAILED"
    assert launch_failure.value.subprocess_exit_code is None
    assert launch_failure.value.subprocess_diagnostic is not None
    assert "bootstrap tool is missing" in launch_failure.value.subprocess_diagnostic
