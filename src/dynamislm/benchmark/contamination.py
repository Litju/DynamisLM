"""Deterministic V1 contamination and exclusion controls."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass

from dynamislm.benchmark.constants import SplitName
from dynamislm.benchmark.contracts import (
    BenchmarkCaseV1,
    ExclusionEntry,
)
from dynamislm.benchmark.hashing import case_payload_hash

_TOKEN_RE = re.compile(r"\w+|[^\w\s]", flags=re.UNICODE)


def normalize_text(text: str) -> str:
    """Apply the frozen NFKC/lowercase/whitespace normalization."""

    if not isinstance(text, str):
        raise TypeError("contamination text must be a string")
    normalized = unicodedata.normalize("NFKC", text).lower()
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    return " ".join(normalized.split())


def tokenize(text: str) -> tuple[str, ...]:
    return tuple(_TOKEN_RE.findall(normalize_text(text)))


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalized_text_sha256(text: str) -> str:
    return "sha256:" + _sha256_hex(normalize_text(text).encode("utf-8"))


def _shingle_hashes(tokens: tuple[str, ...], width: int) -> frozenset[str]:
    if len(tokens) < width:
        return frozenset()
    return frozenset(
        _sha256_hex(" ".join(tokens[index : index + width]).encode("utf-8"))
        for index in range(len(tokens) - width + 1)
    )


def exact_13_token_shingles(text: str) -> frozenset[str]:
    return _shingle_hashes(tokenize(text), 13)


def exact_shingle_digest(text: str) -> str:
    from dynamislm.serialization import canonical_hash

    return canonical_hash(tuple(sorted(exact_13_token_shingles(text))))


def _token_5grams(text: str) -> frozenset[tuple[str, ...]]:
    tokens = tokenize(text)
    if len(tokens) < 5:
        return frozenset()
    return frozenset(tuple(tokens[index : index + 5]) for index in range(len(tokens) - 4))


def _char_5grams(text: str) -> frozenset[str]:
    normalized = normalize_text(text)
    if len(normalized) < 5:
        return frozenset()
    return frozenset(normalized[index : index + 5] for index in range(len(normalized) - 4))


def jaccard(left: frozenset[object], right: frozenset[object]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def token_5gram_jaccard(left: str, right: str) -> float:
    return jaccard(_token_5grams(left), _token_5grams(right))


def character_5gram_jaccard(left: str, right: str) -> float:
    return jaccard(_char_5grams(left), _char_5grams(right))


def normalized_edit_similarity(left: str, right: str) -> float:
    """Return 1 minus normalized Levenshtein distance."""

    a = normalize_text(left)
    b = normalize_text(right)
    if a == b:
        return 1.0
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    previous = list(range(len(b) + 1))
    for index, left_char in enumerate(a, start=1):
        current = [index]
        for right_index, right_char in enumerate(b, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_char != right_char),
                )
            )
        previous = current
    distance = previous[-1]
    return 1.0 - (distance / max(len(a), len(b)))


def fuzzy_fingerprint(text: str) -> str:
    from dynamislm.serialization import canonical_hash

    return canonical_hash(
        {
            "token_5grams": tuple(sorted(" ".join(item) for item in _token_5grams(text))),
            "character_5grams": tuple(sorted(_char_5grams(text))),
        }
    )


@dataclass(frozen=True, slots=True)
class ContaminationArtifact:
    """Text-bearing input used only to construct an exclusion record/index."""

    artifact_id: str
    source_id: str
    text: str
    source_family_id: str
    split_name: SplitName
    normalized_doi: str | None = None
    canonical_url: str | None = None
    semantic_cluster_id: str | None = None
    benchmark_case_ids: tuple[str, ...] = ()
    benchmark_case_hashes: tuple[str, ...] = ()
    exclusion_reason: str = "PSE-V1 benchmark/training exclusion"

    def __post_init__(self) -> None:
        for name in ("artifact_id", "source_id", "text", "source_family_id", "exclusion_reason"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be non-empty")
        object.__setattr__(self, "split_name", SplitName(self.split_name))
        if self.normalized_doi is not None and not self.normalized_doi.strip():
            raise ValueError("normalized_doi must not be empty")
        if self.canonical_url is not None and not self.canonical_url.strip():
            raise ValueError("canonical_url must not be empty")
        if len(self.benchmark_case_ids) != len(self.benchmark_case_hashes):
            raise ValueError("benchmark case IDs and hashes must align")


def build_exclusion_entry(artifact: ContaminationArtifact) -> ExclusionEntry:
    """Create the exact manifest record from text-bearing artifact metadata."""

    return ExclusionEntry(
        artifact_id=artifact.artifact_id,
        source_id=artifact.source_id,
        normalized_doi=artifact.normalized_doi,
        canonical_url=artifact.canonical_url,
        source_family_id=artifact.source_family_id,
        source_content_sha256="sha256:" + _sha256_hex(artifact.text.encode("utf-8")),
        normalized_text_sha256=normalized_text_sha256(artifact.text),
        exact_shingle_digest=exact_shingle_digest(artifact.text),
        fuzzy_fingerprint=fuzzy_fingerprint(artifact.text),
        semantic_cluster_id=artifact.semantic_cluster_id,
        benchmark_case_ids=artifact.benchmark_case_ids,
        benchmark_case_hashes=artifact.benchmark_case_hashes,
        split_names=(artifact.split_name,),
        exclusion_reason=artifact.exclusion_reason,
    )


@dataclass(frozen=True, slots=True)
class ExclusionRegistry:
    """Immutable manifest plus private text fingerprints for audit-time matching."""

    entries: tuple[ExclusionEntry, ...]
    artifacts: tuple[ContaminationArtifact, ...] = ()
    version: str = "PSE-V1-EXCLUSION-REGISTRY@1.0.0"

    def __post_init__(self) -> None:
        if not self.entries:
            raise ValueError("exclusion registry must not be empty")
        if any(not isinstance(item, ExclusionEntry) for item in self.entries):
            raise ValueError("exclusion registry entries must be typed")
        if any(
            build_exclusion_entry(item) != entry
            for item, entry in zip(self.artifacts, self.entries, strict=False)
        ):
            raise ValueError("text-bearing artifacts do not match exclusion entries")

    @classmethod
    def from_artifacts(cls, artifacts: tuple[ContaminationArtifact, ...]) -> ExclusionRegistry:
        if not artifacts:
            raise ValueError("cannot build exclusion registry from no artifacts")
        return cls(
            entries=tuple(build_exclusion_entry(item) for item in artifacts), artifacts=artifacts
        )


@dataclass(frozen=True, slots=True)
class ContaminationAudit:
    status: str
    candidate_artifact_id: str
    exact_matches: tuple[str, ...]
    fuzzy_matches: tuple[str, ...]
    source_family_conflicts: tuple[str, ...]
    semantic_diagnostic: str
    reason: str

    def __post_init__(self) -> None:
        if self.status not in {"PASS", "BLOCKED"}:
            raise ValueError("contamination audit status must be PASS or BLOCKED")
        if not self.candidate_artifact_id.strip():
            raise ValueError("candidate artifact ID must be non-empty")


def audit_contamination(
    candidate: ContaminationArtifact,
    registry: ExclusionRegistry,
    *,
    approved_overlap_artifact_ids: tuple[str, ...] = (),
) -> ContaminationAudit:
    """Run mandatory exact, fuzzy, and source-family checks in frozen order."""

    approved = set(approved_overlap_artifact_ids)
    candidate_entry = build_exclusion_entry(candidate)
    exact_matches: list[str] = []
    fuzzy_matches: list[str] = []
    family_conflicts: list[str] = []
    candidate_shingles = exact_13_token_shingles(candidate.text)
    for entry, artifact in zip(registry.entries, registry.artifacts, strict=False):
        if entry.artifact_id in approved:
            continue
        if entry.normalized_text_sha256 == candidate_entry.normalized_text_sha256:
            exact_matches.append(entry.artifact_id)
        if (
            candidate_shingles
            and entry.exact_shingle_digest == candidate_entry.exact_shingle_digest
        ):
            exact_matches.append(entry.artifact_id)
        if artifact is not None:
            if candidate_shingles & exact_13_token_shingles(artifact.text):
                exact_matches.append(entry.artifact_id)
            token_score = token_5gram_jaccard(candidate.text, artifact.text)
            character_score = character_5gram_jaccard(candidate.text, artifact.text)
            edit_score = normalized_edit_similarity(candidate.text, artifact.text)
            if token_score >= 0.85 or character_score >= 0.85 or edit_score >= 0.90:
                fuzzy_matches.append(entry.artifact_id)
            if entry.source_family_id == candidate.source_family_id and entry.split_names:
                if entry.split_names[0] is not candidate.split_name:
                    family_conflicts.append(entry.artifact_id)
    exact_matches = sorted(set(exact_matches))
    fuzzy_matches = sorted(set(fuzzy_matches))
    family_conflicts = sorted(set(family_conflicts))
    blocked = bool(exact_matches or fuzzy_matches or family_conflicts)
    reasons = []
    if exact_matches:
        reasons.append("mandatory exact overlap")
    if fuzzy_matches:
        reasons.append("mandatory fuzzy overlap")
    if family_conflicts:
        reasons.append("source-family crosses split boundary")
    return ContaminationAudit(
        status="BLOCKED" if blocked else "PASS",
        candidate_artifact_id=candidate.artifact_id,
        exact_matches=tuple(exact_matches),
        fuzzy_matches=tuple(fuzzy_matches),
        source_family_conflicts=tuple(family_conflicts),
        semantic_diagnostic="NOT_APPLICABLE",
        reason="; ".join(reasons) if reasons else "mandatory contamination checks passed",
    )


def validate_source_family_isolation(cases: tuple[BenchmarkCaseV1, ...]) -> None:
    """Require each source/provider/template family to occupy one split only."""

    family_splits: dict[str, SplitName] = {}
    isolation_keys: dict[str, SplitName] = {}
    for case in cases:
        split = case.split.split_name
        if split is None:
            raise ValueError("source-family isolation requires allocated splits")
        assert isinstance(split, SplitName)
        metadata = case.contamination
        keys = [
            ("source-family", metadata.source_family_id),
            ("provider-export", metadata.provider_export_id),
            ("protocol-template", metadata.protocol_template_id),
            ("expert-author-batch", metadata.expert_author_batch_id),
            ("generator-family", case.provenance.generator_family),
            ("mutation-lineage", case.provenance.mutation_lineage_id),
        ]
        for kind, value in keys:
            if value is None:
                continue
            key = f"{kind}:{value}"
            prior = isolation_keys.get(key)
            if prior is not None and prior is not split:
                raise ValueError(f"{kind} crosses split boundary: {value}")
            isolation_keys[key] = split
        prior_family = family_splits.get(metadata.source_family_id)
        if prior_family is not None and prior_family is not split:
            raise ValueError(f"source family crosses split boundary: {metadata.source_family_id}")
        family_splits[metadata.source_family_id] = split


def validate_case_contamination_binding(case: BenchmarkCaseV1) -> None:
    """Check that case-local contamination references are hash-shaped and immutable."""

    expected = case_payload_hash(case)
    if expected != case.case_payload_hash:
        raise ValueError("contamination validation requires a current case payload hash")
    if case.contamination.source_family_id == "":
        raise ValueError("source family is required for contamination isolation")


__all__ = [
    "ContaminationArtifact",
    "ContaminationAudit",
    "ExclusionRegistry",
    "audit_contamination",
    "build_exclusion_entry",
    "character_5gram_jaccard",
    "exact_13_token_shingles",
    "exact_shingle_digest",
    "fuzzy_fingerprint",
    "jaccard",
    "normalize_text",
    "normalized_edit_similarity",
    "normalized_text_sha256",
    "token_5gram_jaccard",
    "tokenize",
    "validate_case_contamination_binding",
    "validate_source_family_isolation",
]
