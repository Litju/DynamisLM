"""R3 provenance and owner signature over the exact protected evaluation inputs."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from scripts import a02_v3_contract as v3
from scripts import a03_benchmark_seal as schema
from scripts import a03_internal_config as config

ATTESTATION_SCHEMA = "DYNAMISLM_A03_INTERNAL_ATTESTATION_V2"
PROVENANCE = "provenance.json"
SIGNATURE = "owner-approval.sig"
RECEIPT = "owner-approval-receipt.json"
NAMESPACE = "dynamislm-a03-owner-v2"
APPROVAL_SCHEMA_V2 = "DYNAMISLM_A03_INTERNAL_OWNER_APPROVAL_V2"
APPROVAL_SCHEMA_V3 = "DYNAMISLM_A03_INTERNAL_OWNER_APPROVAL_V3"
RECEIPT_SCHEMA = "DYNAMISLM_A03_INTERNAL_OWNER_APPROVAL_RECEIPT_V3"
AUTHENTICATION = "RECORDED_LINEAR_OWNER_APPROVAL"
PROTECTED_INPUTS = (
    "attestation.json",
    "gold.jsonl",
    "provenance.json",
    "requests.jsonl",
    "scenarios.jsonl",
)


def attestation(content: dict[str, bytes]) -> dict[str, Any]:
    row = schema._fields(
        v3.json_object(content["attestation.json"].decode()),
        "schema owner_id authorship gold_recorded_before_inference "
        "no_a02_template_or_generator_reuse independence",
    )
    schema._key(row["owner_id"])
    if (
        row["schema"] != ATTESTATION_SCHEMA
        or row["authorship"] != config.AUTHORSHIP
        or row["independence"] != config.INDEPENDENCE
        or row["gold_recorded_before_inference"] is not True
        or row["no_a02_template_or_generator_reuse"] is not True
    ):
        raise ValueError("invalid R3 authorship or owner attestation")
    return row


def payload(content: dict[str, bytes]) -> bytes:
    return (
        v3.canonical(
            {
                "schema": "DYNAMISLM_A03_INTERNAL_OWNER_APPROVAL_V2",
                **config.identity(2),
                "files": {
                    name: v3.sha256(data) for name, data in content.items() if name != SIGNATURE
                },
            }
        )
        + "\n"
    ).encode()


def approval_files(content: dict[str, bytes]) -> dict[str, str]:
    extra = set(content) - set(PROTECTED_INPUTS) - {RECEIPT}
    if not set(PROTECTED_INPUTS).issubset(content) or extra:
        raise ValueError("approval payload requires exactly the five protected inputs")
    return {name: v3.sha256(content[name]) for name in PROTECTED_INPUTS}


def payload_v3(content: dict[str, bytes]) -> bytes:
    return (
        v3.canonical(
            {
                "schema": APPROVAL_SCHEMA_V3,
                **config.identity(3),
                "files": approval_files(content),
            }
        )
        + "\n"
    ).encode()


def _prior_payload(prior: bytes, content: dict[str, bytes]) -> dict[str, Any]:
    row = schema._fields(
        v3.json_object(prior.decode("utf-8")),
        "schema config_sha256 evidence_class files independence mode protocol_sha256",
    )
    if row["schema"] != APPROVAL_SCHEMA_V2 or {
        key: row[key] for key in config.identity(2)
    } != config.identity(2):
        raise ValueError("superseded payload is not the registered v2 approval")
    if prior != (v3.canonical(row) + "\n").encode():
        raise ValueError("superseded payload is not canonical")
    files = approval_files(content)
    recorded = row["files"]
    if not isinstance(recorded, dict) or set(recorded) != set(PROTECTED_INPUTS):
        raise ValueError("superseded payload does not cover the protected inputs")
    for name in PROTECTED_INPUTS:
        schema._digest(recorded[name])
        if recorded[name] != files[name]:
            raise ValueError("protected scientific inputs changed since v2 approval")
    return {
        "schema": APPROVAL_SCHEMA_V2,
        "config_sha256": config.V2_CONFIG_SHA256,
        "protocol_sha256": config.V2_PROTOCOL_SHA256,
        "payload_sha256": v3.sha256(prior),
        "files": files,
        "scientific_inputs_equal": True,
    }


def build_receipt(content: dict[str, bytes], prior: bytes) -> dict[str, Any]:
    """Materialize the v3 receipt from the exact accepted v2 payload bytes."""
    approval = config.load_approval()
    return {
        "schema": RECEIPT_SCHEMA,
        "owner_id": attestation(content)["owner_id"],
        "decision": dict(approval["owner_decision"]),
        "scope": approval["scope"],
        "attribution": approval["authorship"],
        "authentication": approval["authentication"],
        "cryptographic_signature": False,
        "independence": approval["independence"],
        "payload_sha256": v3.sha256(payload_v3(content)),
        "files": approval_files(content),
        "supersedes": _prior_payload(prior, content),
    }


def verify_receipt(
    content: dict[str, bytes], owner_id: str, prior: bytes | None = None
) -> dict[str, Any]:
    """Accept only the recorded owner approval bound to unchanged reviewed inputs."""
    approval = config.load_approval()
    row = schema._fields(
        v3.json_object(content[RECEIPT].decode("utf-8")),
        "schema owner_id decision scope attribution authentication cryptographic_signature "
        "independence payload_sha256 files supersedes",
    )
    if row["schema"] != RECEIPT_SCHEMA or row["owner_id"] != owner_id:
        raise ValueError("missing or mismatched v3 owner approval receipt")
    decision = schema._fields(row["decision"], "issue comment_id recorded_at attribution")
    if decision != approval["owner_decision"]:
        raise ValueError("approval receipt decision differs from the recorded owner decision")
    if (
        row["scope"] != approval["scope"]
        or row["attribution"] != approval["authorship"]
        or row["authentication"] != AUTHENTICATION
        or row["cryptographic_signature"] is not False
        or row["independence"] != approval["independence"]
    ):
        raise ValueError("approval receipt claims unsupported scope or authentication")
    files = approval_files(content)
    recorded = row["files"]
    if not isinstance(recorded, dict) or set(recorded) != set(PROTECTED_INPUTS):
        raise ValueError("approval receipt does not cover the protected inputs")
    for name in PROTECTED_INPUTS:
        schema._digest(recorded[name])
        if recorded[name] != files[name]:
            raise ValueError("approval receipt protected-input digest differs")
    schema._digest(row["payload_sha256"])
    if row["payload_sha256"] != v3.sha256(payload_v3(content)):
        raise ValueError("approval receipt payload digest differs")
    supersedes = schema._fields(
        row["supersedes"],
        "schema config_sha256 protocol_sha256 payload_sha256 files scientific_inputs_equal",
    )
    if (
        supersedes["schema"] != APPROVAL_SCHEMA_V2
        or supersedes["config_sha256"] != config.V2_CONFIG_SHA256
        or supersedes["protocol_sha256"] != config.V2_PROTOCOL_SHA256
        or supersedes["scientific_inputs_equal"] is not True
    ):
        raise ValueError("approval receipt does not supersede the registered v2 payload")
    schema._digest(supersedes["payload_sha256"])
    prior_files = supersedes["files"]
    if not isinstance(prior_files, dict) or set(prior_files) != set(PROTECTED_INPUTS):
        raise ValueError("superseded approval does not cover the protected inputs")
    for name in PROTECTED_INPUTS:
        schema._digest(prior_files[name])
        if prior_files[name] != files[name]:
            raise ValueError("protected scientific inputs changed since v2 approval")
    if prior is not None and _prior_payload(prior, content) != supersedes:
        raise ValueError("superseded payload bytes differ from the recorded v2 approval")
    return row


def verify_signature(
    directory: Path, content: dict[str, bytes], owner_id: str, key_path: Path | None
) -> str:
    if key_path is None or key_path.resolve().is_relative_to(directory.resolve()):
        raise ValueError("R3 requires a separately trusted owner public key outside the packet")
    key = key_path.read_text(encoding="ascii").split()
    if len(key) < 2 or key[0] != "ssh-ed25519" or not re.fullmatch(r"[A-Za-z0-9+/=]+", key[1]):
        raise ValueError("expected the trusted owner's OpenSSH Ed25519 public key")
    identity = " ".join(key[:2])
    with TemporaryDirectory() as work:
        signers, signature = Path(work) / "signers", Path(work) / "signature"
        signers.write_text(f"{owner_id} {identity}\n", encoding="ascii")
        signature.write_bytes(content[SIGNATURE])
        result = subprocess.run(
            [
                "ssh-keygen",
                "-Y",
                "verify",
                "-f",
                str(signers),
                "-I",
                owner_id,
                "-n",
                NAMESPACE,
                "-s",
                str(signature),
            ],
            input=payload(content),
            capture_output=True,
            check=False,
        )
        if result.returncode:
            raise ValueError("owner signature does not authenticate the exact R3 packet")
    return v3.sha256(identity.encode("ascii"))


def validate_provenance(
    content: dict[str, bytes],
    final_gold: dict[str, dict[str, Any]],
) -> None:
    data = schema._fields(
        v3.json_object(content[PROVENANCE].decode()),
        "authoring_model generation_configuration items",
    )
    model = schema._fields(data["authoring_model"], "provider identifier")
    schema._text(model["provider"])
    schema._text(model["identifier"])
    if (
        not isinstance(data["generation_configuration"], dict)
        or not data["generation_configuration"]
    ):
        raise ValueError("missing authoring generation configuration")
    seen = set()
    for entry in schema._items(data["items"]):
        row = schema._fields(
            entry,
            "item_id provenance proposed_gold critique revision_history owner_disposition",
        )
        item_id = schema._key(row["item_id"])
        if item_id in seen or item_id not in final_gold:
            raise ValueError("duplicate or unknown item in R3 provenance")
        seen.add(item_id)
        schema._text(row["provenance"])
        schema._text(row["critique"])
        revisions = schema._items(row["revision_history"])
        for revision in revisions:
            schema._text(revision)
        proposed = schema._fields(row["proposed_gold"], "judgment rationale")
        schema._fields(
            proposed["judgment"],
            "scientific_validity control preferred_action acceptable_actions "
            "dispatch_operation allowed_claims refusal_codes",
        )
        schema._text(proposed["rationale"])
        equal = v3.canonical(proposed) == v3.canonical(final_gold[item_id])
        if not (
            (row["owner_disposition"] == "ACCEPTED" and equal)
            or (row["owner_disposition"] == "REVISED" and not equal and revisions)
        ):
            raise ValueError("missing or inconsistent final owner disposition")
    if seen != final_gold.keys():
        raise ValueError("missing item provenance or final owner disposition")
