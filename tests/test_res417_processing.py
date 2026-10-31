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
    real_overlap = p._screen_pair

    def revoke_during_scan(a: p._Text, b: p._Text, work: p._ScreeningWork) -> str:
        monkeypatch.setattr(admission, "_PRODUCTION_TRUST_SHA256", "sha256:" + "0" * 64)
        return real_overlap(a, b, work)

    monkeypatch.setattr(p, "_screen_pair", revoke_during_scan)
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


def test_review_direction_counterexample() -> None:
    # Independently supplied SYNTHETIC four-token regression.
    a = b"force velocity impulse power"
    b = b"impulse velocity power force"
    assert p._overlap(a, b) == p._overlap(b, a) == "MANUAL_REVIEW"


def test_review_authorized_permutations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    items = provision(
        tmp_path / "trust",
        monkeypatch,
        (b"force velocity impulse power", b"impulse velocity power force"),
    )
    bundle = exclusions(monkeypatch)
    first = p.process_training_inputs(items, exclusion_bundle=bundle, output_root=tmp_path / "out")
    second = p.process_training_inputs(
        tuple(reversed(items)), exclusion_bundle=bundle, output_root=tmp_path / "out"
    )
    assert first["status"] == second["status"] == "MANUAL_REVIEW"
    assert first["sources"] == second["sources"]
    assert canonical_hash(first) == canonical_hash(second)
    assert not list((tmp_path / "out").rglob("shard.json"))


def test_review_cumulative_work_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    items = provision(
        tmp_path / "trust",
        monkeypatch,
        (
            b"SYNTHETIC force " * 128 + b"alpha",
            b"SYNTHETIC force " * 128 + b"beta",
            b"SYNTHETIC short control",
        ),
    )
    bundle = exclusions(monkeypatch)
    # Test-only policy reduction; the production API offers no budget override.
    monkeypatch.setattr(p, "MAX_WORK_UNITS", 1000, raising=False)
    first = p.process_training_inputs(items, exclusion_bundle=bundle, output_root=tmp_path / "out")
    second = p.process_training_inputs(
        tuple(reversed(items)), exclusion_bundle=bundle, output_root=tmp_path / "out"
    )
    assert first == second
    assert first["screening"].get("deferred_comparisons", 0) > 0
    assert first["screening"]["budget_exhausted"]
    from itertools import permutations

    for ordered in permutations(items):
        assert first == p.process_training_inputs(
            ordered, exclusion_bundle=bundle, output_root=tmp_path / "out"
        )
    assert 0 < first["screening"]["used_work_units"] <= 1000
    assert first["screening"]["comparisons"] == 3 + 3 * len(p.REQUIRED_EXCLUSIONS)
    assert first["status"] != "CLEAN"
    assert not list((tmp_path / "out").rglob("shard.json"))


def test_review_independent_batches_need_corpus_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    items = provision(tmp_path / "trust", monkeypatch, (CONTENT, CONTENT))
    bundle = exclusions(monkeypatch)
    receipts = [
        p.process_training_inputs((item,), exclusion_bundle=bundle, output_root=tmp_path / "out")
        for item in items
    ]
    assert all(receipt["status"] == "CLEAN" for receipt in receipts)
    assert (
        receipts[0]["sources"][0]["normalized_sha256"]
        == receipts[1]["sources"][0]["normalized_sha256"]
    )
    assert (
        receipts[0]["sources"][0]["document_sha256"] != receipts[1]["sources"][0]["document_sha256"]
    )
    assert len(list((tmp_path / "out").rglob("shard.json"))) == 2
    for receipt in receipts:
        assert receipt.get("qualification_scope") == "BATCH_LOCAL_ONLY"
        assert receipt["split_isolation"] == "UNQUALIFIED"
        destination = tmp_path / "out" / canonical_hash(receipt).removeprefix("sha256:")
        shard = (destination / "shard.json").read_bytes()
        for candidate in (
            receipt,
            json.loads((destination / "receipt.json").read_bytes())["payload"],
        ):
            with pytest.raises(PermissionError, match="CORPUS_ASSEMBLY_REQUIRED"):
                p.authorize_sft_corpus_bytes(candidate, shard)
            candidate["qualification_scope"] = "CORPUS_QUALIFIED"
            candidate["corpus_qualified"] = True
            candidate["split_isolation"] = "COMPLETE"
            candidate["manifest_sha256"] = canonical_hash(candidate)
            forged = json.loads(json.dumps(candidate))
            with pytest.raises(PermissionError, match="CORPUS_ASSEMBLY_REQUIRED"):
                p.authorize_sft_corpus_bytes(forged, shard)


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        (b"force velocity impulse power", b"impulse velocity power force", "MANUAL_REVIEW"),
        (b"SYNTHETIC exact F=ma", b"SYNTHETIC exact F=ma", "EXACT"),
        (
            b"one two three four five six seven eight",
            b"prefix one two three four five six seven eight tail",
            "MANUAL_REVIEW",
        ),
        (b"force " * 80 + b"velocity", b"force " * 80 + b"power", "MANUAL_REVIEW"),
        (b"a b c d e f g h", b"x y z", "NONE"),
        (
            "SYNTHETIC F = m × a; −2.50 m·s⁻²".encode(),  # noqa: RUF001
            "SYNTHETIC F = m × a; −3.50 m·s⁻²".encode(),  # noqa: RUF001
            "MANUAL_REVIEW",
        ),
    ],
)
def test_symmetric_overlap_cases(a: bytes, b: bytes, expected: str) -> None:
    for _ in range(3):
        assert p._overlap(a, b) == p._overlap(b, a) == expected


def test_bounded_algorithm_retains_former_detections() -> None:
    from difflib import SequenceMatcher
    from itertools import product

    # Exhaustively falsify conservatism on a small finite alphabet, in both directions.
    sequences = list(product(("force", "power"), repeat=4))
    for a in sequences:
        for b in sequences:
            previous = max(
                SequenceMatcher(None, a, b, autojunk=False).ratio(),
                SequenceMatcher(None, b, a, autojunk=False).ratio(),
            )
            forward = p._overlap(" ".join(a).encode(), " ".join(b).encode())
            assert forward == p._overlap(" ".join(b).encode(), " ".join(a).encode())
            if previous >= 0.5:
                assert forward in {"EXACT", "MANUAL_REVIEW"}


def test_precise_work_accounting_and_exact_after_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work = p._ScreeningWork()
    a, b = p._text(b"a b"), p._text(b"a c")
    monkeypatch.setattr(p, "MAX_WORK_UNITS", 8)
    assert p._screen_pair(a, b, work) == "MANUAL_REVIEW"
    assert (work.dp_cells, work.used_work_units, work.comparisons) == (4, 8, 1)
    assert not work.budget_exhausted
    assert p._screen_pair(a, b, work) == "MANUAL_REVIEW"
    assert work.budget_exhausted and work.deferred_comparisons == 1
    assert (work.dp_cells, work.used_work_units) == (4, 8)
    assert p._screen_pair(a, a, work) == "EXACT"
    assert (work.dp_cells, work.used_work_units, work.comparisons) == (4, 8, 3)


def test_pathological_repetition_is_bounded() -> None:
    work = p._ScreeningWork()
    a = p._text(b"force " * (p.MAX_TOKENS - 1) + b"velocity")
    b = p._text(b"force " * (p.MAX_TOKENS - 1) + b"power")
    assert p._screen_pair(a, b, work) == "MANUAL_REVIEW"
    assert work.budget_exhausted
    assert work.dp_cells == work.used_work_units == 0
    assert p._screen_pair(b, a, work) == "MANUAL_REVIEW"
    assert work.deferred_comparisons == 2
    assert work.dp_cells == work.used_work_units == 0


def test_byte_limit_and_token_preparation_bound() -> None:
    raw = b"x" * p.MAX_BYTES
    prepared = p._text(raw)
    work = p._ScreeningWork()
    assert p._screen_pair(prepared, p._text(raw[:-1] + b"y"), work) == "NONE"
    assert work.used_work_units == p.MAX_BYTES + 1
    assert work.dp_cells == 1
    many = p._text(b"x " * (p.MAX_BYTES // 2))
    assert len(many.tokens) == p.MAX_TOKENS + 1
    assert p._screen_pair(many, p._text(b"x"), work) == "MANUAL_REVIEW"
    assert work.deferred_comparisons == 1


def test_exhaustion_still_detects_normalized_duplicates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    items = provision(tmp_path / "trust", monkeypatch, (b"SYNTHETIC F=ma\r\n", b"SYNTHETIC F=ma\n"))
    bundle = exclusions(monkeypatch)
    monkeypatch.setattr(p, "MAX_WORK_UNITS", 0)
    result = p.process_training_inputs(items, exclusion_bundle=bundle, output_root=tmp_path / "out")
    assert result["status"] == "QUARANTINED"
    assert result["screening"]["budget_exhausted"]
    assert result["screening"]["used_work_units"] == 0
    assert all(
        any(f["kind"] == "NORMALIZED_CONTENT" for f in row["findings"]) for row in result["sources"]
    )
    assert not list((tmp_path / "out").rglob("shard.json"))


def test_corpus_gate_has_no_flag_override() -> None:
    attack: dict[str, Any] = {"corpus_qualified": True}
    with pytest.raises(TypeError):
        p.authorize_sft_corpus_bytes({}, b"SYNTHETIC", **attack)
    with pytest.raises(PermissionError, match="CORPUS_ASSEMBLY_REQUIRED"):
        p.authorize_sft_corpus_bytes({"schema": "TRUSTED_CORPUS", "corpus_qualified": True}, b"")


def test_batch_shard_explicit_scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    items = provision(tmp_path / "trust", monkeypatch)
    result = p.process_training_inputs(
        items, exclusion_bundle=exclusions(monkeypatch), output_root=tmp_path / "out"
    )
    destination = tmp_path / "out" / canonical_hash(result).removeprefix("sha256:")
    shard = json.loads((destination / "shard.json").read_bytes())["payload"]
    assert all(row["qualification_scope"] == "BATCH_LOCAL_ONLY" for row in shard)
    assert result["corpus_qualification"] == "ASSEMBLY_REQUIRED"
    assert result["status"] == "CLEAN"
    assert result["screening"]["deferred_comparisons"] == 0


def test_partial_contiguous_overlap_below_ratio_threshold() -> None:
    shared = "force velocity impulse power acceleration mass time distance"
    a = (shared + " " + " ".join(f"left{i}" for i in range(20))).encode()
    b = (shared + " " + " ".join(f"right{i}" for i in range(20))).encode()
    assert p._overlap(a, b) == p._overlap(b, a) == "MANUAL_REVIEW"


def test_dp_accounting_counts_executed_token_equalities() -> None:
    equalities = 0

    class CountingToken(str):
        def __eq__(self, other: object) -> bool:
            nonlocal equalities
            equalities += 1
            return str(self) == str(other)

    a = p._Text("synthetic-a", tuple(CountingToken(x) for x in ("a", "b", "c")), 1)
    b = p._Text("synthetic-b", tuple(CountingToken(x) for x in ("b", "a")), 1)
    work = p._ScreeningWork()
    assert p._screen_pair(a, b, work) == "NONE"
    assert equalities == work.dp_cells == 6
    assert work.used_work_units == 12
    work.used_work_units = p.MAX_WORK_UNITS
    assert p._screen_pair(a, b, work) == "MANUAL_REVIEW"
    assert equalities == work.dp_cells == 6
