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
# Continuation attempts that allocated nothing. Each one is a real allocation counted against the
# four-session envelope; recording them keeps the accounting honest.
ATTEMPT_2 = {
    "modeled_cu": 0.0,
    "wall_clock_seconds": 160.0,
    "sessions": 1,
    "generations": 0,
    "outcome": "ALLOCATION_TRANSPORT_TIMEOUT",
    "balance_delta_cu": 0.0,
    "note": (
        "Stopped in the allocation command before any target endpoint was bound or any payload "
        "was uploaded. The provider reported no active session or assignment afterwards and the "
        "balance was unchanged. Repairs: the allocation bound widens to 420 s, and an unsent "
        "allocation is now verified by reserved-name absence instead of an endpoint that never "
        "existed."
    ),
}
# The second continuation attempt allocated four sessions. Every session reached the remote and
# ran the bootstrap phase, but the worker's argparse consumed the IPython kernel's argv
# ('-f .../kernel-<id>.json') as its positional phase and exited 2. The controller saw a zero
# return code, could not parse a status payload, and treated each session as a transport error
# rather than a deterministic defect, so it spent all four.
ATTEMPT_3 = {
    "modeled_cu": 1.0441,
    "wall_clock_seconds": 532.1,
    "sessions": 4,
    "generations": 0,
    "outcome": "KERNEL_ARGV_ENTRYPOINT_DEFECT",
    "balance_delta_cu": 0.0,
    "note": (
        "All four sessions allocated a T4, uploaded the 39 MB payload and executed the bootstrap "
        "phase in the remote kernel. No generation ran. The phase is now resolved from the "
        "environment because that is the only authority under `colab exec --file`, a positional "
        "phase is accepted only when it is an exact known phase, the controller self-test "
        "reproduces the kernel argv, and an unparseable status is now a deterministic defect that "
        "aborts further allocation."
    ),
}
# A session must fit inside the independent watchdog and inside one exec invocation. 5,200 s per
# session across 4 sessions is 20,800 s, inside the authorized 21,300 s (5 h 55 min) cap.
SESSION_SECONDS = 5200
# The watchdog duration is fixed by the successor policy set {3420, 7020, 14220}.
WATCHDOG_SECONDS = 7020
SETUP_RESERVE_SECONDS = 720
CLEANUP_SECONDS = 120
FETCH_SECONDS = 300
MIN_GENERATION_SECONDS = 300
PROGRESS_POLL_SECONDS = 20


class ControllerError(RuntimeError):
    pass


class DefectError(ControllerError):
    """A deterministic defect: further allocation is forbidden until it is repaired."""


class StatusUnavailableError(DefectError):
    """The remote did not return a parsable status payload.

    ``colab exec`` returns 0 even when the executed file raises ``SystemExit(2)``, because the
    kernel swallows it. A zero return code with no status payload therefore means the worker did
    not run the phase at all. That is deterministic evidence, not a transport blip, and it must
    abort the campaign instead of spending the next session on the same defect.
    """


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


class _Timeouts:
    """Reviewed V2 command bounds, with a longer allocation bound for the A1 continuation.

    The first continuation attempt lost a session to a transient 120 s `colab new` timeout: the
    provider was still creating the target when the client gave up. Allocation is the one call
    that must not be abandoned early, so it gets a bound wide enough for a slow provider queue and
    the name-absence check below still proves what happened.
    """

    def __init__(self, module: Any) -> None:
        self._module = module
        self.NEW_TIMEOUT_SECONDS = 420

    def __getattr__(self, name: str) -> Any:
        return getattr(self._module, name)


class A1Colab(ColabCLI):
    watchdog_seconds = WATCHDOG_SECONDS

    def __init__(self) -> None:
        super().__init__()
        self._timeouts = _Timeouts(self._timeouts)


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
    if not lines:
        raise StatusUnavailableError("remote status returned no output; the worker did not run")
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise StatusUnavailableError(f"remote status is not JSON: {lines[-1][:200]!r}") from exc
    if not isinstance(payload, dict) or "committed" not in payload:
        raise StatusUnavailableError(f"remote status payload differs: {str(payload)[:200]}")
    return payload


def check_worker() -> dict[str, Any]:
    """Prove the worker starts under the *real* remote invocation before allocating.

    ``colab exec --file`` never runs the file as a script: it execs the source inside a live
    IPython kernel whose ``sys.argv`` is ``[... '-f', '.../kernel-<id>.json']``. Two authorized
    sessions were lost to exactly that: the worker's argparse consumed the kernel path as its
    positional phase and exited 2 while the phase was actually in the environment. The self-test
    therefore reproduces the kernel argv, not an empty one.
    """
    env = {**os.environ, "PYTHONPATH": f"{ROOT / 'src'}:{ROOT}"}
    env.pop("A1_PHASE", None)
    kernel = (
        "import sys, runpy\n"
        "sys.argv = ['/usr/local/lib/python3.13/dist-packages/ipykernel_launcher.py',\n"
        "            '-f', '/root/.local/share/jupyter/runtime/kernel-selftest.json']\n"
        "runpy.run_path({path!r}, run_name='__main__')\n"
    )
    missing = subprocess.run(
        [sys.executable, "-c", kernel.format(path=str(WORKER))],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )
    if missing.returncode == 0 or "phase must be given" not in missing.stderr:
        raise DefectError(
            "worker refuses to run under the remote kernel invocation; refusing to allocate: "
            f"rc={missing.returncode} stderr={missing.stderr[-400:]!r}"
        )
    status = subprocess.run(
        [sys.executable, "-c", kernel.format(path=str(WORKER))],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        env={**env, "A1_PHASE": "status"},
    )
    if status.returncode != 0:
        raise DefectError(
            f"worker status self-test failed under the kernel: {status.stderr[-600:]}"
        )
    payload = json.loads(status.stdout.strip().splitlines()[-1])
    if "committed" not in payload:
        raise DefectError(f"worker status payload differs: {payload}")
    plain = subprocess.run(
        [sys.executable, str(WORKER), "status"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )
    if plain.returncode != 0:
        raise DefectError(f"worker plain status self-test failed: {plain.stderr[-400:]}")
    return {
        "kernel_argv_refused": True,
        "kernel_status_ok": True,
        "status": payload,
        "positional_status_ok": True,
    }


def harvest(evidence: Path) -> dict[str, Any]:
    """Extract committed arm files and the smoke receipt from an evidence archive."""
    RUNS.mkdir(parents=True, exist_ok=True)
    restored = 0
    with tarfile.open(evidence) as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            name = Path(member.name).name
            if member.name == "smoke-receipt.json":
                handle = archive.extractfile(member)
                if handle is not None:
                    WORK.mkdir(parents=True, exist_ok=True)
                    (WORK / "smoke-receipt.json").write_bytes(handle.read())
                continue
            if not member.name.startswith("runs/"):
                continue
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
        "smoke_receipt": (WORK / "smoke-receipt.json").is_file(),
    }


def committed_lines() -> int:
    return sum(
        len([line for line in path.read_bytes().split(b"\n") if line])
        for path in RUNS.glob("*.jsonl")
    )


def _require_phase(session: dict[str, Any], phase: str, expected: str, client: ColabCLI) -> None:
    """Fail closed on a phase error, recording it as a deterministic defect.

    A zero return code is not evidence that the phase ran: the remote kernel returns 0 even for a
    failed ``SystemExit``. The phase record and the parsed status must both agree, so a worker
    that never executed aborts the campaign instead of consuming the next session.
    """
    record = session["phases"][-1]
    output = f"{record.get('stdout') or ''}\n{record.get('stderr') or ''}"
    if record.get("returncode") != 0:
        session["defect"] = f"{phase.upper()}_PHASE_FAILED"
        detail = (record.get("stderr") or record.get("error") or "")[-600:]
        raise DefectError(f"{phase} phase failed: {detail}")
    if "phase must be given" in output or "Traceback (most recent call last)" in output:
        session["defect"] = f"{phase.upper()}_WORKER_DID_NOT_RUN"
        raise StatusUnavailableError(f"{phase} ran no worker code: {output[-600:]}")
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
    *,
    smoke_done: bool,
) -> dict[str, Any]:
    payload, receipt = build_payload(directory)
    if receipt["planned_generations"] != 1332:
        raise DefectError("payload does not carry the full frozen work order")
    session: dict[str, Any] = {
        "index": session_index,
        "payload": receipt,
        "budget_seconds": round(session_budget, 1),
        "prior_smoke_complete": smoke_done,
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
        try:
            allocated = client.new(NAME)
        except Exception as exc:
            # A transport timeout during allocation does not prove the target was not created.
            # Record it; teardown then establishes name absence rather than endpoint absence.
            allocated = False
            session["allocation_error"] = f"{type(exc).__name__}: {exc}"
        if not allocated:
            raise ControllerError("exact T4 allocation failed or was not confirmed")
        if client.hardware(NAME) != "T4":
            raise ControllerError("exact T4 allocation returned different hardware")
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

        setup_elapsed = time.monotonic() - started
        reserved = CLEANUP_SECONDS + FETCH_SECONDS + 180
        phase_budget = session_budget - setup_elapsed - reserved
        if phase_budget < MIN_GENERATION_SECONDS:
            session["defect"] = "INSUFFICIENT_GENERATION_BUDGET"
            raise DefectError("session has no usable generation budget")
        # One budget covers verify, model load, smoke and the frozen run, so the exec timeout,
        # the phase deadline and the generation deadline cannot disagree.
        session["phase_budget_seconds"] = int(phase_budget)
        smoke_already = session.get("prior_smoke_complete") is True
        campaign_env = {
            **env,
            "A1_PHASE": "campaign",
            "A1_SECONDS": str(int(phase_budget)),
            "A1_SMOKE": "0" if smoke_already else "1",
        }
        record = _invoke(client, "campaign", int(phase_budget) + 180, campaign_env)
        session["phases"].append(record)
        before_lines = int(session["prior_committed"])
        output = f"{record.get('stdout') or ''}\n{record.get('stderr') or ''}"
        if record.get("returncode") != 0:
            session["defect"] = "CAMPAIGN_PHASE_FAILED"
            raise DefectError(f"campaign phase failed: {(record.get('stderr') or '')[-600:]}")
        if "phase must be given" in output or "Traceback (most recent call last)" in output:
            session["defect"] = "CAMPAIGN_WORKER_DID_NOT_RUN"
            raise StatusUnavailableError(f"campaign ran no worker code: {output[-600:]}")
        status = _remote_status(client)
        session["campaign_status"] = status
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
        # When allocation never bound an endpoint, exact-endpoint absence is unprovable by
        # construction. The reserved session name is the correct target: prove it absent in both
        # authenticated inventories.
        bound = bool(session.get("target_endpoint"))
        if not bound:
            client.teardown_receipt = {}
        termination = supervision.terminate_until_absent(
            client,
            NAME,
            supervision.SessionLifecycle(),
            allocation_attempted=bound,
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
        "attempt_2": ATTEMPT_2,
        "attempt_3": ATTEMPT_3,
        "baseline": before,
        "sessions": [],
        "started": time.time(),
        "worker_self_test": check_worker(),
        "prior_committed_generations": committed_lines(),
    }
    monitor_errors: list[str] = []
    observations: list[dict[str, Any]] = []
    prior_seconds = float(ATTEMPT_2["wall_clock_seconds"] + ATTEMPT_3["wall_clock_seconds"])
    prior_cu = float(ATTEMPT_2["modeled_cu"] + ATTEMPT_3["modeled_cu"])
    prior_sessions = int(ATTEMPT_2["sessions"] + ATTEMPT_3["sessions"])
    total_seconds = 0.0
    cumulative_cu = 0.0
    completed = committed_lines()
    smoke_complete = False
    planned = 1332
    try:
        for session_index in range(1, MAX_SESSIONS + 1):
            remaining = HARD_CAP_SECONDS - prior_seconds - total_seconds
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
                smoke_done=smoke_complete,
            )
            control["sessions"].append(session)
            total_seconds += session.get("elapsed_seconds", 0.0)
            cumulative_cu += session.get("modeled_cu", 0.0)
            completed = committed_lines()
            campaign_status = session.get("campaign_status") or {}
            if (campaign_status.get("smoke") or {}).get("present"):
                smoke_complete = bool((campaign_status.get("smoke") or {}).get("complete"))
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
        continuation_modeled = round(prior_cu + cumulative_cu, 4)
        continuation_seconds = round(prior_seconds + total_seconds, 1)
        continuation_sessions = prior_sessions + len(control["sessions"])
        control["continuation"] = {
            "wall_clock_seconds": continuation_seconds,
            "modeled_cu": continuation_modeled,
            "sessions": continuation_sessions,
            "attempts": [
                {key: row[key] for key in ("modeled_cu", "wall_clock_seconds", "sessions")}
                for row in (ATTEMPT_2, ATTEMPT_3)
            ]
            + [
                {
                    "modeled_cu": round(cumulative_cu, 4),
                    "wall_clock_seconds": round(total_seconds, 1),
                    "sessions": len(control["sessions"]),
                }
            ],
            "within_cap": bool(
                continuation_modeled <= HARD_CAP_CU
                and continuation_seconds <= HARD_CAP_SECONDS
                and continuation_sessions <= MAX_SESSIONS
            ),
        }
        control["combined"] = {
            "wall_clock_seconds": round(ATTEMPT_1["wall_clock_seconds"] + continuation_seconds, 1),
            "modeled_cu": round(ATTEMPT_1["modeled_cu"] + continuation_modeled, 4),
            "sessions": ATTEMPT_1["sessions"] + continuation_sessions,
            "generations": completed,
            "authorized_cu": HARD_CAP_CU,
            "authorized_seconds": HARD_CAP_SECONDS,
            "authorized_sessions": MAX_SESSIONS,
            "within_continuation_cap": control["continuation"]["within_cap"],
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
