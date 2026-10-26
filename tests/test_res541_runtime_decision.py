"""CPU-only tests of an inactive review proposal, not permission to launch."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
DECISION = json.loads((ROOT / "experiments/a01/runtime-decision-v1.json").read_text())


@pytest.mark.parametrize(
    ("changes", "candidate"),
    [
        ({}, True),
        ({"python": "3.13.14"}, True),
        ({"python": "3.13.16"}, True),
        ({"python": None}, False),
        ({"python": "UNKNOWN"}, False),
        ({"python": "3.12.13"}, False),
        ({"python": "3.14.0"}, False),
        ({"python": "3.13.16rc1"}, False),
        ({"python": "3.13.015"}, False),
        ({"implementation": "PyPy"}, False),
        ({"gil_disabled": True}, False),
        ({"debug_build": True}, False),
        ({"soabi": "cpython-313t-x86_64-linux-gnu"}, False),
        ({"torch": None}, False),
        ({"torch": "2.11.0"}, False),
        ({"torch": "2.11.1+cu130"}, False),
        ({"torch_cuda_runtime": None}, False),
        ({"torch_cuda_runtime": "12.8"}, False),
        ({"gpu_name": "NVIDIA A100"}, False),
        ({"compute_capability": [8, 0]}, False),
        ({"device_count": 2}, False),
        ({"device_count": True}, False),
        ({"gil_disabled": 0}, False),
        ({"soabi": None}, False),
        ({"weight_dtype": "bfloat16"}, False),
    ],
)
def test_inactive_candidate_matrix(changes: dict[str, Any], candidate: bool) -> None:
    # Executable review specification only; no production caller consumes this decision.
    spec = dict(DECISION["candidate_screen"])
    pattern = spec.pop("python_final_release_pattern")
    observed = {**spec, "python": "3.13.15", **changes}
    matches = (
        isinstance(observed["python"], str)
        and re.fullmatch(pattern, observed["python"]) is not None
        and all(
            type(observed[key]) is type(value) and observed[key] == value
            for key, value in spec.items()
        )
    )
    assert matches is candidate
    assert DECISION["approved"] is False and DECISION["active"] is False
    assert DECISION["approved_python_patches"] == []
    assert DECISION["candidate_screen_is_launch_authority"] is False


@pytest.mark.parametrize(
    ("script", "function"),
    [("a0_colab_entry.py", "_preflight"), ("a0_colab_inference.py", "run_inference")],
)
def test_both_frozen_gates_still_require_original_versions(script: str, function: str) -> None:
    tree = ast.parse((ROOT / "scripts" / script).read_text())
    gate = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == function
    )
    comparisons = {
        ast.unparse(node.left): [ast.literal_eval(right) for right in node.comparators]
        for node in ast.walk(gate)
        if isinstance(node, ast.Compare)
        and ast.unparse(node.left) in {"platform.python_version()", "str(torch.__version__)"}
    }
    assert comparisons == {
        "platform.python_version()": ["3.13.15"],
        "str(torch.__version__)": ["2.11.0+cu130"],
    }
    assert DECISION["status"] == "BLOCKED_RUNTIME_VERSION_UNKNOWN"
    assert all(
        DECISION[key] is None
        for key in ("failed_attempt_python", "failed_attempt_torch", "failed_attempt_cuda")
    )
