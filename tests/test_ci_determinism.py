from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

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
