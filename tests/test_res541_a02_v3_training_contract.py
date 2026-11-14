"""CPU-only training admission and archive negative controls; no model/weights loaded (RES-541)."""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import pytest
from scripts import a02_v3_decision as decision
from scripts import a02_v3_remote as remote
from scripts import a02_v3_training as training


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
