"""Deterministic RES-426 verifier utilities over the sealed RES-71 reference set."""

from __future__ import annotations

from dataclasses import dataclass

from dynamislm.qualification.contracts import ReferenceCase
from dynamislm.qualification.references import get_reference_cases, reference_case_digest

VERIFIER_GENERATOR_SCHEMA = "RES426_VERIFIER_CASES_V1"


@dataclass(frozen=True, slots=True)
class GeneratedVerifierCase:
    """One synthetic verifier task bound to the sealed RES-71 reference set."""

    case: ReferenceCase
    source_digest: str
    generator_schema: str = VERIFIER_GENERATOR_SCHEMA
    synthetic: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.case, ReferenceCase):
            raise ValueError("generated verifier case must retain its typed reference case")
        if not isinstance(self.source_digest, str) or not self.source_digest.startswith("sha256:"):
            raise ValueError("generated verifier case requires a source digest")


def generate_verifier_cases(
    case_ids: tuple[str, ...] | None = None,
) -> tuple[GeneratedVerifierCase, ...]:
    """Generate reproducible synthetic tasks from the immutable RES-71 cases."""
    cases = get_reference_cases()
    digest = reference_case_digest(cases)
    if case_ids is None:
        selected = {case.case_id for case in cases}
    else:
        if not isinstance(case_ids, tuple) or any(
            not isinstance(case_id, str) or not case_id.strip() for case_id in case_ids
        ):
            raise ValueError("case_ids must be a tuple of non-empty case IDs")
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("case_ids must not contain duplicates")
        selected = set(case_ids)
        unknown = selected - {case.case_id for case in cases}
        if unknown:
            raise ValueError(f"unregistered verifier case IDs: {sorted(unknown)}")
    return tuple(
        GeneratedVerifierCase(case=case, source_digest=digest)
        for case in cases
        if case.case_id in selected
    )


__all__ = ["VERIFIER_GENERATOR_SCHEMA", "GeneratedVerifierCase", "generate_verifier_cases"]
