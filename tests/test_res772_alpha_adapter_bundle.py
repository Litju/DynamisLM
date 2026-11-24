"""Offline artifact checks using synthetic stand-ins for the frozen inputs."""

import json
import tarfile
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


@pytest.fixture
def archive(source: Path, tmp_path: Path) -> Path:
    path = tmp_path / "bundle.tar"
    bundle.build(source, path)
    return path


def test_build_is_byte_reproducible(source: Path, archive: Path, tmp_path: Path) -> None:
    other = tmp_path / "second.tar"
    for path in source.iterdir():
        path.touch()
    bundle.build(source, other)
    assert archive.read_bytes() == other.read_bytes()
    report = bundle.verify(archive)
    assert report["archive_sha256"] == sha256(other.read_bytes())
    assert report["structural_integrity"] == "PASS"
    assert not report["publication_qualified"]
    with pytest.raises(FileExistsError):
        bundle.build(source, archive)
    assert archive.read_bytes() == other.read_bytes()
    with tarfile.open(archive) as tar:
        assert tar.getnames() == bundle.MEMBERS
        assert all(
            m.isfile() and (m.mtime, m.uid, m.gid, m.mode) == (0, 0, 0, 0o644)
            for m in tar.getmembers()
        )
        for name, dest in bundle.COPIED_FILES.items():
            contents = tar.extractfile(dest)
            assert contents is not None
            assert contents.read() == (source / name).read_bytes()


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("weights", "SHA-256 differs"),
        ("config", "source adapter_config.json"),
        ("revision", "base revision differs"),
        ("missing", "missing or invalid archive member"),
        ("extra", "unexpected archive member"),
        ("manifest", "MANIFEST.json differs"),
        ("manifest_revision", "MANIFEST.json differs"),
        ("missing_license", "unexpected archive member"),
        ("license", "LICENSE differs"),
        ("notice", "NOTICE differs"),
        ("traversal", "unexpected archive member"),
        ("checksums", "SHA256SUMS differs"),
    ],
)
def test_verifier_rejects_tampering(archive: Path, change: str, message: str) -> None:
    payload = bundle.read_archive(archive.read_bytes())
    if change == "weights":
        first, *rest = payload[bundle.WEIGHTS]
        payload[bundle.WEIGHTS] = bytes([first ^ 1, *rest])
    elif change in {"config", "revision"}:
        config = json.loads(payload[bundle.CONFIG])
        if change == "config":
            config["r"] = 17
        else:
            config["revision"] = "main"
        payload[bundle.CONFIG] = bundle.json_bytes(config) + b"\n"
    elif change == "missing":
        del payload["provenance/metadata.json"]
    elif change == "extra":
        payload["unregistered"] = b"extra file"
    elif change in {"manifest", "manifest_revision"}:
        manifest = json.loads(payload["MANIFEST.json"])
        if change == "manifest":
            manifest["schema"] = "UNREGISTERED"
            manifest["distribution"] = "APPROVED"
        else:
            manifest["base"]["revision"] = "main"
        payload["MANIFEST.json"] = bundle.json_bytes(manifest) + b"\n"
    elif change == "missing_license":
        del payload["LICENSE"]
    elif change == "license":
        payload["LICENSE"] = b"Unapproved license text"
    elif change == "notice":
        payload["NOTICE"] += b"unregistered claim"
    elif change == "traversal":
        payload["../escaped"] = b"untrusted member"
    if change != "checksums":
        payload["SHA256SUMS"] = bundle.checksums(payload)
    else:
        payload["SHA256SUMS"] += b"\n"
    archive.write_bytes(bundle.archive_bytes(payload))
    with pytest.raises(ValueError, match=message):
        bundle.verify(archive)
    assert not (archive.parent.parent / "escaped").exists()


@pytest.mark.parametrize("member_type", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.XHDTYPE])
def test_verifier_rejects_nonregular_archive_headers(archive: Path, member_type: bytes) -> None:
    data = archive.read_bytes()
    member = bundle.tar_member(bundle.MEMBERS[0], 0)
    member.type = member_type
    member.linkname = "../escaped"
    archive.write_bytes(member.tobuf(tarfile.USTAR_FORMAT) + data[tarfile.BLOCKSIZE :])
    with pytest.raises(ValueError, match="invalid archive header"):
        bundle.verify(archive)


def test_verifier_rejects_extra_bytes_after_trailer(archive: Path) -> None:
    archive.write_bytes(archive.read_bytes() + b"unexpected trailing bytes")
    with pytest.raises(ValueError, match="invalid trailer"):
        bundle.verify(archive)


def test_license_decision_remains_pending(
    source: Path, archive: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["verify", "--archive", str(archive)]
    assert bundle.main(args) == 0
    assert json.loads(capsys.readouterr().out)["distribution"] == "LICENSE_DECISION_REQUIRED"
    assert bundle.main([*args, "--require-publication"]) == 1
    assert not json.loads(capsys.readouterr().out)["publication_qualified"]

    license_file = tmp_path / "candidate-license.txt"
    license_file.write_text("Synthetic candidate license text for testing only.", encoding="utf-8")
    supplied = tmp_path / "supplied.tar"
    bundle.build(source, supplied, license_file)
    with pytest.raises(ValueError, match="LICENSE differs"):
        bundle.verify(supplied)
    assert not bundle.verify(supplied, license_file=license_file)["publication_qualified"]
    license_file.write_bytes(b"\n")
    with pytest.raises(ValueError, match="nonempty UTF-8"):
        bundle.build(source, tmp_path / "empty-license.tar", license_file)


def test_local_base_snapshot_is_checked(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    base = bundle.base_reference()
    pins = {}
    for name in base["files"]:
        data = f"synthetic {name}".encode()
        (snapshot / name).write_bytes(data)
        pins[name] = sha256(data)
    monkeypatch.setattr(bundle, "base_reference", lambda: {**base, "files": pins})
    archive = tmp_path / "base-verified.tar"
    bundle.build(source, archive)
    assert not bundle.verify(archive)["base_snapshot_verified"]
    assert bundle.verify(archive, snapshot)["base_snapshot_verified"]
    (snapshot / "config.json").write_bytes(b"changed")
    with pytest.raises(ValueError, match="config.json"):
        bundle.verify(archive, snapshot)


def test_real_frozen_adapter(tmp_path: Path) -> None:
    evidence = Path.home() / ".local/share/dynamislm-evidence/RES-746-qualification.BKKAML"
    adapter = evidence / "t4-final/staging/adapter"
    if not adapter.exists():
        pytest.skip("authorized RES-746 adapter evidence is absent")
    snapshot = evidence.parent / "RES-746-real-model.fOXGaI/snapshot"
    first, second = tmp_path / "first.tar", tmp_path / "second.tar"
    bundle.build(adapter, first)
    bundle.build(adapter, second)
    assert first.read_bytes() == second.read_bytes()
    report = bundle.verify(first, snapshot if snapshot.exists() else None)
    assert report["structural_integrity"] == "PASS"
    assert not report["publication_qualified"]


def test_build_rejects_unpinned_provenance_before_parsing(source: Path, tmp_path: Path) -> None:
    (source / "metadata.json").write_bytes(b"{}")
    archive = tmp_path / "rejected.tar"
    with pytest.raises(ValueError, match="SHA-256 differs: provenance/metadata.json"):
        bundle.build(source, archive)
    assert not archive.exists()
