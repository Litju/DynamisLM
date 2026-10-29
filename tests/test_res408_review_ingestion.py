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
