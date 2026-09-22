"""Exact deterministic split allocation for PerformanceScience-Eval V1."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, replace

from dynamislm.benchmark.constants import (
    BENCHMARK_SEMANTIC_VERSION,
    SPLIT_ORDER,
    SPLIT_PROPORTIONS,
    SplitName,
)
from dynamislm.benchmark.contracts import BenchmarkCaseV1
from dynamislm.benchmark.coverage import CoverageRow
from dynamislm.benchmark.hashing import case_payload_hash
from dynamislm.benchmark.validation import validate_case_set
from dynamislm.serialization import canonical_hash


class SplitAllocationBlocked(ValueError):  # noqa: N818 - public contract name is descriptive
    """Raised when the frozen exact allocation has no valid solution."""


@dataclass(frozen=True, slots=True)
class SplitAllocationResult:
    cases: tuple[BenchmarkCaseV1, ...]
    target_counts: Mapping[SplitName, int]
    balance_cost: int
    hash_preference_cost: int
    cluster_assignments: tuple[tuple[str, SplitName], ...]

    def __post_init__(self) -> None:
        if not self.cases:
            raise ValueError("split allocation result cannot be empty")
        if set(self.target_counts) != set(SPLIT_ORDER):
            raise ValueError("split allocation result must contain all V1 splits")
        if self.balance_cost < 0 or self.hash_preference_cost < 0:
            raise ValueError("allocation costs must be non-negative")


@dataclass(frozen=True, slots=True)
class _Cluster:
    isolation_cluster_id: str
    member_indices: tuple[int, ...]
    member_case_keys: tuple[tuple[str, str], ...]
    allocation_strata: tuple[str, ...]
    origin_classes: tuple[str, ...]
    generator_seed_blocks: tuple[str, ...]
    cluster_key: str
    preferred_rank: int

    @property
    def size(self) -> int:
        return len(self.member_indices)


def target_counts(case_count: int) -> dict[SplitName, int]:
    """Apply the exact floor/remainder rule from Section 7.2."""

    if isinstance(case_count, bool) or case_count <= 0:
        raise SplitAllocationBlocked("N must be positive")
    floors: dict[SplitName, int] = {}
    remainders: dict[SplitName, int] = {}
    for split in SPLIT_ORDER:
        numerator, denominator = SPLIT_PROPORTIONS[split]
        product = case_count * numerator
        floors[split] = product // denominator
        remainders[split] = product % denominator
    remaining = case_count - sum(floors.values())
    order = sorted(
        SPLIT_ORDER,
        key=lambda split: (-remainders[split], SPLIT_ORDER.index(split)),
    )
    for split in order[:remaining]:
        floors[split] += 1
    if sum(floors.values()) != case_count:
        raise SplitAllocationBlocked("split target counts do not sum to N")
    return floors


def _isolation_values(case: BenchmarkCaseV1) -> tuple[str, ...]:
    contamination = case.contamination
    provenance = case.provenance
    values = (
        f"source-family:{contamination.source_family_id}",
        f"provider-export:{contamination.provider_export_id}"
        if contamination.provider_export_id
        else "",
        f"protocol-template:{contamination.protocol_template_id}"
        if contamination.protocol_template_id
        else "",
        f"expert-author-batch:{contamination.expert_author_batch_id}"
        if contamination.expert_author_batch_id
        else "",
        f"generator-family:{provenance.generator_family}" if provenance.generator_family else "",
        f"mutation-lineage:{provenance.mutation_lineage_id}"
        if provenance.mutation_lineage_id
        else "",
        f"seed-namespace:{provenance.seed_namespace}" if provenance.seed_namespace else "",
        f"seed-block:{provenance.seed_block}" if provenance.seed_block else "",
    )
    return tuple(item for item in values if item)


def _union_find_clusters(cases: tuple[BenchmarkCaseV1, ...]) -> tuple[_Cluster, ...]:
    parent = list(range(len(cases)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        root_left = find(left)
        root_right = find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    seen: dict[str, int] = {}
    for index, case in enumerate(cases):
        keys = (*_isolation_values(case), f"declared-cluster:{case.split.isolation_cluster_id}")
        for key in keys:
            prior = seen.get(key)
            if prior is not None:
                union(index, prior)
            else:
                seen[key] = index
    case_hash_indices = {case.case_payload_hash: index for index, case in enumerate(cases)}
    for index, case in enumerate(cases):
        parent_hash = case.provenance.parent_case_hash
        if parent_hash is not None:
            parent_index = case_hash_indices.get(parent_hash)
            if parent_index is None:
                raise SplitAllocationBlocked(f"mutation parent hash is absent for {case.case_id}")
            union(index, parent_index)

    groups: dict[int, list[int]] = defaultdict(list)
    for index in range(len(cases)):
        groups[find(index)].append(index)
    clusters: list[_Cluster] = []
    for indices in groups.values():
        ordered_indices = tuple(
            sorted(indices, key=lambda index: cases[index].case_id.encode("utf-8"))
        )
        declared_ids = tuple(
            sorted({cases[index].split.isolation_cluster_id for index in ordered_indices})
        )
        isolation_id = declared_ids[0]
        member_case_keys = tuple(
            (cases[index].case_id, cases[index].case_payload_hash) for index in ordered_indices
        )
        allocation_strata = tuple(
            sorted({cases[index].split.allocation_stratum for index in ordered_indices})
        )
        origin_classes = tuple(
            sorted({cases[index].provenance.origin_class.value for index in ordered_indices})
        )
        generator_seed_blocks = tuple(
            sorted(
                item
                for item in (cases[index].provenance.seed_block for index in ordered_indices)
                if item is not None
            )
        )
        cluster_input = {
            "benchmark_version": BENCHMARK_SEMANTIC_VERSION,
            "isolation_cluster_id": isolation_id,
            "member_case_keys": member_case_keys,
            "allocation_strata": allocation_strata,
            "origin_classes": origin_classes,
            "generator_seed_blocks": generator_seed_blocks,
        }
        cluster_key = canonical_hash(cluster_input).removeprefix("sha256:")
        clusters.append(
            _Cluster(
                isolation_cluster_id=isolation_id,
                member_indices=ordered_indices,
                member_case_keys=member_case_keys,
                allocation_strata=allocation_strata,
                origin_classes=origin_classes,
                generator_seed_blocks=generator_seed_blocks,
                cluster_key=cluster_key,
                preferred_rank=int(cluster_key, 16) % 3,
            )
        )
    return tuple(
        sorted(
            clusters,
            key=lambda cluster: (
                cluster.cluster_key.encode("utf-8"),
                cluster.isolation_cluster_id.encode("utf-8"),
            ),
        )
    )


def _soft_cells(case: BenchmarkCaseV1) -> tuple[str, ...]:
    outcome = "REFUSAL" if case.refusal_expectation.decision.value == "REQUIRED" else "ANSWER"
    errors = tuple(item.value for item in case.scoring_contract.error_class_rules)
    cells = [
        f"capability:{case.capability_id}",
        f"family:{case.benchmark_family}",
        f"question:{case.practitioner_question_class.value}",
        f"outcome:{outcome}",
        f"origin:{case.provenance.origin_class.value}",
        f"difficulty:{case.difficulty.level.value}",
    ]
    cells.extend(f"error:{error}" for error in errors)
    return tuple(cells)


def _assignment_cost(
    assignments: tuple[int, ...],
    clusters: tuple[_Cluster, ...],
    cases: tuple[BenchmarkCaseV1, ...],
    targets: Mapping[SplitName, int],
) -> tuple[int, int]:
    total = len(cases)
    target_by_rank = tuple(targets[split] for split in SPLIT_ORDER)
    dimensions: dict[str, int] = defaultdict(int)
    per_split: list[dict[str, int]] = [defaultdict(int) for _ in SPLIT_ORDER]
    for cluster, rank in zip(clusters, assignments, strict=True):
        for index in cluster.member_indices:
            for cell in _soft_cells(cases[index]):
                dimensions[cell] += 1
                per_split[rank][cell] += 1
    balance = 0
    for cell, cell_total in dimensions.items():
        for rank in range(3):
            balance += abs(total * per_split[rank][cell] - target_by_rank[rank] * cell_total)
    hash_cost = sum(
        cluster.size
        for cluster, rank in zip(clusters, assignments, strict=True)
        if rank != cluster.preferred_rank
    )
    return balance, hash_cost


def _row_eligible(case: BenchmarkCaseV1, row: CoverageRow, family: str | None = None) -> bool:
    """Avoid making the allocator depend on mutable labels or heuristics."""

    # ``CoverageRow`` is intentionally duck-typed here so the allocator keeps
    # the coverage matrix as the single source of row policy.
    return (
        case.capability_id == row.capability_id
        and (family is None or case.benchmark_family == family)
        and case.provenance.origin_class in row.case_origins
        and case.scoring_contract.profile_id in row.scorer_profiles
        and bool(
            {binding.authority_kind for binding in case.authority} & set(row.answer_authorities)
        )
    )


def _cluster_has_obligation(
    cluster: _Cluster,
    cases: tuple[BenchmarkCaseV1, ...],
    row: CoverageRow,
    family: str,
) -> bool:
    return any(
        _row_eligible(cases[index], row, family)
        and bool(set(cases[index].adversarial_tags) & set(row.adversarial_tags))
        and bool(set(cases[index].scoring_contract.error_class_rules) & set(row.error_classes))
        for index in cluster.member_indices
    )


def _build_coverage_anchors(
    cases: tuple[BenchmarkCaseV1, ...],
    clusters: tuple[_Cluster, ...],
    targets: Mapping[SplitName, int],
) -> dict[int, int]:
    """Reserve deterministic atomic clusters for the frozen hard coverage contract."""

    from dynamislm.benchmark.coverage import COVERAGE_MATRIX

    assignments: dict[int, int] = {}
    counts = [0, 0, 0]

    requirements = [
        (rank, row, family)
        for rank in range(3)
        for row in COVERAGE_MATRIX
        for family in row.benchmark_families
    ]
    requirements.sort(
        key=lambda item: (
            sum(
                1
                for cluster in clusters
                if _cluster_has_obligation(cluster, cases, item[1], item[2])
            ),
            item[0],
            item[1].capability_id,
            item[2],
        )
    )

    def assigned_cases(rank: int) -> tuple[BenchmarkCaseV1, ...]:
        return tuple(
            cases[index]
            for cluster_index, chosen_rank in assignments.items()
            if chosen_rank == rank
            for index in clusters[cluster_index].member_indices
        )

    for rank, row, family in requirements:
        if any(
            _cluster_has_obligation(clusters[cluster_index], cases, row, family)
            for cluster_index, chosen_rank in assignments.items()
            if chosen_rank == rank
        ):
            continue
        candidates = [
            cluster_index
            for cluster_index, cluster in enumerate(clusters)
            if cluster_index not in assignments
            and counts[rank] + cluster.size <= targets[SPLIT_ORDER[rank]]
            and _cluster_has_obligation(cluster, cases, row, family)
        ]
        if not candidates:
            raise SplitAllocationBlocked(
                f"no atomic candidate can satisfy {row.capability_id}x{family} in "
                f"{SPLIT_ORDER[rank].value}"
            )

        def candidate_key(
            cluster_index: int,
            coverage_rank: int = rank,
        ) -> tuple[object, ...]:
            cluster = clusters[cluster_index]
            contribution = sum(
                _cluster_has_obligation(cluster, cases, other_row, other_family)
                for other_row in COVERAGE_MATRIX
                for other_family in other_row.benchmark_families
            )
            return (
                -contribution,
                cluster.size,
                0 if cluster.preferred_rank == coverage_rank else 1,
                cluster.cluster_key.encode("utf-8"),
                cluster.isolation_cluster_id.encode("utf-8"),
            )

        selected = min(candidates, key=candidate_key)
        assignments[selected] = rank
        counts[rank] += clusters[selected].size

    # Row-level tag/error coverage is separate from the one-intersection
    # obligation check. Add deterministic feature anchors until every row is
    # represented in each split.
    changed = True
    while changed:
        changed = False
        for rank in range(3):
            assigned = assigned_cases(rank)
            for row in COVERAGE_MATRIX:
                relevant = tuple(
                    case
                    for case in assigned
                    if any(_row_eligible(case, row, family) for family in row.benchmark_families)
                )
                represented_tags = {tag for case in relevant for tag in case.adversarial_tags}
                represented_errors = {
                    error for case in relevant for error in case.scoring_contract.error_class_rules
                }
                missing_features = [
                    ("tag", tag) for tag in row.adversarial_tags if tag not in represented_tags
                ] + [
                    ("error", error)
                    for error in row.error_classes
                    if error not in represented_errors
                ]
                if not missing_features:
                    continue
                feature_kind, feature = missing_features[0]
                candidates = [
                    cluster_index
                    for cluster_index, cluster in enumerate(clusters)
                    if cluster_index not in assignments
                    and counts[rank] + cluster.size <= targets[SPLIT_ORDER[rank]]
                    and any(
                        any(
                            _row_eligible(cases[index], row, family)
                            for family in row.benchmark_families
                        )
                        and (
                            feature in cases[index].adversarial_tags
                            if feature_kind == "tag"
                            else feature in cases[index].scoring_contract.error_class_rules
                        )
                        for index in cluster.member_indices
                    )
                ]
                if not candidates:
                    raise SplitAllocationBlocked(
                        f"no atomic candidate can satisfy {row.capability_id} {feature_kind} "
                        f"coverage in {SPLIT_ORDER[rank].value}"
                    )
                selected = min(
                    candidates,
                    key=lambda cluster_index: (
                        clusters[cluster_index].size,
                        0 if clusters[cluster_index].preferred_rank == rank else 1,
                        clusters[cluster_index].cluster_key.encode("utf-8"),
                        clusters[cluster_index].isolation_cluster_id.encode("utf-8"),
                    ),
                )
                assignments[selected] = rank
                counts[rank] += clusters[selected].size
                changed = True
                assigned = assigned_cases(rank)
    return assignments


def _fill_exact_counts(
    clusters: tuple[_Cluster, ...],
    anchored: Mapping[int, int],
    targets: Mapping[SplitName, int],
) -> tuple[int, ...]:
    """Find an exact atomic fill with bounded 2D dynamic programming."""

    target_by_rank = tuple(targets[split] for split in SPLIT_ORDER)
    counts = [0, 0, 0]
    for cluster_index, rank in anchored.items():
        counts[rank] += clusters[cluster_index].size
    if any(count > target for count, target in zip(counts, target_by_rank, strict=True)):
        raise SplitAllocationBlocked("coverage anchors exceed an exact split target")
    remaining = tuple(index for index in range(len(clusters)) if index not in anchored)
    deficits = tuple(target - count for target, count in zip(target_by_rank, counts, strict=True))
    if sum(deficits) != sum(clusters[index].size for index in remaining):
        raise SplitAllocationBlocked("coverage anchors do not leave the exact remaining case count")
    if not remaining:
        if any(deficits):
            raise SplitAllocationBlocked("coverage anchors cannot fill exact split counts")
        return tuple(anchored[index] for index in range(len(clusters)))
    if all(clusters[index].size == 1 for index in remaining):
        # The common benchmark-scale case is singleton isolation clusters. A
        # direct deficit fill is exact, deterministic, and avoids retaining a
        # quadratic predecessor table for a trivial partition.
        remaining_deficits = list(deficits)
        direct = dict(anchored)
        for cluster_index in remaining:
            cluster = clusters[cluster_index]
            rank_order = tuple(
                sorted(
                    range(3),
                    key=lambda rank: (
                        0 if rank == cluster.preferred_rank else 1,
                        rank,
                    ),
                )
            )
            selected = next((rank for rank in rank_order if remaining_deficits[rank] > 0), None)
            if selected is None:
                raise SplitAllocationBlocked("direct exact fill exhausted all split deficits")
            direct[cluster_index] = selected
            remaining_deficits[selected] -= 1
        if any(remaining_deficits):
            raise SplitAllocationBlocked("direct exact fill did not satisfy all split deficits")
        return tuple(direct[index] for index in range(len(clusters)))

    max_states = 250_000
    states: dict[tuple[int, int], tuple[tuple[int, int] | None, int | None]] = {
        (0, 0): (None, None)
    }
    layers: list[dict[tuple[int, int], tuple[tuple[int, int] | None, int | None]]] = [states]
    processed = 0
    for cluster_index in remaining:
        cluster = clusters[cluster_index]
        processed += cluster.size
        next_states: dict[tuple[int, int], tuple[tuple[int, int] | None, int | None]] = {}
        rank_order = tuple(
            sorted(
                range(3),
                key=lambda rank: (
                    0 if rank == cluster.preferred_rank else 1,
                    rank,
                ),
            )
        )
        for public_count, validation_count in sorted(states):
            for rank in rank_order:
                new_public = public_count + (cluster.size if rank == 0 else 0)
                new_validation = validation_count + (cluster.size if rank == 1 else 0)
                new_hidden = processed - new_public - new_validation
                if (
                    new_public > deficits[0]
                    or new_validation > deficits[1]
                    or new_hidden > deficits[2]
                ):
                    continue
                state = (new_public, new_validation)
                if state not in next_states:
                    next_states[state] = ((public_count, validation_count), rank)
        if not next_states:
            raise SplitAllocationBlocked("no exact atomic fill remains after coverage anchors")
        if len(next_states) > max_states:
            raise SplitAllocationBlocked(
                "bounded deterministic allocator state budget exceeded; allocation is unresolved"
            )
        states = next_states
        layers.append(states)
    final_state = (deficits[0], deficits[1])
    if final_state not in states:
        raise SplitAllocationBlocked("no exact atomic fill satisfies the split targets")
    chosen_remaining: dict[int, int] = {}
    state = final_state
    for layer_index in range(len(remaining), 0, -1):
        previous, chosen_rank = layers[layer_index][state]
        assert previous is not None and chosen_rank is not None
        chosen_remaining[remaining[layer_index - 1]] = chosen_rank
        state = previous
    assignments = dict(anchored)
    assignments.update(chosen_remaining)
    return tuple(assignments[index] for index in range(len(clusters)))


def _validate_full_coverage(
    cases: tuple[BenchmarkCaseV1, ...], assignments: tuple[int, ...], clusters: tuple[_Cluster, ...]
) -> None:
    from dynamislm.benchmark.coverage import validate_case_coverage

    assigned_cases = tuple(
        replace(
            cases[index],
            split=replace(
                cases[index].split,
                split_name=SPLIT_ORDER[rank],
                split_manifest_version=None,
                split_manifest_hash=None,
                membership_digest=None,
            ),
        )
        for cluster, rank in zip(clusters, assignments, strict=True)
        for index in cluster.member_indices
    )
    coverage = validate_case_coverage(assigned_cases, require_all_splits=True)
    if coverage.status != "PASS":
        raise SplitAllocationBlocked(
            "full acceptance-matrix coverage is missing: "
            f"cells={coverage.missing_cells[:3]}, "
            f"tags={coverage.missing_adversarial_tags[:3]}, "
            f"errors={coverage.missing_error_classes[:3]}"
        )


def allocate_splits(
    cases: tuple[BenchmarkCaseV1, ...],
    *,
    require_full_coverage: bool = False,
    contamination_audit_passed: bool = True,
) -> SplitAllocationResult:
    """Return a deterministic exact-count, atomic, coverage-safe allocation.

    ``require_full_coverage=False`` is intentional for the small infrastructure
    fixtures in this mission.  Final benchmark generation must pass ``True``;
    it fails closed until every matrix row is represented in every split.
    """

    if not contamination_audit_passed:
        raise SplitAllocationBlocked("mandatory contamination audit is unresolved")
    validate_case_set(cases)
    if any(case.split.split_name is not None for case in cases):
        raise SplitAllocationBlocked("allocator input must not contain pre-assigned splits")
    targets = target_counts(len(cases))
    clusters = _union_find_clusters(cases)
    if sum(cluster.size for cluster in clusters) != len(cases):
        raise SplitAllocationBlocked("isolation clusters do not cover every case")
    if any(cluster.size > max(targets.values()) for cluster in clusters):
        raise SplitAllocationBlocked("atomic isolation cluster cannot fit any target split")

    anchors = _build_coverage_anchors(cases, clusters, targets) if require_full_coverage else {}
    assignments = _fill_exact_counts(clusters, anchors, targets)
    if require_full_coverage:
        _validate_full_coverage(cases, assignments, clusters)
    balance, hash_cost = _assignment_cost(assignments, clusters, cases, targets)
    allocated = list(cases)
    cluster_assignments: list[tuple[str, SplitName]] = []
    for cluster, rank in zip(clusters, assignments, strict=True):
        split = SPLIT_ORDER[rank]
        cluster_assignments.append((cluster.isolation_cluster_id, split))
        for member in cluster.member_indices:
            allocated[member] = replace(
                cases[member],
                split=replace(
                    cases[member].split,
                    split_name=split,
                    split_manifest_version=None,
                    split_manifest_hash=None,
                    membership_digest=None,
                    isolation_cluster_id=cluster.isolation_cluster_id,
                ),
            )
    result = SplitAllocationResult(
        cases=tuple(allocated),
        target_counts=targets,
        balance_cost=balance,
        hash_preference_cost=hash_cost,
        cluster_assignments=tuple(cluster_assignments),
    )
    from dynamislm.benchmark.contamination import validate_source_family_isolation

    validate_source_family_isolation(result.cases)
    if tuple(
        sum(1 for case in result.cases if case.split.split_name is split) for split in SPLIT_ORDER
    ) != tuple(targets[split] for split in SPLIT_ORDER):
        raise SplitAllocationBlocked("allocated split counts do not equal exact targets")
    if any(case_payload_hash(case) != case.case_payload_hash for case in result.cases):
        raise SplitAllocationBlocked("split allocation changed a case payload hash")
    return result


def validate_split_assignment(cases: tuple[BenchmarkCaseV1, ...]) -> None:
    """Recheck one allocated set for leakage and exact split membership."""

    validate_case_set(cases)
    if any(case.split.split_name is None for case in cases):
        raise ValueError("split assignment is incomplete")
    targets = target_counts(len(cases))
    for split in SPLIT_ORDER:
        actual = sum(1 for case in cases if case.split.split_name is split)
        if actual != targets[split]:
            raise ValueError(
                f"split {split.value} count {actual} differs from target {targets[split]}"
            )
    from dynamislm.benchmark.contamination import validate_source_family_isolation

    validate_source_family_isolation(cases)


__all__ = [
    "SplitAllocationBlocked",
    "SplitAllocationResult",
    "allocate_splits",
    "target_counts",
    "validate_split_assignment",
]
