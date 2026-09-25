"""RES-115 authoring adapter that binds the canonical retained-source store."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from dynamislm.benchmark.constants import CaseOrigin
from dynamislm.benchmark.pre_review import CandidateReviewPacket, validate_candidate_review_packet
from dynamislm.benchmark.source_artifacts import PhaseASourceArtifactResolver

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_SOURCE_REGISTRY_ROOT = _REPOSITORY_ROOT / "registries/performance_science_eval"
_CANONICAL_ACCEPTED_SOURCE_ROOT = Path(
    "/mnt/e/Data/Datasets/DynamisLM/PerformanceScienceEval/sources/accepted"
)
_APPLICABILITY_SCOPES = frozenset(
    {
        "DIRECT_TARGET_POPULATION_EVIDENCE",
        "INDIRECT_MEASUREMENT_EVIDENCE",
        "NONCANONICAL_CONTEXT_ONLY",
    }
)
_TARGET_USE_BY_SCOPE = {
    "DIRECT_TARGET_POPULATION_EVIDENCE": "POPULATION_APPLICABILITY_ONLY",
    "INDIRECT_MEASUREMENT_EVIDENCE": "METHOD_OR_MEASUREMENT_ONLY",
    "NONCANONICAL_CONTEXT_ONLY": "CONTEXT_ONLY",
}


def build_res115_source_artifact_resolver() -> PhaseASourceArtifactResolver:
    """Bind core validation to the canonical Phase-A registry and retained store."""

    return PhaseASourceArtifactResolver(
        accepted_registry_path=_SOURCE_REGISTRY_ROOT / "accepted.jsonl",
        checksum_registry_path=_SOURCE_REGISTRY_ROOT / "checksums.jsonl",
        registry_schema_path=_SOURCE_REGISTRY_ROOT / "registry.schema.json",
        retained_source_root=_CANONICAL_ACCEPTED_SOURCE_ROOT,
    )


def validate_res115_candidate_for_authoring(packet: CandidateReviewPacket) -> None:
    """Validate a Phase-B packet using the production accepted-source store."""

    validate_candidate_review_packet(
        packet,
        source_resolver=build_res115_source_artifact_resolver(),
    )
    if packet.proposed_provenance.origin_class is CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION:
        validate_res115_source_applicability(packet)


def _accepted_source_scope_by_document_id(
    accepted_registry_path: Path = _SOURCE_REGISTRY_ROOT / "accepted.jsonl",
) -> dict[str, str]:
    try:
        lines = accepted_registry_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError("Phase-A accepted source registry is unavailable") from exc
    scopes: dict[str, str] = {}
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Phase-A accepted source registry is invalid at line {line_number}"
            ) from exc
        if not isinstance(row, dict):
            raise ValueError("Phase-A accepted source registry rows must be objects")
        artifact = row.get("retained_source_artifact")
        document_id = artifact.get("document_identity_id") if isinstance(artifact, dict) else None
        scope = row.get("applicability_scope")
        if not isinstance(document_id, str) or scope not in _APPLICABILITY_SCOPES:
            raise ValueError("Phase-A source registry has an invalid identity/applicability row")
        if document_id in scopes:
            raise ValueError("Phase-A source document identity is not unique")
        scopes[document_id] = scope
    return scopes


def validate_res115_source_applicability(
    packet: CandidateReviewPacket,
    *,
    source_scopes: Mapping[str, str] | None = None,
) -> None:
    """Preserve Phase-A source applicability and exact source-backed answers."""

    if packet.proposed_provenance.origin_class is not CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION:
        return
    scopes = (
        dict(source_scopes)
        if source_scopes is not None
        else _accepted_source_scope_by_document_id()
    )
    excerpts = packet.input.evidence_excerpts
    if not excerpts or len(excerpts) != len(packet.source_evidence_refs):
        raise ValueError("source-backed applicability requires paired exact excerpts/references")
    document_scopes: list[str] = []
    for excerpt, reference in zip(excerpts, packet.source_evidence_refs, strict=True):
        document = excerpt.document_identity
        if reference.reference_kind.value != "SOURCE" or reference.document_identity != document:
            raise ValueError("source applicability must bind the exact typed SOURCE document")
        registered_scope = scopes.get(document.document_id)
        if registered_scope not in _APPLICABILITY_SCOPES:
            raise ValueError(
                "source document does not resolve to an accepted Phase-A applicability"
            )
        if excerpt.applicability != registered_scope or reference.applicability != registered_scope:
            raise ValueError("source applicability was changed from the sealed Phase-A class")
        document_scopes.append(registered_scope)

    answer = packet.proposed_expected_answer
    fields = dict(answer.expected_fields.items())
    expected_spans = fields.get("source_spans")
    expected_scopes = fields.get("applicability_scopes")
    expected_target_use = fields.get("target_population_use")
    if expected_spans != tuple(excerpt.text for excerpt in excerpts):
        raise ValueError("source-backed expected spans must equal exact resolved JATS text")
    if expected_scopes != tuple(document_scopes):
        raise ValueError("source-backed expected applicability must equal Phase-A classes")
    allowed_target_use = tuple(_TARGET_USE_BY_SCOPE[scope] for scope in document_scopes)
    if expected_target_use != allowed_target_use:
        raise ValueError("source applicability cannot be escalated into target norms or thresholds")
    prohibited_target_fields = {
        "canonical_target_norm",
        "canonical_target_threshold",
        "target_population_norm",
        "target_population_threshold",
    }
    if prohibited_target_fields.intersection(fields):
        raise ValueError("Phase-A evidence cannot author a canonical target norm or threshold")


__all__ = [
    "build_res115_source_artifact_resolver",
    "validate_res115_candidate_for_authoring",
    "validate_res115_source_applicability",
]
