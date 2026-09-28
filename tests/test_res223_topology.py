from __future__ import annotations

from dataclasses import dataclass, replace
from types import SimpleNamespace

import pytest

from dynamislm.benchmark.production_authoring import (
    ProductionExpertBatchV1,
    ProductionMutationLineageInputV1,
)
from dynamislm.benchmark.res223_topology import (
    allocation_resilience_summary,
    apply_repair_actions,
    bind_repair_plan,
    core_coloring_feasible,
    coupling_category_counts,
    make_accidental_batch_action,
    singleton_batch_record,
    topology_content_projection,
    validate_repair_plan,
    validate_topology_only_packet_change,
)

_LEFT = "PSE-V1-CANDIDATE:SEM:C14:F01:00"
_RIGHT = "PSE-V1-CANDIDATE:SEM:C14:F04:00"
_SEEDS = {_LEFT: "a" * 48, _RIGHT: "b" * 48}
_ROLES: dict[str, tuple[str, str, str, tuple[str, ...]]] = {
    _LEFT: ("C14", "F01", "CONSTRUCT", ("POPULATION_MISMATCH",)),
    _RIGHT: ("C14", "F04", "ANSWERABILITY", ("METHOD_VALIDITY_AS_APPLICABILITY",)),
}


def _batch() -> ProductionExpertBatchV1:
    return ProductionExpertBatchV1(
        author_batch_id="old-batch",
        protocol_template_id="old-template",
        isolation_cluster_id="old-cluster",
        candidate_ids=tuple(sorted((_LEFT, _RIGHT))),
        rationale="heuristic pairing",
    )


def _plan(action: dict[str, object]) -> dict[str, object]:
    action_id = str(action["action_id"])
    return bind_repair_plan(
        {
            "schema": "RES-223-REPAIR-PLAN@1.0.0",
            "iteration": 1,
            "status": "READY",
            "action_registry": (action,),
            "selected_action_ids": (action_id,),
            "applied_action_ids": (),
        }
    )


def test_private_core_coloring_reconstruction_is_deterministic() -> None:
    cells = ("C14:F01", "C14:F04", "C14:F10", "C14:F11", "C14:F12")
    edges = (
        ("C14:F01", "C14:F12"),
        ("C14:F04", "C14:F10"),
        ("C14:F01", "C14:F12"),
        ("C14:F10", "C14:F11"),
        ("C14:F01", "C14:F04"),
        ("C14:F10", "C14:F11"),
        ("C14:F01", "C14:F04"),
        ("C14:F11", "C14:F12"),
    )
    topology = tuple(tuple(edge) for edge in edges)
    assert core_coloring_feasible(topology, cells) is False
    cut = topology[0]
    repaired = ((cut[0],), (cut[1],), *topology[1:])
    assert core_coloring_feasible(repaired, cells) is True
    assert core_coloring_feasible(topology, cells) is False


def test_coupling_classification_schema_includes_every_category() -> None:
    counts = coupling_category_counts(({"category": "ACCIDENTAL_AUTHORING_COUPLING"},) * 2)
    assert counts == {
        "REQUIRED_SCIENTIFIC_DEPENDENCY": 0,
        "VALID_REDESIGNABLE_AUTHOR_BATCH": 0,
        "ACCIDENTAL_AUTHORING_COUPLING": 2,
        "REQUIRES_NEW_INDEPENDENT_CANDIDATE": 0,
    }


def test_singleton_binding_is_deterministic_and_seed_bound() -> None:
    first = singleton_batch_record(_LEFT, _SEEDS[_LEFT], _ROLES[_LEFT])
    second = singleton_batch_record(_LEFT, _SEEDS[_LEFT], _ROLES[_LEFT])
    changed_seed = singleton_batch_record(_LEFT, "c" * 48, _ROLES[_LEFT])
    assert first == second
    assert first["protocol_template_id"] != changed_seed["protocol_template_id"]


@pytest.mark.parametrize("dependency", ("source", "mutation", "generator"))
def test_protected_dependency_cannot_be_split(dependency: str) -> None:
    del dependency  # The guard is intentionally identical for every protected identity type.
    with pytest.raises(ValueError, match="cannot split"):
        make_accidental_batch_action(_batch(), _SEEDS, _ROLES, protected_dependency=True)


def test_same_cell_pair_cannot_be_singletonized_as_a_repair() -> None:
    same_cell = {
        _LEFT: _ROLES[_LEFT],
        _RIGHT: ("C14", "F01", "ANSWERABILITY", ("METHOD_VALIDITY_AS_APPLICABILITY",)),
    }
    with pytest.raises(ValueError, match="does not cross"):
        make_accidental_batch_action(_batch(), _SEEDS, same_cell)


def test_duplicate_scenario_context_cannot_be_singletonized() -> None:
    with pytest.raises(ValueError, match="distinct private scenario-context"):
        make_accidental_batch_action(
            _batch(),
            _SEEDS,
            _ROLES,
            scenario_context_digests={_LEFT: "same-context", _RIGHT: "same-context"},
        )


def test_authorized_expert_rebatch_preserves_candidate_membership() -> None:
    action = make_accidental_batch_action(_batch(), _SEEDS, _ROLES)
    plan = _plan(action)
    result = apply_repair_actions((_batch(),), _SEEDS, plan, (action["action_id"],))
    assert tuple(sorted(candidate for item in result for candidate in item.candidate_ids)) == tuple(
        sorted((_LEFT, _RIGHT))
    )
    assert len(result) == 2
    assert all(len(item.candidate_ids) == 1 for item in result)


def test_repair_plan_rejects_unregistered_actions_and_membership() -> None:
    action = make_accidental_batch_action(_batch(), _SEEDS, _ROLES)
    plan = _plan(action)
    with pytest.raises(ValueError, match="unselected"):
        apply_repair_actions((_batch(),), _SEEDS, plan, ("RES-223-ACTION:unknown",))
    allocated = bind_repair_plan(
        {**plan, "candidate_split_membership": {_LEFT: "PUBLIC_DEVELOPMENT"}}
    )
    with pytest.raises(ValueError, match="cannot persist"):
        validate_repair_plan(allocated)


def test_plan_digest_and_newly_exposed_core_update_are_deterministic() -> None:
    first_action = make_accidental_batch_action(_batch(), _SEEDS, _ROLES)
    first = _plan(first_action)
    second_batch = ProductionExpertBatchV1(
        "old-batch-2",
        "old-template-2",
        "old-cluster-2",
        ("PSE-V1-CANDIDATE:SEM:C09:F07:00", "PSE-V1-CANDIDATE:SEM:C09:F10:00"),
        "heuristic pairing",
    )
    ids = second_batch.candidate_ids
    seeds = {ids[0]: "d" * 48, ids[1]: "e" * 48}
    roles: dict[str, tuple[str, str, str, tuple[str, ...]]] = {
        ids[0]: ("C09", "F07", "CLAIM", ("CLAIM_LADDER",)),
        ids[1]: ("C09", "F10", "REFERENCE", ("CURRENT_REFERENCE_LEAKAGE",)),
    }
    second_action = make_accidental_batch_action(second_batch, seeds, roles)
    extended = bind_repair_plan(
        {
            **first,
            "action_registry": (first_action, second_action),
            "selected_action_ids": tuple(
                sorted((first_action["action_id"], second_action["action_id"]))
            ),
        }
    )
    validate_repair_plan(extended)
    assert extended["applied_action_ids"] == ()
    assert len(extended["selected_action_ids"]) == 2
    validate_repair_plan(extended)
    assert first["plan_digest"] != extended["plan_digest"]


@dataclass(frozen=True)
class _Contamination:
    expert_author_batch_id: str | None
    protocol_template_id: str | None


@dataclass(frozen=True)
class _Isolation:
    isolation_cluster_id: str


@dataclass(frozen=True)
class _Packet:
    candidate_id: str
    question: str
    answer: str
    source_evidence: bytes
    contamination: _Contamination
    isolation: _Isolation
    candidate_payload_hash: str
    proposed_approval_digest: str


def _packet(*, question: str = "question", answer: str = "answer", batch: str = "batch") -> _Packet:
    return _Packet(
        _LEFT,
        question,
        answer,
        b"source-bytes",
        _Contamination(batch, "template"),
        _Isolation(batch),
        "sha256:" + "1" * 64,
        "sha256:" + "2" * 64,
    )


def test_topology_only_rebuild_preserves_question_answer_and_source_bytes() -> None:
    before = (_packet(),)
    after = (
        _packet(
            batch="new-singleton",
        ),
    )
    validate_topology_only_packet_change(before, after)
    assert topology_content_projection(before[0]) == topology_content_projection(after[0])


def test_topology_only_rebuild_rejects_scientific_content_changes() -> None:
    with pytest.raises(ValueError, match="changed question, answer, source"):
        validate_topology_only_packet_change((_packet(),), (_packet(answer="changed"),))


def test_mutation_descendants_remain_in_the_hash_propagation_scope() -> None:
    children = tuple(f"PSE-V1-CANDIDATE:MUT:lineage:{index:02d}" for index in range(1, 4))
    lineage = ProductionMutationLineageInputV1(
        lineage_id="lineage-1",
        parent_candidate_id=_LEFT,
        child_candidate_ids=children,
        operator_id="operator-1",
        rationale="scientific mutation relation",
    )
    action = make_accidental_batch_action(
        _batch(),
        _SEEDS,
        _ROLES,
        mutation_parent_descendant_structure=((lineage.lineage_id, _LEFT, children),),
    )
    plan = _plan(action)
    result = apply_repair_actions(
        (_batch(),),
        _SEEDS,
        plan,
        (action["action_id"],),
        mutation_lineages=(lineage,),
    )
    assert len(result) == 2
    assert set(children) <= set(action["expected_hash_propagation_scope"])


def test_parent_payload_change_rebinds_mutation_descendant_hashes() -> None:
    from dynamislm.benchmark.pre_review import bind_candidate_review_packet
    from dynamislm.benchmark.production import PRODUCTION_BATCH_ID
    from dynamislm.benchmark.production_authoring import (
        PRODUCTION_SYNTHETIC_GENERATOR_DIGEST,
        ProductionAuthoringInputsV1,
        _author_semantic_packets,
        _mutation_child,
        production_authoring_input_digest,
    )

    parent_id = "PSE-V1-CANDIDATE:SEM:C01:F01:00"
    parent_input = ProductionAuthoringInputsV1(
        batch_id=PRODUCTION_BATCH_ID,
        synthetic_generator_registry_digest=PRODUCTION_SYNTHETIC_GENERATOR_DIGEST,
        scenario_seeds=((parent_id, "f" * 48),),
        synthetic_seed_blocks=(),
        mutation_seed_blocks=(),
        source_selections=(),
        expert_batches=(
            ProductionExpertBatchV1(
                "batch-old",
                "template-old",
                "cluster-old",
                (parent_id,),
                "single bounded scenario",
            ),
        ),
        mutation_lineages=(),
        input_digest="sha256:" + "0" * 64,
    )
    parent_input = replace(
        parent_input,
        input_digest=production_authoring_input_digest(parent_input),
    )
    parent = _author_semantic_packets(((parent_id, "C01", "F01", 0),), parent_input)[0]

    def rebind(parent_packet, batch: str):
        return bind_candidate_review_packet(
            replace(
                parent_packet,
                contamination=replace(
                    parent_packet.contamination,
                    expert_author_batch_id=batch,
                    protocol_template_id=f"template:{batch}",
                ),
                isolation=replace(
                    parent_packet.isolation,
                    isolation_cluster_id=f"cluster:{batch}",
                ),
                candidate_payload_hash="sha256:" + "0" * 64,
                proposed_approval_digest="sha256:" + "0" * 64,
            )
        )

    old_parent = rebind(parent, "batch-old")
    new_parent = rebind(parent, "batch-new")
    child_id = "PSE-V1-CANDIDATE:MUT:res223-test:01"
    old_child = _mutation_child(
        old_parent,
        candidate_id=child_id,
        lineage_id="PSE-V1-MUTATION-LINEAGE:res223-test",
        operator_id="measurement-identity-trap",
        stage=1,
        mutation_seed=12345,
    )
    new_child = _mutation_child(
        new_parent,
        candidate_id=child_id,
        lineage_id="PSE-V1-MUTATION-LINEAGE:res223-test",
        operator_id="measurement-identity-trap",
        stage=1,
        mutation_seed=12345,
    )
    assert old_child.parent_candidate_binding is not None
    assert new_child.parent_candidate_binding is not None
    assert (
        new_child.parent_candidate_binding.parent_candidate_payload_hash
        == new_parent.candidate_payload_hash
    )
    assert (
        new_child.parent_candidate_binding.parent_candidate_payload_hash
        != old_child.parent_candidate_binding.parent_candidate_payload_hash
    )


def test_allocation_resilience_digest_is_deterministic() -> None:
    counts = (("C01:F01", "PUBLIC_DEVELOPMENT", 2), ("C01:F01", "HIDDEN_FINAL", 3))
    assert allocation_resilience_summary(counts) == allocation_resilience_summary(counts)


def test_resilience_summary_counts_forceable_components() -> None:
    summary = allocation_resilience_summary(
        (
            ("C01:F01", "PUBLIC_DEVELOPMENT", 1),
            ("C01:F01", "FROZEN_VALIDATION", 2),
            ("C01:F01", "HIDDEN_FINAL", 3),
        )
    )
    assert summary["forceable_component_count_min"] == 1
    assert summary["forceable_component_count_median"] == 2
    assert summary["forceable_component_count_max"] == 3
    assert summary["forceable_count_eq_1"] == 1
    assert summary["forceable_count_eq_2"] == 1
    assert summary["forceable_count_ge_3"] == 1


def test_exact_status_gate_requires_both_models(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import scripts.res223_topology as cli

    action = make_accidental_batch_action(_batch(), _SEEDS, _ROLES)
    monkeypatch.setattr(cli, "read_repair_plan", lambda _root: _plan(action))
    monkeypatch.setattr(
        cli,
        "authoring",
        SimpleNamespace(
            build_production_authoring_draft=lambda **_kwargs: (
                SimpleNamespace(
                    feasibility_receipt=SimpleNamespace(
                        base_status="FEASIBLE",
                        colocation_status="INFEASIBLE",
                        canonical_self_reduction_status="NOT_RUN",
                    )
                ),
                None,
            )
        ),
    )
    result = cli.main(["apply", "--production-root", "/tmp/res223-private"])
    assert result == 3
    assert "BASE_EXACT_STATUS=FEASIBLE" in capsys.readouterr().out
