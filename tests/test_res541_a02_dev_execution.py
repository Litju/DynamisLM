from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from scripts import a02_dev_execution, a02_execution


def test_run_refuses_missing_one_time_authorization_before_colab_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(a02_dev_execution, "AUTHORIZATION_PATH", tmp_path / "authorization.json")
    monkeypatch.setattr(
        a02_dev_execution,
        "_run_colab",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Colab must not be called")),
    )

    with pytest.raises(a02_dev_execution.DevelopmentRunError, match="one-time V2 campaign"):
        a02_dev_execution.run_campaign_session()


@pytest.mark.parametrize(
    ("remaining", "rate", "expected"),
    [
        (2.0, 4.0, 720),
        (1.0, 8.0, 337),
        (0.2, 10.0, 0),
    ],
)
def test_exec_bound_respects_remaining_cu_budget(
    remaining: float, rate: float, expected: int
) -> None:
    assert a02_dev_execution._safe_exec_seconds(remaining, rate) == expected


def test_exec_bound_fails_closed_on_unknown_usage_rate() -> None:
    with pytest.raises(a02_dev_execution.DevelopmentRunError, match="ambiguous"):
        a02_dev_execution._safe_exec_seconds(1.0, 0.0)


@pytest.mark.parametrize("seconds", [210, 618, 720])
def test_remote_stage_timeouts_stay_within_campaign_exec_budget(seconds: int) -> None:
    stages = a02_dev_execution._split_stage_timeouts(seconds)
    assert sum(stages.values()) == seconds
    assert 30 <= stages["prepare"] <= a02_dev_execution.REMOTE_PREPARE_MAX_SECONDS
    assert 30 <= stages["infer"] <= a02_dev_execution.REMOTE_INFERENCE_MAX_SECONDS


def test_remote_stage_budget_too_small_fails_closed() -> None:
    with pytest.raises(a02_dev_execution.DevelopmentRunError, match="both V2 stages"):
        a02_dev_execution._split_stage_timeouts(209)


def test_v2_profile_cannot_be_retried_after_a_session_marker() -> None:
    with pytest.raises(a02_dev_execution.DevelopmentRunError, match="single-use"):
        a02_dev_execution._next_session_index([{"run_id": "prior-v2-session"}])


def test_campaign_authorization_record_is_hash_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "authorization.json"
    source = {
        "source_revision": "c" * 40,
        "profile_sha256": "a" * 64,
        "preflight_sha256": "b" * 64,
    }
    balance = {"balance": 10.0}
    confirmation = a02_dev_execution._authorization_phrase(source, balance)
    document: dict[str, Any] = {
        "schema": "RES541_A02_DEVELOPMENT_CAMPAIGN_AUTHORIZATION_V1",
        "status": "OWNER_AUTHORIZED",
        "branch": "work/res-541-a02-colab-recovery",
        "source_revision": source["source_revision"],
        "source_tree": "d" * 40,
        "development_profile_sha256": source["profile_sha256"],
        "development_preflight_sha256": source["preflight_sha256"],
        "campaign_cap_cu": 2.0,
        "max_t4_sessions": 2,
        "max_session_seconds": 900,
        "max_exec_seconds": 720,
        "no_upgrade": True,
        "no_training": True,
        "initial_compute_unit_balance": balance["balance"],
        "owner_confirmation": confirmation,
        "owner_confirmation_sha256": hashlib.sha256(confirmation.encode()).hexdigest(),
    }
    document["authorization_sha256"] = hashlib.sha256(
        json.dumps(document, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    path.write_text(json.dumps(document))
    monkeypatch.setattr(a02_dev_execution, "AUTHORIZATION_PATH", path)

    assert a02_dev_execution._load_authorization()["status"] == "OWNER_AUTHORIZED"
    document["campaign_cap_cu"] = 200.0
    path.write_text(json.dumps(document))
    with pytest.raises(a02_dev_execution.DevelopmentRunError, match="integrity"):
        a02_dev_execution._load_authorization()


def test_colab_timeout_preserves_sanitized_partial_streams(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def timeout(*_args: Any, **_kwargs: Any) -> None:
        raise subprocess.TimeoutExpired(
            "colab exec",
            30,
            output=b"partial output",
            stderr=b"token=secret-value https://signed.example/x",
        )

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(a02_dev_execution.ColabCommandError) as caught:
        a02_dev_execution._run_colab(["colab", "--auth=oauth2", "exec"], timeout=30)
    assert caught.value.stdout_tail == "partial output"
    assert "[REDACTED]" in caught.value.stderr_tail
    assert "[URL_REDACTED]" in caught.value.stderr_tail
    assert "secret-value" not in caught.value.stderr_tail


def test_prepare_timeout_recovers_bound_partial_report_before_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = {
        "source_revision": "a" * 40,
        "source_tree": "b" * 40,
        "profile_sha256": "c" * 64,
        "preflight_sha256": "d" * 64,
    }
    report = {
        "status": "EXTERNAL_BLOCKER",
        "source": {
            "run_id": "run-001",
            "revision": source["source_revision"],
            "tree": source["source_tree"],
            "development_profile_sha256": source["profile_sha256"],
            "development_preflight_sha256": source["preflight_sha256"],
        },
        "current_stage": "INFERENCE_DEPENDENCIES",
        "cases": [],
    }
    calls: list[list[str]] = []

    def run(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[2] == "exec":
            raise a02_dev_execution.ColabCommandError(
                command,
                timeout=timeout,
                stdout="install stdout partial",
                stderr="install stderr partial",
            )
        assert command[2] == "download"
        Path(command[-1]).write_text(json.dumps(report))
        return subprocess.CompletedProcess(command, 0, "downloaded", "")

    monkeypatch.setattr(a02_dev_execution, "_run_colab", run)
    state: dict[str, Any] = {}
    local_report = tmp_path / "remote-prepare-report.json"
    control_path = tmp_path / "control.json"
    with pytest.raises(a02_dev_execution.ColabCommandError):
        a02_dev_execution._run_remote_stage(
            run_id="run-001",
            stage="prepare",
            timeout=60,
            report_path=local_report,
            source=source,
            control_path=control_path,
            state=state,
        )
    assert local_report.is_file()
    assert state["command_failure"]["stdout_tail"] == "install stdout partial"
    assert state["remote_stages"]["prepare"]["report_status"] == "EXTERNAL_BLOCKER"
    assert calls[0][5:7] == ["--env", "A02_DEV_REMOTE_STAGE=prepare"]
    assert "A02_DEV_REMOTE_STAGE_TIMEOUT=60" in calls[0]


@pytest.mark.parametrize("report_status", ["RUNNING", "EXTERNAL_BLOCKER"])
def test_incomplete_prepare_report_blocks_inference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, report_status: str
) -> None:
    source = {
        "source_revision": "a" * 40,
        "source_tree": "b" * 40,
        "profile_sha256": "c" * 64,
        "preflight_sha256": "d" * 64,
    }
    report = {
        "status": report_status,
        "source": {
            "run_id": "run-002",
            "revision": source["source_revision"],
            "tree": source["source_tree"],
            "development_profile_sha256": source["profile_sha256"],
            "development_preflight_sha256": source["preflight_sha256"],
        },
        "cases": [],
    }
    calls: list[list[str]] = []

    def run(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[2] == "download":
            Path(command[-1]).write_text(json.dumps(report))
        return subprocess.CompletedProcess(command, 0, "ok", "")

    monkeypatch.setattr(a02_dev_execution, "_run_colab", run)
    ready = a02_dev_execution._run_remote_stage(
        run_id="run-002",
        stage="prepare",
        timeout=60,
        report_path=tmp_path / "prepare.json",
        source=source,
        control_path=tmp_path / "control.json",
        state={},
    )
    assert ready is False
    assert [command[2] for command in calls] == ["exec", "download"]


def test_missing_remote_report_is_not_recovered_or_scored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = {
        "source_revision": "a" * 40,
        "source_tree": "b" * 40,
        "profile_sha256": "c" * 64,
        "preflight_sha256": "d" * 64,
    }
    monkeypatch.setattr(
        a02_dev_execution,
        "_run_colab",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 1, "", "missing"),
    )
    state: dict[str, Any] = {}
    report = a02_dev_execution._download_stage_report(
        run_id="run-003",
        stage="prepare",
        local_path=tmp_path / "missing.json",
        source=source,
        control_path=tmp_path / "control.json",
        state=state,
    )
    assert report is None
    assert state["remote_stages"]["prepare"]["report_recovered"] is False


@pytest.mark.parametrize("status", ["RUNNING", "READY_FOR_INFERENCE", "EXTERNAL_BLOCKER"])
def test_partial_or_failed_reports_are_never_complete(
    status: str,
) -> None:
    source = {
        "source_revision": "a" * 40,
        "source_tree": "b" * 40,
        "profile_sha256": "c" * 64,
        "preflight_sha256": "d" * 64,
    }
    report = {
        "status": status,
        "source": {
            "run_id": "run",
            "revision": source["source_revision"],
            "tree": source["source_tree"],
            "development_profile_sha256": source["profile_sha256"],
            "development_preflight_sha256": source["preflight_sha256"],
        },
        "cases": [{"case_id": "partial"}],
    }
    assert not a02_dev_execution._remote_report_is_complete(report, "run", source)
    assert not a02_dev_execution._remote_report_is_complete([], "run", source)


def test_target_shutdown_names_only_the_allocated_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[list[str]] = []

    def run(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
        observed.append(command)
        return subprocess.CompletedProcess(command, 0, "stopped", "")

    monkeypatch.setattr(a02_dev_execution, "_run_colab", run)
    a02_dev_execution._stop_exact_session("allocated-target")
    assert observed == [["colab", "--auth=oauth2", "stop", "--session", "allocated-target"]]


def test_exact_target_absence_allows_an_unrelated_session_to_remain() -> None:
    cli = subprocess.CompletedProcess(
        ["colab", "sessions"],
        0,
        "[unrelated] gpu-a100-s-other | Hardware: A100 | Shape: Standard | Variant: GPU",
        "",
    )
    assignments = subprocess.CompletedProcess(
        ["provider-assignments"],
        0,
        json.dumps(
            {
                "endpoint": "https://colab.research.google.com/tun/m/assignments",
                "assignments": [
                    {
                        "endpoint": "gpu-a100-s-other",
                        "accelerator": "Accelerator.A100",
                        "variant": "AssignmentVariant.GPU",
                    }
                ],
            }
        ),
        "",
    )
    assert a02_execution._verify_target_absent(
        cli, "allocated-target", "gpu-t4-s-target", assignments
    )
