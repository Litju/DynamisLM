"""Deterministic V1 contamination and exclusion controls."""

from __future__ import annotations

import datetime as datetime_module
import hashlib
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass

from dynamislm.benchmark.constants import (
    EXCLUSION_REGISTRY_VERSION,
    SPLIT_ORDER,
    CaseOrigin,
    OverlapDecision,
    OverlapLineageRelation,
    OverlapMatchKind,
    OverlapSplitRelation,
    SplitName,
)
from dynamislm.benchmark.contracts import (
    BenchmarkCaseV1,
    ExclusionEntry,
    OverlapDispositionV1,
)
from dynamislm.benchmark.hashing import case_payload_hash
from dynamislm.serialization import canonical_hash

_TOKEN_RE = re.compile(r"\w+|[^\w\s]", flags=re.UNICODE)
type _PairIndex = dict[object, tuple[int, ...]]

PSE_V1_CONTAMINATION_AUDIT = "PSE_V1_CONTAMINATION_AUDIT"
PRETRAINING_EXPOSURE_UNKNOWN = "UNKNOWN"


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


def _optional_sha(value: str | None, field_name: str) -> None:
    if value is not None and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        raise ValueError(f"{field_name} must be a canonical SHA-256 digest")


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
    """Private audit text plus optional document and stored-artifact identity."""

    artifact_id: str
    document_id: str | None
    document_content_digest: str | None
    source_artifact_id: str | None
    source_artifact_digest: str | None
    text: str
    source_family_id: str
    split_name: SplitName
    normalized_doi: str | None = None
    canonical_url: str | None = None
    semantic_cluster_id: str | None = None
    benchmark_case_ids: tuple[str, ...] = ()
    benchmark_case_hashes: tuple[str, ...] = ()
    membership_digests: tuple[str, ...] = ()
    exclusion_reason: str = "PSE-V1 benchmark/training exclusion"
    benchmark_split_names: tuple[SplitName, ...] = ()

    def __post_init__(self) -> None:
        for name in ("artifact_id", "text", "source_family_id", "exclusion_reason"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be non-empty")
        for name in ("document_id", "source_artifact_id"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{name} must be non-empty when provided")
        if self.document_content_digest is not None and self.document_id is None:
            raise ValueError("document digest requires a document identity")
        if self.normalized_doi is not None and self.document_id is None:
            raise ValueError("DOI requires a document identity")
        _optional_sha(self.document_content_digest, "document_content_digest")
        _optional_sha(self.source_artifact_digest, "source_artifact_digest")
        if (self.source_artifact_id is None) != (self.source_artifact_digest is None):
            raise ValueError("source artifact identity and stored-byte digest must align")
        if self.artifact_id.startswith("document:"):
            expected_document_id = self.artifact_id.removeprefix("document:")
            if self.document_id != expected_document_id:
                raise ValueError("document exclusion artifact ID must map to its document ID")
        if self.artifact_id.startswith("source:"):
            expected_source_artifact_id = self.artifact_id.removeprefix("source:")
            if self.source_artifact_id != expected_source_artifact_id:
                raise ValueError("source exclusion artifact ID must map to its source artifact ID")
        object.__setattr__(self, "split_name", SplitName(self.split_name))
        split_names = tuple(SplitName(item) for item in self.benchmark_split_names)
        if len(set(split_names)) != len(split_names):
            raise ValueError("benchmark split associations cannot contain duplicates")
        if split_names and split_names != tuple(
            split for split in SPLIT_ORDER if split in split_names
        ):
            raise ValueError("benchmark split associations must use canonical split ordering")
        object.__setattr__(self, "benchmark_split_names", split_names)
        if self.normalized_doi is not None and not self.normalized_doi.strip():
            raise ValueError("normalized_doi must not be empty")
        if self.canonical_url is not None and not self.canonical_url.strip():
            raise ValueError("canonical_url must not be empty")
        if len(self.benchmark_case_ids) != len(self.benchmark_case_hashes):
            raise ValueError("benchmark case IDs and hashes must align")
        if len(set(self.benchmark_case_ids)) != len(self.benchmark_case_ids):
            raise ValueError("an artifact cannot associate the same case more than once")
        if self.benchmark_case_ids != tuple(
            sorted(self.benchmark_case_ids, key=lambda item: item.encode("utf-8"))
        ):
            raise ValueError("benchmark case associations must use canonical case-ID ordering")
        if self.membership_digests and len(self.membership_digests) != len(self.benchmark_case_ids):
            raise ValueError("membership digests and benchmark case IDs must align")


def build_exclusion_entry(artifact: ContaminationArtifact) -> ExclusionEntry:
    """Create the exact manifest record from text-bearing artifact metadata."""

    return ExclusionEntry(
        artifact_id=artifact.artifact_id,
        document_id=artifact.document_id,
        document_content_digest=artifact.document_content_digest,
        source_artifact_id=artifact.source_artifact_id,
        source_artifact_digest=artifact.source_artifact_digest,
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
        split_names=artifact.benchmark_split_names or (artifact.split_name,),
        exclusion_reason=artifact.exclusion_reason,
        membership_digests=artifact.membership_digests,
    )


@dataclass(frozen=True, slots=True)
class ExclusionRegistry:
    """Immutable manifest plus private text fingerprints for audit-time matching."""

    entries: tuple[ExclusionEntry, ...]
    artifacts: tuple[ContaminationArtifact, ...] = ()
    version: str = EXCLUSION_REGISTRY_VERSION

    def __post_init__(self) -> None:
        if self.version != EXCLUSION_REGISTRY_VERSION:
            raise ValueError("unsupported exclusion registry version")
        if not self.entries:
            raise ValueError("exclusion registry must not be empty")
        if any(not isinstance(item, ExclusionEntry) for item in self.entries):
            raise ValueError("exclusion registry entries must be typed")
        artifact_ids = tuple(item.artifact_id for item in self.entries)
        if artifact_ids != tuple(sorted(artifact_ids, key=lambda item: item.encode("utf-8"))):
            raise ValueError("exclusion registry entries must use canonical artifact-ID ordering")
        if len(set(artifact_ids)) != len(artifact_ids):
            raise ValueError("exclusion registry contains duplicate artifact IDs")
        if self.artifacts and len(self.artifacts) != len(self.entries):
            raise ValueError("private exclusion text index must align with registry entries")
        if self.artifacts and tuple(item.artifact_id for item in self.artifacts) != artifact_ids:
            raise ValueError("private exclusion text index must use registry artifact ordering")
        if any(
            build_exclusion_entry(item) != entry
            for item, entry in zip(self.artifacts, self.entries, strict=False)
        ):
            raise ValueError("text-bearing artifacts do not match exclusion entries")

    @classmethod
    def from_artifacts(cls, artifacts: tuple[ContaminationArtifact, ...]) -> ExclusionRegistry:
        if not artifacts:
            raise ValueError("cannot build exclusion registry from no artifacts")
        artifact_ids = tuple(item.artifact_id for item in artifacts)
        if len(set(artifact_ids)) != len(artifact_ids):
            raise ValueError("cannot build exclusion registry from duplicate artifact IDs")
        ordered = tuple(sorted(artifacts, key=lambda item: item.artifact_id.encode("utf-8")))
        return cls(
            entries=tuple(build_exclusion_entry(item) for item in ordered), artifacts=ordered
        )


@dataclass(frozen=True, slots=True)
class _ContaminationMatchIndex:
    raw_content: _PairIndex
    normalized_text: _PairIndex
    exact_shingles: _PairIndex
    character_5grams: _PairIndex
    token_5grams: _PairIndex
    empty_character_5grams: tuple[int, ...]
    empty_token_5grams: tuple[int, ...]
    source_families: _PairIndex


def _freeze_index(
    values: dict[object, set[int]],
) -> _PairIndex:
    return {key: tuple(sorted(indices)) for key, indices in values.items()}


def _build_contamination_match_index(registry: ExclusionRegistry) -> _ContaminationMatchIndex:
    """Index exact fingerprints and 5-gram candidates before fuzzy checks."""

    raw_content: dict[object, set[int]] = defaultdict(set)
    normalized_text: dict[object, set[int]] = defaultdict(set)
    exact_shingles: dict[object, set[int]] = defaultdict(set)
    character_5grams: dict[object, set[int]] = defaultdict(set)
    token_5grams: dict[object, set[int]] = defaultdict(set)
    source_families: dict[object, set[int]] = defaultdict(set)
    empty_character: list[int] = []
    empty_tokens: list[int] = []
    for index, (entry, artifact) in enumerate(
        zip(registry.entries, registry.artifacts, strict=True)
    ):
        if entry.source_content_sha256 is not None:
            raw_content[entry.source_content_sha256].add(index)
        if entry.normalized_text_sha256 is not None:
            normalized_text[entry.normalized_text_sha256].add(index)
        for shingle in exact_13_token_shingles(artifact.text):
            exact_shingles[shingle].add(index)
        characters = _char_5grams(artifact.text)
        tokens = _token_5grams(artifact.text)
        if not characters:
            empty_character.append(index)
        for character_gram in characters:
            character_5grams[character_gram].add(index)
        if not tokens:
            empty_tokens.append(index)
        for token_gram in tokens:
            token_5grams[token_gram].add(index)
        source_families[entry.source_family_id].add(index)
    return _ContaminationMatchIndex(
        raw_content=_freeze_index(raw_content),
        normalized_text=_freeze_index(normalized_text),
        exact_shingles=_freeze_index(exact_shingles),
        character_5grams=_freeze_index(character_5grams),
        token_5grams=_freeze_index(token_5grams),
        empty_character_5grams=tuple(empty_character),
        empty_token_5grams=tuple(empty_tokens),
        source_families=_freeze_index(source_families),
    )


def _candidate_match_indices(
    candidate: ContaminationArtifact,
    candidate_entry: ExclusionEntry,
    match_index: _ContaminationMatchIndex,
) -> tuple[int, ...]:
    possible: set[int] = set()
    if candidate_entry.source_content_sha256 is not None:
        possible.update(match_index.raw_content.get(candidate_entry.source_content_sha256, ()))
    if candidate_entry.normalized_text_sha256 is not None:
        possible.update(match_index.normalized_text.get(candidate_entry.normalized_text_sha256, ()))
    for shingle in exact_13_token_shingles(candidate.text):
        possible.update(match_index.exact_shingles.get(shingle, ()))
    character_grams = _char_5grams(candidate.text)
    if character_grams:
        for character_gram in character_grams:
            possible.update(match_index.character_5grams.get(character_gram, ()))
    else:
        possible.update(match_index.empty_character_5grams)
    token_grams = _token_5grams(candidate.text)
    if token_grams:
        for token_gram in token_grams:
            possible.update(match_index.token_5grams.get(token_gram, ()))
    else:
        possible.update(match_index.empty_token_5grams)
    possible.update(match_index.source_families.get(candidate.source_family_id, ()))
    return tuple(sorted(possible))


@dataclass(frozen=True, slots=True)
class ContaminationAudit:
    status: str
    candidate_artifact_id: str
    exact_matches: tuple[str, ...]
    fuzzy_matches: tuple[str, ...]
    source_family_conflicts: tuple[str, ...]
    semantic_diagnostic: str
    reason: str
    overlap_dispositions: tuple[OverlapDispositionV1, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {"PASS", "BLOCKED"}:
            raise ValueError("contamination audit status must be PASS or BLOCKED")
        if not self.candidate_artifact_id.strip():
            raise ValueError("candidate artifact ID must be non-empty")
        for name in ("exact_matches", "fuzzy_matches", "source_family_conflicts"):
            values = getattr(self, name)
            if values != tuple(sorted(set(values), key=lambda item: item.encode("utf-8"))):
                raise ValueError(f"{name} must use unique canonical artifact-ID ordering")
        if any(not isinstance(item, OverlapDispositionV1) for item in self.overlap_dispositions):
            raise ValueError("contamination audit dispositions must be typed")
        disposition_matches = tuple(item.matched_artifact_id for item in self.overlap_dispositions)
        if disposition_matches != tuple(
            sorted(set(disposition_matches), key=lambda item: item.encode("utf-8"))
        ):
            raise ValueError("audit overlap dispositions must use canonical ordering")
        if len(disposition_matches) != len(set(disposition_matches)):
            raise ValueError("contamination audit cannot duplicate one overlap finding")
        if any(
            item.candidate_artifact_id != self.candidate_artifact_id
            or item.matched_artifact_id not in self.exact_matches
            or overlap_disposition_hash(item) != item.disposition_hash
            for item in self.overlap_dispositions
        ):
            raise ValueError("contamination audit carries an unrelated or stale disposition")
        approved_matches = {
            item.matched_artifact_id
            for item in self.overlap_dispositions
            if item.decision is OverlapDecision.APPROVED
            and item.split_relation is OverlapSplitRelation.SAME_SPLIT
        }
        if self.status == "PASS" and (
            self.fuzzy_matches
            or self.source_family_conflicts
            or set(self.exact_matches) != approved_matches
        ):
            raise ValueError("PASS contamination audit lacks resolved findings")


@dataclass(frozen=True, slots=True)
class ContaminationGateEvidence:
    """Manifest-bound set of mandatory per-artifact contamination decisions."""

    benchmark_manifest_hash: str
    exclusion_manifest_hash: str
    audits: tuple[ContaminationAudit, ...]
    dispositions: tuple[OverlapDispositionV1, ...] = ()

    def __post_init__(self) -> None:
        for name in ("benchmark_manifest_hash", "exclusion_manifest_hash"):
            value = getattr(self, name)
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
                raise ValueError(f"{name} must be a canonical SHA-256 digest")
        if not self.audits or any(not isinstance(item, ContaminationAudit) for item in self.audits):
            raise ValueError("contamination gate evidence must contain typed audit results")
        artifact_ids = tuple(item.candidate_artifact_id for item in self.audits)
        if len(set(artifact_ids)) != len(artifact_ids):
            raise ValueError("contamination gate evidence cannot duplicate artifact audits")
        if artifact_ids != tuple(sorted(artifact_ids, key=lambda item: item.encode("utf-8"))):
            raise ValueError("contamination gate audits must use canonical artifact-ID ordering")
        if any(not isinstance(item, OverlapDispositionV1) for item in self.dispositions):
            raise ValueError("contamination gate dispositions must be typed")
        audit_dispositions = tuple(
            disposition for audit in self.audits for disposition in audit.overlap_dispositions
        )
        canonical_audit_dispositions = tuple(
            sorted(
                audit_dispositions,
                key=lambda item: (
                    item.candidate_artifact_id.encode("utf-8"),
                    item.matched_artifact_id.encode("utf-8"),
                    item.match_kind.value.encode("utf-8"),
                ),
            )
        )
        if canonical_audit_dispositions != self.dispositions:
            raise ValueError("gate dispositions do not match its per-artifact audit evidence")
        disposition_keys = tuple(
            (item.candidate_artifact_id, item.matched_artifact_id, item.match_kind.value)
            for item in self.dispositions
        )
        if disposition_keys != tuple(
            sorted(
                disposition_keys,
                key=lambda item: tuple(part.encode("utf-8") for part in item),
            )
        ):
            raise ValueError("contamination dispositions must use canonical pair ordering")
        if len(disposition_keys) != len(set(disposition_keys)):
            raise ValueError("contamination gate cannot duplicate overlap dispositions")
        disposition_pairs = tuple((item[0], item[1]) for item in disposition_keys)
        if len(disposition_pairs) != len(set(disposition_pairs)):
            raise ValueError("contamination gate cannot adjudicate one artifact pair twice")
        if any(
            overlap_disposition_hash(item) != item.disposition_hash for item in self.dispositions
        ):
            raise ValueError("contamination gate contains a stale overlap disposition hash")

    @property
    def resolved(self) -> bool:
        dispositions = {
            (item.candidate_artifact_id, item.matched_artifact_id): item
            for item in self.dispositions
        }
        expected_pairs = {
            (audit.candidate_artifact_id, matched_id)
            for audit in self.audits
            for matched_id in audit.exact_matches
        }
        if set(dispositions) != expected_pairs:
            return False
        return all(
            item.status == "PASS"
            and not item.fuzzy_matches
            and not item.source_family_conflicts
            and all(
                (disposition := dispositions.get((item.candidate_artifact_id, matched_id)))
                is not None
                and disposition.decision is OverlapDecision.APPROVED
                and disposition.split_relation is OverlapSplitRelation.SAME_SPLIT
                for matched_id in item.exact_matches
            )
            for item in self.audits
        )

    @property
    def disposition_manifest_digest(self) -> str:
        return canonical_hash(tuple(item.disposition_hash for item in self.dispositions))


@dataclass(frozen=True, slots=True)
class ContaminationReport:
    """Policy-bounded audit language; this is not a universal detector claim."""

    audit_label: str
    pretraining_exposure: str = PRETRAINING_EXPOSURE_UNKNOWN

    def __post_init__(self) -> None:
        if self.audit_label not in {
            f"{PSE_V1_CONTAMINATION_AUDIT}=PASS",
            f"{PSE_V1_CONTAMINATION_AUDIT}=BLOCKED",
        }:
            raise ValueError("contamination report must use the policy-bounded V1 audit label")
        if not self.pretraining_exposure.strip():
            raise ValueError("pretraining exposure label must be non-empty")


def build_contamination_report(
    audit: ContaminationAudit,
    *,
    pretraining_exposure: str = PRETRAINING_EXPOSURE_UNKNOWN,
) -> ContaminationReport:
    """Name deterministic V1 overlap results without claiming universal freedom."""

    if not isinstance(audit, ContaminationAudit):
        raise TypeError("audit must be ContaminationAudit")
    return ContaminationReport(
        audit_label=f"{PSE_V1_CONTAMINATION_AUDIT}={audit.status}",
        pretraining_exposure=pretraining_exposure,
    )


def _case_pairs(entry: ExclusionEntry) -> frozenset[tuple[str, str]]:
    return frozenset(zip(entry.benchmark_case_ids, entry.benchmark_case_hashes, strict=True))


def _same_case_components(left: ExclusionEntry, right: ExclusionEntry) -> bool:
    left_pairs = _case_pairs(left)
    right_pairs = _case_pairs(right)
    return bool(left_pairs) and left_pairs == right_pairs


def _split_relation(
    candidate: ContaminationArtifact, matched: ExclusionEntry
) -> OverlapSplitRelation:
    candidate_splits = set(candidate.benchmark_split_names or (candidate.split_name,))
    matched_splits = set(matched.split_names)
    if not candidate_splits or not matched_splits:
        return OverlapSplitRelation.UNBOUND
    if candidate_splits == matched_splits and len(candidate_splits) == 1:
        return OverlapSplitRelation.SAME_SPLIT
    if candidate_splits.isdisjoint(matched_splits):
        return OverlapSplitRelation.CROSS_SPLIT
    return OverlapSplitRelation.MULTI_SPLIT


def _lineage_relation(
    candidate: ContaminationArtifact, matched: ExclusionEntry
) -> OverlapLineageRelation:
    candidate_parent_prefix = "mutation-parent:"
    if candidate.artifact_id.startswith(candidate_parent_prefix):
        parent_hash = candidate.artifact_id.removeprefix(candidate_parent_prefix)
        if parent_hash in matched.benchmark_case_hashes:
            return OverlapLineageRelation.PARENT_CHILD
    if matched.artifact_id.startswith(candidate_parent_prefix):
        parent_hash = matched.artifact_id.removeprefix(candidate_parent_prefix)
        if parent_hash in candidate.benchmark_case_hashes:
            return OverlapLineageRelation.PARENT_CHILD
    if (
        candidate.source_artifact_id is not None
        and candidate.source_artifact_id == matched.source_artifact_id
    ):
        return OverlapLineageRelation.SAME_SOURCE_ARTIFACT
    if _case_pairs(build_exclusion_entry(candidate)) & _case_pairs(matched):
        return OverlapLineageRelation.SAME_CASE_COMPONENTS
    return OverlapLineageRelation.UNRELATED


def _exact_overlap_kind(
    candidate_entry: ExclusionEntry,
    matched_entry: ExclusionEntry,
    candidate_text: str,
    matched_text: str,
) -> tuple[OverlapMatchKind, str] | None:
    if (
        candidate_entry.source_content_sha256 is not None
        and candidate_entry.source_content_sha256 == matched_entry.source_content_sha256
    ):
        return OverlapMatchKind.RAW_CONTENT_SHA256, "NOT_APPLICABLE"
    if (
        candidate_entry.normalized_text_sha256 is not None
        and candidate_entry.normalized_text_sha256 == matched_entry.normalized_text_sha256
    ):
        return OverlapMatchKind.NORMALIZED_TEXT_SHA256, "NOT_APPLICABLE"
    overlapping_shingles = exact_13_token_shingles(candidate_text) & exact_13_token_shingles(
        matched_text
    )
    if overlapping_shingles:
        return (
            OverlapMatchKind.EXACT_13_TOKEN_SHINGLE,
            canonical_hash(tuple(sorted(overlapping_shingles))),
        )
    return None


def _overlap_match_evidence_digest(
    candidate_entry: ExclusionEntry,
    matched_entry: ExclusionEntry,
    match_kind: OverlapMatchKind,
    overlap_fingerprint: str,
) -> str:
    return canonical_hash(
        {
            "candidate_artifact_id": candidate_entry.artifact_id,
            "candidate_document_id": candidate_entry.document_id,
            "candidate_source_artifact_id": candidate_entry.source_artifact_id,
            "candidate_source_content_sha256": candidate_entry.source_content_sha256,
            "candidate_normalized_text_sha256": candidate_entry.normalized_text_sha256,
            "candidate_exact_shingle_digest": candidate_entry.exact_shingle_digest,
            "matched_artifact_id": matched_entry.artifact_id,
            "matched_document_id": matched_entry.document_id,
            "matched_source_artifact_id": matched_entry.source_artifact_id,
            "matched_source_content_sha256": matched_entry.source_content_sha256,
            "matched_normalized_text_sha256": matched_entry.normalized_text_sha256,
            "matched_exact_shingle_digest": matched_entry.exact_shingle_digest,
            "match_kind": match_kind,
            "overlap_fingerprint": overlap_fingerprint,
        }
    )


def _overlap_disposition_payload(disposition: OverlapDispositionV1) -> dict[str, object]:
    return {
        "candidate_artifact_id": disposition.candidate_artifact_id,
        "matched_artifact_id": disposition.matched_artifact_id,
        "match_kind": disposition.match_kind,
        "split_relation": disposition.split_relation,
        "lineage_relation": disposition.lineage_relation,
        "decision": disposition.decision,
        "rationale": disposition.rationale,
        "reviewer_id": disposition.reviewer_id,
        "reviewed_at": disposition.reviewed_at,
        "evidence_digest": disposition.evidence_digest,
    }


def overlap_disposition_hash(disposition: OverlapDispositionV1) -> str:
    """Hash every field of a reviewer disposition except its stored hash."""

    return canonical_hash(_overlap_disposition_payload(disposition))


def _disposition_evidence_digest(
    overlap_digest: str,
    *,
    rationale: str,
    reviewer_id: str,
    reviewed_at: datetime_module.datetime,
) -> str:
    return canonical_hash(
        {
            "overlap_evidence_digest": overlap_digest,
            "rationale": rationale,
            "reviewer_id": reviewer_id,
            "reviewed_at": reviewed_at,
        }
    )


def build_overlap_disposition(
    candidate: ContaminationArtifact,
    matched_artifact_id: str,
    registry: ExclusionRegistry,
    *,
    decision: OverlapDecision,
    rationale: str,
    reviewer_id: str,
    reviewed_at: datetime_module.datetime,
) -> OverlapDispositionV1:
    """Bind a reviewer decision to one exact private-index overlap finding."""

    if len(registry.entries) != len(registry.artifacts):
        raise ValueError("private audit text index is required to adjudicate an overlap")
    matched_index = next(
        (
            index
            for index, entry in enumerate(registry.entries)
            if entry.artifact_id == matched_artifact_id
        ),
        None,
    )
    if matched_index is None:
        raise ValueError("overlap disposition references an unknown matched artifact")
    matched_entry = registry.entries[matched_index]
    matched_artifact = registry.artifacts[matched_index]
    candidate_entry = build_exclusion_entry(candidate)
    if _same_case_components(candidate_entry, matched_entry):
        raise ValueError("same-case artifact components are not cross-case overlap findings")
    exact_match = _exact_overlap_kind(
        candidate_entry, matched_entry, candidate.text, matched_artifact.text
    )
    if exact_match is None:
        raise ValueError("only a currently identified exact overlap may be adjudicated")
    match_kind, overlap_fingerprint = exact_match
    split_relation = _split_relation(candidate, matched_entry)
    lineage_relation = _lineage_relation(candidate, matched_entry)
    overlap_digest = _overlap_match_evidence_digest(
        candidate_entry, matched_entry, match_kind, overlap_fingerprint
    )
    resolved_decision = OverlapDecision(decision)
    evidence_digest = _disposition_evidence_digest(
        overlap_digest,
        rationale=rationale,
        reviewer_id=reviewer_id,
        reviewed_at=reviewed_at,
    )
    payload = {
        "candidate_artifact_id": candidate.artifact_id,
        "matched_artifact_id": matched_artifact_id,
        "match_kind": match_kind,
        "split_relation": split_relation,
        "lineage_relation": lineage_relation,
        "decision": resolved_decision,
        "rationale": rationale,
        "reviewer_id": reviewer_id,
        "reviewed_at": reviewed_at,
        "evidence_digest": evidence_digest,
    }
    return OverlapDispositionV1(
        candidate_artifact_id=candidate.artifact_id,
        matched_artifact_id=matched_artifact_id,
        match_kind=match_kind,
        split_relation=split_relation,
        lineage_relation=lineage_relation,
        decision=resolved_decision,
        rationale=rationale,
        reviewer_id=reviewer_id,
        reviewed_at=reviewed_at,
        evidence_digest=evidence_digest,
        disposition_hash=canonical_hash(payload),
    )


def _validate_overlap_disposition(
    disposition: OverlapDispositionV1,
    candidate: ContaminationArtifact,
    matched_entry: ExclusionEntry,
    matched_artifact: ContaminationArtifact,
    match_kind: OverlapMatchKind,
    overlap_fingerprint: str,
) -> None:
    if overlap_disposition_hash(disposition) != disposition.disposition_hash:
        raise ValueError("overlap disposition hash is stale or forged")
    split_relation = _split_relation(candidate, matched_entry)
    if disposition.candidate_artifact_id != candidate.artifact_id:
        raise ValueError("overlap disposition candidate identity differs from the exact finding")
    if disposition.matched_artifact_id != matched_entry.artifact_id:
        raise ValueError("overlap disposition match identity differs from the exact finding")
    if disposition.match_kind is not match_kind:
        raise ValueError("overlap disposition match kind differs from the exact finding")
    if disposition.split_relation is not split_relation:
        raise ValueError("overlap disposition split relation differs from the exact finding")
    lineage_relation = _lineage_relation(candidate, matched_entry)
    if disposition.lineage_relation is not lineage_relation:
        raise ValueError("overlap disposition lineage relation differs from the exact finding")
    overlap_digest = _overlap_match_evidence_digest(
        build_exclusion_entry(candidate), matched_entry, match_kind, overlap_fingerprint
    )
    expected_evidence_digest = _disposition_evidence_digest(
        overlap_digest,
        rationale=disposition.rationale,
        reviewer_id=disposition.reviewer_id,
        reviewed_at=disposition.reviewed_at,
    )
    if expected_evidence_digest != disposition.evidence_digest:
        raise ValueError("overlap disposition reviewer evidence digest is stale or forged")
    if (
        disposition.decision is OverlapDecision.APPROVED
        and split_relation is not OverlapSplitRelation.SAME_SPLIT
    ):
        raise ValueError("cross-split overlap cannot be overridden by approval")


def audit_contamination(
    candidate: ContaminationArtifact,
    registry: ExclusionRegistry,
    *,
    dispositions: tuple[OverlapDispositionV1, ...] = (),
    _match_index: _ContaminationMatchIndex | None = None,
) -> ContaminationAudit:
    """Run exact, fuzzy, and source-family checks with reviewed exact dispositions."""

    if len(registry.entries) != len(registry.artifacts):
        return ContaminationAudit(
            status="BLOCKED",
            candidate_artifact_id=candidate.artifact_id,
            exact_matches=(),
            fuzzy_matches=(),
            source_family_conflicts=(),
            semantic_diagnostic="NOT_APPLICABLE",
            reason="private audit text index is unavailable for the mandatory fuzzy audit",
        )

    if any(item.candidate_artifact_id != candidate.artifact_id for item in dispositions):
        raise ValueError("audit disposition candidate differs from the requested candidate")
    candidate_dispositions = dispositions
    if len(
        {(item.candidate_artifact_id, item.matched_artifact_id) for item in candidate_dispositions}
    ) != len(candidate_dispositions):
        raise ValueError("duplicate dispositions for one candidate/matched artifact pair")
    dispositions_by_match = {item.matched_artifact_id: item for item in candidate_dispositions}
    candidate_entry = build_exclusion_entry(candidate)
    match_index = _match_index or _build_contamination_match_index(registry)
    exact_matches: list[str] = []
    fuzzy_matches: list[str] = []
    family_conflicts: list[str] = []
    consumed_dispositions: set[str] = set()
    normalized_candidate_text = normalize_text(candidate.text)
    for index in _candidate_match_indices(candidate, candidate_entry, match_index):
        entry = registry.entries[index]
        artifact = registry.artifacts[index]
        if entry.artifact_id == candidate.artifact_id or _same_case_components(
            candidate_entry, entry
        ):
            continue
        exact_match = _exact_overlap_kind(candidate_entry, entry, candidate.text, artifact.text)
        if exact_match is not None:
            match_kind, overlap_fingerprint = exact_match
            disposition = dispositions_by_match.get(entry.artifact_id)
            if disposition is not None:
                _validate_overlap_disposition(
                    disposition,
                    candidate,
                    entry,
                    artifact,
                    match_kind,
                    overlap_fingerprint,
                )
                consumed_dispositions.add(entry.artifact_id)
            exact_matches.append(entry.artifact_id)
            continue

        token_score = token_5gram_jaccard(candidate.text, artifact.text)
        character_score = character_5gram_jaccard(candidate.text, artifact.text)
        normalized_matched_text = normalize_text(artifact.text)
        edit_score = (
            normalized_edit_similarity(candidate.text, artifact.text)
            if max(len(normalized_candidate_text), len(normalized_matched_text)) >= 10
            else 0.0
        )
        if token_score >= 0.85 or character_score >= 0.85 or edit_score >= 0.90:
            fuzzy_matches.append(entry.artifact_id)
        candidate_splits = set(candidate.benchmark_split_names or (candidate.split_name,))
        if entry.source_family_id == candidate.source_family_id and candidate_splits.isdisjoint(
            entry.split_names
        ):
            family_conflicts.append(entry.artifact_id)

    unmatched_dispositions = set(dispositions_by_match) - consumed_dispositions
    if unmatched_dispositions:
        raise ValueError(
            "overlap disposition has no exact identified scorer finding: "
            + ", ".join(sorted(unmatched_dispositions))
        )
    exact_matches.sort(key=lambda item: item.encode("utf-8"))
    fuzzy_matches.sort(key=lambda item: item.encode("utf-8"))
    family_conflicts.sort(key=lambda item: item.encode("utf-8"))
    approved_matches = {
        matched_id
        for matched_id in exact_matches
        if (disposition := dispositions_by_match.get(matched_id)) is not None
        and disposition.decision is OverlapDecision.APPROVED
    }
    unresolved_exact = set(exact_matches) - approved_matches
    blocked = bool(unresolved_exact or fuzzy_matches or family_conflicts)
    reasons = []
    if unresolved_exact:
        reasons.append("exact overlap is unresolved or rejected")
    elif exact_matches:
        reasons.append("exact overlap approved for the identified same-split pair")
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
        overlap_dispositions=tuple(
            sorted(
                candidate_dispositions,
                key=lambda item: (
                    item.matched_artifact_id.encode("utf-8"),
                    item.match_kind.value.encode("utf-8"),
                ),
            )
        ),
    )


def build_contamination_gate_evidence(
    bundle: object,
    registry: ExclusionRegistry,
    *,
    dispositions: tuple[OverlapDispositionV1, ...] = (),
) -> ContaminationGateEvidence:
    """Audit case artifacts and consume exact-pair reviewer dispositions."""

    from dynamislm.benchmark.contracts import ManifestBundleV1

    if not isinstance(bundle, ManifestBundleV1):
        raise TypeError("bundle must be ManifestBundleV1")
    if registry.entries != bundle.exclusion_manifest.entries:
        raise ValueError("private contamination registry differs from the exclusion manifest")
    if len(registry.artifacts) != len(registry.entries):
        raise ValueError("private contamination text material is required for the final gate")
    case_artifacts = tuple(
        artifact for artifact in registry.artifacts if artifact.benchmark_case_ids
    )
    match_index = _build_contamination_match_index(registry)
    case_artifact_ids = {artifact.artifact_id for artifact in case_artifacts}
    if any(item.candidate_artifact_id not in case_artifact_ids for item in dispositions):
        raise ValueError("overlap disposition candidate is absent from the benchmark artifact set")
    canonical_dispositions = tuple(
        sorted(
            dispositions,
            key=lambda item: (
                item.candidate_artifact_id.encode("utf-8"),
                item.matched_artifact_id.encode("utf-8"),
                item.match_kind.value.encode("utf-8"),
            ),
        )
    )
    audits = tuple(
        sorted(
            (
                audit_contamination(
                    artifact,
                    registry,
                    dispositions=tuple(
                        item
                        for item in canonical_dispositions
                        if item.candidate_artifact_id == artifact.artifact_id
                    ),
                    _match_index=match_index,
                )
                for artifact in case_artifacts
            ),
            key=lambda item: item.candidate_artifact_id.encode("utf-8"),
        )
    )
    return ContaminationGateEvidence(
        benchmark_manifest_hash=bundle.benchmark_manifest.benchmark_manifest_hash,
        exclusion_manifest_hash=bundle.exclusion_manifest.manifest_digest,
        audits=audits,
        dispositions=canonical_dispositions,
    )


def case_isolation_values(case: BenchmarkCaseV1) -> tuple[tuple[str, str], ...]:
    """Return the frozen identity dimensions that must remain split-atomic."""

    contamination = case.contamination
    provenance = case.provenance
    values: set[tuple[str, str]] = {("source-family", contamination.source_family_id)}
    for kind, items in (
        ("source-artifact-identity", contamination.source_artifact_ids),
        ("document-identity", contamination.document_ids),
        ("artifact-identity", contamination.artifact_ids),
        ("benchmark-artifact-identity", contamination.benchmark_artifact_ids),
        ("training-exclusion-artifact", contamination.training_exclusion_ids),
        ("construct-test-identity", contamination.construct_test_identity_ids),
    ):
        values.update((kind, item) for item in items)
    for kind, value in (
        ("provider-export", contamination.provider_export_id),
        ("protocol-template", contamination.protocol_template_id),
        ("expert-author-batch", contamination.expert_author_batch_id),
        ("generator-family", provenance.generator_family),
        ("mutation-lineage", provenance.mutation_lineage_id),
    ):
        if value:
            values.add((kind, value))
    for kind, identities in (
        ("seed-namespace", (provenance.seed_namespace, contamination.generator_namespace)),
        ("seed-block", (provenance.seed_block, contamination.generator_seed_block)),
    ):
        values.update((kind, value) for value in identities if value)
    return tuple(
        sorted(values, key=lambda item: (item[0].encode("utf-8"), item[1].encode("utf-8")))
    )


def validate_source_family_isolation(cases: tuple[BenchmarkCaseV1, ...]) -> None:
    """Require every frozen source/test/generator identity to occupy one split."""

    isolation_keys: dict[str, SplitName] = {}
    for case in cases:
        split = case.split.split_name
        if split is None:
            raise ValueError("source-family isolation requires allocated splits")
        assert isinstance(split, SplitName)
        for kind, value in case_isolation_values(case):
            key = f"{kind}:{value}"
            prior = isolation_keys.get(key)
            if prior is not None and prior is not split:
                raise ValueError(f"{kind} crosses split boundary: {value}")
            isolation_keys[key] = split


def validate_case_contamination_binding(case: BenchmarkCaseV1) -> None:
    """Check that case-local contamination references are hash-shaped and immutable."""

    expected = case_payload_hash(case)
    if expected != case.case_payload_hash:
        raise ValueError("contamination validation requires a current case payload hash")
    if case.contamination.source_family_id == "":
        raise ValueError("source family is required for contamination isolation")


def required_exclusion_artifact_ids(case: BenchmarkCaseV1) -> tuple[str, ...]:
    """Derive the complete case-local exclusion artifact inventory."""

    required = {
        f"case:{case.case_id}",
        f"prompt:{case.case_id}",
        f"answer:{case.case_id}",
        f"split:{case.case_id}",
        *case.contamination.artifact_ids,
        *case.contamination.benchmark_artifact_ids,
        *case.contamination.training_exclusion_ids,
    }
    required.update(f"document:{item}" for item in case.contamination.document_ids)
    origin = case.provenance.origin_class
    if origin is CaseOrigin.EXPERT_AUTHORED_SEMANTIC:
        required.add(f"rubric:{case.case_id}")
    if origin is CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION:
        required.update(f"source:{item}" for item in case.provenance.source_artifact_ids)
        required.update(f"evidence:{item}" for item in case.provenance.evidence_span_refs)
    if origin is CaseOrigin.DETERMINISTIC_SYNTHETIC:
        if case.provenance.generator_id is None:
            raise ValueError("synthetic case has no generator identity for exclusion coverage")
        required.add(f"generated:{case.provenance.generator_id}")
    if origin is CaseOrigin.DETERMINISTIC_ENGINE_DERIVED:
        if case.provenance.engine_reference_case_id is None:
            raise ValueError("engine-derived case has no reference identity for exclusion coverage")
        required.add(f"engine:{case.provenance.engine_reference_case_id}")
    if origin is CaseOrigin.ADVERSARIAL_MUTATION:
        if case.provenance.parent_case_hash is None:
            raise ValueError("mutation case has no parent identity for exclusion coverage")
        required.add(f"mutation:{case.case_id}")
        required.add(f"mutation-parent:{case.provenance.parent_case_hash}")
    return tuple(sorted(required, key=lambda item: item.encode("utf-8")))


def validate_exclusion_completeness(
    cases: tuple[BenchmarkCaseV1, ...],
    entries: tuple[ExclusionEntry, ...],
    *,
    require_manifest_artifacts: bool = True,
) -> None:
    """Require exact one-to-one core and many-to-many shared artifact bindings."""

    if not cases:
        raise ValueError("exclusion completeness requires a non-empty case set")
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("exclusion completeness cannot operate on duplicate case IDs")
    artifact_ids = tuple(entry.artifact_id for entry in entries)
    if len(set(artifact_ids)) != len(entries):
        raise ValueError("exclusion registry contains duplicate artifact IDs")
    if artifact_ids != tuple(sorted(artifact_ids, key=lambda item: item.encode("utf-8"))):
        raise ValueError("exclusion registry entries are not canonically ordered")
    by_artifact_id = {entry.artifact_id: entry for entry in entries}
    by_case_id = {case.case_id: case for case in cases}
    case_hashes = {case.case_id: case.case_payload_hash for case in cases}
    required_members: dict[str, dict[str, BenchmarkCaseV1]] = {}
    for case in cases:
        for artifact_id in required_exclusion_artifact_ids(case):
            required_members.setdefault(artifact_id, {})[case.case_id] = case
        for document_id in case.contamination.document_ids:
            entry = by_artifact_id.get(f"document:{document_id}")
            if entry is not None:
                if entry.document_id != document_id:
                    raise ValueError("document exclusion entry has a mismatched document identity")
                typed_documents = tuple(
                    excerpt.document_identity
                    for excerpt in case.input.evidence_excerpts
                    if excerpt.document_identity.document_id == document_id
                )
                if entry.document_content_digest is not None and not any(
                    identity.content_digest == entry.document_content_digest
                    for identity in typed_documents
                ):
                    raise ValueError(
                        "document exclusion digest is absent from typed document identity"
                    )
                if entry.normalized_doi is not None and not any(
                    identity.doi == entry.normalized_doi for identity in typed_documents
                ):
                    raise ValueError("document exclusion DOI differs from typed document identity")
        source_artifacts = {
            excerpt.source_artifact_identity.artifact_id: excerpt.source_artifact_identity
            for excerpt in case.input.evidence_excerpts
        }
        source_documents = {
            (excerpt.source_artifact_identity.artifact_id, excerpt.document_identity.document_id): (
                excerpt.document_identity
            )
            for excerpt in case.input.evidence_excerpts
        }
        for source_artifact_id in case.provenance.source_artifact_ids:
            entry = by_artifact_id.get(f"source:{source_artifact_id}")
            source_artifact = source_artifacts.get(source_artifact_id)
            if entry is None or source_artifact is None:
                continue
            matching_documents = tuple(
                identity
                for (artifact_id, _), identity in source_documents.items()
                if artifact_id == source_artifact_id
            )
            if (
                entry.source_artifact_id != source_artifact_id
                or entry.source_artifact_digest != source_artifact.content_digest
                or not any(
                    entry.document_id == identity.document_id
                    and entry.document_content_digest == identity.content_digest
                    and (entry.normalized_doi is None or entry.normalized_doi == identity.doi)
                    for identity in matching_documents
                )
            ):
                raise ValueError("source artifact exclusion identity/digests are stale")

    observed_case_hashes: dict[str, str] = {}
    manifest_split_names: set[str] = set()
    for entry in entries:
        for case_id, case_hash in zip(
            entry.benchmark_case_ids, entry.benchmark_case_hashes, strict=True
        ):
            if case_id not in case_hashes:
                raise ValueError(f"exclusion registry references unknown case: {case_id}")
            if case_hashes[case_id] != case_hash:
                raise ValueError(f"exclusion registry case hash is stale: {case_id}")
            prior_hash = observed_case_hashes.get(case_id)
            if prior_hash is not None and prior_hash != case_hash:
                raise ValueError(f"exclusion registry has conflicting hashes for case: {case_id}")
            observed_case_hashes[case_id] = case_hash
            expected_cases = required_members.get(entry.artifact_id)
            if expected_cases is None or case_id not in expected_cases:
                raise ValueError(
                    f"exclusion artifact has a stale or unexpected case association: "
                    f"{entry.artifact_id}/{case_id}"
                )
            case = by_case_id[case_id]
            if case.split.split_name is None:
                raise ValueError("exclusion completeness requires allocated split membership")
            manifest_split_names.add(case.split.split_name.value)
        if entry.membership_digests:
            for case_id, membership_digest in zip(
                entry.benchmark_case_ids, entry.membership_digests, strict=True
            ):
                if by_case_id[case_id].split.membership_digest != membership_digest:
                    raise ValueError(
                        f"exclusion artifact has stale membership digest: {entry.artifact_id}"
                    )
    for case in cases:
        required_ids = required_exclusion_artifact_ids(case)
        missing = tuple(item for item in required_ids if item not in by_artifact_id)
        if missing:
            raise ValueError(
                f"case {case.case_id} has incomplete exclusion artifact coverage: {missing}"
            )
        split_entry = by_artifact_id[f"split:{case.case_id}"]
        if not split_entry.membership_digests or split_entry.membership_digests != (
            case.split.membership_digest,
        ):
            raise ValueError(
                f"split artifact does not bind the exact membership digest: {case.case_id}"
            )
    for artifact_id, associated_cases in required_members.items():
        expected_entry = by_artifact_id.get(artifact_id)
        if expected_entry is None:
            continue
        expected_ids = tuple(sorted(associated_cases, key=lambda item: item.encode("utf-8")))
        expected_hashes = tuple(
            associated_cases[case_id].case_payload_hash for case_id in expected_ids
        )
        expected_splits = tuple(
            split
            for split in SPLIT_ORDER
            if any(associated_cases[case_id].split.split_name is split for case_id in expected_ids)
        )
        if (
            expected_entry.benchmark_case_ids != expected_ids
            or expected_entry.benchmark_case_hashes != expected_hashes
        ):
            raise ValueError(
                f"artifact {artifact_id} has stale, duplicate, or incomplete case associations"
            )
        if expected_entry.split_names != expected_splits:
            raise ValueError(f"artifact {artifact_id} has stale split associations")
    if require_manifest_artifacts:
        required_manifest_ids = {
            "manifest:benchmark",
            "manifest:authority",
            "manifest:scorer",
            "manifest:exclusion",
            *(f"manifest:split:{split_name}" for split_name in manifest_split_names),
        }
        missing_manifest_ids = tuple(
            item for item in sorted(required_manifest_ids) if item not in by_artifact_id
        )
        if missing_manifest_ids:
            raise ValueError(
                "exclusion registry is missing benchmark manifest artifacts: "
                + ", ".join(missing_manifest_ids)
            )


__all__ = [
    "PRETRAINING_EXPOSURE_UNKNOWN",
    "PSE_V1_CONTAMINATION_AUDIT",
    "ContaminationArtifact",
    "ContaminationAudit",
    "ContaminationGateEvidence",
    "ContaminationReport",
    "ExclusionRegistry",
    "audit_contamination",
    "build_contamination_gate_evidence",
    "build_contamination_report",
    "build_exclusion_entry",
    "build_overlap_disposition",
    "case_isolation_values",
    "character_5gram_jaccard",
    "exact_13_token_shingles",
    "exact_shingle_digest",
    "fuzzy_fingerprint",
    "jaccard",
    "normalize_text",
    "normalized_edit_similarity",
    "normalized_text_sha256",
    "overlap_disposition_hash",
    "required_exclusion_artifact_ids",
    "token_5gram_jaccard",
    "tokenize",
    "validate_case_contamination_binding",
    "validate_exclusion_completeness",
    "validate_source_family_isolation",
]
