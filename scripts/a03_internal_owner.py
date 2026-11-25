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
NAMESPACE = "dynamislm-a03-owner-v2"


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
