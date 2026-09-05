"""Explicit CMJ trial selection, scalar session aggregation, and comparability.

RES-40 deliberately keeps four concerns separate: the declared candidate set,
per-trial eligibility, the selection decision, and the resulting session
observation.  The module consumes the typed RES-34--RES-49 objects and does
not implement another CMJ detector, estimator, phase system, or mechanics
operation.
"""

from __future__ import annotations

import datetime as datetime_module
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

from dynamislm.comparability.models import (
    ComparabilityDecisionSource,
    ComparabilityReasonCode,
    ComparabilityResult,
    ComparabilityState,
)
from dynamislm.measurement.cmj.comparability import compare_cmj_measurement_identities
from dynamislm.measurement.cmj.identity import (
    CMJ_TEST_FAMILY,
    CMJMeasurementIdentity,
)
from dynamislm.measurement.cmj.jump_height import (
    CMJJumpHeightResult,
    compare_cmj_jump_height_estimates,
)
from dynamislm.measurement.cmj.mechanics import (
    NetVerticalForceResult,
    NetVerticalImpulseResult,
    SupportedSystemComAccelerationResult,
    SupportedSystemComRelativeDisplacementResult,
    SupportedSystemComVelocityResult,
    compare_cmj_mechanics,
)
from dynamislm.measurement.cmj.phases import (
    CMJPhaseMetricResult,
    _phase_metric_method_key,
    compare_cmj_phase_metrics,
)
from dynamislm.measurement.cmj.registry import (
    CMJ_ARITHMETIC_MEAN_V1,
    CMJ_EXPLICIT_TRIAL_EXCLUSION_POLICY_V1,
    CMJ_SELECT_ALL_DECLARED_ELIGIBLE_V1,
    CMJ_SELECT_EXTREME_BY_REGISTERED_METRIC_V1,
    CMJ_SELECTED_SINGLE_TRIAL_PROJECTION_V1,
    CMJ_SESSION_AGGREGATION_OPERATION,
    CMJ_SESSION_COMPARABILITY_RULE,
    CMJ_TIE_EARLIEST_DECLARED_CANDIDATE_V1,
    RES40_DECISION_SESSION_AGGREGATION,
    RES40_DECISION_SESSION_COMPARABILITY,
    RES40_DECISION_TRIAL_SELECTION,
)
from dynamislm.measurement.cmj.signal import ExplicitTimebase, RegularTimebase, SignalTimebase
from dynamislm.measurement.cmj.weighing import (
    PhysicalSystemMassResult,
    StandardGravityMassEquivalentResult,
    SystemWeightResult,
    compare_cmj_derived_measurements,
)
from dynamislm.measurement.identity import (
    InstanceIdentifier,
    MetadataEntry,
    RegistryReference,
    ScientificIdentifier,
    UnitReference,
    VersionIdentity,
    require_tuple,
)
from dynamislm.measurement.observation import (
    ObservationContext,
    ScientificMeasurementObservation,
)
from dynamislm.measurement.result import (
    MeasurementQuality,
    MeasurementResult,
    QualityStatus,
    ResultStatus,
    ScalarValue,
    UncertaintyMetadata,
    UncertaintyStatus,
)
from dynamislm.measurement.taxonomy import ScientificClassification
from dynamislm.provenance.models import (
    AcquisitionRecord,
    EvidenceReference,
    LineageEdge,
    LineageRelation,
    ProcessingRun,
    Provenance,
    SourceArtifact,
)
from dynamislm.refusal.models import (
    RefusalClass,
    RefusalReasonCode,
    RefusalResult,
    RefusalStatus,
)
from dynamislm.serialization import canonical_hash, canonical_json, register_serializable_type

RES40_SOFTWARE_VERSION = "dynamislm-res40-1.0.0"
_UNCERTAINTY_DESCRIPTION = (
    "RES-40 deterministic session selection/aggregation; no measurement-error or "
    "reliability analysis is assessed."
)


class TrialEligibilityStatus(StrEnum):
    """The only V1 statuses for a declared candidate trial."""

    ELIGIBLE = "ELIGIBLE"
    EXCLUDED = "EXCLUDED"
    UNRESOLVED = "UNRESOLVED"


class TrialSelectionDirection(StrEnum):
    """Explicit direction for a registered extreme-ranking rule."""

    MAXIMIZE = "MAXIMIZE"
    MINIMIZE = "MINIMIZE"


RankingDirection = TrialSelectionDirection


@register_serializable_type
@dataclass(frozen=True, slots=True)
class DeclaredCandidateTrialSet:
    """An ordered, session-bound set of candidate trial identities."""

    athlete_id: InstanceIdentifier
    session_id: InstanceIdentifier
    test_family: RegistryReference
    trial_ids: tuple[InstanceIdentifier, ...]
    candidate_observation_ids: tuple[InstanceIdentifier, ...]

    def __post_init__(self) -> None:
        require_tuple(self.trial_ids, "trial_ids")
        require_tuple(self.candidate_observation_ids, "candidate_observation_ids")
        if self.athlete_id.instance_type != "athlete":
            raise ValueError("athlete_id must identify an athlete")
        if self.session_id.instance_type != "session":
            raise ValueError("session_id must identify a session")
        if not self.trial_ids:
            raise ValueError("declared candidate trial set must not be empty")
        if len(self.trial_ids) != len(self.candidate_observation_ids):
            raise ValueError("trial IDs and candidate observation IDs must be aligned")
        if len(set(self.trial_ids)) != len(self.trial_ids):
            raise ValueError("declared candidate trial IDs must be distinct")
        if len(set(self.candidate_observation_ids)) != len(self.candidate_observation_ids):
            raise ValueError("candidate observation IDs must be distinct")
        for trial_id in self.trial_ids:
            if trial_id.instance_type != "trial":
                raise ValueError("candidate trial IDs must identify trials")
        for observation_id in self.candidate_observation_ids:
            if observation_id.instance_type != "observation":
                raise ValueError("candidate observation IDs must identify observations")
        if self.test_family.stable_id != CMJ_TEST_FAMILY.stable_id:
            raise ValueError("RES-40 currently registers only the CMJ test family")

    @property
    def candidate_trial_ids(self) -> tuple[InstanceIdentifier, ...]:
        """Alias that makes the ordered candidate semantics explicit."""

        return self.trial_ids

    @property
    def declared_candidate_count(self) -> int:
        return len(self.trial_ids)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class TrialEligibilityDecision:
    """One explicit eligibility disposition for one declared candidate."""

    trial_id: InstanceIdentifier
    status: TrialEligibilityStatus
    observation_ids: tuple[InstanceIdentifier, ...]
    reason: str | None = None
    exclusion_policy: RegistryReference | None = None

    def __post_init__(self) -> None:
        require_tuple(self.observation_ids, "observation_ids")
        if self.trial_id.instance_type != "trial":
            raise ValueError("eligibility trial_id must identify a trial")
        if not isinstance(self.status, TrialEligibilityStatus):
            raise ValueError("eligibility status must be registered")
        if any(item.instance_type != "observation" for item in self.observation_ids):
            raise ValueError("eligibility observation IDs must identify observations")
        if self.status is TrialEligibilityStatus.ELIGIBLE and not self.observation_ids:
            raise ValueError("eligible trials must preserve at least one observation ID")
        if self.status is TrialEligibilityStatus.EXCLUDED:
            if self.exclusion_policy is None:
                raise ValueError("excluded trials require a registered exclusion policy")
            if not self.observation_ids:
                raise ValueError("excluded trials must preserve observation IDs")
            if self.exclusion_policy.stable_id != CMJ_EXPLICIT_TRIAL_EXCLUSION_POLICY_V1.stable_id:
                raise ValueError("exclusion policy is not the registered V1 policy")
            if self.reason is None or not self.reason.strip():
                raise ValueError("excluded trials require an exclusion reason")
        if self.status is TrialEligibilityStatus.UNRESOLVED and (
            self.reason is None or not self.reason.strip()
        ):
            raise ValueError("unresolved trials require a reason")

    @classmethod
    def eligible(
        cls,
        trial_id: InstanceIdentifier,
        observation_ids: tuple[InstanceIdentifier, ...],
    ) -> TrialEligibilityDecision:
        return cls(trial_id, TrialEligibilityStatus.ELIGIBLE, observation_ids)

    @classmethod
    def excluded(
        cls,
        trial_id: InstanceIdentifier,
        observation_ids: tuple[InstanceIdentifier, ...],
        *,
        policy: RegistryReference,
        reason: str,
    ) -> TrialEligibilityDecision:
        return cls(
            trial_id,
            TrialEligibilityStatus.EXCLUDED,
            observation_ids,
            reason,
            policy,
        )

    @classmethod
    def unresolved(
        cls,
        trial_id: InstanceIdentifier,
        observation_ids: tuple[InstanceIdentifier, ...],
        *,
        reason: str,
    ) -> TrialEligibilityDecision:
        return cls(trial_id, TrialEligibilityStatus.UNRESOLVED, observation_ids, reason)

    @property
    def is_eligible(self) -> bool:
        return self.status is TrialEligibilityStatus.ELIGIBLE


@register_serializable_type
@dataclass(frozen=True, slots=True)
class TrialSelectionDecision:
    """Immutable result of applying one registered selection rule."""

    candidate_set: DeclaredCandidateTrialSet
    eligibility_decisions: tuple[TrialEligibilityDecision, ...]
    selection_rule: RegistryReference
    selected_trial_ids: tuple[InstanceIdentifier, ...]
    ranking_metric: RegistryReference | None = None
    ranking_method: RegistryReference | None = None
    ranking_direction: TrialSelectionDirection | None = None
    tie_policy: RegistryReference | None = None
    ranking_observation_ids: tuple[InstanceIdentifier, ...] = ()
    ranking_values: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        require_tuple(self.eligibility_decisions, "eligibility_decisions")
        require_tuple(self.selected_trial_ids, "selected_trial_ids")
        require_tuple(self.ranking_observation_ids, "ranking_observation_ids")
        require_tuple(self.ranking_values, "ranking_values")
        if self.selection_rule.identifier.object_type != "selection-rule":
            raise ValueError("selection_rule must be a selection-rule reference")
        expected_order = self.candidate_set.trial_ids
        decision_order = tuple(decision.trial_id for decision in self.eligibility_decisions)
        if decision_order != expected_order:
            raise ValueError("eligibility decisions must follow explicit candidate order")
        if len(set(self.selected_trial_ids)) != len(self.selected_trial_ids):
            raise ValueError("selected trials must be distinct")
        eligible = self.eligible_trial_ids
        if any(trial_id not in eligible for trial_id in self.selected_trial_ids):
            raise ValueError("selected trials must be eligible candidates")
        selected_positions = tuple(expected_order.index(item) for item in self.selected_trial_ids)
        if selected_positions != tuple(sorted(selected_positions)):
            raise ValueError("selected trials must preserve declared candidate order")
        if any(
            observation_id.instance_type != "observation"
            for observation_id in self.ranking_observation_ids
        ):
            raise ValueError("ranking observation IDs must identify observations")
        if len(set(self.ranking_observation_ids)) != len(self.ranking_observation_ids):
            raise ValueError("ranking observation IDs must be distinct")
        if self.ranking_direction is not None and not isinstance(
            self.ranking_direction, TrialSelectionDirection
        ):
            raise ValueError("ranking direction must be MAXIMIZE or MINIMIZE")
        if self.tie_policy is not None and self.tie_policy.identifier.object_type != "tie-policy":
            raise ValueError("tie_policy must be a tie-policy reference")
        is_extreme = (
            self.selection_rule.stable_id == CMJ_SELECT_EXTREME_BY_REGISTERED_METRIC_V1.stable_id
        )
        if is_extreme:
            if len(self.selected_trial_ids) != 1:
                raise ValueError("extreme selection must select exactly one trial")
            if self.ranking_metric is None or self.ranking_method is None:
                raise ValueError("extreme selection must preserve ranking metric and method")
            if self.ranking_direction is None or self.tie_policy is None:
                raise ValueError("extreme selection must preserve direction and tie policy")
            if len(self.ranking_observation_ids) != len(eligible):
                raise ValueError(
                    "extreme selection must preserve one ranking observation per eligible trial"
                )
            if len(self.ranking_values) != len(eligible):
                raise ValueError("extreme selection must preserve every ranking value")
            if any(not math.isfinite(value) for value in self.ranking_values):
                raise ValueError("ranking values must be finite")
        elif self.ranking_observation_ids:
            raise ValueError("non-extreme selection must not preserve ranking observations")
        elif self.ranking_values:
            raise ValueError("non-extreme selection must not preserve ranking values")

    @property
    def eligible_trial_ids(self) -> tuple[InstanceIdentifier, ...]:
        return tuple(
            decision.trial_id
            for decision in self.eligibility_decisions
            if decision.status is TrialEligibilityStatus.ELIGIBLE
        )

    @property
    def excluded_trial_ids(self) -> tuple[InstanceIdentifier, ...]:
        return tuple(
            decision.trial_id
            for decision in self.eligibility_decisions
            if decision.status is TrialEligibilityStatus.EXCLUDED
        )

    @property
    def unresolved_trial_ids(self) -> tuple[InstanceIdentifier, ...]:
        return tuple(
            decision.trial_id
            for decision in self.eligibility_decisions
            if decision.status is TrialEligibilityStatus.UNRESOLVED
        )

    @property
    def declared_candidate_count(self) -> int:
        return self.candidate_set.declared_candidate_count

    @property
    def eligible_count(self) -> int:
        return len(self.eligible_trial_ids)

    @property
    def excluded_count(self) -> int:
        return len(self.excluded_trial_ids)

    @property
    def selected_count(self) -> int:
        return len(self.selected_trial_ids)


type CMJTrialMetricValue = (
    ScientificMeasurementObservation
    | CMJJumpHeightResult
    | CMJPhaseMetricResult
    | SystemWeightResult
    | PhysicalSystemMassResult
    | StandardGravityMassEquivalentResult
    | NetVerticalForceResult
    | NetVerticalImpulseResult
    | SupportedSystemComAccelerationResult
    | SupportedSystemComVelocityResult
    | SupportedSystemComRelativeDisplacementResult
)
type TrialMetricInputs = (
    Sequence[CMJTrialMetricValue] | Mapping[InstanceIdentifier, CMJTrialMetricValue]
)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CMJSessionComparabilityRequest:
    """Claim-relative request for two immutable CMJ session summaries."""

    request_id: InstanceIdentifier
    left_observation_id: InstanceIdentifier
    right_observation_id: InstanceIdentifier
    claim: str

    def __post_init__(self) -> None:
        if self.request_id.instance_type != "comparability-request":
            raise ValueError("request_id must identify a comparability request")
        if self.left_observation_id == self.right_observation_id:
            raise ValueError("session comparability requires distinct observations")
        if not self.claim.strip():
            raise ValueError("session comparability claim must not be empty")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SessionAggregationResult:
    """New immutable session observation plus the exact decision that produced it."""

    observation: ScientificMeasurementObservation
    selection_decision: TrialSelectionDecision
    aggregation_rule: RegistryReference
    equation: str
    target_metric: RegistryReference
    target_measurand: RegistryReference
    target_method: RegistryReference | None
    source_method_key: str
    contributing_trial_ids: tuple[InstanceIdentifier, ...]
    contributing_observation_ids: tuple[InstanceIdentifier, ...]
    source_measurement_identity_ids: tuple[ScientificIdentifier, ...]
    declared_candidate_count: int
    eligible_count: int
    selected_count: int
    contributing_count: int
    source_metric_kind: str
    source_phase_system: RegistryReference | None = None
    source_phase_definitions: tuple[RegistryReference, ...] = ()

    def __post_init__(self) -> None:
        require_tuple(self.contributing_trial_ids, "contributing_trial_ids")
        require_tuple(self.contributing_observation_ids, "contributing_observation_ids")
        require_tuple(self.source_measurement_identity_ids, "source_measurement_identity_ids")
        require_tuple(self.source_phase_definitions, "source_phase_definitions")
        if not isinstance(self.observation.identity, CMJMeasurementIdentity):
            raise ValueError("session observation must preserve a CMJ measurement identity")
        if self.observation.context.trial_id is not None:
            raise ValueError("session observation must not be assigned a trial ID")
        if self.observation.context.athlete_id != self.selection_decision.candidate_set.athlete_id:
            raise ValueError("session observation athlete does not match candidate set")
        if self.observation.context.session_id != self.selection_decision.candidate_set.session_id:
            raise ValueError("session observation session does not match candidate set")
        if (
            self.observation.identity.semantic.test_family.stable_id
            != self.selection_decision.candidate_set.test_family.stable_id
        ):
            raise ValueError("session observation test family does not match candidate set")
        if (
            self.observation.identity.semantic.metric_definition.stable_id
            != self.target_metric.stable_id
        ):
            raise ValueError("session identity metric does not match target metric")
        if (
            self.observation.identity.semantic.measurand.stable_id
            != self.target_measurand.stable_id
        ):
            raise ValueError("session identity measurand does not match target measurand")
        if self.aggregation_rule.identifier.object_type != "aggregation-rule":
            raise ValueError("aggregation_rule must be an aggregation-rule reference")
        if not self.equation.strip() or not self.source_method_key.strip():
            raise ValueError("session equation and source method key must not be empty")
        if self.target_method is not None and self.target_method.identifier.object_type not in {
            "estimator",
            "registered-operation",
            "processing-method",
            "metric-method",
        }:
            raise ValueError("target_method must identify a registered method")
        if self.source_phase_system is not None and (
            self.source_phase_system.identifier.object_type != "phase-system"
        ):
            raise ValueError("source_phase_system must be a phase-system reference")
        if any(
            item.identifier.object_type != "phase-definition"
            for item in self.source_phase_definitions
        ):
            raise ValueError("source phase definitions must be registered")
        if self.declared_candidate_count != self.selection_decision.declared_candidate_count:
            raise ValueError("declared candidate count does not match selection decision")
        if self.eligible_count != self.selection_decision.eligible_count:
            raise ValueError("eligible count does not match selection decision")
        if self.selected_count != self.selection_decision.selected_count:
            raise ValueError("selected count does not match selection decision")
        if self.contributing_count != len(self.contributing_trial_ids):
            raise ValueError("contributing count does not match trial IDs")
        if len(self.contributing_observation_ids) != self.contributing_count:
            raise ValueError("contributing count does not match observation IDs")
        if len(set(self.contributing_trial_ids)) != self.contributing_count:
            raise ValueError("contributing trial IDs must be distinct")
        if len(set(self.contributing_observation_ids)) != self.contributing_count:
            raise ValueError("contributing observation IDs must be distinct")
        if (
            self.declared_candidate_count < 1
            or self.eligible_count < 0
            or self.selected_count < 0
            or self.contributing_count < 1
            or self.eligible_count > self.declared_candidate_count
            or self.selected_count > self.eligible_count
            or self.contributing_count > self.selected_count
        ):
            raise ValueError("session summary counts are inconsistent")
        if any(item.instance_type != "trial" for item in self.contributing_trial_ids):
            raise ValueError("contributing trial IDs must identify trials")
        if any(item.instance_type != "observation" for item in self.contributing_observation_ids):
            raise ValueError("contributing observation IDs must identify observations")
        if tuple(self.contributing_trial_ids) != self.selection_decision.selected_trial_ids:
            raise ValueError("V1 contributions must equal the selected trial order")
        if any(
            item.object_type != "measurement-identity"
            for item in self.source_measurement_identity_ids
        ):
            raise ValueError("source measurement identity IDs must identify measurement identities")
        value = self.observation.result.value
        if not isinstance(value, ScalarValue) or isinstance(value.value, bool):
            raise ValueError("session result must contain one numeric scalar")
        if not isinstance(value.value, int | float) or not math.isfinite(float(value.value)):
            raise ValueError("session result scalar must be finite and numeric")
        if self.observation.result.uncertainty.status is not UncertaintyStatus.NOT_ASSESSED:
            raise ValueError("RES-40 session uncertainty must remain NOT_ASSESSED")
        if self.observation.result.status is not ResultStatus.VALID:
            raise ValueError("RES-40 session result must be VALID")
        if self.observation.result.unit is None:
            raise ValueError("RES-40 session result must preserve an explicit unit")
        processing = self.observation.identity.processing
        if processing.trial_selection != self.selection_decision.selection_rule:
            raise ValueError("session identity must preserve the selection rule")
        if processing.aggregation != self.aggregation_rule:
            raise ValueError("session identity must preserve the aggregation rule")

    @property
    def value(self) -> float:
        value = self.observation.result.value
        if not isinstance(value, ScalarValue) or isinstance(value.value, bool):
            raise ValueError("session result is not numeric")
        return float(value.value)

    @property
    def selected_trial_id(self) -> InstanceIdentifier | None:
        return self.selection_decision.selected_trial_ids[0] if self.selected_count == 1 else None

    @property
    def selection_rule(self) -> RegistryReference:
        return self.selection_decision.selection_rule

    @property
    def source_observation_ids(self) -> tuple[InstanceIdentifier, ...]:
        return self.contributing_observation_ids


def evaluate_trial_eligibility(
    candidate_set: DeclaredCandidateTrialSet,
    observations: TrialMetricInputs = (),
    *,
    explicit_decisions: Sequence[TrialEligibilityDecision] | None = None,
    exclusions: Sequence[TrialEligibilityDecision] = (),
) -> tuple[TrialEligibilityDecision, ...] | RefusalResult:
    """Assign an explicit disposition to every declared candidate.

    Presence is not a validity guarantee.  A missing supplied observation is
    represented as ``UNRESOLVED`` and is refused by selection until an explicit
    registered exclusion decision exists.
    """

    if explicit_decisions is not None and exclusions:
        return _session_refusal(
            "evaluate CMJ trial eligibility",
            (RefusalReasonCode.SESSION_SOURCE_MISMATCH,),
            ("provide explicit decisions or exclusions through one argument only",),
        )
    if explicit_decisions is not None:
        provided_decisions = tuple(explicit_decisions)
        refusal = _validate_eligibility_decisions(candidate_set, provided_decisions)
        return refusal if refusal is not None else provided_decisions
    exclusion_by_trial: dict[InstanceIdentifier, TrialEligibilityDecision] = {}
    for decision in exclusions:
        if decision.status is not TrialEligibilityStatus.EXCLUDED:
            return _session_refusal(
                "evaluate CMJ trial eligibility",
                (RefusalReasonCode.TRIAL_NOT_ELIGIBLE,),
                ("exclusions must use EXCLUDED status",),
            )
        if decision.trial_id in exclusion_by_trial:
            return _session_refusal(
                "evaluate CMJ trial eligibility",
                (RefusalReasonCode.SESSION_SOURCE_MISMATCH,),
                ("one eligibility decision per declared trial",),
                observation_ids=decision.observation_ids,
            )
        expected_observation_id = dict(
            zip(candidate_set.trial_ids, candidate_set.candidate_observation_ids, strict=True)
        ).get(decision.trial_id)
        if expected_observation_id not in decision.observation_ids:
            return _session_refusal(
                "evaluate CMJ trial eligibility",
                (RefusalReasonCode.SESSION_SOURCE_MISMATCH,),
                ("exclusion decision preserving its declared candidate observation ID",),
                observation_ids=decision.observation_ids,
            )
        exclusion_by_trial[decision.trial_id] = decision
    if any(trial_id not in candidate_set.trial_ids for trial_id in exclusion_by_trial):
        return _session_refusal(
            "evaluate CMJ trial eligibility",
            (RefusalReasonCode.SESSION_SOURCE_MISMATCH,),
            ("exclusion decisions for declared candidate trials only",),
        )
    ordered = _ordered_trial_values(candidate_set, observations, "eligibility")
    if isinstance(ordered, RefusalResult):
        return ordered
    values_by_trial = {trial_id: value for trial_id, value in ordered}
    decisions: list[TrialEligibilityDecision] = []
    for trial_id, observation_id in zip(
        candidate_set.trial_ids, candidate_set.candidate_observation_ids, strict=True
    ):
        explicit_exclusion = exclusion_by_trial.get(trial_id)
        if explicit_exclusion is not None:
            decisions.append(explicit_exclusion)
        elif trial_id in values_by_trial:
            observation = _observation(values_by_trial[trial_id])
            if observation.result.status is ResultStatus.VALID:
                decisions.append(
                    TrialEligibilityDecision.eligible(trial_id, (observation.observation_id,))
                )
            else:
                decisions.append(
                    TrialEligibilityDecision.unresolved(
                        trial_id,
                        (observation.observation_id,),
                        reason=(
                            "candidate observation status is "
                            f"{observation.result.status.value}, not VALID"
                        ),
                    )
                )
        else:
            decisions.append(
                TrialEligibilityDecision.unresolved(
                    trial_id,
                    (observation_id,),
                    reason="declared candidate observation was not supplied",
                )
            )
    return tuple(decisions)


def select_trials(
    candidate_set: DeclaredCandidateTrialSet,
    eligibility_decisions: Sequence[TrialEligibilityDecision] = (),
    *,
    selection_rule: RegistryReference = CMJ_SELECT_ALL_DECLARED_ELIGIBLE_V1,
    ranking_observations: TrialMetricInputs = (),
    ranking_metric: RegistryReference | None = None,
    ranking_method: RegistryReference | None = None,
    ranking_direction: TrialSelectionDirection | None = None,
    tie_policy: RegistryReference | None = None,
) -> TrialSelectionDecision | RefusalResult:
    """Apply one registered selection rule in the declared candidate order."""

    decisions = tuple(eligibility_decisions)
    decision_refusal = _validate_eligibility_decisions(candidate_set, decisions)
    if decision_refusal is not None:
        return decision_refusal
    if selection_rule.stable_id not in {
        CMJ_SELECT_ALL_DECLARED_ELIGIBLE_V1.stable_id,
        CMJ_SELECT_EXTREME_BY_REGISTERED_METRIC_V1.stable_id,
    }:
        return _session_refusal(
            "select CMJ trials",
            (RefusalReasonCode.SELECTION_RULE_NOT_REGISTERED,),
            ("registered CMJ selection rule",),
        )
    if any(decision.status is TrialEligibilityStatus.UNRESOLVED for decision in decisions):
        return _session_refusal(
            "select CMJ trials",
            (RefusalReasonCode.TRIAL_SET_INCOMPLETE, RefusalReasonCode.TRIAL_NOT_ELIGIBLE),
            ("explicit eligibility or registered exclusion for every declared candidate",),
            observation_ids=_decision_observation_ids(decisions),
        )
    eligible = tuple(
        decision.trial_id
        for decision in decisions
        if decision.status is TrialEligibilityStatus.ELIGIBLE
    )
    if not eligible:
        return _session_refusal(
            "select CMJ trials",
            (RefusalReasonCode.TRIAL_NOT_ELIGIBLE,),
            ("at least one eligible declared candidate",),
            observation_ids=_decision_observation_ids(decisions),
        )
    if selection_rule.stable_id == CMJ_SELECT_ALL_DECLARED_ELIGIBLE_V1.stable_id:
        if ranking_observations:
            return _session_refusal(
                "select all eligible CMJ trials",
                (RefusalReasonCode.SESSION_SOURCE_MISMATCH,),
                ("ranking observations are not part of SELECT_ALL_DECLARED_ELIGIBLE_V1",),
            )
        return TrialSelectionDecision(
            candidate_set=candidate_set,
            eligibility_decisions=decisions,
            selection_rule=selection_rule,
            selected_trial_ids=eligible,
        )

    if ranking_metric is None:
        return _session_refusal(
            "select extreme CMJ trial",
            (RefusalReasonCode.RANKING_METRIC_REQUIRED,),
            ("registered ranking metric",),
        )
    if ranking_method is None:
        return _session_refusal(
            "select extreme CMJ trial",
            (RefusalReasonCode.RANKING_METHOD_REQUIRED,),
            ("registered ranking method or estimator",),
        )
    if not isinstance(ranking_direction, TrialSelectionDirection):
        return _session_refusal(
            "select extreme CMJ trial",
            (RefusalReasonCode.RANKING_DIRECTION_REQUIRED,),
            ("MAXIMIZE or MINIMIZE",),
        )
    direction = ranking_direction
    if not isinstance(tie_policy, RegistryReference):
        return _session_refusal(
            "select extreme CMJ trial",
            (RefusalReasonCode.TIE_POLICY_REQUIRED,),
            ("registered earliest-declared-candidate tie policy",),
        )
    resolved_tie_policy = tie_policy
    if resolved_tie_policy.stable_id != CMJ_TIE_EARLIEST_DECLARED_CANDIDATE_V1.stable_id:
        return _session_refusal(
            "select extreme CMJ trial",
            (RefusalReasonCode.SELECTION_RULE_NOT_REGISTERED,),
            ("registered V1 tie policy",),
        )
    ordered = _ordered_trial_values(candidate_set, ranking_observations, "ranking")
    if isinstance(ordered, RefusalResult):
        return ordered
    ranking_by_trial = {trial_id: value for trial_id, value in ordered}
    missing = tuple(trial_id for trial_id in eligible if trial_id not in ranking_by_trial)
    if missing:
        return _session_refusal(
            "select extreme CMJ trial",
            (RefusalReasonCode.TRIAL_SET_INCOMPLETE, RefusalReasonCode.RANKING_METRIC_REQUIRED),
            ("ranking observation for every eligible declared trial",),
            observation_ids=_decision_observation_ids(decisions),
        )
    ranking_values: list[tuple[InstanceIdentifier, CMJTrialMetricValue, float]] = []
    for trial_id in eligible:
        value = ranking_by_trial[trial_id]
        metric = _metric_reference(value)
        method = _method_reference(value)
        if (
            metric.stable_id != ranking_metric.stable_id
            or method is None
            or method.stable_id != ranking_method.stable_id
        ):
            return _session_refusal(
                "select extreme CMJ trial",
                (RefusalReasonCode.RANKING_METRICS_NOT_COMPARABLE,),
                ("every ranking observation must use the registered ranking metric and method",),
                observation_ids=_observation_ids_for_values(ranking_by_trial.values()),
            )
        scalar = _numeric_value(_observation(value))
        if scalar is None:
            return _session_refusal(
                "select extreme CMJ trial",
                (RefusalReasonCode.RANKING_METRIC_REQUIRED,),
                ("one finite scalar ranking observation per eligible trial",),
                observation_ids=_observation_ids_for_values(ranking_by_trial.values()),
            )
        ranking_values.append((trial_id, value, scalar))
    for left_index, (_, left_value, _) in enumerate(ranking_values):
        for _, right_value, _ in ranking_values[left_index + 1 :]:
            comparison = _compare_trial_values(left_value, right_value, "rank CMJ trials")
            if comparison.state is not ComparabilityState.COMPARABLE:
                return _comparison_refusal(
                    comparison,
                    category=RefusalReasonCode.RANKING_METRICS_NOT_COMPARABLE,
                    claim="rank CMJ trials by the registered metric",
                    observation_ids=(
                        _observation(left_value).observation_id,
                        _observation(right_value).observation_id,
                    ),
                )
    chosen_trial, _, chosen_value = ranking_values[0]
    for trial_id, _value, scalar in ranking_values[1:]:
        is_better = (
            scalar > chosen_value
            if direction is TrialSelectionDirection.MAXIMIZE
            else scalar < chosen_value
        )
        if is_better:
            chosen_trial, chosen_value = trial_id, scalar
    ranking_ids = tuple(
        _observation(ranking_by_trial[trial_id]).observation_id for trial_id in eligible
    )
    return TrialSelectionDecision(
        candidate_set=candidate_set,
        eligibility_decisions=decisions,
        selection_rule=selection_rule,
        selected_trial_ids=(chosen_trial,),
        ranking_metric=ranking_metric,
        ranking_method=ranking_method,
        ranking_direction=direction,
        tie_policy=resolved_tie_policy,
        ranking_observation_ids=ranking_ids,
        ranking_values=tuple(scalar for _, _, scalar in ranking_values),
    )


def project_selected_trial(
    selection_decision: TrialSelectionDecision,
    target_observations: TrialMetricInputs,
    *,
    output_observation_id: InstanceIdentifier | None = None,
    recorded_at: datetime_module.datetime | None = None,
) -> SessionAggregationResult | RefusalResult:
    """Project one scalar target from exactly the selected trial."""

    if selection_decision.selection_rule.identifier.object_type != "selection-rule":
        return _session_refusal(
            "project selected CMJ trial",
            (RefusalReasonCode.SELECTION_RULE_NOT_REGISTERED,),
            ("registered trial selection decision",),
        )
    if selection_decision.selected_count != 1:
        return _session_refusal(
            "project selected CMJ trial",
            (RefusalReasonCode.TRIAL_NOT_ELIGIBLE,),
            ("exactly one selected trial",),
            observation_ids=_decision_observation_ids(selection_decision.eligibility_decisions),
        )
    return _aggregate_session(
        selection_decision,
        target_observations,
        aggregation_rule=CMJ_SELECTED_SINGLE_TRIAL_PROJECTION_V1,
        equation="x_selected",
        output_observation_id=output_observation_id,
        recorded_at=recorded_at,
    )


def aggregate_cmj_session(
    selection_decision: TrialSelectionDecision,
    target_observations: TrialMetricInputs,
    *,
    output_observation_id: InstanceIdentifier | None = None,
    recorded_at: datetime_module.datetime | None = None,
) -> SessionAggregationResult | RefusalResult:
    """Compute the registered arithmetic mean over selected scalar trials."""

    return _aggregate_session(
        selection_decision,
        target_observations,
        aggregation_rule=CMJ_ARITHMETIC_MEAN_V1,
        equation="sum(x_i) / n",
        output_observation_id=output_observation_id,
        recorded_at=recorded_at,
    )


def aggregate_cmj_trial_metrics(
    selection_decision: TrialSelectionDecision,
    target_observations: TrialMetricInputs,
    *,
    aggregation_rule: RegistryReference = CMJ_ARITHMETIC_MEAN_V1,
    output_observation_id: InstanceIdentifier | None = None,
    recorded_at: datetime_module.datetime | None = None,
) -> SessionAggregationResult | RefusalResult:
    """Explicit operation-shaped entry point for V1 session aggregation."""

    if aggregation_rule.stable_id == CMJ_SELECTED_SINGLE_TRIAL_PROJECTION_V1.stable_id:
        if selection_decision.selected_count != 1:
            return _session_refusal(
                "aggregate CMJ trial metrics",
                (RefusalReasonCode.CONTRIBUTING_TRIAL_COUNT_MISMATCH,),
                ("selected single-trial projection requires one selected trial",),
            )
        return project_selected_trial(
            selection_decision,
            target_observations,
            output_observation_id=output_observation_id,
            recorded_at=recorded_at,
        )
    if aggregation_rule.stable_id != CMJ_ARITHMETIC_MEAN_V1.stable_id:
        return _session_refusal(
            "aggregate CMJ trial metrics",
            (RefusalReasonCode.AGGREGATION_RULE_NOT_REGISTERED,),
            ("registered arithmetic mean or selected-trial projection rule",),
        )
    return aggregate_cmj_session(
        selection_decision,
        target_observations,
        output_observation_id=output_observation_id,
        recorded_at=recorded_at,
    )


def compare_cmj_session_summaries(
    left: SessionAggregationResult,
    right: SessionAggregationResult,
    *,
    claim: str,
    request_id: InstanceIdentifier | None = None,
) -> ComparabilityResult:
    """Compare session summaries using their retained method and count identity."""

    request = CMJSessionComparabilityRequest(
        request_id=request_id
        or InstanceIdentifier(
            "comparability-request",
            f"res40-session:{left.observation.observation_id.value}:{right.observation.observation_id.value}",
        ),
        left_observation_id=left.observation.observation_id,
        right_observation_id=right.observation.observation_id,
        claim=claim,
    )
    differences: list[tuple[ComparabilityReasonCode, str]] = []
    left_identity = left.observation.identity
    right_identity = right.observation.identity
    if not isinstance(left_identity, CMJMeasurementIdentity) or not isinstance(
        right_identity, CMJMeasurementIdentity
    ):
        return _session_comparability_result(
            request,
            ComparabilityState.INSUFFICIENT_INFORMATION,
            (
                ComparabilityReasonCode.COMPARABILITY_NOT_REGISTERED,
                ComparabilityReasonCode.MISSING_METADATA,
            ),
            missing_information=("CMJ session measurement identities",),
            unresolved=True,
        )
    if left.target_measurand.stable_id != right.target_measurand.stable_id:
        differences.append((ComparabilityReasonCode.MEASURAND_MISMATCH, "target measurand"))
    if left.target_metric.stable_id != right.target_metric.stable_id:
        differences.append((ComparabilityReasonCode.IDENTITY_MISMATCH, "target metric"))
    if not _same_reference(left.target_method, right.target_method):
        differences.append(
            (
                _method_mismatch_reason(left.source_metric_kind, right.source_metric_kind),
                "target method",
            )
        )
    if left.source_metric_kind != right.source_metric_kind:
        differences.append((ComparabilityReasonCode.METHOD_MISMATCH, "source metric kind"))
    if left.source_method_key != right.source_method_key:
        differences.append(
            (
                _method_mismatch_reason(left.source_metric_kind, right.source_metric_kind),
                "source method",
            )
        )
    if not _same_reference(left.source_phase_system, right.source_phase_system):
        differences.append((ComparabilityReasonCode.PHASE_SYSTEM_MISMATCH, "phase system"))
    if not _same_reference_tuple(left.source_phase_definitions, right.source_phase_definitions):
        differences.append((ComparabilityReasonCode.PHASE_DEFINITION_MISMATCH, "phase definition"))
    if not _same_reference(left.selection_rule, right.selection_rule):
        differences.append(
            (ComparabilityReasonCode.SESSION_SELECTION_RULE_MISMATCH, "selection rule")
        )
    if not _same_reference(
        left.selection_decision.ranking_metric, right.selection_decision.ranking_metric
    ):
        differences.append(
            (ComparabilityReasonCode.SESSION_RANKING_METRIC_MISMATCH, "ranking metric")
        )
    if not _same_reference(
        left.selection_decision.ranking_method, right.selection_decision.ranking_method
    ):
        differences.append(
            (ComparabilityReasonCode.SESSION_RANKING_METHOD_MISMATCH, "ranking method")
        )
    if left.selection_decision.ranking_direction != right.selection_decision.ranking_direction:
        differences.append(
            (ComparabilityReasonCode.SESSION_RANKING_DIRECTION_MISMATCH, "ranking direction")
        )
    if not _same_reference(left.selection_decision.tie_policy, right.selection_decision.tie_policy):
        differences.append((ComparabilityReasonCode.SESSION_TIE_POLICY_MISMATCH, "tie policy"))
    if not _same_reference(left.aggregation_rule, right.aggregation_rule):
        differences.append(
            (ComparabilityReasonCode.SESSION_AGGREGATION_RULE_MISMATCH, "aggregation rule")
        )
    if left.declared_candidate_count != right.declared_candidate_count:
        differences.append(
            (ComparabilityReasonCode.SESSION_CANDIDATE_COUNT_MISMATCH, "declared candidate count")
        )
    if left.eligible_count != right.eligible_count:
        differences.append(
            (ComparabilityReasonCode.SESSION_ELIGIBLE_COUNT_MISMATCH, "eligible count")
        )
    if left.selected_count != right.selected_count:
        differences.append(
            (ComparabilityReasonCode.SESSION_SELECTED_COUNT_MISMATCH, "selected count")
        )
    if left.contributing_count != right.contributing_count:
        differences.append(
            (ComparabilityReasonCode.SESSION_CONTRIBUTING_COUNT_MISMATCH, "contributing count")
        )
    if not _same_reference(left.observation.result.unit, right.observation.result.unit):
        differences.append((ComparabilityReasonCode.UNIT_OR_NORMALIZATION_MISMATCH, "target unit"))
    if left_identity.processing.normalization != right_identity.processing.normalization:
        differences.append(
            (ComparabilityReasonCode.UNIT_OR_NORMALIZATION_MISMATCH, "normalization")
        )
    if left.observation.result.classification != right.observation.result.classification:
        differences.append((ComparabilityReasonCode.IDENTITY_MISMATCH, "value classification"))
    acquisition = compare_cmj_measurement_identities(
        left_identity,
        right_identity,
        claim=claim,
        request_id=InstanceIdentifier(
            "comparability-request", f"{request.request_id.value}:source"
        ),
        left_observation_id=left.observation.observation_id,
        right_observation_id=right.observation.observation_id,
    )
    if acquisition.state is not ComparabilityState.COMPARABLE:
        for reason in acquisition.reason_codes:
            try:
                code = ComparabilityReasonCode(reason)
            except ValueError:
                code = ComparabilityReasonCode.COMPARABILITY_NOT_REGISTERED
            differences.append((code, "session acquisition identity"))
    if not differences:
        return _session_comparability_result(request, ComparabilityState.COMPARABLE)
    reasons = tuple(dict.fromkeys(reason for reason, _ in differences))
    state = (
        ComparabilityState.NOT_COMPARABLE
        if ComparabilityReasonCode.MEASURAND_MISMATCH in reasons
        or ComparabilityReasonCode.IDENTITY_MISMATCH in reasons
        else ComparabilityState.BRIDGE_VALIDATION_REQUIRED
    )
    return _session_comparability_result(
        request,
        state,
        reasons,
        conditions=(
            "all session target, source-method, acquisition, rule, loading, and count "
            "dimensions must match or have a registered bridge",
        ),
    )


compare_cmj_session_results = compare_cmj_session_summaries


def refusal_for_cmj_session_comparability(
    result: ComparabilityResult,
    *,
    blocked_claim: str,
    observation_ids: tuple[InstanceIdentifier, ...] = (),
) -> RefusalResult | None:
    """Turn an unresolved session comparison into a claim-specific refusal."""

    if result.state is ComparabilityState.COMPARABLE:
        return None
    mapping = {
        ComparabilityReasonCode.MEASURAND_MISMATCH: RefusalReasonCode.MEASURAND_MISMATCH,
        ComparabilityReasonCode.IDENTITY_MISMATCH: RefusalReasonCode.METRIC_DEFINITION_MISMATCH,
        ComparabilityReasonCode.ESTIMATOR_MISMATCH: RefusalReasonCode.ESTIMATOR_MISMATCH,
        ComparabilityReasonCode.METHOD_MISMATCH: RefusalReasonCode.NO_REGISTERED_OPERATION,
        ComparabilityReasonCode.PHASE_METRIC_METHOD_MISMATCH: (
            RefusalReasonCode.PHASE_METHOD_MISMATCH
        ),
        ComparabilityReasonCode.PHASE_SYSTEM_MISMATCH: RefusalReasonCode.PHASE_METHOD_MISMATCH,
        ComparabilityReasonCode.PHASE_DEFINITION_MISMATCH: RefusalReasonCode.PHASE_METHOD_MISMATCH,
        ComparabilityReasonCode.SESSION_CANDIDATE_COUNT_MISMATCH: (
            RefusalReasonCode.CONTRIBUTING_TRIAL_COUNT_MISMATCH
        ),
        ComparabilityReasonCode.SESSION_ELIGIBLE_COUNT_MISMATCH: (
            RefusalReasonCode.CONTRIBUTING_TRIAL_COUNT_MISMATCH
        ),
        ComparabilityReasonCode.SESSION_SELECTED_COUNT_MISMATCH: (
            RefusalReasonCode.CONTRIBUTING_TRIAL_COUNT_MISMATCH
        ),
        ComparabilityReasonCode.SESSION_CONTRIBUTING_COUNT_MISMATCH: (
            RefusalReasonCode.CONTRIBUTING_TRIAL_COUNT_MISMATCH
        ),
        ComparabilityReasonCode.UNIT_OR_NORMALIZATION_MISMATCH: (
            RefusalReasonCode.UNIT_OR_NORMALIZATION_MISMATCH
        ),
        ComparabilityReasonCode.DEVICE_MISMATCH: RefusalReasonCode.DEVICE_BRIDGE_NOT_REGISTERED,
        ComparabilityReasonCode.PROTOCOL_MISMATCH: RefusalReasonCode.PROTOCOL_IDENTITY_MISMATCH,
        ComparabilityReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH: (
            RefusalReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH
        ),
        ComparabilityReasonCode.PROCESSING_STATE_MISMATCH: (
            RefusalReasonCode.PROCESSING_STATE_UNKNOWN
        ),
    }
    reasons: list[RefusalReasonCode] = [
        RefusalReasonCode.SESSION_SUMMARY_COMPARABILITY_UNESTABLISHED
    ]
    for reason in result.reason_codes:
        try:
            normalized = ComparabilityReasonCode(reason)
        except ValueError:
            normalized = ComparabilityReasonCode.COMPARABILITY_NOT_REGISTERED
        mapped = mapping.get(normalized, RefusalReasonCode.COMPARABILITY_NOT_REGISTERED)
        if mapped not in reasons:
            reasons.append(mapped)
    return _session_refusal(
        blocked_claim,
        tuple(reasons),
        result.missing_information or ("registered session-summary comparability bridge",),
        observation_ids=observation_ids,
        refusal_class=RefusalClass.COMPARABILITY_UNESTABLISHED,
    )


def _aggregate_session(
    selection_decision: TrialSelectionDecision,
    target_observations: TrialMetricInputs,
    *,
    aggregation_rule: RegistryReference,
    equation: str,
    output_observation_id: InstanceIdentifier | None,
    recorded_at: datetime_module.datetime | None,
) -> SessionAggregationResult | RefusalResult:
    if aggregation_rule.stable_id not in {
        CMJ_ARITHMETIC_MEAN_V1.stable_id,
        CMJ_SELECTED_SINGLE_TRIAL_PROJECTION_V1.stable_id,
    }:
        return _session_refusal(
            "aggregate CMJ session",
            (RefusalReasonCode.AGGREGATION_RULE_NOT_REGISTERED,),
            ("registered RES-40 aggregation rule",),
        )
    ordered = _ordered_trial_values(selection_decision.candidate_set, target_observations, "target")
    if isinstance(ordered, RefusalResult):
        return ordered
    target_by_trial = {trial_id: value for trial_id, value in ordered}
    eligible = selection_decision.eligible_trial_ids
    missing = tuple(trial_id for trial_id in eligible if trial_id not in target_by_trial)
    if missing:
        return _session_refusal(
            "aggregate CMJ session",
            (RefusalReasonCode.TRIAL_SET_INCOMPLETE, RefusalReasonCode.TARGET_METRIC_REQUIRED),
            ("target observation for every eligible declared candidate",),
            observation_ids=_decision_observation_ids(selection_decision.eligibility_decisions),
        )
    contributing = selection_decision.selected_trial_ids
    if aggregation_rule.stable_id == CMJ_SELECTED_SINGLE_TRIAL_PROJECTION_V1.stable_id:
        if len(contributing) != 1:
            return _session_refusal(
                "project selected CMJ trial",
                (RefusalReasonCode.CONTRIBUTING_TRIAL_COUNT_MISMATCH,),
                ("exactly one selected trial",),
            )
    values = tuple(target_by_trial[trial_id] for trial_id in contributing)
    numeric_values: list[float] = []
    for value in values:
        numeric = _numeric_value(_observation(value))
        if numeric is None:
            return _session_refusal(
                "aggregate CMJ session",
                (RefusalReasonCode.AGGREGATION_REQUIRES_SCALAR,),
                ("selected target observations containing finite numeric ScalarValue",),
                observation_ids=_observation_ids_for_values(values),
            )
        numeric_values.append(numeric)
    if aggregation_rule.stable_id == CMJ_ARITHMETIC_MEAN_V1.stable_id and not numeric_values:
        return _session_refusal(
            "aggregate CMJ session",
            (RefusalReasonCode.AGGREGATION_REQUIRES_SCALAR,),
            ("at least one selected scalar observation",),
        )
    for left_index, left_value in enumerate(values):
        for right_value in values[left_index + 1 :]:
            comparison = _compare_trial_values(left_value, right_value, "aggregate CMJ targets")
            if comparison.state is not ComparabilityState.COMPARABLE:
                return _comparison_refusal(
                    comparison,
                    category=RefusalReasonCode.TARGET_METRICS_NOT_COMPARABLE,
                    claim="aggregate directly comparable CMJ target metrics",
                    observation_ids=(
                        _observation(left_value).observation_id,
                        _observation(right_value).observation_id,
                    ),
                )
    first = values[0]
    first_observation = _observation(first)
    first_identity = first_observation.identity
    if not isinstance(first_identity, CMJMeasurementIdentity):
        return _session_refusal(
            "aggregate CMJ session",
            (RefusalReasonCode.SESSION_SOURCE_MISMATCH,),
            ("CMJ measurement identity on target observations",),
            observation_ids=_observation_ids_for_values(values),
        )
    classification = first_observation.result.classification
    unit = first_observation.result.unit
    for value in values[1:]:
        observation = _observation(value)
        if observation.result.classification != classification:
            return _session_refusal(
                "aggregate CMJ session",
                (RefusalReasonCode.TARGET_METRICS_NOT_COMPARABLE,),
                ("homogeneous scientific value-origin and role classification",),
                observation_ids=_observation_ids_for_values(values),
            )
        if not _same_reference(observation.result.unit, unit):
            return _session_refusal(
                "aggregate CMJ session",
                (RefusalReasonCode.TARGET_METRICS_NOT_COMPARABLE,),
                ("one compatible target unit",),
                observation_ids=_observation_ids_for_values(values),
            )
    if unit is None:
        return _session_refusal(
            "aggregate CMJ session",
            (RefusalReasonCode.TARGET_METRICS_NOT_COMPARABLE,),
            ("explicit target unit",),
            observation_ids=_observation_ids_for_values(values),
        )
    output_value = (
        numeric_values[0]
        if aggregation_rule.stable_id == CMJ_SELECTED_SINGLE_TRIAL_PROJECTION_V1.stable_id
        else sum(numeric_values) / len(numeric_values)
    )
    method_key = _source_method_key(first)
    target_method = _method_reference(first)
    phase_system, phase_definitions = _phase_identity(first)
    result = _build_session_result(
        selection_decision,
        values,
        output_value=output_value,
        aggregation_rule=aggregation_rule,
        equation=equation,
        target_metric=first_identity.semantic.metric_definition,
        target_measurand=first_identity.semantic.measurand,
        target_method=target_method,
        source_method_key=method_key,
        source_metric_kind=_metric_kind(first),
        source_phase_system=phase_system,
        source_phase_definitions=phase_definitions,
        classification=classification,
        unit=unit,
        output_observation_id=output_observation_id,
        recorded_at=recorded_at,
    )
    return result


def _build_session_result(
    selection_decision: TrialSelectionDecision,
    values: tuple[CMJTrialMetricValue, ...],
    *,
    output_value: float,
    aggregation_rule: RegistryReference,
    equation: str,
    target_metric: RegistryReference,
    target_measurand: RegistryReference,
    target_method: RegistryReference | None,
    source_method_key: str,
    source_metric_kind: str,
    source_phase_system: RegistryReference | None,
    source_phase_definitions: tuple[RegistryReference, ...],
    classification: ScientificClassification,
    unit: UnitReference,
    output_observation_id: InstanceIdentifier | None,
    recorded_at: datetime_module.datetime | None,
) -> SessionAggregationResult | RefusalResult:
    observations = tuple(_observation(value) for value in values)
    first_identity = observations[0].identity
    if not isinstance(first_identity, CMJMeasurementIdentity):
        return _session_refusal(
            "build CMJ session observation",
            (RefusalReasonCode.SESSION_SOURCE_MISMATCH,),
            ("CMJ measurement identity on target observations",),
            observation_ids=_observation_ids(observations),
        )
    source_context = observations[0].context
    for observation in observations[1:]:
        if (
            observation.context.athlete_id != source_context.athlete_id
            or observation.context.session_id != source_context.session_id
            or observation.context.test_instance_id != source_context.test_instance_id
            or observation.context.population_context != source_context.population_context
        ):
            return _session_refusal(
                "build CMJ session observation",
                (RefusalReasonCode.SESSION_SOURCE_MISMATCH,),
                ("same athlete, session, test instance, and population context",),
                observation_ids=_observation_ids_for_values(values),
            )
    candidate_set = selection_decision.candidate_set
    digest_payload = {
        "selection": selection_decision,
        "target_observations": observations,
        "aggregation_rule": aggregation_rule,
        "source_method_key": source_method_key,
    }
    digest = canonical_hash(digest_payload).removeprefix("sha256:")[:32]
    output_id = output_observation_id or InstanceIdentifier("observation", f"cmj-session:{digest}")
    if output_id.instance_type != "observation":
        return _session_refusal(
            "build CMJ session observation",
            (RefusalReasonCode.SESSION_SOURCE_MISMATCH,),
            ("output observation ID with instance_type observation",),
        )
    if output_id in {observation.observation_id for observation in observations}:
        return _session_refusal(
            "build CMJ session observation",
            (RefusalReasonCode.SESSION_SOURCE_MISMATCH,),
            ("new output observation ID distinct from every source observation",),
            observation_ids=_observation_ids(observations),
        )
    session_context = ObservationContext(
        context_id=InstanceIdentifier("context", f"cmj-session:{digest}"),
        athlete_id=candidate_set.athlete_id,
        session_id=candidate_set.session_id,
        test_instance_id=source_context.test_instance_id,
        trial_id=None,
        observed_at=recorded_at or source_context.observed_at,
        population_context=source_context.population_context,
        environment=source_context.environment,
        context_metadata=(
            *source_context.context_metadata,
            MetadataEntry("session_summary", "RES-40 deterministic session result"),
        ),
    )
    parameters = _session_processing_parameters(
        selection_decision,
        aggregation_rule=aggregation_rule,
        equation=equation,
        target_metric=target_metric,
        target_measurand=target_measurand,
        target_method=target_method,
        source_method_key=source_method_key,
        source_metric_kind=source_metric_kind,
        source_phase_system=source_phase_system,
        source_phase_definitions=source_phase_definitions,
    )
    parameters = (
        *parameters,
        MetadataEntry(
            "eligibility_decisions", canonical_json(selection_decision.eligibility_decisions)
        ),
        MetadataEntry(
            "source_observation_ids",
            canonical_json(tuple(item.observation_id for item in observations)),
        ),
        MetadataEntry(
            "source_measurement_identity_ids",
            canonical_json(tuple(item.identity.identity_id for item in observations)),
        ),
    )
    source_processing = observations[0].identity.processing
    output_processing = replace(
        source_processing,
        registered_operation=CMJ_SESSION_AGGREGATION_OPERATION,
        method_parameters=parameters,
        trial_selection=selection_decision.selection_rule,
        aggregation=aggregation_rule,
        unit=unit,
    )
    output_identity = CMJMeasurementIdentity(
        identity_id=ScientificIdentifier(
            "dynamislm", "measurement-identity", f"cmj-session:{digest}", "1.0.0"
        ),
        semantic=first_identity.semantic,
        acquisition=first_identity.acquisition,
        processing=output_processing,
        version=VersionIdentity(
            processing_method=CMJ_SESSION_AGGREGATION_OPERATION,
            method_registry_version=CMJ_SESSION_AGGREGATION_OPERATION.identifier.version,
            software_version=RES40_SOFTWARE_VERSION,
            hardware_firmware=first_identity.version.hardware_firmware,
        ),
    )
    output_result = MeasurementResult(
        result_id=InstanceIdentifier("result", f"{output_id.value}:result"),
        value=ScalarValue(output_value),
        unit=unit,
        classification=classification,
        quality=MeasurementQuality(
            status=QualityStatus.UNKNOWN,
            note="deterministic RES-40 session summary; trial quality is not reassessed",
        ),
        uncertainty=UncertaintyMetadata(
            status=UncertaintyStatus.NOT_ASSESSED,
            description=_UNCERTAINTY_DESCRIPTION,
        ),
        status=ResultStatus.VALID,
    )
    provenance = _session_provenance(
        observations,
        output_id=output_id,
        parameters=parameters,
        recorded_at=recorded_at,
    )
    if isinstance(provenance, RefusalResult):
        return provenance
    observation = ScientificMeasurementObservation(
        observation_id=output_id,
        context=session_context,
        identity=output_identity,
        result=output_result,
        provenance=provenance,
    )
    return SessionAggregationResult(
        observation=observation,
        selection_decision=selection_decision,
        aggregation_rule=aggregation_rule,
        equation=equation,
        target_metric=target_metric,
        target_measurand=target_measurand,
        target_method=target_method,
        source_method_key=source_method_key,
        contributing_trial_ids=selection_decision.selected_trial_ids,
        contributing_observation_ids=tuple(item.observation_id for item in observations),
        source_measurement_identity_ids=_unique_tuple(
            item.identity.identity_id for item in observations
        ),
        declared_candidate_count=selection_decision.declared_candidate_count,
        eligible_count=selection_decision.eligible_count,
        selected_count=selection_decision.selected_count,
        contributing_count=len(observations),
        source_metric_kind=source_metric_kind,
        source_phase_system=source_phase_system,
        source_phase_definitions=source_phase_definitions,
    )


def _session_processing_parameters(
    selection_decision: TrialSelectionDecision,
    *,
    aggregation_rule: RegistryReference,
    equation: str,
    target_metric: RegistryReference,
    target_measurand: RegistryReference,
    target_method: RegistryReference | None,
    source_method_key: str,
    source_metric_kind: str,
    source_phase_system: RegistryReference | None,
    source_phase_definitions: tuple[RegistryReference, ...],
) -> tuple[MetadataEntry, ...]:
    return (
        MetadataEntry("selection_rule", selection_decision.selection_rule.stable_id),
        MetadataEntry(
            "selection_rule_version", selection_decision.selection_rule.identifier.version
        ),
        MetadataEntry("ranking_metric", _reference_id(selection_decision.ranking_metric)),
        MetadataEntry("ranking_method", _reference_id(selection_decision.ranking_method)),
        MetadataEntry(
            "ranking_direction",
            selection_decision.ranking_direction.value
            if selection_decision.ranking_direction is not None
            else "not_applicable",
        ),
        MetadataEntry("tie_policy", _reference_id(selection_decision.tie_policy)),
        MetadataEntry("aggregation_rule", aggregation_rule.stable_id),
        MetadataEntry("aggregation_rule_version", aggregation_rule.identifier.version),
        MetadataEntry("equation", equation),
        MetadataEntry("declared_candidate_count", selection_decision.declared_candidate_count),
        MetadataEntry("eligible_count", selection_decision.eligible_count),
        MetadataEntry("selected_count", selection_decision.selected_count),
        MetadataEntry("contributing_count", selection_decision.selected_count),
        MetadataEntry(
            "candidate_trial_ids", canonical_json(selection_decision.candidate_set.trial_ids)
        ),
        MetadataEntry(
            "candidate_observation_ids",
            canonical_json(selection_decision.candidate_set.candidate_observation_ids),
        ),
        MetadataEntry("selected_trial_ids", canonical_json(selection_decision.selected_trial_ids)),
        MetadataEntry(
            "ranking_observation_ids", canonical_json(selection_decision.ranking_observation_ids)
        ),
        MetadataEntry("ranking_values", canonical_json(selection_decision.ranking_values)),
        MetadataEntry("target_metric", target_metric.stable_id),
        MetadataEntry("target_measurand", target_measurand.stable_id),
        MetadataEntry("target_method", _reference_id(target_method)),
        MetadataEntry("source_method_key", source_method_key),
        MetadataEntry("source_metric_kind", source_metric_kind),
        MetadataEntry("source_phase_system", _reference_id(source_phase_system)),
        MetadataEntry("source_phase_definitions", canonical_json(source_phase_definitions)),
        MetadataEntry("uncertainty_status", UncertaintyStatus.NOT_ASSESSED.value),
        MetadataEntry("uncertainty_analysis", _UNCERTAINTY_DESCRIPTION),
    )


def _session_provenance(
    observations: tuple[ScientificMeasurementObservation, ...],
    *,
    output_id: InstanceIdentifier,
    parameters: tuple[MetadataEntry, ...],
    recorded_at: datetime_module.datetime | None,
) -> Provenance | RefusalResult:
    artifacts: list[SourceArtifact] = []
    acquisitions: list[AcquisitionRecord] = []
    processing_runs: list[ProcessingRun] = []
    lineage_edges: list[LineageEdge] = []
    evidence: list[EvidenceReference] = []
    metrological: list[RegistryReference] = []
    for observation in observations:
        provenance = observation.provenance
        for artifact in provenance.source_artifacts:
            if not _append_same(artifacts, artifact, lambda item: item.artifact_id):
                return _session_refusal(
                    "build CMJ session provenance",
                    (RefusalReasonCode.SESSION_SOURCE_MISMATCH,),
                    ("consistent source artifact identity",),
                    observation_ids=(observation.observation_id,),
                )
        for acquisition in provenance.acquisitions:
            if not _append_same(acquisitions, acquisition, lambda item: item.acquisition_id):
                return _session_refusal(
                    "build CMJ session provenance",
                    (RefusalReasonCode.SESSION_SOURCE_MISMATCH,),
                    ("consistent source acquisition identity",),
                    observation_ids=(observation.observation_id,),
                )
        for run in provenance.processing_runs:
            if not _append_same(processing_runs, run, lambda item: item.processing_run_id):
                return _session_refusal(
                    "build CMJ session provenance",
                    (RefusalReasonCode.SESSION_SOURCE_MISMATCH,),
                    ("consistent source processing-run identity",),
                    observation_ids=(observation.observation_id,),
                )
        _append_unique_items(lineage_edges, provenance.lineage_edges)
        _append_unique_items(evidence, provenance.evidence_references)
        _append_unique_items(metrological, provenance.metrological_traceability)
    if not artifacts:
        return _session_refusal(
            "build CMJ session provenance",
            (
                RefusalReasonCode.SESSION_SOURCE_MISMATCH,
                RefusalReasonCode.SOURCE_ARTIFACT_UNVERIFIED,
            ),
            ("at least one verified source artifact in contributing observations",),
            observation_ids=_observation_ids(observations),
        )
    digest = canonical_hash(
        {"output": output_id, "parameters": parameters, "sources": _observation_ids(observations)}
    ).removeprefix("sha256:")[:24]
    run = ProcessingRun(
        processing_run_id=InstanceIdentifier("processing-run", f"cmj-session:{digest}"),
        source_artifact_ids=tuple(item.artifact_id for item in artifacts),
        method=CMJ_SESSION_AGGREGATION_OPERATION,
        parameters=parameters,
        software_version=RES40_SOFTWARE_VERSION,
        output_entity_id=output_id,
    )
    if not _append_same(processing_runs, run, lambda item: item.processing_run_id):
        return _session_refusal(
            "build CMJ session provenance",
            (RefusalReasonCode.SESSION_SOURCE_MISMATCH,),
            ("unique RES-40 processing-run identity",),
            observation_ids=_observation_ids(observations),
        )
    source_artifact_ids = tuple(item.artifact_id for item in artifacts)
    for observation in observations:
        _append_unique_items(
            lineage_edges,
            (
                LineageEdge(
                    observation.observation_id.qualified,
                    run.processing_run_id.qualified,
                    LineageRelation.DERIVED_FROM,
                ),
            ),
        )
    for artifact_id in source_artifact_ids:
        _append_unique_items(
            lineage_edges,
            (
                LineageEdge(
                    artifact_id.qualified,
                    run.processing_run_id.qualified,
                    LineageRelation.DERIVED_FROM,
                ),
            ),
        )
    for acquisition in acquisitions:
        _append_unique_items(
            lineage_edges,
            (
                LineageEdge(
                    acquisition.acquisition_id.qualified,
                    run.processing_run_id.qualified,
                    LineageRelation.PROCESSED_AS,
                ),
            ),
        )
    _append_unique_items(
        lineage_edges,
        (
            LineageEdge(
                run.processing_run_id.qualified,
                output_id.qualified,
                LineageRelation.PRODUCED,
            ),
        ),
    )
    _append_unique_items(
        evidence,
        (EvidenceReference(RES40_DECISION_SESSION_AGGREGATION, "RES-40 session aggregation"),),
    )
    _append_unique_items(
        evidence,
        (EvidenceReference(RES40_DECISION_TRIAL_SELECTION, "RES-40 trial selection"),),
    )
    return Provenance(
        provenance_id=InstanceIdentifier("provenance", output_id.value),
        source_artifacts=tuple(artifacts),
        acquisitions=tuple(acquisitions),
        processing_runs=tuple(processing_runs),
        lineage_edges=tuple(lineage_edges),
        evidence_references=tuple(evidence),
        metrological_traceability=tuple(metrological),
        recorded_at=recorded_at,
    )


def _validate_eligibility_decisions(
    candidate_set: DeclaredCandidateTrialSet,
    decisions: tuple[TrialEligibilityDecision, ...],
) -> RefusalResult | None:
    if len(decisions) != candidate_set.declared_candidate_count:
        return _session_refusal(
            "validate CMJ trial eligibility",
            (RefusalReasonCode.TRIAL_SET_INCOMPLETE,),
            ("one eligibility decision for every declared candidate",),
            observation_ids=_decision_observation_ids(decisions),
        )
    if tuple(decision.trial_id for decision in decisions) != candidate_set.trial_ids:
        return _session_refusal(
            "validate CMJ trial eligibility",
            (RefusalReasonCode.SESSION_SOURCE_MISMATCH,),
            ("eligibility decisions in explicit declared candidate order",),
            observation_ids=_decision_observation_ids(decisions),
        )
    candidate_observation_by_trial = dict(
        zip(candidate_set.trial_ids, candidate_set.candidate_observation_ids, strict=True)
    )
    for decision in decisions:
        if candidate_observation_by_trial[decision.trial_id] not in decision.observation_ids:
            return _session_refusal(
                "validate CMJ trial eligibility",
                (RefusalReasonCode.SESSION_SOURCE_MISMATCH,),
                ("eligibility decision preserving its declared candidate observation ID",),
                observation_ids=decision.observation_ids,
            )
    return None


def _ordered_trial_values(
    candidate_set: DeclaredCandidateTrialSet,
    values: TrialMetricInputs,
    role: str,
) -> tuple[tuple[InstanceIdentifier, CMJTrialMetricValue], ...] | RefusalResult:
    entries: list[tuple[InstanceIdentifier, CMJTrialMetricValue]] = []
    candidate_observation_by_trial = dict(
        zip(candidate_set.trial_ids, candidate_set.candidate_observation_ids, strict=True)
    )
    if isinstance(values, Mapping):
        for key, value in values.items():
            if not isinstance(key, InstanceIdentifier) or key.instance_type not in {
                "trial",
                "observation",
            }:
                return _session_refusal(
                    f"validate CMJ {role} observations",
                    (RefusalReasonCode.SESSION_SOURCE_MISMATCH,),
                    ("values keyed by a trial ID or the supplied observation ID",),
                )
            try:
                observation = _observation(value)
            except (AttributeError, TypeError, ValueError):
                return _session_refusal(
                    f"validate CMJ {role} observations",
                    (RefusalReasonCode.TRIAL_SET_INCOMPLETE,),
                    (f"typed CMJ {role} observation",),
                )
            if key.instance_type == "trial" and key not in candidate_set.trial_ids:
                return _session_refusal(
                    f"validate CMJ {role} observations",
                    (RefusalReasonCode.SESSION_SOURCE_MISMATCH,),
                    ("values keyed by declared trial IDs",),
                    observation_ids=(observation.observation_id,),
                )
            if key.instance_type == "trial" and key != observation.context.trial_id:
                return _session_refusal(
                    f"validate CMJ {role} observations",
                    (RefusalReasonCode.SESSION_SOURCE_MISMATCH,),
                    ("mapping trial key equal to observation trial ID",),
                    observation_ids=(observation.observation_id,),
                )
            if key.instance_type == "observation" and key != observation.observation_id:
                return _session_refusal(
                    f"validate CMJ {role} observations",
                    (RefusalReasonCode.SESSION_SOURCE_MISMATCH,),
                    ("mapping observation key equal to observation ID",),
                    observation_ids=(observation.observation_id,),
                )
            trial_id = observation.context.trial_id
            if trial_id is None:
                return _session_refusal(
                    f"validate CMJ {role} observations",
                    (RefusalReasonCode.SESSION_SOURCE_MISMATCH,),
                    ("observation context with a trial ID",),
                    observation_ids=(observation.observation_id,),
                )
            if role == "eligibility" and (
                candidate_observation_by_trial.get(trial_id) != observation.observation_id
            ):
                return _session_refusal(
                    f"validate CMJ {role} observations",
                    (RefusalReasonCode.SESSION_SOURCE_MISMATCH,),
                    ("eligibility observation equal to its declared candidate observation ID",),
                    observation_ids=(observation.observation_id,),
                )
            entries.append((trial_id, value))
    else:
        if isinstance(values, str | bytes):
            return _session_refusal(
                f"validate CMJ {role} observations",
                (RefusalReasonCode.TRIAL_SET_INCOMPLETE,),
                (f"ordered typed CMJ {role} observations",),
            )
        for value in values:
            try:
                observation = _observation(value)
            except (AttributeError, TypeError, ValueError):
                return _session_refusal(
                    f"validate CMJ {role} observations",
                    (RefusalReasonCode.TRIAL_SET_INCOMPLETE,),
                    (f"typed CMJ {role} observation",),
                )
            trial_id = observation.context.trial_id
            if trial_id is None:
                return _session_refusal(
                    f"validate CMJ {role} observations",
                    (RefusalReasonCode.SESSION_SOURCE_MISMATCH,),
                    ("observation context with a trial ID",),
                    observation_ids=(observation.observation_id,),
                )
            if role == "eligibility" and (
                candidate_observation_by_trial.get(trial_id) != observation.observation_id
            ):
                return _session_refusal(
                    f"validate CMJ {role} observations",
                    (RefusalReasonCode.SESSION_SOURCE_MISMATCH,),
                    ("eligibility observation equal to its declared candidate observation ID",),
                    observation_ids=(observation.observation_id,),
                )
            entries.append((trial_id, value))
    allowed_trials = set(candidate_set.trial_ids)
    seen: set[InstanceIdentifier] = set()
    seen_observation_ids: set[InstanceIdentifier] = set()
    for trial_id, value in entries:
        if trial_id not in allowed_trials:
            return _session_refusal(
                f"validate CMJ {role} observations",
                (RefusalReasonCode.SESSION_SOURCE_MISMATCH,),
                ("same declared athlete, session, CMJ family, and trial set",),
                observation_ids=(_observation(value).observation_id,),
            )
        if trial_id in seen:
            return _session_refusal(
                f"validate CMJ {role} observations",
                (RefusalReasonCode.SESSION_SOURCE_MISMATCH,),
                (f"one {role} observation per declared trial",),
                observation_ids=(_observation(value).observation_id,),
            )
        observation_id = _observation(value).observation_id
        if observation_id in seen_observation_ids:
            return _session_refusal(
                f"validate CMJ {role} observations",
                (RefusalReasonCode.SESSION_SOURCE_MISMATCH,),
                (f"one {role} observation ID per declared trial",),
                observation_ids=(observation_id,),
            )
        seen.add(trial_id)
        seen_observation_ids.add(observation_id)
        source_refusal = _validate_observation_source(
            candidate_set, trial_id, _observation(value), role
        )
        if source_refusal is not None:
            return source_refusal
    by_trial = {trial_id: value for trial_id, value in entries}
    return tuple(
        (trial_id, by_trial[trial_id])
        for trial_id in candidate_set.trial_ids
        if trial_id in by_trial
    )


def _validate_observation_source(
    candidate_set: DeclaredCandidateTrialSet,
    trial_id: InstanceIdentifier,
    observation: ScientificMeasurementObservation,
    role: str,
) -> RefusalResult | None:
    if observation.context.athlete_id != candidate_set.athlete_id:
        return _session_refusal(
            f"validate CMJ {role} observations",
            (RefusalReasonCode.SESSION_SOURCE_MISMATCH,),
            ("declared athlete",),
            observation_ids=(observation.observation_id,),
        )
    if observation.context.session_id != candidate_set.session_id:
        return _session_refusal(
            f"validate CMJ {role} observations",
            (RefusalReasonCode.SESSION_SOURCE_MISMATCH,),
            ("declared session",),
            observation_ids=(observation.observation_id,),
        )
    if observation.context.trial_id != trial_id:
        return _session_refusal(
            f"validate CMJ {role} observations",
            (RefusalReasonCode.SESSION_SOURCE_MISMATCH,),
            ("observation trial ID equal to its declared candidate",),
            observation_ids=(observation.observation_id,),
        )
    if not isinstance(observation.identity, CMJMeasurementIdentity):
        return _session_refusal(
            f"validate CMJ {role} observations",
            (RefusalReasonCode.SESSION_SOURCE_MISMATCH,),
            ("CMJ measurement identity",),
            observation_ids=(observation.observation_id,),
        )
    if observation.identity.semantic.test_family.stable_id != candidate_set.test_family.stable_id:
        return _session_refusal(
            f"validate CMJ {role} observations",
            (RefusalReasonCode.SESSION_SOURCE_MISMATCH,),
            ("CMJ test family equal to the declared candidate family",),
            observation_ids=(observation.observation_id,),
        )
    return None


def _compare_trial_values(
    left: CMJTrialMetricValue,
    right: CMJTrialMetricValue,
    claim: str,
) -> ComparabilityResult:
    request_id = InstanceIdentifier(
        "comparability-request",
        f"res40-trial:{_observation(left).observation_id.value}:{_observation(right).observation_id.value}",
    )
    if isinstance(left, CMJJumpHeightResult) and isinstance(right, CMJJumpHeightResult):
        return compare_cmj_jump_height_estimates(left, right, claim=claim, request_id=request_id)
    if isinstance(left, CMJPhaseMetricResult) and isinstance(right, CMJPhaseMetricResult):
        return compare_cmj_phase_metrics(left, right, claim=claim, request_id=request_id)
    if isinstance(left, _MECHANICS_TYPES) and isinstance(right, _MECHANICS_TYPES):
        return compare_cmj_mechanics(left, right, claim=claim, request_id=request_id)
    if isinstance(left, _DERIVED_TYPES) and isinstance(right, _DERIVED_TYPES):
        return compare_cmj_derived_measurements(left, right, claim=claim, request_id=request_id)
    if isinstance(left, ScientificMeasurementObservation) and isinstance(
        right, ScientificMeasurementObservation
    ):
        return _compare_direct_observations(left, right, claim, request_id)
    reason = (
        ComparabilityReasonCode.ESTIMATOR_MISMATCH
        if _metric_kind(left) == "JUMP_HEIGHT" or _metric_kind(right) == "JUMP_HEIGHT"
        else ComparabilityReasonCode.PHASE_METRIC_METHOD_MISMATCH
        if _metric_kind(left) == "PHASE_METRIC" or _metric_kind(right) == "PHASE_METRIC"
        else ComparabilityReasonCode.METHOD_MISMATCH
    )
    return _trial_comparability_result(
        request_id,
        ComparabilityState.BRIDGE_VALIDATION_REQUIRED,
        (reason,),
    )


_MECHANICS_TYPES = (
    NetVerticalForceResult,
    NetVerticalImpulseResult,
    SupportedSystemComAccelerationResult,
    SupportedSystemComVelocityResult,
    SupportedSystemComRelativeDisplacementResult,
)
_DERIVED_TYPES = (
    SystemWeightResult,
    PhysicalSystemMassResult,
    StandardGravityMassEquivalentResult,
)


def _compare_direct_observations(
    left: ScientificMeasurementObservation,
    right: ScientificMeasurementObservation,
    claim: str,
    request_id: InstanceIdentifier,
) -> ComparabilityResult:
    if not isinstance(left.identity, CMJMeasurementIdentity) or not isinstance(
        right.identity, CMJMeasurementIdentity
    ):
        return _trial_comparability_result(
            request_id,
            ComparabilityState.INSUFFICIENT_INFORMATION,
            (ComparabilityReasonCode.MISSING_METADATA,),
        )
    reasons: list[ComparabilityReasonCode] = []
    if left.identity.semantic.measurand.stable_id != right.identity.semantic.measurand.stable_id:
        reasons.append(ComparabilityReasonCode.MEASURAND_MISMATCH)
    if (
        left.identity.semantic.metric_definition.stable_id
        != right.identity.semantic.metric_definition.stable_id
    ):
        reasons.append(ComparabilityReasonCode.IDENTITY_MISMATCH)
    if _source_method_key(left) != _source_method_key(right):
        reasons.append(ComparabilityReasonCode.METHOD_MISMATCH)
    acquisition = compare_cmj_measurement_identities(
        left.identity,
        right.identity,
        claim=claim,
        request_id=InstanceIdentifier("comparability-request", f"{request_id.value}:source"),
        left_observation_id=left.observation_id,
        right_observation_id=right.observation_id,
    )
    reasons.extend(
        ComparabilityReasonCode(reason)
        for reason in acquisition.reason_codes
        if reason in {item.value for item in ComparabilityReasonCode}
    )
    unique_reasons = tuple(dict.fromkeys(reasons))
    if not unique_reasons:
        return _trial_comparability_result(request_id, ComparabilityState.COMPARABLE)
    state = (
        ComparabilityState.NOT_COMPARABLE
        if ComparabilityReasonCode.MEASURAND_MISMATCH in unique_reasons
        or ComparabilityReasonCode.IDENTITY_MISMATCH in unique_reasons
        else ComparabilityState.BRIDGE_VALIDATION_REQUIRED
    )
    return _trial_comparability_result(request_id, state, unique_reasons)


def _trial_comparability_result(
    request_id: InstanceIdentifier,
    state: ComparabilityState,
    reasons: tuple[ComparabilityReasonCode, ...] = (),
) -> ComparabilityResult:
    return ComparabilityResult(
        result_id=InstanceIdentifier(
            "comparability-result", f"{request_id.value}:{state.value.lower()}"
        ),
        request_id=request_id,
        state=state,
        reason_codes=tuple(reason.value for reason in reasons),
        conditions=(
            "a registered CMJ metric/method bridge is required before ranking or aggregation",
        )
        if reasons
        else (),
        transformations_required=(),
        missing_information=(),
        rule_reference=CMJ_SESSION_COMPARABILITY_RULE,
        evidence_references=(RES40_DECISION_SESSION_COMPARABILITY,),
        decided_by=ComparabilityDecisionSource.DETERMINISTIC_RULE,
    )


def _session_comparability_result(
    request: CMJSessionComparabilityRequest,
    state: ComparabilityState,
    reasons: tuple[ComparabilityReasonCode, ...] = (),
    *,
    conditions: tuple[str, ...] = (),
    missing_information: tuple[str, ...] = (),
    unresolved: bool = False,
) -> ComparabilityResult:
    return ComparabilityResult(
        result_id=InstanceIdentifier(
            "comparability-result", f"{request.request_id.value}:{state.value.lower()}"
        ),
        request_id=request.request_id,
        state=state,
        reason_codes=tuple(reason.value for reason in reasons),
        conditions=conditions,
        transformations_required=(),
        missing_information=missing_information,
        rule_reference=None if unresolved else CMJ_SESSION_COMPARABILITY_RULE,
        evidence_references=() if unresolved else (RES40_DECISION_SESSION_COMPARABILITY,),
        decided_by=(
            ComparabilityDecisionSource.UNRESOLVED
            if unresolved
            else ComparabilityDecisionSource.DETERMINISTIC_RULE
        ),
    )


def _comparison_refusal(
    result: ComparabilityResult,
    *,
    category: RefusalReasonCode,
    claim: str,
    observation_ids: tuple[InstanceIdentifier, ...],
) -> RefusalResult:
    reasons: list[RefusalReasonCode] = [category]
    for code in result.reason_codes:
        try:
            normalized = ComparabilityReasonCode(code)
        except ValueError:
            continue
        mapped = _REFUSAL_REASON_MAP.get(normalized)
        if mapped is not None and mapped not in reasons:
            reasons.append(mapped)
    missing = result.missing_information or (
        "directly comparable CMJ observations under the existing registered authority",
    )
    return _session_refusal(
        claim,
        tuple(reasons),
        missing,
        observation_ids=observation_ids,
        refusal_class=RefusalClass.COMPARABILITY_UNESTABLISHED,
    )


_REFUSAL_REASON_MAP: dict[ComparabilityReasonCode, RefusalReasonCode] = {
    ComparabilityReasonCode.MEASURAND_MISMATCH: RefusalReasonCode.MEASURAND_MISMATCH,
    ComparabilityReasonCode.IDENTITY_MISMATCH: RefusalReasonCode.METRIC_DEFINITION_MISMATCH,
    ComparabilityReasonCode.METHOD_MISMATCH: RefusalReasonCode.NO_REGISTERED_OPERATION,
    ComparabilityReasonCode.ESTIMATOR_MISMATCH: RefusalReasonCode.ESTIMATOR_MISMATCH,
    ComparabilityReasonCode.EVENT_DEFINITION_MISMATCH: RefusalReasonCode.EVENT_DEFINITION_MISMATCH,
    ComparabilityReasonCode.EVENT_METHOD_MISMATCH: RefusalReasonCode.EVENT_METHOD_MISMATCH,
    ComparabilityReasonCode.EVENT_PARAMETER_MISMATCH: RefusalReasonCode.EVENT_PARAMETER_MISMATCH,
    ComparabilityReasonCode.PHASE_SYSTEM_MISMATCH: RefusalReasonCode.PHASE_METHOD_MISMATCH,
    ComparabilityReasonCode.PHASE_DEFINITION_MISMATCH: RefusalReasonCode.PHASE_METHOD_MISMATCH,
    ComparabilityReasonCode.PHASE_BOUNDARY_METHOD_MISMATCH: RefusalReasonCode.PHASE_METHOD_MISMATCH,
    ComparabilityReasonCode.PHASE_METRIC_METHOD_MISMATCH: RefusalReasonCode.PHASE_METHOD_MISMATCH,
    ComparabilityReasonCode.DEVICE_MISMATCH: RefusalReasonCode.DEVICE_BRIDGE_NOT_REGISTERED,
    ComparabilityReasonCode.PROTOCOL_MISMATCH: RefusalReasonCode.PROTOCOL_IDENTITY_MISMATCH,
    ComparabilityReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH: (
        RefusalReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH
    ),
    ComparabilityReasonCode.PROCESSING_STATE_MISMATCH: (RefusalReasonCode.PROCESSING_STATE_UNKNOWN),
    ComparabilityReasonCode.UNIT_OR_NORMALIZATION_MISMATCH: (
        RefusalReasonCode.UNIT_OR_NORMALIZATION_MISMATCH
    ),
    ComparabilityReasonCode.ZERO_VELOCITY_REFERENCE_MISMATCH: (
        RefusalReasonCode.ZERO_VELOCITY_REFERENCE_MISMATCH
    ),
    ComparabilityReasonCode.SYSTEM_DEFINITION_MISMATCH: (
        RefusalReasonCode.SYSTEM_DEFINITION_UNRESOLVED
    ),
    ComparabilityReasonCode.SOURCE_PROCESSING_MISMATCH: (
        RefusalReasonCode.SOURCE_PROCESSING_MISMATCH
    ),
}


def _session_refusal(
    claim: str,
    reason_codes: Sequence[str | RefusalReasonCode],
    missing_information: Sequence[str],
    *,
    observation_ids: Sequence[InstanceIdentifier] = (),
    refusal_class: RefusalClass = RefusalClass.DATA_ADEQUACY_INSUFFICIENT,
) -> RefusalResult:
    normalized_reasons = tuple(
        dict.fromkeys(
            reason.value if isinstance(reason, RefusalReasonCode) else reason
            for reason in reason_codes
        )
    )
    normalized_observations: tuple[InstanceIdentifier, ...] = _unique_tuple(observation_ids)
    digest = canonical_hash(
        {
            "claim": claim,
            "reason_codes": normalized_reasons,
            "observation_ids": normalized_observations,
        }
    ).removeprefix("sha256:")[:24]
    return RefusalResult(
        refusal_id=InstanceIdentifier("refusal", f"res40:{digest}"),
        status=RefusalStatus.REFUSED,
        refusal_class=refusal_class,
        blocked_claim=claim,
        reason_codes=normalized_reasons,
        missing_information=tuple(missing_information),
        what_can_still_be_safely_described=(
            "declared trial identities and independently valid source observations remain intact",
            "no session summary is emitted from the refused input set",
        ),
        evidence_references=(RES40_DECISION_TRIAL_SELECTION, RES40_DECISION_SESSION_AGGREGATION),
        observation_ids=normalized_observations,
    )


def _observation(value: CMJTrialMetricValue) -> ScientificMeasurementObservation:
    if isinstance(value, ScientificMeasurementObservation):
        return value
    return value.observation


def _observation_ids(
    values: Sequence[ScientificMeasurementObservation],
) -> tuple[InstanceIdentifier, ...]:
    return _unique_tuple(item.observation_id for item in values)


def _observation_ids_for_values(
    values: Iterable[CMJTrialMetricValue] | object,
) -> tuple[InstanceIdentifier, ...]:
    if not isinstance(values, Iterable) or isinstance(values, str | bytes):
        return ()
    return _unique_tuple(_observation(item).observation_id for item in values)


def _decision_observation_ids(
    decisions: Sequence[TrialEligibilityDecision],
) -> tuple[InstanceIdentifier, ...]:
    return _unique_tuple(
        observation_id for decision in decisions for observation_id in decision.observation_ids
    )


def _unique_tuple[T](values: Iterable[T] | object) -> tuple[T, ...]:
    if not isinstance(values, Iterable):
        return ()
    result: list[T] = []
    for value in values:
        if value not in result:
            result.append(value)
    return tuple(result)


def _append_same[T](
    values: list[T],
    value: T,
    key: Callable[[T], object],
) -> bool:
    identifier = key(value)
    for existing in values:
        if key(existing) == identifier:
            return existing == value
    values.append(value)
    return True


def _append_unique_items[T](values: list[T], additions: Sequence[T]) -> None:
    for value in additions:
        if value not in values:
            values.append(value)


def _numeric_value(observation: ScientificMeasurementObservation) -> float | None:
    if observation.result.status is not ResultStatus.VALID:
        return None
    value = observation.result.value
    if not isinstance(value, ScalarValue) or isinstance(value.value, bool):
        return None
    if not isinstance(value.value, int | float) or not math.isfinite(float(value.value)):
        return None
    return float(value.value)


def _metric_reference(value: CMJTrialMetricValue) -> RegistryReference:
    return _observation(value).identity.semantic.metric_definition


def _method_reference(value: CMJTrialMetricValue) -> RegistryReference | None:
    if isinstance(value, CMJJumpHeightResult):
        return value.method.reference
    identity = _observation(value).identity
    return (
        identity.processing.estimator
        or identity.processing.registered_operation
        or identity.version.processing_method
    )


def _metric_kind(value: CMJTrialMetricValue) -> str:
    if isinstance(value, CMJJumpHeightResult):
        return "JUMP_HEIGHT"
    if isinstance(value, CMJPhaseMetricResult):
        return "PHASE_METRIC"
    if isinstance(value, _MECHANICS_TYPES):
        return "MECHANICS"
    if isinstance(value, _DERIVED_TYPES):
        return "DERIVED"
    return "OBSERVATION"


def _phase_identity(
    value: CMJTrialMetricValue,
) -> tuple[RegistryReference | None, tuple[RegistryReference, ...]]:
    if isinstance(value, CMJPhaseMetricResult):
        return value.phase_occurrence.phase_system, (value.phase_occurrence.phase_definition,)
    identity = _observation(value).identity
    return None, identity.processing.phase_definitions


def _reference_id(reference: RegistryReference | None) -> str:
    return reference.stable_id if reference is not None else "not_applicable"


def _same_reference(
    left: RegistryReference | UnitReference | None,
    right: RegistryReference | UnitReference | None,
) -> bool:
    if left is None or right is None:
        return left is right
    return left.identifier.stable_id == right.identifier.stable_id


def _same_reference_tuple(
    left: tuple[RegistryReference, ...], right: tuple[RegistryReference, ...]
) -> bool:
    return tuple(item.stable_id for item in left) == tuple(item.stable_id for item in right)


def _method_mismatch_reason(
    left_kind: str,
    right_kind: str,
) -> ComparabilityReasonCode:
    if left_kind == "JUMP_HEIGHT" or right_kind == "JUMP_HEIGHT":
        return ComparabilityReasonCode.ESTIMATOR_MISMATCH
    if left_kind == "PHASE_METRIC" or right_kind == "PHASE_METRIC":
        return ComparabilityReasonCode.PHASE_METRIC_METHOD_MISMATCH
    return ComparabilityReasonCode.METHOD_MISMATCH


def _source_method_key(value: CMJTrialMetricValue) -> str:
    if isinstance(value, CMJPhaseMetricResult):
        return canonical_json(_phase_metric_method_key(value))
    if isinstance(value, CMJJumpHeightResult):
        return canonical_json(
            {
                "kind": "JUMP_HEIGHT",
                "method": value.method,
                "gravity": value.parameters.gravity,
                "source_identity": _identity_method_key(value.observation.identity),
                "source_timebase": _timebase_method_key(value.parameters.source_timebase),
                "takeoff_event": _event_method_key(value.takeoff_event),
                "landing_event": _event_method_key(value.landing_event),
            }
        )
    observation = _observation(value)
    return canonical_json(
        {
            "kind": _metric_kind(value),
            "identity": _identity_method_key(observation.identity),
        }
    )


def _identity_method_key(identity: object) -> object:
    if not isinstance(identity, CMJMeasurementIdentity):
        return ("UNRESOLVED", type(identity).__name__)
    acquisition = identity.acquisition
    processing = identity.processing
    return {
        "semantic": {
            "construct": identity.semantic.construct,
            "test_family": identity.semantic.test_family,
            "protocol": identity.semantic.protocol,
            "protocol_identity": identity.semantic.protocol_identity,
            "measurand": identity.semantic.measurand,
            "metric": identity.semantic.metric_definition,
        },
        "acquisition": {
            "device": acquisition.device,
            "measuring_system": acquisition.measuring_system,
            "hardware_firmware": acquisition.hardware_firmware,
            "sensor_channel": acquisition.sensor_channel,
            "sampling": acquisition.sampling,
            "calibration_reference": acquisition.calibration_reference,
            "physical_axis": acquisition.physical_axis,
            "reference_frame": acquisition.reference_frame,
            "unit": acquisition.unit,
            "sign_convention": acquisition.sign_convention,
            "timebase": _timebase_method_key(acquisition.timebase),
            "acquisition_software_version": acquisition.acquisition_software_version,
            "calibration": acquisition.calibration,
            "zeroing": acquisition.zeroing,
            "processing_state": acquisition.processing_state,
            "arrangement": acquisition.arrangement,
            "channel": acquisition.channel,
            "available_channels": acquisition.available_channels,
            "combination_lineage": acquisition.combination_lineage,
        },
        "processing": {
            "registered_operation": processing.registered_operation,
            "estimator": processing.estimator,
            "filtering": processing.filtering,
            "differentiation_method": processing.differentiation_method,
            "integration_method": processing.integration_method,
            "unit": processing.unit,
            "sign_convention": processing.sign_convention,
            "normalization": processing.normalization,
            "event_definitions": processing.event_definitions,
            "phase_definitions": processing.phase_definitions,
            "trial_selection": processing.trial_selection,
            "aggregation": processing.aggregation,
            "method_parameters": _method_metadata_key(processing.method_parameters),
        },
        "version": identity.version,
    }


_INSTANCE_METADATA_KEYS = frozenset(
    {
        "source_id",
        "source_signal_id",
        "source_signal_ids",
        "source_observation_id",
        "source_observation_ids",
        "source_artifact_id",
        "source_artifact_ids",
        "source_acquisition_id",
        "source_acquisition_ids",
        "source_measurement_identity_id",
        "source_measurement_identity_ids",
        "source_event_id",
        "source_event_ids",
        "event_id",
        "event_ids",
        "source_sample_count",
        "sample_index",
        "sample_indices",
        "search_end_index",
        "start_index",
        "end_index",
        "event_time_s",
        "time_s",
        "timestamp",
    }
)
_INSTANCE_METADATA_SUFFIXES = (
    "_observation_id",
    "_signal_id",
    "_artifact_id",
    "_acquisition_id",
    "_identity_id",
    "_event_id",
    "_event_ids",
    "_occurrence_id",
    "_sample_index",
    "_start_index",
    "_end_index",
    "_time_s",
    "_timestamp",
)


def _method_metadata_key(parameters: tuple[MetadataEntry, ...]) -> tuple[tuple[str, object], ...]:
    return tuple(
        (entry.key, entry.value)
        for entry in parameters
        if entry.key not in _INSTANCE_METADATA_KEYS
        and not entry.key.endswith(_INSTANCE_METADATA_SUFFIXES)
    )


def _timebase_method_key(timebase: SignalTimebase | object | None) -> object:
    if isinstance(timebase, RegularTimebase):
        return ("REGULAR", timebase.sample_rate_hz)
    if isinstance(timebase, ExplicitTimebase):
        return ("EXPLICIT",)
    return ("UNKNOWN", type(timebase).__name__ if timebase is not None else None)


def _event_method_key(event: object | None) -> object:
    if event is None:
        return None
    detector_method = getattr(event, "detector_method", None)
    parameters = getattr(event, "detector_parameters", None)
    definition = getattr(getattr(event, "definition", None), "reference", None)
    if detector_method is None or parameters is None:
        return ("UNRESOLVED",)
    baseline_segment = parameters.baseline_segment
    return {
        "definition": definition,
        "method": detector_method.reference,
        "threshold_family": detector_method.threshold_family,
        "threshold_n": parameters.threshold_n,
        "baseline_selection_method": baseline_segment.selection_method
        if baseline_segment is not None
        else None,
        "baseline_selection_parameters": _method_metadata_key(baseline_segment.selection_parameters)
        if baseline_segment is not None
        else None,
        "sigma_multiplier": parameters.sigma_multiplier,
        "direction": parameters.direction,
        "dwell_samples": parameters.dwell_samples,
        "search_start_index": parameters.search_start_index,
        "timebase": _timebase_method_key(getattr(event, "source_timebase", None)),
    }


__all__ = [
    "RES40_SOFTWARE_VERSION",
    "CMJSessionComparabilityRequest",
    "CMJTrialMetricValue",
    "DeclaredCandidateTrialSet",
    "RankingDirection",
    "SessionAggregationResult",
    "TrialEligibilityDecision",
    "TrialEligibilityStatus",
    "TrialMetricInputs",
    "TrialSelectionDecision",
    "TrialSelectionDirection",
    "aggregate_cmj_session",
    "aggregate_cmj_trial_metrics",
    "compare_cmj_session_results",
    "compare_cmj_session_summaries",
    "evaluate_trial_eligibility",
    "project_selected_trial",
    "refusal_for_cmj_session_comparability",
    "select_trials",
]
