"""Load and verify the frozen RES-773 internal evaluation configuration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "experiments/a03/internal-config-v1.json"
PROTOCOL_PATH = ROOT / "experiments/a03/internal-protocol-v1.md"
CONFIG_SHA256 = "83d2f378fa11d4a32efccd378d46f1dba138538dc867ea32cdc3d573e3fa5cb9"
PROTOCOL_SHA256 = "f45163cabcd1c17263f0191501af25c238eb6869d53e529e1353cec96ea85659"
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


def identity() -> dict[str, str]:
    """Bind packets, runs and reports to the exact frozen protocol and configuration."""
    load_config()
    return {
        "mode": MODE,
        "evidence_class": EVIDENCE_CLASS,
        "independence": INDEPENDENCE,
        "config_sha256": CONFIG_SHA256,
        "protocol_sha256": PROTOCOL_SHA256,
    }
