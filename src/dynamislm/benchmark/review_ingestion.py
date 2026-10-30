"""Authenticated review ledger; protect the database and trust configuration externally.

A valid signature authenticates a key, not the participation of a human.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from dynamislm.benchmark.pre_review import (
    CandidateReviewPacket,
    HumanApprovalRecord,
    HumanReviewDecision,
    ParentPromotionEvidence,
    PromotionResult,
    promote_with_receipt,
    validate_candidate_review_packet,
    validate_human_approval_record,
    validate_promotion_result,
)
from dynamislm.benchmark.source_artifacts import SourceArtifactResolver
from dynamislm.serialization import canonical_json, from_canonical_json

PROTOCOL = "dynamislm-human-review-v1"
Trust = Mapping[str, bytes | tuple[bytes, ...]]


def decision_message(approval: HumanApprovalRecord) -> bytes:
    """Return the domain-separated bytes a reviewer signs, including all record fields."""
    validate_human_approval_record(approval)
    return canonical_json({"protocol": PROTOCOL, "approval": approval}).encode("utf-8")


def _verify(
    approval: HumanApprovalRecord,
    signature: bytes,
    key: bytes,
    trusted_keys: Trust,
    revoked_reviewers: frozenset[str],
) -> None:
    pins = trusted_keys.get(approval.reviewer_id, ())
    if isinstance(pins, bytes):
        pins = (pins,)
    if approval.reviewer_id in revoked_reviewers or key not in pins:
        raise ValueError("reviewer is untrusted or revoked")
    try:
        Ed25519PublicKey.from_public_bytes(key).verify(signature, decision_message(approval))
    except (ValueError, InvalidSignature) as exc:
        raise ValueError("invalid reviewer signature or key") from exc


def _open(database: Path) -> sqlite3.Connection:
    if str(database) == ":memory:":
        raise ValueError("review state must be durable")
    db = sqlite3.connect(database, timeout=30, isolation_level=None)
    db.execute("BEGIN IMMEDIATE")
    try:
        legacy = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='review_decisions'"
        ).fetchone()
        if legacy and db.execute("SELECT 1 FROM review_decisions LIMIT 1").fetchone():
            raise ValueError("legacy review ledger lacks recoverable evidence")
        db.execute("""CREATE TABLE IF NOT EXISTS review_evidence_v1 (
            candidate_id TEXT NOT NULL, candidate_version TEXT NOT NULL,
            approval_id TEXT NOT NULL UNIQUE, approval_digest TEXT NOT NULL UNIQUE,
            packet TEXT NOT NULL, approval TEXT NOT NULL, signature BLOB NOT NULL,
            signer_key BLOB NOT NULL, result TEXT, parent TEXT,
            PRIMARY KEY (candidate_id, candidate_version))""")
        return db
    except BaseException:
        db.rollback()
        db.close()
        raise


def _read(
    db: sqlite3.Connection,
    candidate_id: str,
    candidate_version: str,
    *,
    trusted_keys: Trust,
    revoked_reviewers: frozenset[str],
    source_resolver: SourceArtifactResolver | None,
    seen: set[tuple[str, str]],
) -> tuple[HumanApprovalRecord, ParentPromotionEvidence | None]:
    identity = (candidate_id, candidate_version)
    if identity in seen:
        raise ValueError("cyclic parent evidence")
    seen.add(identity)
    row = db.execute(
        "SELECT approval_id, approval_digest, packet, approval, signature, signer_key, result, "
        "parent FROM review_evidence_v1 WHERE candidate_id=? AND candidate_version=?",
        identity,
    ).fetchone()
    if row is None:
        raise ValueError("promotion was not authenticated by this store")
    approval_id, digest, packet_text, approval_text, signature, key, result_text, parent_text = row
    packet = from_canonical_json(packet_text, CandidateReviewPacket)
    approval = from_canonical_json(approval_text, HumanApprovalRecord)
    if (
        canonical_json(packet) != packet_text
        or canonical_json(approval) != approval_text
        or identity != (packet.candidate_id, packet.candidate_version)
        or (approval_id, digest) != (approval.approval_record_id, approval.approval_record_digest)
    ):
        raise ValueError("stored review evidence mismatch")
    validate_candidate_review_packet(packet, source_resolver=source_resolver)
    if (
        approval.candidate_id,
        approval.candidate_version,
        approval.candidate_payload_hash,
        approval.reviewed_packet_digest,
    ) != (
        packet.candidate_id,
        packet.candidate_version,
        packet.candidate_payload_hash,
        packet.proposed_approval_digest,
    ):
        raise ValueError("decision does not bind the exact candidate packet")
    if approval.reviewer_id.casefold() == packet.proposed_provenance.author_id.casefold():
        raise ValueError("reviewer must be independent of author")
    _verify(approval, signature, key, trusted_keys, revoked_reviewers)
    parent = None
    if parent_text is not None:
        supplied = from_canonical_json(parent_text, ParentPromotionEvidence)
        if canonical_json(supplied) != parent_text:
            raise ValueError("stored parent evidence mismatch")
        _, parent = _read(
            db,
            supplied.packet.candidate_id,
            supplied.packet.candidate_version,
            trusted_keys=trusted_keys,
            revoked_reviewers=revoked_reviewers,
            source_resolver=source_resolver,
            seen=seen,
        )
        if parent != supplied:
            raise ValueError("stored parent evidence mismatch")
    if approval.decision is HumanReviewDecision.REJECTED:
        if result_text is not None or parent is not None:
            raise ValueError("rejection has promotion evidence")
        return approval, None
    if result_text is None:
        raise ValueError("approved review lacks promotion evidence")
    result = from_canonical_json(result_text, PromotionResult)
    if canonical_json(result) != result_text:
        raise ValueError("stored promotion evidence mismatch")
    validate_promotion_result(
        packet, approval, result, parent_promotion_evidence=parent, source_resolver=source_resolver
    )
    return approval, ParentPromotionEvidence(packet, approval, result, parent)


def recover_review(
    database: Path,
    candidate_id: str,
    candidate_version: str,
    *,
    trusted_keys: Trust,
    revoked_reviewers: frozenset[str],
    source_resolver: SourceArtifactResolver | None = None,
) -> tuple[HumanApprovalRecord, ParentPromotionEvidence | None]:
    """Recover and authenticate a decision and its complete promotion lineage.

    Each reviewer pin may contain a bounded tuple of currently trusted historical keys;
    removing a key or revoking a reviewer immediately invalidates its evidence.
    """
    db = _open(database)
    try:
        return _read(
            db,
            candidate_id,
            candidate_version,
            trusted_keys=trusted_keys,
            revoked_reviewers=revoked_reviewers,
            source_resolver=source_resolver,
            seen=set(),
        )
    finally:
        db.rollback()
        db.close()


def admit_authenticated_promotion(
    database: Path,
    result: PromotionResult,
    *,
    trusted_keys: Trust,
    revoked_reviewers: frozenset[str],
    source_resolver: SourceArtifactResolver | None = None,
) -> PromotionResult:
    """Admit only an exact promotion authenticated by the persisted review ledger.

    Downstream approved-case selection must use this boundary, not an eligibility flag.
    """
    _, evidence = recover_review(
        database,
        result.receipt.candidate_id,
        result.receipt.candidate_version,
        trusted_keys=trusted_keys,
        revoked_reviewers=revoked_reviewers,
        source_resolver=source_resolver,
    )
    if evidence is None or evidence.result != result:
        raise ValueError("promotion does not match authenticated evidence")
    return evidence.result


def ingest_review(
    database: Path,
    packet: CandidateReviewPacket,
    approval: HumanApprovalRecord,
    signature: bytes,
    *,
    trusted_keys: Trust,
    revoked_reviewers: frozenset[str],
    parent_promotion_evidence: ParentPromotionEvidence | None = None,
    source_resolver: SourceArtifactResolver | None = None,
) -> PromotionResult | None:
    """Atomically ingest one signed decision; use recover_review after a lost response."""
    validate_candidate_review_packet(packet, source_resolver=source_resolver)
    validate_human_approval_record(approval)
    if (
        approval.candidate_id,
        approval.candidate_version,
        approval.candidate_payload_hash,
        approval.reviewed_packet_digest,
    ) != (
        packet.candidate_id,
        packet.candidate_version,
        packet.candidate_payload_hash,
        packet.proposed_approval_digest,
    ):
        raise ValueError("decision does not bind the exact candidate packet")
    if approval.reviewer_id.casefold() == packet.proposed_provenance.author_id.casefold():
        raise ValueError("reviewer must be independent of author")
    pins = trusted_keys.get(approval.reviewer_id, ())
    if isinstance(pins, bytes):
        pins = (pins,)
    if approval.reviewer_id in revoked_reviewers or not pins:
        raise ValueError("reviewer is untrusted or revoked")
    key = None
    for pin in pins:
        try:
            _verify(approval, signature, pin, trusted_keys, revoked_reviewers)
        except ValueError:
            continue
        key = pin
        break
    if key is None:
        raise ValueError("invalid reviewer signature or key")
    db = _open(database)
    try:
        if parent_promotion_evidence is not None:
            _, parent = _read(
                db,
                parent_promotion_evidence.packet.candidate_id,
                parent_promotion_evidence.packet.candidate_version,
                trusted_keys=trusted_keys,
                revoked_reviewers=revoked_reviewers,
                source_resolver=source_resolver,
                seen=set(),
            )
            if parent != parent_promotion_evidence:
                raise ValueError("parent promotion was not authenticated by this store")
        result = None
        if approval.decision is HumanReviewDecision.APPROVED:
            result = promote_with_receipt(
                packet,
                approval,
                parent_promotion_evidence=parent_promotion_evidence,
                source_resolver=source_resolver,
            )
        elif parent_promotion_evidence is not None:
            raise ValueError("rejection must not include promotion evidence")
        db.execute(
            "INSERT INTO review_evidence_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                packet.candidate_id,
                packet.candidate_version,
                approval.approval_record_id,
                approval.approval_record_digest,
                canonical_json(packet),
                canonical_json(approval),
                signature,
                key,
                canonical_json(result) if result else None,
                canonical_json(parent_promotion_evidence) if parent_promotion_evidence else None,
            ),
        )
        db.commit()
        return result
    except sqlite3.IntegrityError as exc:
        db.rollback()
        raise ValueError("duplicate or conflicting review") from exc
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()
