"""Versioned, model-independent runtime qualification for RES-541 V2."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import re
import site
import subprocess
import sys
import sysconfig
from pathlib import Path
from typing import Any

POLICY: dict[str, Any] = {
    "schema": "RES541_A02_RUNTIME_POLICY_V1",
    "id": "RES541_A02_CPYTHON313_T4_CAPABILITY_V1",
    "compatibility": {
        "system": "Linux",
        "machine": "x86_64",
        "implementation": "CPython",
        "python_minor": "3.13",
        "soabi": "cpython-313-x86_64-linux-gnu",
        "gpu_name_contains": "T4",
        "compute_capability": [7, 5],
        "device_count": 1,
        "minimum_total_vram_bytes": 12 * 1024**3,
        "minimum_free_vram_bytes": 8 * 1024**3,
        "cuda_smoke": "synchronized_fp16_16x16_matmul",
    },
}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def policy_binding() -> dict[str, str]:
    return {
        "runtime_policy_id": POLICY["id"],
        "runtime_policy_sha256": hashlib.sha256(_canonical(POLICY)).hexdigest(),
    }


def _path(value: Any) -> str | None:
    try:
        return str(Path(value).resolve()) if isinstance(value, str) else None
    except (OSError, RuntimeError):
        return None


def inventory(torch: Any | None, inference_site: Path) -> dict[str, Any]:
    """Capture compatibility inputs and provenance before any model weight access."""
    distribution_error: str | None = None
    try:
        distribution = importlib.metadata.distribution("torch")
    except importlib.metadata.PackageNotFoundError as exc:
        distribution = None
        distribution_error = type(exc).__name__
    torch_module = getattr(torch, "_C", None)
    cuda: dict[str, Any] = {
        "available": None,
        "device_count": None,
        "name": None,
        "uuid": None,
        "compute_capability": None,
        "total_vram_bytes": None,
        "free_vram_bytes": None,
        "allocated_vram_bytes": None,
        "reserved_vram_bytes": None,
    }
    inventory_errors: dict[str, str] = {}
    try:
        if torch is None:
            raise ImportError("PyTorch import failed")
        cuda["available"] = bool(torch.cuda.is_available())
        cuda["device_count"] = int(torch.cuda.device_count())
        if cuda["available"] and cuda["device_count"] > 0:
            properties = torch.cuda.get_device_properties(0)
            free_bytes, total_bytes = torch.cuda.mem_get_info(0)
            cuda.update(
                name=str(properties.name),
                uuid=str(properties.uuid) if properties.uuid is not None else None,
                compute_capability=list(torch.cuda.get_device_capability(0)),
                total_vram_bytes=int(total_bytes),
                free_vram_bytes=int(free_bytes),
                allocated_vram_bytes=int(torch.cuda.memory_allocated(0)),
                reserved_vram_bytes=int(torch.cuda.memory_reserved(0)),
            )
    except Exception as exc:
        inventory_errors["cuda"] = f"{type(exc).__name__}: {str(exc)[:500]}"

    origin = _path(getattr(torch, "__file__", None))
    distribution_origin = (
        _path(str(distribution.locate_file(""))) if distribution is not None else None
    )
    extension_origin = _path(getattr(torch_module, "__file__", None))
    excluded_site = inference_site.resolve()
    inherited_sites = [
        str(Path(path).resolve())
        for path in site.getsitepackages()
        if Path(path).resolve() != excluded_site
    ]
    driver_inventory: str | None
    try:
        driver_inventory = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=uuid,driver_version,name,memory.total,memory.free,compute_cap",
                "--format=csv,noheader",
            ],
            text=True,
            timeout=10,
        ).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        driver_inventory = f"unavailable: {type(exc).__name__}"

    return {
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "full_version": sys.version,
            "build": list(platform.python_build()),
            "compiler": platform.python_compiler(),
            "executable": sys.executable,
            "system": platform.system(),
            "machine": platform.machine(),
            "soabi": sysconfig.get_config_var("SOABI"),
            "extension_suffix": sysconfig.get_config_var("EXT_SUFFIX"),
            "gil_disabled": sysconfig.get_config_var("Py_GIL_DISABLED"),
            "gil_enabled": getattr(sys, "_is_gil_enabled", lambda: None)(),
            "debug_build": sysconfig.get_config_var("Py_DEBUG"),
        },
        "torch": {
            "version": str(torch.__version__) if torch is not None else None,
            "distribution_version": distribution.version if distribution is not None else None,
            "cuda_runtime": getattr(getattr(torch, "version", None), "cuda", None),
            "module_origin": origin,
            "distribution_origin": distribution_origin,
            "extension_origin": extension_origin,
            "cxx11_abi": getattr(torch_module, "_GLIBCXX_USE_CXX11_ABI", None),
            "inference_site": str(inference_site.resolve()),
            "inherited_system_sites": inherited_sites,
        },
        "cuda": cuda,
        "driver_inventory": driver_inventory,
        "inventory_errors": {
            **inventory_errors,
            **({"torch_distribution": distribution_error} if distribution_error else {}),
        },
    }


def cuda_smoke(torch: Any, inventory_record: dict[str, Any]) -> dict[str, Any]:
    cuda = inventory_record["cuda"]
    if cuda.get("available") is not True or cuda.get("device_count", 0) < 1:
        return {"attempted": False, "passed": False, "observed": "CUDA device unavailable"}
    try:
        left = torch.ones((16, 16), dtype=torch.float16, device="cuda")
        result = left @ left
        torch.cuda.synchronize(0)
        passed = bool(torch.all(result == 16).item())
        return {
            "attempted": True,
            "passed": passed,
            "observed": "all 256 FP16 outputs equal 16" if passed else "matrix result differed",
        }
    except Exception as exc:
        return {
            "attempted": True,
            "passed": False,
            "observed": f"{type(exc).__name__}: {str(exc)[:500]}",
        }


def qualify(observed: dict[str, Any], smoke: dict[str, Any]) -> dict[str, Any]:
    """Return exact requirement outcomes; provenance fields never silently act as gates."""
    required = POLICY["compatibility"]
    python = observed["python"]
    torch = observed["torch"]
    cuda = observed["cuda"]
    python_version = python.get("version")
    python_minor = (
        ".".join(python_version.split(".")[:2]) if isinstance(python_version, str) else None
    )
    suffix = python.get("extension_suffix")
    extension_origin = torch.get("extension_origin")
    distribution_origin = torch.get("distribution_origin")
    module_origin = torch.get("module_origin")
    inherited_sites = torch.get("inherited_system_sites")
    outcomes: list[dict[str, Any]] = []

    def check(
        name: str, expected: Any, value: Any, passed: bool, kind: str = "compatibility"
    ) -> None:
        outcomes.append(
            {"name": name, "class": kind, "expected": expected, "observed": value, "passed": passed}
        )

    check(
        "system",
        required["system"],
        python.get("system"),
        python.get("system") == required["system"],
    )
    check(
        "machine",
        required["machine"],
        python.get("machine"),
        python.get("machine") == required["machine"],
    )
    check(
        "python_implementation",
        required["implementation"],
        python.get("implementation"),
        python.get("implementation") == required["implementation"],
    )
    check(
        "python_minor",
        required["python_minor"],
        python_minor,
        python_minor == required["python_minor"],
    )
    final_release = (
        isinstance(python_version, str)
        and re.fullmatch(r"3\.13\.[0-9]+", python_version) is not None
    )
    check("python_final_release", "final CPython 3.13 release", python_version, final_release)
    check(
        "python_soabi",
        required["soabi"],
        python.get("soabi"),
        python.get("soabi") == required["soabi"],
    )
    torch_version = torch.get("version")
    distribution_version = torch.get("distribution_version")
    check(
        "torch_distribution_version",
        "same as loaded PyTorch module",
        distribution_version,
        isinstance(torch_version, str) and torch_version == distribution_version,
        "integrity",
    )
    check(
        "torch_module_origin",
        f"under {distribution_origin}",
        module_origin,
        _is_relative_to(module_origin, distribution_origin),
        "integrity",
    )
    inherited = isinstance(inherited_sites, list) and any(
        _is_relative_to(distribution_origin, root) for root in inherited_sites
    )
    check(
        "torch_inherited_origin",
        "outside the inference venv and under an inherited system site",
        distribution_origin,
        inherited,
        "integrity",
    )
    abi_matches = (
        isinstance(suffix, str)
        and bool(suffix)
        and isinstance(extension_origin, str)
        and Path(extension_origin).name.endswith(suffix)
    )
    check("torch_python_abi", f"extension suffix {suffix}", extension_origin, abi_matches)
    cuda_runtime = torch.get("cuda_runtime")
    check(
        "torch_cuda_runtime",
        "a CUDA-enabled PyTorch build",
        cuda_runtime,
        isinstance(cuda_runtime, str) and bool(cuda_runtime),
    )
    available = cuda.get("available")
    check("cuda_available", True, available, available is True)
    device_count = cuda.get("device_count")
    check(
        "cuda_device_count",
        required["device_count"],
        device_count,
        device_count == required["device_count"],
    )
    gpu_name = cuda.get("name")
    gpu_matches = (
        isinstance(gpu_name, str)
        and required["gpu_name_contains"].casefold() in gpu_name.casefold()
    )
    check("gpu_name", f"name containing {required['gpu_name_contains']}", gpu_name, gpu_matches)
    capability = cuda.get("compute_capability")
    check(
        "compute_capability",
        required["compute_capability"],
        capability,
        capability == required["compute_capability"],
    )
    total = cuda.get("total_vram_bytes")
    check(
        "total_vram_bytes",
        f">= {required['minimum_total_vram_bytes']}",
        total,
        type(total) is int and total >= required["minimum_total_vram_bytes"],
    )
    free = cuda.get("free_vram_bytes")
    check(
        "free_vram_bytes",
        f">= {required['minimum_free_vram_bytes']}",
        free,
        type(free) is int and free >= required["minimum_free_vram_bytes"],
    )
    check("cuda_smoke", required["cuda_smoke"], smoke.get("observed"), smoke.get("passed") is True)
    failures = [check for check in outcomes if not check["passed"]]
    failures = [check for check in outcomes if not check["passed"]]
    provenance = {
        "python_full_version": python.get("full_version"),
        "python_build": python.get("build"),
        "python_compiler": python.get("compiler"),
        "python_executable": python.get("executable"),
        "gil_disabled": python.get("gil_disabled"),
        "gil_enabled": python.get("gil_enabled"),
        "debug_build": python.get("debug_build"),
        "torch_version": torch.get("version"),
        "torch_cuda_runtime": torch.get("cuda_runtime"),
        "torch_module_origin": module_origin,
        "torch_distribution_origin": distribution_origin,
        "torch_extension_origin": extension_origin,
        "torch_cxx11_abi": torch.get("cxx11_abi"),
        "gpu_uuid": cuda.get("uuid"),
        "driver_inventory": observed.get("driver_inventory"),
    }
    return {
        "schema": "RES541_A02_RUNTIME_QUALIFICATION_V1",
        **policy_binding(),
        "qualified": not failures,
        "requirements": outcomes,
        "failed_requirements": failures,
        "cuda_smoke": smoke,
        "provenance_only": provenance,
    }


def _is_relative_to(path: Any, parent: Any) -> bool:
    if not isinstance(path, str) or not isinstance(parent, str):
        return False
    try:
        return Path(path).is_relative_to(Path(parent))
    except (OSError, RuntimeError, ValueError):
        return False


class RuntimeQualificationError(ValueError):
    def __init__(self, decision: dict[str, Any]) -> None:
        self.decision = decision
        failures = decision["failed_requirements"]
        detail = "; ".join(
            f"{item['name']}: expected {item['expected']!r}, observed {item['observed']!r}"
            for item in failures
        )
        super().__init__(f"V2 runtime qualification failed: {detail}")
