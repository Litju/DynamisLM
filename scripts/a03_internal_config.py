"""Load and verify the frozen RES-773 internal evaluation configuration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "experiments/a03/internal-config-v1.json"
PROTOCOL_PATH = ROOT / "experiments/a03/internal-protocol-v1.md"
CONFIG_SHA256 = "0727b738f1ac68d65df39ea8cd353b812e4249de5d65af7003657253443f705c"
PROTOCOL_SHA256 = "6f72b9352994d84bab6d7e5994c11ba8be46a3fb597b56444226fe357b85245f"
V2_CONFIG = ROOT / "experiments/a03/internal-config-v2.json"
V2_PROTOCOL = ROOT / "experiments/a03/internal-protocol-v2.md"
V2_CONFIG_SHA256 = "4d4892bc7b7a05f95141867d70b22520b6582b85bc2266365c95d42ead22a97d"
V2_PROTOCOL_SHA256 = "cbe4d22c8332b8ca743810bc42bc054679230a9b99ee44fe35ccaced867f2bb2"
AUTHORSHIP = "AI_ASSISTED_OWNER_ADJUDICATED"
SCHEMA = "DYNAMISLM_A03_INTERNAL_CONFIG_V1"
MODE = "INTERNAL_OWNER_ADJUDICATED"
EVIDENCE_CLASS = "INTERNAL_OWNER_ADJUDICATED"
INDEPENDENCE = "NONE"
PASS, NO_GO, INCONCLUSIVE = "INTERNAL_PASS", "INTERNAL_NO_GO", "INTERNAL_INCONCLUSIVE"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(
        value, allow_nan=False, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )


def load_config(path: Path = CONFIG_PATH, protocol: Path = PROTOCOL_PATH) -> dict[str, Any]:
    """Return the frozen configuration after proving its bytes, protocol and canonical form."""
    for candidate in (path, protocol):
        if candidate.is_symlink() or not candidate.is_file():
            raise ValueError("internal configuration inputs must be regular files")
    data = path.read_bytes()
    if sha256(data) != CONFIG_SHA256:
        raise ValueError("internal configuration differs from its pinned digest")
    if sha256(protocol.read_bytes()) != PROTOCOL_SHA256:
        raise ValueError("internal protocol differs from its pinned digest")
    config = json.loads(data.decode("utf-8"))
    if (canonical(config) + "\n").encode() != data:
        raise ValueError("internal configuration is not canonical")
    if (
        config.get("schema") != SCHEMA
        or config["protocol_sha256"] != PROTOCOL_SHA256
        or config["mode"] != MODE
        or config["evidence_class"] != EVIDENCE_CLASS
        or config["independence"] != INDEPENDENCE
    ):
        raise ValueError("internal configuration identity differs")
    return config  # type: ignore[no-any-return]


def load_amendment(path: Path = V2_CONFIG, protocol: Path = V2_PROTOCOL) -> dict[str, Any]:
    for candidate in (path, protocol):
        if candidate.is_symlink() or not candidate.is_file():
            raise ValueError("internal amendment inputs must be regular files")
    data = path.read_bytes()
    expected = {
        "schema": "DYNAMISLM_A03_INTERNAL_CONFIG_V2",
        "authorship": AUTHORSHIP,
        "base_config_sha256": CONFIG_SHA256,
        "base_protocol_sha256": PROTOCOL_SHA256,
        "protocol_sha256": V2_PROTOCOL_SHA256,
        "owner_decision_comment_id": "2490dfe7-c10d-4f35-8541-007b3e510db8",
    }
    if (
        sha256(data) != V2_CONFIG_SHA256
        or sha256(protocol.read_bytes()) != V2_PROTOCOL_SHA256
        or data != (canonical(expected) + "\n").encode()
    ):
        raise ValueError("internal amendment differs from its pinned identity")
    return expected


def version_for(record: dict[str, Any]) -> int:
    digest = record.get("config_sha256")
    if digest == CONFIG_SHA256:
        return 1
    if digest == V2_CONFIG_SHA256:
        return 2
    raise ValueError("unregistered internal configuration digest")


def identity(version: int = 1) -> dict[str, str]:
    """Bind packets, runs and reports to the exact frozen protocol and configuration."""
    load_config()
    if version == 2:
        load_amendment()
    elif version != 1:
        raise ValueError("unregistered internal protocol version")
    return {
        "mode": MODE,
        "evidence_class": EVIDENCE_CLASS,
        "independence": INDEPENDENCE,
        "config_sha256": V2_CONFIG_SHA256 if version == 2 else CONFIG_SHA256,
        "protocol_sha256": V2_PROTOCOL_SHA256 if version == 2 else PROTOCOL_SHA256,
    }
