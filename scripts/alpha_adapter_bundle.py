"""Build and verify the frozen step-510 adapter bundle without model execution."""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

from scripts.a02_v3_contract import json_object, sha256
from scripts.a03_model_core import ADAPTER_FILES, MODEL_FILES, RUNTIME, verify_files

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
WEIGHTS = COPIED_FILES["adapter_model.safetensors"]
MEMBERS = sorted(
    [*COPIED_FILES.values(), CONFIG, "LICENSE", "MANIFEST.json", "NOTICE", "SHA256SUMS"]
)
MAX_ARCHIVE_BYTES = 32 * 1024**2
MAX_TEXT_BYTES = 64 * 1024


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


def notice(base: dict[str, Any]) -> bytes:
    return (
        "DynamisLM frozen step-510 LoRA adapter\n"
        f"Upstream base model: {base['id']} at revision {base['revision']}.\n"
        "Base weights and tokenizer files are referenced by digest and are not included.\n"
        "Evaluation evidence is development only.\n"
        "Adapter distribution authority: RES-771 D2 (decision required).\n"
    ).encode()


def read_bounded(path: Path, limit: int) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"file exceeds size limit: {path}")
    return data


def license_bytes(path: Path | None) -> bytes:
    if path is None:
        return PENDING_LICENSE
    data = read_bounded(path, MAX_TEXT_BYTES)
    if not data.decode("utf-8").strip() or b"\x00" in data or data == PENDING_LICENSE:
        raise ValueError("supplied LICENSE must contain nonempty UTF-8 license text")
    return data


def checksums(payload: dict[str, bytes]) -> bytes:
    return "".join(
        f"{sha256(payload[name])}  {name}\n" for name in sorted(payload) if name != "SHA256SUMS"
    ).encode()


def tar_member(name: str, size: int) -> tarfile.TarInfo:
    member = tarfile.TarInfo(name)
    member.size = size
    member.mode = 0o644
    return member


def archive_bytes(payload: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:", format=tarfile.USTAR_FORMAT) as archive:
        for name, data in sorted(payload.items()):
            archive.addfile(tar_member(name, len(data)), io.BytesIO(data))
    return output.getvalue()


def read_archive(data: bytes) -> dict[str, bytes]:
    # Read raw headers because tarfile iteration hides extended headers.
    stream = io.BytesIO(data)
    payload = {}
    for name in MEMBERS:
        header = stream.read(tarfile.BLOCKSIZE)
        try:
            member = tarfile.TarInfo.frombuf(header, "ascii", "strict")
        except tarfile.HeaderError as exc:
            raise ValueError(f"missing or invalid archive member: {name}") from exc
        if member.name != name:
            raise ValueError(f"unexpected archive member {member.name!r}; expected {name}")
        limit = MAX_ARCHIVE_BYTES if name == WEIGHTS else MAX_TEXT_BYTES
        if not 0 <= member.size <= limit:
            raise ValueError(f"invalid archive member size: {name}")
        if header != tar_member(name, member.size).tobuf(tarfile.USTAR_FORMAT):
            raise ValueError(f"invalid archive header: {name}")
        contents = stream.read(member.size)
        padding = -member.size % tarfile.BLOCKSIZE
        if len(contents) != member.size or stream.read(padding) != bytes(padding):
            raise ValueError(f"invalid archive content or padding: {name}")
        payload[name] = contents
    end = stream.tell() + 2 * tarfile.BLOCKSIZE
    trailer_size = end + (-end % tarfile.RECORDSIZE) - stream.tell()
    if len(data) - stream.tell() != trailer_size or stream.read() != bytes(trailer_size):
        raise ValueError("unexpected archive members or invalid trailer")
    return payload


def check_frozen_payload(payload: dict[str, bytes], base: dict[str, Any]) -> None:
    for original, member in COPIED_FILES.items():
        check_digest(payload[member], ADAPTER_FILES[original], member)
    check_release_config(payload[CONFIG], base)


def validate_payload(
    payload: dict[str, bytes], base: dict[str, Any], license_file: Path | None
) -> None:
    check_frozen_payload(payload, base)
    if payload["LICENSE"] != license_bytes(license_file):
        raise ValueError("LICENSE differs from the pending placeholder or supplied license file")
    if payload["NOTICE"] != notice(base):
        raise ValueError("NOTICE differs")
    if payload["MANIFEST.json"] != manifest(payload, base, license_file is not None):
        raise ValueError("MANIFEST.json differs from the registered bundle identity")
    if payload["SHA256SUMS"] != checksums(payload):
        raise ValueError("SHA256SUMS differs")


def build(adapter_dir: Path, archive: Path, license_file: Path | None = None) -> None:
    base = base_reference()
    payload = {
        dest: read_bounded(
            adapter_dir / name, MAX_ARCHIVE_BYTES if dest == WEIGHTS else MAX_TEXT_BYTES
        )
        for name, dest in COPIED_FILES.items()
    }
    source_config = read_bounded(adapter_dir / "adapter_config.json", MAX_TEXT_BYTES)
    payload[CONFIG] = derive_config(source_config, base)
    check_frozen_payload(payload, base)
    payload["LICENSE"] = license_bytes(license_file)
    payload["NOTICE"] = notice(base)
    payload["MANIFEST.json"] = manifest(payload, base, license_file is not None)
    payload["SHA256SUMS"] = checksums(payload)
    data = archive_bytes(payload)
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ValueError("bundle exceeds archive size limit")
    with tempfile.NamedTemporaryFile(dir=archive.parent) as pending:
        pending.write(data)
        pending.flush()
        os.link(pending.name, archive)


def verify(
    archive: Path, base_dir: Path | None = None, license_file: Path | None = None
) -> dict[str, Any]:
    data = read_bounded(archive, MAX_ARCHIVE_BYTES)
    payload = read_archive(data)
    base = base_reference()
    validate_payload(payload, base, license_file)
    if base_dir is not None:
        verify_files(base_dir, base["files"])
    return {
        "schema": SCHEMA,
        "structural_integrity": "PASS",
        "distribution": DISTRIBUTION,
        "publication_qualified": False,
        "base_snapshot_verified": base_dir is not None,
        "archive_sha256": sha256(data),
        "files": {name: sha256(content) for name, content in payload.items()},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    builder = commands.add_parser("build")
    builder.add_argument("--adapter-dir", type=Path, required=True)
    verifier = commands.add_parser("verify")
    verifier.add_argument("--base-dir", type=Path)
    verifier.add_argument("--require-publication", action="store_true")
    for command in (builder, verifier):
        command.add_argument("--archive", type=Path, required=True)
        command.add_argument("--license-file", type=Path)

    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            build(args.adapter_dir, args.archive, args.license_file)
            return 0
        report = verify(args.archive, args.base_dir, args.license_file)
        print(json_bytes(report).decode())
        return int(args.require_publication and not report["publication_qualified"])
    except (OSError, ValueError) as exc:
        print(f"Adapter bundle rejected: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
