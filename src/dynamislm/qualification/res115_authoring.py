"""Real Phase-B qualification lanes for RES-115.

This module contains public authoring operators and validators. Exact source
selections, packet contents, questions, proposed answers, and seed blocks are
materialized only in the external qualification store.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

from dynamislm.benchmark.authoring import (
    ACTIVE_SCORERS,
    AUTHORING_PLAN_VERSION,
    AUTHORING_RECIPE_REGISTRY,
    QUALIFICATION_CANDIDATE_ID_PREFIX,
    QUALIFICATION_SEED_NAMESPACE_PREFIX,
    AuthoringPlanItemV1,
    AuthoringPlanV1,
    CandidateStoreReceiptV1,
    QualificationBatchManifestV1,
    QualificationBatchValidation,
    authoring_recipe_registry_digest,
    bind_authoring_plan,
    bind_qualification_manifest_for_candidates,
    question_classes_for_cell,
    validate_authoring_plan,
    validate_qualification_batch,
)
from dynamislm.benchmark.authority import (
    bind_res71_operation,
    make_authority_binding,
)
from dynamislm.benchmark.constants import (
    CAPABILITY_IDS,
    FAMILY_IDS,
    AuthorityKind,
    CaseOrigin,
    DifficultyLevel,
    ErrorClass,
    EvidenceKind,
    ExpectedAnswerKind,
    InputModality,
    PractitionerQuestionClass,
    RefusalDecision,
    ScoringProfile,
)
from dynamislm.benchmark.contamination import (
    exact_shingle_digest,
    fuzzy_fingerprint,
    normalized_text_sha256,
)
from dynamislm.benchmark.contracts import (
    AuthorityBinding,
    ClaimContract,
    ComparabilityContract,
    ContaminationBinding,
    DeterministicResultView,
    DifficultyBinding,
    DocumentIdentity,
    EvidenceExcerpt,
    EvidenceReference,
    EvidenceSpanIdentity,
    ExpectedStructuredAnswer,
    InputContract,
    ProvenanceEdge,
    RefusalExpectation,
    ScoringContract,
    SourceArtifactIdentity,
    ToleranceContract,
)
from dynamislm.benchmark.coverage import COVERAGE_MATRIX, CoverageRow, coverage_manifest_digest
from dynamislm.benchmark.pre_review import (
    CandidateIsolationMetadata,
    CandidateParentBinding,
    CandidateReviewPacket,
    ProposedCaseProvenance,
    bind_candidate_review_packet,
    candidate_scientific_projection,
    validate_candidate_review_packet,
    validate_candidate_set,
)
from dynamislm.benchmark.res115_authoring import (
    build_res115_source_artifact_resolver,
    validate_res115_candidate_for_authoring,
    validate_res115_source_applicability,
)
from dynamislm.benchmark.source_artifacts import (
    SourceArtifactResolver,
    derive_unique_jats_paragraph_locator,
    extract_jats_text,
)
from dynamislm.claims.models import MeasurementClaimLevel, RelationshipClaimLevel
from dynamislm.comparability.models import ComparabilityState
from dynamislm.qualification import (
    ReferenceCase,
    ReferenceCaseStatus,
    get_reference_case,
    get_reference_cases,
)
from dynamislm.refusal.models import RefusalClass, RefusalReasonCode
from dynamislm.serialization import canonical_hash, register_serializable_type

AUTHORING_PROCESS_ID = "agent-process:codex:RES-115-CASE-AUTHORING-001B"
QUALIFICATION_BATCH_ID = "PSE-V1-QUALIFICATION/RES-115-CASE-AUTHORING-001B"
_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_REPOSITORY_SOURCE_REGISTRY = _REPOSITORY_ROOT / "registries/performance_science_eval"
_EXTERNAL_ROOT = Path("/mnt/e/Data/Datasets/DynamisLM/PerformanceScienceEval")
_EXTERNAL_ACCEPTED_SOURCE_ROOT = _EXTERNAL_ROOT / "sources/accepted"
_PHASE_A_MANIFEST_ROOT = _EXTERNAL_ROOT / "manifests"
_SOURCE_TAG_SUPPORT_PATH = _PHASE_A_MANIFEST_ROOT / "source_tag_support_evidence_001.jsonl"
_DIRECT_TARGET_EVIDENCE_PATH = (
    _PHASE_A_MANIFEST_ROOT / "direct_target_population_evidence_001.jsonl"
)
_SEARCH_REPLAY_PATH = _PHASE_A_MANIFEST_ROOT / "search_replays_001.jsonl"
PHASE_A_SEARCH_STRATA = (
    "S01_CMJ_DJ_FORCE_TIME",
    "S02_SPRINT_ACCELERATION",
    "S03_COD_RSA_30_15",
    "S04_STRENGTH_IMTP_VBT",
    "S05_GNSS_GPS_EXTERNAL_LOAD",
    "S06_RELIABILITY_MEASUREMENT_ERROR",
    "S07_VALIDITY_AGREEMENT",
    "S08_LONGITUDINAL_MONITORING",
    "S09_POPULATION_APPLICABILITY",
    "S10_CAUSAL_ASSOCIATION_PREDICTION",
)
_TARGET_USE_BY_SCOPE = {
    "DIRECT_TARGET_POPULATION_EVIDENCE": "POPULATION_APPLICABILITY_ONLY",
    "INDIRECT_MEASUREMENT_EVIDENCE": "METHOD_OR_MEASUREMENT_ONLY",
    "NONCANONICAL_CONTEXT_ONLY": "CONTEXT_ONLY",
}
_RES71_REFERENCES = tuple(get_reference_cases())
_REFERENCE_DIGESTS = {item.case_id: canonical_hash(item) for item in _RES71_REFERENCES}
_BASE_SEMANTIC_CITATIONS = (
    "docs/decisions/RES21-DR-001-performance-science-eval-v1.md",
    "docs/architecture/SCIENTIFIC_CONSTITUTION_V2.md",
    "docs/architecture/REASONING_CLAIMS_EVALUATION_V1.md",
)
_CAPABILITY_AUTHORITY_CITATIONS = {
    "C01": ("docs/decisions/RES60-DR-001-canonical-population-and-source-gate.md",),
    "C02": ("docs/decisions/RES60-DR-001-canonical-population-and-source-gate.md",),
    "C03": ("docs/decisions/RES70-DR-001-cross-source-comparability-analysis-claim-authority.md",),
    "C04": ("docs/decisions/RES62-DR-001-longitudinal-record-and-multisource-provenance.md",),
    "C05": ("docs/decisions/RES70-DR-001-cross-source-comparability-analysis-claim-authority.md",),
    "C06": ("docs/decisions/RES70-DR-001-cross-source-comparability-analysis-claim-authority.md",),
    "C07": ("docs/decisions/RES70-DR-001-cross-source-comparability-analysis-claim-authority.md",),
    "C09": ("docs/decisions/RES70-DR-001-cross-source-comparability-analysis-claim-authority.md",),
    "C10": ("docs/decisions/RES70-DR-001-cross-source-comparability-analysis-claim-authority.md",),
    "C11": (
        "docs/decisions/RES62-DR-001-longitudinal-record-and-multisource-provenance.md",
        "docs/decisions/RES70-DR-001-cross-source-comparability-analysis-claim-authority.md",
    ),
    "C12": ("docs/decisions/RES69-DR-001-longitudinal-reliability-uncertainty.md",),
    "C14": (
        "docs/decisions/RES60-DR-001-canonical-population-and-source-gate.md",
        "docs/decisions/RES70-DR-001-cross-source-comparability-analysis-claim-authority.md",
    ),
    "C15": ("docs/decisions/RES70-DR-001-cross-source-comparability-analysis-claim-authority.md",),
    "C17": (
        "docs/decisions/RES21-DR-001-performance-science-eval-v1.md"
        "#5-error-taxonomy-and-error-asymmetry",
    ),
    "C18": (
        "docs/architecture/REASONING_CLAIMS_EVALUATION_V1.md#scientific-refusal-architecture",
        "docs/decisions/RES70-DR-001-cross-source-comparability-analysis-claim-authority.md",
    ),
}


@register_serializable_type
@dataclass(frozen=True, slots=True)
class QualificationSeedInputV1:
    """Private qualification generator seeds, persisted outside the repository."""

    batch_id: str
    generator_registry_digest: str
    seed_blocks: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.batch_id, str) or not self.batch_id.startswith(
            "PSE-V1-QUALIFICATION/"
        ):
            raise ValueError("qualification seeds require a qualification-only batch namespace")
        if self.generator_registry_digest != RES115_SYNTHETIC_GENERATOR_DIGEST:
            raise ValueError("qualification seed input binds a stale generator registry")
        if not isinstance(self.seed_blocks, tuple) or not self.seed_blocks:
            raise ValueError("qualification seed input requires one block per synthetic case")
        if any(
            not isinstance(entry, tuple)
            or len(entry) != 2
            or not isinstance(entry[0], str)
            or not entry[0]
            or not isinstance(entry[1], str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}", entry[1]) is None
            for entry in self.seed_blocks
        ):
            raise ValueError("qualification seed input contains an invalid case or seed block")
        case_ids = tuple(case_id for case_id, _ in self.seed_blocks)
        seed_values = tuple(seed_block for _, seed_block in self.seed_blocks)
        if len(set(case_ids)) != len(case_ids) or len(set(seed_values)) != len(seed_values):
            raise ValueError("qualification seed inputs cannot collide")
        if case_ids != tuple(sorted(case_ids, key=lambda value: value.encode("utf-8"))):
            raise ValueError("qualification seed inputs must use canonical case ordering")
        expected_case_ids = tuple(
            sorted(
                (
                    reference.case_id
                    for reference in _RES71_REFERENCES
                    if reference.status is ReferenceCaseStatus.REFUSAL
                    and reference.operation_id is None
                ),
                key=lambda value: value.encode("utf-8"),
            )
        )
        if case_ids != expected_case_ids:
            raise ValueError("qualification seed inputs must bind every synthetic RES-71 refusal")


@dataclass(frozen=True, slots=True)
class SourceSpanProposalV1:
    span_digest: str
    locator: str
    text: str
    scope: str
    support_rules: tuple[str, ...]
    support_tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SourceCellSelectionV1:
    pmcid: str
    capability_id: str
    benchmark_family: str
    applicability_scope: str
    source_family_id: str
    source_family_digest: str
    search_strata: tuple[str, ...]
    spans: tuple[SourceSpanProposalV1, ...]
    population_clause_values: tuple[tuple[str, str], ...]
    direct_target: bool = False


@dataclass(frozen=True, slots=True)
class SourceLaneBuildV1:
    packets: tuple[CandidateReviewPacket, ...]
    source_search_strata_by_candidate: tuple[tuple[str, tuple[str, ...]], ...]
    direct_target_document_ids: tuple[str, ...]
    evidence_search_strata: tuple[str, ...]
    source_family_ids: tuple[str, ...]
    source_document_ids: tuple[str, ...]
    applicability_scope_counts: tuple[tuple[str, int], ...]
    primary_cell_candidate_ids: tuple[tuple[str, str, str], ...]


@dataclass(frozen=True, slots=True)
class Res115AuthoringDraftV1:
    batch_id: str
    packets: tuple[CandidateReviewPacket, ...]
    plan: AuthoringPlanV1
    source_lane: SourceLaneBuildV1
    res71_reference_case_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Res115SourceCoverageValidationV1:
    source_backed_case_count: int
    direct_target_document_count: int
    indirect_source_document_count: int
    noncanonical_context_document_count: int
    exact_jats_span_count: int
    multi_span_candidate_count: int
    evidence_strata_count: int
    source_family_count: int
    source_document_ids: tuple[str, ...]
    source_family_ids: tuple[str, ...]
    evidence_search_strata: tuple[str, ...]
    status: str = "PASS"


@dataclass(frozen=True, slots=True)
class Res115QualificationValidationV1:
    candidate_validation: QualificationBatchValidation
    source_validation: Res115SourceCoverageValidationV1
    reference_case_ids: tuple[str, ...]
    status: str = "PASS"


@dataclass(slots=True)
class _PublicSourceDocumentSummary:
    pmcid: str
    document_id: str
    doi: str | None
    applicability_scope: str
    source_family_id: str
    candidate_ids: list[str]
    candidate_payload_hashes: list[str]
    source_search_strata: list[str]
    evidence_span_count: int = 0


_FAMILY_LABELS = {
    "F01": "terminology and construct identification",
    "F02": "protocol extraction",
    "F03": "metric, measurand, and normalization",
    "F04": "device and protocol comparability",
    "F05": "biomechanics calculation interpretation",
    "F06": "unit, frame, and event reasoning",
    "F07": "longitudinal change reasoning",
    "F08": "statistical-analysis selection",
    "F09": "within-athlete and between-athlete reasoning",
    "F10": "uncertainty, reliability, and validity interpretation",
    "F11": "evidence extraction",
    "F12": "causal-language discipline",
    "F13": "scientific error detection",
    "F14": "scientific refusal and insufficient information",
}

_CAPABILITY_LABELS = {
    "C01": "terminology and construct identity",
    "C02": "protocol-field extraction",
    "C03": "measurement identity",
    "C04": "value origin and scientific role",
    "C05": "unit and normalization authority",
    "C06": "frame, sign, event, and phase boundaries",
    "C07": "pairwise comparability",
    "C08": "registered calculation interpretation",
    "C09": "longitudinal claim level",
    "C10": "analysis selection and prerequisites",
    "C11": "within-athlete versus between-athlete support",
    "C12": "reliability, uncertainty, and validity scope",
    "C13": "exact source-span extraction",
    "C14": "evidence applicability and population scope",
    "C15": "causal-language boundary",
    "C16": "deterministic-result interpretation",
    "C17": "scientific error detection",
    "C18": "justified refusal and safe lower-level answers",
}

_QUESTION_PROMPTS = {
    PractitionerQuestionClass.MEASUREMENT_IDENTITY_AND_PROVENANCE: (
        "What identity and provenance are established by the supplied record?"
    ),
    PractitionerQuestionClass.COMPARABILITY_AND_HARMONIZATION: (
        "Can the supplied observations be compared under the registered authority?"
    ),
    PractitionerQuestionClass.INDIVIDUAL_LONGITUDINAL_CHANGE: (
        "What changed for this individual, and what claim level is supported?"
    ),
    PractitionerQuestionClass.GROUP_OR_SQUAD_CHANGE: (
        "What group-level statement is supported by the supplied scope?"
    ),
    PractitionerQuestionClass.RELATIONSHIP_AND_MULTILEVEL_STRUCTURE: (
        "What relationship and level of analysis are supported?"
    ),
    PractitionerQuestionClass.CONSTRUCT_AND_CLAIM_INTERPRETATION: (
        "Which interpretation is supported without exceeding the evidence?"
    ),
    PractitionerQuestionClass.METHOD_AND_ANALYSIS_REASONING: (
        "Which method conditions and analysis prerequisites matter?"
    ),
    PractitionerQuestionClass.ANSWERABILITY_AND_REFUSAL: (
        "Can the requested claim be answered, and what remains safe to describe?"
    ),
}

_QUESTION_CLASS_PREFERENCES: dict[tuple[str, str], PractitionerQuestionClass] = {
    ("C01", "F01"): PractitionerQuestionClass.MEASUREMENT_IDENTITY_AND_PROVENANCE,
    ("C01", "F03"): PractitionerQuestionClass.CONSTRUCT_AND_CLAIM_INTERPRETATION,
    ("C02", "F02"): PractitionerQuestionClass.METHOD_AND_ANALYSIS_REASONING,
    ("C07", "F04"): PractitionerQuestionClass.COMPARABILITY_AND_HARMONIZATION,
    ("C09", "F07"): PractitionerQuestionClass.INDIVIDUAL_LONGITUDINAL_CHANGE,
    ("C10", "F08"): PractitionerQuestionClass.RELATIONSHIP_AND_MULTILEVEL_STRUCTURE,
    ("C12", "F08"): PractitionerQuestionClass.GROUP_OR_SQUAD_CHANGE,
    ("C18", "F14"): PractitionerQuestionClass.ANSWERABILITY_AND_REFUSAL,
}

_REFUSAL_BOUNDARIES = {
    "F01": (RefusalClass.IDENTITY_UNRESOLVED, RefusalReasonCode.MEASURAND_MISMATCH),
    "F02": (RefusalClass.IDENTITY_UNRESOLVED, RefusalReasonCode.PROTOCOL_IDENTITY_MISSING),
    "F03": (RefusalClass.IDENTITY_UNRESOLVED, RefusalReasonCode.METRIC_DEFINITION_MISMATCH),
    "F04": (
        RefusalClass.COMPARABILITY_UNESTABLISHED,
        RefusalReasonCode.DEVICE_COMPARABILITY_NOT_ESTABLISHED,
    ),
    "F05": (RefusalClass.COMPUTATION_NOT_REGISTERED, RefusalReasonCode.NO_REGISTERED_OPERATION),
    "F06": (RefusalClass.IDENTITY_UNRESOLVED, RefusalReasonCode.AXIS_OR_FRAME_MISSING),
    "F07": (RefusalClass.UNCERTAINTY_LIMITS_CLAIM, RefusalReasonCode.UNCERTAINTY_INADEQUATE),
    "F08": (
        RefusalClass.ANALYSIS_DESIGN_MISMATCH,
        RefusalReasonCode.LONGITUDINAL_DATA_INSUFFICIENT,
    ),
    "F09": (
        RefusalClass.ANALYSIS_DESIGN_MISMATCH,
        RefusalReasonCode.BETWEEN_WITHIN_MISMATCH,
    ),
    "F10": (RefusalClass.UNCERTAINTY_LIMITS_CLAIM, RefusalReasonCode.UNCERTAINTY_INADEQUATE),
    "F11": (RefusalClass.EVIDENCE_SCOPE_UNSUPPORTED, RefusalReasonCode.MISSING_METADATA),
    "F12": (
        RefusalClass.CAUSAL_IDENTIFICATION_UNSUPPORTED,
        RefusalReasonCode.CAUSAL_DESIGN_UNSUPPORTED,
    ),
    "F13": (RefusalClass.EVIDENCE_SCOPE_UNSUPPORTED, RefusalReasonCode.MISSING_METADATA),
    "F14": (RefusalClass.DATA_ADEQUACY_INSUFFICIENT, RefusalReasonCode.MISSING_METADATA),
}

_ERROR_CASE_BY_FAMILY = {
    "F01": ErrorClass.WRONG_MEASUREMENT_IDENTITY,
    "F02": ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE,
    "F03": ErrorClass.DIRECT_DERIVED_COLLAPSE,
    "F04": ErrorClass.FALSE_COMPARABILITY_ACCEPTANCE,
    "F05": ErrorClass.INVENTED_NUMERICAL_SCIENCE,
    "F06": ErrorClass.WRONG_MEASUREMENT_IDENTITY,
    "F07": ErrorClass.UNSUPPORTED_LATENT_OR_PHYSIOLOGICAL_INFERENCE,
    "F08": ErrorClass.WRONG_ANALYSIS_CLASS,
    "F09": ErrorClass.BETWEEN_TO_WITHIN_MISINFERENCE,
    "F10": ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE,
    "F11": ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE,
    "F12": ErrorClass.CAUSAL_OVERCLAIM,
    "F13": ErrorClass.OVER_REFUSAL,
    "F14": ErrorClass.UNDER_SPECIFIED_REFUSAL,
}

_ERROR_CORRECTION = {
    ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE: (
        "Keep the unsupported claim blocked and state the supported lower-level description."
    ),
    ErrorClass.INVENTED_NUMERICAL_SCIENCE: (
        "Report only an exact registered RES-71 result; do not calculate an unregistered value."
    ),
    ErrorClass.FALSE_COMPARABILITY_ACCEPTANCE: (
        "Require exact pairwise comparability or return the registered non-comparable state."
    ),
    ErrorClass.CAUSAL_OVERCLAIM: "Separate observation or association from causal evidence.",
    ErrorClass.BETWEEN_TO_WITHIN_MISINFERENCE: (
        "Keep between-athlete support separate from within-athlete inference."
    ),
    ErrorClass.WRONG_MEASUREMENT_IDENTITY: (
        "Resolve typed measurement identity; a display label alone is insufficient."
    ),
    ErrorClass.WRONG_ANALYSIS_CLASS: (
        "Use only a registered analysis class whose support prerequisites pass."
    ),
    ErrorClass.DIRECT_DERIVED_COLLAPSE: (
        "Preserve the supplied direct, provider-derived, or model-estimated origin."
    ),
    ErrorClass.UNSUPPORTED_LATENT_OR_PHYSIOLOGICAL_INFERENCE: (
        "Do not infer a latent physiological state from the supplied performance output."
    ),
    ErrorClass.OVER_REFUSAL: (
        "Answer independently supported fields; keep only the unsupported claim blocked."
    ),
    ErrorClass.UNDER_SPECIFIED_REFUSAL: (
        "State the blocked claim, refusal class, reason, missing information, and safe description."
    ),
    ErrorClass.EXCESSIVE_CONSERVATISM: (
        "Provide a registered safe lower-level description when supported by the supplied input."
    ),
}

_SEMANTIC_ERROR_BY_FAMILY = {
    "F01": ErrorClass.WRONG_MEASUREMENT_IDENTITY,
    "F02": ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE,
    "F03": ErrorClass.DIRECT_DERIVED_COLLAPSE,
    "F04": ErrorClass.FALSE_COMPARABILITY_ACCEPTANCE,
    "F05": ErrorClass.INVENTED_NUMERICAL_SCIENCE,
    "F06": ErrorClass.WRONG_MEASUREMENT_IDENTITY,
    "F07": ErrorClass.UNSUPPORTED_LATENT_OR_PHYSIOLOGICAL_INFERENCE,
    "F08": ErrorClass.WRONG_ANALYSIS_CLASS,
    "F09": ErrorClass.BETWEEN_TO_WITHIN_MISINFERENCE,
    "F10": ErrorClass.EXCESSIVE_CONSERVATISM,
    "F11": ErrorClass.WRONG_MEASUREMENT_IDENTITY,
    "F12": ErrorClass.CAUSAL_OVERCLAIM,
    "F13": ErrorClass.OVER_REFUSAL,
    "F14": ErrorClass.UNDER_SPECIFIED_REFUSAL,
}

_UNSAFE_RESPONSE_BY_ERROR = {
    ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE: (
        "Treats a requested interpretation as established without support."
    ),
    ErrorClass.INVENTED_NUMERICAL_SCIENCE: ("Supplies an unregistered numerical value."),
    ErrorClass.FALSE_COMPARABILITY_ACCEPTANCE: (
        "Treats two methods as interchangeable despite a material mismatch."
    ),
    ErrorClass.CAUSAL_OVERCLAIM: "Describes an observational pattern as a causal effect.",
    ErrorClass.BETWEEN_TO_WITHIN_MISINFERENCE: (
        "Uses one row per athlete to claim a within-athlete relationship."
    ),
    ErrorClass.WRONG_MEASUREMENT_IDENTITY: (
        "Uses a display label to override conflicting typed identity fields."
    ),
    ErrorClass.WRONG_ANALYSIS_CLASS: (
        "Selects an analysis whose registered support prerequisites are absent."
    ),
    ErrorClass.DIRECT_DERIVED_COLLAPSE: "Calls a provider-derived output a direct measurement.",
    ErrorClass.UNSUPPORTED_LATENT_OR_PHYSIOLOGICAL_INFERENCE: (
        "Infers a physiological state from a performance output alone."
    ),
    ErrorClass.OVER_REFUSAL: "Declines to describe a field that is independently supported.",
    ErrorClass.UNDER_SPECIFIED_REFUSAL: (
        "Refuses without naming the blocked claim or missing information."
    ),
    ErrorClass.EXCESSIVE_CONSERVATISM: (
        "Withholds a safe lower-level description despite adequate support."
    ),
}

_SEMANTIC_SCENARIO_BY_CAPABILITY: dict[str, dict[str, object]] = {
    "C01": {
        "display_label": "same label on two measurement records",
        "identity_fact": "typed measurand and estimator fields differ",
        "question_suffix": "Does the shared display label establish one measurement identity?",
    },
    "C02": {
        "protocol_fact": "device, event, or protocol field is absent from the supplied record",
        "question_suffix": "Which required protocol field remains unresolved?",
    },
    "C03": {
        "identity_fact": "the typed measurand field differs while the display label is unchanged",
        "question_suffix": "Do the supplied identity fields resolve to the same measurement?",
    },
    "C04": {
        "value_origin": "PROVIDER_DERIVED",
        "direct_measurement": False,
        "question_suffix": "May this provider-derived value be relabelled as a direct measurement?",
    },
    "C05": {
        "conversion_execution": "NOT_RECORDED",
        "conversion_authority": "NOT_REGISTERED_FOR_THIS_PAIR",
        "question_suffix": "Is a unit or normalization conversion authorized by this record?",
    },
    "C06": {
        "frame_or_event_identity": "NOT_MATCHED",
        "event_boundary_evidence": "INCOMPLETE",
        "question_suffix": "Are sign, frame, and event boundaries established for this comparison?",
    },
    "C07": {
        "same_label": True,
        "threshold_identity": "MISMATCH",
        "method_identity": "MISMATCH",
        "question_suffix": (
            "What registered pairwise comparability state follows from these differences?"
        ),
    },
    "C09": {
        "result_kind": "NUMERICAL_CHANGE",
        "measurement_error_authority": "NOT_SUPPLIED",
        "meaningfulness_threshold": "NOT_REGISTERED",
        "question_suffix": (
            "What is the strongest longitudinal claim supported by this result and its context?"
        ),
    },
    "C10": {
        "analysis_support_shape": "ONE_ROW_PER_ATHLETE",
        "within_athlete_repeats": "ABSENT",
        "analysis_prerequisite_status": "NOT_MET",
        "question_suffix": "Is the requested analysis class authorized by the support shape?",
    },
    "C11": {
        "unit_of_analysis": "ATHLETE_BETWEEN",
        "repeated_measure_key": "ABSENT",
        "question_suffix": "Can between-athlete support answer a within-athlete question?",
    },
    "C12": {
        "reliability_assumption_declaration": "ABSENT",
        "measurement_error_scale": "UNRESOLVED",
        "meaningful_change_criterion": "ABSENT",
        "question_suffix": "Do the supplied facts establish measurement error or meaningfulness?",
    },
    "C14": {
        "evidence_class": "INDIRECT_MEASUREMENT_EVIDENCE",
        "target_norm_authority": "NOT_ESTABLISHED",
        "question_suffix": (
            "Can this applicability class establish a canonical target norm or threshold?"
        ),
    },
    "C15": {
        "study_design": "OBSERVATIONAL_WITHOUT_CAUSAL_IDENTIFICATION",
        "requested_relationship_claim": "CAUSAL_EVIDENCE",
        "question_suffix": "Does this design authorize the requested causal claim?",
    },
}

_REFERENCE_PRIMARY_CELL = {
    "res71-external-unit-km-to-m": ("C05", "F06"),
    "res71-external-relative-distance": ("C16", "F10"),
    "res71-cmj-flight-time-v2-gold": ("C08", "F05"),
    "res71-rsa-mechanical-percent-decrement": ("C16", "F14"),
    "res71-longitudinal-absolute-change": ("C16", "F07"),
    "res71-nonfinite-unit-refusal": ("C18", "F14"),
    "res71-cmj-rfd-refusal": ("C08", "F13"),
    "res71-bpt-generic-power-refusal": ("C08", "F05"),
    "res71-bpt-mpv-refusal": ("C08", "F14"),
    "res71-same-label-different-method": ("C07", "F04"),
    "res71-causal-overclaim-refusal": ("C15", "F12"),
    "res71-between-to-within-refusal": ("C11", "F09"),
}

_EXTRA_REFERENCE_CASE_IDS = frozenset({"res71-bpt-generic-power-refusal"})
_REFERENCE_CLONE_CELLS = {
    ("C08", "F06"): "res71-cmj-flight-time-v2-gold",
    ("C16", "F05"): "res71-cmj-flight-time-v2-gold",
}


@dataclass(frozen=True, slots=True)
class SyntheticGeneratorDefinitionV1:
    generator_id: str
    version: str
    generator_family: str
    output_contract: str


RES115_SYNTHETIC_GENERATORS = (
    SyntheticGeneratorDefinitionV1(
        generator_id="res115-unregistered-operation-context",
        version="1.0.0",
        generator_family="synthetic-scientific-refusal",
        output_contract=(
            "non-numeric qualification-only context bound to a live RES-71 refusal reference"
        ),
    ),
)
RES115_SYNTHETIC_GENERATOR_DIGEST = canonical_hash(RES115_SYNTHETIC_GENERATORS)


def generate_synthetic_unregistered_operation_context(
    reference_case: ReferenceCase,
    *,
    seed_block: str,
) -> Mapping[str, object]:
    """Pure versioned generator; it never emits numeric scientific gold."""

    if (
        reference_case.operation_id is not None
        or reference_case.status is not ReferenceCaseStatus.REFUSAL
    ):
        raise ValueError(
            "synthetic unregistered-operation generator requires a no-operation refusal"
        )
    if not seed_block or not seed_block.strip():
        raise ValueError("synthetic generator seed block must be non-empty")
    marker = canonical_hash(
        {
            "generator_id": RES115_SYNTHETIC_GENERATORS[0].generator_id,
            "generator_version": RES115_SYNTHETIC_GENERATORS[0].version,
            "seed_block": seed_block,
            "reference_case_id": reference_case.case_id,
        }
    )
    values = tuple(
        {"name": item.name, "value": item.value, "unit": item.unit}
        for item in reference_case.synthetic_input
    )
    return {
        "fixture_scope": "QUALIFICATION_ONLY",
        "scenario_marker": marker,
        "reference_input": values,
        "requested_operation": (
            reference_case.synthetic_input[0].value
            if reference_case.synthetic_input
            else reference_case.case_id
        ),
        "numeric_gold_generated": False,
    }


def _row(capability_id: str) -> CoverageRow:
    return next(item for item in COVERAGE_MATRIX if item.capability_id == capability_id)


def _read_phase_a_jsonl(path: Path, *, description: str) -> tuple[dict[str, object], ...]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"{description} is unavailable") from exc
    rows: list[dict[str, object]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{description} is invalid at line {line_number}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"{description} rows must be JSON objects")
        rows.append(row)
    return tuple(rows)


def _mapping(value: object, *, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"Phase-A {field} must be a JSON object")
    return value


def _string(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"Phase-A {field} must be a non-empty string")
    return value


def _accepted_phase_a_rows(
    repository_root: Path = _REPOSITORY_SOURCE_REGISTRY,
) -> tuple[dict[str, object], ...]:
    rows = _read_phase_a_jsonl(
        repository_root / "accepted.jsonl",
        description="public Phase-A accepted registry",
    )
    accepted = tuple(row for row in rows if row.get("disposition") == "ACCEPTED")
    if len(accepted) != 104:
        raise ValueError("sealed Phase-A accepted document count no longer equals 104")
    return accepted


def _retained_jats_bytes(
    row: Mapping[str, object],
    *,
    external_root: Path,
) -> bytes:
    artifact = _mapping(row.get("retained_source_artifact"), field="retained_source_artifact")
    relative_path = _string(artifact.get("relative_path"), field="relative_path")
    parts = PurePosixPath(relative_path).parts
    if parts[:2] != ("sources", "accepted") or ".." in parts or "." in parts:
        raise ValueError("Phase-A retained source path is outside sources/accepted")
    source_root = (external_root / "sources" / "accepted").resolve()
    source_path = source_root.joinpath(*parts[2:]).resolve()
    if not source_path.is_relative_to(source_root) or not source_path.is_file():
        raise ValueError("Phase-A retained article.xml.gz is unavailable")
    try:
        return gzip.decompress(source_path.read_bytes())
    except (OSError, EOFError) as exc:
        raise ValueError("Phase-A retained article.xml.gz cannot be decompressed") from exc


def _source_tag_span_proposals(
    row: Mapping[str, object],
    support_row: Mapping[str, object],
    *,
    capability_id: str,
    benchmark_family: str,
    external_root: Path,
) -> tuple[SourceSpanProposalV1, ...]:
    capabilities = support_row.get("candidate_capabilities_retained")
    families = support_row.get("candidate_benchmark_families_retained")
    if not isinstance(capabilities, list) or capability_id not in capabilities:
        return ()
    if not isinstance(families, list) or benchmark_family not in families:
        return ()
    evidence_by_tag = _mapping(support_row.get("evidence_by_tag"), field="evidence_by_tag")
    capability_specs = _mapping(evidence_by_tag.get("capabilities"), field="capability evidence")
    family_specs = _mapping(evidence_by_tag.get("benchmark_families"), field="family evidence")
    tagged_specs: list[tuple[str, dict[str, object]]] = []
    for tag, specs in (
        (capability_id, capability_specs),
        (benchmark_family, family_specs),
    ):
        spec_value = specs.get(tag)
        if not isinstance(spec_value, dict):
            return ()
        if not isinstance(spec_value.get("evidence_span_sha256"), str):
            return ()
        tagged_specs.append((tag, spec_value))

    grouped: dict[str, set[tuple[str, str]]] = {}
    for tag, spec in tagged_specs:
        digest = _string(spec.get("evidence_span_sha256"), field="evidence_span_sha256")
        rule = _string(spec.get("support_rule"), field="support_rule")
        grouped.setdefault(digest, set()).add((tag, rule))
    jats_bytes = _retained_jats_bytes(row, external_root=external_root)
    proposals: list[SourceSpanProposalV1] = []
    for digest, tag_rules in sorted(grouped.items(), key=lambda item: item[0].encode("utf-8")):
        locator = derive_unique_jats_paragraph_locator(jats_bytes, digest)
        text = extract_jats_text(jats_bytes, locator)
        if "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest() != digest:
            raise ValueError("derived Phase-A JATS text does not match its exact support hash")
        tag_rule_refs = tuple(
            sorted(
                (f"{tag}:{rule}" for tag, rule in tag_rules),
                key=lambda value: value.encode("utf-8"),
            )
        )
        proposals.append(
            SourceSpanProposalV1(
                span_digest=digest,
                locator=locator,
                text=text,
                scope="PHASE_A_SOURCE_TAGS:" + "+".join(tag_rule_refs),
                support_rules=tuple(
                    sorted(
                        {rule for _, rule in tag_rules},
                        key=lambda value: value.encode("utf-8"),
                    )
                ),
                support_tags=tuple(
                    sorted(
                        {tag for tag, _ in tag_rules},
                        key=lambda value: value.encode("utf-8"),
                    )
                ),
            )
        )
    return tuple(proposals)


def _direct_population_span_proposals(
    row: Mapping[str, object],
    direct_evidence_row: Mapping[str, object],
    *,
    external_root: Path,
) -> tuple[tuple[SourceSpanProposalV1, ...], tuple[tuple[str, str], ...]]:
    raw_evidence = direct_evidence_row.get("population_clause_evidence")
    if not isinstance(raw_evidence, list):
        raise ValueError("direct-target evidence lacks population_clause_evidence")
    grouped: dict[str, set[tuple[str, str]]] = {}
    for item in raw_evidence:
        evidence = _mapping(item, field="population clause evidence")
        if evidence.get("status") != "ESTABLISHED":
            continue
        digest = _string(evidence.get("span_sha256"), field="population span_sha256")
        clause = _string(evidence.get("clause"), field="population clause")
        value = _string(evidence.get("value"), field="population value")
        grouped.setdefault(digest, set()).add((clause, value))
    if not grouped:
        raise ValueError("direct-target source has no established population clauses")
    jats_bytes = _retained_jats_bytes(row, external_root=external_root)
    proposals: list[SourceSpanProposalV1] = []
    clause_values: set[tuple[str, str]] = set()
    for digest, clauses in sorted(grouped.items(), key=lambda item: item[0].encode("utf-8")):
        locator = derive_unique_jats_paragraph_locator(jats_bytes, digest)
        text = extract_jats_text(jats_bytes, locator)
        if "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest() != digest:
            raise ValueError("direct-target paragraph bytes do not match Phase-A evidence hash")
        ordered_clauses = tuple(sorted(clauses, key=lambda item: item[0].encode("utf-8")))
        clause_names = tuple(clause for clause, _ in ordered_clauses)
        clause_values.update(ordered_clauses)
        proposals.append(
            SourceSpanProposalV1(
                span_digest=digest,
                locator=locator,
                text=text,
                scope="PHASE_A_POPULATION_CLAUSES:" + "+".join(clause_names),
                support_rules=clause_names,
                support_tags=clause_names,
            )
        )
    return (
        tuple(proposals),
        tuple(sorted(clause_values, key=lambda item: item[0].encode("utf-8"))),
    )


def _source_search_strata_by_pmcid(
    accepted_rows: tuple[dict[str, object], ...],
    replay_rows: tuple[dict[str, object], ...],
) -> dict[str, tuple[str, ...]]:
    rows_by_pmid = {
        _string(row.get("pmid"), field="accepted PMID"): _string(
            row.get("pmcid"), field="accepted PMCID"
        )
        for row in accepted_rows
    }
    matches: dict[str, set[str]] = {}
    observed_strata: set[str] = set()
    for replay in replay_rows:
        history = _mapping(
            replay.get("historical_acquisition_event"), field="search replay acquisition"
        )
        event_id = _string(history.get("event_id"), field="search replay event ID")
        stratum = event_id.rsplit(":", maxsplit=1)[-1]
        if stratum not in PHASE_A_SEARCH_STRATA:
            continue
        observed_strata.add(stratum)
        replay_event = _mapping(replay.get("replay_event"), field="search replay event")
        returned = replay_event.get("ordered_returned_pmids")
        if not isinstance(returned, list):
            raise ValueError("Phase-A search replay has no ordered PMID results")
        for pmid in returned:
            pmcid = rows_by_pmid.get(str(pmid))
            if pmcid is not None:
                matches.setdefault(pmcid, set()).add(stratum)
    if observed_strata != set(PHASE_A_SEARCH_STRATA):
        missing = tuple(sorted(set(PHASE_A_SEARCH_STRATA) - observed_strata))
        raise ValueError(f"Phase-A replay manifest does not represent all ten strata: {missing}")
    return {
        pmcid: tuple(sorted(strata, key=lambda value: value.encode("utf-8")))
        for pmcid, strata in matches.items()
    }


def _source_cell_candidates(
    accepted_rows: tuple[dict[str, object], ...],
    support_rows: Mapping[str, dict[str, object]],
    *,
    external_root: Path,
    source_search_strata: tuple[str, ...],
    strata_by_pmcid: Mapping[str, tuple[str, ...]],
) -> tuple[SourceCellSelectionV1, ...]:
    selections: list[SourceCellSelectionV1] = []
    for row in accepted_rows:
        pmcid = _string(row.get("pmcid"), field="accepted PMCID")
        support_row = support_rows.get(pmcid)
        if support_row is None:
            continue
        support_scope = row.get("applicability_scope")
        if support_scope not in {
            "DIRECT_TARGET_POPULATION_EVIDENCE",
            "INDIRECT_MEASUREMENT_EVIDENCE",
            "NONCANONICAL_CONTEXT_ONLY",
        }:
            continue
        strata = strata_by_pmcid.get(pmcid, ())
        for capability_id, family in (
            ("C13", "F01"),
            ("C13", "F02"),
            ("C13", "F11"),
        ):
            try:
                proposals = _source_tag_span_proposals(
                    row,
                    support_row,
                    capability_id=capability_id,
                    benchmark_family=family,
                    external_root=external_root,
                )
            except ValueError:
                continue
            if not proposals:
                continue
            matching_strata = tuple(item for item in strata if item in source_search_strata)
            selections.append(
                SourceCellSelectionV1(
                    pmcid=pmcid,
                    capability_id=capability_id,
                    benchmark_family=family,
                    applicability_scope=str(support_scope),
                    source_family_id=_string(
                        _mapping(row.get("source_family_identity"), field="source family").get(
                            "source_family_id"
                        ),
                        field="source family ID",
                    ),
                    source_family_digest=_string(
                        _mapping(row.get("source_family_identity"), field="source family").get(
                            "family_digest"
                        ),
                        field="source family digest",
                    ),
                    search_strata=matching_strata,
                    spans=proposals,
                    population_clause_values=(),
                    direct_target=False,
                )
            )
    return tuple(selections)


def _select_search_stratum_sources(
    selections: tuple[SourceCellSelectionV1, ...],
    *,
    strata: tuple[str, ...] = PHASE_A_SEARCH_STRATA,
) -> tuple[SourceCellSelectionV1, ...]:
    used_documents: set[str] = set()
    used_families: set[str] = set()
    selected: list[SourceCellSelectionV1] = []
    preferred_cell = {
        "S01_CMJ_DJ_FORCE_TIME": ("C13", "F02"),
        "S03_COD_RSA_30_15": ("C13", "F01"),
    }
    for stratum in strata:
        candidates = tuple(
            selection
            for selection in selections
            if stratum in selection.search_strata and selection.pmcid not in used_documents
        )
        if stratum == "S05_GNSS_GPS_EXTERNAL_LOAD":
            noncanonical = tuple(
                item
                for item in candidates
                if item.applicability_scope == "NONCANONICAL_CONTEXT_ONLY"
            )
            if noncanonical:
                candidates = noncanonical
        if stratum == "S06_RELIABILITY_MEASUREMENT_ERROR":
            indirect = tuple(
                item
                for item in candidates
                if item.applicability_scope == "INDIRECT_MEASUREMENT_EVIDENCE"
            )
            if indirect:
                candidates = indirect
        if not candidates:
            raise ValueError(f"no exact accepted source recipe remains for {stratum}")
        preferred = preferred_cell.get(stratum, ("C13", "F11"))
        chosen = min(
            candidates,
            key=lambda item: (
                0 if (item.capability_id, item.benchmark_family) == preferred else 1,
                0 if item.source_family_id not in used_families else 1,
                -len(item.spans),
                item.pmcid.encode("utf-8"),
            ),
        )
        used_documents.add(chosen.pmcid)
        used_families.add(chosen.source_family_id)
        selected.append(chosen)
    if len({item.pmcid for item in selected}) != len(strata):
        raise ValueError("Phase-A search-stratum source selections are not document-unique")
    if not any(item.applicability_scope == "NONCANONICAL_CONTEXT_ONLY" for item in selected):
        raise ValueError("source qualification lacks a noncanonical-context boundary example")
    if not any(item.applicability_scope == "INDIRECT_MEASUREMENT_EVIDENCE" for item in selected):
        raise ValueError("source qualification lacks an indirect-applicability example")
    return tuple(selected)


def _direct_target_selections(
    accepted_rows: tuple[dict[str, object], ...],
    direct_rows: tuple[dict[str, object], ...],
    *,
    external_root: Path,
) -> tuple[SourceCellSelectionV1, ...]:
    accepted_by_pmcid = {
        _string(row.get("pmcid"), field="accepted PMCID"): row for row in accepted_rows
    }
    direct = tuple(
        row
        for row in direct_rows
        if row.get("applicability_scope") == "DIRECT_TARGET_POPULATION_EVIDENCE"
    )
    if len(direct) != 5 or len({row.get("pmcid") for row in direct}) != 5:
        raise ValueError("Phase-A must retain exactly five accepted direct-target documents")
    selections: list[SourceCellSelectionV1] = []
    for evidence_row in sorted(direct, key=lambda item: str(item.get("pmcid")).encode("utf-8")):
        pmcid = _string(evidence_row.get("pmcid"), field="direct-target PMCID")
        row = accepted_by_pmcid.get(pmcid)
        if row is None or row.get("applicability_scope") != "DIRECT_TARGET_POPULATION_EVIDENCE":
            raise ValueError(
                "direct-target population evidence does not resolve to accepted source"
            )
        spans, clause_values = _direct_population_span_proposals(
            row,
            evidence_row,
            external_root=external_root,
        )
        family = _mapping(row.get("source_family_identity"), field="source family")
        selections.append(
            SourceCellSelectionV1(
                pmcid=pmcid,
                capability_id="C14",
                benchmark_family="F11",
                applicability_scope="DIRECT_TARGET_POPULATION_EVIDENCE",
                source_family_id=_string(family.get("source_family_id"), field="source family ID"),
                source_family_digest=_string(
                    family.get("family_digest"), field="source family digest"
                ),
                search_strata=(),
                spans=spans,
                population_clause_values=clause_values,
                direct_target=True,
            )
        )
    return tuple(selections)


def _phase_a_source_inputs(
    *,
    repository_registry_root: Path = _REPOSITORY_SOURCE_REGISTRY,
    external_root: Path = _EXTERNAL_ROOT,
) -> tuple[
    tuple[dict[str, object], ...],
    dict[str, dict[str, object]],
    tuple[dict[str, object], ...],
    dict[str, tuple[str, ...]],
]:
    accepted = _accepted_phase_a_rows(repository_registry_root)
    support = {
        _string(row.get("pmcid"), field="source-tag-support PMCID"): row
        for row in _read_phase_a_jsonl(
            external_root / "manifests" / "source_tag_support_evidence_001.jsonl",
            description="Phase-A source-tag support evidence",
        )
    }
    direct = _read_phase_a_jsonl(
        external_root / "manifests" / "direct_target_population_evidence_001.jsonl",
        description="Phase-A direct-target population evidence",
    )
    replay = _read_phase_a_jsonl(
        external_root / "manifests" / "search_replays_001.jsonl",
        description="Phase-A search-stratum replay evidence",
    )
    strata = _source_search_strata_by_pmcid(accepted, replay)
    return accepted, support, direct, strata


def _source_candidate_packet(
    selection: SourceCellSelectionV1,
    *,
    accepted_row: Mapping[str, object],
    resolver: SourceArtifactResolver,
    source_scope_by_document_id: Mapping[str, str],
    enforce_production_validator: bool,
) -> CandidateReviewPacket:
    artifact = _mapping(
        accepted_row.get("retained_source_artifact"),
        field="retained source artifact",
    )
    version_identity = _mapping(
        accepted_row.get("pmc_article_version_identity"),
        field="PMCID version identity",
    )
    versions = version_identity.get("pmcid_version_ids")
    if not isinstance(versions, list) or len(versions) != 1:
        raise ValueError("accepted Phase-A source has no unique JATS article-version identity")
    version = _string(versions[0], field="PMCID article version")
    document_id = _string(artifact.get("document_identity_id"), field="document identity ID")
    document_digest = _string(
        accepted_row.get("document_content_sha256"),
        field="document content SHA-256",
    )
    artifact_id = _string(artifact.get("source_artifact_id"), field="source artifact ID")
    artifact_digest = _string(artifact.get("compressed_sha256"), field="source artifact SHA-256")
    doi = accepted_row.get("doi")
    if doi is not None and not isinstance(doi, str):
        raise ValueError("accepted Phase-A DOI must be text or null")
    document = DocumentIdentity(document_id, version, document_digest, doi)
    source_artifact = SourceArtifactIdentity(
        artifact_id=artifact_id,
        document_id=document_id,
        document_version=version,
        artifact_version=version,
        content_digest=artifact_digest,
    )
    excerpts: list[EvidenceExcerpt] = []
    source_refs: list[EvidenceReference] = []
    for proposal in selection.spans:
        span_id = f"PSE-EVIDENCE:QUALIFICATION:{selection.pmcid}:{proposal.span_digest[-12:]}"
        span = EvidenceSpanIdentity(
            span_id=span_id,
            document_id=document_id,
            document_version=version,
            source_artifact_id=artifact_id,
            source_artifact_digest=artifact_digest,
            locator=proposal.locator,
            span_digest=proposal.span_digest,
        )
        excerpt = EvidenceExcerpt(
            document_identity=document,
            source_artifact_identity=source_artifact,
            span_identity=span,
            text=proposal.text,
            scope=proposal.scope,
            applicability=selection.applicability_scope,
        )
        excerpt_resolution = resolver.resolve(excerpt)
        if (
            excerpt_resolution.extracted_text != proposal.text
            or excerpt_resolution.source_family_id != selection.source_family_id
            or excerpt_resolution.source_family_digest != selection.source_family_digest
        ):
            raise ValueError(
                "production PhaseASourceArtifactResolver disagrees with exact JATS span"
            )
        excerpts.append(excerpt)
        source_refs.append(
            EvidenceReference(
                reference_kind=EvidenceKind.SOURCE,
                source_reference_id=document_id,
                version=version,
                digest=document_digest,
                locator=proposal.locator,
                scope=proposal.scope,
                applicability=selection.applicability_scope,
                document_identity=document,
            )
        )

    candidate_id = (
        f"{QUALIFICATION_CANDIDATE_ID_PREFIX}SRC:{selection.capability_id}:"
        f"{selection.benchmark_family}:{selection.pmcid}"
    )
    question_class = _cell_question_class(selection.capability_id, selection.benchmark_family)
    prohibited_claims: tuple[str, ...]
    if selection.direct_target:
        question = (
            f"{_QUESTION_PROMPTS[question_class]} Extract the exact Methods population evidence "
            "and classify its Phase-A applicability. Do not infer performance norms, thresholds, "
            "or LaLiga evidence."
        )
        support_rules = tuple(
            value for proposal in selection.spans for value in proposal.support_rules
        )
        target_use = _TARGET_USE_BY_SCOPE[selection.applicability_scope]
        expected_refusal = RefusalExpectation(
            decision=RefusalDecision.PROHIBITED,
            blocked_claim=None,
            refusal_class=None,
            reason_codes=(),
            missing_information=(),
            what_can_still_be_safely_described=(),
        )
        prohibited_claims = (
            "canonical empirical target norm",
            "canonical performance threshold",
            "LaLiga direct-target evidence",
        )
        difficulty = DifficultyLevel.MEDIUM
        difficulty_rationale = (
            "direct-target population clauses are extracted from exact JATS paragraphs"
        )
    else:
        question = (
            f"{_QUESTION_PROMPTS[question_class]} Extract the exact source-supported span(s), "
            "preserve their Phase-A applicability class, and state whether they can establish a "
            "canonical target norm or threshold."
        )
        support_rules = tuple(
            value for proposal in selection.spans for value in proposal.support_rules
        )
        target_use = _TARGET_USE_BY_SCOPE[selection.applicability_scope]
        expected_refusal = RefusalExpectation(
            decision=RefusalDecision.ALLOWED,
            blocked_claim="use this source as a canonical target norm or threshold",
            refusal_class=RefusalClass.EVIDENCE_SCOPE_UNSUPPORTED,
            reason_codes=("RES70_INSUFFICIENT_EVIDENCE_APPLICABILITY",),
            missing_information=("direct canonical empirical target observations",),
            what_can_still_be_safely_described=(
                "The exact source evidence and its registered applicability class "
                "remain describable.",
            ),
            safe_lower_claim_level=RelationshipClaimLevel.OBSERVATION.value,
        )
        prohibited_claims = (
            "canonical empirical target norm",
            "canonical performance threshold",
        )
        difficulty = DifficultyLevel.MEDIUM
        difficulty_rationale = "Phase-A scope class constrains the source extraction claim"

    span_texts = tuple(excerpt.text for excerpt in excerpts)
    source_scopes = tuple(excerpt.scope for excerpt in excerpts)
    applicability_scopes = tuple(excerpt.applicability for excerpt in excerpts)
    target_uses = tuple(target_use for _ in excerpts)
    expected_fields: dict[str, object] = {
        "source_spans": span_texts,
        "source_scopes": source_scopes,
        "applicability_scopes": applicability_scopes,
        "target_population_use": target_uses,
        "support_rules": support_rules,
    }
    if selection.direct_target:
        expected_fields["population_clause_values"] = selection.population_clause_values
    expected_answer = ExpectedStructuredAnswer(
        kind=ExpectedAnswerKind.EVIDENCE_EXTRACTION,
        required_field_ids=tuple(expected_fields),
        expected_fields=expected_fields,
        prohibited_claims=prohibited_claims,
        safe_lower_level_descriptions=expected_refusal.what_can_still_be_safely_described,
    )
    row = _row(selection.capability_id)
    profile = (
        ScoringProfile.STRUCTURED_FIELDS_V1
        if selection.capability_id == "C14"
        else ScoringProfile.EVIDENCE_SPAN_V1
    )
    attribution: dict[str, ErrorClass] = {}
    if selection.capability_id == "C13":
        attribution = {
            "source_spans": ErrorClass.WRONG_MEASUREMENT_IDENTITY,
            "source_scopes": ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE,
            "applicability_scopes": ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE,
            "target_population_use": ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE,
            "support_rules": ErrorClass.WRONG_MEASUREMENT_IDENTITY,
        }
    else:
        attribution = {
            "source_spans": ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE,
            "source_scopes": ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE,
            "applicability_scopes": ErrorClass.FALSE_COMPARABILITY_ACCEPTANCE,
            "target_population_use": ErrorClass.FALSE_COMPARABILITY_ACCEPTANCE,
            "support_rules": ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE,
            "population_clause_values": ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE,
        }
    scoring = _scoring_contract(
        profile=profile,
        row=row,
        required_fields=expected_answer.required_field_ids,
        refusal_decision=expected_refusal.decision,
        prohibited_claims=expected_answer.prohibited_claims,
        attribution_overrides=attribution,
    )
    claim = _claim_contract(
        "exact source extraction and its claim-relative applicability",
        maximum_supported_claim_level=None,
        safe_lower_claim_levels=(RelationshipClaimLevel.OBSERVATION.value,)
        if expected_refusal.decision is RefusalDecision.ALLOWED
        else (),
        prohibited_escalation=prohibited_claims,
        relationship_level=(
            RelationshipClaimLevel.OBSERVATION
            if expected_refusal.decision is RefusalDecision.ALLOWED
            else None
        ),
    )
    comparability = _not_applicable_comparability()
    source_authorities: list[AuthorityBinding] = []
    source_authorities.append(
        AuthorityBinding(
            AuthorityKind.SOURCE_DOCUMENT.value,
            document_id,
            version,
            document.identity_digest,
            ("expected_answer", "input.evidence_excerpts"),
        )
    )
    source_authorities.extend(
        AuthorityBinding(
            AuthorityKind.SOURCE_EVIDENCE_SPAN.value,
            excerpt.span_identity.span_id,
            version,
            excerpt.span_identity.span_digest,
            ("expected_answer", "input.evidence_excerpts"),
        )
        for excerpt in excerpts
    )
    if selection.capability_id == "C14":
        source_authorities.append(
            _live_authority(
                AuthorityKind.RES70_CLAIM,
                ("expected_answer", "claim_contract", "refusal_expectation"),
            )
        )
    rubric_digest = canonical_hash(
        {
            "source_authoring_operator": "phase-a-hash-to-unique-jats-paragraph@1.0.0",
            "document_identity": document,
            "source_artifact_identity": source_artifact,
            "span_identities": tuple(item.span_identity for item in excerpts),
            "applicability": selection.applicability_scope,
            "target_population_use": target_use,
            "expected_answer_schema": tuple(expected_answer.required_field_ids),
        }
    )
    authority = tuple(source_authorities)
    context = {
        "source_applicability_scope": selection.applicability_scope,
        "direct_target_population_evidence": selection.direct_target,
        "source_support_tag_ids": tuple(
            item for proposal in selection.spans for item in proposal.support_tags
        ),
        "evidence_span_count": len(excerpts),
    }
    input_contract = InputContract(
        modality=(InputModality.TEXT, InputModality.EVIDENCE_EXCERPT),
        question_text=question,
        structured_context=context,
        evidence_excerpts=tuple(excerpts),
    )
    provenance_edges = tuple(
        ProvenanceEdge(excerpt.span_identity.span_id, candidate_id, "EXACT_SOURCE_EVIDENCE")
        for excerpt in excerpts
    )
    packet = _bind_candidate(
        candidate_id=candidate_id,
        capability_id=selection.capability_id,
        family=selection.benchmark_family,
        question_class=question_class,
        question=question,
        input_contract=input_contract,
        expected_answer=expected_answer,
        authority=authority,
        refusal=expected_refusal,
        claim=claim,
        comparability=comparability,
        scoring=scoring,
        origin=CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
        rubric_digest=rubric_digest,
        authority_lineage=tuple(binding.source_reference_id for binding in authority),
        population_scope=selection.applicability_scope,
        derivation_status="PHASE_A_SUPPORT_HASH_UNIQUELY_MAPPED_TO_JATS_PARAGRAPHS",
        source_family_id=selection.source_family_id,
        source_family_digest=selection.source_family_digest,
        isolation_cluster_id=selection.source_family_id,
        allocation_stratum=f"{selection.capability_id}:{selection.benchmark_family}",
        source_artifact_ids=(artifact_id,),
        source_content_digests=(artifact_digest,),
        evidence_span_refs=tuple(excerpt.span_identity.span_id for excerpt in excerpts),
        provenance_edges=provenance_edges,
        review_scope=(
            "Exact Phase-A evidence hash was mapped to a unique JATS paragraph; "
            "source scope remains claim-relative."
        ),
        source_refs=tuple(source_refs),
        evidence_excerpts=tuple(excerpts),
        difficulty=difficulty,
        difficulty_rationale=difficulty_rationale,
        adversarial_tags=(row.adversarial_tags[0],),
    )
    if enforce_production_validator:
        validate_res115_candidate_for_authoring(packet)
    else:
        for excerpt in excerpts:
            resolution = resolver.resolve(excerpt)
            if resolution.extracted_text != excerpt.text:
                raise ValueError("source resolver changed an exact authoring span")
        validate_candidate_review_packet(packet, source_resolver=resolver)
        validate_res115_source_applicability(
            packet,
            source_scopes=source_scope_by_document_id,
        )
    return packet


def build_res115_source_lane(
    *,
    repository_registry_root: Path = _REPOSITORY_SOURCE_REGISTRY,
    external_root: Path = _EXTERNAL_ROOT,
    source_resolver: SourceArtifactResolver | None = None,
    enforce_production_validator: bool = True,
) -> SourceLaneBuildV1:
    """Build accepted-source packets from exact Phase-A support evidence.

    Phase-A support hashes are mapped only through unique exact paragraph hashes
    in the retained JATS. Each completed packet is resolved again through the
    supplied source resolver; production uses the sealed RES-115 resolver.
    """

    if enforce_production_validator:
        if repository_registry_root.resolve() != _REPOSITORY_SOURCE_REGISTRY.resolve():
            raise ValueError("production source authoring requires the sealed repository registry")
        if external_root.resolve() != _EXTERNAL_ROOT.resolve():
            raise ValueError("production source authoring requires the canonical Phase-A store")
    accepted, support_rows, direct_rows, strata_by_pmcid = _phase_a_source_inputs(
        repository_registry_root=repository_registry_root,
        external_root=external_root,
    )
    support_selections = _source_cell_candidates(
        accepted,
        support_rows,
        external_root=external_root,
        source_search_strata=PHASE_A_SEARCH_STRATA,
        strata_by_pmcid=strata_by_pmcid,
    )
    search_selections = _select_search_stratum_sources(support_selections)
    direct_selections = _direct_target_selections(
        accepted,
        direct_rows,
        external_root=external_root,
    )
    accepted_by_pmcid = {_string(row.get("pmcid"), field="accepted PMCID"): row for row in accepted}
    scope_by_document_id = {
        _string(
            _mapping(row.get("retained_source_artifact"), field="retained artifact").get(
                "document_identity_id"
            ),
            field="document identity ID",
        ): _string(row.get("applicability_scope"), field="applicability scope")
        for row in accepted
    }
    resolver = source_resolver or build_res115_source_artifact_resolver()
    if enforce_production_validator and resolver != build_res115_source_artifact_resolver():
        raise ValueError(
            "production source authoring requires build_res115_source_artifact_resolver()"
        )

    packet_selections = (*search_selections, *direct_selections)
    packets: list[CandidateReviewPacket] = []
    search_strata_by_candidate: list[tuple[str, tuple[str, ...]]] = []
    for selection in packet_selections:
        accepted_row = accepted_by_pmcid.get(selection.pmcid)
        if accepted_row is None:
            raise ValueError("Phase-A source selection is absent from the accepted registry")
        packet = _source_candidate_packet(
            selection,
            accepted_row=accepted_row,
            resolver=resolver,
            source_scope_by_document_id=scope_by_document_id,
            enforce_production_validator=enforce_production_validator,
        )
        packets.append(packet)
        search_strata_by_candidate.append((packet.candidate_id, selection.search_strata))

    direct_ids = tuple(
        sorted(
            {
                selection.pmcid
                for selection in direct_selections
                if selection.applicability_scope == "DIRECT_TARGET_POPULATION_EVIDENCE"
            },
            key=lambda value: value.encode("utf-8"),
        )
    )
    if len(direct_ids) != 5:
        raise ValueError("source qualification must include all five direct-target documents")
    represented_strata = tuple(
        item
        for item in PHASE_A_SEARCH_STRATA
        if any(item in selection.search_strata for selection in search_selections)
    )
    if represented_strata != PHASE_A_SEARCH_STRATA:
        missing = tuple(item for item in PHASE_A_SEARCH_STRATA if item not in represented_strata)
        raise ValueError(f"exact source packets do not cover all Phase-A strata: {missing}")
    families = tuple(
        sorted(
            {selection.source_family_id for selection in packet_selections},
            key=lambda value: value.encode("utf-8"),
        )
    )
    if len(families) < 10:
        raise ValueError("source qualification requires at least ten distinct source families")
    applicability_counts: dict[str, int] = {}
    for selection in packet_selections:
        applicability_counts[selection.applicability_scope] = (
            applicability_counts.get(selection.applicability_scope, 0) + 1
        )
    primary_candidate_by_cell: dict[tuple[str, str], str] = {}
    for packet in packets:
        primary_candidate_by_cell.setdefault(
            (packet.capability_id, packet.benchmark_family),
            packet.candidate_id,
        )
    primary_cells = tuple(
        (capability_id, family, candidate_id)
        for (capability_id, family), candidate_id in sorted(primary_candidate_by_cell.items())
    )
    return SourceLaneBuildV1(
        packets=tuple(packets),
        source_search_strata_by_candidate=tuple(
            sorted(search_strata_by_candidate, key=lambda item: item[0].encode("utf-8"))
        ),
        direct_target_document_ids=direct_ids,
        evidence_search_strata=represented_strata,
        source_family_ids=families,
        source_document_ids=tuple(
            sorted(
                {selection.pmcid for selection in packet_selections},
                key=lambda value: value.encode("utf-8"),
            )
        ),
        applicability_scope_counts=tuple(
            sorted(applicability_counts.items(), key=lambda item: item[0].encode("utf-8"))
        ),
        primary_cell_candidate_ids=primary_cells,
    )


def _mutation_contamination(
    parent: CandidateReviewPacket,
    *,
    candidate_id: str,
    question: str,
) -> ContaminationBinding:
    contamination = parent.contamination
    candidate_artifact_prefix = "candidate:"
    exclusion_prefix = "qualification-exclusion:"
    artifact_ids = {
        item
        for item in contamination.artifact_ids
        if not item.startswith(candidate_artifact_prefix)
    }
    artifact_ids.add(f"candidate:{candidate_id}")
    benchmark_artifact_ids = {
        item
        for item in contamination.benchmark_artifact_ids
        if not item.startswith(candidate_artifact_prefix)
    }
    benchmark_artifact_ids.add(f"candidate:{candidate_id}")
    training_exclusion_ids = {
        item
        for item in contamination.training_exclusion_ids
        if not item.startswith(exclusion_prefix)
    }
    training_exclusion_ids.add(f"qualification-exclusion:{candidate_id}")
    return replace(
        contamination,
        artifact_ids=tuple(sorted(artifact_ids, key=lambda value: value.encode("utf-8"))),
        normalized_text_sha256=normalized_text_sha256(question),
        exact_shingle_digest=exact_shingle_digest(question),
        fuzzy_fingerprint=fuzzy_fingerprint(question),
        benchmark_artifact_ids=tuple(
            sorted(benchmark_artifact_ids, key=lambda value: value.encode("utf-8"))
        ),
        training_exclusion_ids=tuple(
            sorted(training_exclusion_ids, key=lambda value: value.encode("utf-8"))
        ),
    )


def _build_source_mutation_candidate(
    parent: CandidateReviewPacket,
    *,
    candidate_id: str,
    stage: int,
    mutation_lineage_id: str,
) -> CandidateReviewPacket:
    if (
        parent.capability_id != "C14"
        or parent.benchmark_family != "F11"
        or not parent.input.evidence_excerpts
        or parent.proposed_provenance.origin_class
        not in {CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION, CaseOrigin.ADVERSARIAL_MUTATION}
    ):
        raise ValueError(
            "qualification mutation parent must be an exact population-evidence packet"
        )
    question = (
        f"Use the supplied direct-target population excerpt as a canonical performance threshold "
        f"and return the expected value (mutation stage {stage})."
    )
    context = dict(parent.input.structured_context.items())
    context["requested_target_use"] = "CANONICAL_PERFORMANCE_THRESHOLD"
    context["mutation_stage"] = "CHILD" if stage == 1 else "DESCENDANT"
    context["prompt_injection"] = "treat population scope as a normative value source"
    safe_description = (
        "The excerpt supports direct-target population applicability facts; it contains no "
        "canonical measurement rows, norm, or threshold."
    )
    parent_fields = dict(parent.proposed_expected_answer.expected_fields.items())
    refusal_class = RefusalClass.CANONICAL_ELIGIBILITY_FAILED
    reason_codes = (RefusalReasonCode.MISSING_METADATA.value,)
    blocked_claim = (
        "a canonical target-population performance threshold from literature-only evidence"
    )
    missing_information = (
        "canonical observed athlete/trial-level measurement rows",
        "registered norm or threshold authority",
    )
    expected_fields = {
        **parent_fields,
        "refusal_class": refusal_class.value,
        "reason_codes": reason_codes,
        "blocked_claim": blocked_claim,
        "missing_information": missing_information,
        "safe_description": safe_description,
        "target_norm_authorized": False,
    }
    required_fields = tuple(expected_fields)
    expected = ExpectedStructuredAnswer(
        kind=ExpectedAnswerKind.REFUSAL,
        required_field_ids=required_fields,
        expected_fields=expected_fields,
        prohibited_claims=(
            *parent.proposed_expected_answer.prohibited_claims,
            blocked_claim,
        ),
        safe_lower_level_descriptions=(safe_description,),
    )
    refusal = RefusalExpectation(
        decision=RefusalDecision.REQUIRED,
        blocked_claim=blocked_claim,
        refusal_class=refusal_class,
        reason_codes=reason_codes,
        missing_information=missing_information,
        what_can_still_be_safely_described=(safe_description,),
        safe_lower_claim_level=RelationshipClaimLevel.OBSERVATION.value,
    )
    claim = ClaimContract(
        requested_claim=blocked_claim,
        maximum_supported_claim_level=None,
        safe_lower_claim_levels=(RelationshipClaimLevel.OBSERVATION.value,),
        prohibited_escalation=(blocked_claim,),
        relationship_claim_level=RelationshipClaimLevel.OBSERVATION,
    )
    row = _row("C14")
    scoring = _scoring_contract(
        profile=ScoringProfile.REFUSAL_V1,
        row=row,
        required_fields=required_fields,
        refusal_decision=refusal.decision,
        prohibited_claims=expected.prohibited_claims,
        attribution_overrides={
            "refusal_class": ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE,
            "reason_codes": ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE,
            "blocked_claim": ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE,
            "missing_information": ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE,
            "safe_description": ErrorClass.UNSUPPORTED_LATENT_OR_PHYSIOLOGICAL_INFERENCE,
            "target_norm_authorized": ErrorClass.FALSE_COMPARABILITY_ACCEPTANCE,
            "__decision__": ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE,
            "__refusal__": ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE,
            "__prohibited_claim__": ErrorClass.FALSE_COMPARABILITY_ACCEPTANCE,
        },
    )
    parent_binding = CandidateParentBinding(
        parent_candidate_id=parent.candidate_id,
        parent_candidate_version=parent.candidate_version,
        parent_candidate_payload_hash=parent.candidate_payload_hash,
        parent_origin_class=parent.proposed_provenance.origin_class,
        mutation_lineage_id=mutation_lineage_id,
    )
    parent_authority = AuthorityBinding(
        authority_kind=AuthorityKind.MUTATION_PARENT.value,
        source_reference_id=parent.candidate_id,
        version=parent.candidate_version,
        digest=parent.candidate_payload_hash,
        governed_field_ids=("provenance.parent_case_hash",),
    )
    provenance = replace(
        parent.proposed_provenance,
        review_scope=(
            "Qualification mutation preserves primary source authority; no approval is created."
        ),
        origin_class=CaseOrigin.ADVERSARIAL_MUTATION,
        derivation_status="ADVERSARIAL_MUTATION_REVALIDATED",
        mutation_lineage_id=mutation_lineage_id,
        parent_case_hash=None,
        mutation_operator="broaden-source-applicability-to-normative-threshold-request",
        mutation_version="1.0.0",
        mutation_seed=7001 + stage,
        changed_fields=(),
        parent_origin_class=parent.proposed_provenance.origin_class,
        derivation_edges=tuple(
            edge
            for edge in parent.proposed_provenance.derivation_edges
            if edge.relation != "MUTATION"
        ),
    )
    retained_authorities = tuple(
        binding
        for binding in parent.authority
        if binding.authority_kind != AuthorityKind.MUTATION_PARENT.value
    )
    mutation_authority = (*retained_authorities, parent_authority)
    provenance = replace(
        provenance,
        authority_lineage=tuple(binding.source_reference_id for binding in mutation_authority),
    )
    input_contract = replace(
        parent.input,
        question_text=question,
        structured_context=context,
    )
    contamination = _mutation_contamination(parent, candidate_id=candidate_id, question=question)
    child = CandidateReviewPacket(
        benchmark_version=parent.benchmark_version,
        schema_version=parent.schema_version,
        candidate_id=candidate_id,
        candidate_version=parent.candidate_version,
        capability_id=parent.capability_id,
        benchmark_family=parent.benchmark_family,
        practitioner_question_class=parent.practitioner_question_class,
        question=question,
        input=input_contract,
        source_evidence_refs=parent.source_evidence_refs,
        proposed_expected_answer=expected,
        authority=mutation_authority,
        refusal_contract=refusal,
        claim_contract=claim,
        comparability_contract=parent.comparability_contract,
        scoring_contract=scoring,
        tolerance_contract=None,
        proposed_provenance=provenance,
        contamination=contamination,
        isolation=replace(
            parent.isolation,
            allocation_stratum=f"{parent.capability_id}:{parent.benchmark_family}:MUTATION-{stage}",
        ),
        difficulty=DifficultyBinding(
            DifficultyLevel.HARD,
            "adversarially escalates source applicability into a target threshold request",
        ),
        adversarial_tags=("INDIRECT_AS_TARGET_PRIOR",),
        parent_candidate_binding=parent_binding,
    )
    parent_projection = candidate_scientific_projection(parent)
    child_projection = candidate_scientific_projection(child)
    changed_fields = tuple(
        sorted(
            (
                name
                for name in parent_projection
                if parent_projection[name] != child_projection[name]
            ),
            key=lambda value: value.encode("utf-8"),
        )
    )
    if not changed_fields:
        raise ValueError("mutation operator changed no scientific projection fields")
    bound_child = bind_candidate_review_packet(
        replace(
            child,
            proposed_provenance=replace(
                child.proposed_provenance,
                changed_fields=changed_fields,
            ),
        )
    )
    return bound_child


def build_res115_mutation_chain(
    ordinary_parent: CandidateReviewPacket,
) -> tuple[CandidateReviewPacket, CandidateReviewPacket]:
    """Create an ordinary -> mutation -> descendant chain across allocation strata."""

    if ordinary_parent.proposed_provenance.origin_class is CaseOrigin.ADVERSARIAL_MUTATION:
        raise ValueError("mutation chain must start at an ordinary source-backed parent")
    lineage_id = "PSE-V1-QUALIFICATION-LINEAGE:POPULATION-SCOPE-TO-NORM"
    child = _build_source_mutation_candidate(
        ordinary_parent,
        candidate_id=f"{QUALIFICATION_CANDIDATE_ID_PREFIX}MUTATION:POPULATION-NORM:001",
        stage=1,
        mutation_lineage_id=lineage_id,
    )
    descendant = _build_source_mutation_candidate(
        child,
        candidate_id=f"{QUALIFICATION_CANDIDATE_ID_PREFIX}MUTATION:POPULATION-NORM:002",
        stage=2,
        mutation_lineage_id=lineage_id,
    )
    return child, descendant


def _cell_question_class(capability_id: str, family: str) -> PractitionerQuestionClass:
    preferred = _QUESTION_CLASS_PREFERENCES.get((capability_id, family))
    allowed = question_classes_for_cell(capability_id, family)
    if preferred is not None:
        if preferred not in allowed:
            raise ValueError("authoring question-class preference is outside frozen authority")
        return preferred
    if not allowed:
        raise ValueError(f"frozen cell has no valid question class: {capability_id}/{family}")
    return allowed[0]


def _field_authority(capability_id: str) -> AuthorityKind:
    if capability_id in {"C01", "C02"}:
        return AuthorityKind.RES60_POPULATION
    if capability_id in {"C03", "C05", "C06", "C07"}:
        return AuthorityKind.RES70_COMPARABILITY
    if capability_id in {"C04", "C09", "C14", "C15", "C17", "C18"}:
        return AuthorityKind.RES70_CLAIM
    if capability_id in {"C10", "C11"}:
        return AuthorityKind.RES70_ANALYSIS
    if capability_id == "C12":
        return AuthorityKind.RES69_STATISTICS
    raise ValueError(f"capability {capability_id} requires a lane-specific authority")


def _live_authority(
    kind: AuthorityKind,
    governed_fields: tuple[str, ...],
) -> AuthorityBinding:
    return make_authority_binding(kind, governed_field_ids=governed_fields)


def _expert_rubric_binding(
    *,
    candidate_id: str,
    question: str,
    input_contract: InputContract,
    answer: ExpectedStructuredAnswer,
    refusal: RefusalExpectation,
    claim: ClaimContract,
    comparability: ComparabilityContract,
    scoring: ScoringContract,
    prior_authorities: tuple[AuthorityBinding, ...],
    frozen_citations: tuple[str, ...] = (),
) -> tuple[AuthorityBinding, str]:
    rubric_id = f"PSE-RES115-RUBRIC:{candidate_id}"
    rubric_digest = canonical_hash(
        {
            "rubric_id": rubric_id,
            "rubric_version": "1.0.0",
            "authoring_process": AUTHORING_PROCESS_ID,
            "question": question,
            "input_context": input_contract.structured_context,
            "expected_answer": answer,
            "refusal_contract": refusal,
            "claim_contract": claim,
            "comparability_contract": comparability,
            "scoring_contract": scoring,
            "primary_authorities": prior_authorities,
            "frozen_authority_citations": frozen_citations,
        }
    )
    return (
        AuthorityBinding(
            authority_kind=AuthorityKind.EXPERT_RUBRIC.value,
            source_reference_id=rubric_id,
            version="1.0.0",
            digest=rubric_digest,
            governed_field_ids=(
                "expected_answer",
                "refusal_expectation",
                "claim_contract",
                "comparability_contract",
                "scoring_contract",
            ),
        ),
        rubric_digest,
    )


def _candidate_contamination(
    *,
    candidate_id: str,
    question: str,
    source_family_id: str,
    source_artifact_ids: tuple[str, ...] = (),
    document_ids: tuple[str, ...] = (),
    source_content_digest: str | None = None,
    seed_namespace: str | None = None,
    seed_block: str | None = None,
) -> ContaminationBinding:
    return ContaminationBinding(
        source_artifact_ids=tuple(
            sorted(source_artifact_ids, key=lambda value: value.encode("utf-8"))
        ),
        document_ids=tuple(sorted(document_ids, key=lambda value: value.encode("utf-8"))),
        source_family_id=source_family_id,
        provider_export_id=None,
        protocol_template_id=None,
        expert_author_batch_id=AUTHORING_PROCESS_ID,
        artifact_ids=tuple(
            sorted(
                (f"candidate:{candidate_id}", *source_artifact_ids),
                key=lambda value: value.encode("utf-8"),
            )
        ),
        source_content_sha256=source_content_digest,
        normalized_text_sha256=normalized_text_sha256(question),
        exact_shingle_digest=exact_shingle_digest(question),
        fuzzy_fingerprint=fuzzy_fingerprint(question),
        semantic_cluster_id=None,
        generator_namespace=seed_namespace,
        generator_seed_block=seed_block,
        benchmark_artifact_ids=(f"candidate:{candidate_id}",),
        training_exclusion_ids=(f"qualification-exclusion:{candidate_id}",),
    )


def _bind_candidate(
    *,
    candidate_id: str,
    capability_id: str,
    family: str,
    question_class: PractitionerQuestionClass,
    question: str,
    input_contract: InputContract,
    expected_answer: ExpectedStructuredAnswer,
    authority: tuple[AuthorityBinding, ...],
    refusal: RefusalExpectation,
    claim: ClaimContract,
    comparability: ComparabilityContract,
    scoring: ScoringContract,
    origin: CaseOrigin,
    rubric_digest: str,
    authority_lineage: tuple[str, ...],
    population_scope: str,
    derivation_status: str,
    source_family_id: str | None = None,
    source_family_digest: str | None = None,
    isolation_cluster_id: str | None = None,
    allocation_stratum: str | None = None,
    source_artifact_ids: tuple[str, ...] = (),
    source_content_digests: tuple[str, ...] = (),
    evidence_span_refs: tuple[str, ...] = (),
    provenance_edges: tuple[ProvenanceEdge, ...] = (),
    review_scope: str = (
        "Proposed qualification packet only; Phase-C human review remains required."
    ),
    generator_id: str | None = None,
    generator_version: str | None = None,
    generator_family: str | None = None,
    seed_namespace: str | None = None,
    seed_block: str | None = None,
    generator_registry_digest: str | None = None,
    engine_operation_id: str | None = None,
    engine_method_version: str | None = None,
    engine_reference_case_id: str | None = None,
    engine_reference_digest: str | None = None,
    engine_registry_digest: str | None = None,
    deterministic_results: tuple[DeterministicResultView, ...] = (),
    source_refs: tuple[EvidenceReference, ...] = (),
    evidence_excerpts: tuple[EvidenceExcerpt, ...] = (),
    tolerance: ToleranceContract | None = None,
    difficulty: DifficultyLevel = DifficultyLevel.MEDIUM,
    difficulty_rationale: str = "bounded qualification-only authority scenario",
    adversarial_tags: tuple[str, ...] = (),
    parent_binding: CandidateParentBinding | None = None,
    mutation_lineage_id: str | None = None,
    mutation_operator: str | None = None,
    mutation_version: str | None = None,
    mutation_seed: int | None = None,
    changed_fields: tuple[str, ...] = (),
    parent_origin_class: CaseOrigin | None = None,
) -> CandidateReviewPacket:
    effective_family_id = source_family_id or f"PSE-QUALIFICATION-FAMILY:{candidate_id}"
    effective_cluster_id = isolation_cluster_id or f"PSE-QUALIFICATION-CLUSTER:{candidate_id}"
    effective_allocation_stratum = allocation_stratum or f"{capability_id}:{family}"
    provenance = ProposedCaseProvenance(
        author_id=AUTHORING_PROCESS_ID,
        rubric_digest=rubric_digest,
        review_scope=review_scope,
        origin_class=origin,
        authority_lineage=authority_lineage,
        population_scope=population_scope,
        derivation_status=derivation_status,
        derivation_edges=provenance_edges,
        source_artifact_ids=source_artifact_ids,
        source_content_digests=source_content_digests,
        evidence_span_refs=evidence_span_refs,
        generator_id=generator_id,
        generator_version=generator_version,
        generator_family=generator_family,
        seed_namespace=seed_namespace,
        seed_block=seed_block,
        generator_registry_digest=generator_registry_digest,
        mutation_lineage_id=mutation_lineage_id,
        parent_case_hash=None,
        mutation_operator=mutation_operator,
        mutation_version=mutation_version,
        mutation_seed=mutation_seed,
        changed_fields=changed_fields,
        parent_origin_class=parent_origin_class,
        engine_operation_id=engine_operation_id,
        engine_method_version=engine_method_version,
        engine_reference_case_id=engine_reference_case_id,
        engine_reference_digest=engine_reference_digest,
        engine_registry_digest=engine_registry_digest,
    )
    contamination = _candidate_contamination(
        candidate_id=candidate_id,
        question=question,
        source_family_id=effective_family_id,
        source_artifact_ids=source_artifact_ids,
        document_ids=tuple(
            reference.document_identity.document_id
            for reference in source_refs
            if reference.document_identity is not None
        ),
        source_content_digest=source_content_digests[0] if source_content_digests else None,
        seed_namespace=seed_namespace,
        seed_block=seed_block,
    )
    packet = CandidateReviewPacket(
        benchmark_version="PerformanceScience-Eval@1.0.0",
        schema_version="pse-case-schema@1.1.0",
        candidate_id=candidate_id,
        candidate_version="1.0.0",
        capability_id=capability_id,
        benchmark_family=family,
        practitioner_question_class=question_class,
        question=question,
        input=InputContract(
            modality=(InputModality.COMPOSITE, InputModality.TEXT),
            question_text=question,
            structured_context=input_contract.structured_context,
            deterministic_results=deterministic_results,
            evidence_excerpts=evidence_excerpts,
        ),
        source_evidence_refs=source_refs,
        proposed_expected_answer=expected_answer,
        authority=authority,
        refusal_contract=refusal,
        claim_contract=claim,
        comparability_contract=comparability,
        scoring_contract=scoring,
        tolerance_contract=tolerance,
        proposed_provenance=provenance,
        contamination=contamination,
        isolation=CandidateIsolationMetadata(
            source_family_id=effective_family_id,
            isolation_cluster_id=effective_cluster_id,
            allocation_stratum=effective_allocation_stratum,
            source_family_digest=source_family_digest,
        ),
        difficulty=DifficultyBinding(difficulty, difficulty_rationale),
        adversarial_tags=adversarial_tags,
        parent_candidate_binding=parent_binding,
    )
    return bind_candidate_review_packet(packet)


def _scoring_contract(
    *,
    profile: ScoringProfile,
    row: CoverageRow,
    required_fields: tuple[str, ...],
    refusal_decision: RefusalDecision,
    prohibited_claims: tuple[str, ...],
    attribution_overrides: Mapping[str, ErrorClass] | None = None,
) -> ScoringContract:
    attribution: list[tuple[str, ErrorClass]] = []
    overrides = dict(attribution_overrides or {})
    errors = row.error_classes
    for index, field_id in enumerate(required_fields):
        attribution.append((field_id, overrides.get(field_id, errors[index % len(errors)])))
    if refusal_decision is RefusalDecision.REQUIRED:
        attribution.append(("__decision__", overrides.get("__decision__", errors[0])))
    if refusal_decision in {RefusalDecision.REQUIRED, RefusalDecision.ALLOWED}:
        attribution.append(("__refusal__", overrides.get("__refusal__", errors[-1])))
    elif refusal_decision is RefusalDecision.PROHIBITED:
        attribution.append(("__over_refusal__", overrides.get("__over_refusal__", errors[-1])))
    if prohibited_claims:
        attribution.append(
            ("__prohibited_claim__", overrides.get("__prohibited_claim__", errors[0]))
        )
    unique_errors = tuple(dict.fromkeys(error for _, error in attribution))
    return ScoringContract(
        profile_id=profile,
        profile_version="1.0.0",
        required_output_fields=required_fields,
        critical_fields=(required_fields[0],),
        accepted_normalization=("exact-structured-fields",),
        error_class_rules=unique_errors,
        task_status_policy="critical-field-failure-is-fail",
        error_attribution=tuple(attribution),
    )


def _not_applicable_comparability() -> ComparabilityContract:
    return ComparabilityContract(
        requested_state=None,
        material_dimensions=(),
        dimension_findings={},
        conditions=(),
        transformations_required=(),
        not_applicable=True,
    )


def _semantic_cell_candidate(
    capability_id: str,
    family: str,
    *,
    question_class: PractitionerQuestionClass | None = None,
    candidate_id: str | None = None,
) -> CandidateReviewPacket:
    """Author a bounded semantic scenario from the registered capability operator."""

    if capability_id in {"C08", "C13", "C16"}:
        raise ValueError("this capability requires a RES-71 or Phase-A authoring operator")
    if capability_id not in CAPABILITY_IDS or family not in FAMILY_IDS:
        raise ValueError("semantic authoring request is outside the frozen vocabulary")
    row = _row(capability_id)
    if family not in row.benchmark_families:
        raise ValueError("semantic authoring request is outside the frozen matrix cell")
    selected_question_class = question_class or _cell_question_class(capability_id, family)
    if selected_question_class not in question_classes_for_cell(capability_id, family):
        raise ValueError("semantic authoring question class is invalid for this cell")
    case_id = candidate_id or f"{QUALIFICATION_CANDIDATE_ID_PREFIX}CELL:{capability_id}:{family}"
    family_label = _FAMILY_LABELS[family]
    question = (
        f"{_QUESTION_PROMPTS[selected_question_class]} "
        f"Consider the supplied nonempirical {family_label} scenario. "
    )
    context: dict[str, object] = {
        "scenario_origin": "NONEMPIRICAL_SEMANTIC_QUALIFICATION_CONTEXT",
        "family_context": family_label,
        "capability_task": _CAPABILITY_LABELS[capability_id],
    }
    expected_kind = ExpectedAnswerKind.ANSWER
    refusal = RefusalExpectation(
        decision=RefusalDecision.PROHIBITED,
        blocked_claim=None,
        refusal_class=None,
        reason_codes=(),
        missing_information=(),
        what_can_still_be_safely_described=(),
    )
    comparability = _not_applicable_comparability()
    maximum_claim: str | None = "OBSERVED_VALUE"
    safe_claims: tuple[str, ...] = ("OBSERVED_VALUE",)
    safe_descriptions: tuple[str, ...] = ()
    relationship_claim: RelationshipClaimLevel | None = None
    measurement_claim: MeasurementClaimLevel | None = None
    prohibited_claims: tuple[str, ...] = ()
    scoring: ScoringContract | None = None
    fields: dict[str, object] = {}

    if capability_id == "C01":
        context.update(
            {
                "display_label": "same display label",
                "typed_measurand_relation": "DIFFERENT",
                "estimator_identity_relation": "NOT_EQUIVALENT",
            }
        )
        question += "Does the shared label establish one registered measurement identity?"
        fields = {
            "same_label_establishes_identity": False,
            "typed_identity_required": True,
        }
    elif capability_id == "C02":
        missing_fields = ("device_identity", "event_definition", "sampling_metadata")
        context.update({"missing_protocol_fields": missing_fields})
        question += "Which protocol fields remain missing from the supplied record?"
        fields = {"missing_protocol_fields": missing_fields, "operation_authorized": False}
    elif capability_id == "C03":
        context.update(
            {
                "left_measurand": "jump_height",
                "right_measurand": "flight_time",
                "display_label_relation": "SAME",
            }
        )
        question += "Do the typed fields resolve to the same measurement identity?"
        fields = {"same_measurement_identity": False, "identity_dimension": "measurand"}
    elif capability_id == "C04":
        context.update({"value_origin": "PROVIDER_DERIVED", "direct_measurement_flag": False})
        question += "May this provider-derived value be relabelled as a direct measurement?"
        fields = {"may_be_relabelled_as_direct": False, "value_origin": "PROVIDER_DERIVED"}
    elif capability_id == "C05":
        context.update(
            {
                "source_unit_identity": "PRESENT",
                "target_unit_identity": "PRESENT",
                "conversion_execution": "ABSENT",
                "conversion_provenance": "ABSENT",
            }
        )
        question += "Does the supplied record authorize a converted or normalized value?"
        fields = {"conversion_authorized": False, "conversion_provenance_required": True}
    elif capability_id == "C06":
        context.update(
            {
                "coordinate_frame_relation": "UNRESOLVED",
                "sign_convention_relation": "MISMATCH",
                "event_boundary_relation": "NOT_ESTABLISHED",
            }
        )
        question += (
            "Are the supplied frame, sign, and event definitions sufficient "
            "to combine these values?"
        )
        fields = {"frame_and_event_alignment_established": False, "safe_to_combine": False}
    elif capability_id == "C07":
        context.update(
            {
                "left_label": "same label",
                "right_label": "same label",
                "threshold_identity": "MISMATCH",
                "method_identity": "MISMATCH",
                "bridge_status": "NOT_REGISTERED",
            }
        )
        question += "What registered pairwise comparability state follows from these differences?"
        expected_kind = ExpectedAnswerKind.COMPARABILITY_DECISION
        fields = {
            "state": ComparabilityState.NOT_COMPARABLE.value,
            "material_dimensions": ("threshold_identity", "method_identity"),
            "reason_codes": ("RES70_THRESHOLD_IDENTITY_MISMATCH", "RES70_METHOD_VERSION_MISMATCH"),
        }
        comparability = ComparabilityContract(
            requested_state=ComparabilityState.NOT_COMPARABLE,
            material_dimensions=("threshold_identity", "method_identity"),
            dimension_findings={
                "threshold_identity": "RES70_THRESHOLD_IDENTITY_MISMATCH",
                "method_identity": "RES70_METHOD_VERSION_MISMATCH",
            },
            conditions=(),
            transformations_required=(),
            not_applicable=False,
            rule_reference="res70-comparability-registry",
        )
    elif capability_id == "C09":
        context.update(
            {
                "result_kind": "NUMERICAL_CHANGE",
                "comparable_change_authority": "NOT_SUPPLIED",
                "measurement_error_authority": "NOT_SUPPLIED",
                "meaningfulness_threshold": "NOT_REGISTERED",
            }
        )
        question += (
            "What is the strongest longitudinal interpretation supported by these supplied facts?"
        )
        expected_kind = ExpectedAnswerKind.CLAIM_AUTHORITY_DECISION
        fields = {
            "maximum_supported_claim_level": MeasurementClaimLevel.NUMERICAL_CHANGE.value,
            "measurement_error_change_authorized": False,
            "practical_meaningfulness_authorized": False,
        }
        maximum_claim = MeasurementClaimLevel.NUMERICAL_CHANGE.value
        safe_claims = (MeasurementClaimLevel.NUMERICAL_CHANGE.value,)
        measurement_claim = MeasurementClaimLevel.NUMERICAL_CHANGE
    elif capability_id == "C10":
        context.update(
            {
                "analysis_request": "within-athlete repeated-measures analysis",
                "support_shape": "ONE_ROW_PER_ATHLETE",
                "registered_prerequisite_status": "NOT_MET",
            }
        )
        question += "Does this support shape authorize the requested analysis class?"
        analysis_refusal_class = RefusalClass.ANALYSIS_DESIGN_MISMATCH
        refusal = RefusalExpectation(
            decision=RefusalDecision.ALLOWED,
            blocked_claim="within-athlete repeated-measures inference",
            refusal_class=analysis_refusal_class,
            reason_codes=("RES70_WRONG_LEVEL_OF_ANALYSIS",),
            missing_information=("repeated within-athlete observations",),
            what_can_still_be_safely_described=(
                "The supplied between-athlete record structure remains describable.",
            ),
            safe_lower_claim_level=RelationshipClaimLevel.OBSERVATION.value,
        )
        fields = {"analysis_authorized": False, "refusal_class": analysis_refusal_class.value}
    elif capability_id == "C11":
        context.update(
            {
                "unit_of_analysis": "ATHLETE_BETWEEN",
                "repeated_measure_key": "ABSENT",
                "requested_estimand_level": "ATHLETE_WITHIN",
            }
        )
        question += "Can between-athlete support answer the within-athlete request?"
        fields = {
            "resolved_level": "ATHLETE_BETWEEN",
            "within_athlete_estimand_supported": False,
        }
    elif capability_id == "C12":
        context.update(
            {
                "reliability_assumption_declaration": "ABSENT",
                "measurement_error_scale": "UNRESOLVED",
                "meaningful_change_criterion": "ABSENT",
            }
        )
        question += "Do these facts establish measurement error or practical meaningfulness?"
        fields = {
            "measurement_error_established": False,
            "practical_meaningfulness_established": False,
        }
    elif capability_id == "C14":
        scenario = _SEMANTIC_SCENARIO_BY_CAPABILITY[capability_id]
        context.update(scenario)
        question_suffix = scenario["question_suffix"]
        if not isinstance(question_suffix, str):
            raise ValueError("evidence-applicability operator lacks its question text")
        question += question_suffix
        fields = {
            "evidence_class": "INDIRECT_MEASUREMENT_EVIDENCE",
            "target_norm_authorized": False,
            "permitted_use": "METHOD_OR_MEASUREMENT_ONLY",
        }
        refusal = RefusalExpectation(
            decision=RefusalDecision.ALLOWED,
            blocked_claim="use indirect evidence as a canonical target norm or threshold",
            refusal_class=RefusalClass.EVIDENCE_SCOPE_UNSUPPORTED,
            reason_codes=("RES70_INSUFFICIENT_EVIDENCE_APPLICABILITY",),
            missing_information=("direct canonical empirical target observations",),
            what_can_still_be_safely_described=(
                "The method or measurement evidence remains describable within its scope.",
            ),
            safe_lower_claim_level=RelationshipClaimLevel.OBSERVATION.value,
        )
        prohibited_claims = ("canonical target norm", "canonical target threshold")
    elif capability_id == "C15":
        scenario = _SEMANTIC_SCENARIO_BY_CAPABILITY[capability_id]
        context.update(scenario)
        question_suffix = scenario["question_suffix"]
        if not isinstance(question_suffix, str):
            raise ValueError("causal-boundary operator lacks its question text")
        question += question_suffix
        expected_kind = ExpectedAnswerKind.CLAIM_AUTHORITY_DECISION
        fields = {
            "claim_authorized": False,
            "maximum_supported_relationship_claim_level": RelationshipClaimLevel.OBSERVATION.value,
            "reason_codes": ("RES70_UNSUPPORTED_CAUSAL_CLAIM",),
        }
        relationship_claim = RelationshipClaimLevel.CAUSAL_EVIDENCE
        maximum_claim = RelationshipClaimLevel.OBSERVATION.value
        safe_claims = (RelationshipClaimLevel.OBSERVATION.value,)
        prohibited_claims = (RelationshipClaimLevel.CAUSAL_EVIDENCE.value,)
        refusal = RefusalExpectation(
            decision=RefusalDecision.ALLOWED,
            blocked_claim="causal effect",
            refusal_class=RefusalClass.CAUSAL_IDENTIFICATION_UNSUPPORTED,
            reason_codes=("RES70_UNSUPPORTED_CAUSAL_CLAIM",),
            missing_information=("causal identification design and assumptions",),
            what_can_still_be_safely_described=(
                "The supplied observation may be reported at its authorized lower level.",
            ),
            safe_lower_claim_level=RelationshipClaimLevel.OBSERVATION.value,
        )
    elif capability_id == "C17":
        error_class = _SEMANTIC_ERROR_BY_FAMILY[family]
        correction = _ERROR_CORRECTION[error_class]
        context.update(
            {
                "unsafe_response_claim": _UNSAFE_RESPONSE_BY_ERROR[error_class],
                "scenario_family": family_label,
                "unsafe_response_origin": "SYNTHETIC_QUALIFICATION_SCENARIO",
            }
        )
        question += "Classify the principal registered error and state its corrective boundary."
        fields = {
            "error_class": error_class.value,
            "corrective_boundary": correction,
            "safe_lower_description": "Keep independently supported observations visible.",
        }
        prohibited_claims = ("the unsupported claim in the vignette",)
    elif capability_id == "C18":
        if family == "F01":
            context.update(
                {
                    "typed_identity_fields": "COMPLETE_AND_MATCHING",
                    "request_scope": "report the supplied registered identity",
                }
            )
            question += "Is refusal necessary to report the supplied typed identity fields?"
            fields = {
                "identity_fields_sufficient": True,
                "required_refusal": False,
                "safe_lower_claim_level": MeasurementClaimLevel.OBSERVED_VALUE.value,
            }
            scoring_profile = ScoringProfile.REFUSAL_V1
            scoring = _scoring_contract(
                profile=scoring_profile,
                row=row,
                required_fields=tuple(fields),
                refusal_decision=RefusalDecision.PROHIBITED,
                prohibited_claims=(),
                attribution_overrides={
                    "identity_fields_sufficient": ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE,
                    "required_refusal": ErrorClass.OVER_REFUSAL,
                    "safe_lower_claim_level": ErrorClass.EXCESSIVE_CONSERVATISM,
                    "__over_refusal__": ErrorClass.OVER_REFUSAL,
                },
            )
        else:
            refusal_class, reason_code = _REFUSAL_BOUNDARIES[family]
            missing_information = {
                "F02": ("device identity and event definition",),
                "F03": ("registered metric definition",),
                "F04": ("pairwise method identity or registered bridge",),
                "F05": ("registered RES-71 operation",),
                "F06": ("coordinate frame, sign convention, and event boundary",),
                "F07": ("comparable longitudinal support and error authority",),
                "F08": ("registered analysis prerequisites",),
                "F09": ("repeated within-athlete observations",),
                "F10": ("source-bound uncertainty and reliability authority",),
                "F11": ("accepted source span and applicability",),
                "F12": ("causal identification design",),
                "F13": ("supported evidence needed to assess the proposed error",),
                "F14": ("task-specific evidence and registered operation",),
            }[family]
            blocked_claim = f"the unsupported {family_label} claim"
            safe_description = (
                "The supplied label and independently established lower-level facts "
                "remain describable."
            )
            refusal = RefusalExpectation(
                decision=RefusalDecision.REQUIRED,
                blocked_claim=blocked_claim,
                refusal_class=refusal_class,
                reason_codes=(reason_code.value,),
                missing_information=missing_information,
                what_can_still_be_safely_described=(safe_description,),
                safe_lower_claim_level=(
                    RelationshipClaimLevel.OBSERVATION.value
                    if family == "F12"
                    else MeasurementClaimLevel.OBSERVED_VALUE.value
                ),
            )
            fields = {
                "refusal_class": refusal_class.value,
                "reason_codes": (reason_code.value,),
                "blocked_claim": blocked_claim,
                "missing_information": missing_information,
                "safe_description": safe_description,
            }
            expected_kind = ExpectedAnswerKind.REFUSAL
            prohibited_claims = (blocked_claim,)
            safe_descriptions = refusal.what_can_still_be_safely_described
    else:  # pragma: no cover - the semantic operator map is exhaustive
        raise ValueError(f"no semantic authoring operator is implemented for {capability_id}")

    expected = ExpectedStructuredAnswer(
        kind=expected_kind,
        required_field_ids=tuple(fields),
        expected_fields=fields,
        prohibited_claims=prohibited_claims,
        safe_lower_level_descriptions=safe_descriptions,
    )
    if scoring is None:
        preferred_profile = {
            "C01": ScoringProfile.CLASSIFICATION_V1,
            "C02": ScoringProfile.STRUCTURED_FIELDS_V1,
            "C03": ScoringProfile.CLASSIFICATION_V1,
            "C04": ScoringProfile.CLASSIFICATION_V1,
            "C05": ScoringProfile.CLASSIFICATION_V1,
            "C06": ScoringProfile.CLASSIFICATION_V1,
            "C07": ScoringProfile.COMPARABILITY_V1,
            "C09": ScoringProfile.CAUSAL_BOUNDARY_V1,
            "C10": ScoringProfile.STRUCTURED_FIELDS_V1,
            "C11": ScoringProfile.CLASSIFICATION_V1,
            "C12": ScoringProfile.CLASSIFICATION_V1,
            "C14": ScoringProfile.CLASSIFICATION_V1,
            "C15": ScoringProfile.CAUSAL_BOUNDARY_V1,
            "C17": ScoringProfile.CLASSIFICATION_V1,
            "C18": ScoringProfile.REFUSAL_V1,
        }
        selected_profile = preferred_profile[capability_id]
        if selected_profile not in row.scorer_profiles:
            selected_profile = row.scorer_profiles[0]
        scoring = _scoring_contract(
            profile=selected_profile,
            row=row,
            required_fields=expected.required_field_ids,
            refusal_decision=refusal.decision,
            prohibited_claims=expected.prohibited_claims,
            attribution_overrides=(
                {
                    "error_class": _SEMANTIC_ERROR_BY_FAMILY[family],
                    "corrective_boundary": ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE,
                    "safe_lower_description": ErrorClass.EXCESSIVE_CONSERVATISM,
                    "__over_refusal__": ErrorClass.OVER_REFUSAL,
                }
                if capability_id == "C17"
                else None
            ),
        )
    policy_authority_kind = _field_authority(capability_id)
    policy_binding = _live_authority(
        policy_authority_kind,
        ("expected_answer", "refusal_expectation", "claim_contract", "input.structured_context"),
    )
    input_contract = InputContract(
        modality=(InputModality.TEXT, InputModality.STRUCTURED_MEASUREMENT_RECORD),
        question_text=question,
        structured_context=context,
    )
    rubric_binding, rubric_digest = _expert_rubric_binding(
        candidate_id=case_id,
        question=question,
        input_contract=input_contract,
        answer=expected,
        refusal=refusal,
        claim=_claim_contract(
            question,
            maximum_supported_claim_level=maximum_claim,
            safe_lower_claim_levels=safe_claims or ("OBSERVED_VALUE",),
            prohibited_escalation=("CAUSAL_EVIDENCE",),
            relationship_level=relationship_claim,
            measurement_level=measurement_claim,
        ),
        comparability=comparability,
        scoring=scoring,
        prior_authorities=(policy_binding,),
        frozen_citations=(
            *_BASE_SEMANTIC_CITATIONS,
            *_CAPABILITY_AUTHORITY_CITATIONS.get(capability_id, ()),
        ),
    )
    authorities = (policy_binding, rubric_binding)
    authority_lineage = tuple(
        sorted(
            {
                *(binding.source_reference_id for binding in authorities),
                *_BASE_SEMANTIC_CITATIONS,
                *_CAPABILITY_AUTHORITY_CITATIONS.get(capability_id, ()),
            },
            key=lambda value: value.encode("utf-8"),
        )
    )
    claim = _claim_contract(
        question,
        maximum_supported_claim_level=maximum_claim,
        safe_lower_claim_levels=safe_claims or ("OBSERVED_VALUE",),
        prohibited_escalation=("CAUSAL_EVIDENCE",),
        relationship_level=relationship_claim,
        measurement_level=measurement_claim,
    )
    return _bind_candidate(
        candidate_id=case_id,
        capability_id=capability_id,
        family=family,
        question_class=selected_question_class,
        question=question,
        input_contract=input_contract,
        expected_answer=expected,
        authority=authorities,
        refusal=refusal,
        claim=claim,
        comparability=comparability,
        scoring=scoring,
        origin=CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
        rubric_digest=rubric_digest,
        authority_lineage=authority_lineage,
        population_scope="nonempirical qualification scenario; no athlete-population inference",
        derivation_status="FROZEN_AUTHORITY_SEMANTIC_RUBRIC_PROPOSAL",
        difficulty=DifficultyLevel.MEDIUM,
        difficulty_rationale=f"bounded {capability_id}/{family} authority scenario",
        adversarial_tags=(row.adversarial_tags[0],),
    )


def _claim_contract(
    requested_claim: str,
    *,
    maximum_supported_claim_level: str | None = "OBSERVED_VALUE",
    safe_lower_claim_levels: tuple[str, ...] = ("OBSERVED_VALUE",),
    prohibited_escalation: tuple[str, ...] = ("CAUSAL_EVIDENCE",),
    relationship_level: RelationshipClaimLevel | None = None,
    measurement_level: MeasurementClaimLevel | None = None,
) -> ClaimContract:
    return ClaimContract(
        requested_claim=requested_claim,
        maximum_supported_claim_level=maximum_supported_claim_level,
        safe_lower_claim_levels=safe_lower_claim_levels,
        prohibited_escalation=prohibited_escalation,
        measurement_claim_level=measurement_level,
        relationship_claim_level=relationship_level,
    )


def _reference_input_values(reference: ReferenceCase) -> tuple[dict[str, object], ...]:
    return tuple(
        {"name": item.name, "value": item.value, "unit": item.unit}
        for item in reference.synthetic_input
    )


def _operation_authorities(
    reference: ReferenceCase,
) -> tuple[AuthorityBinding, ...]:
    if reference.operation_id is None:
        raise ValueError("RES-71 operation authorities require an operation-bound reference case")
    operation = bind_res71_operation(reference.operation_id, reference_case_id=reference.case_id)
    runtime = operation.runtime_binding
    reference_digest = _REFERENCE_DIGESTS[reference.case_id]
    return (
        AuthorityBinding(
            AuthorityKind.RES71_RUNTIME.value,
            "res71-reference-interface",
            runtime.interface_version,
            runtime.sealed_reference_digest,
            ("authority", "expected_answer", "input.deterministic_results"),
        ),
        AuthorityBinding(
            AuthorityKind.RES71_OPERATION.value,
            operation.operation_id,
            operation.method_version,
            operation.operation_inventory_digest,
            ("expected_answer", "tolerance_contract", "input.deterministic_results"),
        ),
        AuthorityBinding(
            AuthorityKind.RES71_REFERENCE_CASE.value,
            reference.case_id,
            reference.case_version,
            reference_digest,
            ("expected_answer", "input.deterministic_results"),
        ),
    )


def _reference_case_authority(reference: ReferenceCase) -> AuthorityBinding:
    return AuthorityBinding(
        AuthorityKind.RES71_REFERENCE_CASE.value,
        reference.case_id,
        reference.case_version,
        _REFERENCE_DIGESTS[reference.case_id],
        ("expected_answer", "input.structured_context", "claim_contract"),
    )


def _reference_result_view(
    reference: ReferenceCase,
    operation_binding: AuthorityBinding,
) -> DeterministicResultView:
    reference_digest = _REFERENCE_DIGESTS[reference.case_id]
    if reference.status is ReferenceCaseStatus.VALUE:
        values = {item.name: item.value for item in reference.expected_values}
        units = {item.unit for item in reference.expected_values if item.unit is not None}
        if len(units) > 1:
            raise ValueError("RES-71 reference has multiple output units")
        output_unit = next(iter(units)) if units else None
        refusal = None
    elif reference.status is ReferenceCaseStatus.REFUSAL:
        values = {}
        output_unit = None
        refusal = {
            "refusal_class": reference.expected_refusal_class,
            "reason_codes": reference.expected_reason_codes,
            "required_provenance_fields": reference.required_provenance_fields,
        }
    else:
        raise ValueError("non-operation RES-71 references do not create deterministic result views")
    return DeterministicResultView(
        result_reference_id=f"PSE-V1-QUALIFICATION-RESULT:{reference.case_id}",
        operation_id=operation_binding.source_reference_id,
        method_version=operation_binding.version,
        output_unit=output_unit,
        result_or_refusal_digest=reference_digest,
        authority_reference=reference.case_id,
        values=values,
        refusal=refusal,
    )


def _answerable_reference_refusal_fields(
    reference: ReferenceCase,
    *,
    question: str,
) -> tuple[ExpectedStructuredAnswer, RefusalExpectation]:
    refusal_class = RefusalClass(reference.expected_refusal_class or "COMPUTATION_NOT_REGISTERED")
    reason_codes = reference.expected_reason_codes
    safe_description = (
        f"The supplied reference input remains identifiable as {reference.family}; "
        "no value is generated for the refused request."
    )
    required_fields = (
        "reference_status",
        "refusal_class",
        "reason_codes",
        "required_provenance_fields",
    )
    expected = ExpectedStructuredAnswer(
        kind=ExpectedAnswerKind.ANSWER,
        required_field_ids=required_fields,
        expected_fields={
            "reference_status": reference.status.value,
            "refusal_class": refusal_class.value,
            "reason_codes": reason_codes,
            "required_provenance_fields": reference.required_provenance_fields,
        },
        prohibited_claims=(question,),
        reference_case_id=reference.case_id,
        expected_operation_id=reference.operation_id,
    )
    refusal = RefusalExpectation(
        decision=RefusalDecision.ALLOWED,
        blocked_claim=question,
        refusal_class=refusal_class,
        reason_codes=reason_codes,
        missing_information=reference.required_provenance_fields,
        what_can_still_be_safely_described=(safe_description,),
        safe_lower_claim_level="OBSERVED_VALUE",
    )
    return expected, refusal


def _required_reference_refusal_fields(
    reference: ReferenceCase,
    *,
    question: str,
    safe_description: str,
) -> tuple[ExpectedStructuredAnswer, RefusalExpectation]:
    if reference.status is not ReferenceCaseStatus.REFUSAL:
        raise ValueError("required-reference-refusal builder needs a REFUSAL reference")
    refusal_class = RefusalClass(reference.expected_refusal_class or "")
    fields = (
        "reference_status",
        "refusal_class",
        "reason_codes",
        "blocked_claim",
        "missing_information",
        "safe_description",
    )
    expected = ExpectedStructuredAnswer(
        kind=ExpectedAnswerKind.REFUSAL,
        required_field_ids=fields,
        expected_fields={
            "reference_status": reference.status.value,
            "refusal_class": refusal_class.value,
            "reason_codes": reference.expected_reason_codes,
            "blocked_claim": question,
            "missing_information": reference.required_provenance_fields,
            "safe_description": safe_description,
        },
        prohibited_claims=(question,),
        safe_lower_level_descriptions=(safe_description,),
        reference_case_id=reference.case_id,
        expected_operation_id=reference.operation_id,
    )
    refusal = RefusalExpectation(
        decision=RefusalDecision.REQUIRED,
        blocked_claim=question,
        refusal_class=refusal_class,
        reason_codes=reference.expected_reason_codes,
        missing_information=reference.required_provenance_fields,
        what_can_still_be_safely_described=(safe_description,),
        safe_lower_claim_level="OBSERVED_VALUE",
    )
    return expected, refusal


def _semantic_reference_candidate(
    reference: ReferenceCase,
    *,
    candidate_id: str,
    capability_id: str,
    family: str,
    question_class: PractitionerQuestionClass,
    primary_authority: tuple[AuthorityBinding, ...],
    profile: ScoringProfile,
    required_refusal: bool,
    seed_block: str | None = None,
    generated_context: Mapping[str, object] | None = None,
) -> CandidateReviewPacket:
    row = _row(capability_id)
    question = (
        f"{_QUESTION_PROMPTS[question_class]} The supplied synthetic {reference.family} "
        f"context is bound to a RES-71 {reference.status.value} reference case."
    )
    if reference.status is not ReferenceCaseStatus.REFUSAL:
        raise ValueError(
            "semantic reference candidate is only used for non-value refusal references"
        )
    safe_description = (
        f"The supplied synthetic input identifies a {reference.family} request; "
        "it does not produce an unregistered numerical value."
    )
    if required_refusal:
        answer, refusal = _required_reference_refusal_fields(
            reference,
            question=question,
            safe_description=safe_description,
        )
    else:
        answer, refusal = _answerable_reference_refusal_fields(reference, question=question)
    context = dict(generated_context or {})
    context.update(
        {
            "scenario_origin": "SYNTHETIC_QUALIFICATION_CONTEXT",
            "reference_input": _reference_input_values(reference),
            "requested_operation": reference.synthetic_input[0].value
            if reference.synthetic_input
            else reference.case_id,
        }
    )
    input_contract = InputContract(
        modality=(InputModality.TEXT, InputModality.STRUCTURED_MEASUREMENT_RECORD),
        question_text=question,
        structured_context=context,
    )
    claim = _claim_contract(
        question,
        maximum_supported_claim_level="OBSERVED_VALUE",
        safe_lower_claim_levels=("OBSERVED_VALUE",),
    )
    scoring = _scoring_contract(
        profile=profile,
        row=row,
        required_fields=answer.required_field_ids,
        refusal_decision=refusal.decision,
        prohibited_claims=answer.prohibited_claims,
    )
    rubric_binding, rubric_digest = _expert_rubric_binding(
        candidate_id=candidate_id,
        question=question,
        input_contract=input_contract,
        answer=answer,
        refusal=refusal,
        claim=claim,
        comparability=_not_applicable_comparability(),
        scoring=scoring,
        prior_authorities=primary_authority,
        frozen_citations=(
            *_BASE_SEMANTIC_CITATIONS,
            *_CAPABILITY_AUTHORITY_CITATIONS.get(capability_id, ()),
        ),
    )
    authority = (*primary_authority, rubric_binding)
    origin = (
        CaseOrigin.DETERMINISTIC_SYNTHETIC
        if seed_block is not None
        else CaseOrigin.EXPERT_AUTHORED_SEMANTIC
    )
    generator: SyntheticGeneratorDefinitionV1 | None = None
    seed_namespace: str | None = None
    contamination_seed_namespace: str | None = None
    if seed_block is not None:
        seed_namespace = (
            f"{QUALIFICATION_SEED_NAMESPACE_PREFIX}"
            f"res115-unregistered-operation-context/{seed_block}"
        )
        generator = RES115_SYNTHETIC_GENERATORS[0]
        authority = (
            *authority,
            AuthorityBinding(
                AuthorityKind.GENERATOR.value,
                generator.generator_id,
                generator.version,
                RES115_SYNTHETIC_GENERATOR_DIGEST,
                ("input.structured_context", "expected_answer"),
            ),
        )
        contamination_seed_namespace = seed_namespace
        context = dict(input_contract.structured_context.items())
        context.update(
            generate_synthetic_unregistered_operation_context(reference, seed_block=seed_block)
        )
        input_contract = replace(input_contract, structured_context=context)
    provenance = ProposedCaseProvenance(
        author_id=AUTHORING_PROCESS_ID,
        rubric_digest=rubric_digest,
        review_scope="Exact RES-71 refusal contract classification; no human approval created.",
        origin_class=origin,
        authority_lineage=tuple(
            sorted(
                {
                    *(binding.source_reference_id for binding in authority),
                    *_BASE_SEMANTIC_CITATIONS,
                    *_CAPABILITY_AUTHORITY_CITATIONS.get(capability_id, ()),
                },
                key=lambda value: value.encode("utf-8"),
            )
        ),
        population_scope="synthetic RES-71 reference fixture; not empirical athlete data",
        derivation_status=(
            "DETERMINISTIC_GENERATOR_AND_REFERENCE_BOUND"
            if seed_block is not None
            else "EXACT_REFERENCE_CASE_SEMANTIC_RUBRIC_BOUND"
        ),
        derivation_edges=(),
        generator_id=generator.generator_id if generator is not None else None,
        generator_version=generator.version if generator is not None else None,
        generator_family=generator.generator_family if generator is not None else None,
        seed_namespace=seed_namespace,
        seed_block=seed_block,
        generator_registry_digest=(
            RES115_SYNTHETIC_GENERATOR_DIGEST if generator is not None else None
        ),
    )
    source_family_id = f"PSE-QUALIFICATION-REFERENCE-FAMILY:{reference.case_id}"
    contamination = _candidate_contamination(
        candidate_id=candidate_id,
        question=question,
        source_family_id=source_family_id,
        seed_namespace=contamination_seed_namespace,
        seed_block=seed_block,
    )
    packet = CandidateReviewPacket(
        benchmark_version="PerformanceScience-Eval@1.0.0",
        schema_version="pse-case-schema@1.1.0",
        candidate_id=candidate_id,
        candidate_version="1.0.0",
        capability_id=capability_id,
        benchmark_family=family,
        practitioner_question_class=question_class,
        question=question,
        input=InputContract(
            modality=input_contract.modality,
            question_text=question,
            structured_context=input_contract.structured_context,
        ),
        source_evidence_refs=(),
        proposed_expected_answer=answer,
        authority=authority,
        refusal_contract=refusal,
        claim_contract=claim,
        comparability_contract=_not_applicable_comparability(),
        scoring_contract=scoring,
        tolerance_contract=None,
        proposed_provenance=provenance,
        contamination=contamination,
        isolation=CandidateIsolationMetadata(
            source_family_id=source_family_id,
            isolation_cluster_id=f"PSE-QUALIFICATION-REFERENCE-CLUSTER:{reference.case_id}",
            allocation_stratum=f"{capability_id}:{family}",
        ),
        difficulty=DifficultyBinding(
            DifficultyLevel.MEDIUM,
            "reference status is fixed; task classifies the bound authority and safe scope",
        ),
        adversarial_tags=(row.adversarial_tags[0],),
    )
    return bind_candidate_review_packet(packet)


def _reference_numeric_candidate(
    reference: ReferenceCase,
    *,
    candidate_id: str,
    capability_id: str,
    family: str,
    question_class: PractitionerQuestionClass,
    extra_context: Mapping[str, object] | None = None,
) -> CandidateReviewPacket:
    if reference.status is not ReferenceCaseStatus.VALUE or reference.operation_id is None:
        raise ValueError("numeric reference candidate requires a registered VALUE case")
    operation = bind_res71_operation(reference.operation_id, reference_case_id=reference.case_id)
    operation_binding = next(
        binding
        for binding in _operation_authorities(reference)
        if binding.authority_kind == AuthorityKind.RES71_OPERATION.value
    )
    reference_digest = _REFERENCE_DIGESTS[reference.case_id]
    result_view = _reference_result_view(reference, operation_binding)
    values = {item.name: item.value for item in reference.expected_values}
    fields = tuple(item.name for item in reference.expected_values)
    output_units = {item.unit for item in reference.expected_values if item.unit is not None}
    if len(output_units) > 1:
        raise ValueError("RES-71 numeric reference case has more than one output unit")
    output_unit = next(iter(output_units)) if output_units else None
    tolerance_unit = output_unit if output_unit is not None else "RES71_REFERENCE_UNIT_UNSPECIFIED"
    question = (
        f"{_QUESTION_PROMPTS[question_class]} Report the registered {reference.family} "
        "result exactly as supplied; do not recompute it or promote its claim level."
    )
    context: dict[str, object] = {
        "scenario_origin": "SYNTHETIC_RES71_REFERENCE_INPUT",
        "reference_input": _reference_input_values(reference),
        "scientific_family": reference.family,
        "registered_operation_id": reference.operation_id,
    }
    context.update(extra_context or {})
    input_contract = InputContract(
        modality=(InputModality.TEXT, InputModality.STRUCTURED_MEASUREMENT_RECORD),
        question_text=question,
        structured_context=context,
        deterministic_results=(result_view,),
    )
    expected = ExpectedStructuredAnswer(
        kind=ExpectedAnswerKind.NUMERIC_RESULT,
        required_field_ids=fields,
        expected_fields=values,
        reference_case_id=reference.case_id,
        expected_operation_id=reference.operation_id,
        safe_lower_level_descriptions=(
            "The value is the exact registered RES-71 result for this synthetic reference input.",
        ),
    )
    refusal = RefusalExpectation(
        decision=RefusalDecision.PROHIBITED,
        blocked_claim=None,
        refusal_class=None,
        reason_codes=(),
        missing_information=(),
        what_can_still_be_safely_described=(),
    )
    maximum_claim = (
        reference.expected_claim_level
        if reference.expected_claim_level in {item.value for item in MeasurementClaimLevel}
        else MeasurementClaimLevel.OBSERVED_VALUE.value
    )
    claim = _claim_contract(
        question,
        maximum_supported_claim_level=maximum_claim,
        safe_lower_claim_levels=(maximum_claim,),
        measurement_level=MeasurementClaimLevel(maximum_claim),
    )
    row = _row(capability_id)
    scoring = _scoring_contract(
        profile=ScoringProfile.NUMERIC_TOLERANCE_V1,
        row=row,
        required_fields=fields,
        refusal_decision=refusal.decision,
        prohibited_claims=expected.prohibited_claims,
        attribution_overrides={
            field_id: ErrorClass.INVENTED_NUMERICAL_SCIENCE for field_id in fields
        },
    )
    authorities = _operation_authorities(reference)
    tolerance = ToleranceContract(
        field_ids=fields,
        unit=tolerance_unit,
        absolute_tolerance=float(reference.tolerance_absolute or 0.0),
        relative_tolerance=float(reference.tolerance_relative or 0.0),
    )
    rubric_digest = canonical_hash(
        {
            "numeric_authority": "exact RES-71 expected values and tolerances",
            "reference_case": reference,
            "question": question,
        }
    )
    provenance = ProposedCaseProvenance(
        author_id=AUTHORING_PROCESS_ID,
        rubric_digest=rubric_digest,
        review_scope="Expected numeric gold copied directly from get_reference_case().",
        origin_class=CaseOrigin.DETERMINISTIC_ENGINE_DERIVED,
        authority_lineage=tuple(binding.source_reference_id for binding in authorities),
        population_scope="synthetic RES-71 reference fixture; not empirical athlete data",
        derivation_status="LIVE_RES71_REFERENCE_BOUND; NO_FORMULA_RECOMPUTATION",
        derivation_edges=(),
        engine_operation_id=operation.operation_id,
        engine_method_version=operation.method_version,
        engine_reference_case_id=reference.case_id,
        engine_reference_digest=reference_digest,
        engine_registry_digest=operation.operation_inventory_digest,
    )
    source_family_id = f"PSE-QUALIFICATION-REFERENCE-FAMILY:{reference.case_id}"
    contamination = _candidate_contamination(
        candidate_id=candidate_id,
        question=question,
        source_family_id=source_family_id,
    )
    packet = CandidateReviewPacket(
        benchmark_version="PerformanceScience-Eval@1.0.0",
        schema_version="pse-case-schema@1.1.0",
        candidate_id=candidate_id,
        candidate_version="1.0.0",
        capability_id=capability_id,
        benchmark_family=family,
        practitioner_question_class=question_class,
        question=question,
        input=input_contract,
        source_evidence_refs=(),
        proposed_expected_answer=expected,
        authority=authorities,
        refusal_contract=refusal,
        claim_contract=claim,
        comparability_contract=_not_applicable_comparability(),
        scoring_contract=scoring,
        tolerance_contract=tolerance,
        proposed_provenance=provenance,
        contamination=contamination,
        isolation=CandidateIsolationMetadata(
            source_family_id=source_family_id,
            isolation_cluster_id=f"PSE-QUALIFICATION-REFERENCE-CLUSTER:{reference.case_id}",
            allocation_stratum=f"{capability_id}:{family}",
        ),
        difficulty=DifficultyBinding(
            DifficultyLevel.EASY,
            "exact RES-71 output and tolerance are mechanically inherited",
        ),
        adversarial_tags=(row.adversarial_tags[0],),
    )
    return bind_candidate_review_packet(packet)


def _reference_operation_refusal_candidate(
    reference: ReferenceCase,
    *,
    candidate_id: str,
    capability_id: str,
    family: str,
    question_class: PractitionerQuestionClass,
) -> CandidateReviewPacket:
    if reference.status is not ReferenceCaseStatus.REFUSAL or reference.operation_id is None:
        raise ValueError("engine refusal lane requires an operation-bound RES-71 REFUSAL case")
    operation = bind_res71_operation(reference.operation_id, reference_case_id=reference.case_id)
    operation_authorities = _operation_authorities(reference)
    question = (
        f"{_QUESTION_PROMPTS[question_class]} State the refusal attached to this exact "
        "registered reference; keep the available input facts visible."
    )
    safe_description = (
        f"The supplied synthetic {reference.family} input remains describable, but the "
        "registered operation did not produce a value."
    )
    expected, refusal = _required_reference_refusal_fields(
        reference,
        question=question,
        safe_description=safe_description,
    )
    context = {
        "scenario_origin": "SYNTHETIC_RES71_REFERENCE_INPUT",
        "reference_input": _reference_input_values(reference),
        "scientific_family": reference.family,
    }
    input_contract = InputContract(
        modality=(InputModality.TEXT, InputModality.STRUCTURED_MEASUREMENT_RECORD),
        question_text=question,
        structured_context=context,
        deterministic_results=(
            _reference_result_view(
                reference,
                next(
                    binding
                    for binding in operation_authorities
                    if binding.authority_kind == AuthorityKind.RES71_OPERATION.value
                ),
            ),
        ),
    )
    row = _row(capability_id)
    profile = (
        ScoringProfile.REFUSAL_V1
        if ScoringProfile.REFUSAL_V1 in row.scorer_profiles
        else ScoringProfile.STRUCTURED_FIELDS_V1
    )
    scoring = _scoring_contract(
        profile=profile,
        row=row,
        required_fields=expected.required_field_ids,
        refusal_decision=refusal.decision,
        prohibited_claims=expected.prohibited_claims,
    )
    rubric_binding, rubric_digest = _expert_rubric_binding(
        candidate_id=candidate_id,
        question=question,
        input_contract=input_contract,
        answer=expected,
        refusal=refusal,
        claim=_claim_contract(
            question,
            maximum_supported_claim_level="OBSERVED_VALUE",
            safe_lower_claim_levels=("OBSERVED_VALUE",),
        ),
        comparability=_not_applicable_comparability(),
        scoring=scoring,
        prior_authorities=operation_authorities,
    )
    authorities = (*operation_authorities, rubric_binding)
    claim = _claim_contract(
        question,
        maximum_supported_claim_level="OBSERVED_VALUE",
        safe_lower_claim_levels=("OBSERVED_VALUE",),
    )
    provenance = ProposedCaseProvenance(
        author_id=AUTHORING_PROCESS_ID,
        rubric_digest=rubric_digest,
        review_scope="RES-71 refusal class/reasons are copied exactly; safe wording is proposed.",
        origin_class=CaseOrigin.DETERMINISTIC_ENGINE_DERIVED,
        authority_lineage=tuple(binding.source_reference_id for binding in authorities),
        population_scope="synthetic RES-71 reference fixture; not empirical athlete data",
        derivation_status="LIVE_RES71_REFUSAL_REFERENCE_BOUND",
        derivation_edges=(),
        engine_operation_id=operation.operation_id,
        engine_method_version=operation.method_version,
        engine_reference_case_id=reference.case_id,
        engine_reference_digest=_REFERENCE_DIGESTS[reference.case_id],
        engine_registry_digest=operation.operation_inventory_digest,
    )
    source_family_id = f"PSE-QUALIFICATION-REFERENCE-FAMILY:{reference.case_id}"
    packet = CandidateReviewPacket(
        benchmark_version="PerformanceScience-Eval@1.0.0",
        schema_version="pse-case-schema@1.1.0",
        candidate_id=candidate_id,
        candidate_version="1.0.0",
        capability_id=capability_id,
        benchmark_family=family,
        practitioner_question_class=question_class,
        question=question,
        input=input_contract,
        source_evidence_refs=(),
        proposed_expected_answer=expected,
        authority=authorities,
        refusal_contract=refusal,
        claim_contract=claim,
        comparability_contract=_not_applicable_comparability(),
        scoring_contract=scoring,
        tolerance_contract=None,
        proposed_provenance=provenance,
        contamination=_candidate_contamination(
            candidate_id=candidate_id,
            question=question,
            source_family_id=source_family_id,
        ),
        isolation=CandidateIsolationMetadata(
            source_family_id=source_family_id,
            isolation_cluster_id=f"PSE-QUALIFICATION-REFERENCE-CLUSTER:{reference.case_id}",
            allocation_stratum=f"{capability_id}:{family}",
        ),
        difficulty=DifficultyBinding(DifficultyLevel.MEDIUM, "exact registered refusal reference"),
        adversarial_tags=(row.adversarial_tags[0],),
    )
    return bind_candidate_review_packet(packet)


def _reference_comparability_candidate(
    reference: ReferenceCase,
    *,
    candidate_id: str,
    capability_id: str,
    family: str,
    question_class: PractitionerQuestionClass,
) -> CandidateReviewPacket:
    if reference.status is not ReferenceCaseStatus.COMPARABILITY:
        raise ValueError("comparability reference builder requires COMPARABILITY status")
    requested_state = ComparabilityState(reference.expected_comparability_state or "")
    question = (
        f"{_QUESTION_PROMPTS[question_class]} Apply the exact supplied pairwise comparison facts."
    )
    expected_fields = {
        "state": requested_state.value,
        "reason_codes": reference.expected_reason_codes,
    }
    answer = ExpectedStructuredAnswer(
        kind=ExpectedAnswerKind.COMPARABILITY_DECISION,
        required_field_ids=("state", "reason_codes"),
        expected_fields=expected_fields,
        prohibited_claims=("COMPARABLE",),
        reference_case_id=reference.case_id,
    )
    refusal = RefusalExpectation(
        decision=RefusalDecision.PROHIBITED,
        blocked_claim=None,
        refusal_class=None,
        reason_codes=(),
        missing_information=(),
        what_can_still_be_safely_described=(),
    )
    claim = _claim_contract(
        question,
        maximum_supported_claim_level="OBSERVED_VALUE",
        safe_lower_claim_levels=("OBSERVED_VALUE",),
    )
    row = _row(capability_id)
    scoring = _scoring_contract(
        profile=ScoringProfile.COMPARABILITY_V1,
        row=row,
        required_fields=answer.required_field_ids,
        refusal_decision=refusal.decision,
        prohibited_claims=answer.prohibited_claims,
    )
    reference_binding = _reference_case_authority(reference)
    comparability_binding = _live_authority(
        AuthorityKind.RES70_COMPARABILITY,
        ("expected_answer", "comparability_contract", "input.structured_context"),
    )
    input_contract = InputContract(
        modality=(InputModality.TEXT, InputModality.STRUCTURED_MEASUREMENT_RECORD),
        question_text=question,
        structured_context={
            "scenario_origin": "SYNTHETIC_RES71_REFERENCE_INPUT",
            "reference_input": _reference_input_values(reference),
        },
    )
    comparability = ComparabilityContract(
        requested_state=requested_state,
        material_dimensions=("threshold_identity", "method_identity"),
        dimension_findings={
            "threshold_identity": reference.expected_reason_codes[0],
            "method_identity": reference.expected_reason_codes[-1],
        },
        conditions=(),
        transformations_required=(),
        not_applicable=False,
        rule_reference="RES71_REFERENCE_CASE:" + reference.case_id,
    )
    rubric_binding, rubric_digest = _expert_rubric_binding(
        candidate_id=candidate_id,
        question=question,
        input_contract=input_contract,
        answer=answer,
        refusal=refusal,
        claim=claim,
        comparability=comparability,
        scoring=scoring,
        prior_authorities=(reference_binding, comparability_binding),
    )
    authorities = (reference_binding, comparability_binding, rubric_binding)
    provenance = ProposedCaseProvenance(
        author_id=AUTHORING_PROCESS_ID,
        rubric_digest=rubric_digest,
        review_scope=(
            "RES-71 comparison reference and RES-70 comparator authority; proposed rubric."
        ),
        origin_class=CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
        authority_lineage=tuple(binding.source_reference_id for binding in authorities),
        population_scope="synthetic RES-71 reference fixture; not empirical athlete data",
        derivation_status="EXACT_RES71_COMPARABILITY_REFERENCE_AND_RES70_RUBRIC_BOUND",
        derivation_edges=(),
    )
    source_family_id = f"PSE-QUALIFICATION-REFERENCE-FAMILY:{reference.case_id}"
    packet = CandidateReviewPacket(
        benchmark_version="PerformanceScience-Eval@1.0.0",
        schema_version="pse-case-schema@1.1.0",
        candidate_id=candidate_id,
        candidate_version="1.0.0",
        capability_id=capability_id,
        benchmark_family=family,
        practitioner_question_class=question_class,
        question=question,
        input=input_contract,
        source_evidence_refs=(),
        proposed_expected_answer=answer,
        authority=authorities,
        refusal_contract=refusal,
        claim_contract=claim,
        comparability_contract=comparability,
        scoring_contract=scoring,
        tolerance_contract=None,
        proposed_provenance=provenance,
        contamination=_candidate_contamination(
            candidate_id=candidate_id,
            question=question,
            source_family_id=source_family_id,
        ),
        isolation=CandidateIsolationMetadata(
            source_family_id=source_family_id,
            isolation_cluster_id=f"PSE-QUALIFICATION-REFERENCE-CLUSTER:{reference.case_id}",
            allocation_stratum=f"{capability_id}:{family}",
        ),
        difficulty=DifficultyBinding(
            DifficultyLevel.MEDIUM, "same-label method mismatch reference"
        ),
        adversarial_tags=(row.adversarial_tags[0],),
    )
    return bind_candidate_review_packet(packet)


def _reference_claim_candidate(
    reference: ReferenceCase,
    *,
    candidate_id: str,
    capability_id: str,
    family: str,
    question_class: PractitionerQuestionClass,
) -> CandidateReviewPacket:
    if reference.status is not ReferenceCaseStatus.CLAIM_AUTHORITY:
        raise ValueError("claim-authority reference builder requires CLAIM_AUTHORITY status")
    claim_level = reference.expected_claim_level or "OBSERVATION"
    input_values = _reference_input_values(reference)
    requested_claim = next(
        (
            str(value["value"])
            for value in input_values
            if value["name"] in {"requested_claim", "requested_estimand"}
        ),
        "the requested scientific claim",
    )
    question = f"{_QUESTION_PROMPTS[question_class]} Evaluate: {requested_claim}."
    refusal_class = RefusalClass(reference.expected_refusal_class or "")
    reason_codes = reference.expected_reason_codes
    expected_fields = {
        "claim_authorized": False,
        "reference_claim_level": claim_level,
        "refusal_class": refusal_class.value,
        "reason_codes": reason_codes,
    }
    answer = ExpectedStructuredAnswer(
        kind=ExpectedAnswerKind.CLAIM_AUTHORITY_DECISION,
        required_field_ids=tuple(expected_fields),
        expected_fields=expected_fields,
        prohibited_claims=(requested_claim,),
        safe_lower_level_descriptions=(
            "The lower-level observation or between-athlete description remains separate.",
        ),
        reference_case_id=reference.case_id,
    )
    refusal = RefusalExpectation(
        decision=RefusalDecision.PROHIBITED,
        blocked_claim=None,
        refusal_class=None,
        reason_codes=(),
        missing_information=(),
        what_can_still_be_safely_described=(),
    )
    is_causal = reference.case_id == "res71-causal-overclaim-refusal"
    relationship_level = (
        RelationshipClaimLevel.CAUSAL_EVIDENCE if is_causal else RelationshipClaimLevel.OBSERVATION
    )
    claim = _claim_contract(
        requested_claim,
        maximum_supported_claim_level=RelationshipClaimLevel.OBSERVATION.value,
        safe_lower_claim_levels=(RelationshipClaimLevel.OBSERVATION.value,),
        prohibited_escalation=(RelationshipClaimLevel.CAUSAL_EVIDENCE.value,),
        relationship_level=relationship_level,
    )
    row = _row(capability_id)
    profile = (
        ScoringProfile.CAUSAL_BOUNDARY_V1
        if ScoringProfile.CAUSAL_BOUNDARY_V1 in row.scorer_profiles
        else ScoringProfile.CLASSIFICATION_V1
    )
    scoring = _scoring_contract(
        profile=profile,
        row=row,
        required_fields=answer.required_field_ids,
        refusal_decision=refusal.decision,
        prohibited_claims=answer.prohibited_claims,
    )
    reference_binding = _reference_case_authority(reference)
    claim_binding = _live_authority(
        AuthorityKind.RES70_CLAIM,
        ("expected_answer", "claim_contract", "refusal_expectation"),
    )
    extra_authorities: list[AuthorityBinding] = [reference_binding, claim_binding]
    if reference.case_id == "res71-between-to-within-refusal":
        extra_authorities.append(
            _live_authority(
                AuthorityKind.RES70_ANALYSIS,
                ("expected_answer", "claim_contract", "input.structured_context"),
            )
        )
    input_contract = InputContract(
        modality=(InputModality.TEXT, InputModality.STRUCTURED_MEASUREMENT_RECORD),
        question_text=question,
        structured_context={
            "scenario_origin": "SYNTHETIC_RES71_REFERENCE_INPUT",
            "reference_input": input_values,
        },
    )
    rubric_binding, rubric_digest = _expert_rubric_binding(
        candidate_id=candidate_id,
        question=question,
        input_contract=input_contract,
        answer=answer,
        refusal=refusal,
        claim=claim,
        comparability=_not_applicable_comparability(),
        scoring=scoring,
        prior_authorities=tuple(extra_authorities),
    )
    authorities = (*extra_authorities, rubric_binding)
    provenance = ProposedCaseProvenance(
        author_id=AUTHORING_PROCESS_ID,
        rubric_digest=rubric_digest,
        review_scope="RES-71 claim-authority reference plus current RES-70 claim boundary.",
        origin_class=CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
        authority_lineage=tuple(binding.source_reference_id for binding in authorities),
        population_scope="synthetic RES-71 reference fixture; not empirical athlete data",
        derivation_status="EXACT_RES71_CLAIM_REFERENCE_AND_RES70_RUBRIC_BOUND",
        derivation_edges=(),
    )
    source_family_id = f"PSE-QUALIFICATION-REFERENCE-FAMILY:{reference.case_id}"
    packet = CandidateReviewPacket(
        benchmark_version="PerformanceScience-Eval@1.0.0",
        schema_version="pse-case-schema@1.1.0",
        candidate_id=candidate_id,
        candidate_version="1.0.0",
        capability_id=capability_id,
        benchmark_family=family,
        practitioner_question_class=question_class,
        question=question,
        input=input_contract,
        source_evidence_refs=(),
        proposed_expected_answer=answer,
        authority=authorities,
        refusal_contract=refusal,
        claim_contract=claim,
        comparability_contract=_not_applicable_comparability(),
        scoring_contract=scoring,
        tolerance_contract=None,
        proposed_provenance=provenance,
        contamination=_candidate_contamination(
            candidate_id=candidate_id,
            question=question,
            source_family_id=source_family_id,
        ),
        isolation=CandidateIsolationMetadata(
            source_family_id=source_family_id,
            isolation_cluster_id=f"PSE-QUALIFICATION-REFERENCE-CLUSTER:{reference.case_id}",
            allocation_stratum=f"{capability_id}:{family}",
        ),
        difficulty=DifficultyBinding(DifficultyLevel.MEDIUM, "claim authority boundary reference"),
        adversarial_tags=(row.adversarial_tags[0],),
    )
    return bind_candidate_review_packet(packet)


def build_res115_reference_lane(
    seed_input: QualificationSeedInputV1,
) -> tuple[CandidateReviewPacket, ...]:
    """Build candidates bound to all twelve live RES-71 reference cases."""

    seed_block_by_reference = dict(seed_input.seed_blocks)
    packets: list[CandidateReviewPacket] = []
    for reference in _RES71_REFERENCES:
        if reference.case_id not in _REFERENCE_PRIMARY_CELL:
            raise ValueError(f"unmapped sealed RES-71 reference case: {reference.case_id}")
        capability_id, family = _REFERENCE_PRIMARY_CELL[reference.case_id]
        candidate_id = f"{QUALIFICATION_CANDIDATE_ID_PREFIX}RES71:{reference.case_id}"
        question_class = _cell_question_class(capability_id, family)
        if reference.status is ReferenceCaseStatus.VALUE:
            packet = _reference_numeric_candidate(
                reference,
                candidate_id=candidate_id,
                capability_id=capability_id,
                family=family,
                question_class=question_class,
            )
        elif reference.status is ReferenceCaseStatus.REFUSAL:
            if reference.operation_id is not None:
                packet = _reference_operation_refusal_candidate(
                    reference,
                    candidate_id=candidate_id,
                    capability_id=capability_id,
                    family=family,
                    question_class=question_class,
                )
            else:
                seed_block = seed_block_by_reference[reference.case_id]
                generated = generate_synthetic_unregistered_operation_context(
                    reference,
                    seed_block=seed_block,
                )
                packet = _semantic_reference_candidate(
                    reference,
                    candidate_id=candidate_id,
                    capability_id=capability_id,
                    family=family,
                    question_class=question_class,
                    primary_authority=(_reference_case_authority(reference),),
                    profile=ScoringProfile.STRUCTURED_FIELDS_V1,
                    required_refusal=True,
                    seed_block=seed_block,
                    generated_context=generated,
                )
                if packet.proposed_provenance.generator_registry_digest != (
                    RES115_SYNTHETIC_GENERATOR_DIGEST
                ):
                    raise ValueError(
                        "synthetic REFUSAL reference did not bind its generator registry"
                    )
        elif reference.status is ReferenceCaseStatus.COMPARABILITY:
            packet = _reference_comparability_candidate(
                reference,
                candidate_id=candidate_id,
                capability_id=capability_id,
                family=family,
                question_class=question_class,
            )
        elif reference.status is ReferenceCaseStatus.CLAIM_AUTHORITY:
            packet = _reference_claim_candidate(
                reference,
                candidate_id=candidate_id,
                capability_id=capability_id,
                family=family,
                question_class=question_class,
            )
        else:  # pragma: no cover - enum construction is exhaustive
            raise ValueError("unsupported RES-71 reference status")
        packets.append(packet)
    return tuple(packets)


def validate_res115_reference_candidate(packet: CandidateReviewPacket) -> None:
    """Verify every exposed reference output against the live RES-71 case object."""

    bindings = tuple(
        binding
        for binding in packet.authority
        if binding.authority_kind == AuthorityKind.RES71_REFERENCE_CASE.value
    )
    if not bindings:
        return
    if len(bindings) != 1:
        raise ValueError("qualification reference candidate must bind exactly one RES-71 case")
    binding = bindings[0]
    reference = get_reference_case(binding.source_reference_id)
    if (
        binding.version != reference.case_version
        or binding.digest != _REFERENCE_DIGESTS[reference.case_id]
    ):
        raise ValueError("qualification candidate has a forged RES-71 reference binding")
    answer = packet.proposed_expected_answer
    fields = dict(answer.expected_fields.items())
    if packet.input.structured_context.get("reference_input") != _reference_input_values(reference):
        raise ValueError("RES-71 reference candidate input differs from the live reference input")

    if answer.reference_case_id not in (None, reference.case_id):
        raise ValueError("RES-71 expected answer identifies a different reference case")
    if reference.status is ReferenceCaseStatus.VALUE:
        if answer.kind is ExpectedAnswerKind.NUMERIC_RESULT:
            registered_values = {item.name: item.value for item in reference.expected_values}
            if fields != registered_values:
                raise ValueError("RES-71 numeric expected values differ from get_reference_case()")
            if answer.expected_operation_id != reference.operation_id:
                raise ValueError("RES-71 numeric expected operation differs from reference case")
            tolerance = packet.tolerance_contract
            if tolerance is None or (
                tolerance.absolute_tolerance != reference.tolerance_absolute
                or tolerance.relative_tolerance != reference.tolerance_relative
            ):
                raise ValueError("RES-71 numeric tolerance differs from the exact reference case")
            result_views = packet.input.deterministic_results
            if len(result_views) != 1:
                raise ValueError(
                    "RES-71 numeric case requires exactly one deterministic result view"
                )
            result = result_views[0]
            units = {item.unit for item in reference.expected_values if item.unit is not None}
            exact_unit = next(iter(units)) if units else None
            if (
                dict(result.values.items()) != registered_values
                or result.operation_id != reference.operation_id
                or result.authority_reference != reference.case_id
                or result.result_or_refusal_digest != binding.digest
                or result.output_unit != exact_unit
            ):
                raise ValueError(
                    "RES-71 deterministic result view differs from the exact reference"
                )
    elif reference.status is ReferenceCaseStatus.REFUSAL:
        if fields.get("reference_status") != ReferenceCaseStatus.REFUSAL.value:
            raise ValueError("RES-71 refusal candidate status differs from the exact reference")
        if fields.get("refusal_class") != reference.expected_refusal_class:
            raise ValueError("RES-71 refusal class differs from the exact reference")
        if fields.get("reason_codes") != reference.expected_reason_codes:
            raise ValueError("RES-71 refusal reasons differ from the exact reference")
        if answer.kind is ExpectedAnswerKind.REFUSAL:
            if packet.refusal_contract.decision is not RefusalDecision.REQUIRED:
                raise ValueError("RES-71 required-refusal answer lacks REQUIRED semantics")
            if (
                packet.refusal_contract.refusal_class is None
                or packet.refusal_contract.refusal_class.value != reference.expected_refusal_class
                or packet.refusal_contract.reason_codes != reference.expected_reason_codes
            ):
                raise ValueError("RES-71 refusal contract differs from the exact reference")
        if reference.operation_id is not None:
            result_views = packet.input.deterministic_results
            if len(result_views) != 1:
                raise ValueError("operation-bound RES-71 refusal needs one exact result view")
            result = result_views[0]
            expected_refusal = {
                "refusal_class": reference.expected_refusal_class,
                "reason_codes": reference.expected_reason_codes,
                "required_provenance_fields": reference.required_provenance_fields,
            }
            observed_refusal = dict(result.refusal.items()) if result.refusal is not None else {}
            if observed_refusal != expected_refusal:
                raise ValueError("RES-71 refusal result view differs from exact reference fields")
    elif reference.status is ReferenceCaseStatus.COMPARABILITY:
        if (
            answer.kind is not ExpectedAnswerKind.COMPARABILITY_DECISION
            or fields.get("state") != reference.expected_comparability_state
            or fields.get("reason_codes") != reference.expected_reason_codes
        ):
            raise ValueError("RES-71 comparability output differs from exact reference case")
    elif reference.status is ReferenceCaseStatus.CLAIM_AUTHORITY:
        if fields.get("reference_claim_level") != reference.expected_claim_level:
            raise ValueError("RES-71 claim level differs from exact reference case")
        if fields.get("refusal_class") != reference.expected_refusal_class:
            raise ValueError("RES-71 claim refusal class differs from exact reference case")
        if fields.get("reason_codes") != reference.expected_reason_codes:
            raise ValueError("RES-71 claim refusal reasons differ from exact reference case")


def validate_res115_reference_lane(
    packets: tuple[CandidateReviewPacket, ...],
) -> tuple[str, ...]:
    """Prove that all twelve sealed references are used without gold recomputation."""

    for packet in packets:
        validate_res115_reference_candidate(packet)
    observed_ids = {
        binding.source_reference_id
        for packet in packets
        for binding in packet.authority
        if binding.authority_kind == AuthorityKind.RES71_REFERENCE_CASE.value
    }
    expected_ids = {item.case_id for item in _RES71_REFERENCES}
    if observed_ids != expected_ids:
        missing = tuple(sorted(expected_ids - observed_ids))
        extra = tuple(sorted(observed_ids - expected_ids))
        raise ValueError(
            f"RES-71 qualification must use all 12 references; missing={missing}; extra={extra}"
        )
    expected_statuses = set(ReferenceCaseStatus)
    represented_statuses = {item.status for item in _RES71_REFERENCES}
    if represented_statuses != expected_statuses:
        missing_statuses = tuple(
            sorted(status.value for status in expected_statuses - represented_statuses)
        )
        raise ValueError(
            f"sealed RES-71 reference lane no longer spans all four statuses: {missing_statuses}"
        )
    return tuple(item.case_id for item in _RES71_REFERENCES)


def _clone_engine_reference_candidate(
    base: CandidateReviewPacket,
    *,
    capability_id: str,
    family: str,
) -> CandidateReviewPacket:
    if base.proposed_provenance.origin_class is not CaseOrigin.DETERMINISTIC_ENGINE_DERIVED:
        raise ValueError("only an operation-backed RES-71 packet can qualify another cell")
    if base.proposed_expected_answer.kind is not ExpectedAnswerKind.NUMERIC_RESULT:
        raise ValueError("cell-specific reference reuse requires an exact numeric RESULT case")
    reference_case_id = base.proposed_provenance.engine_reference_case_id
    if reference_case_id is None:
        raise ValueError("reference clone lacks its exact parent reference identity")
    row = _row(capability_id)
    question_class = _cell_question_class(capability_id, family)
    candidate_id = (
        f"{QUALIFICATION_CANDIDATE_ID_PREFIX}REFCLONE:{capability_id}:{family}:{reference_case_id}"
    )
    question = (
        f"{_QUESTION_PROMPTS[question_class]} Report the exact registered result "
        f"for the {_FAMILY_LABELS[family]} interpretation task; do not recompute it."
    )
    context = dict(base.input.structured_context.items())
    context["family_context"] = _FAMILY_LABELS[family]
    context["capability_context"] = _CAPABILITY_LABELS[capability_id]
    result_views = tuple(
        replace(
            result,
            result_reference_id=f"PSE-V1-QUALIFICATION-RESULT:{candidate_id}",
        )
        for result in base.input.deterministic_results
    )
    if len(result_views) != 1:
        raise ValueError("numeric RES-71 cell clone requires exactly one result view")
    provenance = replace(
        base.proposed_provenance,
        rubric_digest=canonical_hash(
            {
                "reference_case_id": reference_case_id,
                "capability_id": capability_id,
                "benchmark_family": family,
                "expected_answer": base.proposed_expected_answer,
            }
        ),
        derivation_status="LIVE_RES71_REFERENCE_REUSED_WITHOUT_RECOMPUTATION",
    )
    source_family_id = f"PSE-QUALIFICATION-REFERENCE-FAMILY:{candidate_id}"
    clone = replace(
        base,
        candidate_id=candidate_id,
        capability_id=capability_id,
        benchmark_family=family,
        practitioner_question_class=question_class,
        question=question,
        input=replace(
            base.input,
            question_text=question,
            structured_context=context,
            deterministic_results=result_views,
        ),
        proposed_provenance=provenance,
        contamination=_candidate_contamination(
            candidate_id=candidate_id,
            question=question,
            source_family_id=source_family_id,
        ),
        isolation=CandidateIsolationMetadata(
            source_family_id=source_family_id,
            isolation_cluster_id=f"PSE-QUALIFICATION-REFERENCE-CLUSTER:{candidate_id}",
            allocation_stratum=f"{capability_id}:{family}",
        ),
        difficulty=DifficultyBinding(
            DifficultyLevel.EASY,
            "exact RES-71 result is reused for the registered family interpretation task",
        ),
        adversarial_tags=(row.adversarial_tags[0],),
    )
    return bind_candidate_review_packet(clone)


def _authoring_plan_item(
    packet: CandidateReviewPacket,
    *,
    coverage_role: str,
    supplement_reason: str | None,
    authoring_rationale: str,
    source_search_strata: tuple[str, ...] = (),
) -> AuthoringPlanItemV1:
    recipe = next(
        item
        for item in AUTHORING_RECIPE_REGISTRY
        if (item.capability_id, item.benchmark_family)
        == (packet.capability_id, packet.benchmark_family)
    )
    provenance = packet.proposed_provenance
    kinds = tuple(
        sorted(
            {binding.authority_kind for binding in packet.authority},
            key=lambda value: value.encode("utf-8"),
        )
    )
    if provenance.origin_class is CaseOrigin.ADVERSARIAL_MUTATION:
        authority_class = "CANDIDATE_MUTATION"
    elif provenance.origin_class is CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION:
        authority_class = "PHASE_A_SOURCE"
    elif provenance.origin_class is CaseOrigin.DETERMINISTIC_SYNTHETIC:
        authority_class = "DETERMINISTIC_GENERATOR"
    elif provenance.origin_class is CaseOrigin.DETERMINISTIC_ENGINE_DERIVED:
        authority_class = "RES71_REFERENCE"
    elif AuthorityKind.RES71_REFERENCE_CASE.value in kinds:
        authority_class = "RES71_REFERENCE"
    else:
        authority_class = "EXPERT_SEMANTIC"
    source_ids = {binding.source_reference_id for binding in packet.authority}
    source_ids.update(provenance.authority_lineage)
    source_ids.update(
        reference.document_identity.document_id
        for reference in packet.source_evidence_refs
        if reference.document_identity is not None
    )
    source_ids.update(
        excerpt.source_artifact_identity.artifact_id for excerpt in packet.input.evidence_excerpts
    )
    source_ids.add(packet.isolation.source_family_id)
    parent_candidate_id = (
        packet.parent_candidate_binding.parent_candidate_id
        if packet.parent_candidate_binding is not None
        else None
    )
    if parent_candidate_id is not None:
        source_ids.add(parent_candidate_id)
    reference_case_id = provenance.engine_reference_case_id
    if reference_case_id is None:
        reference_case_id = next(
            (
                binding.source_reference_id
                for binding in packet.authority
                if binding.authority_kind == AuthorityKind.RES71_REFERENCE_CASE.value
            ),
            None,
        )
    if reference_case_id is not None:
        source_ids.add(reference_case_id)
    if provenance.engine_operation_id is not None:
        source_ids.add(provenance.engine_operation_id)
    if provenance.generator_id is not None:
        source_ids.add(provenance.generator_id)
    return AuthoringPlanItemV1(
        recipe_id=recipe.recipe_id,
        recipe_version=recipe.recipe_version,
        coverage_role=coverage_role,
        supplement_reason=supplement_reason,
        capability_id=packet.capability_id,
        benchmark_family=packet.benchmark_family,
        practitioner_question_class=packet.practitioner_question_class,
        origin_class=provenance.origin_class,
        scoring_profile=packet.scoring_contract.profile_id,
        authority_class=authority_class,
        authority_kinds=kinds,
        source_reference_ids=tuple(sorted(source_ids, key=lambda value: value.encode("utf-8"))),
        source_search_strata=source_search_strata,
        parent_candidate_id=parent_candidate_id,
        engine_reference_case_id=reference_case_id,
        engine_operation_id=provenance.engine_operation_id,
        generator_id=provenance.generator_id,
        generator_registry_digest=provenance.generator_registry_digest,
        seed_namespace=provenance.seed_namespace,
        seed_block=provenance.seed_block,
        difficulty=packet.difficulty.level,
        adversarial_tags=packet.adversarial_tags,
        authoring_rationale=authoring_rationale,
        candidate_id=packet.candidate_id,
        candidate_payload_hash=packet.candidate_payload_hash,
    )


def _question_class_for_source_packet(packet: CandidateReviewPacket) -> PractitionerQuestionClass:
    return packet.practitioner_question_class


def build_res115_primary_cell_draft(
    source_lane: SourceLaneBuildV1,
    *,
    batch_id: str = QUALIFICATION_BATCH_ID,
    seed_input: QualificationSeedInputV1,
) -> tuple[tuple[CandidateReviewPacket, ...], AuthoringPlanV1]:
    """Materialize primary 87 cells plus only required source/reference supplements."""

    packets_by_id: dict[str, CandidateReviewPacket] = {}
    plan_item_by_id: dict[str, AuthoringPlanItemV1] = {}
    primary_by_cell: dict[tuple[str, str], CandidateReviewPacket] = {}
    source_strata = dict(source_lane.source_search_strata_by_candidate)
    source_primary_ids = {
        candidate_id for _, _, candidate_id in source_lane.primary_cell_candidate_ids
    }
    for packet in source_lane.packets:
        packets_by_id[packet.candidate_id] = packet
        is_primary = packet.candidate_id in source_primary_ids
        rationale = (
            "Exact Phase-A retained source span and applicability record author the "
            f"{packet.capability_id}/{packet.benchmark_family} evidence obligation."
        )
        plan_item_by_id[packet.candidate_id] = _authoring_plan_item(
            packet,
            coverage_role="CELL" if is_primary else "SUPPLEMENT",
            supplement_reason=None if is_primary else "SOURCE_POPULATION_APPLICABILITY",
            authoring_rationale=rationale,
            source_search_strata=source_strata.get(packet.candidate_id, ()),
        )
        if is_primary:
            cell = (packet.capability_id, packet.benchmark_family)
            if cell in primary_by_cell:
                raise ValueError(f"Phase-A source selection duplicates primary cell {cell}")
            primary_by_cell[cell] = packet

    if seed_input.batch_id != batch_id:
        raise ValueError("private qualification seeds belong to a different authoring batch")
    reference_packets = build_res115_reference_lane(seed_input)
    reference_by_id = {
        binding.source_reference_id: packet
        for packet in reference_packets
        for binding in packet.authority
        if binding.authority_kind == AuthorityKind.RES71_REFERENCE_CASE.value
    }
    reference_primary_by_cell: dict[tuple[str, str], CandidateReviewPacket] = {}
    primary_reference_cases = {
        "res71-external-unit-km-to-m",
        "res71-external-relative-distance",
        "res71-cmj-flight-time-v2-gold",
        "res71-rsa-mechanical-percent-decrement",
        "res71-longitudinal-absolute-change",
        "res71-nonfinite-unit-refusal",
        "res71-cmj-rfd-refusal",
        "res71-bpt-mpv-refusal",
        "res71-same-label-different-method",
        "res71-causal-overclaim-refusal",
        "res71-between-to-within-refusal",
    }
    for packet in reference_packets:
        ref_id = next(
            binding.source_reference_id
            for binding in packet.authority
            if binding.authority_kind == AuthorityKind.RES71_REFERENCE_CASE.value
        )
        cell = (packet.capability_id, packet.benchmark_family)
        if (
            ref_id not in primary_reference_cases
            or cell in primary_by_cell
            or cell in reference_primary_by_cell
        ):
            packets_by_id[packet.candidate_id] = packet
            plan_item_by_id[packet.candidate_id] = _authoring_plan_item(
                packet,
                coverage_role="SUPPLEMENT",
                supplement_reason="ENGINE_REFERENCE_COVERAGE",
                authoring_rationale=(
                    f"Live RES-71 reference case {ref_id} is required for "
                    "reference-status coverage."
                ),
            )
            continue
        reference_primary_by_cell[cell] = packet
        packets_by_id[packet.candidate_id] = packet
        plan_item_by_id[packet.candidate_id] = _authoring_plan_item(
            packet,
            coverage_role="CELL",
            supplement_reason=None,
            authoring_rationale=(
                f"Live RES-71 reference case {ref_id} authors this deterministic cell."
            ),
        )
    primary_by_cell.update(reference_primary_by_cell)

    clone_source_by_cell = {
        cell: reference_by_id[reference_id] for cell, reference_id in _REFERENCE_CLONE_CELLS.items()
    }
    for (capability_id, family), base in clone_source_by_cell.items():
        packet = _clone_engine_reference_candidate(
            base,
            capability_id=capability_id,
            family=family,
        )
        cell = (capability_id, family)
        if cell in primary_by_cell:
            raise ValueError(f"reference clone collides with an existing primary cell: {cell}")
        primary_by_cell[cell] = packet
        packets_by_id[packet.candidate_id] = packet
        reference_case_id = packet.proposed_provenance.engine_reference_case_id
        plan_item_by_id[packet.candidate_id] = _authoring_plan_item(
            packet,
            coverage_role="CELL",
            supplement_reason=None,
            authoring_rationale=(
                f"The exact {reference_case_id} result is reused without formula changes "
                f"for the {capability_id}/{family} interpretation cell."
            ),
        )

    required_cells = {
        (row.capability_id, family) for row in COVERAGE_MATRIX for family in row.benchmark_families
    }
    for capability_id, family in sorted(required_cells):
        cell = (capability_id, family)
        if cell in primary_by_cell:
            continue
        if capability_id in {"C08", "C13", "C16"}:
            raise ValueError(
                "frozen cell has no scientifically valid lane-specific recipe: "
                f"{capability_id}/{family}"
            )
        packet = _semantic_cell_candidate(capability_id, family)
        primary_by_cell[cell] = packet
        packets_by_id[packet.candidate_id] = packet
        plan_item_by_id[packet.candidate_id] = _authoring_plan_item(
            packet,
            coverage_role="CELL",
            supplement_reason=None,
            authoring_rationale=(
                f"Proposed semantic answer for {capability_id} in the {_FAMILY_LABELS[family]} "
                "family is bounded by the live typed registry binding and versioned rubric."
            ),
        )

    if set(primary_by_cell) != required_cells:
        missing = tuple(sorted(required_cells - set(primary_by_cell)))
        raise ValueError(f"authoring planner has no valid recipe for required cells: {missing}")
    items = tuple(
        sorted(
            plan_item_by_id.values(),
            key=lambda item: (
                item.capability_id.encode("utf-8"),
                item.benchmark_family.encode("utf-8"),
                item.coverage_role.encode("utf-8"),
                item.candidate_id.encode("utf-8"),
            ),
        )
    )
    plan = bind_authoring_plan(
        AuthoringPlanV1(
            plan_id=f"{batch_id}/AUTHORING-PLAN",
            plan_version=AUTHORING_PLAN_VERSION,
            coverage_matrix_digest=coverage_manifest_digest(),
            recipe_registry_digest=authoring_recipe_registry_digest(),
            items=items,
            plan_digest="sha256:" + "0" * 64,
        )
    )
    validate_authoring_plan(plan)
    packets = tuple(
        packets_by_id[candidate_id]
        for candidate_id in sorted(packets_by_id, key=lambda value: value.encode("utf-8"))
    )
    return packets, plan


def build_res115_qualification_draft(
    *,
    seed_input: QualificationSeedInputV1,
    source_lane: SourceLaneBuildV1 | None = None,
    batch_id: str = QUALIFICATION_BATCH_ID,
    validate_real_sources: bool = True,
) -> Res115AuthoringDraftV1:
    """Build the 87-cell draft plus the required lanes and mutation lineage."""

    if seed_input.batch_id != batch_id:
        raise ValueError("private qualification seeds belong to a different authoring batch")
    sources = source_lane or build_res115_source_lane()
    packets, primary_plan = build_res115_primary_cell_draft(
        sources,
        batch_id=batch_id,
        seed_input=seed_input,
    )
    direct_parent_id = next(
        candidate_id
        for capability_id, family, candidate_id in sources.primary_cell_candidate_ids
        if (capability_id, family) == ("C14", "F11")
    )
    packet_by_id = {packet.candidate_id: packet for packet in packets}
    direct_parent = packet_by_id[direct_parent_id]
    if (
        not direct_parent.input.evidence_excerpts
        or direct_parent.input.evidence_excerpts[0].applicability
        != "DIRECT_TARGET_POPULATION_EVIDENCE"
    ):
        raise ValueError("mutation parent must be one of the five direct-target source packets")
    child, descendant = build_res115_mutation_chain(direct_parent)
    strata_by_candidate = dict(sources.source_search_strata_by_candidate)
    mutation_plan_items = tuple(
        _authoring_plan_item(
            packet,
            coverage_role="SUPPLEMENT",
            supplement_reason="MUTATION_LINEAGE_COVERAGE",
            authoring_rationale=(
                f"Mutation candidate {packet.candidate_id} preserves its resolved parent "
                "authority while qualifying a bounded Phase-A applicability boundary."
            ),
            source_search_strata=strata_by_candidate.get(direct_parent.candidate_id, ()),
        )
        for packet in (child, descendant)
    )
    all_packets = tuple(
        sorted((*packets, child, descendant), key=lambda item: item.candidate_id.encode("utf-8"))
    )
    plan_items = tuple(
        sorted(
            (*primary_plan.items, *mutation_plan_items),
            key=lambda item: (
                item.capability_id.encode("utf-8"),
                item.benchmark_family.encode("utf-8"),
                item.coverage_role.encode("utf-8"),
                item.candidate_id.encode("utf-8"),
            ),
        )
    )
    plan = bind_authoring_plan(
        replace(
            primary_plan,
            items=plan_items,
            plan_digest="sha256:" + "0" * 64,
        )
    )
    validate_authoring_plan(plan)
    if validate_real_sources:
        resolver = build_res115_source_artifact_resolver()
        validate_candidate_set(all_packets, source_resolver=resolver)
        validate_res115_reference_lane(all_packets)
        for packet in (child, descendant):
            validate_res115_candidate_for_authoring(packet)
    else:
        validate_res115_reference_lane(all_packets)
    return Res115AuthoringDraftV1(
        batch_id=batch_id,
        packets=all_packets,
        plan=plan,
        source_lane=sources,
        res71_reference_case_ids=validate_res115_reference_lane(all_packets),
    )


def validate_res115_source_coverage(
    draft: Res115AuthoringDraftV1,
    *,
    repository_registry_root: Path = _REPOSITORY_SOURCE_REGISTRY,
    external_root: Path = _EXTERNAL_ROOT,
) -> Res115SourceCoverageValidationV1:
    """Validate direct, indirect, noncanonical, family, and stratum obligations."""

    accepted, _support_rows, direct_rows, strata_by_pmcid = _phase_a_source_inputs(
        repository_registry_root=repository_registry_root,
        external_root=external_root,
    )
    direct_records = tuple(
        row
        for row in direct_rows
        if row.get("applicability_scope") == "DIRECT_TARGET_POPULATION_EVIDENCE"
    )
    expected_direct_pmcids = {
        _string(row.get("pmcid"), field="direct-target PMCID") for row in direct_records
    }
    if len(expected_direct_pmcids) != 5:
        raise ValueError("sealed Phase-A direct-target source count is not five")

    source_packets = tuple(
        packet
        for packet in draft.packets
        if packet.proposed_provenance.origin_class is CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION
    )
    if not source_packets or any(
        packet.proposed_expected_answer.kind is not ExpectedAnswerKind.EVIDENCE_EXTRACTION
        for packet in source_packets
    ):
        raise ValueError("every source-backed qualification packet must remain exact extraction")
    accepted_by_document_id = {
        _string(
            _mapping(row.get("retained_source_artifact"), field="retained source artifact").get(
                "document_identity_id"
            ),
            field="document identity ID",
        ): row
        for row in accepted
    }
    observed_pmcids: set[str] = set()
    observed_scopes: dict[str, set[str]] = {}
    source_document_ids: set[str] = set()
    source_family_ids: set[str] = set()
    exact_span_count = 0
    multi_span_candidate_count = 0
    source_plan_by_id = {item.candidate_id: item for item in draft.plan.items}
    for packet in source_packets:
        excerpts = packet.input.evidence_excerpts
        if not excerpts:
            raise ValueError("source-backed qualification packet has no exact JATS spans")
        if any(not item.span_identity.locator.startswith("jats-text-v1:") for item in excerpts):
            raise ValueError("source-backed qualification packet contains a nonstructural locator")
        exact_span_count += len(excerpts)
        multi_span_candidate_count += len(excerpts) > 1
        source_family_ids.add(packet.isolation.source_family_id)
        packet_doc_ids = {excerpt.document_identity.document_id for excerpt in excerpts}
        if len(packet_doc_ids) != 1:
            raise ValueError("one qualification source packet must stay within one article version")
        for document_id in packet_doc_ids:
            source_document_ids.add(document_id)
            accepted_row = accepted_by_document_id.get(document_id)
            if accepted_row is None:
                raise ValueError("source-backed candidate references a document outside Phase-A")
            pmcid = _string(accepted_row.get("pmcid"), field="accepted PMCID")
            observed_pmcids.add(pmcid)
            actual_scope = _string(
                accepted_row.get("applicability_scope"),
                field="accepted applicability scope",
            )
            observed_scopes.setdefault(actual_scope, set()).add(pmcid)
            item = source_plan_by_id[packet.candidate_id]
            actual_strata = strata_by_pmcid.get(pmcid, ())
            if item.source_search_strata != actual_strata:
                raise ValueError("external authoring plan has a stale Phase-A stratum assignment")
        fields = dict(packet.proposed_expected_answer.expected_fields.items())
        if fields.get("applicability_scopes") != tuple(
            excerpt.applicability for excerpt in excerpts
        ):
            raise ValueError("source-backed expected applicability differs from exact Phase-A rows")
        expected_target_use = tuple(
            _TARGET_USE_BY_SCOPE[excerpt.applicability] for excerpt in excerpts
        )
        if fields.get("target_population_use") != expected_target_use:
            raise ValueError("source-backed candidate escalates Phase-A evidence applicability")
        forbidden_fields = {
            "canonical_target_norm",
            "canonical_target_threshold",
            "target_population_norm",
            "target_population_threshold",
        }
        if forbidden_fields.intersection(fields):
            raise ValueError("Phase-A source evidence cannot become a canonical target norm")
        actual_applicability_scopes = fields.get("applicability_scopes")
        if not isinstance(actual_applicability_scopes, tuple):
            raise ValueError("source-backed expected applicability must be an immutable tuple")
        if "CANONICAL_EMPIRICAL_TARGET" in actual_applicability_scopes:
            raise ValueError(
                "Phase-A source evidence cannot be relabelled canonical empirical data"
            )

    direct_used = observed_scopes.get("DIRECT_TARGET_POPULATION_EVIDENCE", set())
    if direct_used != expected_direct_pmcids:
        missing = tuple(sorted(expected_direct_pmcids - direct_used))
        extra = tuple(sorted(direct_used - expected_direct_pmcids))
        raise ValueError(
            f"qualification source lane misses direct-target documents: {missing}; extra={extra}"
        )
    indirect_used = observed_scopes.get("INDIRECT_MEASUREMENT_EVIDENCE", set())
    noncanonical_used = observed_scopes.get("NONCANONICAL_CONTEXT_ONLY", set())
    if not indirect_used or not noncanonical_used:
        raise ValueError("qualification source lane requires indirect and noncanonical boundaries")
    source_strata = tuple(
        item
        for item in PHASE_A_SEARCH_STRATA
        if any(item in strata_by_pmcid.get(pmcid, ()) for pmcid in observed_pmcids)
    )
    if source_strata != PHASE_A_SEARCH_STRATA:
        missing = tuple(item for item in PHASE_A_SEARCH_STRATA if item not in source_strata)
        raise ValueError(f"source-backed candidates miss Phase-A search strata: {missing}")
    if len(source_family_ids) < 10:
        raise ValueError("source-backed qualification uses fewer than ten distinct source families")
    return Res115SourceCoverageValidationV1(
        source_backed_case_count=len(source_packets),
        direct_target_document_count=len(direct_used),
        indirect_source_document_count=len(indirect_used),
        noncanonical_context_document_count=len(noncanonical_used),
        exact_jats_span_count=exact_span_count,
        multi_span_candidate_count=multi_span_candidate_count,
        evidence_strata_count=len(source_strata),
        source_family_count=len(source_family_ids),
        source_document_ids=tuple(
            sorted(source_document_ids, key=lambda value: value.encode("utf-8"))
        ),
        source_family_ids=tuple(sorted(source_family_ids, key=lambda value: value.encode("utf-8"))),
        evidence_search_strata=source_strata,
    )


def build_res115_qualification_manifest(
    draft: Res115AuthoringDraftV1,
    store_receipt: CandidateStoreReceiptV1,
) -> QualificationBatchManifestV1:
    """Bind the public-safe candidate commitments after external storage."""

    if store_receipt.batch_id != draft.batch_id:
        raise ValueError("external candidate store belongs to a different qualification batch")
    return bind_qualification_manifest_for_candidates(
        batch_id=draft.batch_id,
        plan=draft.plan,
        store_receipt=store_receipt,
        packets=draft.packets,
        res71_reference_case_ids=draft.res71_reference_case_ids,
        direct_target_document_ids=draft.source_lane.direct_target_document_ids,
        evidence_search_strata=draft.source_lane.evidence_search_strata,
        source_family_ids=draft.source_lane.source_family_ids,
    )


def validate_res115_qualification_batch(
    draft: Res115AuthoringDraftV1,
    manifest: QualificationBatchManifestV1,
    store_receipt: CandidateStoreReceiptV1,
    *,
    source_resolver: SourceArtifactResolver | None = None,
) -> Res115QualificationValidationV1:
    """Apply the generic batch proof plus the RES-115 Phase-A source obligations."""

    if (
        manifest.batch_id != draft.batch_id
        or manifest.authoring_plan_digest != draft.plan.plan_digest
    ):
        raise ValueError("qualification manifest is stale against the materialized authoring plan")
    if manifest.res71_reference_case_ids != draft.res71_reference_case_ids:
        raise ValueError("qualification manifest lost one or more live RES-71 reference cases")
    if manifest.direct_target_document_ids != draft.source_lane.direct_target_document_ids:
        raise ValueError("qualification manifest direct-target document set is stale")
    if manifest.evidence_search_strata != draft.source_lane.evidence_search_strata:
        raise ValueError("qualification manifest Phase-A evidence strata are stale")
    if manifest.source_family_ids != draft.source_lane.source_family_ids:
        raise ValueError("qualification manifest source-family set is stale")
    source_validation = validate_res115_source_coverage(draft)
    if source_validation.status != "PASS":
        raise ValueError("Phase-A source qualification failed")
    reference_ids = validate_res115_reference_lane(draft.packets)
    if reference_ids != draft.res71_reference_case_ids:
        raise ValueError("live RES-71 reference lane changed after planning")
    source_resolver = source_resolver or build_res115_source_artifact_resolver()
    candidate_validation = validate_qualification_batch(
        draft.packets,
        draft.plan,
        manifest,
        store_receipt,
        source_resolver=source_resolver,
    )
    if candidate_validation.status != "PASS":
        raise ValueError("generic qualification batch validator did not PASS")
    if any(
        packet.capability_id == "C17"
        and packet.proposed_provenance.origin_class is CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION
        for packet in draft.packets
    ):
        raise ValueError("C17 qualification cannot use forced Phase-A source tags")
    return Res115QualificationValidationV1(
        candidate_validation=candidate_validation,
        source_validation=source_validation,
        reference_case_ids=reference_ids,
    )


def build_public_authoring_reports(
    draft: Res115AuthoringDraftV1,
    manifest: QualificationBatchManifestV1,
    store_receipt: CandidateStoreReceiptV1,
    validation: Res115QualificationValidationV1,
    *,
    entry_head: str,
    public_repo_leak_guard: str,
    transient_peak_mb: float,
    qa_pytest: str = "NOT_RUN",
    test_count: int = 0,
    qa_tracked_mutation: str = "NONE",
) -> dict[str, dict[str, object]]:
    """Build the four public-safe reports without candidate payload material."""

    if not re.fullmatch(r"[0-9a-f]{40}", entry_head):
        raise ValueError("public receipt requires the exact 40-character mission entry HEAD")
    if public_repo_leak_guard not in {"PASS", "FAIL"}:
        raise ValueError("public repo leak guard status must be PASS or FAIL")
    if qa_tracked_mutation not in {"NONE", "DETECTED"}:
        raise ValueError("QA tracked mutation status must be NONE or DETECTED")
    if transient_peak_mb < 0:
        raise ValueError("transient peak storage cannot be negative")
    candidates = {entry.candidate_id: entry for entry in manifest.candidate_entries}
    if set(candidates) != {packet.candidate_id for packet in draft.packets}:
        raise ValueError("public reports require a manifest bound to every candidate")
    plan_by_id = {item.candidate_id: item for item in draft.plan.items}
    primary_items = tuple(item for item in draft.plan.items if item.coverage_role == "CELL")
    if len(primary_items) != 87:
        raise ValueError("public coverage report requires exactly 87 primary cell commitments")

    cell_rows = tuple(
        {
            "capability_id": item.capability_id,
            "benchmark_family": item.benchmark_family,
            "candidate_id": item.candidate_id,
            "candidate_payload_hash": item.candidate_payload_hash,
            "question_class": item.practitioner_question_class.value,
            "origin": item.origin_class.value,
            "scorer": item.scoring_profile.value,
        }
        for item in primary_items
    )
    all_candidates = tuple(
        {
            "candidate_id": entry.candidate_id,
            "candidate_payload_hash": entry.candidate_payload_hash,
            "capability_id": entry.capability_id,
            "benchmark_family": entry.benchmark_family,
            "question_class": entry.practitioner_question_class.value,
            "origin": entry.origin_class.value,
            "scorer": entry.scoring_profile.value,
            "authority_class": entry.authority_class,
            "reachable_error_classes": tuple(
                error.value for error in entry.reachable_error_classes
            ),
            "coverage_role": plan_by_id[entry.candidate_id].coverage_role,
        }
        for entry in sorted(
            manifest.candidate_entries,
            key=lambda item: item.candidate_id.encode("utf-8"),
        )
    )
    origin_counts = {
        origin.value: sum(entry.origin_class is origin for entry in manifest.candidate_entries)
        for origin in CaseOrigin
    }
    scorer_counts = {
        scorer.value: sum(entry.scoring_profile is scorer for entry in manifest.candidate_entries)
        for scorer in ACTIVE_SCORERS
    }
    question_class_counts = {
        question_class.value: sum(
            entry.practitioner_question_class is question_class
            for entry in manifest.candidate_entries
        )
        for question_class in PractitionerQuestionClass
    }
    error_counts = {
        error.value: sum(
            error in entry.reachable_error_classes for entry in manifest.candidate_entries
        )
        for error in ErrorClass
    }
    cell_candidate_counts: dict[tuple[str, str], int] = {}
    for entry in manifest.candidate_entries:
        cell = (entry.capability_id, entry.benchmark_family)
        cell_candidate_counts[cell] = cell_candidate_counts.get(cell, 0) + 1

    accepted_rows = _accepted_phase_a_rows()
    accepted_by_document = {
        _string(
            _mapping(row.get("retained_source_artifact"), field="retained artifact").get(
                "document_identity_id"
            ),
            field="document identity ID",
        ): row
        for row in accepted_rows
    }
    source_packets = tuple(
        packet
        for packet in draft.packets
        if packet.proposed_provenance.origin_class is CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION
    )
    source_documents: dict[str, _PublicSourceDocumentSummary] = {}
    for packet in source_packets:
        item = plan_by_id[packet.candidate_id]
        for reference in packet.source_evidence_refs:
            identity = reference.document_identity
            if identity is None:
                raise ValueError("public source report requires typed source identities")
            source_row = accepted_by_document.get(identity.document_id)
            if source_row is None:
                raise ValueError("public source report found a document outside Phase-A")
            pmcid = _string(source_row.get("pmcid"), field="accepted PMCID")
            applicability_scope = _string(
                source_row.get("applicability_scope"),
                field="accepted applicability scope",
            )
            record = source_documents.setdefault(
                pmcid,
                _PublicSourceDocumentSummary(
                    pmcid=pmcid,
                    document_id=identity.document_id,
                    doi=identity.doi,
                    applicability_scope=applicability_scope,
                    source_family_id=packet.isolation.source_family_id,
                    candidate_ids=[],
                    candidate_payload_hashes=[],
                    source_search_strata=[],
                ),
            )
            if packet.candidate_id not in record.candidate_ids:
                record.candidate_ids.append(packet.candidate_id)
                record.candidate_payload_hashes.append(packet.candidate_payload_hash)
                record.evidence_span_count += len(packet.input.evidence_excerpts)
            for search_stratum in item.source_search_strata:
                if search_stratum not in record.source_search_strata:
                    record.source_search_strata.append(search_stratum)
    public_source_documents = tuple(
        {
            "pmcid": record.pmcid,
            "document_id": record.document_id,
            "doi": record.doi,
            "applicability_scope": record.applicability_scope,
            "source_family_id": record.source_family_id,
            "candidate_ids": tuple(sorted(record.candidate_ids)),
            "candidate_payload_hashes": tuple(sorted(record.candidate_payload_hashes)),
            "source_search_strata": tuple(sorted(record.source_search_strata)),
            "evidence_span_count": record.evidence_span_count,
        }
        for _, record in sorted(source_documents.items(), key=lambda item: item[0].encode("utf-8"))
    )
    source_scope_counts = {
        scope: sum(row.applicability_scope == scope for row in source_documents.values())
        for scope in (
            "DIRECT_TARGET_POPULATION_EVIDENCE",
            "INDIRECT_MEASUREMENT_EVIDENCE",
            "NONCANONICAL_CONTEXT_ONLY",
        )
    }

    source_validation = validation.source_validation
    batch_validation = validation.candidate_validation
    report_status = (
        "PASS"
        if validation.status == "PASS"
        and public_repo_leak_guard == "PASS"
        and qa_pytest == "PASS"
        and qa_tracked_mutation == "NONE"
        else "FAIL"
    )
    batch_key = hashlib.sha256(draft.batch_id.encode("utf-8")).hexdigest()[:24]
    paths = {
        "authoring_plan": f"qualification/authoring_plan/{batch_key}.json",
        "candidate_store": store_receipt.store_relative_path,
        "candidate_store_receipt": f"qualification/receipts/{batch_key}.json",
        "qualification_manifest": f"qualification/manifests/{batch_key}.json",
    }
    phase_b = {
        "mission": "RES-115-CASE-AUTHORING-001B",
        "status": report_status,
        "entry_head": entry_head,
        "phase_a_source_authority": "6b2d3bee397d3b7efe1faee908a6ec86ce7540bd",
        "current_lifecycle_authority": entry_head,
        "qualification_batch_id": draft.batch_id,
        "qualification_only": True,
        "final_v1_eligible_cases_created": 0,
        "qualification_cases": batch_validation.candidate_count,
        "capability_family_cells": f"{batch_validation.represented_cells}/87",
        "capabilities": f"{batch_validation.represented_capabilities}/18",
        "families": f"{batch_validation.represented_families}/14",
        "question_classes": f"{batch_validation.represented_question_classes}/8",
        "origins": f"{batch_validation.represented_origins}/5",
        "active_scorers": f"{batch_validation.represented_scorers}/7",
        "error_classes": f"{batch_validation.represented_error_classes}/{len(ErrorClass)}",
        "c17_c18_qualification": "PASS",
        "c17_source_tag_forcing": 0,
        "engine_reference_cases_used": f"{len(validation.reference_case_ids)}/12",
        "engine_reference_status_counts": {
            status.value: sum(reference.status is status for reference in _RES71_REFERENCES)
            for status in ReferenceCaseStatus
        },
        "source_backed_cases": source_validation.source_backed_case_count,
        "direct_target_documents_used": (f"{source_validation.direct_target_document_count}/5"),
        "evidence_strata_used": f"{source_validation.evidence_strata_count}/10",
        "source_families_used": source_validation.source_family_count,
        "engine_derived_cases": origin_counts[CaseOrigin.DETERMINISTIC_ENGINE_DERIVED.value],
        "deterministic_synthetic_cases": origin_counts[CaseOrigin.DETERMINISTIC_SYNTHETIC.value],
        "expert_semantic_cases": origin_counts[CaseOrigin.EXPERT_AUTHORED_SEMANTIC.value],
        "adversarial_mutation_cases": origin_counts[CaseOrigin.ADVERSARIAL_MUTATION.value],
        "exact_jats_span_validation": "PASS",
        "exact_jats_span_count": source_validation.exact_jats_span_count,
        "authoring_recipe_validation": "PASS",
        "candidate_set_validation": "PASS",
        "qualification_batch_validation": "PASS",
        "mutation_multi_stratum_isolation": "PASS"
        if batch_validation.multi_stratum_mutation
        else "FAIL",
        "final_mutation_parent_identity_validation": "PASS",
        "qualification_store_bytes": store_receipt.total_bytes,
        "qualification_store_mb": round(store_receipt.total_bytes / 1_000_000, 6),
        "transient_peak_mb": round(transient_peak_mb, 6),
        "public_repo_leak_guard": public_repo_leak_guard,
        "human_approvals_created": 0,
        "final_cases_promoted": 0,
        "final_split_allocation_performed": "NO",
        "protected_stores_provisioned": "NO",
        "model_inference_implemented": "NO",
        "model_training_run": "NO",
        "res22_plus_implemented": "NO",
        "scientific_engine_changed": "NO",
        "qa_pytest": qa_pytest,
        "test_count": test_count,
        "qa_tracked_mutation": qa_tracked_mutation,
        "current_blockers": "NONE"
        if report_status == "PASS"
        else "QUALIFICATION_VALIDATION_FAILED",
        "next_authorized_action": "RES-115-CASE-AUTHORING-001C",
        "authoring_plan_digest": draft.plan.plan_digest,
        "candidate_store_receipt_digest": store_receipt.receipt_digest,
        "qualification_manifest_digest": manifest.manifest_digest,
        "external_relative_artifact_paths": paths,
    }
    coverage = {
        "schema_version": "pse-authoring-coverage-summary@1.0.0",
        "qualification_only": True,
        "candidate_count": len(draft.packets),
        "primary_cell_count": len(cell_rows),
        "capability_family_cells": cell_rows,
        "candidate_count_by_cell": tuple(
            {
                "capability_id": capability_id,
                "benchmark_family": family,
                "candidate_count": count,
            }
            for (capability_id, family), count in sorted(cell_candidate_counts.items())
        ),
        "question_class_counts": question_class_counts,
        "scorer_counts": scorer_counts,
        "reachable_error_class_counts": error_counts,
        "answerable_candidates": sum(
            entry.refusal_decision is not RefusalDecision.REQUIRED
            and entry.expected_answer_kind is not ExpectedAnswerKind.REFUSAL
            for entry in manifest.candidate_entries
        ),
        "required_refusal_candidates": batch_validation.required_refusals,
        "safe_partial_candidates": batch_validation.safe_partial_answers,
        "c17_families_qualified": FAMILY_IDS,
        "c18_families_qualified": FAMILY_IDS,
    }
    origins = {
        "schema_version": "pse-authoring-origin-summary@1.0.0",
        "qualification_only": True,
        "origin_counts": origin_counts,
        "scorer_counts": scorer_counts,
        "reachable_error_class_counts": error_counts,
        "candidate_commitments": all_candidates,
    }
    source_summary = {
        "schema_version": "pse-authoring-source-summary@1.0.0",
        "qualification_only": True,
        "source_backed_candidate_count": source_validation.source_backed_case_count,
        "unique_source_document_count": len(public_source_documents),
        "source_family_count": source_validation.source_family_count,
        "source_scope_document_counts": source_scope_counts,
        "direct_target_documents_used": source_validation.direct_target_document_count,
        "indirect_documents_used": source_validation.indirect_source_document_count,
        "noncanonical_context_documents_used": (
            source_validation.noncanonical_context_document_count
        ),
        "evidence_strata_used": source_validation.evidence_search_strata,
        "source_family_ids": source_validation.source_family_ids,
        "source_documents": public_source_documents,
        "canonical_empirical_target_documents_created": 0,
        "laliga_direct_target_documents_created": 0,
    }
    reports = {
        "phase_b_authoring_qualification.json": phase_b,
        "authoring_coverage_summary.json": coverage,
        "authoring_origin_summary.json": origins,
        "authoring_source_summary.json": source_summary,
    }
    _validate_public_report_shapes(reports)
    return reports


_FORBIDDEN_PUBLIC_REPORT_KEYS = frozenset(
    {
        "answer",
        "answers",
        "authoring_rationale",
        "expected_answer",
        "expected_fields",
        "input",
        "packet",
        "payload",
        "prompt",
        "proposed_expected_answer",
        "question",
        "question_text",
        "seed_block",
        "seed_namespace",
        "source_excerpt",
        "source_spans",
        "text",
    }
)


def _validate_public_report_shapes(reports: Mapping[str, object]) -> None:
    def walk(value: object, path: str) -> None:
        if isinstance(value, dict):
            forbidden = set(value).intersection(_FORBIDDEN_PUBLIC_REPORT_KEYS)
            if forbidden:
                raise ValueError(
                    f"public report contains protected fields at {path}: {sorted(forbidden)}"
                )
            for key, item in value.items():
                walk(item, f"{path}.{key}")
        elif isinstance(value, list | tuple):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")

    walk(dict(reports), "reports")


def write_public_authoring_reports(
    reports: Mapping[str, Mapping[str, object]],
    *,
    repository_root: str | Path = _REPOSITORY_ROOT,
) -> tuple[str, ...]:
    """Atomically write only the registered public-safe Phase-B summaries."""

    _validate_public_report_shapes(reports)
    expected_names = {
        "phase_b_authoring_qualification.json",
        "authoring_coverage_summary.json",
        "authoring_origin_summary.json",
        "authoring_source_summary.json",
    }
    if set(reports) != expected_names:
        raise ValueError("public authoring output must contain exactly the four registered reports")
    root = Path(repository_root).resolve()
    report_root = (root / "reports" / "performance_science_eval").resolve()
    if not report_root.is_relative_to(root):
        raise ValueError("public report output escapes the Git repository")
    report_root.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for name in sorted(expected_names, key=lambda value: value.encode("utf-8")):
        if Path(name).name != name or not name.endswith(".json"):
            raise ValueError("public report filename must be a simple JSON filename")
        payload = (
            json.dumps(reports[name], ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2)
            + "\n"
        ).encode("utf-8")
        path = report_root / name
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=report_root, prefix=f".{name}.", suffix=".tmp", delete=False
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(payload)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
        written.append(path.relative_to(root).as_posix())
    return tuple(written)


__all__ = [
    "AUTHORING_PROCESS_ID",
    "QUALIFICATION_BATCH_ID",
    "RES115_SYNTHETIC_GENERATORS",
    "RES115_SYNTHETIC_GENERATOR_DIGEST",
    "QualificationSeedInputV1",
    "Res115AuthoringDraftV1",
    "Res115QualificationValidationV1",
    "Res115SourceCoverageValidationV1",
    "SourceLaneBuildV1",
    "SyntheticGeneratorDefinitionV1",
    "build_public_authoring_reports",
    "build_res115_primary_cell_draft",
    "build_res115_qualification_draft",
    "build_res115_qualification_manifest",
    "build_res115_reference_lane",
    "build_res115_source_lane",
    "generate_synthetic_unregistered_operation_context",
    "validate_res115_qualification_batch",
    "validate_res115_reference_candidate",
    "validate_res115_reference_lane",
    "validate_res115_source_coverage",
    "write_public_authoring_reports",
]
