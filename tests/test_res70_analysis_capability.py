from __future__ import annotations

from dynamislm import (
    AnalysisAuthorization,
    AnalysisAuthorizationRequest,
    AnalysisClass,
    AnalysisEstimandLevel,
    AnalysisLevelIdentity,
    AnalysisUnitOfAnalysis,
    InstanceIdentifier,
    authorize_analysis,
)
from dynamislm.refusal import RefusalResult
from test_longitudinal_statistics import _entries, _support


def _request(
    analysis_class: AnalysisClass,
    *,
    level: AnalysisEstimandLevel,
) -> AnalysisAuthorizationRequest:
    entries = _entries((10.0, 12.0), prefix=f"res70-{analysis_class.value.lower()}")
    support = _support(entries)
    return AnalysisAuthorizationRequest(
        request_id=InstanceIdentifier(
            "analysis-authorization-request", f"{analysis_class.value.lower()}-request"
        ),
        analysis_class=analysis_class,
        support=support,
        support_reference=None,
        observations=tuple(entry.observation for entry in entries),
        identity_hashes=(),
        comparability_decisions=(),
        requested_level=AnalysisLevelIdentity(
            unit_of_analysis=AnalysisUnitOfAnalysis.ATHLETE,
            estimand_level=level,
            subject_key="athlete_id",
            clustering_keys=("athlete_id", "session_id"),
            grouping_keys=(),
        ),
        evidence_applicability=None,
        context_references=(),
    )


def test_scalar_absolute_change_consumes_res69_and_authorizes_exact_support() -> None:
    request = _request(
        AnalysisClass.SCALAR_ABSOLUTE_CHANGE,
        level=AnalysisEstimandLevel.WITHIN_ATHLETE,
    )

    result = authorize_analysis(request)

    assert isinstance(result, AnalysisAuthorization)
    assert result.operation_reference is not None
    assert result.support_hashes == (request.support.canonical_support_hash,)  # type: ignore[union-attr]
    assert result.resolved_level.estimand_level is AnalysisEstimandLevel.WITHIN_ATHLETE


def test_missing_prerequisite_returns_structured_refusal() -> None:
    request = _request(
        AnalysisClass.SCALAR_ABSOLUTE_CHANGE,
        level=AnalysisEstimandLevel.WITHIN_ATHLETE,
    )
    request = AnalysisAuthorizationRequest(
        request_id=request.request_id,
        analysis_class=request.analysis_class,
        support=None,
        support_reference=None,
        observations=(),
        identity_hashes=(),
        comparability_decisions=(),
        requested_level=request.requested_level,
        evidence_applicability=None,
        context_references=(),
    )

    result = authorize_analysis(request)

    assert isinstance(result, RefusalResult)
    assert result.refusal_class.value == "DATA_ADEQUACY_INSUFFICIENT"
    assert "RES70_STATISTICAL_AUTHORITY_INSUFFICIENT" in result.reason_codes


def test_deferred_repeated_measures_capability_is_not_executable() -> None:
    request = _request(
        AnalysisClass.WITHIN_ATHLETE_ASSOCIATION,
        level=AnalysisEstimandLevel.WITHIN_ATHLETE,
    )

    result = authorize_analysis(request)

    assert isinstance(result, RefusalResult)
    assert "COMPUTATION_NOT_REGISTERED" in result.reason_codes


def test_relative_change_refuses_without_canonical_res69_scale_authority() -> None:
    request = _request(
        AnalysisClass.SCALAR_RELATIVE_CHANGE,
        level=AnalysisEstimandLevel.WITHIN_ATHLETE,
    )

    result = authorize_analysis(request)

    assert isinstance(result, RefusalResult)
    assert "RES70_STATISTICAL_AUTHORITY_INSUFFICIENT" in result.reason_codes


def test_between_level_cannot_be_relabelled_for_within_scalar_change() -> None:
    request = _request(
        AnalysisClass.SCALAR_ABSOLUTE_CHANGE,
        level=AnalysisEstimandLevel.BETWEEN_ATHLETE,
    )

    result = authorize_analysis(request)

    assert isinstance(result, RefusalResult)
    assert "RES70_WRONG_LEVEL_OF_ANALYSIS" in result.reason_codes
