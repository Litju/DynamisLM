from __future__ import annotations

import pytest
from scripts.res426_verifier import generate_verifier_cases

from dynamislm.qualification.references import RES71_SEALED_REFERENCE_DIGEST


def test_verifier_generator_is_reproducible_and_keeps_reference_provenance() -> None:
    first = generate_verifier_cases()
    second = generate_verifier_cases()

    assert first == second
    assert len(first) == 12
    assert all(task.synthetic is True for task in first)
    assert all(task.source_digest == RES71_SEALED_REFERENCE_DIGEST for task in first)
    assert all(task.generator_schema == "RES426_VERIFIER_CASES_V1" for task in first)


def test_verifier_generator_selects_known_cases_in_sealed_order() -> None:
    all_cases = generate_verifier_cases()
    selected = generate_verifier_cases(
        ("res71-same-label-different-method", "res71-external-unit-km-to-m")
    )

    assert selected == (all_cases[0], all_cases[-3])
    with pytest.raises(ValueError, match="duplicates"):
        generate_verifier_cases(("res71-external-unit-km-to-m", "res71-external-unit-km-to-m"))
    with pytest.raises(ValueError, match="unregistered"):
        generate_verifier_cases(("invented-case",))
