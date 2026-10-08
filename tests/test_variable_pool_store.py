from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from dynamislm.benchmark import variable_pool_store as store
from dynamislm.benchmark.variable_pool import (
    ProductionAuthoringCandidatePoolV1,
    VariablePoolAuthoringPlanV1,
    historical_recipes_from_authoring_inputs,
    materialize_variable_pool,
)
from dynamislm.benchmark.variable_pool_store import VariablePoolStoreReceiptV1
from dynamislm.serialization import canonical_json
from test_variable_pool_materialization import _exclusion, _historical_inputs, _inventory


def _stored_fixture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[VariablePoolAuthoringPlanV1, ProductionAuthoringCandidatePoolV1, dict[str, Any]]:
    # The shared materialization fixture has six synthetic packets; these tests isolate
    # immutable store behavior, while the runner separately enforces the >=434 gate.
    monkeypatch.setattr(store, "validate_variable_pre_review_pool", lambda *_args, **_kwargs: None)
    historical_inputs = _historical_inputs()
    exclusion = _exclusion()
    inventory = _inventory()
    inventory = replace(
        inventory,
        evidence_bindings=tuple(
            sorted(
                (
                    *inventory.evidence_bindings,
                    ("QUALIFICATION_EXCLUSION_COMMITMENT", exclusion.commitment_digest),
                ),
                key=lambda item: item[0].encode(),
            )
        ),
        inventory_digest="",
    )
    plan = VariablePoolAuthoringPlanV1(
        supply_inventory_digest=inventory.inventory_digest,
        qualification_exclusion_digest=exclusion.commitment_digest,
        recipes=historical_recipes_from_authoring_inputs(historical_inputs),
    )
    pool = materialize_variable_pool(
        plan,
        supply_inventory=inventory,
        exclusion=exclusion,
        source_resolver=None,
        historical_inputs=historical_inputs,
    )
    repository_root = tmp_path / "repo"
    repository_root.mkdir()
    production_root = tmp_path / "external"
    production_root.mkdir()
    kwargs = {
        "supply_inventory": inventory,
        "exclusion": exclusion,
        "historical_input_digest": historical_inputs.input_digest,
        "repository_root": repository_root,
        "production_root": production_root,
        "source_resolver": None,
    }
    return plan, pool, kwargs


def _write(
    plan: VariablePoolAuthoringPlanV1,
    pool: ProductionAuthoringCandidatePoolV1,
    kwargs: dict[str, Any],
) -> VariablePoolStoreReceiptV1:
    return store.write_variable_pool_store(
        plan,
        pool,
        materialization_repository_head="a" * 40,
        **kwargs,
    )


def test_variable_pool_store_round_trips_and_identical_retry_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan, pool, kwargs = _stored_fixture(monkeypatch, tmp_path)
    receipt = _write(plan, pool, kwargs)

    assert _write(plan, pool, kwargs) == receipt
    restored_plan, restored_pool = store.read_variable_pool_store(receipt, **kwargs)
    assert restored_plan == plan
    assert restored_pool == pool
    assert (restored_plan.plan_digest, restored_pool.pool_digest) == (
        receipt.variable_pool_authoring_plan_digest,
        receipt.materialized_pool_digest,
    )
    receipt_json = canonical_json(receipt)
    for packet in restored_pool.packets:
        assert packet.question not in receipt_json
        assert canonical_json(packet.proposed_expected_answer) not in receipt_json
        for excerpt in packet.input.evidence_excerpts:
            assert excerpt.text not in receipt_json
    for _candidate_id, seed in _historical_inputs().scenario_seeds:
        assert seed not in receipt_json


def test_variable_pool_store_receipt_is_the_last_commit_marker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan, pool, kwargs = _stored_fixture(monkeypatch, tmp_path)
    writes: list[str] = []
    atomic_write = store._atomic_write_bytes  # type: ignore[attr-defined]

    def observe(path: Path, payload: bytes) -> None:
        writes.append(path.name)
        atomic_write(path, payload)

    monkeypatch.setattr(store, "_atomic_write_bytes", observe)
    receipt = _write(plan, pool, kwargs)
    assert writes[0] == "authoring-plan.json"
    assert writes[-1] == "receipt.json"
    assert receipt.receipt_digest


def test_variable_pool_store_retry_recovers_from_an_incomplete_pre_receipt_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan, pool, kwargs = _stored_fixture(monkeypatch, tmp_path)
    atomic_write = store._atomic_write_bytes  # type: ignore[attr-defined]
    interrupted = False

    def interrupt_after_plan(path: Path, payload: bytes) -> None:
        nonlocal interrupted
        atomic_write(path, payload)
        if path.name == "authoring-plan.json" and not interrupted:
            interrupted = True
            raise RuntimeError("simulated crash before candidate and receipt writes")

    monkeypatch.setattr(store, "_atomic_write_bytes", interrupt_after_plan)
    with pytest.raises(RuntimeError, match="simulated crash"):
        _write(plan, pool, kwargs)
    monkeypatch.setattr(store, "_atomic_write_bytes", atomic_write)

    receipt = _write(plan, pool, kwargs)
    assert store.read_variable_pool_store(receipt, **kwargs)[1] == pool


def test_variable_pool_store_fails_closed_on_conflicting_bytes_and_extra_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan, pool, kwargs = _stored_fixture(monkeypatch, tmp_path)
    receipt = _write(plan, pool, kwargs)
    root = Path(kwargs["production_root"])
    directory = root / receipt.store_relative_path
    candidate_id, _digest = receipt.candidate_file_digests[0]
    candidate_path = directory / "candidates" / store._candidate_filename(candidate_id)
    original = candidate_path.read_bytes()
    candidate_path.write_bytes(original + b" ")
    with pytest.raises(ValueError, match="different bytes"):
        _write(plan, pool, kwargs)

    candidate_path.write_bytes(original)
    (directory / "candidates" / "extra.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unexpected artifacts"):
        store.read_variable_pool_store(receipt, **kwargs)


def test_variable_pool_store_reader_rejects_symlinks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan, pool, kwargs = _stored_fixture(monkeypatch, tmp_path)
    receipt = _write(plan, pool, kwargs)
    directory = Path(kwargs["production_root"]) / receipt.store_relative_path
    packet_path = (
        directory / "candidates" / store._candidate_filename(receipt.candidate_file_digests[0][0])
    )
    payload = packet_path.read_bytes()
    target = directory / "outside.json"
    target.write_bytes(payload)
    packet_path.unlink()
    packet_path.symlink_to(target)

    with pytest.raises(ValueError, match="symlink"):
        store.read_variable_pool_store(receipt, **kwargs)


def test_variable_pool_store_refuses_a_root_inside_the_git_repository(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan, pool, kwargs = _stored_fixture(monkeypatch, tmp_path)
    repository_root = Path(kwargs["repository_root"])
    internal_root = repository_root / "production"
    with pytest.raises(ValueError, match="outside the public Git repository"):
        store.write_variable_pool_store(
            plan,
            pool,
            supply_inventory=kwargs["supply_inventory"],
            exclusion=kwargs["exclusion"],
            historical_input_digest=kwargs["historical_input_digest"],
            materialization_repository_head="a" * 40,
            repository_root=repository_root,
            production_root=internal_root,
            source_resolver=None,
        )
    assert not internal_root.exists()
