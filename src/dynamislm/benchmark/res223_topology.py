"""Private, topology-only repair helpers for RES-223."""

from __future__ import annotations

import hashlib
import json
import statistics
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from dynamislm.serialization import canonical_hash, canonical_json

RES223_PLAN_PATH = "production/diagnostics/RES-223-repair-plan.private.json"
RES223_TOPOLOGY_VERSION = "RES-223-SEMANTIC-SINGLETON@1"


def bind_repair_plan(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        **{key: value for key, value in plan.items() if key != "plan_digest"},
        "plan_digest": canonical_hash(
            {key: value for key, value in plan.items() if key != "plan_digest"}
        ),
    }


def validate_repair_plan(plan: dict[str, Any]) -> None:
    if {"candidate_split_membership", "split_membership", "allocation_witness"} & set(plan):
        raise ValueError("RES-223 plan cannot persist prospective split membership")
    if plan.get("plan_digest") != canonical_hash(
        {key: value for key, value in plan.items() if key != "plan_digest"}
    ):
        raise ValueError("RES-223 repair plan digest mismatch")
    actions = tuple(plan.get("action_registry", ()))
    action_ids = tuple(action.get("action_id") for action in actions)
    if not action_ids or len(set(action_ids)) != len(action_ids):
        raise ValueError("RES-223 repair plan has missing or duplicate action IDs")
    selected = tuple(plan.get("selected_action_ids", ()))
    applied = tuple(plan.get("applied_action_ids", ()))
    if selected != tuple(sorted(set(selected))) or applied != tuple(sorted(set(applied))):
        raise ValueError("RES-223 selected/applied action IDs are not canonical")
    if not set(applied) <= set(selected) <= set(action_ids):
        raise ValueError("RES-223 repair plan selects an unknown or unapplied action")
    if plan.get("status") not in {"READY", "BLOCKED", "PASS"}:
        raise ValueError("RES-223 repair plan status is invalid")


def read_repair_plan(production_root: str | Path) -> dict[str, Any]:
    path = Path(production_root) / RES223_PLAN_PATH
    try:
        decoded = path.read_text(encoding="utf-8")
        envelope = json.loads(decoded)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("RES-223 private repair plan is unavailable or invalid") from exc
    if (
        not isinstance(envelope, dict)
        or envelope.get("type") != "builtins.dict"
        or envelope.get("serialization_version") != 3
        or not isinstance(envelope.get("payload"), dict)
        or canonical_json(envelope["payload"]) + "\n" != decoded
    ):
        raise ValueError("RES-223 private repair plan is not canonical Serialization V3")
    plan = cast(dict[str, Any], envelope["payload"])
    validate_repair_plan(plan)
    return plan


def write_repair_plan(
    plan: dict[str, Any],
    production_root: str | Path,
    repository_root: str | Path,
    *,
    expected_plan_digest: str | None,
) -> None:
    from dynamislm.benchmark.production_store import (
        replace_external_production_json,
        write_external_production_json,
    )

    validate_repair_plan(plan)
    path = Path(production_root) / RES223_PLAN_PATH
    if expected_plan_digest is None:
        if path.exists():
            raise ValueError("RES-223 repair plan appeared during initial creation")
        write_external_production_json(
            plan,
            RES223_PLAN_PATH,
            repository_root=repository_root,
            production_root=production_root,
        )
        return
    current = read_repair_plan(production_root)
    if current["plan_digest"] != expected_plan_digest:
        raise ValueError("RES-223 repair plan changed before update")
    expected_file_digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    replace_external_production_json(
        plan,
        RES223_PLAN_PATH,
        expected_digest=expected_file_digest,
        repository_root=repository_root,
        production_root=production_root,
    )


def scenario_seed_digest(seed: str) -> str:
    if not seed:
        raise ValueError("RES-223 singleton template requires its private scenario seed")
    return hashlib.sha256(seed.encode("ascii")).hexdigest()


def _canonical_case_role(
    role: tuple[str, str, str, tuple[str, ...]],
) -> tuple[str, str, str, tuple[str, ...]]:
    question_class = getattr(role[2], "value", role[2])
    return (role[0], role[1], str(question_class), tuple(role[3]))


def singleton_batch_record(
    candidate_id: str,
    seed: str,
    role: tuple[str, str, str, tuple[str, ...]],
    scenario_context_sha256: str | None = None,
) -> dict[str, Any]:
    role = _canonical_case_role(role)
    seed_digest = scenario_seed_digest(seed)
    identity_inputs = {
        "version": RES223_TOPOLOGY_VERSION,
        "candidate_id": candidate_id,
        "role": role,
        "scenario_seed_sha256": seed_digest,
    }
    if scenario_context_sha256 is not None:
        identity_inputs["scenario_context_sha256"] = scenario_context_sha256
    identity = canonical_hash(identity_inputs).removeprefix("sha256:")[:24]
    rationale = (
        f"Independent bounded {role[0]} case role {role[1]} / {role[2]} / "
        f"{','.join(role[3])}; unique scenario seed commitment {seed_digest}. "
        + (
            f"Structured case context commitment {scenario_context_sha256}. "
            if scenario_context_sha256 is not None
            else ""
        )
        + "No shared source, mutation, generator, or protocol-template dependency is declared."
    )
    record = {
        "candidate_id": candidate_id,
        "author_batch_id": f"PSE-V1-RES223-EXPERT-BATCH:{identity}",
        "protocol_template_id": f"PSE-V1-RES223-PROTOCOL-TEMPLATE:{identity}",
        "isolation_cluster_id": f"PSE-V1-RES223-SEMANTIC-CLUSTER:{identity}",
        "rationale": rationale,
        "question_text_changed": "NO",
        "expected_answer_changed": "NO",
        "source_evidence_changed": "NO",
        "res71_authority_changed": "NO",
        "scientific_contract_changed": "NO",
        "scenario_seed_sha256": seed_digest,
        "case_role": role,
    }
    if scenario_context_sha256 is not None:
        record["scenario_context_sha256"] = scenario_context_sha256
    return record


def make_accidental_batch_action(
    batch: Any,
    scenario_seeds: dict[str, str],
    candidate_roles: dict[str, tuple[str, str, str, tuple[str, ...]]],
    *,
    protected_dependency: bool = False,
    mutation_parent_descendant_structure: tuple[tuple[str, str, tuple[str, ...]], ...] = (),
    scenario_context_digests: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Authorize only a two-case heuristic pair with independent, unique case roles."""

    if protected_dependency:
        raise ValueError("RES-223 cannot split a source, mutation, generator, or seed dependency")
    members = tuple(batch.candidate_ids)
    if len(members) != 2:
        raise ValueError("RES-223 only supports bounded two-candidate semantic batch actions")
    if any(
        candidate_id not in scenario_seeds or candidate_id not in candidate_roles
        for candidate_id in members
    ):
        raise ValueError("RES-223 action is missing a private seed or case-role binding")
    roles = {
        candidate_id: _canonical_case_role(candidate_roles[candidate_id])
        for candidate_id in members
    }
    if roles[members[0]][:2] == roles[members[1]][:2]:
        raise ValueError("RES-223 batch action does not cross capability-family cells")
    if scenario_context_digests is not None and (
        any(candidate_id not in scenario_context_digests for candidate_id in members)
        or len({scenario_context_digests[candidate_id] for candidate_id in members}) != len(members)
    ):
        raise ValueError("RES-223 action lacks distinct private scenario-context bindings")
    mutation_structure = tuple(
        sorted(
            (lineage_id, parent_id, tuple(children))
            for lineage_id, parent_id, children in mutation_parent_descendant_structure
        )
    )
    if any(
        parent_id not in members or not children
        for _lineage, parent_id, children in mutation_structure
    ):
        raise ValueError("RES-223 mutation descendants must stay with one paired parent")
    children = tuple(
        child for _lineage, _parent, child_ids in mutation_structure for child in child_ids
    )
    if len(children) != len(set(children)) or set(children) & set(members):
        raise ValueError("RES-223 mutation descendant structure overlaps candidates")
    replacements = tuple(
        singleton_batch_record(
            candidate_id,
            scenario_seeds[candidate_id],
            roles[candidate_id],
            scenario_context_digests[candidate_id]
            if scenario_context_digests is not None
            else None,
        )
        for candidate_id in members
    )
    action_identity: tuple[Any, ...] = (batch.author_batch_id, members, replacements)
    if mutation_structure:
        action_identity = (*action_identity, mutation_structure)
    action_id = "RES-223-ACTION:" + canonical_hash(action_identity).removeprefix("sha256:")[:24]
    return {
        "action_id": action_id,
        "category": "ACCIDENTAL_AUTHORING_COUPLING",
        "affected_candidate_ids": members,
        "old_batch_id": batch.author_batch_id,
        "old_template_id": batch.protocol_template_id,
        "old_isolation_cluster_id": batch.isolation_cluster_id,
        "old_rationale": batch.rationale,
        "proposed_singletons": replacements,
        "mutation_parent_descendant_structure": mutation_structure,
        "scientific_justification": (
            "The producer paired candidates using expertise group and cell counts only; each "
            "candidate has an independent scenario seed and a distinct frozen cell/question-class/"
            "adversarial-tag role; each declared mutation lineage remains with its original parent."
        ),
        "compatibility_proof": {
            "unique_case_role_per_candidate": True,
            "unique_scenario_context_per_candidate": scenario_context_digests is not None,
            "independent_scenario_seed_commitments": True,
            "source_dependencies_preserved": True,
            "mutation_dependencies_preserved": True,
            "generator_dependencies_preserved": True,
            "question_text_changed": "NO",
            "expected_answer_changed": "NO",
            "source_evidence_changed": "NO",
            "res71_authority_changed": "NO",
            "scientific_contract_changed": "NO",
        },
        "expected_hash_propagation_scope": tuple(sorted((*members, *children))),
        "candidate_metadata_change_count": len(members) + len(children),
        "batch_pair_relationship_change_count": 1,
        "new_template_variant_count": len(replacements),
    }


def apply_repair_actions(
    baseline_batches: tuple[Any, ...],
    scenario_seeds: dict[str, str],
    plan: dict[str, Any],
    action_ids: tuple[str, ...],
    mutation_lineages: tuple[Any, ...] = (),
) -> tuple[Any, ...]:
    from dynamislm.benchmark.production_authoring import ProductionExpertBatchV1

    validate_repair_plan(plan)
    if not set(action_ids) <= set(plan["selected_action_ids"]):
        raise ValueError("RES-223 cannot apply an unselected topology action")
    actions = {action["action_id"]: action for action in plan["action_registry"]}
    batch_by_id = {batch.author_batch_id: batch for batch in baseline_batches}
    replacements: dict[str, ProductionExpertBatchV1] = {}
    removed: set[str] = set()
    for action_id in action_ids:
        action = actions[action_id]
        if action.get("category") != "ACCIDENTAL_AUTHORING_COUPLING":
            raise ValueError(
                "RES-223 topology action does not target a classified accidental coupling"
            )
        batch = batch_by_id.get(action.get("old_batch_id"))
        if batch is None or tuple(batch.candidate_ids) != tuple(action["affected_candidate_ids"]):
            raise ValueError("RES-223 action no longer matches its author batch")
        if batch.protocol_template_id != action.get(
            "old_template_id"
        ) or batch.isolation_cluster_id != action.get("old_isolation_cluster_id"):
            raise ValueError("RES-223 action no longer matches its template/isolation binding")
        if any(candidate_id in removed for candidate_id in batch.candidate_ids):
            raise ValueError("RES-223 actions overlap candidate membership")
        roles = {
            item["candidate_id"]: (
                item["case_role"][0],
                item["case_role"][1],
                item["case_role"][2],
                tuple(item["case_role"][3]),
            )
            for item in action["proposed_singletons"]
        }
        context_digests = {
            item["candidate_id"]: item["scenario_context_sha256"]
            for item in action["proposed_singletons"]
            if "scenario_context_sha256" in item
        }
        if context_digests and len(context_digests) != len(action["proposed_singletons"]):
            raise ValueError("RES-223 action has incomplete scenario-context bindings")
        mutation_structure = tuple(
            (item[0], item[1], tuple(item[2]))
            for item in action.get("mutation_parent_descendant_structure", ())
        )
        if mutation_lineages:
            expected_mutation_structure = tuple(
                sorted(
                    (
                        lineage.lineage_id,
                        lineage.parent_candidate_id,
                        tuple(lineage.child_candidate_ids),
                    )
                    for lineage in mutation_lineages
                    if lineage.parent_candidate_id in batch.candidate_ids
                )
            )
            if mutation_structure != expected_mutation_structure:
                raise ValueError("RES-223 action does not preserve the private mutation lineage")
        elif mutation_structure:
            raise ValueError("RES-223 mutation action requires its private lineage registry")
        expected_action = make_accidental_batch_action(
            batch,
            scenario_seeds,
            roles,
            mutation_parent_descendant_structure=mutation_structure,
            scenario_context_digests=context_digests if context_digests else None,
        )
        if expected_action["action_id"] != action_id or _freeze(
            expected_action["proposed_singletons"]
        ) != _freeze(action["proposed_singletons"]):
            raise ValueError("RES-223 action is stale against its case roles or private seed")
        removed.update(batch.candidate_ids)
        proof = action["compatibility_proof"]
        if any(
            proof.get(name) != expected
            for name, expected in (
                ("independent_scenario_seed_commitments", True),
                ("source_dependencies_preserved", True),
                ("mutation_dependencies_preserved", True),
                ("generator_dependencies_preserved", True),
                ("question_text_changed", "NO"),
                ("expected_answer_changed", "NO"),
                ("source_evidence_changed", "NO"),
                ("res71_authority_changed", "NO"),
                ("scientific_contract_changed", "NO"),
            )
        ):
            raise ValueError("RES-223 action lacks its topology-only compatibility proof")
        if action.get("compatibility_proof", {}).get("unique_scenario_context_per_candidate"):
            if any(
                proof_context.get("scenario_context_sha256") is None
                for proof_context in action["proposed_singletons"]
            ):
                raise ValueError("RES-223 scenario-context proof is incomplete")
        elif proof.get("unique_case_role_per_candidate") is not True:
            raise ValueError("legacy RES-223 singleton lacks a unique case-role proof")
        for replacement in action["proposed_singletons"]:
            candidate_id = replacement["candidate_id"]
            if candidate_id not in batch.candidate_ids:
                raise ValueError("RES-223 singleton is outside the original batch")
            if (
                scenario_seed_digest(scenario_seeds.get(candidate_id, ""))
                != replacement["scenario_seed_sha256"]
            ):
                raise ValueError("RES-223 singleton is stale against its private scenario seed")
            if candidate_id in replacements:
                raise ValueError("RES-223 singleton candidate is duplicated")
            replacements[candidate_id] = ProductionExpertBatchV1(
                author_batch_id=replacement["author_batch_id"],
                protocol_template_id=replacement["protocol_template_id"],
                isolation_cluster_id=replacement["isolation_cluster_id"],
                candidate_ids=(candidate_id,),
                rationale=replacement["rationale"],
            )
        if set(batch.candidate_ids) != {
            replacement["candidate_id"] for replacement in action["proposed_singletons"]
        }:
            raise ValueError("RES-223 action does not preserve complete batch membership")
    result = tuple(
        sorted(
            (
                *(batch for batch in baseline_batches if not set(batch.candidate_ids) & removed),
                *replacements.values(),
            ),
            key=lambda batch: batch.author_batch_id.encode("utf-8"),
        )
    )
    candidate_ids = tuple(candidate_id for batch in result for candidate_id in batch.candidate_ids)
    expected_ids = tuple(
        sorted(candidate_id for batch in baseline_batches for candidate_id in batch.candidate_ids)
    )
    if tuple(sorted(candidate_ids)) != expected_ids or len(candidate_ids) != len(
        set(candidate_ids)
    ):
        raise ValueError("RES-223 action changed or duplicated semantic batch membership")
    return result


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple(sorted((key, _freeze(item)) for key, item in value.items()))
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    return value


def topology_content_projection(packet: Any) -> Any:
    """Erase only authorized batch/template/cluster hashes for content equality checks."""

    contamination = replace(
        packet.contamination,
        expert_author_batch_id=None,
        protocol_template_id=None,
    )
    isolation = replace(packet.isolation, isolation_cluster_id="RES-223-TOPOLOGY-PROJECTION")
    return replace(
        packet,
        contamination=contamination,
        isolation=isolation,
        candidate_payload_hash="sha256:" + "0" * 64,
        proposed_approval_digest="sha256:" + "0" * 64,
    )


def validate_topology_only_packet_change(before: tuple[Any, ...], after: tuple[Any, ...]) -> None:
    before_by_id = {packet.candidate_id: topology_content_projection(packet) for packet in before}
    after_by_id = {packet.candidate_id: topology_content_projection(packet) for packet in after}
    if before_by_id != after_by_id:
        raise ValueError(
            "RES-223 topology repair changed question, answer, source, or scientific content"
        )


def core_coloring_feasible(
    component_cells: tuple[tuple[str, ...], ...], core_cells: tuple[str, ...]
) -> bool:
    from ortools.sat.python import cp_model

    model = cp_model.CpModel()
    colors = tuple(
        tuple(model.new_bool_var(f"c{component}_{rank}") for rank in range(3))
        for component in range(len(component_cells))
    )
    for row in colors:
        model.add_exactly_one(row)
    for cell in core_cells:
        for rank in range(3):
            eligible = tuple(
                colors[index][rank]
                for index, represented in enumerate(component_cells)
                if cell in represented
            )
            model.add(sum(eligible) >= 1)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 60.0
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    solver.parameters.cp_model_presolve = True
    solver.parameters.randomize_search = False
    status = solver.solve(model)
    if status in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        return True
    if status == cp_model.INFEASIBLE:
        return False
    raise RuntimeError("RES-223 reduced-core coloring returned UNKNOWN")


def allocation_resilience_summary(
    forceable_counts: tuple[tuple[str, str, int], ...],
) -> dict[str, Any]:
    values = tuple(count for _cell, _split, count in forceable_counts)
    if not values:
        raise ValueError("RES-223 allocation resilience requires all cell/split counts")
    summary: dict[str, Any] = {
        "forceable_component_count_min": min(values),
        "forceable_component_count_median": statistics.median(values),
        "forceable_component_count_max": max(values),
        "forceable_count_eq_1": sum(value == 1 for value in values),
        "forceable_count_eq_2": sum(value == 2 for value in values),
        "forceable_count_ge_3": sum(value >= 3 for value in values),
    }
    summary["resilience_diagnostic_digest"] = canonical_hash(
        {"forceable_counts": tuple(sorted(forceable_counts)), **summary}
    )
    return summary


def coupling_category_counts(couplings: tuple[dict[str, Any], ...]) -> dict[str, int]:
    counts = Counter(item["category"] for item in couplings)
    return {
        category: counts.get(category, 0)
        for category in (
            "REQUIRED_SCIENTIFIC_DEPENDENCY",
            "VALID_REDESIGNABLE_AUTHOR_BATCH",
            "ACCIDENTAL_AUTHORING_COUPLING",
            "REQUIRES_NEW_INDEPENDENT_CANDIDATE",
        )
    }
