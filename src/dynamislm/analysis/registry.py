"""Canonical RES-70 analysis-capability matrix above RES-69."""

from __future__ import annotations

from dataclasses import dataclass

from dynamislm.analysis.models import (
    AnalysisCapability,
    AnalysisCapabilityDisposition,
    AnalysisClass,
    AnalysisEstimandLevel,
)
from dynamislm.comparability.models import ComparabilityState
from dynamislm.longitudinal.statistics.registry import (
    MIXED_EFFECTS,
    REPEATED_MEASURES_CORRELATION,
    RES69_ABSOLUTE_CHANGE_ESTIMATOR,
    RES69_ABSOLUTE_CHANGE_OPERATION,
    RES69_LOG_RATIO_ESTIMATOR,
    RES69_LOG_RATIO_OPERATION,
    RES69_METHOD_COMPARISON_DESIGN_OPERATION,
    RES69_METHOD_COMPARISON_OPERATION,
    RES69_REFERENCE_WINDOW_DEVIATION_OPERATION,
    RES69_REFERENCE_Z_ESTIMATOR,
    RES69_RELATIVE_CHANGE_ESTIMATOR,
    RES69_RELATIVE_CHANGE_OPERATION,
    RES69_RELIABILITY_ASSUMPTION_ASSESSMENT_OPERATION,
    RES69_RELIABILITY_DESIGN_OPERATION,
    RES69_SCALE_SEMANTICS_AUTHORITY,
    RES69_TWO_REPLICATE_RANDOM_ERROR_OPERATION,
)
from dynamislm.measurement.identity import (
    RegistryReference,
    ScientificIdentifier,
    _require_instance,
    _require_text,
    _require_tuple_items,
    require_tuple,
)
from dynamislm.serialization import canonical_hash, register_serializable_type

RES70_ANALYSIS_REGISTRY_VERSION = "1.0.0"


def _reference(key: str, label: str) -> RegistryReference:
    return RegistryReference(
        ScientificIdentifier(
            "dynamislm",
            "analysis-capability",
            key,
            RES70_ANALYSIS_REGISTRY_VERSION,
        ),
        label,
    )


def _capability(
    key: str,
    analysis_class: AnalysisClass,
    *,
    operation: RegistryReference | None,
    estimator: RegistryReference | None,
    disposition: AnalysisCapabilityDisposition,
    support_shape: tuple[str, ...],
    level: tuple[AnalysisEstimandLevel, ...],
    authority: tuple[RegistryReference, ...] = (),
    evidence_axes: tuple[str, ...] = (),
    context: tuple[str, ...] = (),
    claim_floor: str | None,
) -> AnalysisCapability:
    return AnalysisCapability(
        capability_reference=_reference(key, key.replace("_", " ").title()),
        analysis_class=analysis_class,
        registered_operation_reference=operation,
        estimator_reference=estimator,
        disposition=disposition,
        required_support_shape=support_shape,
        required_identity_dimensions=("CONSTRUCT", "MEASURAND", "METRIC_DEFINITION", "UNIT"),
        required_comparability_states=(
            ComparabilityState.COMPARABLE,
            ComparabilityState.COMPARABLE_WITH_CONDITIONS,
        ),
        required_bridge_execution=False,
        required_level_of_analysis=level,
        required_statistical_authority=authority,
        required_evidence_axes=evidence_axes,
        required_context=context,
        output_claim_floor=claim_floor,
        registry_version=RES70_ANALYSIS_REGISTRY_VERSION,
    )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class AnalysisCapabilityRegistry:
    entries: tuple[AnalysisCapability, ...]
    registry_version: str = RES70_ANALYSIS_REGISTRY_VERSION
    registry_hash: str | None = None

    def __post_init__(self) -> None:
        require_tuple(self.entries, "entries")
        _require_tuple_items(self.entries, AnalysisCapability, "entries")
        _require_text(self.registry_version, "registry_version")
        refs = tuple(item.capability_reference.stable_id for item in self.entries)
        classes = tuple(item.analysis_class.value for item in self.entries)
        if len(set(refs)) != len(refs) or len(set(classes)) != len(classes):
            raise ValueError("RES70 capability registry cannot contain duplicate entries")
        if any(item.registry_version != self.registry_version for item in self.entries):
            raise ValueError("capability and registry versions must match")
        expected = canonical_hash(
            {"entries": self.entries, "registry_version": self.registry_version}
        )
        if self.registry_hash is None:
            object.__setattr__(self, "registry_hash", expected)
        elif self.registry_hash != expected:
            raise ValueError("capability registry hash does not match immutable entries")

    def resolve(self, analysis_class: AnalysisClass) -> AnalysisCapability | None:
        if not isinstance(analysis_class, AnalysisClass):
            raise ValueError("analysis_class must be an AnalysisClass")
        matches = tuple(item for item in self.entries if item.analysis_class is analysis_class)
        if len(matches) > 1:
            raise ValueError("RES70_REGISTRY_INTEGRITY_FAILURE: duplicate analysis capability")
        return matches[0] if matches else None

    def resolve_reference(self, reference: RegistryReference) -> AnalysisCapability | None:
        _require_instance(reference, RegistryReference, "reference")
        matches = tuple(
            item
            for item in self.entries
            if item.capability_reference.stable_id == reference.stable_id
        )
        if len(matches) > 1:
            raise ValueError("RES70_REGISTRY_INTEGRITY_FAILURE: duplicate capability reference")
        return matches[0] if matches else None

    @property
    def canonical_hash(self) -> str:
        assert self.registry_hash is not None
        return self.registry_hash


RES70_CAPABILITIES = (
    _capability(
        "scalar_absolute_change",
        AnalysisClass.SCALAR_ABSOLUTE_CHANGE,
        operation=RES69_ABSOLUTE_CHANGE_OPERATION,
        estimator=RES69_ABSOLUTE_CHANGE_ESTIMATOR,
        disposition=AnalysisCapabilityDisposition.IMPLEMENTED,
        support_shape=("exactly-two-scalar-entries",),
        level=(AnalysisEstimandLevel.WITHIN_ATHLETE,),
        claim_floor="NUMERICAL_CHANGE",
    ),
    _capability(
        "scalar_relative_change",
        AnalysisClass.SCALAR_RELATIVE_CHANGE,
        operation=RES69_RELATIVE_CHANGE_OPERATION,
        estimator=RES69_RELATIVE_CHANGE_ESTIMATOR,
        disposition=AnalysisCapabilityDisposition.IMPLEMENTED,
        support_shape=("exactly-two-scalar-entries", "nonzero-denominator"),
        level=(AnalysisEstimandLevel.WITHIN_ATHLETE,),
        authority=(RES69_SCALE_SEMANTICS_AUTHORITY,),
        claim_floor="NUMERICAL_CHANGE",
    ),
    _capability(
        "scalar_log_change",
        AnalysisClass.SCALAR_LOG_CHANGE,
        operation=RES69_LOG_RATIO_OPERATION,
        estimator=RES69_LOG_RATIO_ESTIMATOR,
        disposition=AnalysisCapabilityDisposition.IMPLEMENTED,
        support_shape=("exactly-two-scalar-entries", "strictly-positive-values"),
        level=(AnalysisEstimandLevel.WITHIN_ATHLETE,),
        authority=(RES69_SCALE_SEMANTICS_AUTHORITY,),
        claim_floor="NUMERICAL_CHANGE",
    ),
    _capability(
        "baseline_reference_window_deviation",
        AnalysisClass.BASELINE_REFERENCE_WINDOW_DEVIATION,
        operation=RES69_REFERENCE_WINDOW_DEVIATION_OPERATION,
        estimator=RES69_REFERENCE_Z_ESTIMATOR,
        disposition=AnalysisCapabilityDisposition.IMPLEMENTED,
        support_shape=(
            "one-current-entry",
            "at-least-two-reference-entries",
            "positive-reference-sd",
        ),
        level=(AnalysisEstimandLevel.WITHIN_ATHLETE,),
        claim_floor="NUMERICAL_CHANGE",
    ),
    _capability(
        "reliability_random_error_comparison",
        AnalysisClass.RELIABILITY_RANDOM_ERROR_COMPARISON,
        operation=RES69_TWO_REPLICATE_RANDOM_ERROR_OPERATION,
        estimator=None,
        disposition=AnalysisCapabilityDisposition.IMPLEMENTED,
        support_shape=("two-replicate-pairs",),
        level=(AnalysisEstimandLevel.WITHIN_ATHLETE,),
        authority=(
            RES69_RELIABILITY_DESIGN_OPERATION,
            RES69_RELIABILITY_ASSUMPTION_ASSESSMENT_OPERATION,
        ),
        evidence_axes=("METHOD_VALIDITY", "STATISTICAL_ADEQUACY"),
        claim_floor="CHANGE_RELATIVE_TO_MEASUREMENT_ERROR",
    ),
    _capability(
        "method_agreement_summary",
        AnalysisClass.METHOD_AGREEMENT_SUMMARY,
        operation=RES69_METHOD_COMPARISON_OPERATION,
        estimator=None,
        disposition=AnalysisCapabilityDisposition.IMPLEMENTED,
        support_shape=("one-pair-per-independent-subject",),
        level=(AnalysisEstimandLevel.WITHIN_ATHLETE,),
        authority=(RES69_METHOD_COMPARISON_DESIGN_OPERATION,),
        evidence_axes=("METHOD_VALIDITY", "STATISTICAL_ADEQUACY"),
        claim_floor="ASSOCIATION",
    ),
    _capability(
        "within_athlete_association",
        AnalysisClass.WITHIN_ATHLETE_ASSOCIATION,
        operation=REPEATED_MEASURES_CORRELATION,
        estimator=None,
        disposition=AnalysisCapabilityDisposition.DEFERRED,
        support_shape=("repeated-observations",),
        level=(AnalysisEstimandLevel.WITHIN_ATHLETE,),
        claim_floor="ASSOCIATION",
    ),
    _capability(
        "between_athlete_association",
        AnalysisClass.BETWEEN_ATHLETE_ASSOCIATION,
        operation=None,
        estimator=None,
        disposition=AnalysisCapabilityDisposition.REJECTED,
        support_shape=("one-independent-unit-per-athlete",),
        level=(AnalysisEstimandLevel.BETWEEN_ATHLETE,),
        claim_floor="ASSOCIATION",
    ),
    _capability(
        "repeated_measures_analysis",
        AnalysisClass.REPEATED_MEASURES_ANALYSIS,
        operation=REPEATED_MEASURES_CORRELATION,
        estimator=None,
        disposition=AnalysisCapabilityDisposition.DEFERRED,
        support_shape=("repeated-observations", "explicit-clustering"),
        level=(AnalysisEstimandLevel.WITHIN_ATHLETE, AnalysisEstimandLevel.JOINT_MULTILEVEL),
        claim_floor="ASSOCIATION",
    ),
    _capability(
        "mixed_effects_analysis",
        AnalysisClass.MIXED_EFFECTS_ANALYSIS,
        operation=MIXED_EFFECTS,
        estimator=None,
        disposition=AnalysisCapabilityDisposition.DEFERRED,
        support_shape=("repeated-observations", "explicit-random-effects"),
        level=(AnalysisEstimandLevel.JOINT_MULTILEVEL,),
        claim_floor="ASSOCIATION",
    ),
    _capability(
        "cross_test_association",
        AnalysisClass.CROSS_TEST_ASSOCIATION,
        operation=None,
        estimator=None,
        disposition=AnalysisCapabilityDisposition.REJECTED,
        support_shape=("distinct-test-identities", "temporal-or-lag-policy"),
        level=(AnalysisEstimandLevel.WITHIN_ATHLETE, AnalysisEstimandLevel.BETWEEN_ATHLETE),
        claim_floor="ASSOCIATION",
    ),
)

RES70_CAPABILITY_REGISTRY = AnalysisCapabilityRegistry(entries=RES70_CAPABILITIES)
CANONICAL_ANALYSIS_CAPABILITY_REGISTRY = RES70_CAPABILITY_REGISTRY


def is_canonical_analysis_registry(registry: AnalysisCapabilityRegistry) -> bool:
    return registry is CANONICAL_ANALYSIS_CAPABILITY_REGISTRY


__all__ = [
    "CANONICAL_ANALYSIS_CAPABILITY_REGISTRY",
    "RES70_ANALYSIS_REGISTRY_VERSION",
    "RES70_CAPABILITIES",
    "RES70_CAPABILITY_REGISTRY",
    "AnalysisCapabilityRegistry",
    "is_canonical_analysis_registry",
]
