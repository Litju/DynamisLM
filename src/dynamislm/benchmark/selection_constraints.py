"""Build the single RES-258 final-selection constraint vocabulary."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping

from dynamislm.benchmark.authoring import parse_production_seed_namespace
from dynamislm.benchmark.constants import (
    BENCHMARK_SEMANTIC_VERSION,
    CRITICAL_ERROR_CLASSES,
    SPLIT_ORDER,
    CaseOrigin,
    ExpectedAnswerKind,
    SplitName,
)
from dynamislm.benchmark.contracts import ContaminationBinding
from dynamislm.benchmark.coverage import COVERAGE_MATRIX, coverage_manifest_digest
from dynamislm.benchmark.production import (
    ProductionAuthoringPlanItemV1,
    ProductionCandidateCommitmentV1,
    _feasibility_row_eligible,
)
from dynamislm.benchmark.selection_contracts import (
    AllocationCluster,
    BalanceDimension,
    ConstraintKind,
    FeatureKind,
    FinalSelectionCandidate,
    FinalSelectionProblem,
    IsolationIdentity,
    IsolationIdentityKind,
    MutationParentProvenance,
    ObjectiveKind,
    RelationKind,
    ReviewEligibility,
    SelectionBalanceCell,
    SelectionConstraint,
    SelectionConstraintSet,
    SelectionFeature,
    SelectionObjective,
)
from dynamislm.serialization import canonical_hash

FINAL_SELECTION_AUTHORITY_VERSION = "RES258-FINAL-SELECTION@1.0.0"
RES258_AUTHORITY_COMMIT = "7e4e5de28d510c1d6bb9a0dda93ed49685594f30"
RES258_AUTHORITY_DOCUMENT_SHA256 = (
    "sha256:2d98c68ea2e75d598efbb66568a0f1e304aa13a77db690e598f0dce231f4dfac"
)
DR001_DOCUMENT_SHA256 = "sha256:857ed5f1833f3404d3dd6df1a0340c6daac916ebe4f283dccd2409710ddf148e"
FINAL_CASE_COUNT = 434
FINAL_SPLIT_COUNTS: tuple[tuple[SplitName, int], ...] = (
    (SplitName.PUBLIC_DEVELOPMENT, 260),
    (SplitName.FROZEN_VALIDATION, 87),
    (SplitName.HIDDEN_FINAL, 87),
)
_ORIGIN_BOUNDS = (
    (CaseOrigin.EXPERT_AUTHORED_SEMANTIC, 0, 240),
    (CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION, 40, FINAL_CASE_COUNT),
    (CaseOrigin.DETERMINISTIC_ENGINE_DERIVED, 30, FINAL_CASE_COUNT),
    (CaseOrigin.DETERMINISTIC_SYNTHETIC, 12, FINAL_CASE_COUNT),
    (CaseOrigin.ADVERSARIAL_MUTATION, 60, FINAL_CASE_COUNT),
)
_AUTHORITY_DIGEST = canonical_hash(
    {
        "version": FINAL_SELECTION_AUTHORITY_VERSION,
        "res258_commit": RES258_AUTHORITY_COMMIT,
        "res258_document": RES258_AUTHORITY_DOCUMENT_SHA256,
        "dr001_document": DR001_DOCUMENT_SHA256,
        "coverage_matrix": coverage_manifest_digest(),
        "final_n": FINAL_CASE_COUNT,
        "split_counts": FINAL_SPLIT_COUNTS,
        "origin_bounds": _ORIGIN_BOUNDS,
        "critical_error_classes": CRITICAL_ERROR_CLASSES,
    }
)


def _review_eligibility(value: ReviewEligibility | str) -> ReviewEligibility:
    raw = getattr(value, "value", value)
    statuses = {
        "APPROVED": ReviewEligibility.APPROVED,
        "REJECTED": ReviewEligibility.REJECTED,
        "PENDING": ReviewEligibility.PENDING,
        "PENDING_HUMAN_REVIEW": ReviewEligibility.PENDING,
        "UNAPPROVED": ReviewEligibility.UNAPPROVED,
        "INVALID": ReviewEligibility.INVALID,
    }
    return statuses.get(str(raw), ReviewEligibility.INVALID)


def _balance_cells(
    item: ProductionAuthoringPlanItemV1, features: set[SelectionFeature]
) -> tuple[SelectionBalanceCell, ...]:
    critical_eligible = any(feature.kind is FeatureKind.CRITICAL_ERROR for feature in features)
    values = [
        SelectionBalanceCell(BalanceDimension.CAPABILITY, (item.capability_id,)),
        SelectionBalanceCell(BalanceDimension.FAMILY, (item.benchmark_family,)),
        SelectionBalanceCell(
            BalanceDimension.QUESTION_CLASS, (item.practitioner_question_class.value,)
        ),
        SelectionBalanceCell(
            BalanceDimension.ANSWER_OUTCOME,
            ("REFUSAL" if item.expected_answer_kind is ExpectedAnswerKind.REFUSAL else "ANSWER",),
        ),
        SelectionBalanceCell(BalanceDimension.ORIGIN, (item.origin_class.value,)),
        SelectionBalanceCell(BalanceDimension.DIFFICULTY, (item.difficulty.value,)),
        SelectionBalanceCell(
            BalanceDimension.CRITICAL_ERROR_ELIGIBILITY,
            ("ELIGIBLE" if critical_eligible else "NOT_ELIGIBLE",),
        ),
    ]
    values.extend(
        SelectionBalanceCell(BalanceDimension.TAG_CELL, (item.capability_id, tag))
        for tag in item.adversarial_tags
    )
    return tuple(sorted(set(values), key=lambda cell: (cell.dimension.value, cell.key)))


def selection_candidate_from_commitment(
    commitment: ProductionCandidateCommitmentV1,
    *,
    review_eligibility: ReviewEligibility | str,
    contamination: ContaminationBinding,
    mutation_parent_payload_hash: str | None = None,
    qualification_excluded: bool = False,
) -> FinalSelectionCandidate:
    """Adapt a validated, payload-free commitment to the selection vocabulary."""

    item = commitment.item
    row = next(row for row in COVERAGE_MATRIX if row.capability_id == item.capability_id)
    eligible = _feasibility_row_eligible(item, row)
    features: set[SelectionFeature] = set()
    if eligible:
        features.update(
            SelectionFeature(FeatureKind.ROW_TAG, (item.capability_id, tag))
            for tag in item.adversarial_tags
            if tag in row.adversarial_tags
        )
        features.update(
            SelectionFeature(FeatureKind.ROW_ERROR, (item.capability_id, error.value))
            for error in item.reachable_error_classes
            if error in row.error_classes
        )
        if set(item.adversarial_tags).intersection(row.adversarial_tags) and set(
            item.reachable_error_classes
        ).intersection(row.error_classes):
            features.add(
                SelectionFeature(FeatureKind.CELL, (item.capability_id, item.benchmark_family))
            )
        features.update(
            SelectionFeature(FeatureKind.CRITICAL_ERROR, (error.value,))
            for error in item.reachable_error_classes
            if error in CRITICAL_ERROR_CLASSES
        )
    if (
        item.capability_id == "C18"
        and eligible
        and item.refusal_decision.value == "REQUIRED"
        and item.expected_answer_kind is ExpectedAnswerKind.REFUSAL
        and item.safe_partial_support
    ):
        features.add(SelectionFeature(FeatureKind.C18_REFUSAL, (item.benchmark_family,)))
    if (
        item.refusal_decision.value != "REQUIRED"
        and item.expected_answer_kind is not ExpectedAnswerKind.REFUSAL
    ):
        features.add(SelectionFeature(FeatureKind.ANSWERABLE))

    identities: set[IsolationIdentity] = {
        IsolationIdentity(IsolationIdentityKind.SOURCE_FAMILY, item.source_family_id)
    }
    for kind, values in (
        (IsolationIdentityKind.SOURCE_DOCUMENT, item.source_document_ids),
        (IsolationIdentityKind.SOURCE_ARTIFACT, item.source_artifact_ids),
        (IsolationIdentityKind.CONSTRUCT_TEST, item.construct_test_identity_ids),
        (IsolationIdentityKind.PROVIDER_EXPORT, item.provider_export_ids),
        (IsolationIdentityKind.PROTOCOL_TEMPLATE, item.protocol_template_ids),
    ):
        identities.update(IsolationIdentity(kind, value) for value in values)
    if item.engine_reference_case_id is not None:
        identities.add(
            IsolationIdentity(
                IsolationIdentityKind.RES71_ENGINE_REFERENCE_CASE,
                item.engine_reference_case_id,
            )
        )
    for kind, value in (
        (IsolationIdentityKind.EXPERT_AUTHOR_BATCH, item.expert_author_batch_id),
        (IsolationIdentityKind.GENERATOR_FAMILY, item.generator_family),
        (IsolationIdentityKind.GENERATOR_SEED_NAMESPACE, item.seed_namespace),
        (IsolationIdentityKind.GENERATOR_SEED_BLOCK, item.seed_block),
        (IsolationIdentityKind.MUTATION_LINEAGE, item.mutation_lineage_id),
        (IsolationIdentityKind.MUTATION_PARENT, item.parent_candidate_id),
    ):
        if value is not None:
            identities.add(IsolationIdentity(kind, value))
    contamination_identities = contamination_isolation_identities(contamination)
    identities.update(contamination_identities)
    seed_blocks = {item.seed_block} if item.seed_block else set()
    seed_blocks.update(
        identity.identity
        for identity in contamination_identities
        if identity.kind is IsolationIdentityKind.GENERATOR_SEED_BLOCK
    )
    split_lock = (
        parse_production_seed_namespace(item.seed_namespace or "").split_name
        if item.origin_class is CaseOrigin.DETERMINISTIC_SYNTHETIC
        else None
    )
    balance = _balance_cells(item, features)
    return FinalSelectionCandidate(
        candidate_id=item.candidate_id,
        payload_hash=commitment.candidate_payload_hash,
        origin_class=item.origin_class,
        review_eligibility=_review_eligibility(review_eligibility),
        features=tuple(sorted(features, key=lambda feature: (feature.kind.value, feature.key))),
        balance_cells=balance,
        isolation_cluster_id=item.isolation_cluster_id,
        allocation_stratum=item.allocation_stratum,
        isolation_identities=tuple(
            sorted(
                identities,
                key=lambda identity: (identity.kind.value, identity.identity.encode()),
            )
        ),
        exact_shingle_digests=(contamination.exact_shingle_digest,),
        generator_seed_blocks=tuple(sorted(seed_blocks, key=str.encode)),
        mutation_lineage_id=item.mutation_lineage_id,
        mutation_parent_candidate_id=item.parent_candidate_id,
        mutation_parent_payload_hash=mutation_parent_payload_hash,
        cell=(item.capability_id, item.benchmark_family),
        locked_split=split_lock,
        qualification_excluded=qualification_excluded,
    )


def contamination_isolation_identities(
    contamination: ContaminationBinding,
) -> tuple[IsolationIdentity, ...]:
    """Retain DR-001 contamination identities not carried by the plan-item projection."""

    values = {
        IsolationIdentity(IsolationIdentityKind.SOURCE_FAMILY, contamination.source_family_id)
    }
    for kind, entries in (
        (IsolationIdentityKind.SOURCE_DOCUMENT, contamination.document_ids),
        (IsolationIdentityKind.SOURCE_ARTIFACT, contamination.source_artifact_ids),
        (IsolationIdentityKind.GENERAL_ARTIFACT, contamination.artifact_ids),
        (IsolationIdentityKind.BENCHMARK_ARTIFACT, contamination.benchmark_artifact_ids),
        (IsolationIdentityKind.TRAINING_EXCLUSION, contamination.training_exclusion_ids),
        (IsolationIdentityKind.CONSTRUCT_TEST, contamination.construct_test_identity_ids),
    ):
        values.update(IsolationIdentity(kind, value) for value in entries)
    for kind, value in (
        (IsolationIdentityKind.PROVIDER_EXPORT, contamination.provider_export_id),
        (IsolationIdentityKind.PROTOCOL_TEMPLATE, contamination.protocol_template_id),
        (IsolationIdentityKind.EXPERT_AUTHOR_BATCH, contamination.expert_author_batch_id),
        (IsolationIdentityKind.GENERATOR_SEED_NAMESPACE, contamination.generator_namespace),
        (IsolationIdentityKind.GENERATOR_SEED_BLOCK, contamination.generator_seed_block),
    ):
        if value is not None:
            values.add(IsolationIdentity(kind, value))
    return tuple(
        sorted(values, key=lambda identity: (identity.kind.value, identity.identity.encode()))
    )


def _feature_constraints() -> list[SelectionConstraint]:
    values: list[SelectionConstraint] = []

    def require(feature: SelectionFeature, split: SplitName, authority: str) -> None:
        feature_id = ":".join((feature.kind.value, *feature.key)) or feature.kind.value
        values.append(
            SelectionConstraint(
                constraint_id=f"{authority}:{feature_id}:{split.value}",
                authority_ref=authority,
                kind=ConstraintKind.FEATURE_MINIMUM,
                feature=feature,
                split=split,
                minimum=1,
            )
        )

    for row in COVERAGE_MATRIX:
        for split in row.split_coverage:
            for family in row.benchmark_families:
                require(
                    SelectionFeature(FeatureKind.CELL, (row.capability_id, family)),
                    split,
                    "DR-001 §12, §15.3",
                )
            for tag in row.adversarial_tags:
                require(
                    SelectionFeature(FeatureKind.ROW_TAG, (row.capability_id, tag)),
                    split,
                    "DR-001 §15.3",
                )
            for error in row.error_classes:
                require(
                    SelectionFeature(FeatureKind.ROW_ERROR, (row.capability_id, error.value)),
                    split,
                    "DR-001 §15.2, §15.3",
                )
            if row.capability_id == "C18":
                for family in row.benchmark_families:
                    require(
                        SelectionFeature(FeatureKind.C18_REFUSAL, (family,)),
                        split,
                        "DR-001 §12, C18 refusal coverage",
                    )
    for split in SPLIT_ORDER:
        require(SelectionFeature(FeatureKind.ANSWERABLE), split, "DR-001 §7.2")
    for split in (SplitName.FROZEN_VALIDATION, SplitName.HIDDEN_FINAL):
        for error in CRITICAL_ERROR_CLASSES:
            require(
                SelectionFeature(FeatureKind.CRITICAL_ERROR, (error.value,)),
                split,
                "DR-001 §5, §12, §15.3",
            )
    return values


def _relation_id(kind: RelationKind, identity: object) -> str:
    digest = canonical_hash({"relation": kind, "identity": identity}).removeprefix("sha256:")
    return digest[:24]


def _allocation_clusters(
    candidates: tuple[FinalSelectionCandidate, ...],
) -> tuple[AllocationCluster, ...]:
    grouped: dict[str, list[FinalSelectionCandidate]] = defaultdict(list)
    for candidate in candidates:
        if (
            candidate.review_eligibility is ReviewEligibility.APPROVED
            and not candidate.qualification_excluded
        ):
            grouped[candidate.isolation_cluster_id].append(candidate)
    clusters: list[AllocationCluster] = []
    for cluster_id, members in grouped.items():
        ordered = tuple(sorted(members, key=lambda item: item.candidate_id.encode()))
        seed_blocks = tuple(
            sorted(
                {block for item in ordered for block in item.generator_seed_blocks},
                key=lambda value: value.encode(),
            )
        )
        key = canonical_hash(
            {
                "benchmark_version": BENCHMARK_SEMANTIC_VERSION,
                "isolation_cluster_id": cluster_id,
                "member_case_keys": tuple(
                    {
                        "case_id": item.candidate_id,
                        "case_payload_hash": item.payload_hash,
                    }
                    for item in ordered
                ),
                "allocation_strata": tuple(sorted({item.allocation_stratum for item in ordered})),
                "origin_classes": tuple(sorted({item.origin_class.value for item in ordered})),
                "generator_seed_blocks": seed_blocks,
            }
        )
        rank = int(key.removeprefix("sha256:"), 16) % len(SPLIT_ORDER)
        clusters.append(
            AllocationCluster(
                cluster_id=cluster_id,
                candidate_ids=tuple(item.candidate_id for item in ordered),
                cluster_key=key,
                preferred_split=SPLIT_ORDER[rank],
            )
        )
    return tuple(sorted(clusters, key=lambda item: item.cluster_id.encode()))


def build_final_selection_problem(
    candidates: tuple[FinalSelectionCandidate, ...],
    *,
    parent_provenance_registry: tuple[MutationParentProvenance, ...] = (),
) -> FinalSelectionProblem:
    """Bind RES-258 and DR-001 hard rules and split objectives once."""

    candidate_ids = {candidate.candidate_id for candidate in candidates}
    constraints = [
        SelectionConstraint(
            constraint_id=f"RES369:ONE_STATE:{candidate.candidate_id}",
            authority_ref="RES-369 one four-state assignment per candidate",
            kind=ConstraintKind.ONE_STATE_PER_CANDIDATE,
            candidate_ids=(candidate.candidate_id,),
        )
        for candidate in candidates
    ]
    constraints.extend(
        (
            SelectionConstraint(
                constraint_id="RES258:FINAL_SELECTED_N",
                authority_ref="RES-258 final selection",
                kind=ConstraintKind.FINAL_COUNT,
                minimum=FINAL_CASE_COUNT,
                maximum=FINAL_CASE_COUNT,
            ),
            *(
                SelectionConstraint(
                    constraint_id=f"RES258:SPLIT_COUNT:{split.value}",
                    authority_ref="RES-258 final split counts",
                    kind=ConstraintKind.SPLIT_COUNT,
                    split=split,
                    minimum=count,
                    maximum=count,
                )
                for split, count in FINAL_SPLIT_COUNTS
            ),
            *(
                SelectionConstraint(
                    constraint_id=f"RES126:ORIGIN:{origin.value}",
                    authority_ref="RES-126 selected-origin bounds, frozen by RES-258",
                    kind=ConstraintKind.ORIGIN_BOUNDS,
                    origin_class=origin,
                    minimum=minimum,
                    maximum=maximum,
                )
                for origin, minimum, maximum in _ORIGIN_BOUNDS
            ),
            SelectionConstraint(
                constraint_id="RES258:MUTATION_LINEAGES_MINIMUM",
                authority_ref="RES-258 final composition",
                kind=ConstraintKind.MUTATION_LINEAGE_MINIMUM,
                minimum=20,
            ),
        )
    )
    constraints.extend(_feature_constraints())

    for candidate in candidates:
        if candidate.review_eligibility is not ReviewEligibility.APPROVED:
            constraints.append(
                SelectionConstraint(
                    constraint_id=f"RES258:REVIEW_OUT:{candidate.candidate_id}",
                    authority_ref="RES-258 review eligibility",
                    kind=ConstraintKind.REVIEW_OUT_ONLY,
                    candidate_ids=(candidate.candidate_id,),
                    reason=candidate.review_eligibility.value,
                )
            )
        if candidate.qualification_excluded:
            constraints.append(
                SelectionConstraint(
                    constraint_id=f"DR001:QUALIFICATION_OUT:{candidate.candidate_id}",
                    authority_ref="DR-001 qualification exclusion",
                    kind=ConstraintKind.QUALIFICATION_OUT_ONLY,
                    candidate_ids=(candidate.candidate_id,),
                    reason="QUALIFICATION_EXCLUDED",
                )
            )
        if candidate.locked_split is not None:
            constraints.append(
                SelectionConstraint(
                    constraint_id=f"DR001:SYNTHETIC_LOCK:{candidate.candidate_id}",
                    authority_ref="DR-001 §7.2 synthetic seed lock",
                    kind=ConstraintKind.SYNTHETIC_SPLIT_LOCK,
                    candidate_ids=(candidate.candidate_id,),
                    locked_split=candidate.locked_split,
                )
            )
        if candidate.mutation_lineage_id is not None:
            constraints.append(
                SelectionConstraint(
                    constraint_id=f"RES258:MUTATION_PARENT_PROVENANCE:{candidate.candidate_id}",
                    authority_ref="RES-258 mutation parent provenance",
                    kind=ConstraintKind.MUTATION_PARENT_PROVENANCE,
                    candidate_ids=(candidate.candidate_id,),
                    related_id=candidate.mutation_parent_candidate_id,
                    related_payload_hash=candidate.mutation_parent_payload_hash,
                )
            )
            constraints.append(
                SelectionConstraint(
                    constraint_id=f"RES258:MUTATION_CELL_INHERITANCE:{candidate.candidate_id}",
                    authority_ref="RES-258 mutation cell inheritance default",
                    kind=ConstraintKind.MUTATION_PARENT_CELL_INHERITANCE,
                    candidate_ids=(candidate.candidate_id,),
                    related_id=candidate.mutation_parent_candidate_id,
                    reason=candidate.mutation_cell_exception_authority_ref,
                )
            )

    relation_groups: dict[tuple[RelationKind, str], set[str]] = defaultdict(set)
    for candidate in candidates:
        relation_groups[(RelationKind.ISOLATION_CLUSTER, candidate.isolation_cluster_id)].add(
            candidate.candidate_id
        )
        for identity in candidate.isolation_identities:
            relation_groups[
                (
                    RelationKind.ISOLATION_IDENTITY,
                    f"{identity.kind.value}\0{identity.identity}",
                )
            ].add(candidate.candidate_id)
        if candidate.mutation_lineage_id:
            relation_groups[(RelationKind.MUTATION_LINEAGE, candidate.mutation_lineage_id)].add(
                candidate.candidate_id
            )
        for digest in candidate.exact_shingle_digests:
            relation_groups[(RelationKind.EXACT_SHINGLE, digest)].add(candidate.candidate_id)
        if candidate.mutation_parent_candidate_id in candidate_ids:
            pair = tuple(
                sorted(
                    (candidate.candidate_id, candidate.mutation_parent_candidate_id),
                    key=str.encode,
                )
            )
            relation_groups[(RelationKind.MUTATION_PARENT, "\0".join(pair))].update(pair)
    for (kind, identity_key), members in relation_groups.items():
        if len(members) >= 2:
            member_ids = tuple(sorted(members, key=str.encode))
            constraints.append(
                SelectionConstraint(
                    constraint_id=(
                        f"DR001:CONDITIONAL_COLOCATION:{kind.value}:"
                        f"{_relation_id(kind, identity_key)}"
                    ),
                    authority_ref=(
                        "RES-71 reference identity; RES-258/RES-369 isolation authority"
                        if kind is RelationKind.ISOLATION_IDENTITY
                        and identity_key.partition("\0")[0]
                        == IsolationIdentityKind.RES71_ENGINE_REFERENCE_CASE.value
                        else (
                            "RES-258 mutation relation semantics"
                            if kind in {RelationKind.MUTATION_LINEAGE, RelationKind.MUTATION_PARENT}
                            else "DR-001 §7.2 isolation and exact-shingle semantics"
                        )
                    ),
                    kind=ConstraintKind.CONDITIONAL_COLOCATION,
                    candidate_ids=member_ids,
                    relation_kind=kind,
                )
            )

    constraint_set = SelectionConstraintSet(
        constraints=tuple(sorted(constraints, key=lambda item: item.constraint_id.encode())),
        objectives=(
            SelectionObjective(
                "DR001:PROPORTIONAL_SPLIT_BALANCE",
                "DR-001 §7.2 proportional-imbalance objective",
                ObjectiveKind.PROPORTIONAL_SPLIT_BALANCE,
            ),
            SelectionObjective(
                "DR001:HASH_CLUSTER_PREFERENCE",
                "DR-001 §7.2 deterministic cluster preference",
                ObjectiveKind.HASH_CLUSTER_PREFERENCE,
            ),
            SelectionObjective(
                "RES369:CANONICAL_ASSIGNMENT",
                "RES-369 canonical plan requirement",
                ObjectiveKind.CANONICAL_ASSIGNMENT,
            ),
        ),
        allocation_clusters=_allocation_clusters(candidates),
    )
    return FinalSelectionProblem(
        candidates=candidates,
        constraint_set=constraint_set,
        authority_digest=_AUTHORITY_DIGEST,
        parent_provenance_registry=parent_provenance_registry,
    )


def build_final_selection_problem_from_commitments(
    commitments: tuple[ProductionCandidateCommitmentV1, ...],
    *,
    review_eligibility: Mapping[str, ReviewEligibility | str],
    contamination_bindings: Mapping[str, ContaminationBinding],
    parent_provenance_registry: tuple[MutationParentProvenance, ...] = (),
    qualification_excluded_candidate_ids: frozenset[str] = frozenset(),
) -> FinalSelectionProblem:
    """Build final-selection contracts from an approved-pool commitment set."""

    by_id = {item.candidate_id: item for item in commitments}
    if len(by_id) != len(commitments):
        raise ValueError("production commitments contain duplicate candidate IDs")
    candidate_ids = set(by_id)
    if set(contamination_bindings) != candidate_ids:
        raise ValueError("every candidate requires its complete contamination binding")
    if not qualification_excluded_candidate_ids.issubset(candidate_ids):
        raise ValueError("qualification exclusion references a candidate outside the pool")
    external = {item.candidate_id: item.payload_hash for item in parent_provenance_registry}
    candidates: list[FinalSelectionCandidate] = []
    for commitment in commitments:
        item = commitment.item
        parent_hash = None
        if item.parent_candidate_id is not None:
            parent = by_id.get(item.parent_candidate_id)
            parent_hash = (
                parent.candidate_payload_hash
                if parent is not None
                else external.get(item.parent_candidate_id)
            )
        candidates.append(
            selection_candidate_from_commitment(
                commitment,
                review_eligibility=review_eligibility.get(
                    item.candidate_id, ReviewEligibility.UNAPPROVED
                ),
                contamination=contamination_bindings[item.candidate_id],
                mutation_parent_payload_hash=parent_hash,
                qualification_excluded=item.candidate_id in qualification_excluded_candidate_ids,
            )
        )
    return build_final_selection_problem(
        tuple(candidates), parent_provenance_registry=parent_provenance_registry
    )


__all__ = [
    "FINAL_CASE_COUNT",
    "FINAL_SELECTION_AUTHORITY_VERSION",
    "FINAL_SPLIT_COUNTS",
    "build_final_selection_problem",
    "build_final_selection_problem_from_commitments",
    "contamination_isolation_identities",
    "selection_candidate_from_commitment",
]
