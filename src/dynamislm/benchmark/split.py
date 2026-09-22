"""Exact deterministic split allocation for PerformanceScience-Eval V1."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, replace

from dynamislm.benchmark.constants import (
    BENCHMARK_SEMANTIC_VERSION,
    CAPABILITY_IDS,
    CRITICAL_ERROR_CLASSES,
    FAMILY_IDS,
    SPLIT_ORDER,
    SPLIT_PROPORTIONS,
    SplitName,
)
from dynamislm.benchmark.contracts import BenchmarkCaseV1
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


def _coverage_possible(
    clusters: tuple[_Cluster, ...],
    index: int,
    assigned: tuple[int, ...],
    cases: tuple[BenchmarkCaseV1, ...],
) -> bool:
    """Prune only when a required case cell cannot occur in a remaining split."""

    # The full matrix is checked at the leaf.  This inexpensive test prevents a split
    # from becoming permanently empty when all remaining cases are already assigned.
    remaining_indices = tuple(
        member for cluster in clusters[index:] for member in cluster.member_indices
    )
    for rank in range(3):
        available = [cases[member] for member in remaining_indices]
        assigned_cases = [
            cases[member]
            for cluster, chosen in zip(clusters[:index], assigned, strict=True)
            if chosen == rank
            for member in cluster.member_indices
        ]
        if not available and not assigned_cases:
            return False
    return True


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


def _validate_full_coverage(
    cases: tuple[BenchmarkCaseV1, ...], assignments: tuple[int, ...], clusters: tuple[_Cluster, ...]
) -> None:
    from dynamislm.benchmark.coverage import validate_case_coverage

    by_rank: dict[int, list[BenchmarkCaseV1]] = defaultdict(list)
    for cluster, rank in zip(clusters, assignments, strict=True):
        by_rank[rank].extend(cases[index] for index in cluster.member_indices)
    for rank in range(3):
        present_capabilities = {case.capability_id for case in by_rank[rank]}
        present_families = {case.benchmark_family for case in by_rank[rank]}
        missing_capabilities = set(CAPABILITY_IDS) - present_capabilities
        missing_families = set(FAMILY_IDS) - present_families
        if missing_capabilities or missing_families:
            raise SplitAllocationBlocked(
                f"split {SPLIT_ORDER[rank].value} lacks coverage: "
                f"capabilities={sorted(missing_capabilities)}, families={sorted(missing_families)}"
            )
    for error_class in CRITICAL_ERROR_CLASSES:
        for rank in (1, 2):
            if not any(
                error_class in case.scoring_contract.error_class_rules for case in by_rank[rank]
            ):
                raise SplitAllocationBlocked(
                    f"critical error {error_class.value} has no eligible case in "
                    f"{SPLIT_ORDER[rank].value}"
                )
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
            f"full acceptance-matrix coverage is missing: {coverage.missing_cells[:3]}"
        )


def allocate_splits(
    cases: tuple[BenchmarkCaseV1, ...],
    *,
    require_full_coverage: bool = False,
    contamination_audit_passed: bool = True,
) -> SplitAllocationResult:
    """Return the exact lexicographic argmin of the frozen three-level objective.

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

    # Remaining counts/cells are used for admissible lower-bound pruning.  The
    # objective itself is always evaluated exactly at complete assignments.
    suffix_sizes = [0] * (len(clusters) + 1)
    suffix_cells: list[dict[str, int]] = [defaultdict(int) for _ in range(len(clusters) + 1)]
    for index in range(len(clusters) - 1, -1, -1):
        suffix_sizes[index] = suffix_sizes[index + 1] + clusters[index].size
        suffix_cells[index] = defaultdict(int, suffix_cells[index + 1])
        for member in clusters[index].member_indices:
            for cell in _soft_cells(cases[member]):
                suffix_cells[index][cell] += 1
    cell_totals: dict[str, int] = defaultdict(int)
    for case in cases:
        for cell in _soft_cells(case):
            cell_totals[cell] += 1
    target_by_rank = tuple(targets[split] for split in SPLIT_ORDER)

    best: tuple[int, int, tuple[int, ...]] | None = None
    current_counts = [0, 0, 0]
    current_cells: list[dict[str, int]] = [defaultdict(int) for _ in range(3)]

    def recurse(index: int, assignments: tuple[int, ...], current_hash_cost: int) -> None:
        nonlocal best
        if index == len(clusters):
            if tuple(current_counts) != target_by_rank:
                return
            if require_full_coverage:
                try:
                    _validate_full_coverage(cases, assignments, clusters)
                except SplitAllocationBlocked:
                    return
            balance, hash_cost = _assignment_cost(assignments, clusters, cases, targets)
            candidate = (balance, hash_cost, assignments)
            if best is None or candidate < best:
                best = candidate
            return

        remaining = suffix_sizes[index]
        for rank in range(3):
            cluster = clusters[index]
            if current_counts[rank] + cluster.size > target_by_rank[rank]:
                continue
            if sum(current_counts) + cluster.size + (remaining - cluster.size) != len(cases):
                continue
            current_counts[rank] += cluster.size
            for member in cluster.member_indices:
                for cell in _soft_cells(cases[member]):
                    current_cells[rank][cell] += 1

            # Capacity feasibility for all remaining atomic clusters.
            remaining_after = suffix_sizes[index + 1]
            if all(
                current_counts[split_rank] <= target_by_rank[split_rank]
                and target_by_rank[split_rank] - current_counts[split_rank] <= remaining_after
                for split_rank in range(3)
            ):
                lower_balance = 0
                for cell, cell_total in cell_totals.items():
                    for split_rank in range(3):
                        current = current_cells[split_rank].get(cell, 0)
                        max_value = current + suffix_cells[index + 1].get(cell, 0)
                        target_value = target_by_rank[split_rank] * cell_total
                        scaled_current = len(cases) * current
                        scaled_max = len(cases) * max_value
                        if target_value < scaled_current:
                            lower_balance += scaled_current - target_value
                        elif target_value > scaled_max:
                            lower_balance += target_value - scaled_max
                lower_hash = current_hash_cost
                if best is None or (lower_balance, lower_hash) <= best[:2]:
                    recurse(
                        index + 1,
                        (*assignments, rank),
                        current_hash_cost + (cluster.size if rank != cluster.preferred_rank else 0),
                    )
            for member in cluster.member_indices:
                for cell in _soft_cells(cases[member]):
                    current_cells[rank][cell] -= 1
            current_counts[rank] -= cluster.size

    recurse(0, (), 0)
    if best is None:
        raise SplitAllocationBlocked("no exact split assignment satisfies frozen hard constraints")
    balance, hash_cost, assignments = best
    if require_full_coverage:
        _validate_full_coverage(cases, assignments, clusters)
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
