#!/usr/bin/env python3
"""Build or durably store the RES-405 variable pre-review pool."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from dynamislm.benchmark.authority_supply import (
    AUTHORITY_SUPPLY_SCHEMA,
    HISTORICAL_RECIPE_INPUT_BINDING,
    AuthoritySupplyInventoryV1,
    build_live_authority_supply_inventory,
)
from dynamislm.benchmark.constants import CaseOrigin
from dynamislm.benchmark.production_authoring import (
    ProductionAuthoringInputsV1,
    production_authoring_input_digest,
)
from dynamislm.benchmark.production_exclusions import (
    QUALIFICATION_PRIVATE_EXCLUSION_PATH,
    QualificationExclusionCommitmentV1,
    validate_qualification_exclusion_commitment,
)
from dynamislm.benchmark.production_store import (
    DEFAULT_PRODUCTION_ROOT,
    read_external_production_json,
)
from dynamislm.benchmark.public_repository import validate_production_private_material_absent
from dynamislm.benchmark.res115_authoring import build_res115_source_artifact_resolver
from dynamislm.benchmark.source_artifacts import PhaseASourceArtifactResolver
from dynamislm.benchmark.variable_pool import (
    ProductionAuthoringCandidatePoolV1,
    RecipeAuthorityBasis,
    VariablePoolAuthoringPlanV1,
    build_initial_variable_pool_authoring_plan,
    historical_recipes_from_authoring_inputs,
    materialize_variable_pool,
    validate_variable_pre_review_pool,
)
from dynamislm.benchmark.variable_pool_store import (
    DYNAMISLM_EXECUTION_BASELINE,
    VariablePoolStoreReceiptV1,
    read_variable_pool_store,
    write_variable_pool_store,
)
from dynamislm.serialization import canonical_json

_BRANCH = "julitocrztuga/res-405-p4a-r1-author-durably-store-the-variable-pre-review-pool"
_INPUT_PATH = "production/authoring_plan/private_inputs.json"
_SUMMARY_PATH = Path("reports/performance_science_eval/res405_variable_pre_review_pool.json")
_PUBLIC_RECEIPT_PATH = Path("docs/qualification/RES-405-ACCEPTANCE-RECEIPT.md")


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _git(repository_root: Path, *args: str) -> str:
    return subprocess.run(
        ("git", "-C", str(repository_root), *args),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _require_clean_execution_tree(repository_root: Path) -> str:
    head = _git(repository_root, "rev-parse", "HEAD")
    if _git(repository_root, "branch", "--show-current") != _BRANCH:
        raise ValueError("RES-405 runner is on the wrong branch")
    subprocess.run(
        (
            "git",
            "-C",
            str(repository_root),
            "merge-base",
            "--is-ancestor",
            DYNAMISLM_EXECUTION_BASELINE,
            head,
        ),
        check=True,
        capture_output=True,
    )
    result = subprocess.run(
        ("git", "-C", str(repository_root), "diff", "--quiet", "HEAD", "--"),
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise ValueError("RES-405 execution requires a clean tracked worktree")
    return head


def _read_inputs(
    repository_root: Path,
    production_root: Path,
) -> tuple[ProductionAuthoringInputsV1, QualificationExclusionCommitmentV1, str]:
    historical_inputs, input_file_digest, _input_size = read_external_production_json(
        _INPUT_PATH,
        ProductionAuthoringInputsV1,
        repository_root=repository_root,
        production_root=production_root,
    )
    exclusion, _exclusion_file_digest, _exclusion_size = read_external_production_json(
        QUALIFICATION_PRIVATE_EXCLUSION_PATH,
        QualificationExclusionCommitmentV1,
        repository_root=repository_root,
        production_root=production_root,
    )
    if historical_inputs.input_digest != production_authoring_input_digest(historical_inputs):
        raise ValueError("historical input digest differs from its canonical content")
    validate_qualification_exclusion_commitment(exclusion)
    return historical_inputs, exclusion, input_file_digest


def _build_authority(
    repository_root: Path,
    production_root: Path,
) -> tuple[
    AuthoritySupplyInventoryV1,
    ProductionAuthoringInputsV1,
    QualificationExclusionCommitmentV1,
    PhaseASourceArtifactResolver,
    Path,
]:
    historical_inputs, exclusion, input_file_digest = _read_inputs(repository_root, production_root)
    inventory = build_live_authority_supply_inventory(
        repository_root=repository_root,
        production_root=production_root,
    )
    if inventory.schema_version != AUTHORITY_SUPPLY_SCHEMA:
        raise ValueError("RES-405 requires the rebuilt v1.3.0 authority supply inventory")
    if (
        inventory.evidence_binding(HISTORICAL_RECIPE_INPUT_BINDING)
        != historical_inputs.input_digest
    ):
        raise ValueError("historical input digest differs from the inventory binding")
    if inventory.evidence_binding("HISTORICAL_RECIPE_INPUT_FILE") != input_file_digest:
        raise ValueError("historical input file bytes differ from the inventory binding")
    if (
        inventory.evidence_binding("QUALIFICATION_EXCLUSION_COMMITMENT")
        != exclusion.commitment_digest
    ):
        raise ValueError("qualification exclusion digest differs from the inventory binding")
    source_resolver = build_res115_source_artifact_resolver()
    external_root = source_resolver.retained_source_root.parents[1]
    if external_root.resolve() != production_root.resolve():
        raise ValueError(
            "Phase-A source authority and production inputs must share one external root"
        )
    return inventory, historical_inputs, exclusion, source_resolver, external_root


def _derive_and_validate(
    repository_root: Path,
    production_root: Path,
) -> tuple[
    VariablePoolAuthoringPlanV1,
    ProductionAuthoringCandidatePoolV1,
    AuthoritySupplyInventoryV1,
    ProductionAuthoringInputsV1,
    QualificationExclusionCommitmentV1,
    PhaseASourceArtifactResolver,
    Path,
]:
    inventory, historical_inputs, exclusion, source_resolver, external_root = _build_authority(
        repository_root, production_root
    )
    plan = build_initial_variable_pool_authoring_plan(
        historical_inputs,
        inventory,
        exclusion,
        external_root=external_root,
    )
    historical = historical_recipes_from_authoring_inputs(historical_inputs)
    planned_historical = tuple(
        item
        for item in plan.recipes
        if item.authority_basis is RecipeAuthorityBasis.HISTORICAL_INDIVIDUAL_RECIPE
    )
    if planned_historical != historical:
        raise ValueError("initial plan differs from the exact canonical historical recipe set")
    pool = materialize_variable_pool(
        plan,
        supply_inventory=inventory,
        exclusion=exclusion,
        source_resolver=source_resolver,
        historical_inputs=historical_inputs,
        external_root=external_root,
    )
    validate_variable_pre_review_pool(
        pool,
        exclusion=exclusion,
        source_resolver=source_resolver,
    )
    if (
        pool.candidate_count != plan.candidate_count
        or pool.authoring_plan_digest != plan.plan_digest
    ):
        raise ValueError("validated pool does not match the exact initial authoring plan")
    if (
        build_live_authority_supply_inventory(
            repository_root=repository_root,
            production_root=production_root,
        )
        != inventory
    ):
        raise ValueError("v1.3 authority supply inventory could not be rebuilt exactly")
    return (
        plan,
        pool,
        inventory,
        historical_inputs,
        exclusion,
        source_resolver,
        external_root,
    )


def _counts(values: tuple[tuple[Any, int], ...]) -> dict[str, int]:
    return {key.value: count for key, count in values}


def _public_summary(
    pool: ProductionAuthoringCandidatePoolV1,
    receipt: VariablePoolStoreReceiptV1,
) -> dict[str, object]:
    return {
        "mission": "RES-405",
        "execution_baseline": receipt.execution_baseline,
        "materialization_code_head": receipt.materialization_repository_head,
        "variable_pool_authoring_plan_digest": receipt.variable_pool_authoring_plan_digest,
        "materialized_pool_digest": receipt.materialized_pool_digest,
        "private_store_receipt_digest": receipt.receipt_digest,
        "supply_inventory_digest": receipt.supply_inventory_digest,
        "qualification_exclusion_digest": receipt.qualification_exclusion_digest,
        "observed_candidate_count": pool.candidate_count,
        "origin_counts": _counts(receipt.origin_counts),
        "authority_basis_counts": _counts(receipt.authority_basis_counts),
        "governed_additions_by_origin": _counts(receipt.governed_additions_by_origin),
        "validation_status": "PASS",
    }


def _write_public_exact(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise ValueError(f"RES-405 public artifact conflicts with existing bytes: {path}")
        return
    path.write_bytes(payload)


def _write_public_outputs(
    repository_root: Path,
    pool: ProductionAuthoringCandidatePoolV1,
    receipt: VariablePoolStoreReceiptV1,
) -> tuple[Path, Path]:
    summary = _public_summary(pool, receipt)
    summary_bytes = (
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    lines = (
        "# RES-405 Acceptance Receipt",
        "",
        "```text",
        "MISSION=RES-405",
        "STATUS=PASS",
        f"DYNAMISLM_EXECUTION_BASELINE={receipt.execution_baseline}",
        f"MATERIALIZATION_CODE_HEAD={receipt.materialization_repository_head}",
        f"PLAN_DIGEST={receipt.variable_pool_authoring_plan_digest}",
        f"POOL_DIGEST={receipt.materialized_pool_digest}",
        f"PRIVATE_STORE_RECEIPT_DIGEST={receipt.receipt_digest}",
        f"SUPPLY_INVENTORY_DIGEST={receipt.supply_inventory_digest}",
        f"QUALIFICATION_EXCLUSION_DIGEST={receipt.qualification_exclusion_digest}",
        f"OBSERVED_CANDIDATE_COUNT={pool.candidate_count}",
        f"ORIGIN_COUNTS={json.dumps(_counts(receipt.origin_counts), sort_keys=True)}",
        "AUTHORITY_BASIS_COUNTS="
        + json.dumps(_counts(receipt.authority_basis_counts), sort_keys=True),
        "GOVERNED_ADDITIONS_BY_ORIGIN="
        + json.dumps(_counts(receipt.governed_additions_by_origin), sort_keys=True),
        "VARIABLE_POOL_VALIDATION=PASS",
        "ROUND_TRIP=PASS",
        "PUBLIC_LEAK_GUARD=PASS",
        "SOLVER_RUNS=0",
        "HUMAN_REVIEW_PERFORMED=NO",
        "FINAL_SPLITS_ALLOCATED=NO",
        "```",
        "",
        "The observed count and origin mix report current v1.3 authority;",
        "neither is a pool target.",
        "Private candidate packets and source text remain in the external variable-pool store.",
        "",
    )
    receipt_bytes = "\n".join(lines).encode("utf-8")
    summary_path = repository_root / _SUMMARY_PATH
    public_receipt_path = repository_root / _PUBLIC_RECEIPT_PATH
    _write_public_exact(summary_path, summary_bytes)
    _write_public_exact(public_receipt_path, receipt_bytes)
    return summary_path, public_receipt_path


def _private_material(
    plan: VariablePoolAuthoringPlanV1,
    pool: ProductionAuthoringCandidatePoolV1,
    historical_inputs: ProductionAuthoringInputsV1,
    exclusion: QualificationExclusionCommitmentV1,
) -> tuple[tuple[str, str], ...]:
    private: list[tuple[str, str]] = [
        ("private historical authoring input", canonical_json(historical_inputs)),
        ("private qualification exclusion", canonical_json(exclusion)),
        ("private variable pool authoring plan", canonical_json(plan)),
    ]
    for packet in pool.packets:
        private.extend(
            (
                ("private variable pool packet", canonical_json(packet)),
                ("private candidate question", packet.question),
                (
                    "private candidate expected answer",
                    canonical_json(packet.proposed_expected_answer),
                ),
                ("private candidate input", canonical_json(packet.input)),
            )
        )
        private.extend(
            ("private candidate JATS evidence span", excerpt.text)
            for excerpt in packet.input.evidence_excerpts
        )
        provenance = packet.proposed_provenance
        for name in ("seed_namespace", "seed_block"):
            value = getattr(provenance, name)
            if value is not None:
                private.append((f"private candidate {name}", value))
        if provenance.mutation_seed is not None:
            private.append(("private candidate mutation seed", str(provenance.mutation_seed)))
    return tuple(private)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("dry-run", "materialize"))
    parser.add_argument("--production-root", type=Path, default=DEFAULT_PRODUCTION_ROOT)
    return parser.parse_args()


def main() -> int:
    arguments = _arguments()
    repository_root = _repository_root()
    production_root = arguments.production_root.resolve()
    materialization_head = _require_clean_execution_tree(repository_root)

    (
        plan,
        pool,
        inventory,
        historical_inputs,
        exclusion,
        source_resolver,
        external_root,
    ) = _derive_and_validate(repository_root, production_root)
    result = {
        "DYNAMISLM_EXECUTION_BASELINE": DYNAMISLM_EXECUTION_BASELINE,
        "MATERIALIZATION_CODE_HEAD": materialization_head,
        "PLAN_DIGEST": plan.plan_digest,
        "POOL_DIGEST": pool.pool_digest,
        "SUPPLY_INVENTORY_DIGEST": inventory.inventory_digest,
        "QUALIFICATION_EXCLUSION_DIGEST": exclusion.commitment_digest,
        "HISTORICAL_INPUT_DIGEST": historical_inputs.input_digest,
        "HISTORICAL_RECIPE_COUNT": sum(
            recipe.authority_basis is RecipeAuthorityBasis.HISTORICAL_INDIVIDUAL_RECIPE
            for recipe in plan.recipes
        ),
        "GOVERNED_SOURCE_ADDITION_COUNT": sum(
            recipe.authority_basis is RecipeAuthorityBasis.GOVERNED_SUPPLY_LANE
            and recipe.origin_class is CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION
            for recipe in plan.recipes
        ),
        "TOTAL_POOL_COUNT": pool.candidate_count,
        "ORIGIN_COUNTS": _counts(
            tuple(
                Counter(packet.proposed_provenance.origin_class for packet in pool.packets).items()
            )
        ),
        "AUTHORITY_BASIS_COUNTS": _counts(
            tuple(Counter(recipe.authority_basis for recipe in plan.recipes).items())
        ),
        "VALIDATION_STATUS": "PASS",
        "SOLVER_RUNS": 0,
    }
    if arguments.action == "dry-run":
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0

    if _require_clean_execution_tree(repository_root) != materialization_head:
        raise ValueError("tracked repository head changed during RES-405 materialization")
    receipt = write_variable_pool_store(
        plan,
        pool,
        supply_inventory=inventory,
        exclusion=exclusion,
        historical_input_digest=historical_inputs.input_digest,
        materialization_repository_head=materialization_head,
        repository_root=repository_root,
        production_root=production_root,
        source_resolver=source_resolver,
    )
    stored_plan, stored_pool = read_variable_pool_store(
        receipt,
        supply_inventory=inventory,
        exclusion=exclusion,
        historical_input_digest=historical_inputs.input_digest,
        repository_root=repository_root,
        production_root=production_root,
        source_resolver=source_resolver,
    )
    regenerated = materialize_variable_pool(
        stored_plan,
        supply_inventory=inventory,
        exclusion=exclusion,
        source_resolver=source_resolver,
        historical_inputs=historical_inputs,
        external_root=external_root,
    )
    validate_variable_pre_review_pool(
        regenerated,
        exclusion=exclusion,
        source_resolver=source_resolver,
    )
    if regenerated != stored_pool or tuple(
        canonical_json(packet) for packet in regenerated.packets
    ) != tuple(canonical_json(packet) for packet in stored_pool.packets):
        raise ValueError("stored variable pool differs from in-memory authority regeneration")

    summary_path, public_receipt_path = _write_public_outputs(repository_root, stored_pool, receipt)
    leak_guard = validate_production_private_material_absent(
        _private_material(stored_plan, stored_pool, historical_inputs, exclusion),
        repository_root=repository_root,
        candidate_count=stored_pool.candidate_count,
    )
    print(
        json.dumps(
            {
                **result,
                "PRIVATE_STORE_RECEIPT_DIGEST": receipt.receipt_digest,
                "EXTERNAL_STORE_PATH": receipt.store_relative_path,
                "PUBLIC_SUMMARY_PATH": summary_path.relative_to(repository_root).as_posix(),
                "PUBLIC_RECEIPT_PATH": public_receipt_path.relative_to(repository_root).as_posix(),
                "ROUND_TRIP": "PASS",
                "PUBLIC_LEAK_GUARD": "PASS",
                "PUBLIC_REPOSITORY_ARTIFACT_DIGEST": leak_guard.repository_artifact_digest,
            },
            sort_keys=True,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
