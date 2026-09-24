"""RES-115 authoring adapter that binds the canonical retained-source store."""

from __future__ import annotations

from pathlib import Path

from dynamislm.benchmark.pre_review import CandidateReviewPacket, validate_candidate_review_packet
from dynamislm.benchmark.source_artifacts import PhaseASourceArtifactResolver

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_SOURCE_REGISTRY_ROOT = _REPOSITORY_ROOT / "registries/performance_science_eval"
_CANONICAL_ACCEPTED_SOURCE_ROOT = Path(
    "/mnt/e/Data/Datasets/DynamisLM/PerformanceScienceEval/sources/accepted"
)


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


__all__ = [
    "build_res115_source_artifact_resolver",
    "validate_res115_candidate_for_authoring",
]
