"""CPU-only training admission and archive negative controls; no model/weights loaded (RES-541)."""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path
from typing import Any, cast

import pytest
from scripts import a02_v3_decision as decision
from scripts import a02_v3_execution as execution
from scripts import a02_v3_remote as remote
from scripts import a02_v3_training as training
from scripts import a02_v3_worker as worker


def test_training_runtime_binding_is_explicit_and_excludes_inference_cost_placeholders(
    tmp_path: Path,
) -> None:
    binding = {
        "schema": remote.TRAINING_BINDING_SCHEMA,
        "source_archive_sha256": "c" * 64,
        "source_identity": {"commit": "a" * 40, "tree": "b" * 40},
        "source_revision": "a" * 40,
        "plan_sha256": "d" * 64,
        "protocol_sha256": decision.protocol_sha256(),
        "session_index": 1,
        "training_spec": training.specification(),
        "training_checkpoint_sha256": None,
    }
    path = tmp_path / "binding.json"
    path.write_text(json.dumps(binding))
    assert remote.load_binding(path) == binding
    binding["item_cost_bounds"] = {"QUALIFICATION": 1}
    path.write_text(json.dumps(binding))
    with pytest.raises(ValueError, match="fields"):
        remote.load_binding(path)


def test_training_profile_drift_rejected_before_any_model_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = training.specification()
    spec["training"]["split"] = "HELDOUT"
    monkeypatch.setattr(
        remote,
        "load_binding",
        lambda: {"protocol_sha256": decision.protocol_sha256(), "training_spec": spec},
    )
    with pytest.raises(ValueError, match="training specification"):
        remote.child("work", 60)


@pytest.mark.parametrize("name", ["../metadata.json", "/absolute", "adapter_model.safetensors"])
def test_training_unpack_refuses_unsafe_or_incomplete_archive(tmp_path: Path, name: str) -> None:
    archive = tmp_path / "checkpoint.tar"
    with tarfile.open(archive, "w:") as handle:
        member = tarfile.TarInfo(name)
        member.size = 1
        handle.addfile(member, io.BytesIO(b"x"))
    with pytest.raises(ValueError, match="unsafe or incomplete"):
        training.unpack(archive, tmp_path / "out")


def test_final_adapter_work_list_preserves_registered_examples_and_baseline() -> None:
    protocol = decision.load_protocol()
    baseline = worker.work_items(protocol)
    before = worker.work_list_sha256(baseline)
    adapted = training.adapted_work_items(protocol)
    assert len(adapted) == 581
    assert [x.key for x in adapted] == [x.key for x in baseline]
    assert adapted[0].key == "QUALIFICATION"
    assert {x.arm for x in adapted} == {"ADAPTED_UNCONSTRAINED", "ADAPTED_CONSTRAINED"}
    assert worker.work_list_sha256(worker.work_items(protocol)) == before


def test_adapted_binding_requires_both_weight_and_config_digests(tmp_path: Path) -> None:
    binding = {
        "schema": remote.ADAPTED_BINDING_SCHEMA,
        "source_archive_sha256": "c" * 64,
        "source_identity": {"commit": "a" * 40, "tree": "b" * 40},
        "source_revision": "a" * 40,
        "plan_sha256": "d" * 64,
        "protocol_sha256": decision.protocol_sha256(),
        "session_index": 1,
        "precision": "float32",
        "numerical_amendment_sha256": "e" * 64,
        "native_cache": True,
        "adapter_sha256": "f" * 64,
        "adapter_config_sha256": "1" * 64,
        "item_cost_bounds": {
            "QUALIFICATION": 10,
            "ADAPTED_UNCONSTRAINED": 2,
            "ADAPTED_CONSTRAINED": 3,
        },
    }
    path = tmp_path / "binding.json"
    path.write_text(json.dumps(binding))
    assert remote.load_binding(path) == binding
    binding["adapter_sha256"] = "not a digest"
    path.write_text(json.dumps(binding))
    with pytest.raises(ValueError, match="adapter identity"):
        remote.load_binding(path)
    del binding["adapter_sha256"]
    path.write_text(json.dumps(binding))
    with pytest.raises(ValueError, match="fields"):
        remote.load_binding(path)


def test_adapter_swap_rejected_before_any_provider_call(tmp_path: Path) -> None:
    (tmp_path / "adapter_model.safetensors").write_bytes(b"SYNTHETIC wrong adapter")
    with pytest.raises(execution.AdmissionError, match="adapter bytes differ"):
        execution.run_session(
            client=cast(Any, None),
            plan={},
            ledger_path=tmp_path / "ledger.json",
            authorization=None,
            session_index=1,
            run_dir=tmp_path,
            source_archive=tmp_path / "source.tar",
            binding={"adapter_sha256": "f" * 64},
            final_adapter=tmp_path,
        )
