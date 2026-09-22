"""Deterministic V1 contamination and exclusion controls."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass

from dynamislm.benchmark.constants import SPLIT_ORDER, CaseOrigin, SplitName
from dynamislm.benchmark.contracts import (
    BenchmarkCaseV1,
    ExclusionEntry,
)
from dynamislm.benchmark.hashing import case_payload_hash

_TOKEN_RE = re.compile(r"\w+|[^\w\s]", flags=re.UNICODE)

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
    membership_digests: tuple[str, ...] = ()
    exclusion_reason: str = "PSE-V1 benchmark/training exclusion"
    benchmark_split_names: tuple[SplitName, ...] = ()

    def __post_init__(self) -> None:
        for name in ("artifact_id", "source_id", "text", "source_family_id", "exclusion_reason"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be non-empty")
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
        split_names=artifact.benchmark_split_names or (artifact.split_name,),
        exclusion_reason=artifact.exclusion_reason,
        membership_digests=artifact.membership_digests,
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


@dataclass(frozen=True, slots=True)
class ContaminationGateEvidence:
    """Manifest-bound set of mandatory per-artifact contamination decisions."""

    benchmark_manifest_hash: str
    exclusion_manifest_hash: str
    audits: tuple[ContaminationAudit, ...]

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

    @property
    def resolved(self) -> bool:
        return all(
            item.status == "PASS"
            and not item.exact_matches
            and not item.fuzzy_matches
            and not item.source_family_conflicts
            for item in self.audits
        )


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


def audit_contamination(
    candidate: ContaminationArtifact,
    registry: ExclusionRegistry,
    *,
    approved_overlap_artifact_ids: tuple[str, ...] = (),
) -> ContaminationAudit:
    """Run mandatory exact, fuzzy, and source-family checks in frozen order."""

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

    approved = set(approved_overlap_artifact_ids)
    approved_case_pairs = {
        (case_id, case_hash)
        for entry in registry.entries
        if entry.artifact_id in approved
        for case_id, case_hash in zip(
            entry.benchmark_case_ids, entry.benchmark_case_hashes, strict=True
        )
    }
    candidate_entry = build_exclusion_entry(candidate)
    exact_matches: list[str] = []
    fuzzy_matches: list[str] = []
    family_conflicts: list[str] = []
    candidate_shingles = exact_13_token_shingles(candidate.text)
    for entry, artifact in zip(registry.entries, registry.artifacts, strict=False):
        entry_case_pairs = set(
            zip(entry.benchmark_case_ids, entry.benchmark_case_hashes, strict=True)
        )
        if entry.artifact_id in approved or entry_case_pairs & approved_case_pairs:
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
                if candidate.split_name not in entry.split_names:
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


def build_contamination_gate_evidence(
    bundle: object,
    registry: ExclusionRegistry,
) -> ContaminationGateEvidence:
    """Compute mandatory deterministic audits bound to a manifest bundle."""

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
    audits = tuple(
        sorted(
            (
                audit_contamination(
                    artifact,
                    registry,
                    approved_overlap_artifact_ids=(artifact.artifact_id,),
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
    )


def case_isolation_values(case: BenchmarkCaseV1) -> tuple[tuple[str, str], ...]:
    """Return the frozen identity dimensions that must remain split-atomic."""

    contamination = case.contamination
    provenance = case.provenance
    values: set[tuple[str, str]] = {("source-family", contamination.source_family_id)}
    for kind, items in (
        ("document-identity", contamination.document_ids),
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
        entry = by_artifact_id.get(artifact_id)
        if entry is None:
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
            entry.benchmark_case_ids != expected_ids
            or entry.benchmark_case_hashes != expected_hashes
        ):
            raise ValueError(
                f"artifact {artifact_id} has stale, duplicate, or incomplete case associations"
            )
        if entry.split_names != expected_splits:
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
    "case_isolation_values",
    "character_5gram_jaccard",
    "exact_13_token_shingles",
    "exact_shingle_digest",
    "fuzzy_fingerprint",
    "jaccard",
    "normalize_text",
    "normalized_edit_similarity",
    "normalized_text_sha256",
    "required_exclusion_artifact_ids",
    "token_5gram_jaccard",
    "tokenize",
    "validate_case_contamination_binding",
    "validate_exclusion_completeness",
    "validate_source_family_isolation",
]
