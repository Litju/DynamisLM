"""Owner-gated WSL control plane for the single RES-541 Colab T4 run."""

from __future__ import annotations

import argparse
import datetime as datetime_module
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import IO

ROOT = Path(__file__).resolve().parents[1]
E_MOUNT = Path("/mnt/e")
A0_STORAGE_ROOT = E_MOUNT / "DynamisLM-A0"
DEFAULT_REPORT_DIR = A0_STORAGE_ROOT / "reports"
BRANCH = "julitocrztuga/res-541-a0-wslcolab-gpu-scientific-reasoning-alpha-development-only"
REPOSITORY = "Litju/DynamisLM"
REPORT_SCHEMA = "RES541_A0_REPORT_V1"
APPROVED_CASE_COUNT = 16
MAX_TOTAL_RUNTIME_SECONDS = 900
MAX_NEW_TOKENS = 64
MAX_WEIGHT_BYTES = 8 * 1024**3
REMOTE_TIMEOUT_SECONDS = 900
REPORT_DOWNLOAD_TIMEOUT_SECONDS = 120
SESSION_STOP_TIMEOUT_SECONDS = 30
SESSION_LIST_TIMEOUT_SECONDS = 30


class RunError(RuntimeError):
    pass


def _within(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
        return True
    except ValueError:
        return False


def _prepare_host_storage(output_dir: Path) -> Path:
    try:
        if not E_MOUNT.is_mount() or E_MOUNT.resolve(strict=True) != E_MOUNT:
            raise RunError("Windows E: must be mounted at /mnt/e before A0 can run")
        if A0_STORAGE_ROOT.parent != E_MOUNT or A0_STORAGE_ROOT.resolve() != A0_STORAGE_ROOT:
            raise RunError("A0 storage path does not resolve to /mnt/e/DynamisLM-A0")

        report_root = A0_STORAGE_ROOT / "reports"
        resolved_report_root = report_root.resolve()
        resolved_output_dir = output_dir.resolve()
        if not _within(resolved_report_root, A0_STORAGE_ROOT) or not _within(
            resolved_output_dir, resolved_report_root
        ):
            raise RunError(f"A0 reports must resolve below {report_root}")

        environment = {
            "UV_CACHE_DIR": A0_STORAGE_ROOT / "cache" / "uv",
            "PIP_CACHE_DIR": A0_STORAGE_ROOT / "cache" / "pip",
            "XDG_CACHE_HOME": A0_STORAGE_ROOT / "cache" / "xdg",
            "HF_HOME": A0_STORAGE_ROOT / "cache" / "huggingface",
            "TORCH_HOME": A0_STORAGE_ROOT / "cache" / "torch",
            "PYTHONPYCACHEPREFIX": A0_STORAGE_ROOT / "cache" / "pycache",
            "TMPDIR": A0_STORAGE_ROOT / "tmp",
        }
        directories = [
            resolved_output_dir,
            *(path for path in environment.values()),
            A0_STORAGE_ROOT / "downloads",
        ]
        for path in directories:
            resolved_path = path.resolve()
            if not _within(resolved_path, A0_STORAGE_ROOT):
                raise RunError(f"A0 storage path resolves outside {A0_STORAGE_ROOT}: {path}")

        for path in directories:
            path.mkdir(parents=True, exist_ok=True)
        for path in directories:
            if not _within(path.resolve(), A0_STORAGE_ROOT):
                raise RunError(f"A0 storage path changed outside {A0_STORAGE_ROOT}: {path}")
    except RunError:
        raise
    except (OSError, RuntimeError) as exc:
        raise RunError(f"Windows E: storage is unavailable at {A0_STORAGE_ROOT}: {exc}") from exc

    os.environ.update({name: str(path) for name, path in environment.items()})
    return resolved_output_dir


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        raise RunError("Git could not verify the exact source revision")
    return completed.stdout.strip()


def _stream(command: list[str]) -> tuple[int, str]:
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    lines: list[str] = []
    _forward_lines(process.stdout, lines)
    return process.wait(), "".join(lines)


def _forward_lines(stream: IO[str], lines: list[str]) -> None:
    for line in stream:
        sys.stdout.write(line)
        sys.stdout.flush()
        lines.append(line)


def _usage() -> tuple[str, str]:
    command = ["colab", "--auth=oauth2", "usage"]
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise RunError("quota and OAuth checks must run in an interactive WSL terminal")
    print("Interactive OAuth2 quota check:")
    visible = subprocess.run(command, cwd=ROOT, check=False)
    if visible.returncode != 0:
        raise RunError("Colab usage could not be read; no session was started")
    code, output = _stream(command)
    if code != 0:
        raise RunError("Colab quota verification failed after the interactive check")
    return _parse_usage_output(output), output


def _parse_usage_output(output: str) -> str:
    balance = re.search(r"Current balance:\s*([0-9]+(?:\.[0-9]+)?)\s+compute units", output)
    active = re.search(r"Active assignments:\s*(\d+)", output)
    if balance is None or active is None:
        raise RunError("Colab usage output did not include a readable quota and active count")
    if float(balance.group(1)) <= 0:
        raise RunError("Colab has no positive compute-unit balance; no session was started")
    if int(active.group(1)) != 0:
        raise RunError("Colab reports an active assignment; this mission requires a clean session")
    return balance.group(1)


def _confirmation_phrase(balance: str) -> str:
    return f"RUN RES-541 A0 | quota={balance} CU | max=900s | cases=16 | tokens=64 | gpu=T4"


def _is_mission_branch(branch: str, upstream: str) -> bool:
    return branch == BRANCH or upstream == f"origin/{BRANCH}"


def _check_clean_pushed_revision() -> str:
    branch = _git("branch", "--show-current")
    upstream = _git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    if not _is_mission_branch(branch, upstream):
        raise RunError("the WSL checkout is not on the RES-541 mission branch")
    if _git("status", "--porcelain"):
        raise RunError("commit the complete A0 source before requesting remote execution")
    revision = _git("rev-parse", "HEAD")
    if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise RunError("the A0 source revision is not a full Git SHA")
    remote = _git("ls-remote", "origin", f"refs/heads/{BRANCH}").split()
    if not remote or remote[0] != revision:
        raise RunError("push the exact clean A0 revision before remote execution")
    return revision


def _case_count() -> int:
    document = json.loads((ROOT / "experiments" / "a0" / "cases.json").read_text(encoding="utf-8"))
    cases = document.get("cases") if isinstance(document, dict) else None
    if not isinstance(cases, list):
        raise RunError("the A0 synthetic case manifest is invalid")
    return len(cases)


def _write_control_failure(
    target: Path,
    *,
    revision: str,
    run_id: str,
    category: str,
    control: dict[str, object],
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "schema": REPORT_SCHEMA,
        "status": "NO_GO",
        "scope": "SYNTHETIC_DEVELOPMENT_ONLY",
        "source_revision": revision,
        "run_id": run_id,
        "failure_stage": "LOCAL_COLAB_CONTROL_PLANE",
        "failure_category": category,
        "control_plane": control,
        "manual_action": (
            f"Run `colab --auth=oauth2 stop --session {run_id}`, then run "
            "`colab --auth=oauth2 sessions` and confirm the session is absent."
            if not control.get("session_absent_after_stop")
            else "Session absence was verified by the local control plane."
        ),
        "cases": [],
    }
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run(output_dir: Path) -> int:
    output_dir = _prepare_host_storage(output_dir)
    revision = _check_clean_pushed_revision()
    count = _case_count()
    if count != APPROVED_CASE_COUNT:
        raise RunError(
            f"quota approval covers {APPROVED_CASE_COUNT} cases; source currently has {count}"
        )
    balance, _usage_output = _usage()
    cli_version = subprocess.run(
        ["colab", "version"],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    if cli_version.returncode != 0:
        raise RunError("Colab CLI version could not be read; no session was started")
    print(
        "Approved run bound: one T4 session; max 15 minutes; 16 synthetic cases; "
        "64 generated tokens per case; pinned model weights capped at 8 GiB; no retry "
        "or tier fallback."
    )
    expected = _confirmation_phrase(balance)
    if input(f"Type exactly `{expected}` to authorize this quota-checked run: ") != expected:
        raise RunError("owner quota confirmation did not match; no session was started")

    timestamp = datetime_module.datetime.now(datetime_module.UTC).strftime("%Y%m%d-%H%M%SZ")
    run_id = f"res541-a0-{timestamp.lower()}"
    remote_report = f"/content/{run_id}-report.json"
    local_report = output_dir / f"{run_id}-report.json"
    failure_receipt = output_dir / f"{run_id}-control-failure.json"
    run_command = [
        "colab",
        "--auth=oauth2",
        "run",
        "--gpu",
        "T4",
        "--session",
        run_id,
        "--keep",
        "--timeout",
        str(REMOTE_TIMEOUT_SECONDS),
        str(ROOT / "scripts" / "a0_colab_entry.py"),
        "--source-revision",
        revision,
        "--run-id",
        run_id,
        "--report-path",
        remote_report,
    ]
    control: dict[str, object] = {
        "colab_cli_version": cli_version.stdout.strip(),
        "quota_checked": True,
        "active_assignments_before": 0,
        "available_compute_units_confirmed_by_owner": True,
        "session_name": run_id,
        "gpu_requested": "T4",
        "case_count": count,
        "max_total_runtime_seconds": MAX_TOTAL_RUNTIME_SECONDS,
        "max_new_tokens_per_case": MAX_NEW_TOKENS,
        "max_model_weight_bytes": MAX_WEIGHT_BYTES,
        "retry_or_tier_fallback": False,
    }

    run_exit_code = 1
    download_exit_code: int | None = None
    stop_exit_code: int | None = None
    sessions_exit_code = 127
    sessions_output = ""
    runner_error: Exception | None = None
    try:
        print(f"Starting one Colab T4 run for source revision {revision}.")
        try:
            run_exit_code = subprocess.run(run_command, cwd=ROOT, check=False).returncode
        except Exception as exc:
            runner_error = exc
    finally:
        try:
            try:
                download_exit_code = subprocess.run(
                    [
                        "colab",
                        "--auth=oauth2",
                        "download",
                        "--session",
                        run_id,
                        remote_report,
                        str(local_report),
                    ],
                    cwd=ROOT,
                    check=False,
                    timeout=REPORT_DOWNLOAD_TIMEOUT_SECONDS,
                ).returncode
            except Exception as exc:
                download_exit_code = 124 if isinstance(exc, subprocess.TimeoutExpired) else 127
                control["artifact_download_error"] = (
                    "TIMEOUT" if isinstance(exc, subprocess.TimeoutExpired) else type(exc).__name__
                )
        finally:
            try:
                stop_exit_code = subprocess.run(
                    ["colab", "--auth=oauth2", "stop", "--session", run_id],
                    cwd=ROOT,
                    check=False,
                    timeout=SESSION_STOP_TIMEOUT_SECONDS,
                ).returncode
            except Exception as exc:
                stop_exit_code = 124 if isinstance(exc, subprocess.TimeoutExpired) else 127
                control["session_stop_error"] = (
                    "TIMEOUT" if isinstance(exc, subprocess.TimeoutExpired) else type(exc).__name__
                )
            finally:
                try:
                    completed = subprocess.run(
                        ["colab", "--auth=oauth2", "sessions"],
                        cwd=ROOT,
                        capture_output=True,
                        check=False,
                        text=True,
                        timeout=SESSION_LIST_TIMEOUT_SECONDS,
                    )
                    sessions_output = completed.stdout + completed.stderr
                    sessions_exit_code = completed.returncode
                except Exception as exc:
                    sessions_exit_code = 124 if isinstance(exc, subprocess.TimeoutExpired) else 127
                    control["sessions_check_error"] = (
                        "TIMEOUT"
                        if isinstance(exc, subprocess.TimeoutExpired)
                        else type(exc).__name__
                    )
                finally:
                    control["runner_exit_code"] = run_exit_code
                    control["artifact_download_exit_code"] = download_exit_code
                    control["session_stop_exit_code"] = stop_exit_code
                    control["sessions_check_exit_code"] = sessions_exit_code
                    control["session_absent_after_stop"] = (
                        stop_exit_code == 0
                        and sessions_exit_code == 0
                        and run_id not in sessions_output
                    )

    if not control["session_absent_after_stop"]:
        _write_control_failure(
            failure_receipt,
            revision=revision,
            run_id=run_id,
            category="SESSION_TEARDOWN_FAILED",
            control=control,
        )
        raise RunError(
            f"Colab session teardown could not be verified for {run_id} "
            f"(stop exit={stop_exit_code}, sessions check exit={sessions_exit_code}); "
            f"failure receipt: {failure_receipt}; stop it with "
            f"colab --auth=oauth2 stop --session {run_id}, then verify with "
            "colab --auth=oauth2 sessions"
        )
    if runner_error is not None:
        _write_control_failure(
            failure_receipt,
            revision=revision,
            run_id=run_id,
            category="COLAB_RUNNER_LAUNCH_FAILED",
            control=control,
        )
        raise RunError(
            f"Colab runner failed; control receipt: {failure_receipt}; report path: {local_report}"
        ) from runner_error

    if download_exit_code != 0 or not local_report.exists():
        _write_control_failure(
            failure_receipt,
            revision=revision,
            run_id=run_id,
            category="REMOTE_ARTIFACT_UNAVAILABLE",
            control=control,
        )
        raise RunError(
            f"Colab artifact retrieval failed; control receipt saved at {failure_receipt}"
        )

    try:
        if local_report.stat().st_size > 2 * 1024**2:
            raise RunError("retrieved A0 report exceeds the 2 MiB size bound")
        report = json.loads(local_report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, RunError) as exc:
        _write_control_failure(
            failure_receipt,
            revision=revision,
            run_id=run_id,
            category="REMOTE_ARTIFACT_INVALID",
            control=control,
        )
        raise RunError(
            f"retrieved A0 report is invalid; control receipt: {failure_receipt}"
        ) from exc
    if (
        not isinstance(report, dict)
        or report.get("schema") != REPORT_SCHEMA
        or report.get("source_revision") != revision
    ):
        _write_control_failure(
            failure_receipt,
            revision=revision,
            run_id=run_id,
            category="REMOTE_ARTIFACT_INVALID",
            control=control,
        )
        raise RunError(f"retrieved A0 report failed validation; control receipt: {failure_receipt}")
    report["run_id"] = run_id
    report["control_plane"] = control
    local_report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Retrieved report: {local_report} ({local_report.stat().st_size} bytes)")
    if report.get("status") not in ("PASS", "PASS_WITH_LIMITATIONS", "NO_GO"):
        _write_control_failure(
            failure_receipt,
            revision=revision,
            run_id=run_id,
            category="REMOTE_ARTIFACT_INVALID",
            control=control,
        )
        raise RunError(
            f"retrieved A0 report has an unknown status; control receipt: {failure_receipt}"
        )
    if run_exit_code != 0 or report.get("status") == "NO_GO":
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", choices=("run",))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_REPORT_DIR)
    args = parser.parse_args()
    try:
        return run(args.output_dir)
    except RunError as exc:
        print(f"RES-541 A0 stopped before allocation: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
