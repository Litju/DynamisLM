from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from scripts import a02_dev_protocol, a02_dev_remote, a02_remote


def test_remote_generator_passes_native_tool_schema_and_enforces_profile_prompt_limit() -> None:
    class TensorRow:
        def tolist(self) -> list[int]:
            return [101, 102]

    class TensorBatch:
        def __getitem__(self, _index: int) -> TensorRow:
            return TensorRow()

    class RuntimeTokenizer:
        def __init__(self) -> None:
            self.tool_schemas: list[Any] = []

        def apply_chat_template(self, _messages: Any, *, tokenize: bool, **kwargs: Any) -> Any:
            self.tool_schemas.append(kwargs.get("xml_tools"))
            if not tokenize:
                return "<rendered>"
            return {"input_ids": TensorBatch()}

        def encode(self, _rendered: str, *, add_special_tokens: bool) -> list[int]:
            assert add_special_tokens is False
            return [101, 102]

    class RuntimeModel:
        def generate(self, **_kwargs: Any) -> None:
            raise AssertionError("generation must stop when the V2 prompt is over its bound")

    tokenizer = RuntimeTokenizer()
    schema = a02_dev_protocol.tool_schema()
    with pytest.raises(ValueError, match="exceeds its 1-token bound"):
        a02_dev_remote._generate(
            RuntimeModel(),
            tokenizer,
            object(),
            [{"role": "system", "content": "synthetic"}],
            cap=256,
            template_date=a02_dev_protocol.ACTION_TEMPLATE_DATE,
            prompt_limit=1,
            xml_tools=[schema],
        )
    assert tokenizer.tool_schemas == [[schema], [schema]]


def _remote_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    work = tmp_path / "remote-work"
    work.mkdir()
    archive = tmp_path / "source.tar"
    archive.write_bytes(b"synthetic source archive")
    report = tmp_path / "remote-report.json"
    binding_path = tmp_path / "binding.json"
    binding = {
        "execution_mode": "development_v2",
        "run_id": "res541-test-run",
        "source_revision": "a" * 40,
        "source_tree": "b" * 40,
        "source_archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "protocol_sha256": "c" * 64,
        "development_profile_sha256": "d" * 64,
        "development_preflight_sha256": "e" * 64,
        "baseline_remote_report_sha256": "f" * 64,
        "remote_stage_timeouts_seconds": {"prepare": 120, "infer": 90},
    }
    binding_path.write_text(json.dumps(binding))
    monkeypatch.setattr(a02_dev_remote, "WORK", work)
    monkeypatch.setattr(a02_dev_remote, "SOURCE_ARCHIVE", archive)
    monkeypatch.setattr(a02_dev_remote, "BINDING_PATH", binding_path)
    monkeypatch.setattr(a02_dev_remote, "REMOTE_REPORT", report)

    def extract(_archive: Path, destination: Path) -> None:
        (destination / "scripts").mkdir(parents=True)
        (destination / "scripts/a02_dev_remote.py").write_text("pass\n")

    monkeypatch.setattr(a02_dev_remote, "_safe_extract", extract)
    monkeypatch.setattr(a02_remote, "_install_uv", lambda: work / "uv-venv/bin/uv")
    monkeypatch.setattr(a02_remote, "_setup_engine", lambda *_args: work / "engine/bin/python")
    inference_python = work / "inference-venv/bin/python"
    inference_python.parent.mkdir(parents=True)
    inference_python.touch()
    monkeypatch.setattr(a02_remote, "_setup_inference", lambda *_args: inference_python)
    return {"work": work, "archive": archive, "report": report, "binding": binding}


def test_remote_prepare_timeout_retains_bootstrap_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _remote_fixture(tmp_path, monkeypatch)

    def timeout() -> None:
        raise subprocess.TimeoutExpired(
            "uv", 45, output=b"setup started", stderr=b"install pending"
        )

    monkeypatch.setattr(a02_remote, "_install_uv", timeout)
    assert a02_dev_remote._run_isolated_inference("prepare") == 1
    report = json.loads(paths["report"].read_text())
    assert report["status"] == "EXTERNAL_BLOCKER"
    assert report["failure_stage"] == "UV_SETUP"
    assert report["stage_history"][-1]["status"] == "FAILED"
    assert report["command_output"] == {
        "stdout_tail": "setup started",
        "stderr_tail": "install pending",
    }
    assert report["cases"] == []


def test_remote_dependency_install_failure_keeps_command_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _remote_fixture(tmp_path, monkeypatch)

    def fail_engine(*_args: Any) -> None:
        raise a02_remote.CommandError(["uv", "sync"], 1, "resolver failed", "ENGINE_FROZEN_SYNC")

    monkeypatch.setattr(a02_remote, "_setup_engine", fail_engine)
    assert a02_dev_remote._run_isolated_inference("prepare") == 1
    report = json.loads(paths["report"].read_text())
    assert report["status"] == "EXTERNAL_BLOCKER"
    assert report["failure_stage"] == "SCIENTIFIC_ENGINE_DEPENDENCIES"
    assert report["command_failure"]["stage"] == "ENGINE_FROZEN_SYNC"


def test_interrupted_model_download_is_retained_without_scoring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _remote_fixture(tmp_path, monkeypatch)

    def interrupted(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        report = json.loads(paths["report"].read_text())
        report.update(
            status="EXTERNAL_BLOCKER",
            current_stage="MODEL_ASSET_DOWNLOAD",
            failure_stage="MODEL_ASSET_DOWNLOAD",
            failure_category="TimeoutExpired",
            model_loaded=False,
            cases=[],
            partial_case_count=0,
        )
        a02_dev_remote._write_report(report)
        return {
            "returncode": -15,
            "timed_out": True,
            "stdout_tail": "download 37%",
            "stderr_tail": "read timeout",
        }

    monkeypatch.setattr(a02_dev_remote, "_run_bounded_child", interrupted)
    assert a02_dev_remote._run_isolated_inference("prepare") == 1
    report = json.loads(paths["report"].read_text())
    assert report["status"] == "EXTERNAL_BLOCKER"
    assert report["failure_stage"] == "MODEL_ASSET_DOWNLOAD"
    assert report["remote_stage_commands"][0]["timed_out"] is True
    assert report["model_loaded"] is False
    assert "37%" in report["remote_stage_commands"][0]["stdout_tail"]


@pytest.mark.parametrize("partial", [False, True])
def test_missing_or_partial_worker_report_cannot_become_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, partial: bool
) -> None:
    paths = _remote_fixture(tmp_path, monkeypatch)

    def incomplete(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        if partial:
            report = json.loads(paths["report"].read_text())
            report["cases"] = [{"case_id": "partial"}]
            report["current_stage"] = "MODEL_INFERENCE"
            report["partial_case_count"] = 1
            a02_dev_remote._write_report(report)
        else:
            paths["report"].unlink()
        return {"returncode": 0, "timed_out": False, "stdout_tail": "", "stderr_tail": ""}

    monkeypatch.setattr(a02_dev_remote, "_run_bounded_child", incomplete)
    assert a02_dev_remote._run_isolated_inference("prepare") == 1
    report = json.loads(paths["report"].read_text())
    assert report["status"] == "EXTERNAL_BLOCKER"
    assert report.get("terminal_outcome") is None
    assert len(report["cases"]) == int(partial)


def test_timed_out_child_is_terminated_and_keeps_sanitized_partial_output(
    tmp_path: Path,
) -> None:
    child = (
        "import sys,time; print('stdout checkpoint',flush=True); "
        "print('token=private-value',file=sys.stderr,flush=True); time.sleep(30)"
    )
    result = a02_dev_remote._run_bounded_child(
        [sys.executable, "-c", child], cwd=tmp_path, env={}, timeout=1
    )
    assert result["timed_out"] is True
    assert result["returncode"] is not None and result["returncode"] != 0
    assert result["stdout_tail"] == "stdout checkpoint\n"
    assert "[REDACTED]" in result["stderr_tail"]
    assert "private-value" not in result["stderr_tail"]


def test_initial_report_uses_campaign_binding_preflight_field() -> None:
    report = a02_dev_remote._initial_report(
        {
            "run_id": "run",
            "source_revision": "a" * 40,
            "source_tree": "b" * 40,
            "source_archive_sha256": "c" * 64,
            "protocol_sha256": "d" * 64,
            "development_preflight_sha256": "e" * 64,
            "development_profile_sha256": "f" * 64,
            "baseline_remote_report_sha256": "0" * 64,
        }
    )
    assert report["source"]["preflight_sha256"] == "e" * 64
