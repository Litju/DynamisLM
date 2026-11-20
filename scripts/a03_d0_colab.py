"""Launch one source-bound D0 Colab session after exact owner approval."""

from __future__ import annotations

import argparse
import math
import subprocess
import tarfile
import threading
import time
from pathlib import Path
from typing import Any

from scripts import a02_execution as base
from scripts import a02_v3_contract as v3
from scripts import a02_v3_supervision as supervision
from scripts import a03_d0_runtime as runtime
from scripts.a02_v3_execution import ColabCLI

WATCHDOG_SECONDS = 3420
FETCH_SECONDS = 60
PREFIX = "APPROVE RES-745 D0 "
ROOT = v3.ROOT


def approved(directory: Path, statement: str) -> tuple[dict[str, Any], str]:
    path = directory / "proposal.json"
    digest = runtime.digest(path)
    if statement != PREFIX + digest:
        raise ValueError("D0 requires explicit owner approval of the exact proposal digest")
    proposal = v3.json_object(path.read_text())
    for command, expected in (
        (["rev-parse", "HEAD"], proposal["source"]["commit"]),
        (["rev-parse", "HEAD^{tree}"], proposal["source"]["tree"]),
    ):
        if subprocess.check_output(["git", *command], cwd=ROOT, text=True).strip() != expected:
            raise ValueError("D0 launch checkout differs from approved source")
    if subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT):
        raise ValueError("D0 launch checkout has tracked changes")
    for name, bound in (
        ("source.tar", proposal["source"]["archive_sha256"]),
        ("sample.json", proposal["sample_sha256"]),
    ):
        if runtime.digest(directory / name) != bound:
            raise ValueError(f"D0 launch artifact differs: {name}")
    runtime.verify_files(directory / "adapter", runtime.ADAPTER_FILES)
    if (
        proposal["schema"] != "DYNAMISLM_A03_D0_T4_PROPOSAL_V1"
        or proposal["budget"] != budget()
        or proposal["session"] != f"dynamislm-res745-d0-{proposal['sample_sha256'][:12]}"
    ):
        raise ValueError("D0 approved spending or exact target differs from launcher")
    return proposal, digest


def budget() -> dict[str, Any]:
    return {
        "hardware": "one T4",
        "allocations": 1,
        "seconds": runtime.MAX_SESSION_SECONDS,
        "watchdog_seconds": WATCHDOG_SECONDS,
        "cleanup_seconds": runtime.CLEANUP_SECONDS,
        "fetch_seconds": FETCH_SECONDS,
        "planning_seconds_per_call": runtime.CALL_SECONDS,
        "maximum_observed_cu_per_hour": runtime.MAX_RATE,
        "reserve_cu": runtime.RESERVE_CU,
        "modeled_limit_cu": runtime.CAP_CU,
    }


def model_cost(before: dict[str, Any], after: dict[str, Any], elapsed: float) -> float:
    rate_time = elapsed * runtime.MAX_RATE / 3600
    balance_delta = max(0.0, float(before["balance"]) - float(after["balance"])) + 0.01
    return math.ceil((max(rate_time, balance_delta) + runtime.RESERVE_CU) * 10000) / 10000


def exact_live(snapshot: dict[str, Any], name: str, endpoint: str) -> bool:
    return bool(
        0 < snapshot["usage_rate_cu_per_hour"] <= runtime.MAX_RATE
        and snapshot["active_assignment_count"] == 1
        and snapshot["active_sessions"] == [{"name": name, "endpoint": endpoint, "hardware": "T4"}]
    )


class D0Colab(ColabCLI):
    watchdog_seconds = WATCHDOG_SECONDS


def launch(directory: Path, statement: str) -> None:
    proposal, digest = approved(directory, statement)
    name = proposal["session"]
    client = D0Colab()
    before = client.snapshot()
    if (
        before["active_assignment_count"] != 0
        or before["usage_rate_cu_per_hour"] != 0
        or before["balance"] < runtime.CAP_CU
        or not client.verify_absent(name, allocation_attempted=False)
    ):
        raise ValueError("D0 requires an idle authenticated account and an unused exact target")
    runtime.write(
        directory / "authority-consumed.json",
        {
            "owner_statement": statement,
            "proposal_sha256": digest,
            "provider_baseline": before,
        },
    )
    bundle = directory / "input.tar"
    with tarfile.open(bundle, "x") as archive:
        for filename in (
            "source.tar",
            "proposal.json",
            "sample.json",
            *(f"adapter/{name}" for name in runtime.ADAPTER_FILES),
        ):
            archive.add(directory / filename, arcname=filename)
    watchdog = client.start_watchdog(name, directory / "watchdog.json")
    started = time.monotonic()
    work_cutoff = started + WATCHDOG_SECONDS - runtime.CLEANUP_SECONDS
    stop_monitor = threading.Event()
    lifecycle = supervision.SessionLifecycle()
    observations: list[dict[str, Any]] = []
    attempted = False
    returned = False
    verified = False
    endpoint = None
    launch_error = None

    def monitor() -> None:
        while not stop_monitor.wait(5):
            try:
                state = client.snapshot()
                observations.append(state)
                if (
                    not exact_live(state, name, str(endpoint))
                    or model_cost(
                        before, state, time.monotonic() - started + runtime.CLEANUP_SECONDS
                    )
                    > runtime.CAP_CU
                ):
                    raise ValueError("D0 provider telemetry breached its bounds")
            except Exception as exc:
                lifecycle.fail(str(exc))
                return

    def invoke(command: list[str], timeout: int, label: str) -> Any:
        return supervision.run_cancellable(
            lambda: client._run(["colab", "--auth=oauth2", *command], timeout=timeout),
            lifecycle,
            label,
            supervisor_ok=lambda: client.watchdog_alive(watchdog),
        )

    try:
        if not client.watchdog_alive(watchdog):
            raise ValueError("D0 watchdog is unavailable")
        attempted = True
        if not client.new(name) or "T4" != client.hardware(name):
            raise ValueError("D0 exact T4 allocation failed")
        endpoint = client.target_endpoint
        base._write_json(directory / "control.json", {"target_endpoint": endpoint})
        live = client.snapshot()
        observations.append(live)
        if not endpoint or not exact_live(live, name, endpoint):
            raise ValueError("D0 live T4 price or inventory failed qualification")
        lifecycle.transition(supervision.Phase.RUNNING, "exact T4 and live rate verified")
        threading.Thread(target=monitor, daemon=True).start()
        command_result = invoke(
            ["upload", "--session", name, str(bundle), "/content/d0-input.tar"], 45, "upload"
        )
        if command_result.returncode != 0:
            raise ValueError("D0 upload failed")
        seconds = math.floor(work_cutoff - time.monotonic())
        if seconds <= 84 * runtime.CALL_SECONDS:
            raise TimeoutError("D0 cannot admit 84 calls before the teardown reserve")
        command_result = invoke(
            [
                "exec",
                "--session",
                name,
                "--timeout",
                str(seconds + 15),
                "--env",
                f"D0_SECONDS={seconds}",
                "--env",
                f"D0_PROPOSAL={digest}",
                "--file",
                str(ROOT / "scripts/a03_d0_colab_bootstrap.py"),
            ],
            seconds + 20,
            "generation",
        )
        returned = command_result.returncode == 0
        (directory / "remote.log").write_text(command_result.stdout + command_result.stderr)
        if lifecycle.cancelled.is_set():
            raise ValueError("D0 telemetry interrupted the session")
        out = directory / "output.tar"
        downloaded = invoke(
            ["download", "--session", name, "/content/d0-output.tar", str(out)],
            FETCH_SECONDS,
            "evidence download",
        )
        if downloaded.returncode != 0:
            raise ValueError("D0 evidence download failed")
    except Exception as exc:
        launch_error = f"{type(exc).__name__}: {exc}"
    finally:
        stop_monitor.set()
        termination = supervision.terminate_until_absent(
            client,
            name,
            lifecycle,
            allocation_attempted=attempted,
            rounds=3,
            call_timeout=45,
            backoff=5,
        )
        verified = termination.absent
        control: dict[str, Any] = {
            "target_endpoint": client.target_endpoint,
            "session": name,
            "proposal_sha256": digest,
            "target_absent": verified,
            "termination_attempts": termination.attempts,
            "teardown_receipt": getattr(client, "teardown_receipt", {}),
            "live_observations": observations,
            "lifecycle": lifecycle.history,
            "telemetry_failures": lifecycle.failures,
            "remote_returned": returned,
            "error": launch_error,
        }
        try:
            client.finish_watchdog(watchdog, verified)
            after = client.snapshot()
            elapsed = time.monotonic() - started
            control.update(after=after, elapsed_seconds=elapsed)
            if (
                verified
                and after["active_assignment_count"] == 0
                and after["usage_rate_cu_per_hour"] == 0
            ):
                control["modeled_cu"] = model_cost(before, after, elapsed)
        finally:
            base._write_json(directory / "control.json", control)
    out = directory / "output.tar"
    if out.exists():
        with tarfile.open(out) as archive:
            for member in archive:
                if (
                    not member.isfile()
                    or Path(member.name).name != member.name
                    or not (
                        member.name in {"runtime.json", "terminal.json", "checkpoint.jsonl"}
                        or (member.name.startswith("divergence-") and member.name.endswith(".json"))
                    )
                    or (directory / member.name).exists()
                ):
                    raise ValueError("D0 evidence archive contains an unexpected member")
                archive.extract(member, directory, filter="data")
        if (directory / "checkpoint.jsonl").exists():
            runtime.score_directory(directory, digest)
    if (
        not verified
        or not returned
        or launch_error
        or control.get("modeled_cu", math.inf) > runtime.CAP_CU
        or control.get("elapsed_seconds", math.inf) > runtime.MAX_SESSION_SECONDS
        or not (directory / "scores.json").exists()
        or not v3.json_object((directory / "scores.json").read_text())["complete"]
    ):
        raise RuntimeError("D0 did not complete within its evidence and provider bounds")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--owner-statement", required=True)
    args = parser.parse_args()
    launch(args.directory, args.owner_statement)


if __name__ == "__main__":
    main()
