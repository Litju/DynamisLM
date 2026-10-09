from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts import res406_pool_qualification as qualification


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


def test_production_public_profile_omits_random_seed() -> None:
    profile = qualification._profile(public=True)
    assert profile == {
        "name": "PSE_V1_PRODUCTION_SELECTION_SOLVER_PROFILE_V2",
        "version": "PSE-V1-PRODUCTION-SELECTION-SOLVER@2.0.0",
        "workers": 8,
        "timeout_s": 120.0,
        "canonical_chunk_size": 15,
        "cp_model_presolve": False,
        "randomize_search": False,
    }
    assert "seed" not in " ".join(profile)
