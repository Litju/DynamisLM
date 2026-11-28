"""Allocate one qualified T4, run the frozen A1 campaign, retain evidence, tear down (RES-832).

Owner authorization for the continuation campaign is restated here as the code's hard limits:

* accelerators: one qualified Tesla T4 only, never a different one;
* additional cumulative GPU wall clock: at most 5 h 55 min (21,300 s);
* additional cumulative spend: at most 11.0 existing compute units;
* additional sessions: at most 4, counting retries;
* provider rate ceiling: 1.65 CU/h;
* no purchases, subscriptions or paid upgrades.

The controller allocates nothing until it has verified an idle authenticated account, a positive
balance, an unused exact target and a live T4 quote inside the authorized rate. It stops the
session and verifies exact-target absence on every path, including exceptions.

Failure policy
--------------
A deterministic worker, setup, generation or evidence-harvesting failure aborts the campaign: no
further session is allocated on the same defect. A normal time-slice interruption that committed
verified progress is not a failure; it is resumed by the next session from the harvested chains.
The distinction is made from the worker's own phase record and from the committed line count, not
from a wall-clock guess.

Resumption is a property of the frozen work order, not of the controller: the worker appends to
per-arm hash-chained files, so a later session continues exactly where the previous one stopped
and never regenerates a committed call.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import tarfile
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import a02_v3_supervision as supervision  # noqa: E402
from scripts.a02_v3_execution import ColabCLI  # noqa: E402

WORK = ROOT / "experiments/a1/.campaign"
RUNS = ROOT / "experiments/a1/.runs"
WORKER = ROOT / "scripts/a1_colab_worker.py"
NAME = "dynamislm-res832-a1"
# Continuation envelope (RES-832 owner authorization, 2026-11-28).
HARD_CAP_CU = 11.0
HARD_CAP_SECONDS = 5 * 3600 + 55 * 60
MAX_SESSIONS = 4
MAX_RATE_CU_PER_HOUR = 1.65
RESERVE_CU = 0.20
# Historical attempt record. Never modified; reported separately and added to the totals.
ATTEMPT_1 = {"modeled_cu": 0.925, "wall_clock_seconds": 272.3, "sessions": 4, "generations": 0}
# A session must fit inside the independent watchdog and inside one exec invocation.
SESSION_SECONDS = 5400
WATCHDOG_SECONDS = 2 * SESSION_SECONDS
SETUP_RESERVE_SECONDS = 720
CLEANUP_SECONDS = 120
FETCH_SECONDS = 300
MIN_GENERATION_SECONDS = 300
PROGRESS_POLL_SECONDS = 20


class ControllerError(RuntimeError):
    pass


class DefectError(ControllerError):
    """A deterministic defect: further allocation is forbidden until it is repaired."""


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def model_cost(elapsed: float, rate: float = MAX_RATE_CU_PER_HOUR) -> float:
    """Conservative modelled spend: elapsed time at the authorized ceiling rate plus a reserve."""
    return math.ceil((elapsed * rate / 3600 + RESERVE_CU) * 10000) / 10000


def exact_live(snapshot: dict[str, Any], name: str, endpoint: str) -> bool:
    return bool(
        0 < snapshot["usage_rate_cu_per_hour"] <= MAX_RATE_CU_PER_HOUR
        and snapshot["active_assignment_count"] == 1
        and snapshot["active_sessions"] == [{"name": name, "endpoint": endpoint, "hardware": "T4"}]
    )


class A1Colab(ColabCLI):
    watchdog_seconds = WATCHDOG_SECONDS


def build_payload(directory: Path) -> tuple[Path, dict[str, Any]]:
    """Assemble the upload: minimal gold-free source, verified work order, adapter bundle."""
    from scripts import a1_payload

    return a1_payload.build(directory)


def _invoke(client: ColabCLI, phase: str, timeout: int, env: dict[str, str]) -> dict[str, Any]:
    command = [
        "colab",
        "--auth=oauth2",
        "exec",
        "--session",
        NAME,
        "--file",
        str(WORKER),
        "--timeout",
        str(timeout + 120),
    ]
    for key, value in env.items():
        command += ["--env", f"{key}={value}"]
    started = time.monotonic()
    try:
        result = client._run(command, timeout=timeout + 180)
        return {
            "phase": phase,
            "returncode": result.returncode,
            "stdout": result.stdout[-4000:],
            "stderr": result.stderr[-4000:],
            "seconds": round(time.monotonic() - started, 1),
        }
    except Exception as exc:
        return {
            "phase": phase,
            "returncode": None,
            "error": f"{type(exc).__name__}: {exc}",
            "seconds": round(time.monotonic() - started, 1),
        }


def _remote_status(client: ColabCLI) -> dict[str, Any]:
    result = client._run(
        [
            "colab",
            "--auth=oauth2",
            "exec",
            "--session",
            NAME,
            "--file",
            str(WORKER),
            "--timeout",
            "180",
            "--env",
            "A1_PHASE=status",
        ],
        timeout=240,
    )
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if result.returncode != 0 or not lines:
        raise ControllerError("remote status is unavailable")
    payload: dict[str, Any] = json.loads(lines[-1])
    return payload


def check_worker() -> dict[str, Any]:
    """Prove the worker starts, reports status and refuses a missing phase, before allocation.

    The first A1 campaign attempt burned every authorized session because the controller passed
    the phase in the environment while the worker required a positional argument. This check runs
    the exact file locally with no arguments, so an entrypoint defect fails before allocation.
    """
    env = {**os.environ, "PYTHONPATH": f"{ROOT / 'src'}:{ROOT}"}
    result = subprocess.run(
        [sys.executable, str(WORKER)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    if result.returncode != 2 or "phase must be given" not in result.stderr:
        raise DefectError(
            "worker entrypoint self-test failed; refusing to allocate: "
            f"rc={result.returncode} stderr={result.stderr[-400:]!r}"
        )
    status = subprocess.run(
        [sys.executable, str(WORKER), "status"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )
    if status.returncode != 0:
        raise DefectError(f"worker status self-test failed: {status.stderr[-400:]}")
    payload = json.loads(status.stdout.strip().splitlines()[-1])
    return {"arguments_required": True, "status_ok": True, "status": payload}


def harvest(evidence: Path) -> dict[str, Any]:
    """Extract committed arm files from an evidence archive into the local run directory."""
    RUNS.mkdir(parents=True, exist_ok=True)
    restored = 0
    with tarfile.open(evidence) as archive:
        for member in archive.getmembers():
            if not member.isfile() or not member.name.startswith("runs/"):
                continue
            name = Path(member.name).name
            if not name.endswith(".jsonl"):
                continue
            handle = archive.extractfile(member)
            if handle is None:
                continue
            data = handle.read()
            path = RUNS / name
            existing = path.read_bytes() if path.is_file() else b""
            if existing:
                if data.startswith(existing):
                    path.write_bytes(data)
                    restored += int(data != existing)
                elif not existing.startswith(data):
                    raise ControllerError(f"evidence arm {name} diverges from the local chain")
            else:
                path.write_bytes(data)
                restored += 1
    return {
        "arms": len(list(RUNS.glob("*.jsonl"))),
        "restored": restored,
        "lines": sum(
            len([line for line in path.read_bytes().split(b"\n") if line])
            for path in RUNS.glob("*.jsonl")
        ),
    }


def committed_lines() -> int:
    return sum(
        len([line for line in path.read_bytes().split(b"\n") if line])
        for path in RUNS.glob("*.jsonl")
    )


def _require_phase(session: dict[str, Any], phase: str, expected: str, client: ColabCLI) -> None:
    """Fail closed on a phase error, recording it as a deterministic defect."""
    record = session["phases"][-1]
    if record.get("returncode") != 0:
        session["defect"] = f"{phase.upper()}_PHASE_FAILED"
        detail = (record.get("stderr") or record.get("error") or "")[-600:]
        raise DefectError(f"{phase} phase failed: {detail}")
    status = _remote_status(client)
    session[f"{phase}_status"] = status
    if status.get("error"):
        session["defect"] = f"{phase.upper()}_WORKER_ERROR"
        raise DefectError(f"{phase} worker error: {status['error']}")
    observed = status.get("phase", {}).get("phase")
    if observed != expected:
        session["defect"] = f"{phase.upper()}_NOT_COMPLETE"
        raise DefectError(f"{phase} did not reach {expected}: {observed}")


def _require_progress(session: dict[str, Any], before: int, status: dict[str, Any]) -> None:
    """A time-slice interruption must show verified progress; silence is a defect."""
    phase = status.get("phase", {}).get("phase")
    after = int(status.get("committed") or 0)
    session["progress"] = {"before": before, "after": after, "phase": phase}
    if phase == "RUN_COMPLETE":
        return
    if phase != "RUN_PARTIAL":
        session["defect"] = "RUN_PHASE_NOT_RECORDED"
        raise DefectError(f"run phase recorded {phase!r}, not a resumable interruption")
    if after <= before:
        session["defect"] = "RUN_PHASE_NO_PROGRESS"
        raise DefectError(
            f"run phase interrupted without progress ({before} -> {after}); refusing to resume"
        )


def _run_session(
    client: A1Colab,
    directory: Path,
    session_index: int,
    session_budget: float,
    prior_cu: float,
    before: dict[str, Any],
    monitor_errors: list[str],
    observations: list[dict[str, Any]],
    smoke_done: bool,
) -> dict[str, Any]:
    payload, receipt = build_payload(directory)
    if receipt["planned_generations"] != 1332:
        raise DefectError("payload does not carry the full frozen work order")
    session: dict[str, Any] = {
        "index": session_index,
        "payload": receipt,
        "budget_seconds": round(session_budget, 1),
        "phases": [],
        "attempted": False,
        "prior_committed": committed_lines(),
    }
    watchdog = client.start_watchdog(NAME, directory / f"watchdog-{session_index}.json")
    stop_monitor = threading.Event()
    started = time.monotonic()
    breach: list[str] = []

    def monitor() -> None:
        failures = 0
        while not stop_monitor.wait(PROGRESS_POLL_SECONDS):
            try:
                state = client.snapshot()
            except Exception as exc:
                failures += 1
                monitor_errors.append(f"{type(exc).__name__}: {exc}")
                if failures >= 3:
                    breach.append("provider snapshot unavailable")
                    client.stop(NAME)
                    return
                continue
            failures = 0
            observations.append(state)
            projected = prior_cu + model_cost(time.monotonic() - started + CLEANUP_SECONDS)
            if (
                state["usage_rate_cu_per_hour"] > MAX_RATE_CU_PER_HOUR
                or projected > HARD_CAP_CU
                or time.monotonic() - started > session_budget
            ):
                breach.append(f"live envelope breach: projected {projected:.3f} CU")
                monitor_errors.append(breach[-1])
                client.stop(NAME)
                return

    evidence = directory / f"evidence-{session_index}.tar"
    try:
        if not client.watchdog_alive(watchdog):
            raise ControllerError("independent watchdog is unavailable")
        session["attempted"] = True
        if not client.new(NAME) or client.hardware(NAME) != "T4":
            raise ControllerError("exact T4 allocation failed")
        endpoint = client.target_endpoint
        live = client.snapshot()
        if not endpoint or not exact_live(live, NAME, endpoint):
            raise ControllerError("live T4 rate or inventory failed qualification")
        session["target_endpoint"] = endpoint
        session["live"] = live
        threading.Thread(target=monitor, daemon=True).start()

        if not client.upload(NAME, payload, "/content/a1-payload.tar"):
            raise ControllerError("payload upload failed")
        if not client.upload(NAME, WORKER, "/content/a1-worker.py"):
            raise ControllerError("worker upload failed")
        env = {
            "A1_PAYLOAD_SHA256": receipt["payload_sha256"],
            "A1_WORK_ORDER_SHA256": receipt["work_order_sha256"],
        }
        session["phases"].append(
            _invoke(client, "bootstrap", 1500, {**env, "A1_PHASE": "bootstrap"})
        )
        _require_phase(session, "bootstrap", "SETUP_COMPLETE", client)
        if receipt["prior_evidence_arms"] or session["prior_committed"]:
            session["phases"].append(_invoke(client, "resume", 300, {**env, "A1_PHASE": "resume"}))
            session["resume"] = _remote_status(client)
            if session["phases"][-1]["returncode"] != 0:
                session["defect"] = "RESUME_PHASE_FAILED"
                raise DefectError("resume phase failed")
        session["phases"].append(_invoke(client, "download", 1200, {**env, "A1_PHASE": "download"}))
        _require_phase(session, "download", "BASE_COMPLETE", client)
        session["phases"].append(_invoke(client, "verify", 900, {**env, "A1_PHASE": "verify"}))
        _require_phase(session, "verify", "VERIFY_COMPLETE", client)

        setup_elapsed = time.monotonic() - started
        reserved = CLEANUP_SECONDS + FETCH_SECONDS + 240
        generation_budget = session_budget - setup_elapsed - reserved
        if generation_budget < MIN_GENERATION_SECONDS:
            session["defect"] = "INSUFFICIENT_GENERATION_BUDGET"
            raise DefectError("session has no usable generation budget")
        session["generation_budget_seconds"] = int(generation_budget)
        before_lines = int(session["prior_committed"])
        record = _invoke(
            client,
            "campaign",
            int(generation_budget) + 180,
            {**env, "A1_PHASE": "campaign", "A1_SECONDS": str(int(generation_budget))},
        )
        session["phases"].append(record)
        status = _remote_status(client)
        session["campaign_status"] = status
        if record.get("returncode") != 0:
            session["defect"] = "CAMPAIGN_PHASE_FAILED"
            raise DefectError(f"campaign phase failed: {(record.get('stderr') or '')[-600:]}")
        if status.get("error"):
            session["defect"] = "CAMPAIGN_WORKER_ERROR"
            raise DefectError(f"campaign worker error: {status['error']}")
        _require_progress(session, before_lines, status)
        session["phases"].append(_invoke(client, "evidence", 300, {**env, "A1_PHASE": "evidence"}))
        if client.download(NAME, "/content/a1/evidence.tar", evidence):
            session["evidence_sha256"] = digest(evidence)
            session["harvest"] = harvest(evidence)
        else:
            session["defect"] = "EVIDENCE_DOWNLOAD_FAILED"
            raise DefectError("evidence download failed; the committed work is not retained")
        session["cleanup"] = _invoke(client, "cleanup", 180, {**env, "A1_PHASE": "cleanup"})
    except DefectError as exc:
        session["error"] = f"{type(exc).__name__}: {exc}"
    except Exception as exc:
        session["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        stop_monitor.set()
        if breach:
            session["monitor_breach"] = list(breach)
        termination = supervision.terminate_until_absent(
            client,
            NAME,
            supervision.SessionLifecycle(),
            allocation_attempted=session["attempted"],
            rounds=3,
            call_timeout=45,
            backoff=5,
        )
        verified = termination.absent
        client.finish_watchdog(watchdog, verified)
        try:
            after = client.snapshot()
        except Exception as exc:
            after = {"error": f"{type(exc).__name__}: {exc}", "active_assignment_count": 1}
            monitor_errors.append(f"final snapshot: {type(exc).__name__}: {exc}")
        elapsed = time.monotonic() - started
        session.update(
            target_absent=verified,
            termination_attempts=termination.attempts,
            teardown=getattr(client, "teardown_receipt", {}),
            after=after,
            elapsed_seconds=round(elapsed, 1),
        )
        if verified and after.get("active_assignment_count") == 0:
            session["modeled_cu"] = model_cost(elapsed)
        if not verified:
            session["defect"] = "TEARDOWN_UNVERIFIED"
    return session


def campaign(directory: Path, record_name: str) -> dict[str, Any]:
    """Run the frozen campaign in as few T4 sessions as the envelope allows."""
    directory.mkdir(parents=True, exist_ok=True)
    control_path = directory / record_name
    client = A1Colab()
    before = client.snapshot()
    if (
        before["active_assignment_count"] != 0
        or before["usage_rate_cu_per_hour"] != 0
        or before["balance"] < HARD_CAP_CU
        or not client.verify_absent(NAME, allocation_attempted=False)
    ):
        raise ControllerError("provider is not idle, funded or free of the exact target")
    control: dict[str, Any] = {
        "name": NAME,
        "authorization": {
            "issue": "RES-832",
            "accelerator": "T4 only",
            "hard_cap_cu": HARD_CAP_CU,
            "hard_cap_seconds": HARD_CAP_SECONDS,
            "max_sessions": MAX_SESSIONS,
            "max_rate_cu_per_hour": MAX_RATE_CU_PER_HOUR,
            "no_purchase": True,
            "scope": "continuation campaign after the infrastructure failure",
        },
        "attempt_1": ATTEMPT_1,
        "baseline": before,
        "sessions": [],
        "started": time.time(),
        "worker_self_test": check_worker(),
        "prior_committed_generations": committed_lines(),
    }
    monitor_errors: list[str] = []
    observations: list[dict[str, Any]] = []
    total_seconds = 0.0
    cumulative_cu = 0.0
    completed = committed_lines()
    planned = 1332
    try:
        for session_index in range(1, MAX_SESSIONS + 1):
            remaining = HARD_CAP_SECONDS - total_seconds
            if remaining < SETUP_RESERVE_SECONDS + MIN_GENERATION_SECONDS + CLEANUP_SECONDS:
                control["stop_reason"] = "WALL_CLOCK_ENVELOPE"
                break
            budget = min(SESSION_SECONDS, remaining)
            session = _run_session(
                client,
                directory,
                session_index,
                budget,
                cumulative_cu,
                before,
                monitor_errors,
                observations,
                smoke_done=any(
                    (session.get("campaign_status") or {}).get("smoke", {}).get("complete")
                    for session in control["sessions"]
                ),
            )
            control["sessions"].append(session)
            total_seconds += session.get("elapsed_seconds", 0.0)
            cumulative_cu += session.get("modeled_cu", 0.0)
            completed = committed_lines()
            if session.get("defect"):
                control["stop_reason"] = session["defect"]
                control["stop_detail"] = session.get("error")
                break
            if completed >= planned:
                control["stop_reason"] = "COMPLETE"
                break
            if session_index == MAX_SESSIONS:
                control["stop_reason"] = "SESSION_LIMIT"
        else:
            control["stop_reason"] = control.get("stop_reason", "SESSION_LIMIT")
    finally:
        try:
            after = client.snapshot()
        except Exception as exc:
            after = {"error": f"{type(exc).__name__}: {exc}", "active_assignment_count": 1}
            monitor_errors.append(f"post-campaign snapshot: {type(exc).__name__}: {exc}")
        control.update(
            after=after,
            continuation_seconds=round(total_seconds, 1),
            completed_generations=completed,
            planned_generations=planned,
            monitor_errors=monitor_errors,
            live_observations=len(observations),
            target_absent=all(session.get("target_absent") for session in control["sessions"]),
        )
        if after.get("active_assignment_count") == 0:
            control["continuation_modeled_cu"] = round(cumulative_cu, 4)
            control["displayed_balance_delta_cu"] = round(
                float(before["balance"]) - float(after["balance"]), 4
            )
        control["combined"] = {
            "wall_clock_seconds": round(ATTEMPT_1["wall_clock_seconds"] + total_seconds, 1),
            "modeled_cu": round(ATTEMPT_1["modeled_cu"] + cumulative_cu, 4),
            "sessions": ATTEMPT_1["sessions"] + len(control["sessions"]),
            "authorized_cu": HARD_CAP_CU,
            "authorized_seconds": HARD_CAP_SECONDS,
            "authorized_sessions": MAX_SESSIONS,
            "within_continuation_cap": bool(
                cumulative_cu <= HARD_CAP_CU
                and total_seconds <= HARD_CAP_SECONDS
                and len(control["sessions"]) <= MAX_SESSIONS
            ),
        }
        control_path.write_text(json.dumps(control, indent=2, sort_keys=True) + "\n")
    print(json.dumps(control, indent=2, sort_keys=True))
    return control


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preflight", "launch", "status"))
    parser.add_argument("--directory", type=Path, default=WORK)
    parser.add_argument("--record", default="campaign-2-control.json")
    args = parser.parse_args()
    if args.action == "preflight":
        _payload, receipt = build_payload(args.directory)
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return 0
    if args.action == "status":
        print(json.dumps(_remote_status(A1Colab()), indent=2, sort_keys=True))
        return 0
    control = campaign(args.directory, args.record)
    return 0 if control.get("target_absent") else 1


if __name__ == "__main__":
    raise SystemExit(main())
