"""Prospective FP32 campaign binding retains all frozen scientific bytes (RES-541)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts import a02_v3_decision as decision
from scripts import a02_v3_execution as execution
from scripts import a02_v3_gpu_diagnostic as diagnostic
from scripts import a02_v3_remote as remote


def test_fp32_campaign_binding_is_explicit_and_source_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = {"commit": "a" * 40, "tree": "b" * 40}
    monkeypatch.setattr(execution, "source_identity", lambda: identity)
    archive = tmp_path / "synthetic-source.tar"
    archive.write_bytes(b"synthetic source fixture")
    plan = {
        "plan_sha256": "c" * 64,
        "protocol_sha256": decision.protocol_sha256(),
        "item_cost_bounds_seconds": {
            "QUALIFICATION": 1,
            "ZERO_SHOT_UNCONSTRAINED": 1,
            "ZERO_SHOT_CONSTRAINED": 1,
        },
    }
    historical = execution.remote_binding(plan, archive, identity["commit"])
    assert historical["schema"] == remote.BINDING_SCHEMA
    assert "precision" not in historical
    binding = execution.remote_binding(plan, archive, identity["commit"], precision="float32")
    assert binding["source_identity"] == identity
    assert binding["numerical_amendment_sha256"] == diagnostic.specification()["amendment_sha256"]
    assert binding["protocol_sha256"] == historical["protocol_sha256"]
    binding["session_index"] = 1
    path = tmp_path / "binding.json"
    path.write_text(json.dumps(binding))
    assert remote.load_binding(path) == binding
    old_path = tmp_path / "historical.json"
    old_path.write_text(json.dumps({**historical, "session_index": 1}))
    assert remote.load_binding(old_path)["schema"] == remote.BINDING_SCHEMA
    binding["precision"] = "float16"
    path.write_text(json.dumps(binding))
    with pytest.raises(ValueError, match="FP32"):
        remote.load_binding(path)
    with pytest.raises(ValueError, match="precision"):
        execution.remote_binding(plan, archive, identity["commit"], precision="bfloat16")


def test_changed_numerical_amendment_is_rejected_before_torch_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = {
        "precision": "float32",
        "numerical_amendment_sha256": "0" * 64,
        "protocol_sha256": decision.protocol_sha256(),
    }
    monkeypatch.setattr(remote, "load_binding", lambda: binding)
    with pytest.raises(ValueError, match="amendment differs"):
        remote.child("work", 60)


def test_native_cache_binding_is_explicit_fp32_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = {"commit": "a" * 40, "tree": "b" * 40}
    monkeypatch.setattr(execution, "source_identity", lambda: identity)
    archive = tmp_path / "source.tar"
    archive.write_bytes(b"synthetic")
    plan = {
        "plan_sha256": "c" * 64,
        "protocol_sha256": decision.protocol_sha256(),
        "item_cost_bounds_seconds": {
            "QUALIFICATION": 1,
            "ZERO_SHOT_UNCONSTRAINED": 1,
            "ZERO_SHOT_CONSTRAINED": 1,
        },
    }
    binding = execution.remote_binding(
        plan, archive, identity["commit"], precision="float32", native_cache=True
    )
    assert (
        binding["native_cache"] is True and binding["schema"] == remote.NATIVE_CACHE_BINDING_SCHEMA
    )
    binding["session_index"] = 1
    path = tmp_path / "binding.json"
    path.write_text(json.dumps(binding))
    assert remote.load_binding(path) == binding
    binding["native_cache"] = False
    path.write_text(json.dumps(binding))
    with pytest.raises(ValueError, match="cache execution"):
        remote.load_binding(path)
    with pytest.raises(ValueError, match="FP32"):
        execution.remote_binding(plan, archive, identity["commit"], native_cache=True)
