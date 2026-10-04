"""Regression checks for the RES-258 PSE V1 authority surface."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DECISION = (
    ROOT / "docs/decisions/RES258-DR-001-pse-v1-pool-first-selection-authority.md"
).read_text(encoding="utf-8")
SUPERSESSION = (ROOT / "docs/decisions/RES258-SUPERSESSION-MAP.md").read_text(encoding="utf-8")
LIFECYCLE = (ROOT / "docs/architecture/PERFORMANCE_SCIENCE_EVAL_PRE_REVIEW_V1.md").read_text(
    encoding="utf-8"
)
DECISION_NORMALIZED = " ".join(DECISION.split()).lower()
LIFECYCLE_NORMALIZED = " ".join(LIFECYCLE.split()).lower()


def test_pool_and_final_cardinality_are_separate() -> None:
    assert "PRE_REVIEW_POOL_N=VARIABLE_GE434" in DECISION
    assert "FINAL_SELECTED_N=434" in DECISION
    assert "FINAL_SPLITS=PUBLIC_DEVELOPMENT:260,FROZEN_VALIDATION:87,HIDDEN_FINAL:87" in DECISION
    assert "no fixed pre-review count" in DECISION.lower()
    assert "pre-review pool has no fixed cardinality beyond `N >= 434`" in LIFECYCLE
    for active_document in (DECISION, LIFECYCLE):
        assert "PRE_REVIEW_POOL_N=434" not in active_document
        assert "pre-review pool is exactly 434" not in active_document.lower()


def test_final_composition_uses_res126_bounds() -> None:
    for name, bound in (
        ("EXPERT_AUTHORED_SEMANTIC", "<= 240"),
        ("SOURCE_BACKED_EVIDENCE_EXTRACTION", ">= 40"),
        ("DETERMINISTIC_ENGINE_DERIVED", ">= 30"),
        ("DETERMINISTIC_SYNTHETIC", ">= 12"),
        ("ADVERSARIAL_MUTATION", ">= 60"),
        ("MUTATION_LINEAGES", ">= 20"),
    ):
        assert f"| `{name}` | `{bound}`" in DECISION
    assert "EXPERT_AUTHORED_SEMANTIC_SCOPE=FINAL_SELECTED_ONLY;MAX=240" in DECISION
    assert "res-126 composition bounds" in LIFECYCLE_NORMALIZED
    for phrase in (
        "expert-authored semantic `<= 240`",
        "source-backed evidence extraction `>= 40`",
        "deterministic engine-derived `>= 30`",
        "deterministic synthetic `>= 12`",
        "adversarial mutation `>= 60`",
        "at least 20 mutation lineages",
    ):
        assert phrase in LIFECYCLE_NORMALIZED


def test_old_exact_origin_vector_and_37_by_3_are_historical_only() -> None:
    rows = [line for line in SUPERSESSION.splitlines() if line.startswith("| RES-")]
    assert any("RES-249" in line and "historical" in line.lower() for line in rows)
    assert "EXACT_ORIGIN_VECTOR_240_40_31_12_111=HISTORICAL_EVIDENCE_ONLY" in SUPERSESSION
    assert "MUTATION_37X3=HISTORICAL_EVIDENCE_ONLY" in SUPERSESSION
    assert "remain historical evidence only" in DECISION_NORMALIZED
    assert "they are not required final composition or mutation topology." in DECISION_NORMALIZED
    assert "not by a fixed lineage-size geometry" in DECISION_NORMALIZED
    assert "not a fixed `37 x 3` topology" in LIFECYCLE_NORMALIZED


def test_review_rejection_removes_eligibility() -> None:
    assert "REJECTION=REMOVE_FROM_FINAL_ELIGIBILITY" in DECISION
    assert "removed from final eligibility" in DECISION.lower()
    assert "rejection removes that candidate from final eligibility" in LIFECYCLE_NORMALIZED
    assert "never reclassified as `public_development`" in DECISION_NORMALIZED


def test_mutation_parent_provenance_does_not_require_coselection() -> None:
    assert "MUTATION_PARENT_PROVENANCE=REQUIRED" in DECISION
    assert "MUTATION_PARENT_CO_SELECTION=NO" in DECISION
    assert "MUTATION_RELATED_SELECTED_MEMBERS=SAME_SPLIT" in DECISION
    assert "MUTATION_CELL_INHERITANCE=KEEP_SAME_CELL_BY_DEFAULT" in DECISION
    assert "parent co-selection is not required" in LIFECYCLE_NORMALIZED


def test_critical_minimum_and_pool_reserve_are_distinct() -> None:
    assert "CRITICAL_FINAL_MINIMUM=DR001" in DECISION
    assert "CRITICAL_POOL_POLICY=INDEPENDENT_RESERVE_BEFORE_FINAL_SELECTION" in DECISION
    assert "does not add a new dr-001 final-count requirement" in DECISION_NORMALIZED
    assert "does not increase the final critical minimum in dr-001" in LIFECYCLE_NORMALIZED
    assert "CRITICAL_FINAL_MINIMUM=DR001" in SUPERSESSION


def test_pse_v1_claim_ceiling_is_preserved() -> None:
    assert "PSE_V1_ROLE=COVERAGE_PLUS_ADVERSARIAL_EXAM" in DECISION
    assert "PSE_V1_PRIMARY_ROLE=SCIENTIFIC_CAPABILITY_COVERAGE_EXAM" in DECISION
    assert "PSE_V1_SECONDARY_ROLE=ADVERSARIAL_SCIENTIFIC_BEHAVIOR_EXAM" in DECISION
    assert "HIGH_PRECISION_CELL_PERFORMANCE_CLAIM=NOT_AUTHORIZED" in DECISION
    assert "FINE_GRAINED_MODEL_RANKING_CLAIM=NOT_AUTHORIZED" in DECISION
    assert (
        "does not authorize high-precision cell-level performance estimates" in LIFECYCLE_NORMALIZED
    )
    assert "PSE_V1_CLAIM_CEILING=COVERAGE_PLUS_ADVERSARIAL" in SUPERSESSION


def test_solver_materialization_and_protected_stores_are_out_of_scope() -> None:
    assert "PRODUCTION_SOLVER_CHANGED=NO" in DECISION
    assert "CANDIDATE_CONTENT_CHANGED=NO" in DECISION
    assert "MATERIALIZATION_RUN=NO" in DECISION
    assert "PROTECTED_STORES_MODIFIED=NO" in DECISION
    assert "does not implement that solver or materialize candidates" in LIFECYCLE_NORMALIZED


def test_supersession_map_covers_required_prior_missions() -> None:
    for mission in ("RES-126", "RES-223", "RES-225", "RES-249", "RES-252"):
        assert f"| {mission} " in SUPERSESSION
