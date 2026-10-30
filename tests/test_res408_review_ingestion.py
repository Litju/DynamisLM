from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from dynamislm.benchmark.pre_review import (
    HumanReviewDecision,
    ParentPromotionEvidence,
    bind_human_approval_record,
    promote_with_receipt,
)
from dynamislm.benchmark.review_ingestion import decision_message, ingest_review
from test_res115_pre_review import _approved_record, _mutation_candidate, _semantic_candidate


def test_authenticated_review_and_replay(tmp_path: Path) -> None:
    packet = _semantic_candidate()
    record = _approved_record(packet)
    key = Ed25519PrivateKey.generate()
    pins = {
        record.reviewer_id: key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
    }
    signature = key.sign(decision_message(record))
    db = tmp_path / "reviews.db"
    result = ingest_review(
        db, packet, record, signature, trusted_keys=pins, revoked_reviewers=frozenset()
    )
    assert result is not None
    with pytest.raises(ValueError, match="duplicate"):
        ingest_review(
            db, packet, record, signature, trusted_keys=pins, revoked_reviewers=frozenset()
        )
    conflicting = bind_human_approval_record(replace(record, decision=HumanReviewDecision.REJECTED))
    with pytest.raises(ValueError, match="conflicting"):
        ingest_review(
            db,
            packet,
            conflicting,
            key.sign(decision_message(conflicting)),
            trusted_keys=pins,
            revoked_reviewers=frozenset(),
        )


def test_rejection_forgery_stale_and_revocation(tmp_path: Path) -> None:
    packet = _semantic_candidate()
    record = _approved_record(packet, decision=HumanReviewDecision.REJECTED)
    key = Ed25519PrivateKey.generate()
    pins = {
        record.reviewer_id: key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
    }
    sig = key.sign(decision_message(record))
    db = tmp_path / "reviews.db"
    with pytest.raises(ValueError, match="signature"):
        ingest_review(
            db,
            packet,
            record,
            Ed25519PrivateKey.generate().sign(decision_message(record)),
            trusted_keys=pins,
            revoked_reviewers=frozenset(),
        )
    with pytest.raises(ValueError, match="revoked"):
        ingest_review(
            db,
            packet,
            record,
            sig,
            trusted_keys=pins,
            revoked_reviewers=frozenset({record.reviewer_id}),
        )
    stale = bind_human_approval_record(replace(record, reviewed_packet_digest="sha256:" + "1" * 64))
    with pytest.raises(ValueError, match="exact candidate"):
        ingest_review(
            db,
            packet,
            stale,
            key.sign(decision_message(stale)),
            trusted_keys=pins,
            revoked_reviewers=frozenset(),
        )
    assert (
        ingest_review(db, packet, record, sig, trusted_keys=pins, revoked_reviewers=frozenset())
        is None
    )


def test_concurrent_ingestion_and_parent_bypass(tmp_path: Path) -> None:
    packet = _semantic_candidate()
    record = _approved_record(packet)
    child = _mutation_candidate(packet)
    child_record = _approved_record(child, approval_record_id="synthetic-child")
    key = Ed25519PrivateKey.generate()
    pins = {
        record.reviewer_id: key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
    }
    db = tmp_path / "reviews.db"
    evidence = ParentPromotionEvidence(packet, record, promote_with_receipt(packet, record))
    with pytest.raises(ValueError, match="not authenticated"):
        ingest_review(
            db,
            child,
            child_record,
            key.sign(decision_message(child_record)),
            trusted_keys=pins,
            revoked_reviewers=frozenset(),
            parent_promotion_evidence=evidence,
        )

    def attempt() -> bool:
        try:
            ingest_review(
                db,
                packet,
                record,
                key.sign(decision_message(record)),
                trusted_keys=pins,
                revoked_reviewers=frozenset(),
            )
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(lambda _: attempt(), range(2))) == [False, True]
    assert (
        ingest_review(
            db,
            child,
            child_record,
            key.sign(decision_message(child_record)),
            trusted_keys=pins,
            revoked_reviewers=frozenset(),
            parent_promotion_evidence=evidence,
        )
        is not None
    )


def test_untrusted_author_and_revoked_parent(tmp_path: Path) -> None:
    packet = _semantic_candidate()
    record = _approved_record(packet)
    key = Ed25519PrivateKey.generate()
    pins = {
        record.reviewer_id: key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
    }
    signature = key.sign(decision_message(record))
    db = tmp_path / "reviews.db"
    with pytest.raises(ValueError, match="untrusted"):
        ingest_review(db, packet, record, signature, trusted_keys={}, revoked_reviewers=frozenset())
    author = _approved_record(packet, reviewer_id=packet.proposed_provenance.author_id)
    with pytest.raises(ValueError, match="independent"):
        ingest_review(
            db, packet, author, signature, trusted_keys=pins, revoked_reviewers=frozenset()
        )
    result = ingest_review(
        db, packet, record, signature, trusted_keys=pins, revoked_reviewers=frozenset()
    )
    assert result is not None
    child = _mutation_candidate(packet)
    other_key = Ed25519PrivateKey.generate()
    other = _approved_record(child, reviewer_id="synthetic-other", approval_record_id="child")
    pins[other.reviewer_id] = other_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    with pytest.raises(ValueError, match="revoked"):
        ingest_review(
            db,
            child,
            other,
            other_key.sign(decision_message(other)),
            trusted_keys=pins,
            revoked_reviewers=frozenset({record.reviewer_id}),
            parent_promotion_evidence=ParentPromotionEvidence(packet, record, result),
        )


def test_recovery_admission_rotation_and_tampering(tmp_path: Path) -> None:
    import sqlite3

    from dynamislm.benchmark.review_ingestion import admit_authenticated_promotion, recover_review

    packet = _semantic_candidate()
    approval = _approved_record(packet)
    old = Ed25519PrivateKey.generate()
    new = Ed25519PrivateKey.generate()

    def public(key: Ed25519PrivateKey) -> bytes:
        return key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )

    old_pin = {approval.reviewer_id: public(old)}
    rotated = {approval.reviewer_id: (public(new), public(old))}
    db = tmp_path / "ledger.db"
    bare = promote_with_receipt(packet, approval)
    with pytest.raises(ValueError, match="not authenticated"):
        admit_authenticated_promotion(db, bare, trusted_keys=old_pin, revoked_reviewers=frozenset())
    ingest_review(
        db,
        packet,
        approval,
        old.sign(decision_message(approval)),
        trusted_keys=old_pin,
        revoked_reviewers=frozenset(),
    )
    recovered, evidence = recover_review(
        db,
        packet.candidate_id,
        packet.candidate_version,
        trusted_keys=rotated,
        revoked_reviewers=frozenset(),
    )
    assert recovered == approval and evidence is not None and evidence.result == bare
    assert (
        admit_authenticated_promotion(db, bare, trusted_keys=rotated, revoked_reviewers=frozenset())
        == bare
    )
    with pytest.raises(ValueError, match="untrusted"):
        recover_review(
            db,
            packet.candidate_id,
            packet.candidate_version,
            trusted_keys={approval.reviewer_id: public(new)},
            revoked_reviewers=frozenset(),
        )
    with pytest.raises(ValueError, match="revoked"):
        admit_authenticated_promotion(
            db, bare, trusted_keys=rotated, revoked_reviewers=frozenset({approval.reviewer_id})
        )
    with sqlite3.connect(db) as conn:
        original = conn.execute("SELECT approval, result FROM review_evidence_v1").fetchone()
        conn.execute(
            "UPDATE review_evidence_v1 SET approval = ?",
            (original[0].replace(approval.reviewer_id, "forged"),),
        )
    with pytest.raises(ValueError):
        recover_review(
            db,
            packet.candidate_id,
            packet.candidate_version,
            trusted_keys=rotated,
            revoked_reviewers=frozenset(),
        )
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE review_evidence_v1 SET approval = ?, result = ?",
            (original[0], original[1].replace(bare.receipt.receipt_digest, "sha256:" + "0" * 64)),
        )
    with pytest.raises(ValueError):
        admit_authenticated_promotion(db, bare, trusted_keys=rotated, revoked_reviewers=frozenset())


def test_rejection_recovery_and_multilevel_restart(tmp_path: Path) -> None:
    from dynamislm.benchmark.review_ingestion import admit_authenticated_promotion, recover_review

    key = Ed25519PrivateKey.generate()
    packet = _semantic_candidate()
    record = _approved_record(packet)
    pins = {
        record.reviewer_id: key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
    }
    db = tmp_path / "reviews.db"
    parent = None
    for index in range(3):
        record = _approved_record(packet, approval_record_id=f"synthetic-{index}")
        result = ingest_review(
            db,
            packet,
            record,
            key.sign(decision_message(record)),
            trusted_keys=pins,
            revoked_reviewers=frozenset(),
            parent_promotion_evidence=parent,
        )
        assert result is not None
        # Recover through a new connection, as after a committed response is lost.
        _, parent = recover_review(
            db,
            packet.candidate_id,
            packet.candidate_version,
            trusted_keys=pins,
            revoked_reviewers=frozenset(),
        )
        assert parent is not None and parent.result == result
        assert (
            admit_authenticated_promotion(
                db, result, trusted_keys=pins, revoked_reviewers=frozenset()
            )
            == result
        )
        if index < 2:
            packet = _mutation_candidate(packet)
            if index == 1:
                from dynamislm.benchmark.pre_review import bind_candidate_review_packet

                packet = bind_candidate_review_packet(
                    replace(
                        packet,
                        authority=tuple(
                            binding
                            for binding in packet.authority
                            if binding.authority_kind != "MUTATION_PARENT"
                            or binding.source_reference_id == parent.packet.candidate_id
                        ),
                    )
                )
    rejected_packet = _semantic_candidate()
    rejected = _approved_record(rejected_packet, decision=HumanReviewDecision.REJECTED)
    rejected_db = tmp_path / "rejected.db"
    assert (
        ingest_review(
            rejected_db,
            rejected_packet,
            rejected,
            key.sign(decision_message(rejected)),
            trusted_keys=pins,
            revoked_reviewers=frozenset(),
        )
        is None
    )
    assert recover_review(
        rejected_db,
        rejected_packet.candidate_id,
        rejected_packet.candidate_version,
        trusted_keys=pins,
        revoked_reviewers=frozenset(),
    ) == (rejected, None)


def test_lost_response_after_commit_and_stored_signature_forgery(tmp_path: Path) -> None:
    import sqlite3

    from dynamislm.benchmark.review_ingestion import recover_review

    packet = _semantic_candidate()
    approval = _approved_record(packet)
    key = Ed25519PrivateKey.generate()
    pins = {
        approval.reviewer_id: key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
    }
    db = tmp_path / "crash.db"

    def crash_after_commit() -> None:
        ingest_review(
            db,
            packet,
            approval,
            key.sign(decision_message(approval)),
            trusted_keys=pins,
            revoked_reviewers=frozenset(),
        )
        raise RuntimeError("simulated lost response")

    with pytest.raises(RuntimeError, match="lost response"):
        crash_after_commit()
    assert (
        recover_review(
            db,
            packet.candidate_id,
            packet.candidate_version,
            trusted_keys=pins,
            revoked_reviewers=frozenset(),
        )[1]
        is not None
    )
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE review_evidence_v1 SET signature = ?", (b"x" * 64,))
    with pytest.raises(ValueError, match="signature"):
        recover_review(
            db,
            packet.candidate_id,
            packet.candidate_version,
            trusted_keys=pins,
            revoked_reviewers=frozenset(),
        )
