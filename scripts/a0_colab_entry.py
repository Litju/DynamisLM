"""Colab-side orchestrator; provisions exact source and separates Python 3.12 authority."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import resource as process_resource
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPORT_SCHEMA = "RES541_A0_REPORT_V1"
SOURCE_REPOSITORY = "https://github.com/Litju/DynamisLM.git"
SOURCE_PYTHON = "3.12.13"
UV_VERSION = "0.12.2"
MAX_RUNTIME_SECONDS = 840
MIN_TOTAL_VRAM_BYTES = 12 * 1024**3
MIN_FREE_VRAM_BYTES = 8 * 1024**3
MIN_FREE_DISK_BYTES = 12 * 1024**3
GIB = 1024**3


class A0Error(RuntimeError):
    def __init__(self, stage: str, category: str) -> None:
        super().__init__(category)
        self.stage = stage
        self.category = category


def _run(
    command: list[str],
    *,
    cwd: Path | None,
    env: dict[str, str] | None,
    deadline: float,
    timeout: int,
    stage: str,
) -> str:
    remaining = int(deadline - time.monotonic())
    if remaining <= 0:
        raise A0Error(stage, "EXECUTION_DEADLINE_EXCEEDED")
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            capture_output=True,
            check=False,
            text=True,
            timeout=min(timeout, remaining),
        )
    except subprocess.TimeoutExpired as exc:
        raise A0Error(stage, "SUBPROCESS_TIMEOUT") from exc
    if completed.returncode != 0:
        raise A0Error(stage, "SUBPROCESS_FAILED")
    return completed.stdout


def _preflight() -> tuple[Any, dict[str, object]]:
    try:
        import torch  # type: ignore[import-not-found]
    except ImportError as exc:
        raise A0Error("GPU_PREFLIGHT", "TORCH_UNAVAILABLE") from exc
    if platform.python_version() != "3.13.15":
        raise A0Error("GPU_PREFLIGHT", "PYTHON_VERSION_MISMATCH")
    if str(torch.__version__) != "2.11.0+cu130":
        raise A0Error("GPU_PREFLIGHT", "PYTORCH_VERSION_MISMATCH")
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise A0Error("GPU_PREFLIGHT", "CUDA_DEVICE_UNAVAILABLE_OR_AMBIGUOUS")
    properties = torch.cuda.get_device_properties(0)
    capability = torch.cuda.get_device_capability(0)
    free_vram, _ = torch.cuda.mem_get_info(0)
    total_vram = int(properties.total_memory)
    if "T4" not in properties.name or capability != (7, 5):
        raise A0Error("GPU_PREFLIGHT", "GPU_IDENTITY_MISMATCH")
    if total_vram < MIN_TOTAL_VRAM_BYTES or free_vram < MIN_FREE_VRAM_BYTES:
        raise A0Error("GPU_PREFLIGHT", "GPU_MEMORY_BELOW_BOUND")
    disk_free = int(shutil.disk_usage(Path.cwd()).free)
    if disk_free < MIN_FREE_DISK_BYTES:
        raise A0Error("GPU_PREFLIGHT", "DISK_SPACE_BELOW_BOUND")
    return torch, {
        "python": platform.python_version(),
        "torch": str(torch.__version__),
        "torch_cuda_runtime": torch.version.cuda,
        "gpu_name": properties.name,
        "compute_capability": list(capability),
        "total_vram_bytes": total_vram,
        "free_vram_before_setup_bytes": int(free_vram),
        "disk_free_before_setup_bytes": disk_free,
    }


def _write_failure(
    path: Path,
    *,
    revision: str,
    stage: str,
    category: str,
    elapsed_seconds: float,
    preflight: dict[str, object] | None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document: dict[str, object] = {
        "schema": REPORT_SCHEMA,
        "status": "NO_GO",
        "scope": "SYNTHETIC_DEVELOPMENT_ONLY",
        "source_revision": revision,
        "failure_stage": stage,
        "failure_category": category,
        "remote_elapsed_seconds": round(elapsed_seconds, 3),
        "runtime_preflight": preflight or {},
        "cases": [],
    }
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run(revision: str, run_id: str, report_path: Path) -> int:
    if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise A0Error("SOURCE_VALIDATION", "INVALID_GIT_REVISION")
    if re.fullmatch(r"[a-z0-9-]{1,64}", run_id) is None:
        raise A0Error("SOURCE_VALIDATION", "INVALID_RUN_ID")
    started = time.monotonic()
    deadline = started + MAX_RUNTIME_SECONDS
    stage = "GPU_PREFLIGHT"
    preflight: dict[str, object] | None = None
    report_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _torch, preflight = _preflight()
        with tempfile.TemporaryDirectory(prefix="res541-a0-") as temporary:
            work = Path(temporary)
            repository = work / "source"
            stage = "EXACT_SOURCE_TRANSFER"
            _run(
                [
                    "git",
                    "clone",
                    "--filter=blob:none",
                    "--no-checkout",
                    SOURCE_REPOSITORY,
                    str(repository),
                ],
                cwd=work,
                env=None,
                deadline=deadline,
                timeout=90,
                stage=stage,
            )
            _run(
                ["git", "-C", str(repository), "fetch", "--depth=1", "origin", revision],
                cwd=work,
                env=None,
                deadline=deadline,
                timeout=90,
                stage=stage,
            )
            _run(
                ["git", "-C", str(repository), "checkout", "--detach", revision],
                cwd=work,
                env=None,
                deadline=deadline,
                timeout=30,
                stage=stage,
            )
            head = _run(
                ["git", "-C", str(repository), "rev-parse", "HEAD"],
                cwd=work,
                env=None,
                deadline=deadline,
                timeout=15,
                stage=stage,
            ).strip()
            if head != revision:
                raise A0Error(stage, "SOURCE_REVISION_MISMATCH")
            source_tree = _run(
                ["git", "-C", str(repository), "rev-parse", "HEAD^{tree}"],
                cwd=work,
                env=None,
                deadline=deadline,
                timeout=15,
                stage=stage,
            ).strip()
            if _run(
                ["git", "-C", str(repository), "status", "--porcelain"],
                cwd=work,
                env=None,
                deadline=deadline,
                timeout=15,
                stage=stage,
            ).strip():
                raise A0Error(stage, "SOURCE_CHECKOUT_DIRTY")

            stage = "PYTHON_312_BOOTSTRAP"
            uv_target = work / "uv"
            _run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "--no-input",
                    "--target",
                    str(uv_target),
                    f"uv=={UV_VERSION}",
                ],
                cwd=work,
                env=None,
                deadline=deadline,
                timeout=120,
                stage=stage,
            )
            uv_env = os.environ.copy()
            uv_env["PYTHONPATH"] = str(uv_target) + os.pathsep + uv_env.get("PYTHONPATH", "")
            uv_prefix = [sys.executable, "-m", "uv"]
            uv_version = _run(
                [*uv_prefix, "--version"],
                cwd=repository,
                env=uv_env,
                deadline=deadline,
                timeout=15,
                stage=stage,
            ).strip()
            if uv_version != f"uv {UV_VERSION}":
                raise A0Error(stage, "UV_VERSION_MISMATCH")
            _run(
                [*uv_prefix, "python", "install", SOURCE_PYTHON],
                cwd=repository,
                env=uv_env,
                deadline=deadline,
                timeout=240,
                stage=stage,
            )
            _run(
                [*uv_prefix, "sync", "--frozen", "--python", SOURCE_PYTHON],
                cwd=repository,
                env=uv_env,
                deadline=deadline,
                timeout=300,
                stage=stage,
            )
            engine_python = repository / ".venv" / "bin" / "python"
            if not engine_python.exists():
                raise A0Error(stage, "PYTHON_312_ENVIRONMENT_MISSING")

            prepared_path = work / "prepared-cases.json"
            stage = "SYNTHETIC_CASE_PREPARATION"
            _run(
                [
                    str(engine_python),
                    str(repository / "scripts" / "a0_engine.py"),
                    "prepare",
                    "--output",
                    str(prepared_path),
                ],
                cwd=repository,
                env=uv_env,
                deadline=deadline,
                timeout=120,
                stage=stage,
            )

            stage = "INFERENCE_ENVIRONMENT"
            inference_env_path = work / "inference-env"
            _run(
                [sys.executable, "-m", "venv", "--system-site-packages", str(inference_env_path)],
                cwd=work,
                env=None,
                deadline=deadline,
                timeout=30,
                stage=stage,
            )
            inference_python = inference_env_path / "bin" / "python"
            requirements = repository / "experiments" / "a0" / "requirements-colab.txt"
            _run(
                [
                    str(inference_python),
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "--no-input",
                    "--no-deps",
                    "-r",
                    str(requirements),
                ],
                cwd=repository,
                env=None,
                deadline=deadline,
                timeout=240,
                stage=stage,
            )
            torch_probe_script = (
                "import json, torch\n"
                "print(json.dumps({'version': str(torch.__version__), 'path': torch.__file__}))"
            )
            torch_probe = _run(
                [
                    str(inference_python),
                    "-c",
                    torch_probe_script,
                ],
                cwd=repository,
                env=None,
                deadline=deadline,
                timeout=15,
                stage=stage,
            ).strip()
            child_torch = json.loads(torch_probe)
            import torch

            if (
                child_torch.get("version") != str(torch.__version__)
                or Path(str(child_torch.get("path"))).resolve() != Path(torch.__file__).resolve()
            ):
                raise A0Error(stage, "INFERENCE_ENV_DID_NOT_INHERIT_COLAB_TORCH")

            model_outputs = work / "model-outputs.json"
            stage = "PINNED_MODEL_INFERENCE"
            inference_env = os.environ.copy()
            inference_env["HF_HOME"] = str(work / "model-cache")
            inference_env["HF_HUB_DISABLE_TELEMETRY"] = "1"
            inference_env["HF_HUB_DOWNLOAD_TIMEOUT"] = "90"
            inference_env["HF_HUB_ETAG_TIMEOUT"] = "30"
            _run(
                [
                    str(inference_python),
                    str(repository / "scripts" / "a0_colab_inference.py"),
                    "--prepared-cases",
                    str(prepared_path),
                    "--output",
                    str(model_outputs),
                ],
                cwd=repository,
                env=inference_env,
                deadline=deadline,
                timeout=MAX_RUNTIME_SECONDS,
                stage=stage,
            )

            stage = "INFERENCE_OUTPUT_VALIDATION"
            outputs = json.loads(model_outputs.read_text(encoding="utf-8"))
            if not isinstance(outputs, dict) or outputs.get("status") != "COMPLETE":
                category = outputs.get("failure_category") if isinstance(outputs, dict) else None
                if (
                    not isinstance(category, str)
                    or re.fullmatch(r"[A-Za-z0-9_]+", category) is None
                ):
                    category = "INFERENCE_FAILED"
                raise A0Error(stage, category)

            stage = "DETERMINISTIC_SCIENTIFIC_SCORING"
            engine_report = work / "engine-report.json"
            _run(
                [
                    str(engine_python),
                    str(repository / "scripts" / "a0_engine.py"),
                    "score",
                    "--model-outputs",
                    str(model_outputs),
                    "--source-revision",
                    revision,
                    "--output",
                    str(engine_report),
                ],
                cwd=repository,
                env=uv_env,
                deadline=deadline,
                timeout=120,
                stage=stage,
            )
            report = json.loads(engine_report.read_text(encoding="utf-8"))
            engine_report_payload = report.get("runtime", {})
            if not isinstance(engine_report_payload, dict):
                engine_report_payload = {}
            engine_report_payload["python_engine"] = SOURCE_PYTHON
            engine_report_payload["uv"] = UV_VERSION
            engine_report_payload["model_id"] = "HuggingFaceTB/SmolLM3-3B"
            engine_report_payload["model_revision"] = "a07cc9a04f16550a088caea529712d1d335b0ac1"
            engine_report_payload["transformers"] = "4.53.0"
            engine_report_payload["inference_packages"] = outputs.get("packages", {})
            engine_report_payload["weight_dtype"] = "float16"
            engine_report_payload["device_map"] = {"": 0}
            report["runtime"] = engine_report_payload
            report["source"] = {
                "repository": SOURCE_REPOSITORY,
                "revision": revision,
                "resolved_head": head,
                "tree_sha": source_tree,
                "clean_checkout": True,
                "full_repository_cloned": True,
            }
            report["colab"] = {"gpu_requested": "T4", "remote_vm": True}
            report["resource"] = {
                "remote_elapsed_seconds": round(time.monotonic() - started, 3),
                "remote_execution_limit_seconds": MAX_RUNTIME_SECONDS,
                "process_peak_rss_bytes": int(
                    process_resource.getrusage(process_resource.RUSAGE_SELF).ru_maxrss * 1024
                ),
                "disk_free_before_setup_bytes": preflight["disk_free_before_setup_bytes"],
                "disk_free_before_weight_load_bytes": engine_report_payload.get(
                    "free_disk_before_weight_load_bytes"
                ),
                "disk_free_after_inference_bytes": engine_report_payload.get(
                    "free_disk_after_inference_bytes"
                ),
                "weight_file_bytes_from_pinned_revision": engine_report_payload.get(
                    "model_weight_bytes_from_revision_metadata"
                ),
                "weight_cache_bytes_delta": engine_report_payload.get("model_cache_bytes_delta"),
                "weights_loaded": True,
                "training_or_fine_tuning": False,
                "model_output_artifact_bytes": model_outputs.stat().st_size,
                "python_engine_report_bytes": engine_report.stat().st_size,
                "inference_runtime": outputs.get("runtime", {}),
            }
            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            if report_path.stat().st_size > 2 * 1024**2:
                raise A0Error("ARTIFACT_SIZE_CHECK", "REPORT_EXCEEDS_2_MIB_BOUND")
        print(f"RES-541 A0 {run_id}: report ready; source={revision}; status={report['status']}")
        return 0
    except A0Error as exc:
        _write_failure(
            report_path,
            revision=revision,
            stage=exc.stage,
            category=exc.category,
            elapsed_seconds=time.monotonic() - started,
            preflight=preflight,
        )
        print(f"RES-541 A0 stopped at {exc.stage}: {exc.category}", file=sys.stderr)
        return 1
    except Exception as exc:
        _write_failure(
            report_path,
            revision=revision,
            stage=stage,
            category=type(exc).__name__,
            elapsed_seconds=time.monotonic() - started,
            preflight=preflight,
        )
        print(f"RES-541 A0 stopped at {stage}: {type(exc).__name__}", file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--report-path", type=Path)
    args = parser.parse_args()
    report_path = args.report_path or Path("/content") / f"{args.run_id}-report.json"
    return run(args.source_revision, args.run_id, report_path)


if __name__ == "__main__":
    raise SystemExit(main())
