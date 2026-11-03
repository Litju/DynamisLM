"""E:-only WSL control plane for one explicitly owner-approved A0.2 Colab session."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts import a02_experiment

ROOT = Path(__file__).resolve().parents[1]
E_ROOT = Path("/mnt/e/DynamisLM-A0")
REPORT_DIR = E_ROOT / "a02"
ATTEMPT_MARKER = REPORT_DIR / "one-attempt-used.json"
MAX_SESSION_SECONDS = 900
NEW_TIMEOUT_SECONDS = 120
UPLOAD_TIMEOUT_SECONDS = 120
DOWNLOAD_TIMEOUT_SECONDS = 120
STOP_TIMEOUT_SECONDS = 30
VERIFY_TIMEOUT_SECONDS = 30
REMOTE_REPORT = "/content/a02-report.json"


class RunError(RuntimeError):
    pass


def clean_colab_env() -> dict[str, str]:
    env = {
        key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME"}
    }
    cache = E_ROOT / "cache"
    temp = E_ROOT / "tmp"
    env.update(
        TMPDIR=str(temp),
        TEMP=str(temp),
        TMP=str(temp),
        UV_CACHE_DIR=str(cache / "uv"),
        PIP_CACHE_DIR=str(cache / "pip"),
        XDG_CACHE_HOME=str(cache / "xdg"),
        HF_HOME=str(cache / "huggingface"),
        TORCH_HOME=str(cache / "torch"),
        RUFF_CACHE_DIR=str(cache / "ruff"),
        MYPY_CACHE_DIR=str(cache / "mypy"),
        PYTHONDONTWRITEBYTECODE="1",
    )
    return env


def _run(
    command: list[str], *, timeout: int, capture: bool = True
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=ROOT,
            env=clean_colab_env(),
            timeout=timeout,
            check=False,
            text=True,
            capture_output=capture,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RunError(
            f"Colab command failed or timed out: {command[2] if len(command) > 2 else command[0]}"
        ) from exc


def _parse_balance(text: str) -> float:
    match = re.search(
        r"Current balance:\s*([0-9]+(?:\.[0-9]+)?)\s*compute units", text, re.IGNORECASE
    )
    if not match:
        raise RunError("Colab usage output did not contain a compute-unit balance")
    return float(match.group(1))


def _zero_sessions(text: str) -> bool:
    plain = re.sub(r"\x1b\[[0-9;]*m", "", text).strip()
    return (
        re.fullmatch(
            r"(?:\[colab\] Pruned [1-9][0-9]* stale local session\(s\)\.\r?\n)?"
            r"\[colab\] No active sessions found on server\.",
            plain,
        )
        is not None
    )


def _check_e_mount() -> str:
    try:
        source = subprocess.check_output(
            ["findmnt", "-n", "-o", "SOURCE", "--target", "/mnt/e"], text=True, timeout=10
        ).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise RunError("cannot verify Windows E: mount") from exc
    if source != "E:\\" or not Path("/mnt/e").is_mount():
        raise RunError("persistent host storage must be mounted Windows E: at /mnt/e")
    return source


def _prepare_e_directories() -> None:
    for path in (
        E_ROOT / "tmp",
        E_ROOT / "cache/uv",
        E_ROOT / "cache/pip",
        E_ROOT / "cache/xdg",
        E_ROOT / "cache/huggingface",
        E_ROOT / "cache/torch",
        E_ROOT / "cache/ruff",
        E_ROOT / "cache/mypy",
    ):
        path.mkdir(parents=True, exist_ok=True)


def _check_tracked_model_weights() -> None:
    result = subprocess.run(
        ["find", str(E_ROOT / "cache"), "-type", "f", "-size", "+100M", "-print"],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    if result.returncode != 0:
        raise RunError("host model-weight cache inspection failed")
    if result.stdout.strip():
        raise RunError("host model cache contains a file over 100 MiB; weights must remain remote")


def preflight() -> dict[str, Any]:
    if ATTEMPT_MARKER.exists():
        raise RunError("the single A0.2 GPU allocation attempt has already been used")
    _check_e_mount()
    _prepare_e_directories()
    _check_tracked_model_weights()
    if not Path("/mnt/e/DynamisLM-A0/a01/tokenizer/tokenizer.json").is_file():
        raise RunError("pinned CPU tokenizer assets are missing from E:")
    branch = subprocess.check_output(
        ["git", "branch", "--show-current"], cwd=ROOT, text=True
    ).strip()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True).strip()
    status = subprocess.check_output(["git", "status", "--porcelain=v1"], cwd=ROOT, text=True)
    if status:
        raise RunError("A0.2 source must be committed and clean before any Colab allocation")
    base = subprocess.check_output(
        ["git", "merge-base", "HEAD", "b8510aef00d1e3208562ceefea083c0fa57901fa"],
        cwd=ROOT,
        text=True,
    ).strip()
    if base != "b8510aef00d1e3208562ceefea083c0fa57901fa":
        raise RunError("A0.2 branch is not based on the verified current main")
    cli_version = _run(["colab", "version"], timeout=15)
    if cli_version.returncode or "0.7.5" not in cli_version.stdout:
        raise RunError("the reviewed official google-colab-cli 0.7.5 is required")
    usage = _run(["colab", "--auth=oauth2", "usage"], timeout=30)
    sessions = _run(["colab", "--auth=oauth2", "sessions"], timeout=30)
    if usage.returncode != 0 or sessions.returncode != 0 or not _zero_sessions(sessions.stdout):
        raise RunError("Colab authentication, quota, or zero-session preflight failed")
    balance = _parse_balance(usage.stdout)
    if balance <= 0:
        raise RunError("Colab reports no existing compute-unit balance")
    return {
        "schema": "RES541_A02_COLAB_PREFLIGHT_V1",
        "utc": datetime.now(UTC).isoformat(),
        "branch": branch,
        "source_revision": head,
        "source_tree": tree,
        "base_head": base,
        "git_clean": True,
        "colab_cli": cli_version.stdout.strip(),
        "authentication": "OAUTH2_ACCOUNT_SESSION_VERIFIED",
        "usage_output": usage.stdout.strip(),
        "compute_unit_balance": balance,
        "session_list": sessions.stdout.strip(),
        "active_session_count": 0,
        "requested_gpu": "T4",
        "gpu_availability": "NOT_PROBED_NO_ALLOCATION",
        "e_mount_source": "E:\\",
        "host_model_weights": "NOT_PRESENT_IN_CHECKED_CACHE",
        "limits": {
            "session_total_seconds": MAX_SESSION_SECONDS,
            "exec_seconds_max": 720,
            "download_seconds": DOWNLOAD_TIMEOUT_SECONDS,
            "stop_seconds": STOP_TIMEOUT_SECONDS,
            "verification_seconds": VERIFY_TIMEOUT_SECONDS,
            "one_attempt": True,
            "automatic_paid_upgrade": False,
            "training": False,
        },
    }


def _binding(
    run_id: str,
    source_archive: Path,
    preflight_doc: dict[str, Any],
    preflight_path: Path,
) -> dict[str, Any]:
    protocol = a02_experiment.PROTOCOL_PATH.read_bytes()
    archive_hash = hashlib.sha256(source_archive.read_bytes()).hexdigest()
    return {
        "schema": "RES541_A02_RUN_BINDING_V1",
        "run_id": run_id,
        "source_revision": preflight_doc["source_revision"],
        "source_tree": preflight_doc["source_tree"],
        "source_archive_sha256": archive_hash,
        "protocol_sha256": hashlib.sha256(protocol).hexdigest(),
        "preflight_sha256": hashlib.sha256(preflight_path.read_bytes()).hexdigest(),
        "remote_report": REMOTE_REPORT,
    }


def _confirmation(doc: dict[str, Any], binding: dict[str, Any]) -> str:
    protocol = json.loads(a02_experiment.PROTOCOL_PATH.read_text())
    cases_sha = protocol["new_a02_cases"]["case_manifest_sha256"]
    prompt_sha = protocol["new_a02_cases"]["action_prompt_sha256"]
    final_sha = protocol["new_a02_cases"]["final_prompt_sha256"]
    profile_id = protocol["runtime"]["runtime_profile_id"]
    profile_sha = protocol["runtime"]["runtime_profile_sha256"]
    return (
        "AUTHORIZE ONE RES-541 A0.2 T4 RUN"
        f" | source={doc['source_revision']}"
        f" | protocol={binding['protocol_sha256']}"
        f" | cases={cases_sha}"
        f" | action-prompt={prompt_sha}"
        f" | final-prompt={final_sha}"
        f" | model={protocol['model']['model_id']}@{protocol['model']['model_revision']}"
        f" | runtime={profile_id}:{profile_sha}"
        " | suites=16-paired+10-new"
        f" | current-balance={doc['compute_unit_balance']:.2f} CU"
        " | existing balance only"
        " | dtype=fp16, weights<=8GiB, VRAM>=12GiB"
        " | session<=900s, exec<=720s, download<=120s, stop<=30s, verify<=30s"
        " | tokens=history 1024/64, A02 action 1024/128, final 1024/64"
        " | no retry"
        " | no upgrade"
        " | inference only"
    )


def _archive_source(path: Path) -> None:
    with path.open("wb") as stream:
        subprocess.run(
            ["git", "archive", "--format=tar", "HEAD"], cwd=ROOT, check=True, stdout=stream
        )
    if path.stat().st_size > 64 * 1024**2:
        raise RunError("A0.2 source bundle exceeds the small source-upload bound")


def run() -> int:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise RunError("Colab allocation requires the owner at an interactive WSL terminal")
    doc = preflight()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    run_id = f"res541-a02-{datetime.now(UTC):%Y%m%d-%H%M%S%f}"
    preflight_path = REPORT_DIR / f"{run_id}-preflight.json"
    preflight_path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    source_archive = REPORT_DIR / f"{run_id}-source.tar"
    binding_path = REPORT_DIR / f"{run_id}-binding.json"
    _archive_source(source_archive)
    binding = _binding(run_id, source_archive, doc, preflight_path)
    binding_path.write_text(json.dumps(binding, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    approval = _confirmation(doc, binding)
    print(
        "This requests one T4 session from the current Colab balance and stops after "
        "this 16+10-case inference."
    )
    print(f"Evidence staging directory: {REPORT_DIR}")
    print(f"Type exactly: {approval}")
    if input("> ") != approval:
        raise RunError("interactive owner confirmation did not match; no Colab session was started")

    # Re-read quota and sessions after confirmation; a prior approval cannot outlive this state.
    fresh = preflight()
    if fresh["source_revision"] != doc["source_revision"] or fresh["compute_unit_balance"] <= 0:
        raise RunError("source or Colab quota changed after confirmation")
    if fresh["compute_unit_balance"] != doc["compute_unit_balance"]:
        raise RunError("Colab balance changed after confirmation; obtain a fresh owner decision")

    remote_artifact = REPORT_DIR / f"{run_id}-remote.json"
    control_path = REPORT_DIR / f"{run_id}-control.json"
    state: dict[str, Any] = {
        "schema": "RES541_A02_CONTROL_RECEIPT_V1",
        "preflight": doc,
        "preflight_path": str(preflight_path),
        "binding": binding,
        "session": run_id,
        "owner_confirmation": True,
        "owner_confirmation_text": approval,
        "allocation_requested_utc": datetime.now(UTC).isoformat(),
        "new_exit_code": None,
        "allocation_attempted": False,
        "upload_source_exit_code": None,
        "upload_binding_exit_code": None,
        "exec_exit_code": None,
        "download_exit_code": None,
        "stop_exit_code": None,
        "session_absent_after_stop": False,
    }
    started = time.monotonic()
    deadline = started + MAX_SESSION_SECONDS

    def call(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        remaining = int(deadline - time.monotonic())
        if remaining <= 0:
            raise subprocess.TimeoutExpired(command, timeout)
        return _run(command, timeout=min(timeout, remaining))

    allocation_attempted = False
    created = False
    try:
        attempt_record = {
            "schema": "RES541_A02_ONE_ATTEMPT_USED_V1",
            "run_id": run_id,
            "source_revision": doc["source_revision"],
            "binding_sha256": hashlib.sha256(
                json.dumps(binding, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "owner_confirmation_sha256": hashlib.sha256(approval.encode()).hexdigest(),
            "recorded_utc": datetime.now(UTC).isoformat(),
        }
        with ATTEMPT_MARKER.open("x", encoding="utf-8") as marker:
            marker.write(json.dumps(attempt_record, indent=2, sort_keys=True) + "\n")
        state["allocation_attempted"] = True
        state["one_attempt_marker"] = str(ATTEMPT_MARKER)
        state["one_attempt_marker_sha256"] = hashlib.sha256(ATTEMPT_MARKER.read_bytes()).hexdigest()
        allocation_attempted = True
        new = call(
            ["colab", "--auth=oauth2", "new", "--session", run_id, "--gpu", "T4"],
            NEW_TIMEOUT_SECONDS,
        )
        state["new_exit_code"] = new.returncode
        state["new_output"] = new.stdout.strip()
        state["allocation_returned_utc"] = datetime.now(UTC).isoformat()
        if new.returncode != 0:
            raise RunError("single requested T4 allocation failed; no GPU fallback or retry")
        created = True
        state["upload_source_exit_code"] = call(
            [
                "colab",
                "--auth=oauth2",
                "upload",
                "--session",
                run_id,
                str(source_archive),
                "/content/a02-source.tar",
            ],
            UPLOAD_TIMEOUT_SECONDS,
        ).returncode
        if state["upload_source_exit_code"] != 0:
            raise RunError("A0.2 source archive upload failed")
        state["upload_binding_exit_code"] = call(
            [
                "colab",
                "--auth=oauth2",
                "upload",
                "--session",
                run_id,
                str(binding_path),
                "/content/a02-binding.json",
            ],
            UPLOAD_TIMEOUT_SECONDS,
        ).returncode
        if state["upload_binding_exit_code"] != 0:
            raise RunError("A0.2 run-binding upload failed")
        exec_timeout = min(720, max(1, int(deadline - time.monotonic()) - 180))
        execute = call(
            [
                "colab",
                "--auth=oauth2",
                "exec",
                "--session",
                run_id,
                "--file",
                str(ROOT / "scripts/a02_remote.py"),
                "--timeout",
                str(exec_timeout),
            ],
            exec_timeout + 30,
        )
        state["exec_exit_code"] = execute.returncode
        state["exec_tail"] = execute.stdout[-4000:]
        state["exec_stderr_tail"] = execute.stderr[-2000:]
    except Exception as exc:
        state["control_error"] = type(exc).__name__
        state["control_error_message"] = str(exc)[:2000]
    finally:
        if allocation_attempted:
            if created:
                try:
                    downloaded = call(
                        [
                            "colab",
                            "--auth=oauth2",
                            "download",
                            "--session",
                            run_id,
                            REMOTE_REPORT,
                            str(remote_artifact),
                        ],
                        DOWNLOAD_TIMEOUT_SECONDS,
                    )
                    state["download_exit_code"] = downloaded.returncode
                    if downloaded.returncode != 0:
                        state["download_stderr_tail"] = downloaded.stderr[-2000:]
                except Exception as exc:
                    state["download_error"] = type(exc).__name__
            try:
                # A failed create can still leave a server-side assignment; always attempt stop.
                stopped = _run(
                    ["colab", "--auth=oauth2", "stop", "--session", run_id],
                    timeout=STOP_TIMEOUT_SECONDS,
                )
                state["stop_exit_code"] = stopped.returncode
                state["stop_returned_utc"] = datetime.now(UTC).isoformat()
            except Exception as exc:
                state["stop_error"] = type(exc).__name__
            try:
                sessions = _run(
                    ["colab", "--auth=oauth2", "sessions"], timeout=VERIFY_TIMEOUT_SECONDS
                )
                state["session_absent_after_stop"] = sessions.returncode == 0 and _zero_sessions(
                    sessions.stdout
                )
                state["session_list_after_stop"] = sessions.stdout.strip()
            except Exception as exc:
                state["sessions_error"] = type(exc).__name__
            try:
                usage_after = _run(
                    ["colab", "--auth=oauth2", "usage"], timeout=VERIFY_TIMEOUT_SECONDS
                )
                state["usage_after_exit_code"] = usage_after.returncode
                state["usage_after_output"] = usage_after.stdout.strip()
                if usage_after.returncode == 0:
                    state["compute_unit_balance_after"] = _parse_balance(usage_after.stdout)
                    state["compute_unit_balance_delta"] = (
                        state["preflight"]["compute_unit_balance"]
                        - state["compute_unit_balance_after"]
                    )
            except Exception as exc:
                state["usage_after_error"] = type(exc).__name__
        state["elapsed_seconds"] = time.monotonic() - started
        state["finished_utc"] = datetime.now(UTC).isoformat()
        control_path.write_text(
            json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    if not allocation_attempted:
        raise RunError(f"Colab allocation was not attempted; control receipt: {control_path}")
    if not state["session_absent_after_stop"]:
        raise RunError(
            f"Colab teardown was not verified; preserve receipt {control_path} and stop {run_id}"
        )
    if not remote_artifact.is_file() or state.get("download_exit_code") != 0:
        raise RunError(f"remote report was not recovered; control receipt: {control_path}")
    if remote_artifact.stat().st_size > 8 * 1024**2:
        raise RunError("remote A0.2 report exceeds the 8 MiB artifact bound")
    if state.get("exec_exit_code") != 0:
        raise RunError(f"Colab inference did not complete; partial report: {remote_artifact}")
    tokenizer_site = E_ROOT / "a01/tokenizer-venv/lib/python3.12/site-packages"
    score_env = clean_colab_env()
    score_env.update(
        PYTHONPATH=f"{tokenizer_site}:{ROOT / 'src'}:{ROOT}",
        USE_TORCH="0",
        USE_TF="0",
        USE_FLAX="0",
        TRANSFORMERS_OFFLINE="1",
        HF_HUB_OFFLINE="1",
        HF_HOME=str(E_ROOT / "cache/huggingface"),
    )
    score = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.a02_score",
            "--remote",
            str(remote_artifact),
            "--control",
            str(control_path),
            "--preflight",
            str(REPORT_DIR / "preflight-v1.json"),
            "--output-dir",
            str(REPORT_DIR),
        ],
        cwd=ROOT,
        env=score_env,
        timeout=180,
        text=True,
        capture_output=True,
        check=False,
    )
    verified_path = REPORT_DIR / "verified.json"
    markdown_path = REPORT_DIR / "scientific-report.md"
    if score.returncode not in {0, 1} or not verified_path.is_file() or not markdown_path.is_file():
        raise RunError(
            "WSL CPU replay/scoring failed; see remote report and control receipt: "
            f"{score.stderr[-2000:]}"
        )
    verified = json.loads(verified_path.read_text())
    if verified.get("schema") != "RES541_A02_VERIFIED_REPORT_V1":
        raise RunError("WSL CPU replay did not produce the expected scientific report")
    artifact_paths = (
        preflight_path,
        source_archive,
        binding_path,
        ATTEMPT_MARKER,
        REPORT_DIR / "preflight-v1.json",
        remote_artifact,
        control_path,
        verified_path,
        markdown_path,
    )
    manifest = {
        "schema": "RES541_A02_ARTIFACT_HASHES_V1",
        "run_id": run_id,
        "files": {
            path.name: {
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in artifact_paths
        },
    }
    manifest_path = REPORT_DIR / f"{run_id}-artifact-hashes.json"
    manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    manifest_path.write_text(manifest_bytes, encoding="utf-8")
    print(
        json.dumps(
            {
                "terminal_outcome": verified["terminal_outcome"],
                "evidence_package": str(REPORT_DIR),
                "report": str(markdown_path),
                "artifact_hash_manifest": str(manifest_path),
                "artifact_hash_manifest_sha256": hashlib.sha256(
                    manifest_bytes.encode()
                ).hexdigest(),
            },
            indent=2,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "run"))
    args = parser.parse_args()
    if args.command == "preflight":
        print(json.dumps(preflight(), indent=2, sort_keys=True))
        return 0
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
