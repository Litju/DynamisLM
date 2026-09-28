"""Diagnose and repair the RES-223 private production topology."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict, deque
from collections.abc import Callable
from itertools import combinations
from pathlib import Path
from typing import Any, cast

import dynamislm.benchmark.production as production
import dynamislm.benchmark.production_authoring as authoring
from dynamislm.benchmark.authoring import question_classes_for_cell
from dynamislm.benchmark.production_authoring import ProductionAuthoringInputsV1
from dynamislm.benchmark.production_store import (
    DEFAULT_PRODUCTION_ROOT,
    read_external_production_json,
    write_external_production_json,
)
from dynamislm.benchmark.res223_topology import (
    RES223_PLAN_PATH,
    bind_repair_plan,
    core_coloring_feasible,
    coupling_category_counts,
    make_accidental_batch_action,
    read_repair_plan,
    validate_repair_plan,
    write_repair_plan,
)
from dynamislm.serialization import canonical_hash

_RES222_PRIVATE_SHA256 = "77730f68876baa5b6979d034be42b3c192769898fe1b81326109c536792d021e"
_RES222_INPUT_SHA256 = "54e7a28810d38a11b843bc710412504df828a6ae2f90684c423b0b07d5484067"
_RES222_RECEIPT_DIGEST = "sha256:c026321561ff094017d2d3734709f30ce02dd4c318464a6f2a90d15a599754cd"


class _TopologyCapturedError(Exception):
    pass


def _capture_current_draft(
    root: Path,
) -> tuple[tuple[Any, ...], tuple[tuple[str, str], ...], ProductionAuthoringInputsV1]:
    captured: dict[str, Any] = {}
    original = cast(
        Callable[..., Any],
        authoring.validate_production_exact_feasibility,  # type: ignore[attr-defined]
    )

    def capture(
        commitments: tuple[Any, ...],
        *,
        exact_shingle_colocation_pairs: tuple[tuple[str, str], ...],
        **_kwargs: Any,
    ) -> Any:
        captured["commitments"] = commitments
        captured["pairs"] = exact_shingle_colocation_pairs
        raise _TopologyCapturedError

    authoring.validate_production_exact_feasibility = capture  # type: ignore[attr-defined]
    try:
        authoring.build_production_authoring_draft(
            repository_root=Path.cwd(), production_root=root, _diagnostic_only=True
        )
    except _TopologyCapturedError:
        pass
    finally:
        authoring.validate_production_exact_feasibility = original  # type: ignore[attr-defined]
    if "commitments" not in captured:
        raise RuntimeError("RES-223 topology reconstruction did not reach the exact oracle")
    inputs, _digest, _size = read_external_production_json(
        "production/authoring_plan/private_inputs.json",
        ProductionAuthoringInputsV1,
        repository_root=Path.cwd(),
        production_root=root,
    )
    return tuple(captured["commitments"]), tuple(captured["pairs"]), inputs


def _private_payload(path: Path) -> tuple[dict[str, Any], str]:
    try:
        decoded = path.read_text(encoding="utf-8")
        envelope = json.loads(decoded)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("RES-223 exact diagnostic is unavailable or invalid") from exc
    digest = hashlib.sha256(decoded.encode("utf-8")).hexdigest()
    if (
        not isinstance(envelope, dict)
        or envelope.get("type") != "builtins.dict"
        or envelope.get("serialization_version") != 3
        or not isinstance(envelope.get("payload"), dict)
    ):
        raise ValueError("RES-223 exact diagnostic is not a Serialization V3 dictionary")
    return envelope["payload"], digest


def _current_core(root: Path, plan: dict[str, Any] | None) -> tuple[dict[str, Any], str]:
    if plan and plan.get("applied_action_ids"):
        diagnostics = root / "production/diagnostics"
        paths = tuple(diagnostics.glob("RES-223-exact-feasibility-*.private.json"))
        if not paths:
            raise ValueError("RES-223 private exact result is unavailable")
        path = max(paths, key=lambda item: int(item.stem.rsplit("-", 1)[-1].split(".", 1)[0]))
        return _private_payload(path)
    path = root / "production/diagnostics/RES-222-exact-feasibility.private.json"
    payload, digest = _private_payload(path)
    if digest != _RES222_PRIVATE_SHA256 or payload.get("receipt_digest") != _RES222_RECEIPT_DIGEST:
        raise ValueError("RES-222 private diagnostic differs from its sealed entry digest")
    input_path = root / "production/authoring_plan/private_inputs.json"
    if hashlib.sha256(input_path.read_bytes()).hexdigest() != _RES222_INPUT_SHA256:
        raise ValueError("RES-222 private authoring inputs differ from their sealed entry digest")
    return payload, digest


def _candidate_role(candidate_id: str) -> tuple[str, str, str, tuple[str, ...]]:
    _, _, capability, family, raw_slot = candidate_id.split(":")
    slot = int(raw_slot)
    classes = question_classes_for_cell(capability, family)
    question_class = getattr(classes[slot % len(classes)], "value", classes[slot % len(classes)])
    return (
        capability,
        family,
        str(question_class),
        authoring._production_adversarial_tags(capability, family, slot=slot),
    )


def _candidate_context_digest(candidate_id: str, seed: str) -> str:
    _, _, capability, family, raw_slot = candidate_id.split(":")
    slot = int(raw_slot)
    required_refusal = capability == "C18" and family == "F01" and slot < 3
    facts = authoring._semantic_facts(
        capability,
        family,
        seed,
        required_refusal=required_refusal,
    )
    if capability == "C02":
        facts["missing_protocol_fields"] = (
            "device_identity",
            "event_definition",
            "phase_definition",
            "threshold_definition",
        )
    return canonical_hash(
        {
            "capability": capability,
            "family": family,
            "case_role": _candidate_role(candidate_id),
            "structured_scenario_facts": facts,
        }
    )


def _component_record(
    component: Any,
    component_index: int,
    core_group_ids: tuple[str, ...],
    constraint_by_id: dict[str, Any],
    batch_by_id: dict[str, Any],
    input_data: ProductionAuthoringInputsV1,
) -> dict[str, Any]:
    items = tuple(component.items)
    cells = tuple(sorted({f"{item.capability_id}:{item.benchmark_family}" for item in items}))
    batch_ids = tuple(
        sorted({item.expert_author_batch_id for item in items if item.expert_author_batch_id})
    )
    template_ids = tuple(
        sorted({template for item in items for template in item.protocol_template_ids})
    )
    lineage_ids = tuple(
        sorted({item.mutation_lineage_id for item in items if item.mutation_lineage_id})
    )
    batch_rationales = tuple(
        {"identity": batch_id, "kind": "expert_batch", "text": batch_by_id[batch_id].rationale}
        for batch_id in batch_ids
    )
    lineage_by_id = {item.lineage_id: item for item in input_data.mutation_lineages}
    rationales = (
        *batch_rationales,
        *(
            {
                "identity": lineage_id,
                "kind": "mutation_lineage",
                "text": lineage_by_id[lineage_id].rationale,
            }
            for lineage_id in lineage_ids
        ),
    )
    common_identities: dict[tuple[str, str], set[str]] = defaultdict(set)
    for item in items:
        for identity in production._isolation_values(item):
            common_identities[identity].add(item.candidate_id)
    atomic = [identity for identity, owners in common_identities.items() if len(owners) > 1]
    if len(items) > 1:
        atomic.append(("isolation_cluster", component.isolation_cluster_id))
    seed_map = dict(input_data.scenario_seeds)
    candidate_records = []
    for item in items:
        seed = seed_map.get(item.candidate_id)
        candidate_records.append(
            {
                "candidate_id": item.candidate_id,
                "capability_family_cell": f"{item.capability_id}:{item.benchmark_family}",
                "origin": item.origin_class.value,
                "expert_author_batch_id": item.expert_author_batch_id,
                "protocol_template_ids": tuple(item.protocol_template_ids),
                "source_family_id": item.source_family_id,
                "source_document_ids": tuple(item.source_document_ids),
                "source_artifact_ids": tuple(getattr(item, "source_artifact_ids", ())),
                "construct_test_identity_ids": tuple(
                    getattr(item, "construct_test_identity_ids", ())
                ),
                "provider_export_ids": tuple(getattr(item, "provider_export_ids", ())),
                "mutation_lineage_id": item.mutation_lineage_id,
                "parent_candidate_id": item.parent_candidate_id,
                "generator_family": item.generator_family,
                "seed_split_lock": item.seed_namespace.rsplit(":", 1)[-1]
                if item.seed_namespace
                else None,
                "scenario_seed_sha256": hashlib.sha256(seed.encode("ascii")).hexdigest()
                if seed
                else None,
                "case_role": _candidate_role(item.candidate_id)
                if item.candidate_id.startswith("PSE-V1-CANDIDATE:SEM:")
                else None,
                "component_key": component.cluster_key,
                "component_size": component.size,
            }
        )
    component_group_ids = tuple(
        group_id
        for group_id in core_group_ids
        if component_index
        in {index for index, _rank, _coefficient in constraint_by_id[group_id].terms}
    )
    return {
        "component_key": component.cluster_key,
        "component_size": component.size,
        "candidate_ids": tuple(item.candidate_id for item in items),
        "candidate_records": tuple(candidate_records),
        "represented_capability_family_cells": cells,
        "candidate_origins": tuple(sorted({item.origin_class.value for item in items})),
        "expert_author_batch_ids": batch_ids,
        "protocol_template_ids": template_ids,
        "source_family_ids": tuple(
            sorted({item.source_family_id for item in items if item.source_family_id})
        ),
        "source_document_ids": tuple(
            sorted({doc for item in items for doc in item.source_document_ids})
        ),
        "source_artifact_ids": tuple(
            sorted({doc for item in items for doc in getattr(item, "source_artifact_ids", ())})
        ),
        "mutation_lineage_ids": lineage_ids,
        "mutation_parent_edges": tuple(
            sorted(
                (item.parent_candidate_id, item.candidate_id, item.mutation_lineage_id)
                for item in items
                if item.parent_candidate_id
            )
        ),
        "generator_families": tuple(
            sorted({item.generator_family for item in items if item.generator_family})
        ),
        "split_locks": tuple(
            sorted(
                production.PROSPECTIVE_SPLIT_COUNTS[rank][0].value
                for rank in production._split_lock_ranks(component)
            )
        ),
        "current_private_authoring_rationale": tuple(rationales),
        "singleton": len(items) == 1,
        "cross_cell": len(cells) > 1,
        "declared_atomic_isolation_identities": tuple(sorted(set(atomic))),
        "core_conflict_group_ids": component_group_ids,
        "component_degree_within_core": len(component_group_ids),
    }


def _diagnose(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    prior_plan = read_repair_plan(root) if (root / RES223_PLAN_PATH).exists() else None
    diagnostic, diagnostic_file_sha = _current_core(root, prior_plan)
    core_group_ids = tuple(diagnostic.get("base_conflict_groups", ()))
    if not core_group_ids:
        core_group_ids = tuple(
            item
            for item in diagnostic.get("colocation_conflict_groups", ())
            if item.startswith("CELL:")
        )
    if not core_group_ids:
        raise ValueError("RES-223 exact diagnostic has no reduced cell core to classify")
    commitments, exact_pairs, input_data = _capture_current_draft(root)
    components = production._feasibility_clusters(commitments, allow_incompatible_locks=True)
    constraints = production._exact_requirement_constraints(components, components)
    constraint_by_id = {item.group_id: item for item in constraints}
    missing = set(core_group_ids) - set(constraint_by_id)
    if missing:
        raise ValueError(
            f"RES-223 reduced core is stale against current commitments: {sorted(missing)}"
        )
    core_indices = sorted(
        {
            index
            for group_id in core_group_ids
            for index, _rank, _coefficient in constraint_by_id[group_id].terms
        }
    )
    batch_by_id = {batch.author_batch_id: batch for batch in input_data.expert_batches}
    core_components = tuple(
        _component_record(
            components[index], index, core_group_ids, constraint_by_id, batch_by_id, input_data
        )
        for index in core_indices
    )
    group_records = []
    for group_id in core_group_ids:
        constraint = constraint_by_id[group_id]
        eligible = tuple(sorted({index for index, _rank, _coefficient in constraint.terms}))
        kind, remainder = group_id.split(":", 1)
        requirement, split = remainder.rsplit(":", 1)
        group_records.append(
            {
                "group_id": group_id,
                "requirement_kind": kind,
                "requirement_key": requirement,
                "capability_family_cell": requirement if kind == "CELL" else None,
                "required_split": split,
                "eligible_component_keys": tuple(
                    components[index].cluster_key for index in eligible
                ),
                "eligible_component_count": len(eligible),
            }
        )
    cell_counts = {
        cell: len(
            {
                key
                for group in group_records
                if group["capability_family_cell"] == cell
                for key in group["eligible_component_keys"]
            }
        )
        for cell in sorted(
            {
                group["capability_family_cell"]
                for group in group_records
                if group["capability_family_cell"] is not None
            }
        )
    }
    adjacency: dict[str, set[str]] = defaultdict(set)
    for group in group_records:
        left = "CELL:" + group["group_id"]
        for key in group["eligible_component_keys"]:
            right = "COMP:" + key
            adjacency[left].add(right)
            adjacency[right].add(left)
    seen: set[str] = set()
    graph_components = []
    for node in sorted(adjacency):
        if node in seen:
            continue
        queue = deque([node])
        seen.add(node)
        nodes = []
        while queue:
            current = queue.popleft()
            nodes.append(current)
            for neighbor in sorted(adjacency[current]):
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
        graph_components.append(
            {
                "cell_group_count": sum(node.startswith("CELL:") for node in nodes),
                "component_count": sum(node.startswith("COMP:") for node in nodes),
                "node_count": len(nodes),
            }
        )
    seeds = dict(input_data.scenario_seeds)
    context_digests = {
        candidate_id: _candidate_context_digest(candidate_id, seeds[candidate_id])
        for candidate_id, _capability, _family, _slot in authoring._semantic_slot_specs()
    }
    context_counts = Counter(context_digests.values())
    lineage_by_id = {item.lineage_id: item for item in input_data.mutation_lineages}
    couplings = []
    action_list: list[dict[str, Any]] = []
    for component in core_components:
        if not component["cross_cell"]:
            continue
        if len(component["expert_author_batch_ids"]) != 1:
            couplings.append(
                {
                    "component_key": component["component_key"],
                    "category": "REQUIRES_NEW_INDEPENDENT_CANDIDATE",
                    "basis": "No unique expert batch identifies a bounded topology-only action.",
                }
            )
            continue
        batch = batch_by_id[component["expert_author_batch_ids"][0]]
        members = tuple(batch.candidate_ids)
        if len(members) != 2:
            couplings.append(
                {
                    "component_key": component["component_key"],
                    "category": "REQUIRES_NEW_INDEPENDENT_CANDIDATE",
                    "basis": (
                        "No bounded topology-only action can truthfully separate this author batch."
                    ),
                }
            )
            continue
        roles = {
            candidate_id: _candidate_role(candidate_id) for candidate_id in batch.candidate_ids
        }
        records = {record["candidate_id"]: record for record in component["candidate_records"]}
        mutation_structure = tuple(
            sorted(
                (
                    lineage_id,
                    lineage_by_id[lineage_id].parent_candidate_id,
                    tuple(lineage_by_id[lineage_id].child_candidate_ids),
                )
                for lineage_id in component["mutation_lineage_ids"]
                if lineage_id in lineage_by_id
            )
        )
        component_candidate_ids = set(component["candidate_ids"])
        mutation_lineages_preservable = all(
            parent_id in members and set(children) <= component_candidate_ids
            for _lineage_id, parent_id, children in mutation_structure
        ) and len(mutation_structure) == len(component["mutation_lineage_ids"])
        protected = any(
            component[field]
            for field in (
                "source_document_ids",
                "source_artifact_ids",
                "generator_families",
                "split_locks",
            )
        )
        unique_contexts = all(
            context_counts[context_digests[candidate_id]] == 1 for candidate_id in members
        )
        independent_seeds = len(
            {records[candidate_id]["scenario_seed_sha256"] for candidate_id in members}
        ) == len(members)
        if protected or not mutation_lineages_preservable or not independent_seeds:
            couplings.append(
                {
                    "component_key": component["component_key"],
                    "category": "REQUIRED_SCIENTIFIC_DEPENDENCY",
                    "basis": (
                        "A source, generator, split-lock, or non-local mutation "
                        "dependency prevents topology-only decoupling."
                    ),
                }
            )
            continue
        if not unique_contexts:
            couplings.append(
                {
                    "component_key": component["component_key"],
                    "old_batch_id": batch.author_batch_id,
                    "candidate_ids": members,
                    "capability_family_cells": component["represented_capability_family_cells"],
                    "category": "ACCIDENTAL_AUTHORING_COUPLING",
                    "current_private_rationale": batch.rationale,
                    "action_unavailable_reason": (
                        "The private case-context registry does not distinguish "
                        "these singleton templates."
                    ),
                }
            )
            continue
        action = make_accidental_batch_action(
            batch,
            seeds,
            roles,
            mutation_parent_descendant_structure=mutation_structure,
            scenario_context_digests={
                candidate_id: context_digests[candidate_id] for candidate_id in members
            },
        )
        action_list.append(action)
        couplings.append(
            {
                "component_key": component["component_key"],
                "old_batch_id": batch.author_batch_id,
                "candidate_ids": members,
                "mutation_parent_descendant_structure": mutation_structure,
                "expected_hash_propagation_scope": action["expected_hash_propagation_scope"],
                "capability_family_cells": component["represented_capability_family_cells"],
                "category": "ACCIDENTAL_AUTHORING_COUPLING",
                "current_private_rationale": batch.rationale,
                "classification_basis": (
                    "Batch membership is selected by expertise group/cell counts; "
                    "case contexts have independent seeds and no shared source, "
                    "mutation, generator, or split lock."
                ),
                "authorized_action_id": action["action_id"],
            }
        )
    actions = tuple(sorted(action_list, key=lambda action: action["action_id"]))
    coupling_records = tuple(couplings)
    current_batch_ids = {
        batch_id for item in core_components for batch_id in item["expert_author_batch_ids"]
    }
    batch_distribution = Counter(
        len(batch_by_id[batch_id].candidate_ids) for batch_id in current_batch_ids
    )
    action_batch_ids = tuple(action["old_batch_id"] for action in actions)
    core_cells = tuple(sorted(cell_counts))
    minimum_core_actions = None
    if all(group_id.startswith("CELL:") for group_id in core_group_ids):
        for action_count in range(len(actions) + 1):
            feasible_sets = []
            for subset in combinations(action_batch_ids, action_count):
                cut = set(subset)
                split_components: list[tuple[str, ...]] = []
                for component in core_components:
                    batch_id = next(iter(component["expert_author_batch_ids"]), None)
                    if batch_id in cut:
                        split_components.extend(
                            (record["capability_family_cell"],)
                            for record in component["candidate_records"]
                        )
                    else:
                        split_components.append(component["represented_capability_family_cells"])
                if core_coloring_feasible(tuple(split_components), core_cells):
                    feasible_sets.append(subset)
            if feasible_sets:
                minimum_core_actions = action_count
                break
    summary = {
        "core_group_count": len(core_group_ids),
        "core_component_count": len(core_components),
        "core_cross_cell_component_count": sum(item["cross_cell"] for item in core_components),
        "core_exactly_three_eligible_cells": sum(count == 3 for count in cell_counts.values()),
        "cell_eligible_component_counts": tuple(sorted(cell_counts.items())),
        "components_shared_by_two_or_more_conflict_cells": sum(
            len(item["represented_capability_family_cells"]) >= 2 for item in core_components
        ),
        "component_degree_distribution": tuple(
            sorted(
                Counter(item["component_degree_within_core"] for item in core_components).items()
            )
        ),
        "conflict_group_degree_distribution": tuple(
            sorted(Counter(group["eligible_component_count"] for group in group_records).items())
        ),
        "connected_component_distribution": tuple(
            sorted(
                (item["cell_group_count"], item["component_count"], item["node_count"])
                for item in graph_components
            )
        ),
        "current_batch_size_distribution": tuple(sorted(batch_distribution.items())),
        "cross_cell_atomic_couplings_by_category": tuple(
            sorted(coupling_category_counts(coupling_records).items())
        ),
        "minimum_core_feasibility_action_count": minimum_core_actions,
        "truthful_action_count_required": len(actions),
        "authorized_repair_actions": len(actions),
        "selected_repair_actions": len(actions),
        "candidate_metadata_changes": sum(
            action["candidate_metadata_change_count"] for action in actions
        ),
        "batch_pair_relationships_changed": sum(
            action["batch_pair_relationship_change_count"] for action in actions
        ),
        "new_template_variants": sum(action["new_template_variant_count"] for action in actions),
    }
    topology = {
        "schema": "RES-223-PRIVATE-CORE-TOPOLOGY@1.0.0",
        "authority": {
            "res222_private_diagnostic_sha256": "sha256:" + diagnostic_file_sha,
            "res222_receipt_digest": diagnostic["receipt_digest"],
            "private_authoring_inputs_sha256": hashlib.sha256(
                (root / "production/authoring_plan/private_inputs.json").read_bytes()
            ).hexdigest(),
            "base_model_digest": diagnostic["base_model_digest"],
            "base_status": diagnostic["base_status"],
            "serialization_version": 3,
        },
        "core_conflict_group_ids": core_group_ids,
        "groups": tuple(group_records),
        "components": core_components,
        "incidence_edges": tuple(
            sorted(
                (group["group_id"], key)
                for group in group_records
                for key in group["eligible_component_keys"]
            )
        ),
        "connected_components": tuple(graph_components),
        "coupling_classifications": coupling_records,
        "summary": summary,
        "exclusions": {
            "question_text_included": False,
            "source_excerpts_included": False,
            "raw_scenario_seeds_included": False,
            "private_rationale_in_git": False,
        },
    }
    topology_digest = canonical_hash(topology)
    topology["topology_digest"] = topology_digest
    topology_iteration = 0 if prior_plan is None else int(prior_plan["iteration"])
    topology_path = (
        f"production/diagnostics/RES-223-core-topology-{topology_iteration:03d}.private.json"
    )
    write_external_production_json(
        topology,
        topology_path,
        repository_root=Path.cwd(),
        production_root=root,
    )
    prior_actions = tuple(prior_plan["action_registry"]) if prior_plan else ()
    actions_by_id = {item["action_id"]: item for item in (*prior_actions, *actions)}
    action_registry = tuple(actions_by_id[key] for key in sorted(actions_by_id))
    newly_selected = tuple(action["action_id"] for action in actions)
    selected = tuple(
        sorted(set(prior_plan["selected_action_ids"] if prior_plan else ()) | set(newly_selected))
    )
    applied = tuple(prior_plan["applied_action_ids"]) if prior_plan else ()
    if prior_plan:
        iteration = int(prior_plan["iteration"]) + 1
    else:
        iteration = 1
    status = "READY" if len(selected) > len(applied) and actions else "BLOCKED"
    plan = bind_repair_plan(
        {
            "schema": "RES-223-REPAIR-PLAN@1.0.0",
            "iteration": iteration,
            "status": status,
            "action_registry": action_registry,
            "selected_action_ids": selected,
            "applied_action_ids": applied,
            "selection_basis": (
                "Remove every classified accidental cross-cell dependency; "
                "preserve all case and authority bytes."
            ),
            "topology_digest": topology_digest,
            "core_group_ids": core_group_ids,
            "exact_result_path": (
                f"production/diagnostics/RES-223-exact-feasibility-{iteration:03d}.private.json"
            ),
        }
    )
    validate_repair_plan(plan)
    write_repair_plan(
        plan,
        root,
        Path.cwd(),
        expected_plan_digest=prior_plan["plan_digest"] if prior_plan else None,
    )
    return topology, plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("diagnose", "apply"), nargs="?", default="diagnose")
    parser.add_argument("--production-root", type=Path, default=DEFAULT_PRODUCTION_ROOT)
    args = parser.parse_args(argv)
    root = args.production_root.resolve()
    if root.is_relative_to(Path.cwd().resolve()):
        raise ValueError("RES-223 private topology must remain outside Git")
    if args.command == "diagnose":
        topology, plan = _diagnose(root)
        print("PRIVATE_CORE_TOPOLOGY=PASS")
        print(f"CORE_TOPOLOGY_DIGEST={topology['topology_digest']}")
        print(f"CORE_COMPONENTS={topology['summary']['core_component_count']}")
        print(
            f"CORE_CROSS_CELL_COMPONENTS={topology['summary']['core_cross_cell_component_count']}"
        )
        print(
            f"CORE_EXACTLY_THREE_ELIGIBLE_CELLS={topology['summary']['core_exactly_three_eligible_cells']}"
        )
        print(f"AUTHORIZED_REPAIR_ACTIONS={len(plan['action_registry'])}")
        selected_count = len(plan["selected_action_ids"]) - len(plan["applied_action_ids"])
        print(f"SELECTED_REPAIR_ACTIONS={selected_count}")
        return 0 if plan["status"] == "READY" else 2
    plan = read_repair_plan(root)
    validate_repair_plan(plan)
    if plan["status"] != "READY":
        print("STATUS=BLOCKED")
        return 2
    try:
        draft, _exclusion = authoring.build_production_authoring_draft(
            repository_root=Path.cwd(), production_root=root
        )
    except ValueError as exc:
        if not str(exc).startswith("exact production feasibility is "):
            raise
        print(str(exc))
        return 3
    receipt = draft.feasibility_receipt
    print(f"BASE_EXACT_STATUS={receipt.base_status}")
    print(f"COLOCATION_EXACT_STATUS={receipt.colocation_status}")
    print(f"CANONICAL_SELF_REDUCTION={receipt.canonical_self_reduction_status}")
    return 0 if receipt.base_status == receipt.colocation_status == "FEASIBLE" else 3


if __name__ == "__main__":
    raise SystemExit(main())
