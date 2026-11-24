"""Build and verify the frozen step-510 adapter bundle without model execution."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.a02_v3_contract import json_object, sha256
from scripts.a03_d0_runtime import ADAPTER_FILES, MODEL_FILES, RUNTIME

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "DYNAMISLM_ADAPTER_BUNDLE_V1"
DISTRIBUTION = "LICENSE_DECISION_REQUIRED"
PENDING_LICENSE = (
    b"LICENSE_DECISION_REQUIRED\nSee RES-771 D2 for the owner's distribution decision.\n"
)
COPIED_FILES = {
    "adapter_model.safetensors": "adapter/adapter_model.safetensors",
    "metadata.json": "provenance/metadata.json",
    "evaluation-binding.json": "provenance/evaluation-binding.json",
}
CONFIG = "adapter/adapter_config.json"


def read_object(path: Path) -> dict[str, Any]:
    return json_object(path.read_text(encoding="utf-8"))


def json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, indent=2, sort_keys=True, allow_nan=False).encode()


def base_reference() -> dict[str, Any]:
    pins = read_object(ROOT / "experiments/a02/tokenizer-files-v1.json")
    return {
        "id": pins["model_id"],
        "revision": pins["model_revision"],
        "files": MODEL_FILES | pins["files"],
        "tokenizer_files": sorted(pins["files"]),
    }


def check_digest(data: bytes, expected: str, name: str) -> None:
    if sha256(data) != expected:
        raise ValueError(f"SHA-256 differs: {name}")


def derive_config(source: bytes, base: dict[str, Any]) -> bytes:
    check_digest(source, ADAPTER_FILES["adapter_config.json"], "source adapter_config.json")
    config = json_object(source.decode())
    config.update(base_model_name_or_path=base["id"], revision=base["revision"])
    return json_bytes(config) + b"\n"


def check_release_config(release: bytes, base: dict[str, Any]) -> None:
    config = json_object(release.decode())
    if config.get("base_model_name_or_path") != base["id"]:
        raise ValueError("release adapter base model differs")
    if config.get("revision") != base["revision"]:
        raise ValueError("release adapter base revision differs")
    # Reconstruct the exact frozen PEFT JSON so the original config stays outside the bundle.
    repo = base["id"].replace("/", "--")
    config.update(
        base_model_name_or_path=f"/content/a02/hf-cache/models--{repo}/snapshots/{base['revision']}",
        revision=None,
    )
    if derive_config(json_bytes(config), base) != release:
        raise ValueError("release adapter configuration bytes differ")


def manifest(payload: dict[str, bytes], base: dict[str, Any], supplied_license: bool) -> bytes:
    metadata = json_object(payload["provenance/metadata.json"].decode())
    config = json_object(payload[CONFIG].decode())
    protocol = read_object(ROOT / "experiments/a02/model-comparison-protocol-v3.json")
    colab = dict(
        line.split("==", 1)
        for line in (ROOT / "experiments/a0/requirements-colab.txt").read_text().splitlines()
        if "==" in line
    )
    return (
        json_bytes(
            {
                "schema": SCHEMA,
                "base": base,
                "adapter": {
                    "weights_sha256": ADAPTER_FILES["adapter_model.safetensors"],
                    "source_config_sha256": ADAPTER_FILES["adapter_config.json"],
                    "release_config_sha256": sha256(payload[CONFIG]),
                    "metadata_sha256": ADAPTER_FILES["metadata.json"],
                    "evaluation_binding_sha256": ADAPTER_FILES["evaluation-binding.json"],
                },
                "training": {
                    "checkpoint_schema": metadata["schema"],
                    "source": metadata["identity"],
                    "specification_sha256": metadata["specification_sha256"],
                    "data_order_sha256": metadata["data_order_sha256"],
                    "completed_steps": metadata["next_step"],
                    "target_tokens": metadata["target_tokens"],
                    "synthetic_data": protocol["data"]["training"],
                    "lora": {
                        key: config[key]
                        for key in ("r", "lora_alpha", "lora_dropout", "target_modules")
                    },
                },
                "evaluation": {
                    "scope": "DEVELOPMENT_ONLY",
                    "a02": {
                        "decision": "ESCALATE_TO_STRONGER_MODEL_COMPARISON",
                        "heldout": protocol["data"]["heldout_evaluation"],
                    },
                    "d0": {
                        "issue": "RES-745",
                        "status": "D0_COMPLETE",
                        "checkpoint_sha256": (
                            "6c0c811db4e641c7ef9e24a9fa81c904882fb6c5e8c6337d3ce04fca6eaeab2d"
                        ),
                    },
                    "res746": {
                        "issue": "RES-746",
                        "status": "PASS_EXPOSED_REAL_MODEL_QUALIFICATION",
                        "cpu_output_commit_sha256": (
                            "0257d95442c2fa491a7d03f1d9df2cc95bb14e2459d4ff2d102eda256b068e87"
                        ),
                        "t4_output_commit_sha256": (
                            "d438b6da65fa6c878122a41ab61ed538b0a81f37a8b99f4f2f92df1ec9f1100a"
                        ),
                    },
                },
                "runtime": {
                    **RUNTIME,
                    "torch": RUNTIME["torch"].split("+", 1)[0],
                    "accelerate": colab["accelerate"],
                    "safetensors": colab["safetensors"],
                    "python": "CPython 3.13",
                },
                "distribution": DISTRIBUTION,
                "license": {
                    "authority": "RES-771 D2",
                    "supplied": supplied_license,
                    "sha256": sha256(payload["LICENSE"]),
                },
            }
        )
        + b"\n"
    )
