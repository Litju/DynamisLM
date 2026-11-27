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
# One exec slice. The watchdog fires before the provider's own session limit so the teardown
# path always runs inside the session that spent the compute.
SLICE_SECONDS = 2700
WATCHDOG_SECONDS = 3480
CLEANUP_SECONDS = 60
FETCH_SECONDS = 240


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
    """Assemble the upload: clean HEAD source archive, frozen manifest, verified adapter bundle."""
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
    payload = directory / "a1-payload.tar"
    if payload.exists():
        payload.unlink()
    with tarfile.open(payload, "x") as archive:
        for path in (source, sealed, bundle):
            archive.add(path, arcname=path.name)
    receipt = {
        "source_commit": head,
        "source_tar_sha256": digest(source),
        "call_manifest_sha256": digest(sealed),
        "bundle_tar_sha256": digest(bundle),
        "payload_sha256": digest(payload),
        "planned_generations": manifest["planned_generations"],
        "planned_conditions": manifest["planned_conditions"],
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
    directory.mkdir(parents=True, exist_ok=True)
    control_path = directory / "control.json"
    payload, receipt = build_payload(directory)
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
        "payload": receipt,
        "baseline": before,
        "sessions": [],
        "phases": [],
        "started": time.time(),
    }
    watchdog = client.start_watchdog(NAME, directory / "watchdog.json")
    stop_monitor = threading.Event()
    monitor_errors: list[str] = []
    observations: list[dict[str, Any]] = []
    spent = 0.0
    elapsed_total = 0.0
    attempted = False

    def monitor() -> None:
        while not stop_monitor.wait(20):
            try:
                state = client.snapshot()
                observations.append(state)
                projected = spent + model_cost(before, state, elapsed_total + CLEANUP_SECONDS)
                if (
                    state["usage_rate_cu_per_hour"] > MAX_RATE_CU_PER_HOUR
                    or state["active_assignment_count"] > MAX_SESSIONS
                    or projected > HARD_CAP_CU
                ):
                    monitor_errors.append(f"live envelope breach: projected {projected:.3f} CU")
                    client.stop(NAME)
                    return
            except Exception as exc:
                monitor_errors.append(f"{type(exc).__name__}: {exc}")
                return

    thread: threading.Thread | None = None
    try:
        if not client.watchdog_alive(watchdog):
            raise ControllerError("independent watchdog is unavailable")
        attempted = True
        if not client.new(NAME) or client.hardware(NAME) != "T4":
            raise ControllerError("exact T4 allocation failed")
        endpoint = client.target_endpoint
        live = client.snapshot()
        if not endpoint or not exact_live(live, NAME, endpoint):
            raise ControllerError("live T4 rate or inventory failed qualification")
        control["target_endpoint"] = endpoint
        control["live"] = live
        thread = threading.Thread(target=monitor, daemon=True)
        thread.start()

        if not client.upload(NAME, payload, "/content/a1-payload.tar"):
            raise ControllerError("payload upload failed")
        if not client.upload(NAME, WORKER, "/content/a1-worker.py"):
            raise ControllerError("worker upload failed")
        env = {
            "A1_PAYLOAD_SHA256": receipt["payload_sha256"],
            "A1_MANIFEST_SHA256": receipt["call_manifest_sha256"],
        }
        for phase, timeout in (("bootstrap", 900), ("download", 700)):
            record = _invoke(client, phase, timeout, {**env, "A1_PHASE": phase})
            control["phases"].append(record)
            if record["returncode"] != 0:
                raise ControllerError(f"{phase} phase failed")
            status = _remote_status(client)
            expected = "SETUP_COMPLETE" if phase == "bootstrap" else "BASE_COMPLETE"
            if status.get("phase", {}).get("phase") != expected:
                raise ControllerError(f"{phase} did not reach {expected}: {status}")

        session_started = time.monotonic()
        generation_seconds = 0.0
        for slice_index in range(1, 13):
            remaining_wall = HARD_CAP_SECONDS - elapsed_total
            if remaining_wall < 300:
                control["stop_reason"] = "WALL_CLOCK_ENVELOPE"
                break
            budget = int(min(SLICE_SECONDS, remaining_wall - CLEANUP_SECONDS))
            record = _invoke(
                client,
                "run",
                budget + 240,
                {**env, "A1_PHASE": "run", "A1_SECONDS": str(budget)},
            )
            record["slice"] = slice_index
            record["budget_seconds"] = budget
            control["phases"].append(record)
            generation_seconds += record["seconds"]
            if record["returncode"] not in (0, None):
                control["stop_reason"] = f"RUN_SLICE_EXIT_{record['returncode']}"
                break
            status = _remote_status(client)
            control["progress"] = status
            arms = status.get("arms", {})
            committed = sum(arms.values())
            if status.get("error"):
                control["stop_reason"] = "WORKER_ERROR"
                control["worker_error"] = status["error"]
                break
            if committed >= receipt["planned_generations"]:
                control["stop_reason"] = "COMPLETE"
                break
        elapsed_total = time.monotonic() - session_started
        control["generation_seconds"] = round(generation_seconds, 1)
        if "stop_reason" not in control:
            control["stop_reason"] = "SLICE_LIMIT"

        evidence = directory / "evidence.tar"
        if not client.download(NAME, "/content/a1/evidence.tar", evidence):
            control["evidence_error"] = "download failed"
        else:
            control["evidence_sha256"] = digest(evidence)
            with tarfile.open(evidence) as archive:
                names = set(archive.getnames())
            control["evidence_members"] = len(names)
            runs = {name for name in names if name.startswith("runs/")}
            control["evidence_arms"] = len(runs)
        control["cleanup"] = _invoke(client, "cleanup", 120, {**env, "A1_PHASE": "cleanup"})
    except Exception as exc:
        control["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        stop_monitor.set()
        termination = supervision.terminate_until_absent(
            client,
            NAME,
            supervision.SessionLifecycle(),
            allocation_attempted=attempted,
            rounds=3,
            call_timeout=45,
            backoff=5,
        )
        verified = termination.absent
        client.finish_watchdog(watchdog, verified)
        after = client.snapshot()
        elapsed_total = max(elapsed_total, time.monotonic() - control.get("started", time.time()))
        control.update(
            target_absent=verified,
            termination_attempts=termination.attempts,
            teardown=getattr(client, "teardown_receipt", {}),
            after=after,
            elapsed_seconds=round(elapsed_total, 1),
            live_observations=len(observations),
            monitor_errors=monitor_errors,
        )
        if verified and after["active_assignment_count"] == 0:
            control["modeled_cu"] = model_cost(before, after, elapsed_total)
            control["displayed_balance_delta_cu"] = round(
                float(before["balance"]) - float(after["balance"]), 4
            )
        control["within_cap"] = bool(
            control.get("modeled_cu", HARD_CAP_CU) <= HARD_CAP_CU
            and elapsed_total <= HARD_CAP_SECONDS
        )
        control_path.write_text(json.dumps(control, indent=2, sort_keys=True) + "\n")
    print(json.dumps(control, indent=2, sort_keys=True))
    return control


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
