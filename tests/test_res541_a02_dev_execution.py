from __future__ import annotations

import builtins
import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from scripts import a02_dev_execution, a02_dev_protocol, a02_execution


def test_run_refuses_missing_one_time_authorization_before_colab_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        a02_dev_execution, "AUTHORIZATION_PATH", tmp_path / "campaign-authorization-v2.json"
    )
    monkeypatch.setattr(
        a02_dev_execution, "LEGACY_AUTHORIZATION_PATH", tmp_path / "authorization.json"
    )
    monkeypatch.setattr(
        a02_dev_execution,
        "_run_colab",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Colab must not be called")),
    )

    with pytest.raises(a02_dev_execution.DevelopmentRunError, match="campaign-level V2"):
        a02_dev_execution.run_campaign_session()


def test_legacy_source_bound_approval_cannot_authorize_modified_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        a02_dev_execution, "AUTHORIZATION_PATH", tmp_path / "campaign-authorization-v2.json"
    )
    legacy_path = tmp_path / "authorization.json"
    legacy_path.write_text("{}")
    monkeypatch.setattr(a02_dev_execution, "LEGACY_AUTHORIZATION_PATH", legacy_path)
    with pytest.raises(a02_dev_execution.DevelopmentRunError, match="legacy source-bound"):
        a02_dev_execution._load_authorization()


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


def test_campaign_budget_counts_original_usage_and_rejects_topups_or_exhaustion() -> None:
    authorization = {
        "initial_compute_unit_balance": 87.49,
        "account_balance_at_authorization": 87.32,
        "remaining_cu_at_authorization": 1.83,
    }
    prior, remaining = a02_dev_execution._campaign_budget(authorization, 87.32)
    assert prior == pytest.approx(0.17)
    assert remaining == pytest.approx(1.83)
    with pytest.raises(a02_dev_execution.DevelopmentRunError, match="ambiguous"):
        a02_dev_execution._campaign_budget(authorization, 87.40)
    with pytest.raises(a02_dev_execution.DevelopmentRunError, match="exhausted"):
        a02_dev_execution._campaign_budget(authorization, 85.39)


def _prior_session(
    runs: Path,
    *,
    index: int,
    source_revision: str,
    source_tree: str,
    profile_sha256: str,
    preflight_sha256: str,
    outcome: str,
) -> dict[str, Any]:
    run_id = f"prior-{index}"
    directory = runs / run_id
    directory.mkdir(parents=True)
    binding = {
        "run_id": run_id,
        "session_index": index,
        "source_revision": source_revision,
        "source_tree": source_tree,
        "development_profile_sha256": profile_sha256,
        "development_preflight_sha256": preflight_sha256,
    }
    binding_bytes = json.dumps(binding, sort_keys=True).encode()
    (directory / "binding.json").write_bytes(binding_bytes)
    (directory / "control.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "session_index": index,
                "status": "CONTROL_FINISHED",
                "terminal_outcome": outcome,
            }
        )
    )
    marker = {
        "schema": "RES541_A02_DEVELOPMENT_SESSION_USED_V1",
        "run_id": run_id,
        "session_index": index,
        "source_revision": source_revision,
        "source_tree": source_tree,
        "development_profile_sha256": profile_sha256,
        "development_preflight_sha256": preflight_sha256,
        "binding_sha256": hashlib.sha256(binding_bytes).hexdigest(),
    }
    marker_bytes = json.dumps(marker, sort_keys=True).encode()
    (directory / "session-used.json").write_bytes(marker_bytes)
    manifest_files = []
    for name in ("binding.json", "control.json", "session-used.json"):
        data = (directory / name).read_bytes()
        manifest_files.append(
            {"name": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        )
    (directory / "artifact-hashes.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "terminal_outcome": outcome,
                "files": manifest_files,
            }
        )
    )
    return marker


def test_external_failure_allows_only_a_new_source_bound_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    monkeypatch.setattr(a02_dev_execution, "RUNS_DIR", runs)
    markers = [
        _prior_session(
            runs,
            index=1,
            source_revision="a" * 40,
            source_tree="b" * 40,
            profile_sha256="c" * 64,
            preflight_sha256="d" * 64,
            outcome="EXTERNAL_BLOCKER",
        )
    ]
    current = {
        "source_revision": "e" * 40,
        "source_tree": "f" * 40,
        "profile_sha256": "c" * 64,
        "preflight_sha256": "0" * 64,
    }
    assert a02_dev_execution._next_session_index(markers, current) == 2
    failed = {
        **current,
        "source_revision": "a" * 40,
        "source_tree": "b" * 40,
        "preflight_sha256": "d" * 64,
    }
    with pytest.raises(a02_dev_execution.DevelopmentRunError, match="cannot be replayed"):
        a02_dev_execution._next_session_index(markers, failed)


def test_completed_experiment_blocks_another_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    monkeypatch.setattr(a02_dev_execution, "RUNS_DIR", runs)
    markers = [
        _prior_session(
            runs,
            index=1,
            source_revision="a" * 40,
            source_tree="b" * 40,
            profile_sha256="c" * 64,
            preflight_sha256="d" * 64,
            outcome="STAGE_A_SCIENTIFIC_NO_GO",
        )
    ]
    current = {
        "source_revision": "e" * 40,
        "source_tree": "f" * 40,
        "profile_sha256": "c" * 64,
        "preflight_sha256": "0" * 64,
    }
    with pytest.raises(a02_dev_execution.DevelopmentRunError, match="completed V2 experiment"):
        a02_dev_execution._next_session_index(markers, current)


def test_two_consumed_markers_exhaust_campaign_session_cap() -> None:
    with pytest.raises(a02_dev_execution.DevelopmentRunError, match="exhausted"):
        a02_dev_execution._next_session_index([{}, {}], {})


def test_followup_authorization_preserves_original_cu_cap_and_allows_one_new_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile_sha = hashlib.sha256(a02_dev_protocol.PROFILE_PATH.read_bytes()).hexdigest()
    runs = tmp_path / "runs"
    runs.mkdir()
    monkeypatch.setattr(a02_dev_execution, "RUNS_DIR", runs)
    markers = [
        _prior_session(
            runs,
            index=1,
            source_revision="a" * 40,
            source_tree="b" * 40,
            profile_sha256=profile_sha,
            preflight_sha256="c" * 64,
            outcome="EXTERNAL_BLOCKER",
        ),
        _prior_session(
            runs,
            index=2,
            source_revision="d" * 40,
            source_tree="e" * 40,
            profile_sha256=profile_sha,
            preflight_sha256="f" * 64,
            outcome="EXTERNAL_BLOCKER",
        ),
    ]
    source = {
        "branch": "work/res-541-a02-colab-recovery",
        "source_revision": "1" * 40,
        "source_tree": "2" * 40,
        "profile_sha256": profile_sha,
        "preflight_sha256": "3" * 64,
    }
    quota = {
        "balance": 87.19,
        "usage_rate_cu_per_hour": 0.0,
        "active_assignment_count": 0,
        "active_sessions": [],
        "provider_assignments": [],
        "snapshot_sha256": "4" * 64,
    }
    base_authorization = {
        "authorization_sha256": "5" * 64,
        "initial_compute_unit_balance": 87.49,
        "account_balance_at_authorization": 87.32,
        "remaining_cu_at_authorization": 1.83,
        "remaining_sessions_at_authorization": 1,
    }
    path = tmp_path / "followup-authorization-v1.json"
    monkeypatch.setattr(a02_dev_execution, "FOLLOWUP_AUTHORIZATION_PATH", path)
    monkeypatch.setattr(a02_dev_execution, "_load_authorization", lambda: base_authorization)
    monkeypatch.setattr(a02_dev_execution, "_source_state", lambda: source)
    monkeypatch.setattr(a02_dev_execution, "_colab_snapshot", lambda: quota)

    with pytest.raises(a02_dev_execution.DevelopmentRunError, match="one additional"):
        a02_dev_execution._resolve_session_scope(base_authorization, source, quota, markers)
    receipt = a02_dev_execution.authorize_followup_session("okay retry")
    scope = a02_dev_execution._resolve_session_scope(base_authorization, source, quota, markers)
    saved = json.loads(path.read_bytes())

    assert receipt["gpu_allocated"] is False
    assert saved["campaign_cap_cu"] == 2.0
    assert saved["remaining_cu_at_authorization"] == pytest.approx(1.70)
    assert saved["additional_t4_sessions"] == 1
    assert saved["previous_session_marker_sha256s"] == [
        hashlib.sha256((runs / marker["run_id"] / "session-used.json").read_bytes()).hexdigest()
        for marker in markers
    ]
    assert scope[0] is not None
    assert scope[0]["authorization_sha256"] == receipt["authorization_sha256"]
    assert scope[1] == 3
    assert scope[2] == pytest.approx(0.30)
    assert scope[3] == pytest.approx(1.70)


def test_followup_authorization_rejects_a_rebudgeted_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile_sha = hashlib.sha256(a02_dev_protocol.PROFILE_PATH.read_bytes()).hexdigest()
    runs = tmp_path / "runs"
    runs.mkdir()
    monkeypatch.setattr(a02_dev_execution, "RUNS_DIR", runs)
    markers = [
        _prior_session(
            runs,
            index=index,
            source_revision=revision,
            source_tree=tree,
            profile_sha256=profile_sha,
            preflight_sha256=preflight,
            outcome="EXTERNAL_BLOCKER",
        )
        for index, revision, tree, preflight in (
            (1, "a" * 40, "b" * 40, "c" * 64),
            (2, "d" * 40, "e" * 40, "f" * 64),
        )
    ]
    source = {
        "branch": "work/res-541-a02-colab-recovery",
        "source_revision": "1" * 40,
        "source_tree": "2" * 40,
        "profile_sha256": profile_sha,
        "preflight_sha256": "3" * 64,
    }
    quota = {
        "balance": 87.19,
        "usage_rate_cu_per_hour": 0.0,
        "active_assignment_count": 0,
        "active_sessions": [],
        "provider_assignments": [],
        "snapshot_sha256": "4" * 64,
    }
    base = {
        "authorization_sha256": "5" * 64,
        "initial_compute_unit_balance": 87.49,
        "account_balance_at_authorization": 87.32,
        "remaining_cu_at_authorization": 1.83,
    }
    path = tmp_path / "followup-authorization-v1.json"
    monkeypatch.setattr(a02_dev_execution, "FOLLOWUP_AUTHORIZATION_PATH", path)
    monkeypatch.setattr(a02_dev_execution, "_load_authorization", lambda: base)
    monkeypatch.setattr(a02_dev_execution, "_source_state", lambda: source)
    monkeypatch.setattr(a02_dev_execution, "_colab_snapshot", lambda: quota)
    a02_dev_execution.authorize_followup_session("okay retry")

    saved = json.loads(path.read_text())
    saved["remaining_cu_at_authorization"] = 2.0
    saved["authorization_sha256"] = a02_dev_execution._sha(
        a02_dev_execution._canonical(
            {k: v for k, v in saved.items() if k != "authorization_sha256"}
        ).encode()
    )
    path.write_text(json.dumps(saved))
    with pytest.raises(a02_dev_execution.DevelopmentRunError, match="scope or integrity"):
        a02_dev_execution._load_followup_authorization(base, source, quota, markers)


def test_followup_does_not_authorize_a_fourth_session() -> None:
    authorization = {
        "initial_compute_unit_balance": 87.49,
        "account_balance_at_authorization": 87.32,
        "remaining_cu_at_authorization": 1.83,
    }
    with pytest.raises(a02_dev_execution.DevelopmentRunError, match="exhausted"):
        a02_dev_execution._resolve_session_scope(
            authorization,
            {},
            {"balance": 87.19},
            [{}, {}, {}],
        )


def test_campaign_authorization_record_is_hash_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "campaign-authorization-v2.json"
    profile_sha256 = hashlib.sha256(a02_dev_protocol.PROFILE_PATH.read_bytes()).hexdigest()
    remaining_cu = 1.83
    remaining_sessions = 1
    confirmation = a02_dev_execution._campaign_authorization_phrase(
        profile_sha256, remaining_cu, remaining_sessions
    )
    document: dict[str, Any] = {
        "schema": "RES541_A02_DEVELOPMENT_CAMPAIGN_AUTHORIZATION_V2",
        "status": "OWNER_AUTHORIZED",
        "branch": "work/res-541-a02-colab-recovery",
        "development_profile_sha256": profile_sha256,
        "campaign_cap_cu": 2.0,
        "max_t4_sessions": 2,
        "max_session_seconds": 900,
        "max_exec_seconds": 720,
        "no_upgrade": True,
        "no_training": True,
        "approval_scope": "CAMPAIGN_PROFILE_WITH_PER_SESSION_SOURCE_BINDING",
        "initial_compute_unit_balance": 87.49,
        "account_balance_at_authorization": 87.32,
        "account_spend_before_authorization_cu": 0.17,
        "remaining_cu_at_authorization": remaining_cu,
        "remaining_sessions_at_authorization": remaining_sessions,
        "legacy_source_authorization_sha256": None,
        "quota_snapshot_sha256": "1" * 64,
        "owner_confirmation": confirmation,
        "owner_confirmation_sha256": hashlib.sha256(confirmation.encode()).hexdigest(),
    }
    document["authorization_sha256"] = hashlib.sha256(
        json.dumps(document, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    path.write_text(json.dumps(document))
    monkeypatch.setattr(a02_dev_execution, "AUTHORIZATION_PATH", path)
    monkeypatch.setattr(
        a02_dev_execution, "LEGACY_AUTHORIZATION_PATH", tmp_path / "authorization.json"
    )

    assert a02_dev_execution._load_authorization()["status"] == "OWNER_AUTHORIZED"
    assert "source=" not in confirmation and "preflight" not in confirmation
    document["campaign_cap_cu"] = 200.0
    path.write_text(json.dumps(document))
    with pytest.raises(a02_dev_execution.DevelopmentRunError, match="integrity"):
        a02_dev_execution._load_authorization()


def test_legacy_approval_is_read_only_and_retains_its_original_budget_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "authorization.json"
    source = {
        "source_revision": "c" * 40,
        "profile_sha256": "a" * 64,
        "preflight_sha256": "b" * 64,
    }
    balance = {"balance": 87.49}
    confirmation = a02_dev_execution._legacy_authorization_phrase(source, balance)
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
    original = json.dumps(document)
    path.write_text(original)
    monkeypatch.setattr(a02_dev_execution, "LEGACY_AUTHORIZATION_PATH", path)
    loaded = a02_dev_execution._load_legacy_authorization()
    assert loaded["initial_compute_unit_balance"] == 87.49
    assert path.read_text() == original


def test_campaign_approval_migrates_only_remaining_scope_without_source_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile_sha256 = hashlib.sha256(a02_dev_protocol.PROFILE_PATH.read_bytes()).hexdigest()
    source = {
        "branch": "work/res-541-a02-colab-recovery",
        "source_revision": "f" * 40,
        "source_tree": "0" * 40,
        "profile_sha256": profile_sha256,
        "preflight_sha256": "1" * 64,
        "preflight_path": tmp_path / "preflight.json",
    }
    runs = tmp_path / "runs"
    runs.mkdir()
    monkeypatch.setattr(a02_dev_execution, "RUNS_DIR", runs)
    _prior_session(
        runs,
        index=1,
        source_revision="9" * 40,
        source_tree="8" * 40,
        profile_sha256=profile_sha256,
        preflight_sha256="7" * 64,
        outcome="EXTERNAL_BLOCKER",
    )
    legacy_path = tmp_path / "authorization.json"
    legacy_source = {
        "source_revision": "9" * 40,
        "profile_sha256": profile_sha256,
        "preflight_sha256": "7" * 64,
    }
    legacy_phrase = a02_dev_execution._legacy_authorization_phrase(
        legacy_source, {"balance": 87.49}
    )
    legacy: dict[str, Any] = {
        "schema": "RES541_A02_DEVELOPMENT_CAMPAIGN_AUTHORIZATION_V1",
        "status": "OWNER_AUTHORIZED",
        "branch": source["branch"],
        "source_revision": legacy_source["source_revision"],
        "source_tree": "8" * 40,
        "development_profile_sha256": profile_sha256,
        "development_preflight_sha256": legacy_source["preflight_sha256"],
        "campaign_cap_cu": 2.0,
        "max_t4_sessions": 2,
        "max_session_seconds": 900,
        "max_exec_seconds": 720,
        "no_upgrade": True,
        "no_training": True,
        "initial_compute_unit_balance": 87.49,
        "owner_confirmation": legacy_phrase,
        "owner_confirmation_sha256": hashlib.sha256(legacy_phrase.encode()).hexdigest(),
    }
    legacy["authorization_sha256"] = hashlib.sha256(
        json.dumps(legacy, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    legacy_path.write_text(json.dumps(legacy))
    auth_path = tmp_path / "campaign-authorization-v2.json"
    quota = {
        "balance": 87.32,
        "usage_rate_cu_per_hour": 0.0,
        "active_assignment_count": 0,
        "active_sessions": [],
        "provider_assignments": [],
        "snapshot_sha256": "2" * 64,
    }
    phrase = a02_dev_execution._campaign_authorization_phrase(profile_sha256, 1.83, 1)
    monkeypatch.setattr(a02_dev_execution, "AUTHORIZATION_PATH", auth_path)
    monkeypatch.setattr(a02_dev_execution, "LEGACY_AUTHORIZATION_PATH", legacy_path)
    monkeypatch.setattr(a02_dev_execution, "_source_state", lambda: source)
    monkeypatch.setattr(a02_dev_execution, "_colab_snapshot", lambda: quota)
    monkeypatch.setattr(a02_execution, "_check_e_mount", lambda: None)
    monkeypatch.setattr(builtins, "input", lambda _prompt: phrase)

    class Terminal(io.StringIO):
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(sys, "stdin", Terminal())
    monkeypatch.setattr(sys, "stdout", Terminal())
    result = a02_dev_execution.authorize_campaign()
    saved = json.loads(auth_path.read_bytes())
    assert result["gpu_allocated"] is False
    assert saved["initial_compute_unit_balance"] == 87.49
    assert saved["remaining_cu_at_authorization"] == 1.83
    assert saved["remaining_sessions_at_authorization"] == 1
    assert saved["legacy_source_authorization_sha256"] == legacy["authorization_sha256"]
    assert "source_revision" not in saved
    assert "development_preflight_sha256" not in saved


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
