"""A0.1-only inactive compatibility profile and audited frozen-gate adapter."""

from __future__ import annotations

import ast
import hashlib
import json
import platform
import re
import subprocess
import sys
import sysconfig
from pathlib import Path
from types import ModuleType
from typing import Any

VERSION = "RES541_A01_EXECUTION_V2"
PROFILE: dict[str, Any] = {
    "id": "RES541_A01_CPYTHON313_T4_V1",
    "active": False,
    "candidate_python_patches": ["3.13.15", "3.13.16", "3.13.17", "3.13.18"],
    "approved_python_patches": [],
    "independent_review": None,
    "owner_approval": None,
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
FROZEN = {
    "a0_colab_entry": "3150cba8d6f75092e928eb207bad12dbb360b36614289609b931b6d77bcbb123",
    "a0_colab_inference": "e168998219c0944bcac305855b341637fc728f81880a0f515200188fd46792f5",
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


def agree(before: dict[str, Any], after: dict[str, Any]) -> None:
    qualify(before)
    qualify(after)
    # The child venv has its own executable; all interpreter/build/GPU observations must agree.
    keys = set(before) | set(after)
    if any(before.get(k) != after.get(k) for k in keys - {"python_executable"}):
        raise ValueError("bootstrap/inference runtime inventory mismatch")


def adapt_gate(module: ModuleType, name: str, source: bytes, check: Any) -> None:
    """Replace exactly one frozen Python comparison, in a private module only."""
    if hashlib.sha256(source).hexdigest() != FROZEN[name]:
        raise ValueError("frozen runtime gate SHA-256 mismatch")
    tree = ast.parse(source)
    function = "_preflight" if name == "a0_colab_entry" else "run_inference"
    gates = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == function]
    if len(gates) != 1:
        raise ValueError("frozen runtime gate function drift")
    matches = [
        n
        for n in ast.walk(gates[0])
        if isinstance(n, ast.Compare)
        and ast.dump(n)
        == ast.dump(ast.parse('platform.python_version() != "3.13.15"', mode="eval").body)
    ]
    if len(matches) != 1:
        raise ValueError("frozen runtime comparison drift")
    matches[0].left = ast.Call(
        func=ast.Name(id="_a01_runtime_check", ctx=ast.Load()), args=[], keywords=[]
    )
    matches[0].ops = [ast.IsNot()]
    matches[0].comparators = [ast.Constant(value=True)]
    module.__dict__["_a01_runtime_check"] = check
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=[gates[0]], type_ignores=[])),
            str(module.__file__),
            "exec",
        ),
        module.__dict__,
    )


def immutable(path: Path, document: dict[str, Any]) -> None:
    with path.open("x") as stream:
        stream.write(json.dumps(document, indent=2, sort_keys=True) + "\n")
