"""Frozen capability/family coverage matrix and representability validation."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from dynamislm.benchmark.constants import (
    CAPABILITY_IDS,
    FAMILY_IDS,
    SPLIT_ORDER,
    CaseOrigin,
    ErrorClass,
    ScoringProfile,
    SplitName,
)
from dynamislm.benchmark.contracts import BenchmarkCaseV1
from dynamislm.serialization import canonical_hash


@dataclass(frozen=True, slots=True)
class CoverageRow:
    capability_id: str
    benchmark_families: tuple[str, ...]
    case_origins: tuple[CaseOrigin, ...]
    answer_authorities: tuple[str, ...]
    scorer_profiles: tuple[ScoringProfile, ...]
    adversarial_tags: tuple[str, ...]
    error_classes: tuple[ErrorClass, ...]
    split_coverage: tuple[SplitName, ...] = SPLIT_ORDER


def _row(
    capability: str,
    families: tuple[str, ...],
    origins: tuple[CaseOrigin, ...],
    authorities: tuple[str, ...],
    scorers: tuple[ScoringProfile, ...],
    tags: tuple[str, ...],
    errors: tuple[ErrorClass, ...],
) -> CoverageRow:
    return CoverageRow(capability, families, origins, authorities, scorers, tags, errors)


COVERAGE_MATRIX = (
    _row(
        "C01",
        ("F01", "F03", "F11"),
        (
            CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
            CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
            CaseOrigin.ADVERSARIAL_MUTATION,
        ),
        ("EXPERT_RUBRIC", "SOURCE_EVIDENCE_SPAN", "RES60_POPULATION"),
        (
            ScoringProfile.CLASSIFICATION_V1,
            ScoringProfile.STRUCTURED_FIELDS_V1,
            ScoringProfile.EVIDENCE_SPAN_V1,
        ),
        ("ALIAS_COLLISION", "SAME_LABEL_DIFFERENT_CONSTRUCT", "UNSUPPORTED_SYNONYM"),
        (ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE, ErrorClass.WRONG_MEASUREMENT_IDENTITY),
    ),
    _row(
        "C02",
        ("F02",),
        (
            CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
            CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
            CaseOrigin.ADVERSARIAL_MUTATION,
        ),
        ("EXPERT_RUBRIC", "SOURCE_EVIDENCE_SPAN", "RES60_POPULATION"),
        (
            ScoringProfile.STRUCTURED_FIELDS_V1,
            ScoringProfile.EVIDENCE_SPAN_V1,
            ScoringProfile.REFUSAL_V1,
        ),
        ("MISSING_DEVICE", "MISSING_THRESHOLD", "MISSING_EVENT", "MISSING_PHASE"),
        (ErrorClass.WRONG_MEASUREMENT_IDENTITY, ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE),
    ),
    _row(
        "C03",
        ("F01", "F03", "F04", "F13"),
        (
            CaseOrigin.DETERMINISTIC_ENGINE_DERIVED,
            CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
            CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
            CaseOrigin.ADVERSARIAL_MUTATION,
        ),
        ("RES71_REFERENCE_CASE", "RES70_COMPARABILITY", "EXPERT_RUBRIC", "SOURCE_EVIDENCE_SPAN"),
        (
            ScoringProfile.CLASSIFICATION_V1,
            ScoringProfile.STRUCTURED_FIELDS_V1,
            ScoringProfile.COMPARABILITY_V1,
        ),
        ("SAME_LABEL_DIFFERENT_MEASURAND", "METHOD_VERSION_COLLISION", "ESTIMATOR_RELABEL"),
        (
            ErrorClass.WRONG_MEASUREMENT_IDENTITY,
            ErrorClass.FALSE_COMPARABILITY_ACCEPTANCE,
            ErrorClass.DIRECT_DERIVED_COLLAPSE,
        ),
    ),
    _row(
        "C04",
        ("F03", "F05", "F10", "F13"),
        (
            CaseOrigin.DETERMINISTIC_ENGINE_DERIVED,
            CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
            CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
            CaseOrigin.ADVERSARIAL_MUTATION,
        ),
        ("RES71_REFERENCE_CASE", "RES70_CLAIM", "EXPERT_RUBRIC", "SOURCE_EVIDENCE_SPAN"),
        (ScoringProfile.CLASSIFICATION_V1, ScoringProfile.STRUCTURED_FIELDS_V1),
        ("PROVIDER_DERIVED_AS_DIRECT", "MODEL_ESTIMATE_AS_MEASUREMENT", "LATENT_INFERENCE"),
        (
            ErrorClass.DIRECT_DERIVED_COLLAPSE,
            ErrorClass.UNSUPPORTED_LATENT_OR_PHYSIOLOGICAL_INFERENCE,
        ),
    ),
    _row(
        "C05",
        ("F03", "F04", "F06", "F05"),
        (
            CaseOrigin.DETERMINISTIC_ENGINE_DERIVED,
            CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
            CaseOrigin.ADVERSARIAL_MUTATION,
        ),
        ("RES71_REFERENCE_CASE", "RES70_COMPARABILITY", "EXPERT_RUBRIC"),
        (
            ScoringProfile.NUMERIC_TOLERANCE_V1,
            ScoringProfile.CLASSIFICATION_V1,
            ScoringProfile.STRUCTURED_FIELDS_V1,
        ),
        ("UNIT_CONVERSION_WITHOUT_PROVENANCE", "WRONG_DENOMINATOR", "NORMALIZATION_SHORTCUT"),
        (
            ErrorClass.INVENTED_NUMERICAL_SCIENCE,
            ErrorClass.FALSE_COMPARABILITY_ACCEPTANCE,
            ErrorClass.WRONG_MEASUREMENT_IDENTITY,
        ),
    ),
    _row(
        "C06",
        ("F02", "F05", "F06", "F13"),
        (
            CaseOrigin.DETERMINISTIC_ENGINE_DERIVED,
            CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
            CaseOrigin.ADVERSARIAL_MUTATION,
        ),
        ("RES71_REFERENCE_CASE", "RES70_COMPARABILITY", "EXPERT_RUBRIC"),
        (
            ScoringProfile.CLASSIFICATION_V1,
            ScoringProfile.STRUCTURED_FIELDS_V1,
            ScoringProfile.REFUSAL_V1,
        ),
        ("FRAME_MISMATCH", "SIGN_MISMATCH", "EVENT_BOUNDARY", "INVALID_DOMAIN"),
        (
            ErrorClass.INVENTED_NUMERICAL_SCIENCE,
            ErrorClass.WRONG_MEASUREMENT_IDENTITY,
            ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE,
        ),
    ),
    _row(
        "C07",
        ("F04", "F06", "F13", "F14"),
        (
            CaseOrigin.DETERMINISTIC_ENGINE_DERIVED,
            CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
            CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
            CaseOrigin.ADVERSARIAL_MUTATION,
        ),
        ("RES71_REFERENCE_CASE", "RES70_COMPARABILITY", "SOURCE_EVIDENCE_SPAN", "EXPERT_RUBRIC"),
        (
            ScoringProfile.COMPARABILITY_V1,
            ScoringProfile.CLASSIFICATION_V1,
            ScoringProfile.REFUSAL_V1,
        ),
        ("SAME_LABEL", "BRIDGE_ABSENT", "NON_TRANSITIVITY", "CORRELATION_NOT_AGREEMENT"),
        (
            ErrorClass.FALSE_COMPARABILITY_ACCEPTANCE,
            ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE,
            ErrorClass.WRONG_MEASUREMENT_IDENTITY,
        ),
    ),
    _row(
        "C08",
        ("F05", "F06", "F13", "F14"),
        (
            CaseOrigin.DETERMINISTIC_ENGINE_DERIVED,
            CaseOrigin.DETERMINISTIC_SYNTHETIC,
            CaseOrigin.ADVERSARIAL_MUTATION,
        ),
        ("RES71_REFERENCE_CASE", "RES71_UNRESOLVED"),
        (
            ScoringProfile.NUMERIC_TOLERANCE_V1,
            ScoringProfile.STRUCTURED_FIELDS_V1,
            ScoringProfile.REFUSAL_V1,
        ),
        ("NONFINITE_INPUT", "UNREGISTERED_OPERATION", "WRONG_GRAVITY", "LM_ARITHMETIC"),
        (ErrorClass.INVENTED_NUMERICAL_SCIENCE, ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE),
    ),
    _row(
        "C09",
        ("F07", "F10", "F12"),
        (
            CaseOrigin.DETERMINISTIC_ENGINE_DERIVED,
            CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
            CaseOrigin.ADVERSARIAL_MUTATION,
        ),
        ("RES71_REFERENCE_CASE", "RES70_CLAIM", "EXPERT_RUBRIC"),
        (
            ScoringProfile.NUMERIC_TOLERANCE_V1,
            ScoringProfile.STRUCTURED_FIELDS_V1,
            ScoringProfile.CAUSAL_BOUNDARY_V1,
        ),
        ("CLAIM_LADDER", "CURRENT_REFERENCE_LEAKAGE"),
        (
            ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE,
            ErrorClass.CAUSAL_OVERCLAIM,
            ErrorClass.UNSUPPORTED_LATENT_OR_PHYSIOLOGICAL_INFERENCE,
        ),
    ),
    _row(
        "C10",
        ("F08", "F09", "F13", "F14"),
        (
            CaseOrigin.DETERMINISTIC_ENGINE_DERIVED,
            CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
            CaseOrigin.ADVERSARIAL_MUTATION,
        ),
        ("RES71_REFERENCE_CASE", "RES70_ANALYSIS", "EXPERT_RUBRIC"),
        (
            ScoringProfile.CLASSIFICATION_V1,
            ScoringProfile.STRUCTURED_FIELDS_V1,
            ScoringProfile.REFUSAL_V1,
        ),
        ("DEFERRED_OPERATION", "WRONG_SUPPORT_SHAPE", "MISSING_DESIGN"),
        (ErrorClass.WRONG_ANALYSIS_CLASS, ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE),
    ),
    _row(
        "C11",
        ("F08", "F09", "F07", "F13"),
        (
            CaseOrigin.DETERMINISTIC_ENGINE_DERIVED,
            CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
            CaseOrigin.ADVERSARIAL_MUTATION,
        ),
        ("RES71_REFERENCE_CASE", "RES70_ANALYSIS", "EXPERT_RUBRIC"),
        (
            ScoringProfile.CLASSIFICATION_V1,
            ScoringProfile.STRUCTURED_FIELDS_V1,
            ScoringProfile.REFUSAL_V1,
        ),
        ("BETWEEN_AS_WITHIN", "PSEUDOREPLICATION", "GROUP_TO_INDIVIDUAL"),
        (
            ErrorClass.BETWEEN_TO_WITHIN_MISINFERENCE,
            ErrorClass.WRONG_ANALYSIS_CLASS,
            ErrorClass.CAUSAL_OVERCLAIM,
        ),
    ),
    _row(
        "C12",
        ("F07", "F08", "F10", "F13"),
        (
            CaseOrigin.DETERMINISTIC_ENGINE_DERIVED,
            CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
            CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
            CaseOrigin.ADVERSARIAL_MUTATION,
        ),
        ("RES71_REFERENCE_CASE", "RES69_STATISTICS", "SOURCE_EVIDENCE_SPAN", "EXPERT_RUBRIC"),
        (
            ScoringProfile.CLASSIFICATION_V1,
            ScoringProfile.STRUCTURED_FIELDS_V1,
            ScoringProfile.REFUSAL_V1,
        ),
        ("RELIABILITY_AGREEMENT", "ERROR_MEANINGFULNESS", "VALIDITY_SCOPE"),
        (
            ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE,
            ErrorClass.WRONG_ANALYSIS_CLASS,
            ErrorClass.UNSUPPORTED_LATENT_OR_PHYSIOLOGICAL_INFERENCE,
        ),
    ),
    _row(
        "C13",
        ("F11", "F01", "F02"),
        (
            CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
            CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
            CaseOrigin.ADVERSARIAL_MUTATION,
        ),
        ("SOURCE_EVIDENCE_SPAN", "EXPERT_RUBRIC"),
        (
            ScoringProfile.EVIDENCE_SPAN_V1,
            ScoringProfile.STRUCTURED_FIELDS_V1,
            ScoringProfile.CLASSIFICATION_V1,
        ),
        ("SPAN_MISMATCH", "SOURCE_VERSION_MISMATCH", "UNSUPPORTED_PARAPHRASE"),
        (ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE, ErrorClass.WRONG_MEASUREMENT_IDENTITY),
    ),
    _row(
        "C14",
        ("F01", "F04", "F10", "F11", "F12"),
        (
            CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
            CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
            CaseOrigin.ADVERSARIAL_MUTATION,
        ),
        ("SOURCE_EVIDENCE_SPAN", "RES70_CLAIM", "EXPERT_RUBRIC"),
        (
            ScoringProfile.CLASSIFICATION_V1,
            ScoringProfile.STRUCTURED_FIELDS_V1,
            ScoringProfile.REFUSAL_V1,
        ),
        ("INDIRECT_AS_TARGET_PRIOR", "POPULATION_MISMATCH", "METHOD_VALIDITY_AS_APPLICABILITY"),
        (
            ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE,
            ErrorClass.FALSE_COMPARABILITY_ACCEPTANCE,
            ErrorClass.UNSUPPORTED_LATENT_OR_PHYSIOLOGICAL_INFERENCE,
        ),
    ),
    _row(
        "C15",
        ("F07", "F09", "F12", "F13"),
        (
            CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
            CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
            CaseOrigin.ADVERSARIAL_MUTATION,
            CaseOrigin.DETERMINISTIC_ENGINE_DERIVED,
        ),
        ("RES70_CLAIM", "EXPERT_RUBRIC", "RES71_REFERENCE_CASE"),
        (
            ScoringProfile.CAUSAL_BOUNDARY_V1,
            ScoringProfile.CLASSIFICATION_V1,
            ScoringProfile.REFUSAL_V1,
        ),
        ("ASSOCIATION_TO_CAUSATION", "TEMPORAL_OVERCLAIM", "PREDICTION_CAUSATION"),
        (
            ErrorClass.CAUSAL_OVERCLAIM,
            ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE,
            ErrorClass.UNSUPPORTED_LATENT_OR_PHYSIOLOGICAL_INFERENCE,
        ),
    ),
    _row(
        "C16",
        ("F05", "F07", "F10", "F14"),
        (CaseOrigin.DETERMINISTIC_ENGINE_DERIVED, CaseOrigin.ADVERSARIAL_MUTATION),
        ("RES71_REFERENCE_CASE", "RES71_UNRESOLVED", "RES70_CLAIM"),
        (
            ScoringProfile.NUMERIC_TOLERANCE_V1,
            ScoringProfile.STRUCTURED_FIELDS_V1,
            ScoringProfile.REFUSAL_V1,
            ScoringProfile.CAUSAL_BOUNDARY_V1,
        ),
        ("CHANGED_NUMBER", "DROPPED_PROVENANCE", "RESULT_REFUSAL_INVERSION"),
        (
            ErrorClass.INVENTED_NUMERICAL_SCIENCE,
            ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE,
            ErrorClass.CAUSAL_OVERCLAIM,
        ),
    ),
    _row(
        "C17",
        FAMILY_IDS,
        (
            CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
            CaseOrigin.DETERMINISTIC_ENGINE_DERIVED,
            CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
            CaseOrigin.ADVERSARIAL_MUTATION,
        ),
        ("RES71_REFERENCE_CASE", "RES70_CLAIM", "SOURCE_EVIDENCE_SPAN", "EXPERT_RUBRIC"),
        (
            ScoringProfile.CLASSIFICATION_V1,
            ScoringProfile.STRUCTURED_FIELDS_V1,
            ScoringProfile.REFUSAL_V1,
        ),
        ("ALL_CRITICAL_HIGH_ERRORS", "COMPOUND_ERROR", "SAFE_PARTIAL_CORRECTION"),
        (*ErrorClass,),
    ),
    _row(
        "C18",
        FAMILY_IDS,
        (
            CaseOrigin.DETERMINISTIC_ENGINE_DERIVED,
            CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
            CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
            CaseOrigin.ADVERSARIAL_MUTATION,
        ),
        (
            "RES71_REFERENCE_CASE",
            "RES71_UNRESOLVED",
            "RES70_CLAIM",
            "SOURCE_EVIDENCE_SPAN",
            "EXPERT_RUBRIC",
        ),
        (
            ScoringProfile.REFUSAL_V1,
            ScoringProfile.STRUCTURED_FIELDS_V1,
            ScoringProfile.CLASSIFICATION_V1,
        ),
        (
            "MISSING_METADATA",
            "UNRESOLVED_IDENTITY",
            "BRIDGE_REQUIRED",
            "DEFERRED_OPERATION",
            "EVIDENCE",
            "UNCERTAINTY",
            "CAUSAL_DESIGN",
            "OVER_REFUSAL",
        ),
        (
            ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE,
            ErrorClass.OVER_REFUSAL,
            ErrorClass.UNDER_SPECIFIED_REFUSAL,
            ErrorClass.EXCESSIVE_CONSERVATISM,
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class CoverageValidation:
    status: str
    represented_capabilities: tuple[str, ...]
    represented_families: tuple[str, ...]
    missing_capabilities: tuple[str, ...]
    missing_families: tuple[str, ...]
    missing_cells: tuple[tuple[str, str, str], ...]
    reason: str


def validate_coverage_matrix(rows: Iterable[CoverageRow] = COVERAGE_MATRIX) -> CoverageValidation:
    materialized = tuple(rows)
    capabilities = tuple(row.capability_id for row in materialized)
    if capabilities != CAPABILITY_IDS:
        raise ValueError("coverage matrix must contain exactly C01..C18 in order")
    for row in materialized:
        if any(family not in FAMILY_IDS for family in row.benchmark_families):
            raise ValueError(f"coverage row {row.capability_id} contains an unknown family")
        if not row.benchmark_families or not row.case_origins or not row.scorer_profiles:
            raise ValueError(f"coverage row {row.capability_id} is incomplete")
        if tuple(row.split_coverage) != SPLIT_ORDER:
            raise ValueError(f"coverage row {row.capability_id} does not require D/V/H")
    family_set = tuple(
        sorted({family for row in materialized for family in row.benchmark_families})
    )
    if family_set != FAMILY_IDS:
        raise ValueError("coverage matrix does not represent all 14 benchmark families")
    return CoverageValidation(
        status="PASS",
        represented_capabilities=CAPABILITY_IDS,
        represented_families=FAMILY_IDS,
        missing_capabilities=(),
        missing_families=(),
        missing_cells=(),
        reason="all 18 capabilities and all 14 benchmark families are representable",
    )


def coverage_manifest_digest() -> str:
    validate_coverage_matrix()
    return canonical_hash(COVERAGE_MATRIX)


def _case_satisfies_row(case: BenchmarkCaseV1, row: CoverageRow, family: str) -> bool:
    return (
        case.capability_id == row.capability_id
        and case.benchmark_family == family
        and case.provenance.origin_class in row.case_origins
        and case.scoring_contract.profile_id in row.scorer_profiles
        and bool(set(case.adversarial_tags) & set(row.adversarial_tags))
        and bool(set(case.scoring_contract.error_class_rules) & set(row.error_classes))
    )


def validate_case_coverage(
    cases: tuple[BenchmarkCaseV1, ...],
    *,
    require_all_splits: bool = False,
) -> CoverageValidation:
    """Check actual cases; small fixtures may prove infrastructure without full V1 coverage."""

    validate_coverage_matrix()
    represented_capabilities = tuple(sorted({case.capability_id for case in cases}))
    represented_families = tuple(sorted({case.benchmark_family for case in cases}))
    missing_capabilities = tuple(
        item for item in CAPABILITY_IDS if item not in represented_capabilities
    )
    missing_families = tuple(item for item in FAMILY_IDS if item not in represented_families)
    missing_cells: list[tuple[str, str, str]] = []
    expected_cells = tuple(
        (row, family, split)
        for row in COVERAGE_MATRIX
        for family in row.benchmark_families
        for split in SPLIT_ORDER
    )
    for row, family, split in expected_cells:
        if not require_all_splits and split != SplitName.PUBLIC_DEVELOPMENT:
            continue
        if not any(
            _case_satisfies_row(case, row, family)
            and (case.split.split_name is None or case.split.split_name is split)
            for case in cases
        ):
            missing_cells.append((row.capability_id, family, split.value))
    status = (
        "PASS"
        if not missing_capabilities and not missing_families and not missing_cells
        else "BLOCKED"
    )
    return CoverageValidation(
        status=status,
        represented_capabilities=represented_capabilities,
        represented_families=represented_families,
        missing_capabilities=missing_capabilities,
        missing_families=missing_families,
        missing_cells=tuple(missing_cells),
        reason=(
            "case set satisfies requested coverage"
            if status == "PASS"
            else "case set is an infrastructure fixture or is missing frozen coverage cells"
        ),
    )


__all__ = [
    "COVERAGE_MATRIX",
    "CoverageRow",
    "CoverageValidation",
    "coverage_manifest_digest",
    "validate_case_coverage",
    "validate_coverage_matrix",
]
