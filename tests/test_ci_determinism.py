from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

_HASH_SEED_HELPER = """
from dynamislm import (
    RegistryReference,
    ScalarValue,
    ScientificClassification,
    ScientificIdentifier,
    ScientificRole,
    ValueOrigin,
    canonical_hash,
)

identifier = ScientificIdentifier("dynamislm", "sentinel", "hash-seed", "1.0.0")
registry = RegistryReference(identifier, "hash-seed sentinel")
classification = ScientificClassification(
    ValueOrigin.DERIVED_MECHANICAL_QUANTITY,
    tuple({ScientificRole.PERFORMANCE_OUTCOME, ScientificRole.PHYSIOLOGICAL_INFERENCE}),
)
primitive = dict({("beta", ScalarValue(2.0)), ("alpha", ScalarValue(1.0))})
objects = (
    ("identifier", identifier),
    ("registry", registry),
    ("classification", classification),
    ("primitive", primitive),
)
for name, value in objects:
    print(f"{name}={canonical_hash(value)}")
"""


def _hashes_for_seed(repo_root: Path, seed: str) -> tuple[str, ...]:
    environment = os.environ.copy()
    environment["PYTHONHASHSEED"] = seed
    source_path = str(repo_root / "src")
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        source_path
        if not existing_pythonpath
        else os.pathsep.join((source_path, existing_pythonpath))
    )
    result = subprocess.run(
        [sys.executable, "-c", _HASH_SEED_HELPER],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    return tuple(result.stdout.strip().splitlines())


def test_canonical_hashes_are_independent_of_python_hash_seed() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    hashes_seed_1 = _hashes_for_seed(repo_root, "1")
    hashes_seed_92731 = _hashes_for_seed(repo_root, "92731")

    assert hashes_seed_1
    assert hashes_seed_1 == hashes_seed_92731


def test_setup_uv_cache_is_explicitly_disabled() -> None:
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml").read_text()
    blocks = workflow.split("uses: astral-sh/setup-uv@")[1:]
    assert len(blocks) == 2  # the mission job and the QA shard job
    assert all('enable-cache: "false"' in b[: b.index("\n      - name:")] for b in blocks)


def test_required_ci_check_needs_every_job_and_every_shard() -> None:
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml").read_text()
    body = workflow[workflow.index("\njobs:\n") :].splitlines()
    jobs = [line[2:-1] for line in body if re.fullmatch(r"  [a-z]+:", line)]
    assert jobs == ["mission", "qa", "ci"]
    required = workflow[workflow.index("\n  ci:\n") :]
    assert "    name: ci\n" in required and "    if: ${{ always() }}\n" in required
    assert "    needs: [mission, qa]\n" in required
    assert 'test "$MISSION_RESULT" = success' in required
    assert 'test "$QA_RESULT" = success' in required
    assert "      fail-fast: false\n" in workflow
    assert "        shard: [fast, controller, integration]\n" in workflow
    assert './scripts/ci-shard.sh "${{ matrix.shard }}"' in workflow


def test_required_ci_shards_partition_every_test_module_exactly_once(
    tmp_path: Path, monkeypatch: Any
) -> None:
    import pytest
    from scripts import test_shards

    shards = test_shards.partition()
    flat = [name for files in shards.values() for name in files]
    assert sorted(flat) == test_shards.modules() and len(flat) == len(set(flat))
    assert set(shards) == {"fast", "controller", "integration"} and all(shards.values())
    # The full-scale integrity test and the real-child integration stay in a required shard.
    assert "test_res541_a02_v3_execution.py" in shards["integration"]

    (tmp_path / "tests").mkdir()
    for name in [*test_shards.modules(), "test_new_module.py"]:
        (tmp_path / "tests" / name).touch()
    assert "test_new_module.py" in test_shards.partition(tmp_path)["fast"]  # never unowned
    (tmp_path / "tests" / "test_res541_a02_v3_execution.py").unlink()
    with pytest.raises(ValueError, match="missing"):
        test_shards.partition(tmp_path)  # a listed module that vanished is not ignored
    shared = test_shards.INTEGRATION[0]
    monkeypatch.setitem(test_shards.SHARDS, "controller", (*test_shards.CONTROLLER, shared))
    with pytest.raises(ValueError, match="duplicated"):
        test_shards.partition()  # one module in two jobs would hide nothing but is ambiguous
