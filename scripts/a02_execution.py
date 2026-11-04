"""E:-only WSL control plane for one explicitly owner-approved A0.2 Colab session."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import select
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts import a02_experiment

ROOT = Path(__file__).resolve().parents[1]
E_ROOT = Path("/mnt/e/DynamisLM-A0")
REPORT_DIR = E_ROOT / "a02"
ATTEMPT_MARKER = REPORT_DIR / "one-attempt-used.json"
REPLACEMENT_MARKER = REPORT_DIR / "attempt-002-used.json"
RECOVERY_INVENTORY = REPORT_DIR / "recovery-inventory-20261104.json"
RECOVERY_INVENTORY_SHA256 = "034bd0fc97906e87dd8c62d6a52a2ce28fabf60ce34357b68489d665238c549f"
MAX_SESSION_SECONDS = 900
MAX_EXEC_SECONDS = 720
NEW_TIMEOUT_SECONDS = 120
UPLOAD_TIMEOUT_SECONDS = 120
DOWNLOAD_TIMEOUT_SECONDS = 120
DRIVE_RECEIPT_TIMEOUT_SECONDS = 30
STOP_TIMEOUT_SECONDS = 30
VERIFY_TIMEOUT_SECONDS = 30
REMOTE_REPORT = "/content/a02-report.json"
REMOTE_DRIVE_RECEIPT = "/content/a02-drive-receipt.json"
DRIVE_OWNER_RECORD = REPORT_DIR / "drive-owner-identity.json"
DRIVE_FOLDER_ID = "1mibCkKr0cuWPuSKt_OaYiZcI_GkJ-WG6"
DRIVE_FOLDER_URL = f"https://drive.google.com/drive/folders/{DRIVE_FOLDER_ID}"


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


@contextmanager
def _cleanup_signals(original_sigterm: Any) -> Iterator[None]:
    previous_sigint = signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        yield
    finally:
        try:
            signal.signal(signal.SIGINT, previous_sigint)
        finally:
            signal.signal(signal.SIGTERM, original_sigterm)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _watchdog(run_id: str, receipt: Path) -> None:
    # EOF means the controller died; a deadline also bounds a stuck controller.
    print("READY", flush=True)
    ready, _, _ = select.select([sys.stdin], [], [], MAX_SESSION_SECONDS)
    if ready and sys.stdin.read(1) == "D":
        return
    state: dict[str, Any] = {"session": run_id, "phase": "STOP_REQUESTED"}
    _write_json(receipt, state)
    try:
        stopped = _run(
            ["colab", "--auth=oauth2", "stop", "--session", run_id],
            timeout=STOP_TIMEOUT_SECONDS,
        )
        state["stop_exit_code"] = stopped.returncode
    except Exception as exc:
        state["stop_error"] = type(exc).__name__
    state["phase"] = "STOP_RETURNED"
    _write_json(receipt, state)
    state["phase"] = "VERIFY_REQUESTED"
    _write_json(receipt, state)
    try:
        sessions = _run(["colab", "--auth=oauth2", "sessions"], timeout=VERIFY_TIMEOUT_SECONDS)
        state["sessions_exit_code"] = sessions.returncode
        state["session_list"] = sessions.stdout.strip()
        state["session_absent"] = sessions.returncode == 0 and _zero_sessions(sessions.stdout)
    except Exception as exc:
        state["verification_error"] = type(exc).__name__
        state["session_absent"] = False
    state["phase"] = "VERIFY_RETURNED"
    _write_json(receipt, state)


def _parse_balance(text: str) -> float:
    match = re.search(
        r"Current balance:\s*([0-9]+(?:\.[0-9]+)?)\s*compute units", text, re.IGNORECASE
    )
    if not match:
        raise RunError("Colab usage output did not contain a compute-unit balance")
    return float(match.group(1))


def _parse_colab_email(text: str) -> str:
    match = re.search(r"^Email:\s*([^\s]+@[^\s]+)\s*$", text, re.MULTILINE)
    if not match:
        raise RunError("Colab OAuth identity could not be verified")
    return match.group(1).lower()


def _same_google_account(colab_email: str, drive_email: str) -> bool:
    return colab_email.strip().lower() == drive_email.strip().lower()


def _drive_owner() -> dict[str, Any]:
    try:
        value = json.loads(DRIVE_OWNER_RECORD.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunError("connected Google Drive owner identity record is unavailable") from exc
    if (
        not isinstance(value, dict)
        or value.get("schema") != "RES541_A02_DRIVE_OWNER_V1"
        or value.get("folder_id") != DRIVE_FOLDER_ID
        or value.get("owner_only") is not True
        or not isinstance(value.get("email"), str)
        or not re.fullmatch(r"[^\s@]+@[^\s@]+", value["email"])
        or not isinstance(value.get("probe_file_id"), str)
        or not isinstance(value.get("probe_name"), str)
        or Path(value["probe_name"]).name != value["probe_name"]
        or not isinstance(value.get("probe_content"), str)
        or len(value["probe_content"].encode()) > 256
        or value.get("probe_sha256") != hashlib.sha256(value["probe_content"].encode()).hexdigest()
    ):
        raise RunError("connected Google Drive owner identity record is invalid")
    return value


def _run_id(
    protocol: dict[str, Any], protocol_sha256: str, attempt: int = 1, source: str = ""
) -> str:
    content = "\n".join(
        (
            protocol_sha256,
            str(attempt),
            source,
            protocol["historical_a01"]["case_manifest_sha256"],
            protocol["new_a02_cases"]["case_manifest_sha256"],
        )
    )
    return f"res541-a02-{attempt:03d}-{hashlib.sha256(content.encode()).hexdigest()[:24]}"


def _sanitize_colab_log(raw: str, run_id: str) -> str:
    records = []
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        safe = {
            key: event[key]
            for key in (
                "type",
                "event_type",
                "timestamp",
                "ts",
                "status",
                "exit_code",
                "duration_ms",
                "duration_s",
            )
            if key in event and isinstance(event[key], str | int | float | bool | type(None))
        }
        if safe:
            safe["session"] = run_id
            records.append(json.dumps(safe, sort_keys=True, separators=(",", ":")))
    return "\n".join(records) + ("\n" if records else "")


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


def _check_attempt(attempt: int, *, allow_used: bool = False) -> dict[str, str]:
    if attempt == 1:
        if ATTEMPT_MARKER.exists():
            raise RunError("the single A0.2 GPU allocation attempt has already been used")
        return {}
    if attempt != 2:
        raise RunError("only the separately authorized replacement attempt 2 is permitted")
    if REPLACEMENT_MARKER.exists() and not allow_used:
        raise RunError("replacement attempt 2 has already been used")
    try:
        inventory_bytes = RECOVERY_INVENTORY.read_bytes()
        if hashlib.sha256(inventory_bytes).hexdigest() != RECOVERY_INVENTORY_SHA256:
            raise RunError("recovery inventory identity changed")
        inventory = json.loads(inventory_bytes)
        for name, expected in inventory["files"].items():
            path = REPORT_DIR / name
            if path.resolve().is_relative_to(REPORT_DIR.resolve()) is False:
                raise RunError("recovery inventory contains an unsafe path")
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise RunError(f"original evidence changed: {name}")
        original = json.loads(ATTEMPT_MARKER.read_bytes())
        if original["run_id"] != "res541-a02-219a94c0d64e3af6c0cce654":
            raise RunError("original incident identity changed")
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RunError("original attempt evidence is unavailable or invalid") from exc
    return {
        "original_marker_sha256": hashlib.sha256(ATTEMPT_MARKER.read_bytes()).hexdigest(),
        "recovery_inventory_sha256": RECOVERY_INVENTORY_SHA256,
        "previous_run_id": original["run_id"],
    }


def _verify_replacement_science(recovery: dict[str, str]) -> None:
    previous_path = REPORT_DIR / recovery["previous_run_id"] / "protocol-v1.json"
    try:
        previous = json.loads(previous_path.read_bytes())
        current = json.loads(a02_experiment.PROTOCOL_PATH.read_bytes())
        immutable = (
            "schema",
            "status",
            "prepared_from_main",
            "population",
            "protected_data_used",
            "model",
            "historical_a01",
            "new_a02_cases",
            "scientific_source_sha256",
            "scientific_source_files",
            "tokenizer_preflight",
            "historical_inputs_sha256",
            "limits",
            "evaluation_rules",
            "decision_rules",
        )
        if any(previous[key] != current[key] for key in immutable):
            raise RunError("replacement protocol changes frozen scientific identities")
        a02_experiment.verify_protocol_source_bindings(current)
    except (OSError, KeyError, json.JSONDecodeError, ValueError) as exc:
        raise RunError("replacement protocol source or scientific binding is invalid") from exc


def preflight(attempt: int = 1) -> dict[str, Any]:
    recovery = _check_attempt(attempt)
    if attempt == 2:
        _verify_replacement_science(recovery)
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
    identity = _run(["colab", "--auth=oauth2", "whoami"], timeout=15)
    if identity.returncode != 0:
        raise RunError("Colab OAuth identity check failed")
    colab_email = _parse_colab_email(identity.stdout)
    drive_owner = _drive_owner()
    usage = _run(["colab", "--auth=oauth2", "usage"], timeout=30)
    sessions = _run(["colab", "--auth=oauth2", "sessions"], timeout=30)
    if usage.returncode != 0 or sessions.returncode != 0 or not _zero_sessions(sessions.stdout):
        raise RunError("Colab authentication, quota, or zero-session preflight failed")
    balance = _parse_balance(usage.stdout)
    if balance <= 0:
        raise RunError("Colab reports no existing compute-unit balance")
    return {
        "schema": "RES541_A02_COLAB_PREFLIGHT_V1",
        "attempt": attempt,
        "recovery": recovery,
        "utc": datetime.now(UTC).isoformat(),
        "branch": branch,
        "source_revision": head,
        "source_tree": tree,
        "base_head": base,
        "git_clean": True,
        "colab_cli": cli_version.stdout.strip(),
        "authentication": "OAUTH2_ACCOUNT_SESSION_VERIFIED",
        "colab_account_email": colab_email,
        "drive_owner_email": drive_owner["email"].lower(),
        "drive_folder_id": DRIVE_FOLDER_ID,
        "drive_folder_url": DRIVE_FOLDER_URL,
        "drive_folder_owner_only": True,
        "drive_probe_file_id": drive_owner["probe_file_id"],
        "drive_probe_name": drive_owner["probe_name"],
        "drive_probe_sha256": drive_owner["probe_sha256"],
        "drive_account_matches_colab": _same_google_account(colab_email, drive_owner["email"]),
        "drive_write_allowed": _same_google_account(colab_email, drive_owner["email"]),
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
            "exec_seconds_max": MAX_EXEC_SECONDS,
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
    protocol_bytes = a02_experiment.PROTOCOL_PATH.read_bytes()
    protocol = json.loads(protocol_bytes)
    archive_hash = hashlib.sha256(source_archive.read_bytes()).hexdigest()
    return {
        "schema": "RES541_A02_RUN_BINDING_V1",
        "run_id": run_id,
        "attempt": preflight_doc["attempt"],
        "recovery": preflight_doc["recovery"],
        "source_revision": preflight_doc["source_revision"],
        "source_tree": preflight_doc["source_tree"],
        "source_archive_sha256": archive_hash,
        "protocol_sha256": hashlib.sha256(protocol_bytes).hexdigest(),
        "historical_case_manifest_sha256": protocol["historical_a01"]["case_manifest_sha256"],
        "new_case_manifest_sha256": protocol["new_a02_cases"]["case_manifest_sha256"],
        "action_prompt_sha256": protocol["new_a02_cases"]["action_prompt_sha256"],
        "final_prompt_sha256": protocol["new_a02_cases"]["final_prompt_sha256"],
        "model_revision": protocol["model"]["model_revision"],
        "drive_folder_id": DRIVE_FOLDER_ID,
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
        + (
            f" | attempt=2 | recovery={doc['recovery']['recovery_inventory_sha256']}"
            if doc.get("attempt", 1) == 2
            else ""
        )
        + f" | source={doc['source_revision']}"
        f" | protocol={binding['protocol_sha256']}"
        f" | cases={cases_sha}"
        f" | action-prompt={prompt_sha}"
        f" | final-prompt={final_sha}"
        f" | model={protocol['model']['model_id']}@{protocol['model']['model_revision']}"
        f" | runtime={profile_id}:{profile_sha}"
        " | suites=16-paired+10-new"
        f" | current-balance={doc['compute_unit_balance']:.2f} CU"
        f" | drive-account-match={str(doc['drive_account_matches_colab']).lower()}"
        f" | drive-probe={doc['drive_probe_sha256'][:12]}"
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


def _copy_frozen_inputs(run_dir: Path) -> list[Path]:
    sources = (
        ROOT / "experiments/a02/protocol-v1.json",
        ROOT / "experiments/a02/cases-v1.json",
        ROOT / "experiments/a02/historical-cases-v1.json",
        ROOT / "experiments/a02/historical-inputs-v1.json",
        ROOT / "experiments/a02/system-action-v1.txt",
        ROOT / "experiments/a02/system-final-v1.txt",
        ROOT / "experiments/a01/system-prompt-v1.txt",
        ROOT / "experiments/a02/tokenizer-files-v1.json",
        ROOT / "experiments/a0/requirements-colab.txt",
        ROOT / "experiments/a02/README.md",
        REPORT_DIR / "preflight-v1.json",
    )
    copied = []
    for source in sources:
        target = run_dir / (
            "tokenizer-preflight-v1.json" if source.name == "preflight-v1.json" else source.name
        )
        if target.exists():
            raise RunError(f"A0.2 evidence file would overwrite existing data: {target.name}")
        target.write_bytes(source.read_bytes())
        copied.append(target)
    return copied


def _executor_records(remote: dict[str, Any], path: Path) -> None:
    lines = []
    for case in remote.get("cases", []):
        response = case.get("engine_response")
        if isinstance(response, dict):
            lines.append(
                json.dumps(
                    {
                        "case_id": case.get("case_id"),
                        "interaction_id": case.get("interaction_id"),
                        "engine_response": response,
                    },
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _gpu_resource_report(remote: dict[str, Any], run_id: str) -> dict[str, Any]:
    return {
        "schema": "RES541_A02_GPU_RESOURCE_REPORT_V1",
        "run_id": run_id,
        "model": remote.get("model"),
        "runtime": remote.get("runtime"),
        "peak_allocated_vram_bytes": remote.get("peak_allocated_vram_bytes"),
        "peak_reserved_vram_bytes": remote.get("peak_reserved_vram_bytes"),
        "runtime_seconds": remote.get("runtime_seconds"),
    }


def _write_artifact_manifest(
    run_id: str,
    run_dir: Path,
    paths: list[Path],
    terminal_outcome: str,
) -> tuple[Path, str]:
    manifest_path = run_dir / "artifact-hashes.json"
    if manifest_path.exists():
        raise RunError("A0.2 artifact manifest already exists; refusing overwrite")
    files = []
    seen = set()
    for path in dict.fromkeys(paths):
        if not path.is_file():
            continue
        if path.name in seen:
            raise RunError(f"A0.2 artifact names are not unique: {path.name}")
        seen.add(path.name)
        data = path.read_bytes()
        files.append(
            {
                "name": path.name,
                "local_path": str(path),
                "drive_path": f"{run_id}/{path.name}",
                "drive_file_id": None,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    manifest = {
        "schema": "RES541_A02_ARTIFACT_HASHES_V1",
        "run_id": run_id,
        "terminal_outcome": terminal_outcome,
        "drive": {
            "folder_id": DRIVE_FOLDER_ID,
            "folder_url": DRIVE_FOLDER_URL,
            "run_directory_name": run_id,
            "sync_status": "PENDING_CONNECTED_DRIVE_VERIFICATION_AND_SYNC",
        },
        "files": files,
    }
    content = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    manifest_path.write_text(content, encoding="utf-8")
    return manifest_path, content


def run(attempt: int = 1) -> int:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise RunError("Colab allocation requires the owner at an interactive WSL terminal")
    doc = preflight(attempt)
    protocol = json.loads(a02_experiment.PROTOCOL_PATH.read_text(encoding="utf-8"))
    protocol_sha = hashlib.sha256(a02_experiment.PROTOCOL_PATH.read_bytes()).hexdigest()
    run_id = _run_id(protocol, protocol_sha, attempt, doc["source_revision"])
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    run_dir = REPORT_DIR / run_id
    if run_dir.exists():
        raise RunError(f"content-addressed A0.2 run already exists; refusing overwrite: {run_dir}")
    run_dir.mkdir(parents=False, exist_ok=False)
    preflight_path = run_dir / "preflight.json"
    preflight_path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    frozen_inputs = _copy_frozen_inputs(run_dir)
    source_archive = run_dir / "source.tar"
    binding_path = run_dir / "binding.json"
    _archive_source(source_archive)
    binding = _binding(run_id, source_archive, doc, preflight_path)
    binding_path.write_text(json.dumps(binding, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    approval = _confirmation(doc, binding)
    print(
        "This requests one T4 session from the current Colab balance for this 16+10-case inference."
    )
    if not doc["drive_account_matches_colab"]:
        print(
            "Drive writes are disabled because the Colab OAuth account differs "
            "from connected Drive."
        )
    print(f"Evidence staging directory: {run_dir}")
    print(f"Type exactly: {approval}")
    if input("> ") != approval:
        shutil.rmtree(run_dir)
        raise RunError("interactive owner confirmation did not match; no Colab session was started")

    try:
        fresh = preflight(attempt)
        if (
            fresh["source_revision"] != doc["source_revision"]
            or fresh["recovery"] != doc["recovery"]
            or fresh["compute_unit_balance"] <= 0
        ):
            raise RunError("source or Colab quota changed after confirmation")
        if fresh["compute_unit_balance"] != doc["compute_unit_balance"]:
            raise RunError(
                "Colab balance changed after confirmation; obtain a fresh owner decision"
            )
        if (
            fresh["drive_owner_email"] != doc["drive_owner_email"]
            or fresh["drive_probe_sha256"] != doc["drive_probe_sha256"]
        ):
            raise RunError(
                "connected Drive identity or verification probe changed after confirmation"
            )
    except Exception:
        shutil.rmtree(run_dir)
        raise

    remote_artifact = run_dir / "remote-report.json"
    control_path = run_dir / "control.json"
    log_path = run_dir / "colab-execution-log.jsonl"
    drive_receipt_path = run_dir / "remote-drive-receipt.json"
    marker_path = ATTEMPT_MARKER if attempt == 1 else REPLACEMENT_MARKER
    attempt_copy = run_dir / marker_path.name
    authorization_path = run_dir / "authorization.json"
    base_evidence_paths = [
        *frozen_inputs,
        preflight_path,
        source_archive,
        binding_path,
        attempt_copy,
        authorization_path,
        control_path,
        run_dir / "watchdog-receipt.json",
    ]
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
        "drive_mount_exit_code": None,
        "drive_mount_status": "SKIPPED_ACCOUNT_MISMATCH"
        if not doc["drive_write_allowed"]
        else "NOT_ATTEMPTED",
        "stop_exit_code": None,
        "session_absent_after_stop": False,
    }
    watchdog: subprocess.Popen[str] | None = None
    _write_json(control_path, state)
    started = time.monotonic()
    deadline = started + MAX_SESSION_SECONDS

    def call(
        command: list[str], timeout: int, *, capture: bool = True
    ) -> subprocess.CompletedProcess[str]:
        remaining = int(deadline - time.monotonic())
        if remaining <= 0:
            raise subprocess.TimeoutExpired(command, timeout)
        return tracked_call(command, min(timeout, remaining), capture=capture)

    def tracked_call(
        command: list[str], timeout: int, *, capture: bool = True
    ) -> subprocess.CompletedProcess[str]:
        action = command[2] if len(command) > 2 else command[0]
        state["external_call"] = {"action": action, "phase": "REQUESTED"}
        _write_json(control_path, state)
        try:
            result = _run(command, timeout=timeout, capture=capture)
            state["external_call"] = {
                "action": action,
                "phase": "RETURNED",
                "exit_code": result.returncode,
            }
            return result
        except BaseException as exc:
            state["external_call"] = {
                "action": action,
                "phase": "FAILED",
                "error": type(exc).__name__,
            }
            raise
        finally:
            _write_json(control_path, state)

    allocation_attempted = False
    created = False

    def cancel_on_sigterm(signum: int, frame: Any) -> None:
        raise KeyboardInterrupt("SIGTERM")

    original_sigterm = signal.signal(signal.SIGTERM, cancel_on_sigterm)
    try:
        authorization = {
            "schema": "RES541_A02_AUTHORIZATION_V1",
            "attempt": attempt,
            "binding": binding,
            "owner_confirmation": approval,
            "recorded_utc": datetime.now(UTC).isoformat(),
        }
        with authorization_path.open("x", encoding="utf-8") as receipt:
            receipt.write(json.dumps(authorization, indent=2, sort_keys=True) + "\n")
        attempt_record = {
            "schema": "RES541_A02_ONE_ATTEMPT_USED_V1",
            "attempt": attempt,
            "authorization_sha256": hashlib.sha256(authorization_path.read_bytes()).hexdigest(),
            "recovery": doc["recovery"],
            "run_id": run_id,
            "source_revision": doc["source_revision"],
            "binding_sha256": hashlib.sha256(
                json.dumps(binding, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "owner_confirmation_sha256": hashlib.sha256(approval.encode()).hexdigest(),
            "recorded_utc": datetime.now(UTC).isoformat(),
        }
        with marker_path.open("x", encoding="utf-8") as marker:
            marker.write(json.dumps(attempt_record, indent=2, sort_keys=True) + "\n")
        state["allocation_attempted"] = True
        state["one_attempt_marker"] = str(marker_path)
        state["one_attempt_marker_sha256"] = hashlib.sha256(marker_path.read_bytes()).hexdigest()
        attempt_copy.write_bytes(marker_path.read_bytes())
        allocation_attempted = True
        state["watchdog_phase"] = "START_REQUESTED"
        _write_json(control_path, state)
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
            env=clean_colab_env(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            start_new_session=True,
        )
        if watchdog.stdout is None:
            raise RunError("watchdog readiness pipe unavailable")
        ready, _, _ = select.select([watchdog.stdout], [], [], 10)
        if not ready or watchdog.stdout.readline().strip() != "READY":
            raise RunError("watchdog failed to become ready; no allocation requested")
        state["watchdog_phase"] = "STARTED"
        state["watchdog_pid"] = watchdog.pid
        _write_json(control_path, state)
        new = call(
            ["colab", "--auth=oauth2", "new", "--session", run_id, "--gpu", "T4"],
            NEW_TIMEOUT_SECONDS,
        )
        state["new_exit_code"] = new.returncode
        state["allocation_returned_utc"] = datetime.now(UTC).isoformat()
        if new.returncode != 0:
            raise RunError("single requested T4 allocation failed; no GPU fallback or retry")
        created = True
        status = call(
            ["colab", "--auth=oauth2", "status", "--session", run_id], VERIFY_TIMEOUT_SECONDS
        )
        state["status_after_allocation_exit_code"] = status.returncode
        state["status_after_allocation"] = status.stdout.strip()
        if status.returncode != 0 or not re.search(r"\bT4\b", status.stdout, re.IGNORECASE):
            state["execution_blocker"] = "REQUESTED_T4_NOT_VERIFIED"
            raise RunError("Colab status did not verify the requested T4; inference not started")

        for local_path, remote_path, state_key in (
            (source_archive, "/content/a02-source.tar", "upload_source_exit_code"),
            (binding_path, "/content/a02-binding.json", "upload_binding_exit_code"),
        ):
            uploaded = call(
                [
                    "colab",
                    "--auth=oauth2",
                    "upload",
                    "--session",
                    run_id,
                    str(local_path),
                    remote_path,
                ],
                UPLOAD_TIMEOUT_SECONDS,
            )
            state[state_key] = uploaded.returncode
            if uploaded.returncode != 0:
                raise RunError(f"A0.2 upload failed: {remote_path}")

        reserve = (
            DOWNLOAD_TIMEOUT_SECONDS
            + DRIVE_RECEIPT_TIMEOUT_SECONDS
            + 3 * VERIFY_TIMEOUT_SECONDS
            + STOP_TIMEOUT_SECONDS
            + 60
        )
        exec_timeout = min(MAX_EXEC_SECONDS, max(1, int(deadline - time.monotonic()) - reserve))
        state["exec_timeout_seconds"] = exec_timeout
        command = [
            "colab",
            "--auth=oauth2",
            "exec",
            "--session",
            run_id,
            "--file",
            str(ROOT / "scripts/a02_remote.py"),
            "--timeout",
            str(exec_timeout),
        ]
        execute = call(command, exec_timeout + 30)
        state["exec_exit_code"] = execute.returncode
        state["inference_returned_utc"] = datetime.now(UTC).isoformat()
    except (Exception, KeyboardInterrupt) as exc:
        state["control_error"] = type(exc).__name__
        state["control_error_message"] = str(exc)[:2000]
    finally:
        with _cleanup_signals(original_sigterm):
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
                        raw_log = E_ROOT / "tmp" / f"{run_id}-colab-log.jsonl"
                        raw_log.parent.mkdir(parents=True, exist_ok=True)
                        log = tracked_call(
                            [
                                "colab",
                                "--auth=oauth2",
                                "log",
                                "--session",
                                run_id,
                                "--output",
                                str(raw_log),
                            ],
                            timeout=VERIFY_TIMEOUT_SECONDS,
                        )
                        state["colab_log_exit_code"] = log.returncode
                        if log.returncode == 0 and raw_log.is_file():
                            sanitized = _sanitize_colab_log(raw_log.read_text(), run_id)
                            if sanitized:
                                log_path.write_text(sanitized, encoding="utf-8")
                                state["sanitized_log_path"] = str(log_path)
                                state["sanitized_log_sha256"] = hashlib.sha256(
                                    sanitized.encode()
                                ).hexdigest()
                        raw_log.unlink(missing_ok=True)
                    except Exception as exc:
                        state["colab_log_error"] = type(exc).__name__
                        raw_log.unlink(missing_ok=True) if "raw_log" in locals() else None
                try:
                    stopped = tracked_call(
                        ["colab", "--auth=oauth2", "stop", "--session", run_id],
                        timeout=STOP_TIMEOUT_SECONDS,
                    )
                    state["stop_exit_code"] = stopped.returncode
                    state["stop_returned_utc"] = datetime.now(UTC).isoformat()
                except Exception as exc:
                    state["stop_error"] = type(exc).__name__
                try:
                    sessions = tracked_call(
                        ["colab", "--auth=oauth2", "sessions"], timeout=VERIFY_TIMEOUT_SECONDS
                    )
                    state["session_absent_after_stop"] = (
                        sessions.returncode == 0 and _zero_sessions(sessions.stdout)
                    )
                    state["session_list_after_stop"] = sessions.stdout.strip()
                except Exception as exc:
                    state["sessions_error"] = type(exc).__name__
                try:
                    usage_after = tracked_call(
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
            if watchdog is not None and watchdog.stdin is not None:
                try:
                    if state["session_absent_after_stop"]:
                        watchdog.stdin.write("D")
                        watchdog.stdin.flush()
                    watchdog.stdin.close()
                except (OSError, BrokenPipeError) as exc:
                    state["watchdog_error"] = type(exc).__name__
                state["watchdog_phase"] = (
                    "DISARMED" if state["session_absent_after_stop"] else "TRIGGERED"
                )
                _write_json(control_path, state)
            state["elapsed_seconds"] = time.monotonic() - started
            state["finished_utc"] = datetime.now(UTC).isoformat()
            control_path.write_text(
                json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )

    if not allocation_attempted:
        raise RunError(f"Colab allocation was not attempted; control receipt: {control_path}")

    def external_blocker(reason: str, *extra_paths: Path) -> int:
        state["terminal_outcome"] = "EXTERNAL_BLOCKER"
        state["external_blocker"] = reason
        control_path.write_text(
            json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        blocker_path = run_dir / "external-blocker.json"
        blocker_path.write_text(
            json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        manifest_path, manifest_bytes = _write_artifact_manifest(
            run_id,
            run_dir,
            [
                *base_evidence_paths,
                *extra_paths,
                blocker_path,
                log_path,
                drive_receipt_path,
            ],
            state["terminal_outcome"],
        )
        print(
            json.dumps(
                {
                    "terminal_outcome": state["terminal_outcome"],
                    "external_blocker": reason,
                    "control": str(control_path),
                    "artifact_hash_manifest": str(manifest_path),
                    "artifact_hash_manifest_sha256": hashlib.sha256(
                        manifest_bytes.encode()
                    ).hexdigest(),
                }
            )
        )
        return 1

    if not state["session_absent_after_stop"]:
        return external_blocker("ZERO_ACTIVE_SESSIONS_NOT_VERIFIED", remote_artifact)
    if state["stop_exit_code"] != 0:
        return external_blocker("SESSION_STOP_NOT_CONFIRMED", remote_artifact)
    if not remote_artifact.is_file() or state.get("download_exit_code") != 0:
        return external_blocker(
            state.get("execution_blocker", "REMOTE_REPORT_NOT_RECOVERED"), remote_artifact
        )
    if remote_artifact.stat().st_size > 8 * 1024**2:
        return external_blocker("REMOTE_REPORT_EXCEEDS_8_MIB_BOUND", remote_artifact)
    try:
        remote = json.loads(remote_artifact.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return external_blocker("REMOTE_REPORT_JSON_INVALID", remote_artifact)
    drive_receipt = drive_receipt_path
    if drive_receipt.is_file():
        drive_receipt_doc = json.loads(drive_receipt.read_text(encoding="utf-8"))
        state["remote_drive_receipt_path"] = str(drive_receipt_path)
        state["remote_drive_receipt_sha256"] = hashlib.sha256(
            drive_receipt.read_bytes()
        ).hexdigest()
        if state["drive_mount_status"] == "MOUNTED_IDENTITY_PENDING_REMOTE_PROBE":
            state["drive_mount_status"] = drive_receipt_doc.get("status", "UNAVAILABLE")
        control_path.write_text(
            json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    remote_drive_status = remote.get("drive_persistence", {}).get("status", "NOT_MOUNTED")
    if state["drive_mount_status"] == "MOUNTED_IDENTITY_PENDING_REMOTE_PROBE":
        state["drive_mount_status"] = remote_drive_status
        control_path.write_text(
            json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if not drive_receipt.is_file():
        drive_receipt.write_text(
            json.dumps(
                {
                    "schema": "RES541_A02_DRIVE_PERSISTENCE_RECEIPT_V1",
                    "run_id": run_id,
                    "status": remote_drive_status,
                    "folder_id": DRIVE_FOLDER_ID,
                    "folder_url": DRIVE_FOLDER_URL,
                    "persistence": remote.get("drive_persistence", {}),
                    "remote_report_sha256": hashlib.sha256(
                        remote_artifact.read_bytes()
                    ).hexdigest(),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    if remote.get("status") != "COMPLETE" or state.get("exec_exit_code") != 0:
        return external_blocker(
            remote.get("failure_message", "REMOTE_INFERENCE_INCOMPLETE"),
            remote_artifact,
            drive_receipt_path,
        )
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
    try:
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
                str(run_dir),
            ],
            cwd=ROOT,
            env=score_env,
            timeout=180,
            text=True,
            capture_output=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return external_blocker(
            f"CPU_SCIENTIFIC_REPLAY_FAILED_{type(exc).__name__}", remote_artifact
        )
    verified_path = run_dir / "verified.json"
    markdown_path = run_dir / "scientific-report.md"
    if score.returncode not in {0, 1} or not verified_path.is_file() or not markdown_path.is_file():
        return external_blocker(
            f"CPU_SCIENTIFIC_REPLAY_FAILED_EXIT_{score.returncode}",
            remote_artifact,
            verified_path,
            markdown_path,
        )
    try:
        verified = json.loads(verified_path.read_text())
    except (OSError, json.JSONDecodeError):
        return external_blocker(
            "CPU_VERIFIED_REPORT_JSON_INVALID", remote_artifact, verified_path, markdown_path
        )
    if verified.get("schema") != "RES541_A02_VERIFIED_REPORT_V1":
        return external_blocker(
            "CPU_VERIFIED_REPORT_SCHEMA_INVALID", remote_artifact, verified_path, markdown_path
        )
    executor_path = run_dir / "trusted-executor-records.jsonl"
    _executor_records(remote, executor_path)
    resource_path = run_dir / "gpu-resource-report.json"
    resource_path.write_text(
        json.dumps(_gpu_resource_report(remote, run_id), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    artifact_paths = [
        *frozen_inputs,
        preflight_path,
        source_archive,
        binding_path,
        attempt_copy,
        authorization_path,
        remote_artifact,
        control_path,
        verified_path,
        markdown_path,
        executor_path,
        resource_path,
    ]
    if log_path.is_file():
        artifact_paths.append(log_path)
    if drive_receipt_path.is_file():
        artifact_paths.append(drive_receipt_path)
    drive_sync_status = "PENDING_CONNECTED_DRIVE_VERIFICATION_AND_SYNC"
    manifest_path, manifest_bytes = _write_artifact_manifest(
        run_id, run_dir, artifact_paths, verified["terminal_outcome"]
    )
    print(
        json.dumps(
            {
                "terminal_outcome": verified["terminal_outcome"],
                "run_id": run_id,
                "evidence_package": str(run_dir),
                "report": str(markdown_path),
                "artifact_hash_manifest": str(manifest_path),
                "artifact_hash_manifest_sha256": hashlib.sha256(
                    manifest_bytes.encode()
                ).hexdigest(),
                "drive_sync_status": drive_sync_status,
                "drive_folder_id": DRIVE_FOLDER_ID,
                "drive_run_directory": run_id,
            },
            indent=2,
        )
    )
    return 0


def main() -> int:
    if len(sys.argv) == 4 and sys.argv[1] == "watchdog":
        _watchdog(sys.argv[2], Path(sys.argv[3]))
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "run"))
    parser.add_argument("--attempt", type=int, default=1, choices=(1, 2))
    args = parser.parse_args()
    if args.command == "preflight":
        print(json.dumps(preflight(args.attempt), indent=2, sort_keys=True))
        return 0
    return run(args.attempt)


if __name__ == "__main__":
    raise SystemExit(main())
