"""Generic, fail-closed authoring plans and qualification batch contracts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, fields, replace

from dynamislm.benchmark.constants import (
    CAPABILITY_IDS,
    FAMILY_IDS,
    CaseOrigin,
    DifficultyLevel,
    ErrorClass,
    ExpectedAnswerKind,
    PractitionerQuestionClass,
    RefusalDecision,
    ScoringProfile,
)
from dynamislm.benchmark.coverage import (
    COVERAGE_MATRIX,
    CoverageRow,
    coverage_manifest_digest,
    coverage_obligation_count,
    validate_coverage_matrix,
)
from dynamislm.benchmark.pre_review import (
    CandidateReviewPacket,
    topological_candidate_promotion_order,
    validate_candidate_set,
)
from dynamislm.benchmark.scoring_paths import reachable_error_classes
from dynamislm.benchmark.source_artifacts import SourceArtifactResolver
from dynamislm.serialization import canonical_hash, register_serializable_type

QUALIFICATION_CANDIDATE_ID_PREFIX = "PSE-V1-QUALIFICATION:"
QUALIFICATION_SEED_NAMESPACE_PREFIX = "PSE-V1-QUALIFICATION/"
QUALIFICATION_MANIFEST_VERSION = "pse-qualification-batch@1.0.0"
AUTHORING_PLAN_VERSION = "pse-authoring-plan@1.0.0"
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SEED_BLOCK = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}\Z")

ACTIVE_SCORERS = (
    ScoringProfile.NUMERIC_TOLERANCE_V1,
    ScoringProfile.CLASSIFICATION_V1,
    ScoringProfile.STRUCTURED_FIELDS_V1,
    ScoringProfile.EVIDENCE_SPAN_V1,
    ScoringProfile.COMPARABILITY_V1,
    ScoringProfile.REFUSAL_V1,
    ScoringProfile.CAUSAL_BOUNDARY_V1,
)

_QUESTION_CLASS_SCOPE: dict[PractitionerQuestionClass, tuple[tuple[str, ...], tuple[str, ...]]] = {
    PractitionerQuestionClass.MEASUREMENT_IDENTITY_AND_PROVENANCE: (
        ("F01", "F02", "F03", "F11", "F14"),
        ("C01", "C02", "C03", "C04", "C13", "C18"),
    ),
    PractitionerQuestionClass.COMPARABILITY_AND_HARMONIZATION: (
        ("F04", "F06", "F13", "F14"),
        ("C05", "C06", "C07", "C14", "C17", "C18"),
    ),
    PractitionerQuestionClass.INDIVIDUAL_LONGITUDINAL_CHANGE: (
        ("F07", "F10", "F12", "F14"),
        ("C09", "C12", "C15", "C18"),
    ),
    PractitionerQuestionClass.GROUP_OR_SQUAD_CHANGE: (
        ("F07", "F08", "F09", "F11", "F12"),
        tuple(f"C{index:02d}" for index in range(9, 16)),
    ),
    PractitionerQuestionClass.RELATIONSHIP_AND_MULTILEVEL_STRUCTURE: (
        ("F08", "F09", "F10", "F12", "F13"),
        ("C10", "C11", "C12", "C15", "C17", "C18"),
    ),
    PractitionerQuestionClass.CONSTRUCT_AND_CLAIM_INTERPRETATION: (
        ("F01", "F03", "F07", "F10", "F12", "F13"),
        ("C01", "C03", "C09", "C12", "C14", "C15", "C16", "C17"),
    ),
    PractitionerQuestionClass.METHOD_AND_ANALYSIS_REASONING: (
        ("F02", "F04", "F05", "F06", "F08", "F09"),
        ("C02", "C05", "C06", "C07", "C08", "C09", "C10", "C11", "C12", "C18"),
    ),
    PractitionerQuestionClass.ANSWERABILITY_AND_REFUSAL: (
        FAMILY_IDS,
        CAPABILITY_IDS,
    ),
}

_OPERATOR_BY_CAPABILITY = {
    "C01": ("res115.construct-identity", "1.0.0"),
    "C02": ("res115.protocol-extraction", "1.0.0"),
    "C03": ("res115.measurement-identity", "1.0.0"),
    "C04": ("res115.value-origin", "1.0.0"),
    "C05": ("res115.unit-normalization", "1.0.0"),
    "C06": ("res115.frame-event-boundary", "1.0.0"),
    "C07": ("res115.comparability", "1.0.0"),
    "C08": ("res115.registered-calculation-interpretation", "1.0.0"),
    "C09": ("res115.longitudinal-change", "1.0.0"),
    "C10": ("res115.analysis-selection", "1.0.0"),
    "C11": ("res115.analysis-level", "1.0.0"),
    "C12": ("res115.uncertainty-boundary", "1.0.0"),
    "C13": ("res115.evidence-extraction", "1.0.0"),
    "C14": ("res115.evidence-applicability", "1.0.0"),
    "C15": ("res115.causal-boundary", "1.0.0"),
    "C16": ("res115.engine-result-interpretation", "1.0.0"),
    "C17": ("res115.scientific-error-detection", "1.0.0"),
    "C18": ("res115.justified-refusal", "1.0.0"),
}

_AUTHORITY_CLASS_BY_KIND = {
    "EXPERT_RUBRIC": "EXPERT_SEMANTIC",
    "SOURCE_EVIDENCE_SPAN": "PHASE_A_SOURCE",
    "SOURCE_DOCUMENT": "PHASE_A_SOURCE",
    "RES71_RUNTIME": "RES71_REFERENCE",
    "RES71_OPERATION": "RES71_REFERENCE",
    "RES71_REFERENCE_CASE": "RES71_REFERENCE",
    "RES71_UNRESOLVED": "RES71_REFERENCE",
    "RES60_POPULATION": "SCIENTIFIC_REGISTRY",
    "RES62_PROVENANCE": "SCIENTIFIC_REGISTRY",
    "RES69_STATISTICS": "SCIENTIFIC_REGISTRY",
    "RES70_CLAIM": "SCIENTIFIC_REGISTRY",
    "RES70_COMPARABILITY": "SCIENTIFIC_REGISTRY",
    "RES70_ANALYSIS": "SCIENTIFIC_REGISTRY",
    "GENERATOR": "DETERMINISTIC_GENERATOR",
    "MUTATION_PARENT": "CANDIDATE_MUTATION",
}

_SUPPLEMENT_REASONS = frozenset(
    {
        "ENGINE_REFERENCE_COVERAGE",
        "SOURCE_POPULATION_APPLICABILITY",
        "SOURCE_MULTI_SPAN",
        "ORIGIN_SCORER_ERROR_COVERAGE",
        "MUTATION_LINEAGE_COVERAGE",
    }
)
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


def _row_by_capability(capability_id: str) -> CoverageRow:
    for row in COVERAGE_MATRIX:
        if row.capability_id == capability_id:
            return row
    raise ValueError(f"unknown capability in frozen authoring matrix: {capability_id}")


def question_classes_for_cell(
    capability_id: str,
    benchmark_family: str,
) -> tuple[PractitionerQuestionClass, ...]:
    """Return the frozen question classes that authorize a capability/family cell."""

    return tuple(
        question_class
        for question_class, (families, capabilities) in _QUESTION_CLASS_SCOPE.items()
        if benchmark_family in families and capability_id in capabilities
    )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class AuthoringRecipeV1:
    """Public immutable operator contract for one frozen capability/family cell."""

    recipe_id: str
    recipe_version: str
    operator_id: str
    operator_version: str
    capability_id: str
    benchmark_family: str
    question_classes: tuple[PractitionerQuestionClass, ...]
    origins: tuple[CaseOrigin, ...]
    scorers: tuple[ScoringProfile, ...]
    authority_kinds: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "recipe_id",
            "recipe_version",
            "operator_id",
            "operator_version",
            "capability_id",
            "benchmark_family",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be non-empty")
        if self.capability_id not in CAPABILITY_IDS or self.benchmark_family not in FAMILY_IDS:
            raise ValueError("authoring recipe has an unknown capability/family cell")
        if not self.question_classes or any(
            not isinstance(item, PractitionerQuestionClass) for item in self.question_classes
        ):
            raise ValueError("authoring recipe requires frozen question classes")
        if not self.origins or any(not isinstance(item, CaseOrigin) for item in self.origins):
            raise ValueError("authoring recipe requires valid origin classes")
        if not self.scorers or any(not isinstance(item, ScoringProfile) for item in self.scorers):
            raise ValueError("authoring recipe requires valid scorer profiles")
        if not self.authority_kinds or any(not item.strip() for item in self.authority_kinds):
            raise ValueError("authoring recipe requires authority classes")


def _build_recipe_registry() -> tuple[AuthoringRecipeV1, ...]:
    recipes: list[AuthoringRecipeV1] = []
    for row in COVERAGE_MATRIX:
        operator = _OPERATOR_BY_CAPABILITY.get(row.capability_id)
        if operator is None:
            continue
        for family in row.benchmark_families:
            recipes.append(
                AuthoringRecipeV1(
                    recipe_id=f"res115:{row.capability_id}:{family}",
                    recipe_version="1.0.0",
                    operator_id=operator[0],
                    operator_version=operator[1],
                    capability_id=row.capability_id,
                    benchmark_family=family,
                    question_classes=question_classes_for_cell(row.capability_id, family),
                    origins=row.case_origins,
                    scorers=row.scorer_profiles,
                    authority_kinds=row.answer_authorities,
                )
            )
    return tuple(recipes)


AUTHORING_RECIPE_REGISTRY = _build_recipe_registry()


def authoring_recipe_registry_digest(
    recipes: tuple[AuthoringRecipeV1, ...] = AUTHORING_RECIPE_REGISTRY,
) -> str:
    validate_authoring_recipe_registry(recipes)
    return canonical_hash(recipes)


def validate_authoring_recipe_registry(
    recipes: tuple[AuthoringRecipeV1, ...] = AUTHORING_RECIPE_REGISTRY,
) -> None:
    """Prove that a valid, authority-backed operator exists for all 87 cells."""

    validate_coverage_matrix()
    cells = tuple((recipe.capability_id, recipe.benchmark_family) for recipe in recipes)
    if len(cells) != len(set(cells)):
        raise ValueError("authoring recipe registry contains duplicate capability/family cells")
    if len({recipe.recipe_id for recipe in recipes}) != len(recipes):
        raise ValueError("authoring recipe IDs must be unique")
    required_cells = {
        (row.capability_id, family) for row in COVERAGE_MATRIX for family in row.benchmark_families
    }
    if set(cells) != required_cells or len(cells) != coverage_obligation_count():
        missing = sorted(required_cells.difference(cells))
        extra = sorted(set(cells).difference(required_cells))
        raise ValueError(
            f"authoring recipe registry does not cover the frozen cells; missing={missing}; "
            f"extra={extra}"
        )
    for recipe in recipes:
        expected_operator = _OPERATOR_BY_CAPABILITY.get(recipe.capability_id)
        row = _row_by_capability(recipe.capability_id)
        if expected_operator != (recipe.operator_id, recipe.operator_version):
            raise ValueError("authoring recipe has no registered generic operator")
        if recipe.benchmark_family not in row.benchmark_families:
            raise ValueError("authoring recipe relabels an unsupported capability/family cell")
        if recipe.question_classes != question_classes_for_cell(
            recipe.capability_id, recipe.benchmark_family
        ):
            raise ValueError("authoring recipe question classes differ from frozen authority")
        if recipe.origins != row.case_origins or recipe.scorers != row.scorer_profiles:
            raise ValueError("authoring recipe origin/scorer scope differs from frozen authority")
        if recipe.authority_kinds != row.answer_authorities:
            raise ValueError("authoring recipe authority scope differs from frozen authority")
        if not recipe.question_classes:
            raise ValueError("authoring recipe has no scientifically valid question class")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class AuthoringPlanItemV1:
    """One exact private recipe instance and its constructed candidate commitment."""

    recipe_id: str
    recipe_version: str
    coverage_role: str
    supplement_reason: str | None
    capability_id: str
    benchmark_family: str
    practitioner_question_class: PractitionerQuestionClass
    origin_class: CaseOrigin
    scoring_profile: ScoringProfile
    authority_class: str
    authority_kinds: tuple[str, ...]
    source_reference_ids: tuple[str, ...]
    source_search_strata: tuple[str, ...]
    parent_candidate_id: str | None
    engine_reference_case_id: str | None
    engine_operation_id: str | None
    generator_id: str | None
    generator_registry_digest: str | None
    seed_namespace: str | None
    seed_block: str | None
    difficulty: DifficultyLevel
    adversarial_tags: tuple[str, ...]
    authoring_rationale: str
    candidate_id: str
    candidate_payload_hash: str

    def __post_init__(self) -> None:
        for name in (
            "recipe_id",
            "recipe_version",
            "capability_id",
            "benchmark_family",
            "authority_class",
            "authoring_rationale",
            "candidate_id",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"authoring plan item {name} must be non-empty")
        if self.coverage_role not in {"CELL", "SUPPLEMENT"}:
            raise ValueError("coverage_role must be CELL or SUPPLEMENT")
        if self.coverage_role == "CELL" and self.supplement_reason is not None:
            raise ValueError("cell obligation cannot declare a supplement reason")
        if self.coverage_role == "SUPPLEMENT" and self.supplement_reason not in _SUPPLEMENT_REASONS:
            raise ValueError("supplement recipe is not required by a frozen qualification target")
        if self.capability_id not in CAPABILITY_IDS or self.benchmark_family not in FAMILY_IDS:
            raise ValueError("authoring plan item has an unknown capability/family cell")
        if not isinstance(self.practitioner_question_class, PractitionerQuestionClass):
            raise ValueError("authoring plan item question class is invalid")
        if not isinstance(self.origin_class, CaseOrigin):
            raise ValueError("authoring plan item origin class is invalid")
        if self.scoring_profile not in ACTIVE_SCORERS:
            raise ValueError("authoring plan item requires an active V1 scorer")
        if self.authority_class not in set(_AUTHORITY_CLASS_BY_KIND.values()):
            raise ValueError("authoring plan item has an unknown authority class")
        if not self.authority_kinds or any(not item.strip() for item in self.authority_kinds):
            raise ValueError("authoring plan item requires authority kinds")
        for name in ("source_reference_ids", "source_search_strata", "adversarial_tags"):
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(not isinstance(item, str) for item in values):
                raise ValueError(f"{name} must be an immutable string tuple")
        if self.parent_candidate_id is not None and not self.parent_candidate_id.strip():
            raise ValueError("parent_candidate_id must be non-empty when supplied")
        for name in ("engine_reference_case_id", "engine_operation_id", "generator_id"):
            value = getattr(self, name)
            if value is not None and not value.strip():
                raise ValueError(f"{name} must be non-empty when supplied")
        for name in ("generator_registry_digest",):
            value = getattr(self, name)
            if value is not None and _SHA256.fullmatch(value) is None:
                raise ValueError(f"{name} must be a sha256 digest")
        if (
            self.origin_class is CaseOrigin.ADVERSARIAL_MUTATION
            and self.parent_candidate_id is None
        ):
            raise ValueError("mutation plan item requires a parent candidate")
        if self.origin_class is CaseOrigin.DETERMINISTIC_ENGINE_DERIVED and (
            self.engine_reference_case_id is None
        ):
            raise ValueError("engine-derived plan item requires a RES-71 reference case")
        if self.origin_class is CaseOrigin.DETERMINISTIC_SYNTHETIC:
            if (
                self.generator_id is None
                or self.generator_registry_digest is None
                or self.seed_namespace is None
                or self.seed_block is None
            ):
                raise ValueError("synthetic plan item requires generator registry and seed inputs")
            if not self.seed_namespace.startswith(QUALIFICATION_SEED_NAMESPACE_PREFIX):
                raise ValueError("synthetic qualification seed uses a non-qualification namespace")
            if _SEED_BLOCK.fullmatch(self.seed_block) is None:
                raise ValueError("synthetic qualification seed block is malformed")
        if self.candidate_id.startswith("sha256:") or not self.candidate_id.startswith(
            QUALIFICATION_CANDIDATE_ID_PREFIX
        ):
            raise ValueError("candidate ID must use the qualification-only namespace")
        if _SHA256.fullmatch(self.candidate_payload_hash) is None:
            raise ValueError("candidate_payload_hash must be a sha256 digest")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class AuthoringPlanV1:
    """Canonical recipe-instance list, stored outside Git for real batches."""

    plan_id: str
    plan_version: str
    coverage_matrix_digest: str
    recipe_registry_digest: str
    items: tuple[AuthoringPlanItemV1, ...]
    plan_digest: str

    def __post_init__(self) -> None:
        for name in ("plan_id", "plan_version"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must be non-empty")
        for name in ("coverage_matrix_digest", "recipe_registry_digest", "plan_digest"):
            if _SHA256.fullmatch(getattr(self, name)) is None:
                raise ValueError(f"{name} must be a sha256 digest")
        if not self.items or any(not isinstance(item, AuthoringPlanItemV1) for item in self.items):
            raise ValueError("authoring plan requires exact typed plan items")
        order = tuple(_plan_item_order(item) for item in self.items)
        if order != tuple(sorted(order)):
            raise ValueError("authoring plan items must use canonical deterministic order")


def _plan_item_order(item: AuthoringPlanItemV1) -> tuple[bytes, bytes, bytes, bytes]:
    return (
        item.capability_id.encode("utf-8"),
        item.benchmark_family.encode("utf-8"),
        item.coverage_role.encode("utf-8"),
        item.candidate_id.encode("utf-8"),
    )


def _authoring_plan_payload(plan: AuthoringPlanV1 | Mapping[str, object]) -> Mapping[str, object]:
    if isinstance(plan, Mapping):
        return {key: value for key, value in plan.items() if key != "plan_digest"}
    return {
        item.name: getattr(plan, item.name) for item in fields(plan) if item.name != "plan_digest"
    }


def authoring_plan_digest(plan: AuthoringPlanV1 | Mapping[str, object]) -> str:
    return canonical_hash(_authoring_plan_payload(plan))


def bind_authoring_plan(plan: AuthoringPlanV1) -> AuthoringPlanV1:
    return replace(plan, plan_digest=authoring_plan_digest(plan))


def validate_authoring_plan(
    plan: AuthoringPlanV1,
    *,
    recipes: tuple[AuthoringRecipeV1, ...] = AUTHORING_RECIPE_REGISTRY,
    require_all_cells: bool = True,
) -> None:
    validate_authoring_recipe_registry(recipes)
    if plan.plan_version != AUTHORING_PLAN_VERSION:
        raise ValueError("unsupported authoring plan version")
    if plan.coverage_matrix_digest != coverage_manifest_digest():
        raise ValueError("authoring plan is stale against the frozen coverage matrix")
    if plan.recipe_registry_digest != authoring_recipe_registry_digest(recipes):
        raise ValueError("authoring plan is stale against the authoring operator registry")
    if plan.plan_digest != authoring_plan_digest(plan):
        raise ValueError("authoring plan digest mismatch")
    recipe_by_id = {recipe.recipe_id: recipe for recipe in recipes}
    ids = tuple(item.candidate_id for item in plan.items)
    hashes = tuple(item.candidate_payload_hash for item in plan.items)
    if len(set(ids)) != len(ids) or len(set(hashes)) != len(hashes):
        raise ValueError("authoring plan candidate IDs and payload hashes must be unique")
    required_cells = {
        (row.capability_id, family) for row in COVERAGE_MATRIX for family in row.benchmark_families
    }
    represented_cells: set[tuple[str, str]] = set()
    for item in plan.items:
        recipe = recipe_by_id.get(item.recipe_id)
        if recipe is None or recipe.recipe_version != item.recipe_version:
            raise ValueError("authoring plan references an unknown recipe/version")
        cell = (item.capability_id, item.benchmark_family)
        if cell != (recipe.capability_id, recipe.benchmark_family):
            raise ValueError("authoring plan recipe was relabelled to another cell")
        if item.practitioner_question_class not in recipe.question_classes:
            raise ValueError("authoring plan question class is not valid for its frozen cell")
        if item.origin_class not in recipe.origins:
            raise ValueError("authoring plan origin is not authorized for its frozen cell")
        if item.scoring_profile not in recipe.scorers:
            raise ValueError("authoring plan scorer is not authorized for its frozen cell")
        if not set(item.authority_kinds).intersection(recipe.authority_kinds):
            raise ValueError("authoring plan has no authority allowed for its frozen cell")
        classes = {_AUTHORITY_CLASS_BY_KIND.get(kind) for kind in item.authority_kinds}
        if item.authority_class not in classes:
            raise ValueError("authoring plan authority class does not match its bindings")
        if item.coverage_role == "CELL":
            if cell in represented_cells:
                raise ValueError("authoring plan has duplicate primary cell recipes")
            represented_cells.add(cell)
    if require_all_cells and represented_cells != required_cells:
        missing = tuple(sorted(required_cells - represented_cells))
        extra = tuple(sorted(represented_cells - required_cells))
        raise ValueError(
            f"authoring plan does not cover all frozen cells; missing={missing}; extra={extra}"
        )
    if not require_all_cells and not represented_cells.issubset(required_cells):
        raise ValueError("authoring plan contains a recipe outside frozen capability/family cells")
    seed_uses = tuple(
        (item.generator_id, item.seed_namespace, item.seed_block)
        for item in plan.items
        if item.origin_class is CaseOrigin.DETERMINISTIC_SYNTHETIC
    )
    if len(set(seed_uses)) != len(seed_uses):
        raise ValueError("qualification generator seed collision in authoring plan")


def validate_production_seed_namespace(seed_namespace: str) -> None:
    """Reject qualification seeds without freezing any future production policy."""

    if not isinstance(seed_namespace, str) or not seed_namespace.strip():
        raise ValueError("production seed namespace must be non-empty")
    if seed_namespace.startswith(QUALIFICATION_SEED_NAMESPACE_PREFIX):
        raise ValueError("qualification-only seed namespace cannot be used for production")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class QualificationCandidateCommitmentV1:
    """Public-safe candidate identity, hash, and aggregate coverage metadata."""

    candidate_id: str
    candidate_payload_hash: str
    capability_id: str
    benchmark_family: str
    practitioner_question_class: PractitionerQuestionClass
    origin_class: CaseOrigin
    scoring_profile: ScoringProfile
    authority_class: str
    authority_kinds: tuple[str, ...]
    reachable_error_classes: tuple[ErrorClass, ...]
    source_document_ids: tuple[str, ...]
    expected_answer_kind: ExpectedAnswerKind
    refusal_decision: RefusalDecision
    safe_partial_support: bool

    def __post_init__(self) -> None:
        if not self.candidate_id.startswith(QUALIFICATION_CANDIDATE_ID_PREFIX):
            raise ValueError("qualification commitment candidate ID is not namespaced")
        if _SHA256.fullmatch(self.candidate_payload_hash) is None:
            raise ValueError("qualification commitment hash is malformed")
        if self.capability_id not in CAPABILITY_IDS or self.benchmark_family not in FAMILY_IDS:
            raise ValueError("qualification commitment has an unknown coverage cell")
        if self.scoring_profile not in ACTIVE_SCORERS:
            raise ValueError("qualification commitment has an inactive scorer")
        if not isinstance(self.expected_answer_kind, ExpectedAnswerKind):
            raise ValueError("qualification commitment has an invalid answer kind")
        if not isinstance(self.refusal_decision, RefusalDecision):
            raise ValueError("qualification commitment has an invalid refusal decision")
        for field_name in ("authority_kinds", "source_document_ids"):
            values = getattr(self, field_name)
            if not isinstance(values, tuple) or any(not item for item in values):
                raise ValueError(f"{field_name} must be an immutable tuple of non-empty strings")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CandidateStoreReceiptV1:
    """Integrity receipt for an external-only qualification packet store."""

    batch_id: str
    store_relative_path: str
    candidate_file_digests: tuple[tuple[str, str], ...]
    candidate_count: int
    total_bytes: int
    authoring_plan_digest: str
    artifact_inventory_digest: str
    receipt_digest: str

    def __post_init__(self) -> None:
        if not self.batch_id.strip():
            raise ValueError("batch_id must be non-empty")
        path = self.store_relative_path
        if path.startswith("/") or ".." in path.split("/") or not path.startswith("qualification/"):
            raise ValueError("qualification store path must remain under qualification/")
        if self.candidate_count < 1 or self.total_bytes < 1:
            raise ValueError("candidate store receipt requires positive counts and size")
        for name in (
            "authoring_plan_digest",
            "artifact_inventory_digest",
            "receipt_digest",
        ):
            if _SHA256.fullmatch(getattr(self, name)) is None:
                raise ValueError(f"{name} must be a sha256 digest")
        ids = tuple(candidate_id for candidate_id, _ in self.candidate_file_digests)
        if len(ids) != self.candidate_count or len(set(ids)) != len(ids):
            raise ValueError("candidate store receipt must bind every unique candidate file")
        if ids != tuple(sorted(ids, key=lambda value: value.encode("utf-8"))):
            raise ValueError("candidate store receipt entries must use canonical ID order")
        if any(
            not candidate_id.startswith(QUALIFICATION_CANDIDATE_ID_PREFIX) for candidate_id in ids
        ):
            raise ValueError("candidate store receipt includes a non-qualification ID")
        if any(_SHA256.fullmatch(digest) is None for _, digest in self.candidate_file_digests):
            raise ValueError("candidate file digest is malformed")


def candidate_store_receipt_digest(receipt: CandidateStoreReceiptV1) -> str:
    return canonical_hash(
        {
            item.name: getattr(receipt, item.name)
            for item in fields(receipt)
            if item.name != "receipt_digest"
        }
    )


def bind_candidate_store_receipt(receipt: CandidateStoreReceiptV1) -> CandidateStoreReceiptV1:
    return replace(receipt, receipt_digest=candidate_store_receipt_digest(receipt))


def validate_candidate_store_receipt(receipt: CandidateStoreReceiptV1) -> None:
    if receipt.receipt_digest != candidate_store_receipt_digest(receipt):
        raise ValueError("candidate store receipt digest mismatch")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class QualificationBatchManifestV1:
    """Qualification-only public commitment to an external candidate batch."""

    batch_id: str
    manifest_version: str
    qualification_only: bool
    final_v1_eligible: bool
    authoring_plan_digest: str
    candidate_store_receipt_digest: str
    candidate_entries: tuple[QualificationCandidateCommitmentV1, ...]
    res71_reference_case_ids: tuple[str, ...]
    direct_target_document_ids: tuple[str, ...]
    evidence_search_strata: tuple[str, ...]
    source_family_ids: tuple[str, ...]
    human_approval_count: int
    final_case_count: int
    split_assignment_count: int
    protected_store_count: int
    manifest_digest: str

    def __post_init__(self) -> None:
        if not self.batch_id.startswith("PSE-V1-QUALIFICATION/"):
            raise ValueError("qualification batch ID must use the non-production namespace")
        if self.manifest_version != QUALIFICATION_MANIFEST_VERSION:
            raise ValueError("unsupported qualification manifest version")
        if self.qualification_only is not True or self.final_v1_eligible is not False:
            raise ValueError("qualification packets can never be final V1 eligible")
        for name in ("authoring_plan_digest", "candidate_store_receipt_digest", "manifest_digest"):
            if _SHA256.fullmatch(getattr(self, name)) is None:
                raise ValueError(f"{name} must be a sha256 digest")
        if not self.candidate_entries:
            raise ValueError("qualification batch manifest must bind candidate commitments")
        ids = tuple(item.candidate_id for item in self.candidate_entries)
        hashes = tuple(item.candidate_payload_hash for item in self.candidate_entries)
        if len(set(ids)) != len(ids) or len(set(hashes)) != len(hashes):
            raise ValueError("qualification candidate IDs and hashes must be unique")
        for name in (
            "res71_reference_case_ids",
            "direct_target_document_ids",
            "evidence_search_strata",
            "source_family_ids",
        ):
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(
                not isinstance(item, str) or not item for item in values
            ):
                raise ValueError(f"{name} must be an immutable non-empty-string tuple")
        if any(
            count != 0
            for count in (
                self.human_approval_count,
                self.final_case_count,
                self.split_assignment_count,
                self.protected_store_count,
            )
        ):
            raise ValueError(
                "qualification batch cannot contain approvals, final cases, splits, or stores"
            )


def qualification_batch_manifest_digest(manifest: QualificationBatchManifestV1) -> str:
    return canonical_hash(
        {
            item.name: getattr(manifest, item.name)
            for item in fields(manifest)
            if item.name != "manifest_digest"
        }
    )


def bind_qualification_batch_manifest(
    manifest: QualificationBatchManifestV1,
) -> QualificationBatchManifestV1:
    return replace(manifest, manifest_digest=qualification_batch_manifest_digest(manifest))


def validate_qualification_batch_manifest(manifest: QualificationBatchManifestV1) -> None:
    if manifest.manifest_digest != qualification_batch_manifest_digest(manifest):
        raise ValueError("qualification batch manifest digest mismatch")
    validate_qualification_commitment_coverage(manifest.candidate_entries)
    from dynamislm.qualification import get_reference_cases

    expected_reference_ids = tuple(item.case_id for item in get_reference_cases())
    if manifest.res71_reference_case_ids != expected_reference_ids:
        raise ValueError("qualification manifest must bind all 12 live RES-71 reference cases")
    if (
        len(manifest.direct_target_document_ids) != 5
        or len(set(manifest.direct_target_document_ids)) != 5
    ):
        raise ValueError("qualification manifest must bind all five direct-target documents")
    if len(manifest.evidence_search_strata) != len(PHASE_A_SEARCH_STRATA) or set(
        manifest.evidence_search_strata
    ) != set(PHASE_A_SEARCH_STRATA):
        raise ValueError("qualification manifest must bind all ten Phase-A search strata")
    if len(set(manifest.source_family_ids)) < 10:
        raise ValueError("qualification manifest must bind at least ten source families")


@dataclass(frozen=True, slots=True)
class QualificationBatchValidation:
    candidate_count: int
    represented_cells: int
    represented_capabilities: int
    represented_families: int
    represented_question_classes: int
    represented_origins: int
    represented_scorers: int
    represented_error_classes: int
    required_refusals: int
    safe_partial_answers: int
    mutation_depth: int
    multi_stratum_mutation: bool
    status: str = "PASS"


@dataclass(frozen=True, slots=True)
class QualificationCommitmentCoverage:
    candidate_count: int
    represented_cells: int
    represented_capabilities: int
    represented_families: int
    represented_question_classes: int
    represented_origins: int
    represented_scorers: int
    represented_error_classes: int
    required_refusals: int
    safe_partial_answers: int
    status: str = "PASS"


def _commitment_for(
    packet: CandidateReviewPacket,
    item: AuthoringPlanItemV1,
) -> QualificationCandidateCommitmentV1:
    reachable = reachable_error_classes(
        packet.scoring_contract,
        refusal_decision=packet.refusal_contract.decision,
        prohibited_claims=packet.proposed_expected_answer.prohibited_claims,
    )
    source_documents = tuple(
        sorted(
            {
                reference.document_identity.document_id
                for reference in packet.source_evidence_refs
                if reference.document_identity is not None
            },
            key=lambda value: value.encode("utf-8"),
        )
    )
    return QualificationCandidateCommitmentV1(
        candidate_id=packet.candidate_id,
        candidate_payload_hash=packet.candidate_payload_hash,
        capability_id=packet.capability_id,
        benchmark_family=packet.benchmark_family,
        practitioner_question_class=packet.practitioner_question_class,
        origin_class=packet.proposed_provenance.origin_class,
        scoring_profile=packet.scoring_contract.profile_id,
        authority_class=item.authority_class,
        authority_kinds=tuple(
            sorted(
                {binding.authority_kind for binding in packet.authority},
                key=lambda value: value.encode("utf-8"),
            )
        ),
        reachable_error_classes=tuple(
            sorted(reachable, key=lambda value: value.value.encode("utf-8"))
        ),
        source_document_ids=source_documents,
        expected_answer_kind=packet.proposed_expected_answer.kind,
        refusal_decision=packet.refusal_contract.decision,
        safe_partial_support=bool(
            packet.refusal_contract.what_can_still_be_safely_described
            and (
                packet.refusal_contract.safe_lower_claim_level is not None
                or packet.claim_contract.safe_lower_claim_levels
                or packet.proposed_expected_answer.safe_lower_level_descriptions
            )
        ),
    )


def validate_qualification_commitment_coverage(
    entries: tuple[QualificationCandidateCommitmentV1, ...],
) -> QualificationCommitmentCoverage:
    """Validate public coverage commitments without reading packet payloads."""

    if not entries:
        raise ValueError("qualification batch commitments must be non-empty")
    ids = tuple(item.candidate_id for item in entries)
    hashes = tuple(item.candidate_payload_hash for item in entries)
    if len(set(ids)) != len(ids) or len(set(hashes)) != len(hashes):
        raise ValueError("qualification candidate IDs and payload hashes must be unique")
    cells = {(item.capability_id, item.benchmark_family) for item in entries}
    required_cells = {
        (row.capability_id, family) for row in COVERAGE_MATRIX for family in row.benchmark_families
    }
    if cells != required_cells or len(cells) != coverage_obligation_count():
        missing = tuple(sorted(required_cells - cells))
        extra = tuple(sorted(cells - required_cells))
        raise ValueError(f"qualification coverage is not 87/87; missing={missing}; extra={extra}")
    for entry in entries:
        row = _row_by_capability(entry.capability_id)
        if entry.benchmark_family not in row.benchmark_families:
            raise ValueError("candidate commitment is outside the frozen capability/family matrix")
        if entry.practitioner_question_class not in question_classes_for_cell(
            entry.capability_id, entry.benchmark_family
        ):
            raise ValueError("candidate commitment uses an invalid question class for its cell")
        if entry.origin_class not in row.case_origins:
            raise ValueError("candidate commitment uses an invalid origin for its cell")
        if entry.scoring_profile not in row.scorer_profiles:
            raise ValueError("candidate commitment uses an invalid scorer for its cell")
        if not set(entry.authority_kinds).intersection(row.answer_authorities):
            raise ValueError("candidate commitment has no authorized answer authority")
        allowed_authority_classes = {
            _AUTHORITY_CLASS_BY_KIND.get(kind) for kind in entry.authority_kinds
        }
        if entry.authority_class not in allowed_authority_classes:
            raise ValueError("candidate commitment authority class does not match its bindings")
        if not set(entry.reachable_error_classes).issubset(row.error_classes):
            raise ValueError("candidate commitment maps an error outside its frozen cell")
        if entry.capability_id == "C17" and entry.origin_class is (
            CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION
        ):
            raise ValueError("C17 cannot be qualified by forced source tags")
    capabilities = {item.capability_id for item in entries}
    families = {item.benchmark_family for item in entries}
    question_classes = {item.practitioner_question_class for item in entries}
    origins = {item.origin_class for item in entries}
    scorers = {item.scoring_profile for item in entries}
    errors = {error for item in entries for error in item.reachable_error_classes}
    if capabilities != set(CAPABILITY_IDS):
        raise ValueError("qualification commitments do not represent C01..C18")
    if families != set(FAMILY_IDS):
        raise ValueError("qualification commitments do not represent F01..F14")
    if question_classes != set(PractitionerQuestionClass):
        raise ValueError("qualification commitments do not represent all question classes")
    if origins != set(CaseOrigin):
        raise ValueError("qualification commitments do not represent all origin classes")
    if scorers != set(ACTIVE_SCORERS):
        raise ValueError("qualification commitments do not represent all active scorers")
    if errors != set(ErrorClass):
        missing_error_values: list[str] = []
        for error_class in ErrorClass:
            if error_class not in errors:
                missing_error_values.append(error_class.value)
        raise ValueError(
            f"qualification commitments have unreachable ErrorClass values: {missing_error_values}"
        )
    if {item.benchmark_family for item in entries if item.capability_id == "C17"} != set(
        FAMILY_IDS
    ):
        raise ValueError("C17 must be explicitly represented in every family")
    if {item.benchmark_family for item in entries if item.capability_id == "C18"} != set(
        FAMILY_IDS
    ):
        raise ValueError("C18 must be explicitly represented in every family")
    answerable = any(
        item.refusal_decision is not RefusalDecision.REQUIRED
        and item.expected_answer_kind is not ExpectedAnswerKind.REFUSAL
        for item in entries
    )
    required_refusals = sum(item.refusal_decision is RefusalDecision.REQUIRED for item in entries)
    safe_partials = sum(
        item.refusal_decision is RefusalDecision.REQUIRED and item.safe_partial_support
        for item in entries
    )
    if not answerable or not required_refusals or not safe_partials:
        raise ValueError("qualification commitments require answer/refusal/safe-partial outcomes")
    return QualificationCommitmentCoverage(
        candidate_count=len(entries),
        represented_cells=len(cells),
        represented_capabilities=len(capabilities),
        represented_families=len(families),
        represented_question_classes=len(question_classes),
        represented_origins=len(origins),
        represented_scorers=len(scorers),
        represented_error_classes=len(errors),
        required_refusals=required_refusals,
        safe_partial_answers=safe_partials,
    )


def validate_qualification_batch(
    packets: tuple[CandidateReviewPacket, ...],
    plan: AuthoringPlanV1,
    manifest: QualificationBatchManifestV1,
    store_receipt: CandidateStoreReceiptV1,
    *,
    source_resolver: SourceArtifactResolver | None = None,
) -> QualificationBatchValidation:
    """Validate every packet and the complete qualification-only coverage contract."""

    validate_authoring_plan(plan)
    validate_qualification_batch_manifest(manifest)
    validate_candidate_store_receipt(store_receipt)
    recipe_by_id = {recipe.recipe_id: recipe for recipe in AUTHORING_RECIPE_REGISTRY}
    if manifest.batch_id != store_receipt.batch_id:
        raise ValueError("manifest and external candidate-store batch IDs disagree")
    if manifest.authoring_plan_digest != plan.plan_digest:
        raise ValueError("qualification manifest does not bind the authoring plan")
    if manifest.candidate_store_receipt_digest != store_receipt.receipt_digest:
        raise ValueError("qualification manifest has a stale external-store receipt")
    if store_receipt.authoring_plan_digest != plan.plan_digest:
        raise ValueError("candidate-store receipt does not bind the authoring plan")

    packet_by_id = {packet.candidate_id: packet for packet in packets}
    plan_by_id = {item.candidate_id: item for item in plan.items}
    if len(packet_by_id) != len(packets) or len(plan_by_id) != len(plan.items):
        raise ValueError("qualification candidate IDs must be unique")
    if set(packet_by_id) != set(plan_by_id):
        raise ValueError("authoring plan and candidate store have different candidate IDs")
    if len({packet.candidate_payload_hash for packet in packets}) != len(packets):
        raise ValueError("qualification candidate payload hashes must be unique")
    for packet in packets:
        if not packet.candidate_id.startswith(QUALIFICATION_CANDIDATE_ID_PREFIX):
            raise ValueError("qualification candidate ID uses a production/unknown namespace")
        item = plan_by_id[packet.candidate_id]
        if (
            packet.candidate_payload_hash != item.candidate_payload_hash
            or packet.capability_id != item.capability_id
            or packet.benchmark_family != item.benchmark_family
            or packet.practitioner_question_class is not item.practitioner_question_class
            or packet.proposed_provenance.origin_class is not item.origin_class
            or packet.scoring_contract.profile_id is not item.scoring_profile
        ):
            raise ValueError("candidate packet differs from its exact authoring plan instance")
        if packet.capability_id == "C17" and packet.proposed_provenance.origin_class is (
            CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION
        ):
            raise ValueError("C17 must be explicitly authored; source-tag forcing is prohibited")
        if (
            packet.capability_id == "C17"
            and recipe_by_id[plan_by_id[packet.candidate_id].recipe_id].operator_id
            != _OPERATOR_BY_CAPABILITY["C17"][0]
        ):
            raise ValueError("C17 qualification must use its scientific-error operator")

    validate_candidate_set(packets, source_resolver=source_resolver)

    commitments = tuple(
        _commitment_for(packet_by_id[item.candidate_id], item)
        for item in sorted(plan.items, key=_plan_item_order)
    )
    expected_commitments = tuple(
        sorted(manifest.candidate_entries, key=lambda item: item.candidate_id.encode("utf-8"))
    )
    observed_commitments = tuple(
        sorted(commitments, key=lambda item: item.candidate_id.encode("utf-8"))
    )
    if observed_commitments != expected_commitments:
        raise ValueError("qualification manifest candidate commitments are stale or incomplete")
    validate_qualification_commitment_coverage(observed_commitments)
    receipt_entries = dict(store_receipt.candidate_file_digests)
    if set(receipt_entries) != set(packet_by_id):
        raise ValueError("external candidate-store receipt does not bind every packet")

    represented_cells = {(packet.capability_id, packet.benchmark_family) for packet in packets}
    required_cells = {
        (row.capability_id, family) for row in COVERAGE_MATRIX for family in row.benchmark_families
    }
    if represented_cells != required_cells or len(represented_cells) != coverage_obligation_count():
        missing = tuple(sorted(required_cells - represented_cells))
        extra = tuple(sorted(represented_cells - required_cells))
        raise ValueError(f"qualification coverage is not 87/87; missing={missing}; extra={extra}")
    represented_capabilities = {packet.capability_id for packet in packets}
    represented_families = {packet.benchmark_family for packet in packets}
    question_classes = {packet.practitioner_question_class for packet in packets}
    origins = {packet.proposed_provenance.origin_class for packet in packets}
    scorers = {packet.scoring_contract.profile_id for packet in packets}
    errors = {
        error_class
        for packet in packets
        for error_class in reachable_error_classes(
            packet.scoring_contract,
            refusal_decision=packet.refusal_contract.decision,
            prohibited_claims=packet.proposed_expected_answer.prohibited_claims,
        )
    }
    if represented_capabilities != set(CAPABILITY_IDS):
        raise ValueError("qualification batch does not represent C01..C18")
    if represented_families != set(FAMILY_IDS):
        raise ValueError("qualification batch does not represent F01..F14")
    if question_classes != set(PractitionerQuestionClass):
        raise ValueError("qualification batch does not represent all eight question classes")
    if origins != set(CaseOrigin):
        raise ValueError("qualification batch does not represent all five origins")
    if scorers != set(ACTIVE_SCORERS):
        raise ValueError("qualification batch does not represent all active scorer profiles")
    if errors != set(ErrorClass):
        missing_error_values: list[str] = []
        for error_class in ErrorClass:
            if error_class not in errors:
                missing_error_values.append(error_class.value)
        raise ValueError(
            "qualification batch has unreachable registered ErrorClass values: "
            f"{missing_error_values}"
        )

    c17_families = {packet.benchmark_family for packet in packets if packet.capability_id == "C17"}
    c18_families = {packet.benchmark_family for packet in packets if packet.capability_id == "C18"}
    if c17_families != set(FAMILY_IDS) or c18_families != set(FAMILY_IDS):
        raise ValueError("C17 and C18 must each be explicitly qualified across F01..F14")

    answerable = tuple(
        packet
        for packet in packets
        if packet.refusal_contract.decision.value != "REQUIRED"
        and packet.proposed_expected_answer.kind.value != "REFUSAL"
    )
    refusals = tuple(
        packet for packet in packets if packet.refusal_contract.decision.value == "REQUIRED"
    )
    safe_partial = tuple(
        packet
        for packet in refusals
        if packet.refusal_contract.what_can_still_be_safely_described
        and (
            packet.refusal_contract.safe_lower_claim_level is not None
            or packet.claim_contract.safe_lower_claim_levels
            or packet.proposed_expected_answer.safe_lower_level_descriptions
        )
    )
    if not answerable or not refusals or not safe_partial:
        raise ValueError(
            "qualification batch requires answerable, refusal, and safe-partial outcomes"
        )
    if not any(packet.capability_id == "C18" for packet in refusals):
        raise ValueError("C18 qualification must include a required refusal")

    mutations = tuple(
        packet
        for packet in packets
        if packet.proposed_provenance.origin_class is CaseOrigin.ADVERSARIAL_MUTATION
    )
    order = topological_candidate_promotion_order(packets, source_resolver=source_resolver)
    order_positions = {packet.candidate_id: index for index, packet in enumerate(order)}
    by_id = packet_by_id
    mutation_depth = 0
    multi_stratum_mutation = False
    for child in mutations:
        binding = child.parent_candidate_binding
        if binding is None:
            raise ValueError("mutation qualification packet lacks its sealed parent binding")
        parent = by_id[binding.parent_candidate_id]
        if order_positions[parent.candidate_id] >= order_positions[child.candidate_id]:
            raise ValueError("mutation authoring order is not parent-first and deterministic")
        depth = 1
        current = parent
        while current.proposed_provenance.origin_class is CaseOrigin.ADVERSARIAL_MUTATION:
            ancestor_binding = current.parent_candidate_binding
            if ancestor_binding is None:
                raise ValueError("mutation descendant has an unresolved parent")
            current = by_id[ancestor_binding.parent_candidate_id]
            depth += 1
        mutation_depth = max(mutation_depth, depth)
        if (
            child.isolation.isolation_cluster_id == parent.isolation.isolation_cluster_id
            and child.isolation.allocation_stratum != parent.isolation.allocation_stratum
        ):
            multi_stratum_mutation = True
    if mutation_depth < 2 or not multi_stratum_mutation:
        raise ValueError(
            "qualification mutations require an ordinary-to-descendant chain across strata"
        )

    return QualificationBatchValidation(
        candidate_count=len(packets),
        represented_cells=len(represented_cells),
        represented_capabilities=len(represented_capabilities),
        represented_families=len(represented_families),
        represented_question_classes=len(question_classes),
        represented_origins=len(origins),
        represented_scorers=len(scorers),
        represented_error_classes=len(errors),
        required_refusals=len(refusals),
        safe_partial_answers=len(safe_partial),
        mutation_depth=mutation_depth,
        multi_stratum_mutation=multi_stratum_mutation,
    )


def bind_qualification_manifest_for_candidates(
    *,
    batch_id: str,
    plan: AuthoringPlanV1,
    store_receipt: CandidateStoreReceiptV1,
    packets: tuple[CandidateReviewPacket, ...],
    res71_reference_case_ids: tuple[str, ...],
    direct_target_document_ids: tuple[str, ...],
    evidence_search_strata: tuple[str, ...],
    source_family_ids: tuple[str, ...],
) -> QualificationBatchManifestV1:
    """Create the public-safe manifest after candidates are in external storage."""

    item_by_id = {item.candidate_id: item for item in plan.items}
    entries = tuple(
        sorted(
            (_commitment_for(packet, item_by_id[packet.candidate_id]) for packet in packets),
            key=lambda item: item.candidate_id.encode("utf-8"),
        )
    )
    provisional = QualificationBatchManifestV1(
        batch_id=batch_id,
        manifest_version=QUALIFICATION_MANIFEST_VERSION,
        qualification_only=True,
        final_v1_eligible=False,
        authoring_plan_digest=plan.plan_digest,
        candidate_store_receipt_digest=store_receipt.receipt_digest,
        candidate_entries=entries,
        res71_reference_case_ids=res71_reference_case_ids,
        direct_target_document_ids=direct_target_document_ids,
        evidence_search_strata=evidence_search_strata,
        source_family_ids=source_family_ids,
        human_approval_count=0,
        final_case_count=0,
        split_assignment_count=0,
        protected_store_count=0,
        manifest_digest="sha256:" + "0" * 64,
    )
    return bind_qualification_batch_manifest(provisional)


__all__ = [
    "ACTIVE_SCORERS",
    "AUTHORING_PLAN_VERSION",
    "AUTHORING_RECIPE_REGISTRY",
    "PHASE_A_SEARCH_STRATA",
    "QUALIFICATION_CANDIDATE_ID_PREFIX",
    "QUALIFICATION_MANIFEST_VERSION",
    "QUALIFICATION_SEED_NAMESPACE_PREFIX",
    "AuthoringPlanItemV1",
    "AuthoringPlanV1",
    "AuthoringRecipeV1",
    "CandidateStoreReceiptV1",
    "QualificationBatchManifestV1",
    "QualificationBatchValidation",
    "QualificationCandidateCommitmentV1",
    "QualificationCommitmentCoverage",
    "authoring_plan_digest",
    "authoring_recipe_registry_digest",
    "bind_authoring_plan",
    "bind_candidate_store_receipt",
    "bind_qualification_batch_manifest",
    "bind_qualification_manifest_for_candidates",
    "candidate_store_receipt_digest",
    "qualification_batch_manifest_digest",
    "question_classes_for_cell",
    "validate_authoring_plan",
    "validate_authoring_recipe_registry",
    "validate_candidate_store_receipt",
    "validate_qualification_batch",
    "validate_qualification_batch_manifest",
]
