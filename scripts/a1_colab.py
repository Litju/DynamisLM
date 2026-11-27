"""Allocate one qualified T4, run the frozen A1 campaign, retain evidence, tear down (RES-832).

Owner authorization recorded in RES-832, restated here as the code's hard limits:

* accelerators: one qualified Tesla T4 only, never a different one;
* cumulative GPU wall clock: at most 6 hours across all sessions;
* cumulative spend: at most 12 existing compute units;
* sessions: at most 4, counting retries;
* no purchases, subscriptions or paid upgrades.

The controller allocates nothing until it has verified an idle authenticated account, a positive
balance, an unused exact target and a live T4 quote inside the authorized rate. It stops the
session and verifies exact-target absence on every path, including exceptions.

Resumption is a property of the frozen work order, not of the controller: the worker appends to
per-arm hash-chained files, so a second session continues exactly where the first stopped and
never regenerates a committed call.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
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
WORKER = ROOT / "scripts/a1_colab_worker.py"
NAME = "dynamislm-res832-a1"
HARD_CAP_CU = 12.0
HARD_CAP_SECONDS = 6 * 3600
MAX_SESSIONS = 4
MAX_RATE_CU_PER_HOUR = 1.65
RESERVE_CU = 0.20
# Approved watchdog durations are fixed by the successor policy; 7020 s is the shortest that can
# hold more than one 1800 s generation slice plus setup, evidence fetch and teardown.
WATCHDOG_SECONDS = 7020
SLICE_SECONDS = 1800
SESSION_GENERATION_SECONDS = 3 * SLICE_SECONDS
CLEANUP_SECONDS = 120
FETCH_SECONDS = 300
SETUP_SECONDS = 1500


class ControllerError(RuntimeError):
    pass


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def model_cost(before: dict[str, Any], after: dict[str, Any], elapsed: float) -> float:
    rate_time = elapsed * MAX_RATE_CU_PER_HOUR / 3600
    balance_delta = max(0.0, float(before["balance"]) - float(after["balance"])) + 0.01
    return math.ceil((max(rate_time, balance_delta) + RESERVE_CU) * 10000) / 10000


def exact_live(snapshot: dict[str, Any], name: str, endpoint: str) -> bool:
    return bool(
        0 < snapshot["usage_rate_cu_per_hour"] <= MAX_RATE_CU_PER_HOUR
        and snapshot["active_assignment_count"] == 1
        and snapshot["active_sessions"] == [{"name": name, "endpoint": endpoint, "hardware": "T4"}]
    )


class A1Colab(ColabCLI):
    watchdog_seconds = WATCHDOG_SECONDS


def build_payload(directory: Path) -> tuple[Path, dict[str, Any]]:
    """Assemble the upload: clean HEAD source archive, frozen manifest, verified adapter bundle.

    Previously committed arm files are included so a new Colab session resumes instead of
    regenerating. Each session starts with a fresh filesystem, so continuation is carried by the
    payload and harvested back from the evidence archive.
    """
    from scripts import a1_manifest, alpha_adapter_bundle

    if subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, text=True
    ):
        raise ControllerError("A1 requires the exact clean committed source")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    manifest = a1_manifest.load_manifest()
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / "source.tar"
    subprocess.run(
        ["git", "archive", "--format=tar", f"--output={source}", head], cwd=ROOT, check=True
    )
    sealed = directory / "call-manifest.json"
    shutil.copyfile(a1_manifest.SEAL_PATH, sealed)
    bundle_src = Path(
        "/home/litju/.local/share/dynamislm-evidence/RES-772-adapter-bundle/first.tar"
    )
    if not bundle_src.is_file():
        raise ControllerError("verified adapter bundle is unavailable")
    bundle = directory / "bundle.tar"
    shutil.copyfile(bundle_src, bundle)
    alpha_adapter_bundle.verified_payload(bundle)
    prior = sorted((ROOT / "experiments/a1/.runs").glob("*.jsonl"))
    payload = directory / "a1-payload.tar"
    if payload.exists():
        payload.unlink()
    with tarfile.open(payload, "x") as archive:
        for path in (source, sealed, bundle):
            archive.add(path, arcname=path.name)
        for path in prior:
            archive.add(path, arcname=f"runs/{path.name}")
    receipt = {
        "source_commit": head,
        "source_tar_sha256": digest(source),
        "call_manifest_sha256": digest(sealed),
        "bundle_tar_sha256": digest(bundle),
        "payload_sha256": digest(payload),
        "planned_generations": manifest["planned_generations"],
        "planned_conditions": manifest["planned_conditions"],
        "prior_evidence_arms": len(prior),
        "prior_evidence_lines": sum(
            len([line for line in path.read_bytes().split(b"\n") if line]) for path in prior
        ),
    }
    (directory / "payload-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    )
    return payload, receipt


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
        str(timeout + 60),
    ]
    for key, value in env.items():
        command += ["--env", f"{key}={value}"]
    started = time.monotonic()
    try:
        result = client._run(command, timeout=timeout + 120)
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
            "120",
            "--env",
            "A1_PHASE=status",
        ],
        timeout=180,
    )
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if result.returncode != 0 or not lines:
        raise ControllerError("remote status is unavailable")
    payload: dict[str, Any] = json.loads(lines[-1])
    return payload


def campaign(directory: Path) -> dict[str, Any]:
    """Run the frozen campaign in as few T4 sessions as the envelope allows.

    Each session is self-contained: allocate, upload, set up, download, run, package evidence,
    harvest, stop. A session that runs out of wall clock or slice budget before the frozen
    workload completes is followed by another session that resumes from the harvested evidence.
    Sessions are capped at MAX_SESSIONS and at HARD_CAP_SECONDS in aggregate.
    """
    directory.mkdir(parents=True, exist_ok=True)
    control_path = directory / "control.json"
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
        },
        "baseline": before,
        "sessions": [],
        "started": time.time(),
    }
    monitor_errors: list[str] = []
    observations: list[dict[str, Any]] = []
    total_seconds = 0.0
    cumulative_cu = 0.0
    completed = 0
    try:
        for session_index in range(1, MAX_SESSIONS + 1):
            remaining = HARD_CAP_SECONDS - total_seconds
            if remaining < SETUP_SECONDS + SLICE_SECONDS + CLEANUP_SECONDS + FETCH_SECONDS:
                control["stop_reason"] = "WALL_CLOCK_ENVELOPE"
                break
            session = _run_session(
                client,
                directory,
                session_index,
                remaining,
                cumulative_cu,
                before,
                monitor_errors,
                observations,
            )
            control["sessions"].append(session)
            total_seconds += session.get("elapsed_seconds", 0.0)
            cumulative_cu += session.get("modeled_cu", 0.0)
            harvest_info = session.get("harvest") or {}
            completed = harvest_info.get("lines", completed)
            planned = session.get("proof", {}).get("planned_generations")
            if planned is not None and completed >= planned:
                control["stop_reason"] = "COMPLETE"
                break
            if session.get("aborted"):
                control["stop_reason"] = session["aborted"]
                break
            if session_index == MAX_SESSIONS:
                control["stop_reason"] = "SESSION_LIMIT"
        else:
            control["stop_reason"] = control.get("stop_reason", "SESSION_LIMIT")
    finally:
        after = client.snapshot()
        control.update(
            after=after,
            elapsed_seconds=round(total_seconds, 1),
            completed_generations=completed,
            monitor_errors=monitor_errors,
            live_observations=len(observations),
        )
        if after["active_assignment_count"] == 0:
            control["modeled_cu"] = round(cumulative_cu, 4)
            control["displayed_balance_delta_cu"] = round(
                float(before["balance"]) - float(after["balance"]), 4
            )
        control["within_cap"] = bool(
            control.get("modeled_cu", HARD_CAP_CU) <= HARD_CAP_CU
            and total_seconds <= HARD_CAP_SECONDS
            and len(control["sessions"]) <= MAX_SESSIONS
        )
        control_path.write_text(json.dumps(control, indent=2, sort_keys=True) + "\n")
    print(json.dumps(control, indent=2, sort_keys=True))
    return control


def harvest(evidence: Path) -> dict[str, Any]:
    """Extract committed arm files from an evidence archive into the local run directory."""
    target = ROOT / "experiments/a1/.runs"
    target.mkdir(parents=True, exist_ok=True)
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
            path = target / name
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
        "arms": len(list(target.glob("*.jsonl"))),
        "restored": restored,
        "lines": sum(
            len([line for line in path.read_bytes().split(b"\n") if line])
            for path in target.glob("*.jsonl")
        ),
    }


def _run_session(
    client: A1Colab,
    directory: Path,
    session_index: int,
    remaining: float,
    prior_cu: float,
    before: dict[str, Any],
    monitor_errors: list[str],
    observations: list[dict[str, Any]],
) -> dict[str, Any]:
    payload, receipt = build_payload(directory)
    session: dict[str, Any] = {
        "index": session_index,
        "payload": receipt,
        "phases": [],
        "attempted": False,
        "proof": {"planned_generations": receipt["planned_generations"]},
    }
    watchdog = client.start_watchdog(NAME, directory / f"watchdog-{session_index}.json")
    stop_monitor = threading.Event()
    started = time.monotonic()

    def monitor() -> None:
        while not stop_monitor.wait(20):
            try:
                state = client.snapshot()
                observations.append(state)
                projected = prior_cu + model_cost(
                    before, state, time.monotonic() - started + CLEANUP_SECONDS
                )
                if (
                    state["usage_rate_cu_per_hour"] > MAX_RATE_CU_PER_HOUR
                    or projected > HARD_CAP_CU
                    or time.monotonic() - started > remaining
                ):
                    monitor_errors.append(f"live envelope breach: projected {projected:.3f} CU")
                    client.stop(NAME)
                    return
            except Exception as exc:
                monitor_errors.append(f"{type(exc).__name__}: {exc}")
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
            "A1_MANIFEST_SHA256": receipt["call_manifest_sha256"],
        }
        session["phases"].append(
            _invoke(client, "bootstrap", 1200, {**env, "A1_PHASE": "bootstrap"})
        )
        if session["phases"][-1]["returncode"] != 0:
            raise ControllerError("bootstrap phase failed")
        if _remote_status(client).get("phase", {}).get("phase") != "SETUP_COMPLETE":
            raise ControllerError("bootstrap did not reach SETUP_COMPLETE")
        if receipt["prior_evidence_arms"]:
            session["phases"].append(_invoke(client, "resume", 240, {**env, "A1_PHASE": "resume"}))
            resumed = _remote_status(client)
            session["resume"] = resumed
            if session["phases"][-1]["returncode"] != 0:
                raise ControllerError("resume phase failed")
        session["phases"].append(_invoke(client, "download", 900, {**env, "A1_PHASE": "download"}))
        if session["phases"][-1]["returncode"] != 0:
            raise ControllerError("base download phase failed")
        if _remote_status(client).get("phase", {}).get("phase") != "BASE_COMPLETE":
            raise ControllerError("download did not reach BASE_COMPLETE")

        setup_elapsed = time.monotonic() - started
        generation_budget = remaining - setup_elapsed - CLEANUP_SECONDS - FETCH_SECONDS
        generation_budget = min(generation_budget, SESSION_GENERATION_SECONDS)
        if generation_budget < 300:
            session["aborted"] = "INSUFFICIENT_GENERATION_BUDGET"
        else:
            record = _invoke(
                client,
                "run",
                int(generation_budget) + 300,
                {**env, "A1_PHASE": "run", "A1_SECONDS": str(int(generation_budget))},
            )
            session["phases"].append(record)
            session["generation_budget_seconds"] = int(generation_budget)
            session["proof"]["worker"] = _remote_status(client)
        session["phases"].append(_invoke(client, "evidence", 300, {**env, "A1_PHASE": "evidence"}))
        if client.download(NAME, "/content/a1/evidence.tar", evidence):
            session["evidence_sha256"] = digest(evidence)
            session["harvest"] = harvest(evidence)
        else:
            session["evidence_error"] = "download failed"
        session["cleanup"] = _invoke(client, "cleanup", 180, {**env, "A1_PHASE": "cleanup"})
    except Exception as exc:
        session["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        stop_monitor.set()
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
        after = client.snapshot()
        elapsed = time.monotonic() - started
        session.update(
            target_absent=verified,
            termination_attempts=termination.attempts,
            teardown=getattr(client, "teardown_receipt", {}),
            after=after,
            elapsed_seconds=round(elapsed, 1),
            probe_window_hours=round(elapsed / 3600, 4),
        )
        if verified and after["active_assignment_count"] == 0:
            session["modeled_cu"] = model_cost(before, after, elapsed)
        if not verified:
            session["aborted"] = "TEARDOWN_UNVERIFIED"
    return session


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preflight", "launch", "status"))
    parser.add_argument("--directory", type=Path, default=WORK)
    args = parser.parse_args()
    if args.action == "preflight":
        _payload, receipt = build_payload(args.directory)
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return 0
    if args.action == "status":
        print(json.dumps(_remote_status(A1Colab()), indent=2, sort_keys=True))
        return 0
    control = campaign(args.directory)
    return 0 if control.get("target_absent") else 1


if __name__ == "__main__":
    raise SystemExit(main())
