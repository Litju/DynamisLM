#!/usr/bin/env python3
"""Qualify the existing RES-407 C08 generator contract without materialization."""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

_REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPOSITORY))
sys.path.insert(0, str(_REPOSITORY / "src"))

from dynamislm.benchmark.authoring import production_seed_namespace  # noqa: E402
from dynamislm.benchmark.authority_supply import (  # noqa: E402
    LaneCapacityStatus,
    ReserveCandidateLaneV1,
)
from dynamislm.benchmark.constants import (  # noqa: E402
    CRITICAL_ERROR_CLASSES,
    CaseOrigin,
    ExpectedAnswerKind,
    RefusalDecision,
    ScoringProfile,
    SplitName,
)
from dynamislm.benchmark.contamination import exact_13_token_shingles  # noqa: E402
from dynamislm.benchmark.coverage import COVERAGE_MATRIX, coverage_manifest_digest  # noqa: E402
from dynamislm.benchmark.production_authoring import (  # noqa: E402
    PRODUCTION_SYNTHETIC_GENERATOR_DIGEST,
    PRODUCTION_SYNTHETIC_GENERATORS,
    SYNTHETIC_GENERATOR_ID,
    SYNTHETIC_GENERATOR_VERSION,
    _production_adversarial_tags,
)
from dynamislm.benchmark.repair_geometry import (  # noqa: E402
    RepairArchetype,
    RepairGeometry,
    build_compact_ideal_repair_signatures,
)
from dynamislm.benchmark.scoring_paths import reachable_error_classes  # noqa: E402
from dynamislm.benchmark.selection_contracts import (  # noqa: E402
    ConstraintKind,
    FeatureKind,
    IsolationIdentityKind,
    SelectionFeature,
)
from dynamislm.qualification.res115_authoring import (  # noqa: E402
    AUTHORING_PROCESS_ID,
    _production_authoring_engine_references,
    _required_reference_refusal_fields,
    _scoring_contract,
)
from dynamislm.serialization import (  # noqa: E402
    SERIALIZATION_VERSION,
    canonical_hash,
    canonical_json,
    from_canonical_json,
    type_identifier,
)
from scripts import res407_governed_backfill as legacy  # noqa: E402
from scripts import res407_repair_geometry as geometry_script  # noqa: E402

STRUCTURAL_REPORT_PATH = Path(
    "reports/performance_science_eval/res407_governed_structural_comparison.json"
)
QUALIFICATION_REPORT_PATH = Path(
    "reports/performance_science_eval/res407_c08_generator_qualification.json"
)
_SCHEMA = "RES407-C08-GENERATOR-QUALIFICATION@1.0.0"
_REQUIRED_OPTIMISTIC_COUNT = 48
_PUBLIC_SPLIT = SplitName.PUBLIC_DEVELOPMENT
_C08_F05_LANE = "synthetic:pse-v1-synthetic-refusal-public_development"
_C08_F05_FAMILY = "pse-v1-synthetic-refusal-public_development"
_SOURCE_FILES = (
    "scripts/res407_governed_backfill.py",
    "src/dynamislm/benchmark/authoring.py",
    "src/dynamislm/benchmark/coverage.py",
    "src/dynamislm/benchmark/production_authoring.py",
    "src/dynamislm/benchmark/repair_geometry.py",
    "src/dynamislm/benchmark/scoring_paths.py",
    "src/dynamislm/benchmark/selection_constraints.py",
    "src/dynamislm/benchmark/validation.py",
    "src/dynamislm/benchmark/variable_pool.py",
    "src/dynamislm/qualification/res115_authoring.py",
)


def _without(record: dict[str, Any], key: str) -> dict[str, Any]:
    return {name: value for name, value in record.items() if name != key}


def _check_digest(name: str, actual: str, expected: str) -> str:
    if actual != expected:
        raise ValueError(f"persisted RES-407 digest mismatch: {name}")
    return name


def _decode_nested(value: dict[str, Any], cls: type[Any]) -> Any:
    envelope = {
        "serialization_version": SERIALIZATION_VERSION,
        "type": type_identifier(cls),
        "payload": value,
    }
    return from_canonical_json(
        json.dumps(envelope, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        cls,
    )


def _external_record(relative_path: str) -> tuple[dict[str, Any], str]:
    from dynamislm.benchmark.production_store import DEFAULT_PRODUCTION_ROOT
    from scripts import res406_pool_qualification as res406

    result = res406._read_record(
        relative_path,
        repository_root=_REPOSITORY,
        production_root=DEFAULT_PRODUCTION_ROOT,
    )
    if result is None:
        raise ValueError(f"required RES-407 external evidence is missing: {relative_path}")
    record, _bytes_digest, _size = result
    return record, record["receipt_digest"]


def _geometry_evidence() -> tuple[RepairGeometry, dict[str, Any], str]:
    from dynamislm.benchmark.production_store import DEFAULT_PRODUCTION_ROOT

    relative = PurePosixPath(
        "production/variable-pools/backfill"
        f"/{legacy.ORIGINAL_PLAN_DIGEST.removeprefix('sha256:')}"
        f"/{legacy.RES451_MERGE_SHA}/geometry/v3/repair-geometry.json"
    )
    path = DEFAULT_PRODUCTION_ROOT.joinpath(*relative.parts)
    payload_bytes = path.read_bytes()
    encoded = payload_bytes.decode("utf-8")
    envelope = json.loads(encoded)
    if (
        envelope.get("serialization_version") != SERIALIZATION_VERSION
        or envelope.get("type") != type_identifier(dict)
        or canonical_json(envelope["payload"]) + "\n" != encoded
    ):
        raise ValueError("external RES-407 geometry is not canonical")
    record = envelope["payload"]
    _check_digest(
        "geometry_record_receipt_digest",
        canonical_hash(_without(record, "receipt_digest")),
        record["receipt_digest"],
    )
    geometry = _decode_nested(record["geometry"], RepairGeometry)
    if record.get("geometry_digest") != geometry.geometry_digest:
        raise ValueError("external RES-407 geometry record digest mismatch")
    return geometry, record, "sha256:" + hashlib.sha256(payload_bytes).hexdigest()


def _archetype_evidence() -> tuple[dict[str, Any], tuple[RepairArchetype, ...]]:
    from dynamislm.benchmark.production_store import DEFAULT_PRODUCTION_ROOT
    from scripts import res406_pool_qualification as res406

    relative = (
        "production/variable-pools/backfill/"
        f"{legacy.ORIGINAL_PLAN_DIGEST.removeprefix('sha256:')}/"
        f"{legacy.RES451_MERGE_SHA}/geometry/v3/governed-archetype-inventory.json"
    )
    result = res406._read_record(
        relative,
        repository_root=_REPOSITORY,
        production_root=DEFAULT_PRODUCTION_ROOT,
    )
    if result is None:
        raise ValueError("external RES-407 archetype inventory is missing")
    record = result[0]
    archetypes = tuple(_decode_nested(item, RepairArchetype) for item in record["archetypes"])
    if canonical_hash(archetypes) != record["archetype_inventory_digest"]:
        raise ValueError("external RES-407 archetype inventory digest mismatch")
    return record, archetypes


def _governed_report_path(relative: str) -> str:
    return (
        "production/variable-pools/backfill/"
        f"{legacy.ORIGINAL_PLAN_DIGEST.removeprefix('sha256:')}/"
        f"{legacy.RES451_MERGE_SHA}/geometry/v3/{relative}"
    )


def _generator_for_family(family: str) -> Any:
    return next(item for item in PRODUCTION_SYNTHETIC_GENERATORS if item.generator_family == family)


def _source_code_digests() -> tuple[dict[str, str], ...]:
    return tuple(
        {
            "path": relative,
            "sha256": "sha256:" + hashlib.sha256((_REPOSITORY / relative).read_bytes()).hexdigest(),
        }
        for relative in _SOURCE_FILES
    )


def _reconstruct_generator_lane(split: SplitName) -> ReserveCandidateLaneV1:
    generator = _generator_for_family(f"pse-v1-synthetic-refusal-{split.value.lower()}")
    c08_row = next(item for item in COVERAGE_MATRIX if item.capability_id == "C08")
    cells = tuple(sorted({("C08", family) for family in c08_row.benchmark_families}))
    identity_digests = tuple(
        sorted(
            {
                canonical_hash(("SYNTHETIC_GENERATOR", generator.generator_id, generator.version)),
                canonical_hash(("GENERATOR_FAMILY", generator.generator_family)),
                canonical_hash(("SYNTHETIC_SPLIT_LOCK", split)),
            }
        )
    )
    return ReserveCandidateLaneV1(
        lane_id="synthetic:" + generator.generator_family,
        origin_class=CaseOrigin.DETERMINISTIC_SYNTHETIC,
        authority_ref="registered split-family synthetic generator",
        authority_digest=canonical_hash(generator),
        capacity_unit="unique split-locked synthetic seed block",
        existing_planned_capacity=0,
        available_capacity=None,
        capacity_status=LaneCapacityStatus.RULE_GOVERNED,
        capacity_rule="registered generator and split-family seed-block namespace",
        supported_cells=cells,
        isolation_identity_digests=identity_digests,
    )


def verify_persisted_digests(report: dict[str, Any]) -> dict[str, Any]:
    """Recheck persisted report hashes and their exact geometry/archetype bindings."""

    geometry, geometry_record, geometry_file_digest = _geometry_evidence()
    archetype_record, archetypes = _archetype_evidence()
    comparison_record, external_checkpoint_receipt = _external_record(
        _governed_report_path("governed-structural-comparison.json")
    )

    accepted_signatures = build_compact_ideal_repair_signatures(geometry)
    _ideal_signatures, _ideal_vector, ideal_witness = geometry_script._accepted_ideal_witness(
        geometry
    )
    checks = [
        _check_digest(
            "governed_archetype_contract_digest",
            canonical_hash(tuple(report["archetype_contract_inventory"])),
            report["governed_archetype_contract_digest"],
        ),
        _check_digest("geometry_digest", geometry.geometry_digest, report["geometry_digest"]),
        _check_digest("problem_digest", geometry.problem.problem_digest, report["problem_digest"]),
        _check_digest(
            "live_supply_inventory_digest",
            archetype_record["consumption"]["inventory_digest"],
            report["live_supply_inventory_digest"],
        ),
        _check_digest(
            "capability_gap_digest",
            canonical_hash(_without(report["capability_gap"], "gap_digest")),
            report["capability_gap_digest"],
        ),
        _check_digest(
            "ideal_signature_inventory_digest",
            canonical_hash(accepted_signatures),
            report["ideal_signature_inventory_digest"],
        ),
        _check_digest(
            "ideal_winning_vector_digest",
            ideal_witness["winning_vector_digest"],
            report["ideal_winning_vector_digest"],
        ),
        _check_digest(
            "ideal_result_digest",
            ideal_witness["ideal_result_digest"],
            report["ideal_result_digest"],
        ),
        _check_digest(
            "ideal_relaxation_proof_digest",
            canonical_hash(_without(report["ideal_relaxation_proof"], "proof_digest")),
            report["ideal_relaxation_proof_digest"],
        ),
        _check_digest(
            "optimistic_c08_relaxation_proof_digest",
            canonical_hash(_without(report["optimistic_c08_relaxation_proof"], "proof_digest")),
            report["optimistic_c08_relaxation_proof_digest"],
        ),
        _check_digest(
            "saturation_proof_digest",
            canonical_hash(_without(report["saturation_proof"], "proof_digest")),
            report["saturation_proof_digest"],
        ),
        _check_digest(
            "optimistic_c08_vector_digest",
            canonical_hash(tuple(report["optimistic_c08_repair_vector_typed"])),
            report["optimistic_c08_vector_digest"],
        ),
        _check_digest(
            "optimistic_c08_vector_report_digest",
            canonical_hash(tuple(report["optimistic_c08_repair_vector"])),
            report["optimistic_c08_vector_report_digest"],
        ),
        _check_digest(
            "public_report_receipt_digest",
            canonical_hash(_without(report, "receipt_digest")),
            report["receipt_digest"],
        ),
    ]
    if comparison_record["receipt_digest"] != external_checkpoint_receipt:
        raise ValueError("external structural-comparison checkpoint receipt mismatch")

    archetype_by_key = {(item.lane_id, item.cell): item for item in archetypes}
    report_rows = {
        (item["lane_id"], tuple(item["cell"])): item
        for item in report["archetype_contract_inventory"]
    }
    for key, archetype in archetype_by_key.items():
        row = report_rows[key]
        _check_digest("archetype_digest", canonical_hash(archetype), row["archetype_digest"])
        if (archetype.authority_digest, archetype.lane_digest) != (
            row["authority_digest"],
            row["lane_digest"],
        ):
            raise ValueError("persisted C08 archetype authority binding mismatch")
    target = report_rows[(_C08_F05_LANE, ("C08", "F05"))]
    generator = _generator_for_family(_C08_F05_FAMILY)
    _check_digest(
        "C08_F05_generator_authority_digest",
        canonical_hash(generator),
        target["authority_digest"],
    )
    lane = _reconstruct_generator_lane(_PUBLIC_SPLIT)
    _check_digest("C08_F05_lane_digest", lane.lane_digest, target["lane_digest"])
    _check_digest(
        "synthetic_generator_registry_digest",
        canonical_hash(PRODUCTION_SYNTHETIC_GENERATORS),
        PRODUCTION_SYNTHETIC_GENERATOR_DIGEST,
    )

    return {
        "status": "PASS",
        "verified_digest_fields": tuple(checks),
        "verified_archetype_digest_count": len(archetype_by_key),
        "governed_archetype_contract_digest": report["governed_archetype_contract_digest"],
        "external_checkpoint_receipt_digest": external_checkpoint_receipt,
        "geometry_record_sha256": geometry_file_digest,
        "geometry_record_receipt_digest": geometry_record["receipt_digest"],
        "archetype_inventory_receipt_digest": archetype_record["receipt_digest"],
        "geometry": geometry,
        "archetype_record": archetype_record,
    }


def derive_c08_f05_features() -> tuple[SelectionFeature, ...]:
    """Derive selection features from the fixed F05 authoring and scoring path."""

    row = next(item for item in COVERAGE_MATRIX if item.capability_id == "C08")
    if (
        "F05" not in row.benchmark_families
        or CaseOrigin.DETERMINISTIC_SYNTHETIC not in row.case_origins
        or ScoringProfile.STRUCTURED_FIELDS_V1 not in row.scorer_profiles
        or "RES71_REFERENCE_CASE" not in row.answer_authorities
    ):
        raise ValueError("current F05 synthetic authoring no longer qualifies for C08 selection")

    _engine_reference, _rfd_refusal_reference, generic_refusal_reference = (
        _production_authoring_engine_references()
    )
    answer, refusal = _required_reference_refusal_fields(
        generic_refusal_reference,
        question="RES-407 F05 contract derivation only.",
        safe_description="No numeric result is authorized.",
    )
    scoring = _scoring_contract(
        profile=ScoringProfile.STRUCTURED_FIELDS_V1,
        row=row,
        required_fields=answer.required_field_ids,
        refusal_decision=refusal.decision,
        prohibited_claims=answer.prohibited_claims,
    )
    errors = reachable_error_classes(
        scoring,
        refusal_decision=refusal.decision,
        prohibited_claims=answer.prohibited_claims,
    )
    tags = _production_adversarial_tags("C08", "F05")
    row_errors = errors.intersection(row.error_classes)
    row_tags = set(tags).intersection(row.adversarial_tags)
    features: set[SelectionFeature] = set()
    features.update(SelectionFeature(FeatureKind.ROW_TAG, ("C08", tag)) for tag in row_tags)
    features.update(
        SelectionFeature(FeatureKind.ROW_ERROR, ("C08", error.value)) for error in row_errors
    )
    if row_tags and row_errors:
        features.add(SelectionFeature(FeatureKind.CELL, ("C08", "F05")))
    features.update(
        SelectionFeature(FeatureKind.CRITICAL_ERROR, (error.value,))
        for error in errors.intersection(CRITICAL_ERROR_CLASSES)
    )
    if (
        refusal.decision is not RefusalDecision.REQUIRED
        or answer.kind is not ExpectedAnswerKind.REFUSAL
    ):
        raise ValueError("governed C08 F05 generator lost its required non-numeric refusal")
    return tuple(sorted(features, key=lambda item: (item.kind.value, item.key)))


def _feature_wire(feature: SelectionFeature) -> dict[str, Any]:
    return {"kind": feature.kind.value, "key": feature.key}


def _optimistic_features(report: dict[str, Any]) -> tuple[tuple[str, tuple[str, ...]], ...]:
    vector = report["optimistic_c08_repair_vector"]
    winning = next(
        item
        for item in vector
        if item["lane_id"] == _C08_F05_LANE and tuple(item["cell"]) == ("C08", "F05")
    )
    return tuple((kind, tuple(key)) for kind, key in winning["optimistic_feature_support"])


def repeat_authority(contract: dict[str, Any]) -> dict[str, Any]:
    lane_capacity = contract["capacity_semantics"]
    multiplicity = contract["implemented_recipe_path_multiplicity"]
    if (
        lane_capacity["status"] != "RULE_GOVERNED"
        or lane_capacity["remaining_finite_capacity"] is not None
    ):
        raise ValueError("C08 repeat accounting no longer matches the persisted rule-governed lane")
    return {
        "status": "UNKNOWN",
        "authorized_repeat_count_min": multiplicity["options_per_lane_cell"],
        "authorized_repeat_count_max": "UNKNOWN",
        "minimum_basis": "One currently materializable recipe option exists for this lane/cell.",
        "multiple_seed_authority": "REPEAT_COUNT_UNSPECIFIED",
        "seed_reuse_forbidden": True,
        "current_recipe_options_per_lane_cell": multiplicity["options_per_lane_cell"],
        "repeat_ordinal_in_candidate_id": multiplicity["repeat_ordinal_in_candidate_id"],
        "repeat_ordinal_in_seed_block_rule": multiplicity["repeat_ordinal_in_seed_block_rule"],
        "capacity_status": lane_capacity["status"],
        "capacity_unit": "unique split-locked synthetic seed block",
        "capacity_rule": lane_capacity["rule"],
        "capacity_accounting": (
            "RULE_GOVERNED counts distinct authorized split-locked seed-block units. "
            "A null finite capacity supplies no numeric maximum and does not mean unlimited."
        ),
        "seed_namespace_template": (
            "PSE-V1/{split}/pse-v1-unregistered-operation-context:1.0.0@{seed_block}"
        ),
        "seed_block_allocation_rule": (
            "Current helper: 'res407-' + canonical_hash((conflict_set_digest, lane_id, cell)) "
            "without the sha256: prefix, truncated to 48 hex characters; no repeat ordinal."
        ),
        "candidate_id_allocation_rule": (
            "PSE-V1-CANDIDATE:RES407:SYNTH:{capability}:{family}:{split}; "
            "the current ID has no repeat ordinal."
        ),
        "repeated_seed_distinctness_validation": (
            "_governed_recipe_check requires unique synthetic seed blocks; "
            "validate_case_set rejects reused generator namespace/block identities."
        ),
    }


def instance_identity_contract(candidate_id: str, seed_block: str) -> dict[str, Any]:
    """Return identity formulas only; this does not construct or materialize a candidate."""

    return {
        "candidate_id": candidate_id,
        "source_family_id": f"PSE-V1-SYNTHETIC-FAMILY:{candidate_id}",
        "isolation_cluster_id": f"PSE-V1-SYNTHETIC-CLUSTER:{_PUBLIC_SPLIT.value}",
        "generator_family": _C08_F05_FAMILY,
        "generator_id": SYNTHETIC_GENERATOR_ID,
        "generator_version": SYNTHETIC_GENERATOR_VERSION,
        "seed_namespace": production_seed_namespace(
            _PUBLIC_SPLIT, SYNTHETIC_GENERATOR_ID, SYNTHETIC_GENERATOR_VERSION, seed_block
        ),
        "seed_block": seed_block,
        "shared_contamination_author_batch_id": AUTHORING_PROCESS_ID,
        "candidate_artifact_id": f"candidate:{candidate_id}",
        "training_exclusion_id": f"qualification-exclusion:{candidate_id}",
    }


def instance_identity_formulas() -> dict[str, Any]:
    return {
        "candidate_id": (
            "PSE-V1-CANDIDATE:RES407:SYNTH:{capability}:{family}:{split}; no repeat ordinal"
        ),
        "source_family_id": "PSE-V1-SYNTHETIC-FAMILY:{candidate_id}",
        "isolation_cluster_id": "PSE-V1-SYNTHETIC-CLUSTER:PUBLIC_DEVELOPMENT",
        "generator_family": _C08_F05_FAMILY,
        "seed_namespace": (
            "PSE-V1/PUBLIC_DEVELOPMENT/pse-v1-unregistered-operation-context:1.0.0@{seed_block}"
        ),
        "seed_block": "{seed_block}",
        "contamination_identities": {
            "source_family": "PSE-V1-SYNTHETIC-FAMILY:{candidate_id}",
            "general_artifact": "candidate:{candidate_id}",
            "benchmark_artifact": "candidate:{candidate_id}",
            "training_exclusion": "qualification-exclusion:{candidate_id}",
            "expert_author_batch": AUTHORING_PROCESS_ID,
            "generator_seed_namespace": (
                "PSE-V1/PUBLIC_DEVELOPMENT/pse-v1-unregistered-operation-context:1.0.0@{seed_block}"
            ),
            "generator_seed_block": "{seed_block}",
            "source_documents_artifacts_constructs_and_provider_ids": (),
        },
        "shared_repeated_instance_groups": (
            "isolation cluster",
            "generator family",
            "contamination expert-author-batch",
        ),
    }


def relationship_semantics() -> dict[str, dict[str, str]]:
    return {
        "isolation_cluster_id": {
            "status": "GUARANTEED_COUPLED",
            "basis": (
                "All PUBLIC_DEVELOPMENT instances use PSE-V1-SYNTHETIC-CLUSTER:PUBLIC_DEVELOPMENT."
            ),
        },
        "SOURCE_FAMILY": {
            "status": "CONDITIONAL",
            "basis": (
                "PSE-V1-SYNTHETIC-FAMILY derives from candidate ID; unique repeat IDs "
                "are required, and the current helper has no repeat ordinal."
            ),
        },
        "GENERATOR_FAMILY": {
            "status": "GUARANTEED_COUPLED",
            "basis": "All F05 instances use pse-v1-synthetic-refusal-public_development.",
        },
        "GENERATOR_SEED_NAMESPACE": {
            "status": "CONDITIONAL",
            "basis": (
                "Distinct seed blocks produce distinct split-qualified namespaces; "
                "no 48-block allocation rule exists."
            ),
        },
        "GENERATOR_SEED_BLOCK": {
            "status": "CONDITIONAL",
            "basis": (
                "Reuse is rejected, but authority does not specify a repeat count "
                "or 48-block allocation."
            ),
        },
        "contamination_candidate_identities": {
            "status": "CONDITIONAL",
            "basis": (
                "Candidate artifacts, source-family IDs, and training-exclusion IDs "
                "derive from unique candidate IDs; 48 IDs are not allocated by the current helper."
            ),
        },
        "contamination_author_batch_identity": {
            "status": "GUARANTEED_COUPLED",
            "basis": (
                "The production refusal authoring path binds each instance to the "
                "same authoring-process identity."
            ),
        },
        "exact_13_token_shingles": {
            "status": "UNKNOWN",
            "basis": (
                "Seed changes do not prove distinct question shingles; text-dependent "
                "overlap is unqualified until materialization."
            ),
        },
        "CONDITIONAL_COLOCATION": {
            "status": "GUARANTEED_COUPLED",
            "basis": (
                "Shared split cluster, generator-family, and author-batch identities create "
                "co-location groups; exact-shingle groups remain unknown."
            ),
        },
    }


def summarize_existing_relations(problem: Any) -> dict[str, Any]:
    family_members = tuple(
        candidate
        for candidate in problem.candidates
        if any(
            identity.kind is IsolationIdentityKind.GENERATOR_FAMILY
            and identity.identity == _C08_F05_FAMILY
            for identity in candidate.isolation_identities
        )
    )
    cluster_id = f"PSE-V1-SYNTHETIC-CLUSTER:{_PUBLIC_SPLIT.value}"
    cluster_members = tuple(
        candidate
        for candidate in problem.candidates
        if candidate.isolation_cluster_id == cluster_id
    )
    family_ids = {item.candidate_id for item in family_members}
    cluster_ids = {item.candidate_id for item in cluster_members}
    target_ids = family_ids | cluster_ids
    relation_groups: Counter[str] = Counter()
    for constraint in problem.constraint_set.constraints:
        if constraint.kind is ConstraintKind.CONDITIONAL_COLOCATION and target_ids.intersection(
            constraint.candidate_ids
        ):
            relation_groups[constraint.relation_kind.value] += 1
    author_batch_matches = sum(
        any(
            identity.kind is IsolationIdentityKind.EXPERT_AUTHOR_BATCH
            and identity.identity == AUTHORING_PROCESS_ID
            for identity in candidate.isolation_identities
        )
        for candidate in problem.candidates
    )
    identity_counts = Counter(
        identity.kind.value
        for candidate in cluster_members
        for identity in candidate.isolation_identities
    )
    distinct_identity_counts = {
        kind: len(
            {
                identity.identity
                for candidate in cluster_members
                for identity in candidate.isolation_identities
                if identity.kind.value == kind
            }
        )
        for kind in (
            "source-family",
            "generator-family",
            "seed-namespace",
            "seed-block",
            "general-artifact",
            "benchmark-artifact",
            "training-exclusion",
        )
    }
    return {
        "candidate_count": len(problem.candidates),
        "problem_digest": problem.problem_digest,
        "matching_public_cluster_count": len(cluster_members),
        "matching_generator_family_count": len(family_members),
        "matching_f05_cell_count": sum(
            candidate.cell == ("C08", "F05") for candidate in cluster_members
        ),
        "matching_author_batch_count": author_batch_matches,
        "existing_cluster_identity_counts": dict(sorted(identity_counts.items())),
        "existing_cluster_distinct_identity_counts": distinct_identity_counts,
        "incident_conditional_colocation_group_counts": dict(sorted(relation_groups.items())),
        "incident_exact_shingle_group_count": relation_groups.get("EXACT_SHINGLE", 0),
        "new_to_existing_relation_semantics": {
            "isolation_cluster_id": "GUARANTEED_COUPLED_TO_4_EXISTING_CANDIDATES",
            "SOURCE_FAMILY": "INDEPENDENT_IF_A_UNIQUE_REPEAT_ID_IS_AUTHORIZED",
            "GENERATOR_FAMILY": "GUARANTEED_COUPLED_TO_4_EXISTING_CANDIDATES",
            "GENERATOR_SEED_NAMESPACE": "CONDITIONAL_ON_UNIQUE_AUTHORIZED_SEED_BLOCKS",
            "GENERATOR_SEED_BLOCK": "CONDITIONAL_ON_UNIQUE_AUTHORIZED_SEED_BLOCKS",
            "exact_13_token_shingles": "UNKNOWN_UNTIL_MATERIALIZATION",
            "contamination_candidate_identities": "INDEPENDENT_IF_REPEAT_IDS_ARE_UNIQUE",
            "contamination_author_batch_identity": "NO_MATCH_IN_EXISTING_449",
        },
        "seed_independence_conclusion": (
            "Fresh seed blocks distinguish seed identities only; shared split-cluster and "
            "generator-family identities still couple instances, and text independence is unknown."
        ),
        "finding": (
            "The existing 449-candidate pool has four PUBLIC_DEVELOPMENT synthetic C08 members "
            "sharing this generator family and split cluster; none has the new helper's "
            "candidate-ID-derived family."
        ),
    }


def check_exact_shingle_independence(
    new_questions: dict[str, str],
    existing_questions: dict[str, str],
) -> None:
    """Fail closed if any materialized question shingle repeats in new or existing text."""

    if set(new_questions).intersection(existing_questions):
        raise ValueError("materialized candidate ID collides with the existing pool")
    existing_shingles = {
        digest
        for question in existing_questions.values()
        for digest in exact_13_token_shingles(question)
    }
    new_shingles: set[str] = set()
    for question in new_questions.values():
        shingles = exact_13_token_shingles(question)
        if not shingles:
            raise ValueError("materialized question has no complete 13-token shingle")
        if shingles.intersection(existing_shingles | new_shingles):
            raise ValueError("exact 13-token shingle collision requires materialization rejection")
        new_shingles.update(shingles)


def capability_from_repeat_bound(
    maximum: int | None,
    required: int = _REQUIRED_OPTIMISTIC_COUNT,
) -> str:
    if maximum is not None and maximum < required:
        return "PROVABLY_INSUFFICIENT"
    return "UNRESOLVED"


def derive_qualification(
    structural_report: dict[str, Any],
    *,
    existing_relations: dict[str, Any],
    digest_verification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    target_row = next(
        item
        for item in structural_report["archetype_contract_inventory"]
        if item["lane_id"] == _C08_F05_LANE and item["cell"] == ["C08", "F05"]
    )
    real_features = derive_c08_f05_features()
    real_pairs = {(feature.kind.value, feature.key) for feature in real_features}
    optimistic = _optimistic_features(structural_report)
    optimistic_set = set(optimistic)
    feature_classification = tuple(
        {
            "kind": kind,
            "key": key,
            "classification": "GUARANTEED" if (kind, key) in real_pairs else "NOT_GUARANTEED",
        }
        for kind, key in optimistic
    )
    repeat = repeat_authority(target_row)
    max_count: int | None = (
        repeat["authorized_repeat_count_max"]
        if isinstance(repeat["authorized_repeat_count_max"], int)
        else None
    )
    vector_realizable = real_pairs.issuperset(optimistic_set)
    return {
        "schema_version": _SCHEMA,
        "mission": "RES-407 C08 generator contract qualification",
        "structural_comparison_report": STRUCTURAL_REPORT_PATH.as_posix(),
        "structural_comparison_report_receipt_digest": structural_report["receipt_digest"],
        "governed_archetype_contract_digest": structural_report[
            "governed_archetype_contract_digest"
        ],
        "authority_bindings": {
            "authority_ref": target_row["authority_ref"],
            "authority_digest": target_row["authority_digest"],
            "lane_id": target_row["lane_id"],
            "lane_digest": target_row["lane_digest"],
            "generator_family": target_row["generator_family"],
            "generator_id": target_row["generator_id"],
            "generator_version": target_row["generator_version"],
            "generator_contract": target_row["generator_contract"],
            "live_supply_inventory_digest": structural_report["live_supply_inventory_digest"],
            "locked_split": "PUBLIC_DEVELOPMENT",
            "identity_requirement_digests": target_row["isolation_guarantees"][
                "identity_requirement_digests"
            ],
        },
        "repeat_authority": repeat,
        "real_feature_contract_status": "PROVEN_FIXED_BY_CURRENT_AUTHORING_AND_SELECTION_LOGIC",
        "real_feature_contract_basis": (
            "The registry output_contract only promises non-numeric C08 refusal context. "
            "The additional fixed tag and error features are derived from the current F05 "
            "authoring path and scorer/selection adapters; the registry does not enumerate "
            "them as a complete feature vector."
        ),
        "real_feature_vector": tuple(_feature_wire(feature) for feature in real_features),
        "real_feature_vector_complete_in_persisted_archetype": target_row[
            "feature_vector_complete"
        ],
        "optimistic_feature_vector": tuple({"kind": kind, "key": key} for kind, key in optimistic),
        "optimistic_feature_classification": feature_classification,
        "optimistic_feature_dominance_status": (
            "YES" if vector_realizable else "NO_REAL_VECTOR_MISSES_OPTIMISTIC_FEATURES"
        ),
        "repeated_instance_independence_status": "GUARANTEED_COUPLED",
        "relation_semantics": relationship_semantics(),
        "instance_identity_formulas": instance_identity_formulas(),
        "existing_449_relation_summary": existing_relations,
        "shingle_independence": "CHECKABLE_AFTER_MATERIALIZATION",
        "shingle_materialization_gate": (
            "Before any production-store write, compute exact 13-token shingle hashes for all "
            "48 staged questions and the existing 449. Reject the full staged batch on any "
            "new-to-new or new-to-existing collision; do not infer independence from distinct "
            "seeds."
        ),
        "c08_48_realizability": (
            "PROVABLY_REALIZABLE" if vector_realizable else "PROVABLY_NOT_REALIZABLE"
        ),
        "current_c08_repair_capability": capability_from_repeat_bound(max_count),
        "current_c08_repair_capability_reason": (
            "The repeat maximum is unknown. The exact F05 optimistic vector is unrealizable, "
            "but that does not prove every mixed-cell C08 vector infeasible. No new search ran."
        ),
        "c08_48_materialization_plan_digest": None,
        "concrete_candidates_generated": 0,
        "seeds_generated": 0,
        "candidate_materialization_invoked": False,
        "optimization_or_candidate_subset_search_rerun": False,
        "digest_verification": digest_verification or {"status": "NOT_RUN"},
        "source_code_evidence": _source_code_digests(),
        "source_code_evidence_digest": canonical_hash(_source_code_digests()),
        "coverage_matrix_digest": coverage_manifest_digest(),
        "synthetic_generator_registry_digest": PRODUCTION_SYNTHETIC_GENERATOR_DIGEST,
        "next_step": (
            "Expand the C08 feature contract and define explicit repeat/seed-block allocation "
            "authority, then requalify before considering a 48-instance materialization."
        ),
        "ready_for_48_materialization": False,
        "ready_for_authority_expansion": True,
    }


def build_qualification_report() -> dict[str, Any]:
    structural_report = json.loads(
        (_REPOSITORY / STRUCTURAL_REPORT_PATH).read_text(encoding="utf-8")
    )
    digest_verification = verify_persisted_digests(structural_report)
    existing_relations = summarize_existing_relations(digest_verification["geometry"].problem)
    body = derive_qualification(
        structural_report,
        existing_relations=existing_relations,
        digest_verification={
            key: value
            for key, value in digest_verification.items()
            if key not in {"geometry", "archetype_record"}
        },
    )
    body["qualification_digest"] = canonical_hash(body)
    return body


def main() -> None:
    report = build_qualification_report()
    path = _REPOSITORY / QUALIFICATION_REPORT_PATH
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"C08_QUALIFICATION_DIGEST={report['qualification_digest']}")
    print("CONCRETE_CANDIDATES_GENERATED=0")
    print("SEEDS_GENERATED=0")


if __name__ == "__main__":
    main()
