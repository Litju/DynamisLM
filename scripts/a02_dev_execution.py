"""One-time-budget control plane for the RES-541 V2 development campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import select
import subprocess
import sys
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts import (
    a02_dev_protocol,
    a02_dev_remote,
    a02_dev_runtime,
    a02_dev_score,
    a02_execution,
    a02_v3_supervision,
)

ROOT = a02_execution.ROOT
E_ROOT = a02_execution.E_ROOT
CAMPAIGN_DIR = E_ROOT / "a02/development-v2"
LEGACY_AUTHORIZATION_PATH = CAMPAIGN_DIR / "authorization.json"
AUTHORIZATION_PATH = CAMPAIGN_DIR / "campaign-authorization-v2.json"
FOLLOWUP_AUTHORIZATION_PATH = CAMPAIGN_DIR / "followup-authorization-v1.json"
NEXT_AUTHORIZATION_PATH = CAMPAIGN_DIR / "session-004-authorization-v1.json"
RUNS_DIR = CAMPAIGN_DIR / "runs"
REMOTE_SOURCE = "/content/a02-source.tar"
REMOTE_BINDING = "/content/a02-binding.json"
REMOTE_PREFLIGHT = "/content/a02-development-preflight-v2.json"
REMOTE_REPORT = "/content/a02-report.json"
CAMPAIGN_CU_CAP = 2.0
CAMPAIGN_SESSION_CAP = 2
SESSION_SECONDS = 900
EXEC_SECONDS = 720
COST_BUFFER_CU = 0.05
COST_POLL_SECONDS = 10
CLEANUP_RESERVE_SECONDS = 90
REMOTE_PREPARE_MAX_SECONDS = 420
REMOTE_INFERENCE_MAX_SECONDS = 360
# Inference-stage sizing. Session 004 (run res541-a02-dev-v2-004-53820150-fd19bc72) spent
# 77.7 s before its first token (runtime checks, 33.2 s asset re-verification, 35.6 s model
# load), needed 7.3 s for the first warm-up token, and decoded at >= 23.05 tokens/s on a T4.
# Its 198 s inference stage (168 s worker) could not cover 20 bounded generations while
# prepare used 108 s of a 420 s allowance. Each bound below is more conservative than the
# observation; the worst-case token count comes from the profile, never from observed lengths.
REMOTE_WORKER_MARGIN_SECONDS = 30
INFERENCE_FIXED_OVERHEAD_SECONDS = 90
INFERENCE_WARMUP_SECONDS = 10
INFERENCE_PER_GENERATION_OVERHEAD_SECONDS = 1
INFERENCE_MIN_DECODE_TOKENS_PER_SECOND = 20
REMOTE_PREPARE_MIN_SECONDS = 180
_URL = re.compile(r"https?://[^\s<>\"']+")


class DevelopmentRunError(RuntimeError):
    pass


class InventoryMismatchError(DevelopmentRunError, a02_v3_supervision.InventoryMismatchError):
    """Independent provider inventory reads disagree; benign only across a stop transition."""


class ColabCommandError(DevelopmentRunError):
    def __init__(
        self,
        command: list[str],
        *,
        timeout: int,
        stdout: str | bytes | None,
        stderr: str | bytes | None,
        timed_out: bool = True,
    ) -> None:
        self.command_name = command[2] if len(command) > 2 else command[0]
        self.timeout_seconds = timeout
        self.stdout_tail = _safe_command_excerpt(stdout)
        self.stderr_tail = _safe_command_excerpt(stderr)
        self.timed_out = timed_out
        suffix = "timed out" if timed_out else "could not start"
        super().__init__(f"Colab command {suffix}: {self.command_name}")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(
        value, allow_nan=False, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )


def _write_exclusive(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, allow_nan=False, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _write_state(path: Path, value: dict[str, Any]) -> None:
    a02_execution._write_json(path, value)


def _safe_command_excerpt(value: str | bytes | None) -> str:
    return _URL.sub("[URL_REDACTED]", a02_dev_remote._safe_excerpt(value, 4000))


def _run_colab(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    # a02_execution._run is hash-pinned by the frozen V1 protocol and drops timeout streams.
    try:
        return subprocess.run(
            command,
            cwd=ROOT,
            env=a02_execution.clean_colab_env(),
            timeout=timeout,
            check=False,
            text=True,
            capture_output=True,
        )
    except subprocess.TimeoutExpired as exc:
        raise ColabCommandError(
            command,
            timeout=timeout,
            stdout=exc.stdout,
            stderr=exc.stderr,
        ) from exc
    except OSError as exc:
        raise ColabCommandError(
            command,
            timeout=timeout,
            stdout=None,
            stderr=str(exc),
            timed_out=False,
        ) from exc


def _record_command_failure(state: dict[str, Any], stage: str, exc: ColabCommandError) -> None:
    state["command_failure"] = {
        "stage": stage,
        "command": exc.command_name,
        "timed_out": exc.timed_out,
        "timeout_seconds": exc.timeout_seconds,
        "stdout_tail": exc.stdout_tail,
        "stderr_tail": exc.stderr_tail,
    }


def _stop_exact_session(run_id: str) -> subprocess.CompletedProcess[str]:
    return _run_colab(
        ["colab", "--auth=oauth2", "stop", "--session", run_id],
        timeout=a02_execution.STOP_TIMEOUT_SECONDS,
    )


def _remote_report_matches(report: object, run_id: str, source: dict[str, Any]) -> bool:
    if not isinstance(report, dict):
        return False
    bound = report.get("source")
    return (
        isinstance(bound, dict)
        and bound.get("run_id") == run_id
        and bound.get("revision") == source["source_revision"]
        and bound.get("tree") == source["source_tree"]
        and bound.get("development_profile_sha256") == source["profile_sha256"]
        and bound.get("development_preflight_sha256") == source["preflight_sha256"]
        and (
            "runtime_policy_sha256" not in source
            or (
                bound.get("runtime_policy_id") == source["runtime_policy_id"]
                and bound.get("runtime_policy_sha256") == source["runtime_policy_sha256"]
            )
        )
    )


def _remote_report_is_complete(report: object, run_id: str, source: dict[str, Any]) -> bool:
    return bool(
        isinstance(report, dict)
        and _remote_report_matches(report, run_id, source)
        and report.get("status") == "COMPLETE"
    )


def _download_stage_report(
    *,
    run_id: str,
    stage: str,
    local_path: Path,
    source: dict[str, Any],
    control_path: Path,
    state: dict[str, Any],
) -> dict[str, Any] | None:
    entry = state.setdefault("remote_stages", {}).setdefault(stage, {})
    try:
        downloaded = _run_colab(
            [
                "colab",
                "--auth=oauth2",
                "download",
                "--session",
                run_id,
                REMOTE_REPORT,
                str(local_path),
            ],
            timeout=a02_execution.DOWNLOAD_TIMEOUT_SECONDS,
        )
    except ColabCommandError as exc:
        _record_command_failure(state, f"{stage}_REPORT_RECOVERY", exc)
        entry["report_download_error"] = str(exc)
        _write_state(control_path, state)
        return None
    entry["report_download_returncode"] = downloaded.returncode
    entry["report_download_stdout_tail"] = _safe_command_excerpt(downloaded.stdout)
    if downloaded.returncode != 0:
        entry["report_download_stderr_tail"] = _safe_command_excerpt(downloaded.stderr)
    if not local_path.is_file():
        entry["report_recovered"] = False
        _write_state(control_path, state)
        return None
    try:
        report = json.loads(local_path.read_bytes())
    except (OSError, json.JSONDecodeError):
        entry["report_recovered"] = False
        entry["report_parse_error"] = True
        _write_state(control_path, state)
        return None
    entry["report_recovered"] = True
    entry["report_sha256"] = _sha(local_path.read_bytes())
    if not isinstance(report, dict) or not _remote_report_matches(report, run_id, source):
        entry["report_binding_valid"] = False
        _write_state(control_path, state)
        return None
    entry["report_binding_valid"] = True
    entry["report_status"] = report.get("status")
    _write_state(control_path, state)
    return report


def _run_remote_stage(
    *,
    run_id: str,
    stage: str,
    timeout: int,
    report_path: Path,
    source: dict[str, Any],
    control_path: Path,
    state: dict[str, Any],
) -> bool:
    entry = state.setdefault("remote_stages", {}).setdefault(stage, {})
    entry["status"] = "REQUESTED"
    entry["timeout_seconds"] = timeout
    state["active_remote_stage"] = stage
    _write_state(control_path, state)
    command = [
        "colab",
        "--auth=oauth2",
        "exec",
        "--session",
        run_id,
        "--env",
        f"A02_DEV_REMOTE_STAGE={stage}",
        "--env",
        f"A02_DEV_REMOTE_STAGE_TIMEOUT={timeout}",
        "--file",
        str(ROOT / "scripts/a02_dev_remote.py"),
        "--timeout",
        str(timeout),
    ]
    try:
        execution = _run_colab(command, timeout=timeout + 30)
    except ColabCommandError as exc:
        entry["status"] = "TIMEOUT" if exc.timed_out else "COMMAND_ERROR"
        _record_command_failure(state, stage, exc)
        _write_state(control_path, state)
        _download_stage_report(
            run_id=run_id,
            stage=stage,
            local_path=report_path,
            source=source,
            control_path=control_path,
            state=state,
        )
        raise
    entry.update(
        status="EXEC_RETURNED",
        exec_returncode=execution.returncode,
        stdout_tail=_safe_command_excerpt(execution.stdout),
        stderr_tail=_safe_command_excerpt(execution.stderr),
    )
    _write_state(control_path, state)
    report = _download_stage_report(
        run_id=run_id,
        stage=stage,
        local_path=report_path,
        source=source,
        control_path=control_path,
        state=state,
    )
    expected = "READY_FOR_INFERENCE" if stage == "prepare" else "COMPLETE"
    return bool(
        execution.returncode == 0
        and report is not None
        and report.get("status") == expected
        and entry.get("report_download_returncode") == 0
    )


def _source_state() -> dict[str, Any]:
    a02_execution._check_e_mount()
    a02_execution._check_tracked_model_weights()
    branch = subprocess.check_output(
        ["git", "branch", "--show-current"], cwd=ROOT, text=True
    ).strip()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain=v1"], cwd=ROOT, text=True
    ).strip()
    base = subprocess.check_output(
        ["git", "merge-base", "HEAD", "b8510aef00d1e3208562ceefea083c0fa57901fa"],
        cwd=ROOT,
        text=True,
    ).strip()
    if (
        branch != "work/res-541-a02-colab-recovery"
        or base != "b8510aef00d1e3208562ceefea083c0fa57901fa"
    ):
        raise DevelopmentRunError("V2 campaign must use the existing RES-541 branch and base")
    if dirty:
        raise DevelopmentRunError("V2 campaign requires the exact clean committed source")
    preflight_path = E_ROOT / "a02" / f"development-preflight-v2-{head}.json"
    try:
        preflight_bytes = preflight_path.read_bytes()
        preflight = json.loads(preflight_bytes)
    except (OSError, json.JSONDecodeError) as exc:
        raise DevelopmentRunError("current-head V2 CPU preflight is unavailable") from exc
    if (
        preflight.get("schema") != "RES541_A02_DEVELOPMENT_PREFLIGHT_V2"
        or preflight.get("working_tree_clean") is not True
        or preflight.get("source_revision") != head
        or preflight.get("source_tree") != tree
        or preflight.get("development_profile_sha256")
        != _sha(a02_dev_protocol.PROFILE_PATH.read_bytes())
        or preflight.get("model_weights_loaded") is not False
        or preflight.get("gpu_allocated") is not False
    ):
        raise DevelopmentRunError("V2 CPU preflight does not bind the clean current source")
    return {
        "branch": branch,
        "source_revision": head,
        "source_tree": tree,
        "preflight_path": preflight_path,
        "preflight": preflight,
        "preflight_sha256": _sha(preflight_bytes),
        "profile_sha256": _sha(a02_dev_protocol.PROFILE_PATH.read_bytes()),
        **a02_dev_runtime.policy_binding(),
    }


def _colab_snapshot() -> dict[str, Any]:
    version = _run_colab(["colab", "version"], timeout=15)
    identity = _run_colab(["colab", "--auth=oauth2", "whoami"], timeout=15)
    usage = _run_colab(["colab", "--auth=oauth2", "usage"], timeout=30)
    sessions = _run_colab(["colab", "--auth=oauth2", "sessions"], timeout=30)
    if (
        version.returncode != 0
        or "0.7.5" not in version.stdout
        or identity.returncode != 0
        or usage.returncode != 0
        or sessions.returncode != 0
    ):
        raise DevelopmentRunError("Colab OAuth, CLI, or quota preflight failed")
    balance, rate, usage_assignments = a02_execution._parse_current_usage(usage.stdout)
    session_rows = a02_execution._session_rows(sessions.stdout)
    assignments = a02_execution._provider_assignments()
    if {row[1] for row in session_rows} != {row["endpoint"] for row in assignments}:
        raise InventoryMismatchError("Colab CLI and provider assignment inventories differ")
    if usage_assignments != len(assignments):
        raise InventoryMismatchError("Colab usage and provider assignment counts differ")
    return {
        "balance": balance,
        "usage_rate_cu_per_hour": rate,
        "active_assignment_count": len(assignments),
        "active_sessions": [
            {"name": name, "endpoint": endpoint, "hardware": hardware}
            for name, endpoint, hardware in session_rows
        ],
        "provider_assignments": assignments,
        "usage_output": usage.stdout.strip(),
        "session_list": sessions.stdout.strip(),
        "snapshot_sha256": _sha(
            _canonical(
                {
                    "usage_output": usage.stdout.strip(),
                    "session_list": sessions.stdout.strip(),
                    "provider_assignments": assignments,
                }
            ).encode()
        ),
    }


def _legacy_authorization_phrase(source: dict[str, Any], quota: dict[str, Any]) -> str:
    return (
        "AUTHORIZE RES-541 V2 DEVELOPMENT CAMPAIGN"
        f" | source={source['source_revision']}"
        f" | profile={source['profile_sha256']}"
        f" | preflight={source['preflight_sha256']}"
        f" | cap={CAMPAIGN_CU_CAP:.2f} CU"
        f" | sessions={CAMPAIGN_SESSION_CAP} T4"
        f" | session-limit={SESSION_SECONDS}s"
        f" | current-balance={quota['balance']:.2f} CU"
        " | no-upgrade"
        " | no-training"
    )


def _campaign_authorization_phrase(
    profile_sha256: str, remaining_cu: float, remaining_sessions: int
) -> str:
    return (
        "AUTHORIZE RES-541 V2 DEVELOPMENT CAMPAIGN"
        f" | profile={profile_sha256}"
        f" | total-cap={CAMPAIGN_CU_CAP:.2f} CU"
        f" | remaining={remaining_cu:.2f} CU"
        f" | sessions={remaining_sessions} T4"
        f" | session-limit={SESSION_SECONDS}s"
        " | no-upgrade"
        " | no-training"
    )


def authorize_campaign() -> dict[str, Any]:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise DevelopmentRunError("one-time campaign approval requires an interactive WSL terminal")
    a02_execution._check_e_mount()
    if AUTHORIZATION_PATH.exists():
        raise DevelopmentRunError("campaign-level V2 authorization is immutable")
    source = _source_state()
    profile = a02_dev_protocol.load_profile()
    cap = profile["campaign_cap"]
    if (
        cap.get("compute_units") != CAMPAIGN_CU_CAP
        or cap.get("max_t4_sessions") != CAMPAIGN_SESSION_CAP
        or cap.get("max_session_seconds") != SESSION_SECONDS
        or cap.get("no_upgrade") is not True
        or cap.get("no_training") is not True
    ):
        raise DevelopmentRunError("V2 campaign profile exceeds the fixed proposed budget")
    quota = _colab_snapshot()
    if quota["balance"] <= 0:
        raise DevelopmentRunError("Colab reports no existing compute-unit balance")
    legacy = _load_legacy_authorization() if LEGACY_AUTHORIZATION_PATH.is_file() else None
    if legacy and (
        legacy.get("branch") != source["branch"]
        or legacy.get("development_profile_sha256") != source["profile_sha256"]
    ):
        raise DevelopmentRunError("legacy approval belongs to a different campaign profile")
    markers = _used_session_markers()
    if markers and legacy is None:
        raise DevelopmentRunError("prior sessions require the original campaign budget baseline")
    initial_balance = float(legacy["initial_compute_unit_balance"]) if legacy else quota["balance"]
    if quota["balance"] > initial_balance:
        raise DevelopmentRunError("Colab balance increased; cumulative campaign spend is ambiguous")
    prior_spend = max(0.0, initial_balance - quota["balance"])
    remaining_cu = round(CAMPAIGN_CU_CAP - prior_spend, 2)
    _next_session_index(markers, source)
    remaining_sessions = CAMPAIGN_SESSION_CAP - len(markers)
    if remaining_cu <= COST_BUFFER_CU or remaining_sessions <= 0:
        raise DevelopmentRunError("the previously approved campaign scope is exhausted")
    phrase = _campaign_authorization_phrase(
        source["profile_sha256"], remaining_cu, remaining_sessions
    )
    print(
        "This records one campaign-level approval for the remaining V2 scope. It allocates no GPU."
    )
    print(f"Type exactly: {phrase}")
    if input("> ") != phrase:
        raise DevelopmentRunError(
            "campaign authorization text did not match; no marker was written"
        )
    fresh_source = _source_state()
    fresh_quota = _colab_snapshot()
    if any(fresh_source[key] != source[key] for key in ("branch", "profile_sha256")) or any(
        fresh_quota[key] != quota[key]
        for key in (
            "balance",
            "usage_rate_cu_per_hour",
            "active_assignment_count",
            "active_sessions",
            "provider_assignments",
        )
    ):
        raise DevelopmentRunError("source or quota changed during one-time campaign approval")
    authorization: dict[str, Any] = {
        "schema": "RES541_A02_DEVELOPMENT_CAMPAIGN_AUTHORIZATION_V2",
        "status": "OWNER_AUTHORIZED",
        "branch": source["branch"],
        "development_profile_sha256": source["profile_sha256"],
        "campaign_cap_cu": CAMPAIGN_CU_CAP,
        "max_t4_sessions": CAMPAIGN_SESSION_CAP,
        "max_session_seconds": SESSION_SECONDS,
        "max_exec_seconds": EXEC_SECONDS,
        "no_upgrade": True,
        "no_training": True,
        "approval_scope": "CAMPAIGN_PROFILE_WITH_PER_SESSION_SOURCE_BINDING",
        "initial_compute_unit_balance": initial_balance,
        "account_balance_at_authorization": quota["balance"],
        "account_spend_before_authorization_cu": prior_spend,
        "remaining_cu_at_authorization": remaining_cu,
        "remaining_sessions_at_authorization": remaining_sessions,
        "legacy_source_authorization_sha256": (legacy["authorization_sha256"] if legacy else None),
        "quota_snapshot_sha256": quota["snapshot_sha256"],
        "active_sessions_at_authorization": quota["active_sessions"],
        "provider_assignments_at_authorization": quota["provider_assignments"],
        "owner_confirmation": phrase,
        "owner_confirmation_sha256": _sha(phrase.encode()),
        "authorized_at_utc": datetime.now(UTC).isoformat(),
    }
    authorization["authorization_sha256"] = _sha(_canonical(authorization).encode())
    _write_exclusive(AUTHORIZATION_PATH, authorization)
    return {
        "path": str(AUTHORIZATION_PATH),
        "authorization_sha256": authorization["authorization_sha256"],
        "campaign_cap_cu": CAMPAIGN_CU_CAP,
        "max_t4_sessions": CAMPAIGN_SESSION_CAP,
        "gpu_allocated": False,
    }


def _load_legacy_authorization() -> dict[str, Any]:
    value = json.loads(LEGACY_AUTHORIZATION_PATH.read_bytes())
    if not isinstance(value, dict):
        raise DevelopmentRunError("legacy source-bound authorization record is invalid")
    digest = value.pop("authorization_sha256", None)
    source = {
        "source_revision": value.get("source_revision"),
        "profile_sha256": value.get("development_profile_sha256"),
        "preflight_sha256": value.get("development_preflight_sha256"),
    }
    quota = {"balance": value.get("initial_compute_unit_balance")}
    confirmation = value.get("owner_confirmation")
    if (
        value.get("schema") != "RES541_A02_DEVELOPMENT_CAMPAIGN_AUTHORIZATION_V1"
        or value.get("status") != "OWNER_AUTHORIZED"
        or digest != _sha(_canonical(value).encode())
        or value.get("campaign_cap_cu") != CAMPAIGN_CU_CAP
        or value.get("max_t4_sessions") != CAMPAIGN_SESSION_CAP
        or value.get("max_session_seconds") != SESSION_SECONDS
        or value.get("max_exec_seconds") != EXEC_SECONDS
        or value.get("no_upgrade") is not True
        or value.get("no_training") is not True
        or isinstance(quota["balance"], bool)
        or not isinstance(quota["balance"], int | float)
        or not math.isfinite(quota["balance"])
        or quota["balance"] <= 0
        or not isinstance(confirmation, str)
        or confirmation != _legacy_authorization_phrase(source, quota)
        or value.get("owner_confirmation_sha256") != _sha(confirmation.encode())
    ):
        raise DevelopmentRunError("legacy source-bound authorization failed integrity checks")
    value["authorization_sha256"] = digest
    return value


def _load_authorization() -> dict[str, Any]:
    if not AUTHORIZATION_PATH.is_file():
        if LEGACY_AUTHORIZATION_PATH.is_file():
            raise DevelopmentRunError(
                "legacy source-bound approval cannot authorize modified code; "
                "a fresh campaign-level authorization is required"
            )
        raise DevelopmentRunError("one-time campaign-level V2 budget authorization is required")
    value = json.loads(AUTHORIZATION_PATH.read_bytes())
    if not isinstance(value, dict):
        raise DevelopmentRunError("campaign-level V2 authorization record is invalid")
    digest = value.pop("authorization_sha256", None)
    profile_sha256 = value.get("development_profile_sha256")
    balance = value.get("initial_compute_unit_balance")
    account_balance = value.get("account_balance_at_authorization")
    spend_before = value.get("account_spend_before_authorization_cu")
    remaining_cu = value.get("remaining_cu_at_authorization")
    remaining_sessions = value.get("remaining_sessions_at_authorization")
    confirmation = value.get("owner_confirmation")
    legacy_sha256 = value.get("legacy_source_authorization_sha256")
    quota_sha256 = value.get("quota_snapshot_sha256")
    if not isinstance(profile_sha256, str):
        raise DevelopmentRunError("campaign-level V2 authorization profile is invalid")
    profile_matches = profile_sha256 == _sha(a02_dev_protocol.PROFILE_PATH.read_bytes())
    legacy_matches = (
        not LEGACY_AUTHORIZATION_PATH.exists()
        if legacy_sha256 is None
        else (
            LEGACY_AUTHORIZATION_PATH.is_file()
            and _load_legacy_authorization()["authorization_sha256"] == legacy_sha256
        )
    )
    if (
        value.get("schema") != "RES541_A02_DEVELOPMENT_CAMPAIGN_AUTHORIZATION_V2"
        or value.get("status") != "OWNER_AUTHORIZED"
        or digest != _sha(_canonical(value).encode())
        or value.get("branch") != "work/res-541-a02-colab-recovery"
        or value.get("approval_scope") != "CAMPAIGN_PROFILE_WITH_PER_SESSION_SOURCE_BINDING"
        or not profile_matches
        or not legacy_matches
        or value.get("campaign_cap_cu") != CAMPAIGN_CU_CAP
        or value.get("max_t4_sessions") != CAMPAIGN_SESSION_CAP
        or value.get("max_session_seconds") != SESSION_SECONDS
        or value.get("max_exec_seconds") != EXEC_SECONDS
        or value.get("no_upgrade") is not True
        or value.get("no_training") is not True
        or isinstance(balance, bool)
        or not isinstance(balance, int | float)
        or not math.isfinite(balance)
        or balance <= 0
        or isinstance(account_balance, bool)
        or not isinstance(account_balance, int | float)
        or not math.isfinite(account_balance)
        or account_balance <= 0
        or account_balance > balance
        or isinstance(spend_before, bool)
        or not isinstance(spend_before, int | float)
        or not math.isfinite(spend_before)
        or spend_before < 0
        or abs(account_balance - (balance - spend_before)) > 0.005000001
        or not isinstance(quota_sha256, str)
        or len(quota_sha256) != 64
        or any(char not in "0123456789abcdef" for char in quota_sha256)
        or (legacy_sha256 is not None and not isinstance(legacy_sha256, str))
        or isinstance(remaining_cu, bool)
        or not isinstance(remaining_cu, int | float)
        or not math.isfinite(remaining_cu)
        or not 0 <= remaining_cu <= CAMPAIGN_CU_CAP
        or remaining_cu != round(CAMPAIGN_CU_CAP - spend_before, 2)
        or isinstance(remaining_sessions, bool)
        or not isinstance(remaining_sessions, int)
        or not 0 <= remaining_sessions <= CAMPAIGN_SESSION_CAP
        or not isinstance(confirmation, str)
        or confirmation
        != _campaign_authorization_phrase(profile_sha256, remaining_cu, remaining_sessions)
        or value.get("owner_confirmation_sha256") != _sha(confirmation.encode())
    ):
        raise DevelopmentRunError("campaign-level V2 authorization failed integrity checks")
    value["authorization_sha256"] = digest
    return value


def _followup_authorization_path(session_index: int) -> Path:
    if type(session_index) is int and session_index == CAMPAIGN_SESSION_CAP + 1:
        return FOLLOWUP_AUTHORIZATION_PATH
    if type(session_index) is int and session_index == CAMPAIGN_SESSION_CAP + 2:
        return NEXT_AUTHORIZATION_PATH
    raise DevelopmentRunError("no further T4 session authorization scope is implemented")


def authorize_followup_session(
    approval_text: str, *, session_index: int = CAMPAIGN_SESSION_CAP + 1
) -> dict[str, Any]:
    authorization_path = _followup_authorization_path(session_index)
    if authorization_path.exists():
        raise DevelopmentRunError("the one-session follow-up authorization is immutable")
    if not isinstance(approval_text, str) or not approval_text.strip() or len(approval_text) > 500:
        raise DevelopmentRunError("the follow-up owner approval reference is invalid")
    authorization = _load_authorization()
    source = _source_state()
    quota = _colab_snapshot()
    markers = _used_session_markers()
    if len(markers) != session_index - 1:
        raise DevelopmentRunError("follow-up authorization requires all preceding sessions")
    if (
        quota["active_assignment_count"] != 0
        or quota["active_sessions"]
        or quota["provider_assignments"]
    ):
        raise DevelopmentRunError("active Colab assignments prevent a follow-up authorization")
    next_index = _next_session_index(markers, source, max_sessions=session_index)
    if next_index != session_index:
        raise DevelopmentRunError("follow-up session index is invalid")
    prior_spend, remaining_cu = _campaign_budget(authorization, quota["balance"])
    if remaining_cu > authorization["remaining_cu_at_authorization"] + 0.005000001:
        raise DevelopmentRunError("follow-up budget exceeds the original authorized remainder")
    prior_spend = round(prior_spend, 2)
    remaining_cu = round(remaining_cu, 2)
    marker_hashes = [
        _sha((RUNS_DIR / marker["run_id"] / "session-used.json").read_bytes()) for marker in markers
    ]
    fresh_source = _source_state()
    fresh_quota = _colab_snapshot()
    if any(
        fresh_source[key] != source[key]
        for key in (
            "branch",
            "source_revision",
            "source_tree",
            "profile_sha256",
            "preflight_sha256",
        )
    ) or any(
        fresh_quota[key] != quota[key]
        for key in (
            "balance",
            "usage_rate_cu_per_hour",
            "active_assignment_count",
            "active_sessions",
            "provider_assignments",
        )
    ):
        raise DevelopmentRunError("source or quota changed during follow-up authorization")
    followup: dict[str, Any] = {
        "schema": "RES541_A02_DEVELOPMENT_FOLLOWUP_AUTHORIZATION_V1",
        "status": "OWNER_AUTHORIZED",
        "approval_scope": "ONE_ADDITIONAL_SESSION_WITHIN_ORIGINAL_CAMPAIGN_CAP",
        "owner_approval_text": approval_text,
        "owner_approval_sha256": _sha(approval_text.encode()),
        "base_campaign_authorization_sha256": authorization["authorization_sha256"],
        "branch": source["branch"],
        "source_revision": source["source_revision"],
        "source_tree": source["source_tree"],
        "development_profile_sha256": source["profile_sha256"],
        "development_preflight_sha256": source["preflight_sha256"],
        "campaign_cap_cu": CAMPAIGN_CU_CAP,
        "initial_compute_unit_balance": authorization["initial_compute_unit_balance"],
        "account_balance_at_authorization": quota["balance"],
        "account_spend_before_authorization_cu": prior_spend,
        "remaining_cu_at_authorization": remaining_cu,
        "additional_t4_sessions": 1,
        "authorized_session_index": session_index,
        "max_session_seconds": SESSION_SECONDS,
        "max_exec_seconds": EXEC_SECONDS,
        "no_upgrade": True,
        "no_training": True,
        "previous_session_marker_sha256s": marker_hashes,
        "quota_snapshot_sha256": quota["snapshot_sha256"],
        "active_sessions_at_authorization": quota["active_sessions"],
        "provider_assignments_at_authorization": quota["provider_assignments"],
        "authorized_at_utc": datetime.now(UTC).isoformat(),
    }
    followup["authorization_sha256"] = _sha(_canonical(followup).encode())
    _write_exclusive(authorization_path, followup)
    return {
        "path": str(authorization_path),
        "authorization_sha256": followup["authorization_sha256"],
        "remaining_cu": remaining_cu,
        "additional_t4_sessions": 1,
        "gpu_allocated": False,
    }


def _load_followup_authorization(
    authorization: dict[str, Any],
    source: dict[str, Any],
    quota: dict[str, Any],
    markers: list[dict[str, Any]],
) -> dict[str, Any]:
    session_index = len(markers) + 1
    authorization_path = _followup_authorization_path(session_index)
    if not authorization_path.is_file():
        raise DevelopmentRunError("one additional source-bound T4 authorization is required")
    value = json.loads(authorization_path.read_bytes())
    if not isinstance(value, dict):
        raise DevelopmentRunError("follow-up authorization record is invalid")
    digest = value.pop("authorization_sha256", None)
    approval_text = value.get("owner_approval_text")
    balance_at_authorization = value.get("account_balance_at_authorization")
    spend_before = value.get("account_spend_before_authorization_cu")
    remaining_cu = value.get("remaining_cu_at_authorization")
    quota_sha256 = value.get("quota_snapshot_sha256")
    marker_hashes = [
        _sha((RUNS_DIR / marker["run_id"] / "session-used.json").read_bytes()) for marker in markers
    ]
    _, remaining_now = _campaign_budget(authorization, quota["balance"])
    if (
        value.get("schema") != "RES541_A02_DEVELOPMENT_FOLLOWUP_AUTHORIZATION_V1"
        or value.get("status") != "OWNER_AUTHORIZED"
        or digest != _sha(_canonical(value).encode())
        or value.get("approval_scope") != "ONE_ADDITIONAL_SESSION_WITHIN_ORIGINAL_CAMPAIGN_CAP"
        or not isinstance(approval_text, str)
        or not approval_text.strip()
        or value.get("owner_approval_sha256") != _sha(approval_text.encode())
        or value.get("base_campaign_authorization_sha256") != authorization["authorization_sha256"]
        or value.get("branch") != source["branch"]
        or value.get("source_revision") != source["source_revision"]
        or value.get("source_tree") != source["source_tree"]
        or value.get("development_profile_sha256") != source["profile_sha256"]
        or value.get("development_preflight_sha256") != source["preflight_sha256"]
        or value.get("campaign_cap_cu") != CAMPAIGN_CU_CAP
        or value.get("initial_compute_unit_balance")
        != authorization["initial_compute_unit_balance"]
        or isinstance(balance_at_authorization, bool)
        or not isinstance(balance_at_authorization, int | float)
        or not math.isfinite(balance_at_authorization)
        or balance_at_authorization > authorization["account_balance_at_authorization"]
        or isinstance(spend_before, bool)
        or not isinstance(spend_before, int | float)
        or spend_before
        != round(authorization["initial_compute_unit_balance"] - balance_at_authorization, 2)
        or isinstance(remaining_cu, bool)
        or not isinstance(remaining_cu, int | float)
        or remaining_cu != round(CAMPAIGN_CU_CAP - spend_before, 2)
        or not 0 < remaining_cu <= authorization["remaining_cu_at_authorization"]
        or remaining_now > remaining_cu + 0.005000001
        or type(value.get("additional_t4_sessions")) is not int
        or value.get("additional_t4_sessions") != 1
        or value.get("authorized_session_index") != session_index
        or value.get("max_session_seconds") != SESSION_SECONDS
        or value.get("max_exec_seconds") != EXEC_SECONDS
        or value.get("no_upgrade") is not True
        or value.get("no_training") is not True
        or value.get("previous_session_marker_sha256s") != marker_hashes
        or quota["active_assignment_count"] != 0
        or quota["active_sessions"]
        or quota["provider_assignments"]
        or quota["balance"] > balance_at_authorization
        or not isinstance(quota_sha256, str)
        or len(quota_sha256) != 64
        or any(char not in "0123456789abcdef" for char in quota_sha256)
    ):
        raise DevelopmentRunError("follow-up authorization failed scope or integrity checks")
    value["authorization_sha256"] = digest
    return value


def _used_session_markers() -> list[dict[str, Any]]:
    if not RUNS_DIR.exists():
        return []
    markers = []
    for directory in sorted(RUNS_DIR.iterdir()):
        marker_path = directory / "session-used.json"
        if not marker_path.exists():
            continue
        marker = json.loads(marker_path.read_bytes())
        if not isinstance(marker, dict) or marker.get("run_id") != directory.name:
            raise DevelopmentRunError("V2 campaign session marker is invalid")
        markers.append(marker)
    return markers


def _prior_session_config(marker: dict[str, Any]) -> tuple[tuple[str, str, str, str], str]:
    run_id = marker["run_id"]
    directory = RUNS_DIR / run_id
    binding_path = directory / "binding.json"
    control_path = directory / "control.json"
    try:
        binding_bytes = binding_path.read_bytes()
        binding = json.loads(binding_bytes)
        control = json.loads(control_path.read_bytes())
        manifest = json.loads((directory / "artifact-hashes.json").read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise DevelopmentRunError("prior V2 session evidence is incomplete") from exc
    if (
        not isinstance(binding, dict)
        or not isinstance(control, dict)
        or not isinstance(manifest, dict)
    ):
        raise DevelopmentRunError("prior V2 session receipts are invalid")
    rows = manifest.get("files")
    if not isinstance(rows, list):
        raise DevelopmentRunError("prior V2 artifact manifest is invalid")
    manifest_files = {
        row.get("name"): row
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("name"), str)
    }
    control_bytes = control_path.read_bytes()
    binding_manifest = manifest_files.get("binding.json", {})
    control_manifest = manifest_files.get("control.json", {})
    marker_path = directory / "session-used.json"
    try:
        marker_bytes = marker_path.read_bytes()
    except OSError as exc:
        raise DevelopmentRunError("prior V2 session marker is missing") from exc
    marker_manifest = manifest_files.get("session-used.json", {})
    followup_sha256 = marker.get("followup_authorization_sha256")
    if followup_sha256 is not None:
        followup_path = directory / "followup-authorization.json"
        try:
            followup_bytes = followup_path.read_bytes()
            followup = json.loads(followup_bytes)
        except (OSError, json.JSONDecodeError) as exc:
            raise DevelopmentRunError("prior V2 follow-up authorization is incomplete") from exc
        if not isinstance(followup, dict):
            raise DevelopmentRunError("prior V2 follow-up authorization is invalid")
        followup_manifest = manifest_files.get("followup-authorization.json", {})
        followup_digest = followup.pop("authorization_sha256", None)
        if (
            followup_digest != followup_sha256
            or followup_manifest.get("sha256") != _sha(followup_bytes)
            or followup_manifest.get("bytes") != len(followup_bytes)
            or followup_digest != _sha(_canonical(followup).encode())
        ):
            raise DevelopmentRunError("prior V2 follow-up authorization failed integrity checks")
    if (
        manifest.get("run_id") != run_id
        or manifest.get("terminal_outcome") != control.get("terminal_outcome")
        or binding_manifest.get("sha256") != _sha(binding_bytes)
        or binding_manifest.get("bytes") != len(binding_bytes)
        or control_manifest.get("sha256") != _sha(control_bytes)
        or control_manifest.get("bytes") != len(control_bytes)
        or marker_manifest.get("sha256") != _sha(marker_bytes)
        or marker_manifest.get("bytes") != len(marker_bytes)
        or _sha(binding_bytes) != marker.get("binding_sha256")
        or binding.get("run_id") != run_id
        or binding.get("source_revision") != marker.get("source_revision")
        or (
            marker.get("source_tree") is not None
            and binding.get("source_tree") != marker.get("source_tree")
        )
        or binding.get("development_profile_sha256") != marker.get("development_profile_sha256")
        or (
            marker.get("development_preflight_sha256") is not None
            and binding.get("development_preflight_sha256")
            != marker.get("development_preflight_sha256")
        )
        or binding.get("campaign_followup_authorization_sha256") != followup_sha256
        or control.get("run_id") != run_id
        or control.get("status") != "CONTROL_FINISHED"
        or control.get("session_index") != marker.get("session_index")
        or not isinstance(control.get("terminal_outcome"), str)
    ):
        raise DevelopmentRunError("prior V2 session binding or disposition is invalid")
    config = (
        binding["source_revision"],
        binding["source_tree"],
        binding["development_profile_sha256"],
        binding["development_preflight_sha256"],
    )
    return config, control["terminal_outcome"]


def _next_session_index(
    markers: list[dict[str, Any]],
    source: dict[str, Any],
    *,
    max_sessions: int = CAMPAIGN_SESSION_CAP,
) -> int:
    if len(markers) >= max_sessions:
        raise DevelopmentRunError("V2 campaign has exhausted its T4 session cap")
    indices = [marker.get("session_index") for marker in markers]
    if any(isinstance(index, bool) or not isinstance(index, int) for index in indices):
        raise DevelopmentRunError("V2 campaign session index is invalid")
    valid_indices = [
        index for index in indices if isinstance(index, int) and not isinstance(index, bool)
    ]
    if sorted(valid_indices) != list(range(1, len(markers) + 1)):
        raise DevelopmentRunError("V2 campaign session markers are not contiguous")
    current = (
        source["source_revision"],
        source["source_tree"],
        source["profile_sha256"],
        source["preflight_sha256"],
    )
    for marker in markers:
        previous, outcome = _prior_session_config(marker)
        if outcome != "EXTERNAL_BLOCKER":
            raise DevelopmentRunError("a completed V2 experiment cannot be repeated")
        if previous == current:
            raise DevelopmentRunError("the failed V2 configuration cannot be replayed")
    return len(markers) + 1


def _campaign_budget(authorization: dict[str, Any], current_balance: float) -> tuple[float, float]:
    initial = float(authorization["initial_compute_unit_balance"])
    if current_balance <= 0 or current_balance > authorization["account_balance_at_authorization"]:
        raise DevelopmentRunError("Colab balance is ambiguous against campaign authorization")
    prior_spend = max(0.0, initial - current_balance)
    remaining = CAMPAIGN_CU_CAP - prior_spend
    if (
        remaining <= COST_BUFFER_CU
        or remaining > authorization["remaining_cu_at_authorization"] + 0.005000001
    ):
        raise DevelopmentRunError("authorized V2 campaign budget is exhausted or ambiguous")
    return prior_spend, remaining


def _resolve_session_scope(
    authorization: dict[str, Any],
    source: dict[str, Any],
    quota: dict[str, Any],
    markers: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, int, float, float]:
    prior_spend, remaining_cu = _campaign_budget(authorization, quota["balance"])
    if len(markers) < CAMPAIGN_SESSION_CAP:
        if FOLLOWUP_AUTHORIZATION_PATH.exists():
            raise DevelopmentRunError(
                "follow-up authorization cannot precede the original sessions"
            )
        session_index = _next_session_index(markers, source)
        if (
            CAMPAIGN_SESSION_CAP - len(markers)
            > authorization["remaining_sessions_at_authorization"]
        ):
            raise DevelopmentRunError(
                "session count exceeds the approved campaign continuation scope"
            )
        return None, session_index, prior_spend, remaining_cu
    if len(markers) not in (CAMPAIGN_SESSION_CAP, CAMPAIGN_SESSION_CAP + 1) or (
        len(markers) == CAMPAIGN_SESSION_CAP + 1 and not NEXT_AUTHORIZATION_PATH.is_file()
    ):
        raise DevelopmentRunError("V2 campaign has exhausted its T4 session cap")
    followup = _load_followup_authorization(authorization, source, quota, markers)
    session_index = _next_session_index(
        markers, source, max_sessions=len(markers) + followup["additional_t4_sessions"]
    )
    if session_index != followup["authorized_session_index"]:
        raise DevelopmentRunError("follow-up authorization does not bind the next session")
    return (
        followup,
        session_index,
        prior_spend,
        min(remaining_cu, followup["remaining_cu_at_authorization"]),
    )


def _safe_exec_seconds(remaining_cu: float, usage_rate_cu_per_hour: float) -> int:
    if (
        not math.isfinite(remaining_cu)
        or not math.isfinite(usage_rate_cu_per_hour)
        or remaining_cu <= COST_BUFFER_CU
        or usage_rate_cu_per_hour <= 0
    ):
        raise DevelopmentRunError("campaign remaining budget or usage rate is ambiguous")
    return max(
        0,
        min(
            EXEC_SECONDS,
            math.floor((remaining_cu - COST_BUFFER_CU) * 3600 / usage_rate_cu_per_hour)
            - CLEANUP_RESERVE_SECONDS,
        ),
    )


def required_inference_stage_seconds(profile: dict[str, Any] | None = None) -> int:
    """Worst-case inference-stage seconds for every planned generation at its token cap."""
    profile = a02_dev_protocol.load_profile() if profile is None else profile
    decoding = profile["decoding"]
    cases = len(profile["case_ids"])
    generations = 2 * cases
    tokens = cases * (
        int(decoding["action_max_new_tokens"]) + int(decoding["final_max_new_tokens"])
    )
    return (
        INFERENCE_FIXED_OVERHEAD_SECONDS
        + INFERENCE_WARMUP_SECONDS
        + generations * INFERENCE_PER_GENERATION_OVERHEAD_SECONDS
        + math.ceil(tokens / INFERENCE_MIN_DECODE_TOKENS_PER_SECOND)
        + REMOTE_WORKER_MARGIN_SECONDS
    )


def _split_stage_timeouts(
    exec_seconds: int, profile: dict[str, Any] | None = None
) -> dict[str, int]:
    """Reserve worst-case inference first; slack goes to inference, then to prepare."""
    required = required_inference_stage_seconds(profile)
    if required > REMOTE_INFERENCE_MAX_SECONDS:
        raise DevelopmentRunError("V2 profile cannot complete within the inference stage ceiling")
    inference = min(REMOTE_INFERENCE_MAX_SECONDS, exec_seconds - REMOTE_PREPARE_MIN_SECONDS)
    prepare = min(REMOTE_PREPARE_MAX_SECONDS, exec_seconds - inference)
    if prepare < REMOTE_PREPARE_MIN_SECONDS or inference < required:
        raise DevelopmentRunError(
            "remaining CU budget cannot cover V2 prepare and worst-case inference"
        )
    return {"prepare": prepare, "infer": inference}


def _cost_guard(
    *,
    run_id: str,
    balance_before_allocation: float,
    prior_spend_cu: float,
    initial_rate: float,
    allocated_at: float,
    halt: threading.Event,
    result: dict[str, Any],
    lock: threading.Lock,
) -> None:
    maximum_rate = initial_rate
    while not halt.wait(COST_POLL_SECONDS):
        try:
            usage = _run_colab(
                ["colab", "--auth=oauth2", "usage"], timeout=a02_execution.VERIFY_TIMEOUT_SECONDS
            )
            if usage.returncode != 0:
                raise DevelopmentRunError("live Colab budget monitor failed")
            balance, rate, _ = a02_execution._parse_current_usage(usage.stdout)
            if balance > balance_before_allocation:
                raise DevelopmentRunError(
                    "Colab balance increased during session; budget is ambiguous"
                )
            if rate <= 0:
                raise DevelopmentRunError("live Colab usage rate became unknown")
            maximum_rate = max(maximum_rate, rate)
            elapsed = time.monotonic() - allocated_at
            account_delta = max(0.0, balance_before_allocation - balance)
            usage_upper_bound = max(account_delta, maximum_rate * elapsed / 3600)
            total_upper_bound = prior_spend_cu + usage_upper_bound
            reserve = COST_BUFFER_CU + maximum_rate * (COST_POLL_SECONDS + 2) / 3600
            if balance <= 0 or total_upper_bound + reserve >= CAMPAIGN_CU_CAP:
                raise DevelopmentRunError("campaign cost guard reached its conservative stop bound")
            with lock:
                result.update(
                    last_balance=balance,
                    max_usage_rate_cu_per_hour=maximum_rate,
                    estimated_campaign_spend_upper_bound=total_upper_bound,
                )
        except Exception as exc:
            stop_error: str | None = None
            try:
                stop = _stop_exact_session(run_id)
                stop_code = stop.returncode
                stop_failed = False
            except ColabCommandError as stop_exc:
                stop_code = None
                stop_failed = True
                stop_error = str(stop_exc)
            with lock:
                result["stop_reason"] = str(exc)
                result["monitor_stop_exit_code"] = stop_code
                result["monitor_stopped_target"] = not stop_failed
                if stop_error:
                    result["monitor_stop_error"] = stop_error
            return


def run_campaign_session() -> dict[str, Any]:
    authorization = _load_authorization()
    source = _source_state()
    if (
        authorization.get("branch") != source["branch"]
        or authorization.get("development_profile_sha256") != source["profile_sha256"]
    ):
        raise DevelopmentRunError(
            "campaign-level authorization does not bind the current development profile"
        )
    quota_before = _colab_snapshot()
    initial_balance = float(authorization["initial_compute_unit_balance"])
    markers = _used_session_markers()
    followup, session_index, prior_spend, remaining_before = _resolve_session_scope(
        authorization, source, quota_before, markers
    )
    run_id = (
        f"res541-a02-dev-v2-{session_index:03d}-"
        f"{source['profile_sha256'][:8]}-{uuid.uuid4().hex[:8]}"
    )
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    preflight_copy = run_dir / "development-preflight-v2.json"
    preflight_copy.write_bytes(source["preflight_path"].read_bytes())
    if followup is not None:
        (run_dir / "followup-authorization.json").write_bytes(
            _followup_authorization_path(session_index).read_bytes()
        )
    source_archive = run_dir / "source.tar"
    with source_archive.open("xb") as archive:
        subprocess.run(
            ["git", "archive", "--format=tar", "HEAD"],
            cwd=ROOT,
            check=True,
            stdout=archive,
        )
    if source_archive.stat().st_size > 64 * 1024**2:
        raise DevelopmentRunError("V2 source archive exceeds the fixed upload bound")
    protocol_bytes = a02_dev_protocol.ROOT.joinpath("experiments/a02/protocol-v1.json").read_bytes()
    binding = {
        "schema": "RES541_A02_DEVELOPMENT_BINDING_V2",
        "execution_mode": "development_v2",
        "run_id": run_id,
        "session_index": session_index,
        "campaign_authorization_sha256": authorization["authorization_sha256"],
        "campaign_followup_authorization_sha256": (
            followup["authorization_sha256"] if followup is not None else None
        ),
        "branch": source["branch"],
        "source_revision": source["source_revision"],
        "source_tree": source["source_tree"],
        "source_archive_sha256": _sha(source_archive.read_bytes()),
        "protocol_sha256": _sha(protocol_bytes),
        "development_profile_sha256": source["profile_sha256"],
        "development_preflight_sha256": source["preflight_sha256"],
        "runtime_policy_id": source["runtime_policy_id"],
        "runtime_policy_sha256": source["runtime_policy_sha256"],
        "baseline_remote_report_sha256": a02_dev_protocol.load_profile()["baseline"][
            "remote_report_sha256"
        ],
        "model_revision": a02_dev_protocol.load_profile()["model"]["revision"],
        "requested_gpu": "T4",
        "max_session_seconds": SESSION_SECONDS,
        "max_exec_seconds": EXEC_SECONDS,
        "remote_stage_timeouts_seconds": {
            "prepare": REMOTE_PREPARE_MAX_SECONDS,
            "infer": REMOTE_INFERENCE_MAX_SECONDS,
        },
        "no_retry": True,
        "no_upgrade": True,
        "training": False,
        "remote_report": REMOTE_REPORT,
    }
    binding_path = run_dir / "binding.json"
    binding_bytes = (json.dumps(binding, indent=2, sort_keys=True) + "\n").encode()
    binding_path.write_bytes(binding_bytes)
    marker = {
        "schema": "RES541_A02_DEVELOPMENT_SESSION_USED_V2",
        "campaign_authorization_sha256": authorization["authorization_sha256"],
        "followup_authorization_sha256": (
            followup["authorization_sha256"] if followup is not None else None
        ),
        "development_profile_sha256": source["profile_sha256"],
        "session_index": session_index,
        "run_id": run_id,
        "source_revision": source["source_revision"],
        "source_tree": source["source_tree"],
        "development_preflight_sha256": source["preflight_sha256"],
        "binding_sha256": _sha(binding_bytes),
        "recorded_at_utc": datetime.now(UTC).isoformat(),
    }
    marker_path = run_dir / "session-used.json"
    control_path = run_dir / "control.json"
    state: dict[str, Any] = {
        "schema": "RES541_A02_DEVELOPMENT_CONTROL_V2",
        "status": "PREPARED",
        "run_id": run_id,
        "session_index": session_index,
        "campaign_authorization_sha256": authorization["authorization_sha256"],
        "campaign_followup_authorization_sha256": (
            followup["authorization_sha256"] if followup is not None else None
        ),
        "source_revision": source["source_revision"],
        "development_profile_sha256": source["profile_sha256"],
        "development_preflight_sha256": source["preflight_sha256"],
        "usage_before": quota_before,
        "compute_unit_balance_after_campaign_authorization": initial_balance,
        "compute_unit_spend_before_session": prior_spend,
        "remaining_campaign_budget_before_session": remaining_before,
        "session_seconds_limit": SESSION_SECONDS,
        "exec_seconds_limit": EXEC_SECONDS,
        "automatic_retry": False,
        "paid_upgrade": False,
        "training": False,
    }
    _write_state(control_path, state)
    remote_artifact = run_dir / "remote-report.json"
    watchdog: subprocess.Popen[str] | None = None
    monitor: threading.Thread | None = None
    monitor_halt = threading.Event()
    monitor_state: dict[str, Any] = {}
    monitor_lock = threading.Lock()
    target_endpoint: str | None = None
    allocation_attempted = False
    allocated_at = 0.0
    try:
        state["watchdog_phase"] = "START_REQUESTED"
        _write_state(control_path, state)
        watchdog = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "scripts.a02_execution",
                "watchdog",
                run_id,
                str(run_dir / "watchdog-receipt.json"),
            ],
            cwd=ROOT,
            env=a02_execution.clean_colab_env(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            start_new_session=True,
        )
        if watchdog.stdout is None:
            raise DevelopmentRunError("V2 watchdog readiness pipe is unavailable")
        ready, _, _ = select.select([watchdog.stdout], [], [], 10)
        if not ready or watchdog.stdout.readline().strip() != "READY":
            raise DevelopmentRunError("V2 watchdog did not become ready")
        state["watchdog_phase"] = "STARTED"
        state["watchdog_pid"] = watchdog.pid
        _write_state(control_path, state)

        _write_exclusive(marker_path, marker)
        state["session_marker_sha256"] = _sha(marker_path.read_bytes())
        state["status"] = "ALLOCATION_REQUESTED"
        _write_state(control_path, state)
        allocation_attempted = True
        allocated_at = time.monotonic()
        created = _run_colab(
            ["colab", "--auth=oauth2", "new", "--session", run_id, "--gpu", "T4"],
            timeout=a02_execution.NEW_TIMEOUT_SECONDS,
        )
        state["allocation_returncode"] = created.returncode
        if created.returncode != 0:
            raise DevelopmentRunError("single V2 T4 allocation failed; no retry or upgrade")
        status = _run_colab(
            ["colab", "--auth=oauth2", "status", "--session", run_id],
            timeout=a02_execution.VERIFY_TIMEOUT_SECONDS,
        )
        if status.returncode != 0 or "T4" not in status.stdout.upper():
            raise DevelopmentRunError("Colab did not verify the exact requested T4 session")
        target_rows = [
            row for row in a02_execution._session_rows(status.stdout) if row[0] == run_id
        ]
        if len(target_rows) != 1 or target_rows[0][2].upper() != "T4":
            raise DevelopmentRunError("exact V2 session name, endpoint, or T4 hardware differs")
        target_endpoint = target_rows[0][1]
        state["target_endpoint"] = target_endpoint
        state["target_status"] = status.stdout.strip()
        after_allocation = _colab_snapshot()
        if after_allocation["balance"] > quota_before["balance"]:
            raise DevelopmentRunError(
                "Colab balance increased during allocation; budget is ambiguous"
            )
        before_sessions = {row["endpoint"] for row in quota_before["active_sessions"]}
        after_unrelated = {
            row["endpoint"]
            for row in after_allocation["active_sessions"]
            if row["endpoint"] != target_endpoint
        }
        if before_sessions != after_unrelated or target_endpoint not in {
            row["endpoint"] for row in after_allocation["active_sessions"]
        }:
            raise DevelopmentRunError("unrelated Colab session inventory changed during allocation")
        current_rate = after_allocation["usage_rate_cu_per_hour"]
        spent_after_allocation = max(0.0, initial_balance - after_allocation["balance"])
        remaining_after_allocation = CAMPAIGN_CU_CAP - spent_after_allocation
        safe_exec_seconds = _safe_exec_seconds(remaining_after_allocation, current_rate)
        elapsed = time.monotonic() - allocated_at
        exec_timeout = min(
            safe_exec_seconds - math.ceil(elapsed) - CLEANUP_RESERVE_SECONDS,
            EXEC_SECONDS,
        )
        stage_timeouts = _split_stage_timeouts(exec_timeout)
        state.update(
            usage_after_allocation=after_allocation,
            current_account_usage_rate_cu_per_hour=current_rate,
            estimated_safe_exec_seconds=exec_timeout,
            remote_stage_timeouts_seconds=stage_timeouts,
        )
        _write_state(control_path, state)
        monitor = threading.Thread(
            target=_cost_guard,
            kwargs={
                "run_id": run_id,
                "balance_before_allocation": quota_before["balance"],
                "prior_spend_cu": prior_spend,
                "initial_rate": current_rate,
                "allocated_at": allocated_at,
                "halt": monitor_halt,
                "result": monitor_state,
                "lock": monitor_lock,
            },
            name=f"a02-v2-budget-{session_index}",
            daemon=True,
        )
        monitor.start()

        for local_path, remote_path in (
            (source_archive, REMOTE_SOURCE),
            (binding_path, REMOTE_BINDING),
            (preflight_copy, REMOTE_PREFLIGHT),
        ):
            uploaded = _run_colab(
                [
                    "colab",
                    "--auth=oauth2",
                    "upload",
                    "--session",
                    run_id,
                    str(local_path),
                    remote_path,
                ],
                timeout=a02_execution.UPLOAD_TIMEOUT_SECONDS,
            )
            if uploaded.returncode != 0:
                raise DevelopmentRunError(f"V2 upload failed: {remote_path}")
        state["status"] = "REMOTE_PREPARE_REQUESTED"
        state["exec_timeout_seconds"] = exec_timeout
        _write_state(control_path, state)
        prepare_report = run_dir / "remote-prepare-report.json"
        prepared = _run_remote_stage(
            run_id=run_id,
            stage="prepare",
            timeout=stage_timeouts["prepare"],
            report_path=prepare_report,
            source=source,
            control_path=control_path,
            state=state,
        )
        if prepared:
            state["status"] = "REMOTE_INFERENCE_REQUESTED"
            _write_state(control_path, state)
            inferred = _run_remote_stage(
                run_id=run_id,
                stage="infer",
                timeout=stage_timeouts["infer"],
                report_path=remote_artifact,
                source=source,
                control_path=control_path,
                state=state,
            )
            state["remote_inference_verified"] = inferred
            if not inferred:
                state["status"] = "REMOTE_INFERENCE_INCOMPLETE"
                _write_state(control_path, state)
        else:
            state["status"] = "REMOTE_PREPARE_INCOMPLETE"
            _write_state(control_path, state)
    except Exception as exc:
        state["control_error_category"] = type(exc).__name__
        state["control_error"] = str(exc)[:1000]
        if isinstance(exc, ColabCommandError):
            _record_command_failure(state, state.get("active_remote_stage", "CONTROL"), exc)
    finally:
        monitor_halt.set()
        if monitor is not None:
            monitor.join(timeout=15)
        with monitor_lock:
            state["budget_monitor"] = dict(monitor_state)
        if allocation_attempted:
            if not remote_artifact.is_file():
                _download_stage_report(
                    run_id=run_id,
                    stage="final_recovery",
                    local_path=remote_artifact,
                    source=source,
                    control_path=control_path,
                    state=state,
                )
            complete_report = False
            if remote_artifact.is_file():
                try:
                    current_report = json.loads(remote_artifact.read_bytes())
                    complete_report = _remote_report_is_complete(current_report, run_id, source)
                except (OSError, json.JSONDecodeError):
                    pass
            if not complete_report:
                _download_stage_report(
                    run_id=run_id,
                    stage="final_latest_recovery",
                    local_path=run_dir / "remote-latest-report.json",
                    source=source,
                    control_path=control_path,
                    state=state,
                )
            monitor_stopped = (
                monitor_state.get("monitor_stopped_target") is True
                and monitor_state.get("monitor_stop_exit_code") == 0
            )
            if monitor_stopped:
                state["stop_returncode"] = monitor_state.get("monitor_stop_exit_code")
                state["stop_by_budget_guard"] = True
            else:
                try:
                    stopped = _stop_exact_session(run_id)
                    state["stop_returncode"] = stopped.returncode
                except ColabCommandError as exc:
                    state["stop_returncode"] = None
                    _record_command_failure(state, "STOP_EXACT_TARGET", exc)
                state["stop_by_budget_guard"] = False
            state["stop_requested_at_utc"] = datetime.now(UTC).isoformat()
            try:
                sessions_after = _run_colab(
                    ["colab", "--auth=oauth2", "sessions"],
                    timeout=a02_execution.VERIFY_TIMEOUT_SECONDS,
                )
                assignments_after = _run_colab(
                    a02_execution._assignment_command(),
                    timeout=a02_execution.VERIFY_TIMEOUT_SECONDS,
                )
                state["target_absent_after_stop"] = a02_execution._verify_target_absent(
                    sessions_after, run_id, target_endpoint, assignments_after
                )
                state["sessions_after_stop"] = sessions_after.stdout.strip()
                state["assignments_after_stop_sha256"] = _sha(assignments_after.stdout.encode())
            except Exception as exc:
                state["target_absent_after_stop"] = False
                state["teardown_error"] = type(exc).__name__
                state["usage_accounting_error"] = True
            try:
                usage_after = _run_colab(
                    ["colab", "--auth=oauth2", "usage"],
                    timeout=a02_execution.VERIFY_TIMEOUT_SECONDS,
                )
                state["usage_after_returncode"] = usage_after.returncode
                if usage_after.returncode == 0:
                    after_balance, after_rate, after_assignments = (
                        a02_execution._parse_current_usage(usage_after.stdout)
                    )
                    state["compute_unit_balance_after"] = after_balance
                    state["usage_rate_after_cu_per_hour"] = after_rate
                    state["active_assignment_count_after"] = after_assignments
                    if after_balance > quota_before["balance"]:
                        state["usage_accounting_error"] = True
                    else:
                        state["campaign_compute_unit_spend"] = max(
                            0.0, initial_balance - after_balance
                        )
                else:
                    state["usage_accounting_error"] = True
            except ColabCommandError as exc:
                state["usage_accounting_error"] = True
                _record_command_failure(state, "POST_RUN_USAGE", exc)
        state["finished_at_utc"] = datetime.now(UTC).isoformat()
        state["status"] = "CONTROL_FINISHED"
        _write_state(control_path, state)
        if watchdog is not None and watchdog.stdin is not None:
            try:
                if not allocation_attempted or state.get("target_absent_after_stop") is True:
                    watchdog.stdin.write("D")
                    watchdog.stdin.flush()
                watchdog.stdin.close()
                state["watchdog_phase"] = (
                    "DISARMED"
                    if not allocation_attempted or state.get("target_absent_after_stop")
                    else "TRIGGERED"
                )
            except (OSError, BrokenPipeError):
                state["watchdog_phase"] = "UNKNOWN"
        _write_state(control_path, state)

    target_safe = state.get("target_absent_after_stop") is True
    stop_confirmed = state.get("stop_returncode") == 0
    budget_spent = state.get("campaign_compute_unit_spend")
    if budget_spent is not None and budget_spent > CAMPAIGN_CU_CAP:
        state["terminal_outcome"] = "EXTERNAL_BLOCKER"
        state["external_blocker"] = "ACCOUNT_SPEND_EXCEEDED_OR_AMBIGUOUS"
    elif not target_safe or not stop_confirmed:
        state["terminal_outcome"] = "EXTERNAL_BLOCKER"
        state["external_blocker"] = "EXACT_TARGET_TEARDOWN_NOT_VERIFIED"
    elif state.get("control_error_category"):
        state["terminal_outcome"] = "EXTERNAL_BLOCKER"
        state["external_blocker"] = state["control_error_category"]
    elif state.get("budget_monitor", {}).get("stop_reason"):
        state["terminal_outcome"] = "EXTERNAL_BLOCKER"
        state["external_blocker"] = state["budget_monitor"]["stop_reason"]
    elif (
        state.get("usage_accounting_error") is True
        or state.get("campaign_compute_unit_spend") is None
    ):
        state["terminal_outcome"] = "EXTERNAL_BLOCKER"
        state["external_blocker"] = "POST_RUN_USAGE_ACCOUNTING_MISSING"
    elif not remote_artifact.is_file():
        state["terminal_outcome"] = "EXTERNAL_BLOCKER"
        state["external_blocker"] = "REMOTE_REPORT_NOT_DOWNLOADED"
    elif state.get("remote_inference_verified") is not True:
        state["terminal_outcome"] = "EXTERNAL_BLOCKER"
        state["external_blocker"] = "REMOTE_INFERENCE_COMPLETION_NOT_VERIFIED"
    else:
        try:
            report = json.loads(remote_artifact.read_bytes())
            if not _remote_report_is_complete(report, run_id, source):
                raise DevelopmentRunError("remote report is partial, unbound, or incomplete")
            verification = a02_dev_score.verify_files(
                remote_artifact,
                preflight_copy,
                run_dir / "verified-development-v2.json",
            )
            state["verification"] = verification
            state["terminal_outcome"] = verification["terminal_outcome"]
        except Exception as exc:
            state["terminal_outcome"] = "EXTERNAL_BLOCKER"
            state["external_blocker"] = "REMOTE_REPORT_NOT_VERIFIED_AS_COMPLETE"
            state["verification_error_category"] = type(exc).__name__
            state["verification_error"] = str(exc)[:1000]
    _write_state(control_path, state)
    artifact_rows = []
    for path in sorted(run_dir.iterdir()):
        if path.is_file() and path.name != "artifact-hashes.json":
            data = path.read_bytes()
            artifact_rows.append(
                {
                    "name": path.name,
                    "local_path": str(path),
                    "bytes": len(data),
                    "sha256": _sha(data),
                }
            )
    artifact_manifest = {
        "schema": "RES541_A02_DEVELOPMENT_ARTIFACT_HASHES_V2",
        "run_id": run_id,
        "terminal_outcome": state["terminal_outcome"],
        "files": artifact_rows,
    }
    _write_exclusive(run_dir / "artifact-hashes.json", artifact_manifest)
    return {
        "run_id": run_id,
        "run_directory": str(run_dir),
        "terminal_outcome": state["terminal_outcome"],
        "artifact_manifest_sha256": _sha((run_dir / "artifact-hashes.json").read_bytes()),
        "gpu_allocated": allocation_attempted,
        "campaign_compute_unit_spend": state.get("campaign_compute_unit_spend"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("authorize", "authorize-retry", "authorize-next", "run")
    )
    parser.add_argument("--approval-text")
    args = parser.parse_args()
    try:
        if args.command == "authorize":
            result = authorize_campaign()
        elif args.command in ("authorize-retry", "authorize-next"):
            if args.approval_text is None:
                raise DevelopmentRunError("the follow-up owner approval reference is required")
            result = authorize_followup_session(
                args.approval_text,
                session_index=CAMPAIGN_SESSION_CAP + (2 if args.command == "authorize-next" else 1),
            )
        else:
            if args.approval_text is not None:
                raise DevelopmentRunError("approval text applies only to authorization commands")
            result = run_campaign_session()
    except (DevelopmentRunError, a02_execution.RunError, OSError, ValueError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, indent=2))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result.get("terminal_outcome") == "EXTERNAL_BLOCKER" else 0


if __name__ == "__main__":
    raise SystemExit(main())
