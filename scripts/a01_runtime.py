"""The reviewed A0.1 Colab compatibility profile reused by A0.2."""

from __future__ import annotations

import hashlib
import json
import platform
import re
import subprocess
import sys
import sysconfig
from typing import Any

PROFILE: dict[str, Any] = {
    "id": "RES541_A01_CPYTHON313_T4_V1",
    "active": True,
    "candidate_python_patches": ["3.13.15", "3.13.16", "3.13.17", "3.13.18"],
    "approved_python_patches": ["3.13.15", "3.13.16", "3.13.17", "3.13.18"],
    "independent_review": {
        "identity": "coderabbitai[bot]",
        "evidence": "https://github.com/Litju/DynamisLM/pull/46#pullrequestreview-5677323707",
    },
    "owner_approval": {
        "identity": "Litju",
        "evidence": "https://github.com/Litju/DynamisLM/pull/46#issuecomment-6458914435",
    },
    "requirements": {
        "implementation": "CPython",
        "python_final_release_pattern": r"3\.13\.(?:0|[1-9][0-9]*)",
        "system": "Linux",
        "machine": "x86_64",
        "soabi": "cpython-313-x86_64-linux-gnu",
        "gil_disabled": False,
        "gil_enabled": True,
        "debug_build": False,
        "torch": "2.11.0+cu130",
        "torch_cuda_runtime": "13.0",
        "gpu_name": "Tesla T4",
        "compute_capability": [7, 5],
        "device_count": 1,
        "weight_dtype": "float16",
    },
}


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def binding() -> dict[str, str]:
    return {"runtime_profile_id": PROFILE["id"], "runtime_profile_sha256": digest(PROFILE)}


def require_approval() -> None:
    review, owner = PROFILE["independent_review"], PROFILE["owner_approval"]
    if (
        PROFILE["active"] is not True
        or not isinstance(PROFILE["approved_python_patches"], list)
        or not PROFILE["approved_python_patches"]
        or any(
            not isinstance(v, str)
            or re.fullmatch(r"3\.13\.(?:0|[1-9][0-9]*)", v) is None
            or v not in PROFILE["candidate_python_patches"]
            for v in PROFILE["approved_python_patches"]
        )
        or not isinstance(review, dict)
        or not isinstance(owner, dict)
        or any(
            not isinstance(record.get(key), str) or not record[key].strip()
            for record in (review, owner)
            for key in ("identity", "evidence")
        )
        or review["identity"] == owner["identity"]
    ):
        raise ValueError("runtime profile inactive or independent review/owner approval missing")


def inventory() -> dict[str, Any]:
    """Read actual metadata before setup; missing observations remain explicit failures."""
    observed: dict[str, Any] = {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "python_build": list(platform.python_build()),
        "python_compiler": platform.python_compiler(),
        "python_full_version": sys.version,
        "python_executable": sys.executable,
        "soabi": sysconfig.get_config_var("SOABI"),
        "gil_disabled": bool(sysconfig.get_config_var("Py_GIL_DISABLED"))
        if type(sysconfig.get_config_var("Py_GIL_DISABLED")) is int
        else None,
        "gil_enabled": getattr(sys, "_is_gil_enabled", lambda: None)(),
        "debug_build": bool(sysconfig.get_config_var("Py_DEBUG"))
        if type(sysconfig.get_config_var("Py_DEBUG")) is int
        else None,
        "system": platform.system(),
        "machine": platform.machine(),
        "weight_dtype": "float16",
    }
    try:
        import torch  # type: ignore[import-not-found]

        observed.update(torch=str(torch.__version__), torch_cuda_runtime=torch.version.cuda)
        observed["device_count"] = torch.cuda.device_count()
        properties = torch.cuda.get_device_properties(0)
        observed.update(
            gpu_name=properties.name,
            compute_capability=list(torch.cuda.get_device_capability(0)),
            total_vram_bytes=int(properties.total_memory),
            gpu_uuid=str(properties.uuid) if properties.uuid is not None else None,
        )
        observed["driver_inventory"] = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=uuid,driver_version,name", "--format=csv,noheader"],
            text=True,
            timeout=10,
        ).strip()
    except Exception as exc:
        observed["inventory_error"] = type(exc).__name__
    return observed


def qualify(observed: dict[str, Any], *, approved: bool = True) -> None:
    if approved:
        require_approval()
    requirements = dict(PROFILE["requirements"])
    pattern = requirements.pop("python_final_release_pattern")
    if (
        not isinstance(observed.get("python"), str)
        or re.fullmatch(pattern, observed["python"]) is None
        or observed["python"] not in PROFILE["candidate_python_patches"]
        or any(
            type(observed.get(key)) is not type(value) or observed[key] != value
            for key, value in requirements.items()
        )
        or "inventory_error" in observed
        or not isinstance(observed.get("python_build"), list)
        or len(observed["python_build"]) != 2
        or any(not isinstance(v, str) or not v.strip() for v in observed["python_build"])
        or any(
            not isinstance(observed.get(key), str) or not observed[key].strip()
            for key in (
                "python_compiler",
                "python_full_version",
                "python_executable",
                "gpu_uuid",
                "driver_inventory",
            )
        )
        or type(observed.get("total_vram_bytes")) is not int
        or observed["total_vram_bytes"] < 12 * 1024**3
        or (approved and observed["python"] not in PROFILE["approved_python_patches"])
    ):
        raise ValueError("RUNTIME_INCOMPATIBLE")
