"""CPU dry run with isolated SYNTHETIC bytes and test-only trust provisioning."""

import json
import subprocess
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import pytest

from dynamislm.serialization import canonical_hash
from dynamislm.training_data import admission
from dynamislm.training_data import processing as p
from dynamislm.training_data.admission import Request, Source, SourceClass
from test_res416_admission import CONTENT, fixture, install_test_authority


def provision(
    root: Path, monkeypatch: pytest.MonkeyPatch, contents: tuple[bytes, ...] = (CONTENT,)
) -> tuple[tuple[Request, bytes, bytes], ...]:
    root.mkdir()
    items = []
    pins = []
    for i, content in enumerate(contents):
        source = Source(f"SYNTHETIC-res417-{i}", "1", p.sha256(content), SourceClass.TEXT)
        request, grant = fixture(
            root,
            changes={
                "source": asdict(source),
                "synthetic": False,
                "transformations": [p.TRANSFORM],
            },
        )
        items.append(
            (replace(request, source=source, transformations=(p.TRANSFORM,)), content, grant)
        )
        trust = json.loads((root / admission.TRUST_PATH).read_bytes())
        pins.extend(trust["grants"])
    trust["grants"] = pins
    (root / admission.TRUST_PATH).write_text(json.dumps(trust))
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "SYNTHETIC batch trust",
        ],
        cwd=root,
        check=True,
    )
    install_test_authority(root, monkeypatch)
    return tuple(items)


def exclusions(monkeypatch: pytest.MonkeyPatch, text: bytes | None = None) -> bytes:
    entries = [
        {
            "identity": f"SYNTHETIC-{role}",
            "role": role,
            "text": (text or f"SYNTHETIC excluded {role} zeta omega".encode()).decode(),
            "sha256": p.sha256(text or f"SYNTHETIC excluded {role} zeta omega".encode()),
        }
        for role in sorted(p.REQUIRED_EXCLUSIONS)
    ]
    raw = json.dumps({"schema": "RES417-EXCLUSIONS-1", "entries": entries}).encode()
    monkeypatch.setattr(p, "_EXCLUSION_COMMITMENTS", frozenset({p.sha256(raw)}))
    return raw


def test_cpu_dry_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    items = provision(tmp_path / "trust", monkeypatch)
    bundle = exclusions(monkeypatch)
    result = p.process_training_inputs(items, exclusion_bundle=bundle, output_root=tmp_path / "out")
    assert result["status"] == "CLEAN"
    assert result == p.process_training_inputs(
        items, exclusion_bundle=bundle, output_root=tmp_path / "out"
    )
    artifacts = list((tmp_path / "out").iterdir())
    assert len(artifacts) == 1
    shard = (artifacts[0] / "shard.json").read_bytes()
    assert p.sha256(shard) == result["shard_sha256"]
    shard_row = json.loads(shard)["payload"][0]
    assert shard_row["text"].encode() == CONTENT
    assert shard_row["document_sha256"] == result["sources"][0]["document_sha256"]
    assert shard_row["chunk_sha256"] == result["sources"][0]["chunk_sha256"]
    assert CONTENT.decode() not in json.dumps(result)
    assert result["sources"][0]["raw_sha256"] == p.sha256(CONTENT)
    (artifacts[0] / "shard.json").write_bytes(b"SYNTHETIC tamper")
    with pytest.raises(ValueError, match="artifact changed"):
        p.process_training_inputs(items, exclusion_bundle=bundle, output_root=tmp_path / "out")


def test_normalization_preserves_science() -> None:
    raw = "SYNTHETIC\r\nF = m × a; −2.50 m·s⁻² ≠ 2.50; α_1\tβ\rE=mc²".encode()  # noqa: RUF001
    normalized = p.normalize(raw)
    assert normalized.decode() == raw.decode().replace("\r\n", "\n").replace("\r", "\n")
    assert p.sha256(raw) != p.sha256(normalized)
    assert p.normalize(normalized) == normalized


@pytest.mark.parametrize("raw", [b"", b"\xff", b"SYNTHETIC\x00", b"x" * (p.MAX_BYTES + 1)])
def test_invalid_text(raw: bytes) -> None:
    with pytest.raises(ValueError):
        p.normalize(raw)


@pytest.mark.parametrize("case", ["changed", "forged", "revoked", "partition", "transform"])
def test_admission_to_shard_denials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    items = provision(tmp_path / "trust", monkeypatch)
    request, content, grant = items[0]
    if case == "changed":
        content += b" changed"
    if case == "forged":
        grant += b" "
    if case == "partition":
        request = replace(request, partition="VALIDATION")
    if case == "transform":
        request = replace(request, transformations=("unapproved",))
    if case == "revoked":
        trust = json.loads((tmp_path / "trust" / admission.TRUST_PATH).read_bytes())
        trust["revoked"] = [p.sha256(grant)]
        (tmp_path / "trust" / admission.TRUST_PATH).write_text(json.dumps(trust))
        subprocess.run(
            ["git", "commit", "-am", "SYNTHETIC revoke"],
            cwd=tmp_path / "trust",
            check=True,
            env={
                "PATH": "/usr/bin:/bin",
                "GIT_AUTHOR_NAME": "Test",
                "GIT_AUTHOR_EMAIL": "test@example.invalid",
                "GIT_COMMITTER_NAME": "Test",
                "GIT_COMMITTER_EMAIL": "test@example.invalid",
            },
        )
        install_test_authority(tmp_path / "trust", monkeypatch)
    with pytest.raises((ValueError, PermissionError)):
        p.process_training_inputs(
            ((request, content, grant),),
            exclusion_bundle=exclusions(monkeypatch),
            output_root=tmp_path / "out",
        )
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    "case", ["exact", "normalized", "near", "identity", "protected", "partial"]
)
def test_overlap_quarantine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str) -> None:
    a = b"SYNTHETIC force equation F = m * a with acceleration 2.5 m/s2\r\n"
    b = a
    if case == "normalized":
        b = a.replace(b"\r\n", b"\n")
    if case == "near":
        b = a.replace(b"2.5", b"3.5")
    if case == "identity":
        b = b"SYNTHETIC unrelated cycling prescription"
    items = provision(tmp_path / "trust", monkeypatch, (a, b))
    if case == "identity":
        # Same source/version with changed bytes needs its own exact pinned grant.
        first, content, raw = items[1]
        source = replace(first.source, source_id=items[0][0].source.source_id)
        grant = json.loads(raw)
        grant["source"] = asdict(source)
        raw = json.dumps(grant).encode()
        trust_path = tmp_path / "trust" / admission.TRUST_PATH
        trust = json.loads(trust_path.read_bytes())
        trust["grants"].append({**trust["grants"][0], "grant_sha256": p.sha256(raw)})
        trust_path.write_text(json.dumps(trust))
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "-am",
                "SYNTHETIC identity collision",
            ],
            cwd=tmp_path / "trust",
            check=True,
        )
        install_test_authority(tmp_path / "trust", monkeypatch)
        items = (items[0], (replace(first, source=source), content, raw))
    if case in {"protected", "partial"}:
        items = items[:1]
    bundle = exclusions(
        monkeypatch,
        a
        if case == "protected"
        else (a + b" SYNTHETIC additional exclusion context" if case == "partial" else None),
    )
    result = p.process_training_inputs(items, exclusion_bundle=bundle, output_root=tmp_path / "out")
    expected = (
        "CONTAMINATED"
        if case == "protected"
        else ("QUARANTINED" if case in {"exact", "normalized", "identity"} else "MANUAL_REVIEW")
    )
    assert result["status"] == expected
    assert all(r["findings"] for r in result["sources"])
    assert not list((tmp_path / "out").rglob("shard.json"))


@pytest.mark.parametrize("case", ["missing", "untrusted", "empty", "incomplete"])
def test_missing_exclusion_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    items = provision(tmp_path / "trust", monkeypatch)
    raw: bytes | None = None
    if case == "untrusted":
        raw = exclusions(monkeypatch) + b" "
    if case in {"empty", "incomplete"}:
        bundle = json.loads(exclusions(monkeypatch))
        bundle["entries"] = [] if case == "empty" else bundle["entries"][:1]
        raw = json.dumps(bundle).encode()
        monkeypatch.setattr(p, "_EXCLUSION_COMMITMENTS", frozenset({p.sha256(raw)}))
    if case == "empty":
        with pytest.raises(ValueError):
            p.process_training_inputs(items, exclusion_bundle=raw, output_root=tmp_path / "out")
        return
    result = p.process_training_inputs(items, exclusion_bundle=raw, output_root=tmp_path / "out")
    assert result["status"] == "UNQUALIFIED"
    assert not list((tmp_path / "out").rglob("shard.json"))


def test_production_does_not_trust_test_grant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with monkeypatch.context() as patch:
        items = provision(tmp_path / "trust", patch)
    with pytest.raises(PermissionError):
        p.process_training_inputs(items, exclusion_bundle=None, output_root=tmp_path / "out")


def test_git_output_and_manifest_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="outside repository"):
        p.process_training_inputs((), exclusion_bundle=None, output_root=Path.cwd() / "artifacts")
    forged: Any = {"status": "AUTHORIZED", "sources": []}
    attack: dict[str, Any] = {"admission_manifest": forged}
    with pytest.raises(TypeError):
        p.process_training_inputs(forged, exclusion_bundle=None, output_root=tmp_path, **attack)


def test_screening_bounds() -> None:
    assert p._overlap(b"a " * (p.MAX_TOKENS + 1), b"b") == "MANUAL_REVIEW"
    assert p._overlap(b"SYNTHETIC x y z", b"SYNTHETIC z y x") == "MANUAL_REVIEW"


def test_cli_cpu_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from dynamislm.training_data.process_cli import main

    items = provision(tmp_path / "trust", monkeypatch)
    request, content, grant = items[0]
    content_path = tmp_path / "synthetic.txt"
    grant_path = tmp_path / "synthetic-grant.json"
    content_path.write_bytes(content)
    grant_path.write_bytes(grant)
    exclusion_path = tmp_path / "synthetic-exclusions.json"
    exclusion_path.write_bytes(exclusions(monkeypatch))
    request_path = tmp_path / "request.json"
    request_path.write_text(
        json.dumps(
            {
                "inputs": [
                    {
                        **asdict(request),
                        "content_path": str(content_path),
                        "grant_path": str(grant_path),
                    }
                ]
            }
        )
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "process_cli",
            str(request_path),
            "--exclusions",
            str(exclusion_path),
            "--output-root",
            str(tmp_path / "out"),
        ],
    )
    main()
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "CLEAN"
    assert len(list((tmp_path / "out").rglob("shard.json"))) == 1
    request_path.write_text(json.dumps({"inputs": [], "status": "AUTHORIZED"}))
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2


def test_symlink_into_git_refused(tmp_path: Path) -> None:
    (tmp_path / "link").symlink_to(Path.cwd(), target_is_directory=True)
    with pytest.raises(ValueError, match="outside repository"):
        p.require_external(tmp_path / "link" / "new-shards")


def test_changed_exclusion_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    items = provision(tmp_path / "trust", monkeypatch)
    bundle = json.loads(exclusions(monkeypatch))
    bundle["entries"][0]["text"] += " changed"
    raw = json.dumps(bundle).encode()
    monkeypatch.setattr(p, "_EXCLUSION_COMMITMENTS", frozenset({p.sha256(raw)}))
    with pytest.raises(ValueError, match="changed exclusion"):
        p.process_training_inputs(items, exclusion_bundle=raw, output_root=tmp_path / "out")


def test_publication_rechecks_admission(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    items = provision(tmp_path / "trust", monkeypatch)
    bundle = exclusions(monkeypatch)
    real_overlap = p._overlap

    def revoke_during_scan(a: bytes, b: bytes) -> str:
        monkeypatch.setattr(admission, "_PRODUCTION_TRUST_SHA256", "sha256:" + "0" * 64)
        return real_overlap(a, b)

    monkeypatch.setattr(p, "_overlap", revoke_during_scan)
    with pytest.raises(PermissionError, match="unprovisioned"):
        p.process_training_inputs(items, exclusion_bundle=bundle, output_root=tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_order_invariant_receipts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    items = provision(
        tmp_path / "trust",
        monkeypatch,
        (
            b"SYNTHETIC alpha beta gamma delta scientific acceleration 2.5 m/s2",
            b"SYNTHETIC alpha beta gamma delta scientific acceleration 3.5 m/s2",
            b"SYNTHETIC alpha beta gamma delta scientific acceleration 4.5 m/s2",
        ),
    )
    bundle = exclusions(monkeypatch)
    first = p.process_training_inputs(items, exclusion_bundle=bundle, output_root=tmp_path / "out")
    assert first == p.process_training_inputs(
        tuple(reversed(items)), exclusion_bundle=bundle, output_root=tmp_path / "out"
    )
    for row in first["sources"]:
        assert row["chunk"]["document_sha256"] == row["document_sha256"]
        assert row["chunk"]["start_byte"] == 0
        assert row["chunk_sha256"] == canonical_hash(row["chunk"])


def test_expired_source_no_shard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "trust"
    root.mkdir()
    request, grant = fixture(
        root,
        changes={
            "synthetic": False,
            "transformations": [p.TRANSFORM],
            "expires": "2026-02-01T00:00:00+00:00",
        },
    )
    request = replace(request, transformations=(p.TRANSFORM,))
    install_test_authority(root, monkeypatch)
    with pytest.raises(PermissionError, match="EXPIRED"):
        p.process_training_inputs(
            ((request, CONTENT, grant),), exclusion_bundle=None, output_root=tmp_path / "out"
        )
    assert not (tmp_path / "out").exists()
