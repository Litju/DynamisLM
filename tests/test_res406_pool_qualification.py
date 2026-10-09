from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import res406_pool_qualification as qualification

from dynamislm.benchmark.selection_contracts import (
    POOL_FEASIBILITY_SOLVER_PROFILE_VERSION,
    PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1,
)


def test_checkpoint_receipt_is_atomic_and_digest_checked(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    production_root = tmp_path / "external"
    relative = "production/variable-pools/test/qualification/base-receipt.json"
    record = qualification._write_record(
        relative,
        {"schema_version": qualification._BASE_SCHEMA, "status": "FEASIBLE"},
        repository_root=repository_root,
        production_root=production_root,
    )

    restored = qualification._read_record(
        relative,
        repository_root=repository_root,
        production_root=production_root,
    )
    assert restored is not None
    assert restored[0] == record

    artifact = production_root / relative
    envelope = json.loads(artifact.read_text())
    envelope["payload"]["status"] = "UNKNOWN"
    artifact.write_text(json.dumps(envelope))
    with pytest.raises(ValueError, match="not canonical JSON|digest mismatch"):
        qualification._read_record(
            relative,
            repository_root=repository_root,
            production_root=production_root,
        )


def test_res406_uses_the_exact_named_pool_feasibility_profile() -> None:
    config = PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1
    assert (
        config.workers,
        config.random_seed,
        config.timeout_s,
        config.canonical_chunk_size,
        config.cp_model_presolve,
        config.randomize_search,
    ) == (8, 369, 120.0, 30, False, False)
    assert qualification.PROFILE_NAME == "PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1"
    assert qualification.PROFILE_VERSION == POOL_FEASIBILITY_SOLVER_PROFILE_VERSION
    assert qualification._profile() == {
        "name": "PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1",
        "version": "PSE-V1-POOL-FEASIBILITY-SOLVER@1.0.0",
        "workers": 8,
        "timeout_s": 120.0,
        "canonical_chunk_size": 30,
        "cp_model_presolve": False,
        "randomize_search": False,
        "random_seed": 369,
    }
    profile = qualification._profile(public=True)
    assert profile == {
        "name": "PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1",
        "version": "PSE-V1-POOL-FEASIBILITY-SOLVER@1.0.0",
        "workers": 8,
        "timeout_s": 120.0,
        "canonical_chunk_size": 30,
        "cp_model_presolve": False,
        "randomize_search": False,
    }
    assert "seed" not in " ".join(profile)


def test_checkpoint_namespace_is_outside_the_immutable_pool_directory() -> None:
    problem = SimpleNamespace(problem_digest="sha256:" + "1" * 64)
    checkpoint = qualification._checkpoint_root(problem)  # type: ignore[arg-type]
    plan_key = qualification.PLAN_DIGEST.removeprefix("sha256:")
    assert checkpoint.startswith(f"production/variable-pools/qualification/{plan_key}/")
    assert f"production/variable-pools/{plan_key}/qualification" not in checkpoint


def test_public_receipt_records_leak_evidence_and_unevaluated_reserve(tmp_path: Path) -> None:
    final = {
        "reserve_deficits": [{"deficit_kind": "EXACT_BASELINE_INFEASIBLE"}],
        "backfill_requests": [],
        "problem_digest": "sha256:" + "1" * 64,
        "base_status": "INFEASIBLE",
        "base_plan_digest": None,
        "base_validation_digest": None,
        "checked_removal_count": 0,
        "feasible_removal_count": 0,
        "infeasible_removal_count": 0,
        "unknown_removal_count": 0,
        "critical_obligation_count": None,
        "critical_obligations_with_structural_reserve": None,
        "critical_reserve_status": "NOT_EVALUATED",
        "backfill_needs": [],
        "fresh_process_confirmation": {"status": "PASS"},
        "artifact_inventory_digest": "sha256:" + "2" * 64,
        "receipt_digest": "sha256:" + "3" * 64,
        "checkpoint_path": "qualification/checkpoint",
        "outcome": "BASE_INFEASIBLE",
        "next": "STOP",
    }
    leak_guard = SimpleNamespace(
        status="PASS",
        repository_head="a" * 40,
        repository_artifact_digest="sha256:" + "4" * 64,
    )

    qualification._write_public_outputs(tmp_path, final, leak_guard)

    receipt = (tmp_path / qualification._PUBLIC_RECEIPT_PATH).read_text()
    assert "PUBLIC_LEAK_GUARD=PASS" in receipt
    assert f"PUBLIC_LEAK_GUARD_HEAD={'a' * 40}" in receipt
    assert f"PUBLIC_REPOSITORY_ARTIFACT_DIGEST={'sha256:' + '4' * 64}" in receipt
    assert "CRITICAL_OBLIGATION_COUNT=NOT_EVALUATED" in receipt
    assert "CRITICAL_WITH_STRUCTURAL_RESERVE=NOT_EVALUATED" in receipt
    assert "RESERVE_STATUS=NOT_EVALUATED" in receipt
    assert (
        "The base selection problem was INFEASIBLE; critical reserve was not evaluated." in receipt
    )
    assert "reported as structural pool capacity" not in receipt
