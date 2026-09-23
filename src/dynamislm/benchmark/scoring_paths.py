"""Reachable scorer-error paths for a single benchmark case."""

from __future__ import annotations

from dynamislm.benchmark.constants import ErrorClass, RefusalDecision, ScoringProfile
from dynamislm.benchmark.contracts import ScoringContract


def reachable_error_attributions(
    contract: ScoringContract,
    *,
    refusal_decision: RefusalDecision,
    prohibited_claims: tuple[str, ...],
) -> tuple[tuple[str, ErrorClass], ...]:
    """Return error-class mappings that a real scorer branch can emit."""

    if contract.profile_id is ScoringProfile.CALIBRATION_V1:
        return ()

    attribution = dict(contract.error_attribution)
    keys = list(contract.required_output_fields)
    if refusal_decision is RefusalDecision.REQUIRED:
        keys.append("__decision__")
    if refusal_decision in {RefusalDecision.REQUIRED, RefusalDecision.ALLOWED}:
        keys.append("__refusal__")
    if refusal_decision is RefusalDecision.PROHIBITED:
        keys.append("__over_refusal__")
    if prohibited_claims:
        keys.append("__prohibited_claim__")

    default = attribution.get("__default__")
    return tuple(
        (key, error_class)
        for key in keys
        if (error_class := attribution.get(key, default)) is not None
    )


def reachable_error_classes(
    contract: ScoringContract,
    *,
    refusal_decision: RefusalDecision,
    prohibited_claims: tuple[str, ...],
) -> frozenset[ErrorClass]:
    """Return the distinct error classes emitted by reachable scorer paths."""

    return frozenset(
        error_class
        for _, error_class in reachable_error_attributions(
            contract,
            refusal_decision=refusal_decision,
            prohibited_claims=prohibited_claims,
        )
    )


__all__ = ["reachable_error_attributions", "reachable_error_classes"]
