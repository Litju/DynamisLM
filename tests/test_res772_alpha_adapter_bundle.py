"""Offline artifact checks using synthetic stand-ins for the frozen inputs."""

import json
from pathlib import Path

import pytest
from scripts import alpha_adapter_bundle as bundle
from scripts.a02_v3_contract import sha256


@pytest.fixture
def source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "source"
    path.mkdir()
    base = bundle.base_reference()
    repo = base["id"].replace("/", "--")
    (path / "adapter_config.json").write_bytes(
        bundle.json_bytes(
            {
                "base_model_name_or_path": (
                    f"/content/a02/hf-cache/models--{repo}/snapshots/{base['revision']}"
                ),
                "revision": None,
                "r": 16,
                "lora_alpha": 32,
                "lora_dropout": 0.05,
                "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj"],
            }
        )
    )
    (path / "adapter_model.safetensors").write_bytes(b"synthetic stand-in, not model weights\n")
    (path / "metadata.json").write_bytes(
        bundle.json_bytes(
            {
                "schema": "SYNTHETIC_CHECKPOINT",
                "identity": {"source_identity": {"commit": "synthetic", "tree": "synthetic"}},
                "specification_sha256": "synthetic",
                "data_order_sha256": "synthetic",
                "next_step": 510,
                "target_tokens": 385600,
            }
        )
    )
    (path / "evaluation-binding.json").write_bytes(b'{"schema": "SYNTHETIC_EVALUATION"}\n')
    monkeypatch.setattr(
        bundle, "ADAPTER_FILES", {p.name: sha256(p.read_bytes()) for p in path.iterdir()}
    )
    return path


def test_release_config_changes_exactly_two_keys(source: Path) -> None:
    base = bundle.base_reference()
    original = (source / "adapter_config.json").read_bytes()
    release = bundle.derive_config(original, base)
    before, after = json.loads(original), json.loads(release)
    assert before.keys() == after.keys()
    assert {key for key in before if before[key] != after[key]} == {
        "base_model_name_or_path",
        "revision",
    }
    assert after["base_model_name_or_path"] == base["id"]
    assert after["revision"] == base["revision"]
    bundle.check_release_config(release, base)
    with pytest.raises(ValueError, match="source adapter_config.json"):
        bundle.derive_config(original + b" ", base)


def test_manifest_binds_identity_and_evidence(source: Path) -> None:
    base = bundle.base_reference()
    payload = {dest: (source / name).read_bytes() for name, dest in bundle.COPIED_FILES.items()}
    payload[bundle.CONFIG] = bundle.derive_config(
        (source / "adapter_config.json").read_bytes(), base
    )
    payload["LICENSE"] = bundle.PENDING_LICENSE
    manifest = json.loads(bundle.manifest(payload, base, False))
    assert manifest["schema"] == "DYNAMISLM_ADAPTER_BUNDLE_V1"
    assert manifest["base"] == base
    assert len(base["files"]) == 9
    assert len(base["tokenizer_files"]) == 4
    assert manifest["adapter"]["release_config_sha256"] == sha256(payload[bundle.CONFIG])
    assert manifest["training"]["completed_steps"] == 510
    assert manifest["training"]["synthetic_data"]["count"] == 2800
    assert manifest["evaluation"]["scope"] == "DEVELOPMENT_ONLY"
    assert manifest["evaluation"]["a02"]["decision"] == "ESCALATE_TO_STRONGER_MODEL_COMPARISON"
    assert manifest["distribution"] == "LICENSE_DECISION_REQUIRED"
    assert manifest["runtime"] == {
        "torch": "2.14.1",
        "transformers": "4.53.0",
        "peft": "0.16.0",
        "tokenizers": "0.21.1",
        "accelerate": "1.8.1",
        "safetensors": "0.5.3",
        "python": "CPython 3.13",
    }
