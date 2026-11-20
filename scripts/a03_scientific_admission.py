"""Request-local binding for untrusted V3 model proposals and trusted RES-62 source inputs."""

from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import combinations
from typing import Any, Literal

from dynamislm.analysis.authority import authorize_analysis
from dynamislm.analysis.models import (
    AnalysisAuthorization,
    AnalysisAuthorizationRequest,
    AnalysisClass,
    AnalysisEstimandLevel,
    AnalysisLevelIdentity,
    AnalysisUnitOfAnalysis,
)
from dynamislm.claims import authorize_claim, validate_claim_authority
from dynamislm.claims.models import (
    ClaimAuthorityResult,
    ClaimIntent,
    ClaimTarget,
    MeasurementClaimLevel,
    RelationshipClaimLevel,
)
from dynamislm.comparability import (
    CrossSourceComparabilityRequest,
    ObservationAuthorityReference,
    SemanticIdentityKey,
    assess_cross_source_comparability,
)
from dynamislm.evidence.res70 import ClaimEvidenceApplicability
from dynamislm.longitudinal.models import (
    LongitudinalAthletePerformanceRecord,
    LongitudinalObservationEntry,
    MultiSourceAnalysisInput,
)
from dynamislm.longitudinal.statistics import (
    RES69_ABSOLUTE_CHANGE_ESTIMATOR,
    RES69_ABSOLUTE_CHANGE_OPERATION,
    RES69_CHANGE_ESTIMAND,
    StatisticalResult,
    StatisticalSupport,
    SupportEntryExclusion,
    SupportExclusionReason,
    build_statistical_support,
    calculate_absolute_change,
    validate_statistical_result,
)
from dynamislm.longitudinal.statistics.support import (
    StatisticalConstraintError,
    exact_common_unit,
    validate_comparable_entries,
)
from dynamislm.measurement.identity import (
    InstanceIdentifier,
    RegistryReference,
    ScientificIdentifier,
)
from dynamislm.measurement.observation import ScientificMeasurementObservation
from dynamislm.measurement.result import ScalarValue
from dynamislm.qualification import OperationDisposition
from dynamislm.qualification.inventory import _metadata, _metadata_for_id
from dynamislm.refusal import RefusalResult
from scripts import a02_v3_contract as v3


class ProposalError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Proposal:
    analysis: AnalysisClass | None
    observation_ids: tuple[str, ...]
    operation: str | None
    measurement: tuple[MeasurementClaimLevel, ...]
    relationship: tuple[RelationshipClaimLevel, ...]


@dataclass(frozen=True)
class BoundRequest:
    """Created by the host using its authenticated source selection for this interaction.

    Only question text and generated action bytes come from untrusted parties. Source objects
    and explicit claim requests from a typed host workflow use separate arguments.
    """

    question: str
    source: MultiSourceAnalysisInput | None
    records: tuple[LongitudinalAthletePerformanceRecord, ...]
    required_measurement: tuple[MeasurementClaimLevel, ...] = ()
    required_relationship: tuple[RelationshipClaimLevel, ...] = ()
    evidence_applicability: ClaimEvidenceApplicability | None = None

    @property
    def entries(self) -> tuple[LongitudinalObservationEntry, ...]:
        return self.source.entries if self.source is not None else ()

    def model_request(self) -> dict[str, Any]:
        if not isinstance(self.question, str):
            raise ProposalError("V3_INVALID_REQUEST")
        rows = []
        for entry in self.entries:
            observation = entry.observation
            identity = observation.identity
            result = observation.result
            rows.append(
                {
                    "date": entry.observed_at.isoformat(),
                    "measurement": identity.semantic.metric_definition.stable_id,
                    "protocol": identity.semantic.protocol.stable_id
                    if identity.semantic.protocol
                    else None,
                    "device": identity.acquisition.device.stable_id
                    if identity.acquisition.device
                    else None,
                    "value": result.value.value if isinstance(result.value, ScalarValue) else None,
                    "unit": result.unit.display_label if result.unit else None,
                }
            )
        return {
            "question": self.question,
            "observations": rows,
            "requested_claims": {
                "measurement": [level.value for level in self.required_measurement],
                "relationship": [level.value for level in self.required_relationship],
            },
        }

    def parse(self, raw: object) -> Proposal:
        try:
            ids = v3.observation_ids(self.model_request())
        except (TypeError, ValueError) as exc:
            raise ProposalError("V3_INVALID_REQUEST") from exc
        try:
            action = v3.parse_action(
                raw, [f"observation-{i}" for i in range(1, v3.MAX_OBSERVATIONS + 1)]
            )
        except (TypeError, ValueError) as exc:
            raise ProposalError("V3_INVALID_PROPOSAL") from exc
        refs = tuple(action["observation_ids"])
        if not set(refs).issubset(ids):
            raise ProposalError("V3_OBSERVATION_REFERENCE_UNRESOLVED")
        operation = action["operation"]
        return Proposal(
            analysis=AnalysisClass(action["analysis_class"])
            if action["analysis_class"] != v3.NONE
            else None,
            observation_ids=refs,
            operation=operation if operation != v3.NONE else None,
            measurement=tuple(
                MeasurementClaimLevel(level) for level in action["target_claims"]["measurement"]
            ),
            relationship=tuple(
                RelationshipClaimLevel(level) for level in action["target_claims"]["relationship"]
            ),
        )

    def resolve(self, proposal: Proposal) -> StatisticalSupport:
        if self.source is None or not proposal.observation_ids:
            raise ProposalError("V3_OBSERVATION_REFERENCE_UNRESOLVED")
        have = {f"observation-{index}": entry for index, entry in enumerate(self.entries, 1)}
        if not set(proposal.observation_ids).issubset(have):
            raise ProposalError("V3_OBSERVATION_REFERENCE_UNRESOLVED")
        if not self.records:
            raise ProposalError("V3_SOURCE_PROVENANCE_UNRESOLVED")
        selected = set(proposal.observation_ids)
        try:
            return build_statistical_support(
                self.source,
                (entry for alias, entry in have.items() if alias in selected),
                source_records=self.records,
                excluded_entries=tuple(
                    SupportEntryExclusion.from_entry(entry, SupportExclusionReason.NOT_SELECTED)
                    for alias, entry in have.items()
                    if alias not in selected
                ),
            )
        except ValueError as exc:
            raise ProposalError("V3_SOURCE_PROVENANCE_UNRESOLVED") from exc


@dataclass(frozen=True)
class Admission:
    model_proposal: Proposal | None = None
    trusted_admission: Literal["NOT_REACHED", "REFUSED", "RESOLVED"] = "NOT_REACHED"
    execution_authorized: bool = False
    operation_executed: bool = False
    analysis_authorization: AnalysisAuthorization | None = None
    claim_authority: ClaimAuthorityResult | None = None
    final_grounding_status: Literal["NOT_IMPLEMENTED"] = "NOT_IMPLEMENTED"
    outcome: Literal["REFUSED", "ABSTAINED", "GROUNDED_RESULT"] = "REFUSED"
    reason_codes: tuple[str, ...] = ()
    result: StatisticalResult | None = None
    observations: tuple[ScientificMeasurementObservation, ...] = ()


def _claim_decision(intent: ClaimIntent) -> ClaimAuthorityResult:
    decision = authorize_claim(intent)
    validate_claim_authority(decision, intent)
    return decision


def _allows(decision: ClaimAuthorityResult, proposal: Proposal) -> bool:
    return set(proposal.measurement).issubset(decision.allowed_measurement_levels) and set(
        proposal.relationship
    ).issubset(decision.allowed_relationship_levels)


def submit_scientific_action_v3(bound: BoundRequest, raw: object) -> Admission:
    """Adjudicate this interaction's generated tool call. All dispatch is local and registered."""
    try:
        proposal = bound.parse(raw)
    except ProposalError as exc:
        return Admission(reason_codes=(exc.code,))
    trace = Admission(model_proposal=proposal, trusted_admission="REFUSED")
    if not (
        set(bound.required_measurement).issubset(proposal.measurement)
        and set(bound.required_relationship).issubset(proposal.relationship)
    ):
        return replace(trace, reason_codes=("V3_REQUESTED_CLAIM_OMITTED",))
    if proposal.analysis is None and proposal.operation is not None:
        return replace(trace, reason_codes=("V3_OPERATION_ANALYSIS_MISMATCH",))
    if not (proposal.measurement or proposal.relationship):
        if proposal.analysis is None and not proposal.observation_ids:
            return replace(
                trace,
                trusted_admission="NOT_REACHED",
                outcome="ABSTAINED",
                reason_codes=("V3_NO_ACTION_PROPOSED",),
            )
        return replace(trace, reason_codes=("V3_CLAIM_REQUIRED",))
    try:
        support = bound.resolve(proposal)
    except ProposalError as exc:
        return replace(trace, reason_codes=(exc.code,))

    entries = support.included_entries
    observations = tuple(entry.observation for entry in entries)
    evidence = bound.evidence_applicability
    identity = v3.sha256(
        v3.canonical(
            [
                bound.model_request(),
                raw,
                support.canonical_support_hash,
            ]
        ).encode()
    )
    claim_ref = RegistryReference(
        ScientificIdentifier("dynamislm", "claim-intent", identity, "1.0.0"), "V3 claim"
    )
    if evidence is not None and evidence.claim_intent_reference != claim_ref:
        return replace(trace, reason_codes=("RES70_INSUFFICIENT_EVIDENCE_APPLICABILITY",))
    intent = ClaimIntent(
        claim_reference=claim_ref,
        measurement_level=next(
            (
                MeasurementClaimLevel(level)
                for level in reversed(v3.MEASUREMENT_LEVELS)
                if level in proposal.measurement
            ),
            None,
        ),
        relationship_level=next(
            (
                RelationshipClaimLevel(level)
                for level in reversed(v3.RELATIONSHIP_LEVELS)
                if level in proposal.relationship
            ),
            None,
        ),
        predictive_intent=None,
        target=ClaimTarget.ATHLETE_WITHIN,
        analysis_reference=None,
        evidence_applicability_reference=evidence.claim_intent_reference if evidence else None,
        decision_criterion_reference=None,
        observations=observations,
        evidence_applicability=evidence,
    )
    trace = replace(trace, trusted_admission="RESOLVED")
    if proposal.analysis is None:
        claim = _claim_decision(intent)
        if not _allows(claim, proposal):
            return replace(trace, claim_authority=claim, reason_codes=claim.reason_codes)
        return replace(
            trace, outcome="GROUNDED_RESULT", claim_authority=claim, observations=observations
        )

    contexts = tuple(entry.football_context for entry in entries)
    pairs = tuple(
        CrossSourceComparabilityRequest(
            request_id=InstanceIdentifier(
                "cross-source-comparability-request", f"{identity}-{index}"
            ),
            left_observation=ObservationAuthorityReference.from_observation(left),
            right_observation=ObservationAuthorityReference.from_observation(right),
            claim_intent=claim_ref,
        )
        for index, (left, right) in enumerate(combinations(observations, 2))
        if SemanticIdentityKey.from_identity(left.identity)
        != SemanticIdentityKey.from_identity(right.identity)
        or left.result.unit != right.result.unit
    )
    decisions = tuple(
        assess_cross_source_comparability(pair, observations, football_contexts=contexts)
        for pair in pairs
    )
    request = AnalysisAuthorizationRequest(
        request_id=InstanceIdentifier("analysis-authorization-request", identity),
        analysis_class=proposal.analysis,
        support=support,
        support_reference=None,
        observations=observations,
        identity_hashes=(),
        comparability_decisions=decisions,
        requested_level=AnalysisLevelIdentity(
            AnalysisUnitOfAnalysis.ATHLETE, AnalysisEstimandLevel.WITHIN_ATHLETE, "athlete_id"
        ),
        evidence_applicability=evidence,
        context_references=(),
        comparability_requests=pairs,
    )
    authorization = authorize_analysis(request)
    if isinstance(authorization, RefusalResult):
        return replace(trace, reason_codes=authorization.reason_codes)
    trace = replace(trace, analysis_authorization=authorization)
    operation = authorization.operation_reference
    if operation is None or proposal.operation != operation.stable_id:
        return replace(trace, reason_codes=("V3_OPERATION_ANALYSIS_MISMATCH",))
    if operation != RES69_ABSOLUTE_CHANGE_OPERATION:
        return replace(trace, reason_codes=("COMPUTATION_NOT_REGISTERED",))
    # Full inventory discovery imports checkout-only empirical adapters.
    registered = _metadata_for_id(operation.stable_id, _metadata())
    if (
        registered.version != operation.identifier.version
        or registered.disposition is not OperationDisposition.IMPLEMENTED
    ):
        return replace(trace, reason_codes=("COMPUTATION_NOT_REGISTERED",))

    intent = replace(
        intent,
        analysis_reference=authorization.capability_reference,
        analysis_authorization=authorization,
        analysis_authorization_request=request,
        comparability_decisions=decisions,
        comparability_requests=pairs,
    )
    provisional = _claim_decision(intent)
    # The only pre-execution deferral is the missing result of this authorized operation.
    if provisional.missing_information != ("StatisticalResult",) or provisional.reason_codes != (
        "RES70_STATISTICAL_AUTHORITY_INSUFFICIENT",
    ):
        return replace(
            trace,
            claim_authority=provisional,
            reason_codes=provisional.reason_codes or ("V3_REGISTERED_RESULT_CLAIM_REQUIRED",),
        )
    try:
        unit = exact_common_unit(entries)
        validate_comparable_entries(support, entries)
    except ValueError as exc:
        return replace(
            trace,
            reason_codes=(
                exc.code
                if isinstance(exc, StatisticalConstraintError)
                else "V3_INCOMPATIBLE_SCALAR_SUPPORT",
            ),
        )

    if entries[0].observed_at == entries[1].observed_at:
        return replace(trace, reason_codes=("RES69_DUPLICATE_TIMESTAMP",))
    trace = replace(trace, execution_authorized=True, operation_executed=True)
    result = calculate_absolute_change(support)
    if isinstance(result, RefusalResult):
        return replace(trace, reason_codes=result.reason_codes)
    if (
        not isinstance(result, StatisticalResult)
        or result.operation != operation
        or result.analysis_run.operation != operation
        or result.support != support
        or result.analysis_run.estimator != RES69_ABSOLUTE_CHANGE_ESTIMATOR
        or len(result.estimates) != 1
        or result.estimates[0].estimand != RES69_CHANGE_ESTIMAND
        or result.estimates[0].estimator != RES69_ABSOLUTE_CHANGE_ESTIMATOR
        or result.estimates[0].unit != unit
    ):
        return replace(trace, reason_codes=("V3_EXECUTOR_RESULT_UNBOUND",))
    validate_statistical_result(result)
    claim = _claim_decision(replace(intent, statistical_result=result))
    if not _allows(claim, proposal):
        return replace(trace, claim_authority=claim, reason_codes=claim.reason_codes)
    return replace(
        trace,
        outcome="GROUNDED_RESULT",
        claim_authority=claim,
        result=result,
        observations=observations,
    )
