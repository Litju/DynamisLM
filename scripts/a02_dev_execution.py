"""One-time-budget control plane for the RES-541 V2 development campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import select
import subprocess
import sys
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts import a02_dev_protocol, a02_dev_score, a02_execution

ROOT = a02_execution.ROOT
E_ROOT = a02_execution.E_ROOT
CAMPAIGN_DIR = E_ROOT / "a02/development-v2"
AUTHORIZATION_PATH = CAMPAIGN_DIR / "authorization.json"
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


class DevelopmentRunError(RuntimeError):
    pass


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
    }


def _colab_snapshot() -> dict[str, Any]:
    version = a02_execution._run(["colab", "version"], timeout=15)
    identity = a02_execution._run(["colab", "--auth=oauth2", "whoami"], timeout=15)
    usage = a02_execution._run(["colab", "--auth=oauth2", "usage"], timeout=30)
    sessions = a02_execution._run(["colab", "--auth=oauth2", "sessions"], timeout=30)
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
        raise DevelopmentRunError("Colab CLI and provider assignment inventories differ")
    if usage_assignments != len(assignments):
        raise DevelopmentRunError("Colab usage and provider assignment counts differ")
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


def _authorization_phrase(source: dict[str, Any], quota: dict[str, Any]) -> str:
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


def authorize_campaign() -> dict[str, Any]:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise DevelopmentRunError("one-time campaign approval requires an interactive WSL terminal")
    a02_execution._check_e_mount()
    if AUTHORIZATION_PATH.exists():
        raise DevelopmentRunError("V2 campaign already has an immutable owner authorization")
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
    phrase = _authorization_phrase(source, quota)
    print(
        "This records one owner approval for the entire bounded V2 campaign. It allocates no GPU."
    )
    print(f"Type exactly: {phrase}")
    if input("> ") != phrase:
        raise DevelopmentRunError(
            "campaign authorization text did not match; no marker was written"
        )
    fresh_source = _source_state()
    fresh_quota = _colab_snapshot()
    if any(
        fresh_source[key] != source[key]
        for key in (
            "branch",
            "source_revision",
            "source_tree",
            "preflight_sha256",
            "profile_sha256",
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
        raise DevelopmentRunError("source or quota changed during one-time campaign approval")
    authorization: dict[str, Any] = {
        "schema": "RES541_A02_DEVELOPMENT_CAMPAIGN_AUTHORIZATION_V1",
        "status": "OWNER_AUTHORIZED",
        "branch": source["branch"],
        "source_revision": source["source_revision"],
        "source_tree": source["source_tree"],
        "development_profile_sha256": source["profile_sha256"],
        "development_preflight_sha256": source["preflight_sha256"],
        "campaign_cap_cu": CAMPAIGN_CU_CAP,
        "max_t4_sessions": CAMPAIGN_SESSION_CAP,
        "max_session_seconds": SESSION_SECONDS,
        "max_exec_seconds": EXEC_SECONDS,
        "no_upgrade": True,
        "no_training": True,
        "initial_compute_unit_balance": quota["balance"],
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


def _load_authorization() -> dict[str, Any]:
    if not AUTHORIZATION_PATH.is_file():
        raise DevelopmentRunError("one-time V2 campaign budget authorization is required")
    value = json.loads(AUTHORIZATION_PATH.read_bytes())
    if not isinstance(value, dict):
        raise DevelopmentRunError("V2 campaign authorization record is invalid")
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
        or confirmation != _authorization_phrase(source, quota)
        or value.get("owner_confirmation_sha256") != _sha(confirmation.encode())
    ):
        raise DevelopmentRunError("V2 campaign authorization record failed integrity checks")
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


def _next_session_index(markers: list[dict[str, Any]]) -> int:
    if len(markers) >= CAMPAIGN_SESSION_CAP:
        raise DevelopmentRunError("V2 campaign has exhausted its T4 session cap")
    if markers:
        raise DevelopmentRunError("the V2 ten-case profile is single-use; no repeat after a run")
    return 1


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
            usage = a02_execution._run(
                ["colab", "--auth=oauth2", "usage"], timeout=a02_execution.VERIFY_TIMEOUT_SECONDS
            )
            if usage.returncode != 0:
                raise DevelopmentRunError("live Colab budget monitor failed")
            balance, rate, _ = a02_execution._parse_current_usage(usage.stdout)
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
            stop = a02_execution._run(
                ["colab", "--auth=oauth2", "stop", "--session", run_id],
                timeout=a02_execution.STOP_TIMEOUT_SECONDS,
            )
            with lock:
                result["stop_reason"] = str(exc)
                result["monitor_stop_exit_code"] = stop.returncode
                result["monitor_stopped_target"] = True
            return


def run_campaign_session() -> dict[str, Any]:
    authorization = _load_authorization()
    source = _source_state()
    if any(
        authorization.get(key) != source[auth_key]
        for key, auth_key in (
            ("branch", "branch"),
            ("source_revision", "source_revision"),
            ("source_tree", "source_tree"),
            ("development_profile_sha256", "profile_sha256"),
            ("development_preflight_sha256", "preflight_sha256"),
        )
    ):
        raise DevelopmentRunError(
            "V2 campaign authorization does not bind the clean current source"
        )
    quota_before = _colab_snapshot()
    initial_balance = float(authorization["initial_compute_unit_balance"])
    prior_spend = max(0.0, initial_balance - quota_before["balance"])
    remaining_before = CAMPAIGN_CU_CAP - prior_spend
    if remaining_before <= COST_BUFFER_CU or quota_before["balance"] <= 0:
        raise DevelopmentRunError("authorized V2 campaign budget is exhausted or ambiguous")
    markers = _used_session_markers()
    session_index = _next_session_index(markers)
    run_id = (
        f"res541-a02-dev-v2-{session_index:03d}-"
        f"{source['profile_sha256'][:8]}-{uuid.uuid4().hex[:8]}"
    )
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    preflight_copy = run_dir / "development-preflight-v2.json"
    preflight_copy.write_bytes(source["preflight_path"].read_bytes())
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
        "branch": source["branch"],
        "source_revision": source["source_revision"],
        "source_tree": source["source_tree"],
        "source_archive_sha256": _sha(source_archive.read_bytes()),
        "protocol_sha256": _sha(protocol_bytes),
        "development_profile_sha256": source["profile_sha256"],
        "development_preflight_sha256": source["preflight_sha256"],
        "baseline_remote_report_sha256": a02_dev_protocol.load_profile()["baseline"][
            "remote_report_sha256"
        ],
        "model_revision": a02_dev_protocol.load_profile()["model"]["revision"],
        "requested_gpu": "T4",
        "max_session_seconds": SESSION_SECONDS,
        "max_exec_seconds": EXEC_SECONDS,
        "no_retry": True,
        "no_upgrade": True,
        "training": False,
        "remote_report": REMOTE_REPORT,
    }
    binding_path = run_dir / "binding.json"
    binding_bytes = (json.dumps(binding, indent=2, sort_keys=True) + "\n").encode()
    binding_path.write_bytes(binding_bytes)
    marker = {
        "schema": "RES541_A02_DEVELOPMENT_SESSION_USED_V1",
        "campaign_authorization_sha256": authorization["authorization_sha256"],
        "development_profile_sha256": source["profile_sha256"],
        "session_index": session_index,
        "run_id": run_id,
        "source_revision": source["source_revision"],
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
        created = a02_execution._run(
            ["colab", "--auth=oauth2", "new", "--session", run_id, "--gpu", "T4"],
            timeout=a02_execution.NEW_TIMEOUT_SECONDS,
        )
        state["allocation_returncode"] = created.returncode
        if created.returncode != 0:
            raise DevelopmentRunError("single V2 T4 allocation failed; no retry or upgrade")
        status = a02_execution._run(
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
        if exec_timeout < 30:
            raise DevelopmentRunError("remaining CU budget cannot safely bound V2 inference")
        state.update(
            usage_after_allocation=after_allocation,
            current_account_usage_rate_cu_per_hour=current_rate,
            estimated_safe_exec_seconds=exec_timeout,
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
            uploaded = a02_execution._run(
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
        state["status"] = "INFERENCE_REQUESTED"
        state["exec_timeout_seconds"] = exec_timeout
        _write_state(control_path, state)
        execution = a02_execution._run(
            [
                "colab",
                "--auth=oauth2",
                "exec",
                "--session",
                run_id,
                "--file",
                str(ROOT / "scripts/a02_dev_remote.py"),
                "--timeout",
                str(exec_timeout),
            ],
            timeout=exec_timeout + 30,
        )
        state["exec_returncode"] = execution.returncode
        state["exec_stderr_tail"] = execution.stderr[-1000:]
        downloaded = a02_execution._run(
            [
                "colab",
                "--auth=oauth2",
                "download",
                "--session",
                run_id,
                REMOTE_REPORT,
                str(remote_artifact),
            ],
            timeout=a02_execution.DOWNLOAD_TIMEOUT_SECONDS,
        )
        state["download_returncode"] = downloaded.returncode
        if downloaded.returncode != 0:
            state["download_stderr_tail"] = downloaded.stderr[-1000:]
    except Exception as exc:
        state["control_error_category"] = type(exc).__name__
        state["control_error"] = str(exc)[:1000]
    finally:
        monitor_halt.set()
        if monitor is not None:
            monitor.join(timeout=15)
        with monitor_lock:
            state["budget_monitor"] = dict(monitor_state)
        if allocation_attempted:
            if not remote_artifact.is_file():
                try:
                    downloaded = a02_execution._run(
                        [
                            "colab",
                            "--auth=oauth2",
                            "download",
                            "--session",
                            run_id,
                            REMOTE_REPORT,
                            str(remote_artifact),
                        ],
                        timeout=a02_execution.DOWNLOAD_TIMEOUT_SECONDS,
                    )
                    state["final_download_returncode"] = downloaded.returncode
                    if downloaded.returncode != 0:
                        state["final_download_stderr_tail"] = downloaded.stderr[-1000:]
                except Exception as exc:
                    state["final_download_error"] = type(exc).__name__
            monitor_stopped = (
                monitor_state.get("monitor_stopped_target") is True
                and monitor_state.get("monitor_stop_exit_code") == 0
            )
            if monitor_stopped:
                state["stop_returncode"] = monitor_state.get("monitor_stop_exit_code")
                state["stop_by_budget_guard"] = True
            else:
                stopped = a02_execution._run(
                    ["colab", "--auth=oauth2", "stop", "--session", run_id],
                    timeout=a02_execution.STOP_TIMEOUT_SECONDS,
                )
                state["stop_returncode"] = stopped.returncode
                state["stop_by_budget_guard"] = False
            state["stop_requested_at_utc"] = datetime.now(UTC).isoformat()
            sessions_after = a02_execution._run(
                ["colab", "--auth=oauth2", "sessions"],
                timeout=a02_execution.VERIFY_TIMEOUT_SECONDS,
            )
            assignments_after = a02_execution._run(
                a02_execution._assignment_command(),
                timeout=a02_execution.VERIFY_TIMEOUT_SECONDS,
            )
            try:
                state["target_absent_after_stop"] = a02_execution._verify_target_absent(
                    sessions_after, run_id, target_endpoint, assignments_after
                )
            except Exception as exc:
                state["target_absent_after_stop"] = False
                state["teardown_error"] = type(exc).__name__
            state["sessions_after_stop"] = sessions_after.stdout.strip()
            state["assignments_after_stop_sha256"] = _sha(assignments_after.stdout.encode())
            usage_after = a02_execution._run(
                ["colab", "--auth=oauth2", "usage"],
                timeout=a02_execution.VERIFY_TIMEOUT_SECONDS,
            )
            state["usage_after_returncode"] = usage_after.returncode
            if usage_after.returncode == 0:
                after_balance, after_rate, after_assignments = a02_execution._parse_current_usage(
                    usage_after.stdout
                )
                state["compute_unit_balance_after"] = after_balance
                state["usage_rate_after_cu_per_hour"] = after_rate
                state["active_assignment_count_after"] = after_assignments
                state["campaign_compute_unit_spend"] = max(0.0, initial_balance - after_balance)
            else:
                state["usage_accounting_error"] = True
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
    else:
        try:
            verification = a02_dev_score.verify_files(
                remote_artifact,
                preflight_copy,
                run_dir / "verified-development-v2.json",
            )
            state["verification"] = verification
            state["terminal_outcome"] = verification["terminal_outcome"]
        except Exception as exc:
            state["terminal_outcome"] = "SCIENTIFIC_NO_GO"
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
    parser.add_argument("command", choices=("authorize", "run"))
    args = parser.parse_args()
    try:
        result = authorize_campaign() if args.command == "authorize" else run_campaign_session()
    except (DevelopmentRunError, a02_execution.RunError, OSError, ValueError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, indent=2))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result.get("terminal_outcome") == "EXTERNAL_BLOCKER" else 0


if __name__ == "__main__":
    raise SystemExit(main())
