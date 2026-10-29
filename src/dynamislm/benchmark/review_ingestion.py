"""Authenticated review ingestion. Trust configuration and database require operator protection.

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
)
from dynamislm.benchmark.source_artifacts import SourceArtifactResolver
from dynamislm.serialization import canonical_json

PROTOCOL = "dynamislm-human-review-v1"


def decision_message(approval: HumanApprovalRecord) -> bytes:
    """Return the domain-separated bytes a reviewer signs, including all record fields."""
    validate_human_approval_record(approval)
    return canonical_json({"protocol": PROTOCOL, "approval": approval}).encode("utf-8")


def ingest_review(
    database: Path,
    packet: CandidateReviewPacket,
    approval: HumanApprovalRecord,
    signature: bytes,
    *,
    trusted_keys: Mapping[str, bytes],
    revoked_reviewers: frozenset[str],
    parent_promotion_evidence: ParentPromotionEvidence | None = None,
    source_resolver: SourceArtifactResolver | None = None,
) -> PromotionResult | None:
    """Verify and atomically ingest one decision; rejection produces no promotion.

    The caller supplies an independently managed, current key pin and revocation set.
    The database must be durable, access-controlled and shared by all ingesters.
    """
    if str(database) == ":memory:":
        raise ValueError("review state must be durable")
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

    def verify(record: HumanApprovalRecord, signed: bytes) -> None:
        key = trusted_keys.get(record.reviewer_id)
        if record.reviewer_id in revoked_reviewers or key is None:
            raise ValueError("reviewer is untrusted or revoked")
        try:
            Ed25519PublicKey.from_public_bytes(key).verify(signed, decision_message(record))
        except (ValueError, InvalidSignature) as exc:
            raise ValueError("invalid reviewer signature or key") from exc

    verify(approval, signature)
    with sqlite3.connect(database, timeout=30, isolation_level=None) as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute("""CREATE TABLE IF NOT EXISTS review_decisions (
                candidate_id TEXT NOT NULL, candidate_version TEXT NOT NULL,
                approval_id TEXT NOT NULL UNIQUE, approval_digest TEXT NOT NULL UNIQUE,
                signature BLOB NOT NULL, receipt_digest TEXT,
                PRIMARY KEY (candidate_id, candidate_version))""")
            parent = parent_promotion_evidence
            while parent is not None:
                row = db.execute(
                    "SELECT approval_digest, signature, receipt_digest FROM review_decisions "
                    "WHERE candidate_id = ? AND candidate_version = ?",
                    (parent.packet.candidate_id, parent.packet.candidate_version),
                ).fetchone()
                if (
                    row is None
                    or row[0] != parent.approval.approval_record_digest
                    or (row[2] != parent.result.receipt.receipt_digest)
                ):
                    raise ValueError("parent promotion was not authenticated by this store")
                verify(parent.approval, row[1])
                parent = parent.parent_promotion_evidence
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
                "INSERT INTO review_decisions VALUES (?, ?, ?, ?, ?, ?)",
                (
                    packet.candidate_id,
                    packet.candidate_version,
                    approval.approval_record_id,
                    approval.approval_record_digest,
                    signature,
                    result.receipt.receipt_digest if result else None,
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
