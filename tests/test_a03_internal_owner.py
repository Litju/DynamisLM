"""R3 accepts only authenticated and complete final adjudication."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from scripts import a02_v3_contract as v3
from scripts import a03_internal_config as config
from scripts import a03_internal_estimate as estimate
from scripts import a03_internal_owner as owner
from scripts import a03_internal_run as runner
from scripts import a03_internal_score as scoring
from scripts import a03_internal_seal as sealer

from a03_internal_fixtures import BUNDLE_SHA, FIXTURE_SOURCE, FakeTokenizer, valid_packet


def write(path: Path, data: dict[str, Any]) -> None:
    path.write_text(v3.canonical(data) + "\n")


def keypair(path: Path) -> Path:
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(path)], check=True)
    return path


def sign(packet: Path, key: Path, work: Path) -> Path:
    approval = work / "approval.json"
    approval.write_bytes(owner.payload(sealer._read(packet, for_approval=True)))
    subprocess.run(
        ["ssh-keygen", "-Y", "sign", "-f", str(key), "-n", owner.NAMESPACE, str(approval)],
        check=True,
        capture_output=True,
    )
    (packet / owner.SIGNATURE).write_bytes(approval.with_suffix(".json.sig").read_bytes())
    return key.with_suffix(".pub")


@pytest.fixture(scope="module")
def signed(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    root = tmp_path_factory.mktemp("r3-owner")
    original = valid_packet()
    packet = original.write(root / "protected")
    packet.chmod(0o700)
    attestation = dict(original.attestation)
    del attestation["owner_authored_all_items"]
    attestation.update(schema=owner.ATTESTATION_SCHEMA, authorship=config.AUTHORSHIP)
    write(packet / "attestation.json", attestation)
    write(
        packet / owner.PROVENANCE,
        {
            "authoring_model": {"provider": "synthetic", "identifier": "scripted"},
            "generation_configuration": {"profile": "synthetic test only"},
            "items": [
                {
                    "item_id": row["item_id"],
                    "provenance": "Synthetic contract fixture",
                    "proposed_gold": {"judgment": row["judgment"], "rationale": row["rationale"]},
                    "critique": "Synthetic review fixture",
                    "revision_history": [],
                    "owner_disposition": "ACCEPTED",
                }
                for row in original.gold
            ],
        },
    )
    return packet, sign(packet, keypair(root / "owner"), root)


@pytest.fixture(scope="module")
def recorded(
    signed: tuple[Path, Path], tmp_path_factory: pytest.TempPathFactory
) -> tuple[Path, Path, dict[str, Any]]:
    source, _ = signed
    root = tmp_path_factory.mktemp("r3-recorded")
    packet = Path(shutil.copytree(source, root / "protected"))
    (packet / owner.SIGNATURE).unlink()
    (packet / sealer.RELEASE_FILE).unlink(missing_ok=True)
    content = sealer._read(packet, for_receipt=True)
    prior = root / "owner-approval-payload.txt"
    prior.write_bytes(owner.payload(content))
    receipt = owner.build_receipt(content, prior.read_bytes())
    write(packet / owner.RECEIPT, receipt)
    return packet, prior, receipt


def test_authenticated_r3_identity_survives_blinding_estimation_and_release(
    signed: tuple[Path, Path],
) -> None:
    packet, pub = signed
    sealed = sealer.seal(packet, owner_key=pub)
    assert sealed["authorship"] == config.AUTHORSHIP
    assert config.version_for(sealed) == 2
    assert sealed["evidence_class"] == config.EVIDENCE_CLASS and sealed["independence"] == "NONE"
    blind = sealer.blind_export(packet)
    assert blind.keys() == set(sealer.BLIND_FILES)
    requests, scenarios = blind["blind-requests.jsonl"], blind["blind-scenarios.jsonl"]
    manifest = runner.run_manifest(
        requests,
        scenarios,
        packet_sha256=sealer.packet_sha256(sealed),
        bundle_archive_sha256=BUNDLE_SHA,
        source=FIXTURE_SOURCE,
        protocol_version=2,
    )
    runner.verify_manifest(
        manifest, requests, scenarios, bundle_archive_sha256=BUNDLE_SHA, verify_source=False
    )
    one = estimate.estimate(requests, scenarios, FakeTokenizer())
    two = estimate.estimate(requests, scenarios, FakeTokenizer(), protocol_version=2)
    assert {key: value for key, value in one.items() if key not in config.identity()} == {
        key: value for key, value in two.items() if key not in config.identity()
    }
    assert (
        config.version_for(
            estimate.verify(estimate.render(two), requests, scenarios, FakeTokenizer())
        )
        == 2
    )
    commit = "a" * 64
    scoring.write_release(packet, commit, owner_key=pub)
    release = packet / sealer.RELEASE_FILE
    digest = v3.sha256(release.read_bytes())
    assert (
        scoring._released_packet(release, digest, commit, manifest, (requests, scenarios), pub)[1]
        == sealed
    )
    mismatch = manifest | config.identity()
    with pytest.raises(ValueError, match="protocol differs"):
        scoring._released_packet(release, digest, commit, mismatch, (requests, scenarios), pub)


@pytest.mark.parametrize(
    "failure", ["no-key", "missing", "modified-gold", "wrong-key", "key-in-packet"]
)
def test_owner_authentication_fails_closed(
    signed: tuple[Path, Path], tmp_path: Path, failure: str
) -> None:
    source, pub = signed
    packet = Path(shutil.copytree(source, tmp_path / "packet"))
    match = "trusted owner|files differ|does not authenticate"
    if failure == "no-key":
        with pytest.raises(sealer.PacketRefusalError, match=match):
            sealer.seal(packet)
        return
    if failure == "missing":
        (packet / owner.SIGNATURE).unlink()
    if failure == "modified-gold":
        with (packet / "gold.jsonl").open("ab") as file:
            file.write(b" ")
    if failure == "wrong-key":
        pub = keypair(tmp_path / "other").with_suffix(".pub")
    if failure == "key-in-packet":
        target = packet / "owner.pub"
        shutil.copyfile(pub, target)
        pub = target
    with pytest.raises(sealer.PacketRefusalError, match=match):
        sealer.seal(packet, owner_key=pub)


@pytest.mark.parametrize("failure", ["owner-only", "missing-row", "pending", "fabricated-revision"])
def test_signature_cannot_override_incomplete_or_false_authority(
    signed: tuple[Path, Path], tmp_path: Path, failure: str
) -> None:
    source, _ = signed
    packet = Path(shutil.copytree(source, tmp_path / "packet"))
    if failure == "owner-only":
        path = packet / "attestation.json"
        data = json.loads(path.read_text())
        data["authorship"] = "OWNER_AUTHORED"
        write(path, data)
    else:
        path = packet / owner.PROVENANCE
        data = json.loads(path.read_text())
        if failure == "missing-row":
            data["items"].pop()
        else:
            data["items"][0]["owner_disposition"] = "PENDING" if failure == "pending" else "REVISED"
        write(path, data)
    pub = sign(packet, keypair(tmp_path / "fixture-owner"), tmp_path)
    with pytest.raises(sealer.PacketRefusalError, match="authorship|final owner disposition"):
        sealer.seal(packet, owner_key=pub)


def test_recorded_v3_approval_survives_blinding_estimation_and_release(
    recorded: tuple[Path, Path, dict[str, Any]],
) -> None:
    packet, prior, receipt = recorded
    sealed = sealer.seal(packet, prior_payload=prior)
    assert sealed["schema"] == "DYNAMISLM_A03_INTERNAL_PACKET_V3"
    assert config.version_for(sealed) == 3
    assert sealed["evidence_class"] == config.EVIDENCE_CLASS
    assert sealed["independence"] == "NONE"
    assert sealed["authorship"] == config.AUTHORSHIP
    assert sealed["owner_id"] == receipt["owner_id"]
    assert sealed["approval"] == {
        "authority": owner.AUTHENTICATION,
        "cryptographic": False,
        "decision": config.load_approval()["owner_decision"],
        "receipt_sha256": v3.sha256((packet / owner.RECEIPT).read_bytes()),
        "supersedes_payload_sha256": receipt["supersedes"]["payload_sha256"],
    }
    assert "owner_key_sha256" not in sealed
    blind = sealer.blind_export(packet)
    assert blind.keys() == set(sealer.BLIND_FILES)
    requests, scenarios = blind["blind-requests.jsonl"], blind["blind-scenarios.jsonl"]
    manifest = runner.run_manifest(
        requests,
        scenarios,
        packet_sha256=sealer.packet_sha256(sealed),
        bundle_archive_sha256=BUNDLE_SHA,
        source=FIXTURE_SOURCE,
        protocol_version=3,
    )
    runner.verify_manifest(
        manifest, requests, scenarios, bundle_archive_sha256=BUNDLE_SHA, verify_source=False
    )
    one = estimate.estimate(requests, scenarios, FakeTokenizer())
    three = estimate.estimate(requests, scenarios, FakeTokenizer(), protocol_version=3)
    assert {key: value for key, value in one.items() if key not in config.identity()} == {
        key: value for key, value in three.items() if key not in config.identity()
    }
    assert (
        config.version_for(
            estimate.verify(estimate.render(three), requests, scenarios, FakeTokenizer())
        )
        == 3
    )
    commit = "b" * 64
    scoring.write_release(packet, commit)
    release = packet / sealer.RELEASE_FILE
    digest = v3.sha256(release.read_bytes())
    assert (
        scoring._released_packet(release, digest, commit, manifest, (requests, scenarios))[1]
        == sealed
    )


@pytest.mark.parametrize(
    "failure",
    [
        "no-receipt",
        "crypto-claim",
        "independence-claim",
        "wrong-scope",
        "payload-digest",
        "input-digest",
        "superseded-digest",
    ],
)
def test_recorded_v3_approval_fails_closed(
    recorded: tuple[Path, Path, dict[str, Any]], tmp_path: Path, failure: str
) -> None:
    source, prior, _ = recorded
    packet = Path(shutil.copytree(source, tmp_path / "packet"))
    path = packet / owner.RECEIPT
    data = json.loads(path.read_text())
    if failure == "no-receipt":
        path.unlink()
    elif failure == "crypto-claim":
        data["cryptographic_signature"] = True
        write(path, data)
    elif failure == "independence-claim":
        data["independence"] = "INDEPENDENT"
        write(path, data)
    elif failure == "wrong-scope":
        data["scope"] = "a wider scope than the recorded owner decision"
        write(path, data)
    elif failure == "payload-digest":
        data["payload_sha256"] = "0" * 64
        write(path, data)
    elif failure == "input-digest":
        data["files"]["gold.jsonl"] = "0" * 64
        write(path, data)
    else:
        data["supersedes"]["payload_sha256"] = "0" * 64
        write(path, data)
    match = "approval|protected|superseded|files differ"
    with pytest.raises(sealer.PacketRefusalError, match=match):
        sealer.seal(packet, prior_payload=prior)


def test_recorded_v3_refuses_tampered_superseded_bytes(
    recorded: tuple[Path, Path, dict[str, Any]], tmp_path: Path
) -> None:
    packet, prior, _ = recorded
    data = json.loads(prior.read_text())
    data["files"]["gold.jsonl"] = "0" * 64
    bad = tmp_path / "prior.json"
    write(bad, data)
    with pytest.raises(sealer.PacketRefusalError, match="superseded|protected"):
        sealer.seal(packet, prior_payload=bad)


def test_recorded_v3_refuses_an_owner_key(
    recorded: tuple[Path, Path, dict[str, Any]], tmp_path: Path
) -> None:
    packet, _, _ = recorded
    pub = keypair(tmp_path / "unused").with_suffix(".pub")
    with pytest.raises(sealer.PacketRefusalError, match="recorded owner approval"):
        sealer.seal(packet, owner_key=pub)


def test_recorded_v3_receipt_cannot_cover_changed_inputs(
    recorded: tuple[Path, Path, dict[str, Any]], tmp_path: Path
) -> None:
    source, _, _ = recorded
    packet = Path(shutil.copytree(source, tmp_path / "packet"))
    with (packet / "gold.jsonl").open("ab") as file:
        file.write(b" ")
    with pytest.raises(sealer.PacketRefusalError, match="protected-input digest"):
        sealer.seal(packet)
