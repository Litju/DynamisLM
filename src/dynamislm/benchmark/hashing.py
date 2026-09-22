"""Serialization V3 case, split, authority, scorer, exclusion and benchmark hashes."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import replace

from dynamislm.benchmark.constants import (
    BENCHMARK_SEMANTIC_VERSION,
    CASE_SCHEMA_VERSION,
    EXCLUSION_REGISTRY_VERSION,
    SPLIT_MANIFEST_VERSION,
    SPLIT_ORDER,
    SplitName,
)
from dynamislm.benchmark.contracts import (
    AuthorityManifestEntry,
    AuthorityManifestV1,
    BenchmarkCaseV1,
    BenchmarkManifestV1,
    ExclusionEntry,
    ExclusionManifestV1,
    ManifestBundleV1,
    RES71RuntimeBinding,
    ScorerManifestEntry,
    ScorerManifestV1,
    SplitManifestV1,
    SplitMembershipRecordV1,
)
from dynamislm.serialization import canonical_hash, canonical_json

CASE_CONTENT_KEYS = (
    "benchmark_version",
    "schema_version",
    "case_id",
    "case_version",
    "capability_id",
    "benchmark_family",
    "practitioner_question_class",
    "question",
    "input",
    "source_evidence_refs",
    "expected_answer",
    "authority",
    "refusal_expectation",
    "claim_contract",
    "comparability_contract",
    "scoring_contract",
    "tolerance_contract",
    "provenance",
    "contamination",
    "difficulty",
    "adversarial_tags",
)


def _utf8_key(value: str) -> bytes:
    return value.encode("utf-8")


def case_content_projection(case: BenchmarkCaseV1) -> dict[str, object]:
    """Return exactly the frozen Section 2.6 case-content projection."""

    if not isinstance(case, BenchmarkCaseV1):
        raise TypeError("case must be BenchmarkCaseV1")
    return {
        "benchmark_version": case.benchmark_version,
        "schema_version": case.schema_version,
        "case_id": case.case_id,
        "case_version": case.case_version,
        "capability_id": case.capability_id,
        "benchmark_family": case.benchmark_family,
        "practitioner_question_class": case.practitioner_question_class,
        "question": case.question,
        "input": case.input,
        "source_evidence_refs": case.source_evidence_refs,
        "expected_answer": case.expected_answer,
        "authority": case.authority,
        "refusal_expectation": case.refusal_expectation,
        "claim_contract": case.claim_contract,
        "comparability_contract": case.comparability_contract,
        "scoring_contract": case.scoring_contract,
        "tolerance_contract": case.tolerance_contract,
        "provenance": case.provenance,
        "contamination": case.contamination,
        "difficulty": case.difficulty,
        "adversarial_tags": case.adversarial_tags,
    }


def case_payload_hash(case: BenchmarkCaseV1) -> str:
    """Hash only case meaning, never split or aggregate manifest bindings."""

    projection = case_content_projection(case)
    if tuple(projection) != CASE_CONTENT_KEYS:
        raise ValueError("case content projection key set/order diverges from the V1 contract")
    return canonical_hash(projection)


def canonical_case_content_json(case: BenchmarkCaseV1) -> str:
    """Return the exact canonical JSON input used for the case payload hash."""

    return canonical_json(case_content_projection(case))


def bind_case_payload(case: BenchmarkCaseV1) -> BenchmarkCaseV1:
    """Return a case with its recomputed payload digest."""

    return replace(case, case_payload_hash=case_payload_hash(case))


def validate_case_payload_hash(case: BenchmarkCaseV1) -> None:
    expected = case_payload_hash(case)
    if case.case_payload_hash != expected:
        raise ValueError(
            f"case payload hash mismatch for {case.case_id}: expected {expected}, "
            f"got {case.case_payload_hash}"
        )


def split_membership_digest(record: SplitMembershipRecordV1) -> str:
    """Hash the exact seven-field split membership record."""

    return canonical_hash(record)


def _split_manifest_payload(manifest: SplitManifestV1) -> dict[str, object]:
    return {
        "benchmark_version": manifest.benchmark_version,
        "split_manifest_version": manifest.split_manifest_version,
        "split_name": manifest.split_name,
        "target_case_count": manifest.target_case_count,
        "membership_records": manifest.membership_records,
    }


def split_manifest_hash(manifest: SplitManifestV1) -> str:
    return canonical_hash(_split_manifest_payload(manifest))


def bind_split_manifest(manifest: SplitManifestV1) -> SplitManifestV1:
    return replace(manifest, split_manifest_hash=split_manifest_hash(manifest))


def _authority_manifest_payload(manifest: AuthorityManifestV1) -> dict[str, object]:
    return {
        "benchmark_version": manifest.benchmark_version,
        "authority_bindings": tuple(
            {
                "case_id": entry.case_id,
                "bindings": entry.bindings,
            }
            for entry in manifest.entries
        ),
        "res71_runtime_binding": manifest.runtime_binding,
    }


def authority_manifest_hash(manifest: AuthorityManifestV1) -> str:
    return canonical_hash(_authority_manifest_payload(manifest))


def bind_authority_manifest(manifest: AuthorityManifestV1) -> AuthorityManifestV1:
    return replace(manifest, authority_manifest_hash=authority_manifest_hash(manifest))


def _scorer_manifest_payload(manifest: ScorerManifestV1) -> dict[str, object]:
    return {
        "benchmark_version": manifest.benchmark_version,
        "scorers": tuple(
            {
                "case_id": entry.case_id,
                "scoring_contract": entry.contract,
                "profile_definition_digest": entry.profile_definition_digest,
            }
            for entry in manifest.entries
        ),
    }


def scorer_manifest_hash(manifest: ScorerManifestV1) -> str:
    return canonical_hash(_scorer_manifest_payload(manifest))


def bind_scorer_manifest(manifest: ScorerManifestV1) -> ScorerManifestV1:
    return replace(manifest, scorer_manifest_hash=scorer_manifest_hash(manifest))


def _exclusion_manifest_payload(manifest: ExclusionManifestV1) -> dict[str, object]:
    return {
        "registry_version": manifest.registry_version,
        "entries": manifest.entries,
        "normalization_policy": manifest.normalization_policy,
        "detector_policy": manifest.detector_policy,
        "semantic_diagnostic_policy": manifest.semantic_diagnostic_policy,
    }


def exclusion_manifest_hash(manifest: ExclusionManifestV1) -> str:
    return canonical_hash(_exclusion_manifest_payload(manifest))


def bind_exclusion_manifest(manifest: ExclusionManifestV1) -> ExclusionManifestV1:
    return replace(manifest, manifest_digest=exclusion_manifest_hash(manifest))


def _benchmark_manifest_payload(manifest: BenchmarkManifestV1) -> dict[str, object]:
    return {
        "benchmark_semantic_version": manifest.benchmark_semantic_version,
        "case_schema_version": manifest.case_schema_version,
        "case_entries": manifest.case_entries,
        "split_manifests": manifest.split_manifests,
        "authority_manifest_hash": manifest.authority_manifest_hash,
        "scorer_manifest_hash": manifest.scorer_manifest_hash,
        "contamination_exclusion_manifest_hash": manifest.contamination_exclusion_manifest_hash,
    }


def benchmark_manifest_hash(manifest: BenchmarkManifestV1) -> str:
    return canonical_hash(_benchmark_manifest_payload(manifest))


def bind_benchmark_manifest(manifest: BenchmarkManifestV1) -> BenchmarkManifestV1:
    return replace(manifest, benchmark_manifest_hash=benchmark_manifest_hash(manifest))


def _sort_authority_entries(
    entries: Iterable[AuthorityManifestEntry],
) -> tuple[AuthorityManifestEntry, ...]:
    return tuple(
        sorted(
            entries,
            key=lambda entry: _utf8_key(entry.case_id),
        )
    )


def _sort_scorer_entries(entries: Iterable[ScorerManifestEntry]) -> tuple[ScorerManifestEntry, ...]:
    return tuple(sorted(entries, key=lambda entry: _utf8_key(entry.case_id)))


def _sort_exclusion_entries(entries: Iterable[ExclusionEntry]) -> tuple[ExclusionEntry, ...]:
    return tuple(
        sorted(
            entries,
            key=lambda entry: (
                _utf8_key(entry.artifact_id),
                _utf8_key(entry.source_id),
                _utf8_key(entry.source_content_sha256 or ""),
                _utf8_key(entry.normalized_text_sha256 or ""),
                _utf8_key(entry.exact_shingle_digest),
                _utf8_key(entry.fuzzy_fingerprint),
                _utf8_key(entry.semantic_cluster_id or ""),
                tuple(_utf8_key(item.value) for item in entry.split_names),
            ),
        )
    )


def build_split_manifests(
    cases: tuple[BenchmarkCaseV1, ...],
    target_counts: Mapping[SplitName, int] | None = None,
) -> tuple[tuple[BenchmarkCaseV1, ...], tuple[SplitManifestV1, ...]]:
    """Bind split records/manifests without changing any case payload hash."""

    if not cases:
        raise ValueError("cannot construct split manifests for an empty case set")
    for case in cases:
        validate_case_payload_hash(case)
        if case.split.split_name is None:
            raise ValueError(f"case {case.case_id} has no allocated split")
    counts = {
        split: (
            target_counts[split]
            if target_counts is not None
            else sum(1 for case in cases if case.split.split_name is split)
        )
        for split in SPLIT_ORDER
    }
    by_split: dict[SplitName, list[tuple[BenchmarkCaseV1, SplitMembershipRecordV1]]] = {
        split: [] for split in SPLIT_ORDER
    }
    for case in cases:
        split = case.split.split_name
        assert isinstance(split, SplitName)
        record = SplitMembershipRecordV1(
            benchmark_version=BENCHMARK_SEMANTIC_VERSION,
            split_manifest_version=SPLIT_MANIFEST_VERSION,
            split_name=split,
            case_id=case.case_id,
            case_payload_hash=case.case_payload_hash,
            allocation_stratum=case.split.allocation_stratum,
            isolation_cluster_id=case.split.isolation_cluster_id,
        )
        by_split[split].append((case, record))

    bound_cases = list(cases)
    case_indices = {case.case_id: index for index, case in enumerate(cases)}
    manifests: list[SplitManifestV1] = []
    for split in SPLIT_ORDER:
        pairs = sorted(
            by_split[split],
            key=lambda pair: (_utf8_key(pair[1].case_id), _utf8_key(pair[1].case_payload_hash)),
        )
        if counts[split] != len(pairs):
            raise ValueError(f"target count mismatch for split {split.value}")
        records = tuple(record for _, record in pairs)
        manifest = bind_split_manifest(
            SplitManifestV1(
                benchmark_version=BENCHMARK_SEMANTIC_VERSION,
                split_manifest_version=SPLIT_MANIFEST_VERSION,
                split_name=split,
                target_case_count=counts[split],
                membership_records=records,
                split_manifest_hash="sha256:" + "0" * 64,
            )
        )
        manifests.append(manifest)
        for case, record in pairs:
            index = case_indices[case.case_id]
            bound_cases[index] = replace(
                case,
                split=replace(
                    case.split,
                    split_manifest_version=SPLIT_MANIFEST_VERSION,
                    split_manifest_hash=manifest.split_manifest_hash,
                    membership_digest=split_membership_digest(record),
                ),
            )
    return tuple(bound_cases), tuple(manifests)


def build_authority_manifest(
    cases: tuple[BenchmarkCaseV1, ...], runtime_binding: RES71RuntimeBinding
) -> AuthorityManifestV1:
    from dynamislm.benchmark.authority import validate_res71_runtime_binding

    validate_res71_runtime_binding(runtime_binding)
    entries = _sort_authority_entries(
        AuthorityManifestEntry(case_id=case.case_id, bindings=case.authority) for case in cases
    )
    return bind_authority_manifest(
        AuthorityManifestV1(
            benchmark_version=BENCHMARK_SEMANTIC_VERSION,
            entries=entries,
            runtime_binding=runtime_binding,
            authority_manifest_hash="sha256:" + "0" * 64,
        )
    )


def build_scorer_manifest(cases: tuple[BenchmarkCaseV1, ...]) -> ScorerManifestV1:
    from dynamislm.benchmark.scoring import scorer_profile_digest

    entries = _sort_scorer_entries(
        ScorerManifestEntry(
            case_id=case.case_id,
            contract=case.scoring_contract,
            profile_definition_digest=scorer_profile_digest(case.scoring_contract.profile_id),
        )
        for case in cases
    )
    return bind_scorer_manifest(
        ScorerManifestV1(
            benchmark_version=BENCHMARK_SEMANTIC_VERSION,
            entries=entries,
            scorer_manifest_hash="sha256:" + "0" * 64,
        )
    )


def build_exclusion_manifest(entries: tuple[ExclusionEntry, ...]) -> ExclusionManifestV1:
    return bind_exclusion_manifest(
        ExclusionManifestV1(
            registry_version=EXCLUSION_REGISTRY_VERSION,
            entries=_sort_exclusion_entries(entries),
            normalization_policy="NFKC; lowercase; normalize whitespace and line endings",
            detector_policy=(
                "exact full/paragraph/span SHA-256; exact 13-token shingles; "
                "token/character 5-gram Jaccard >= 0.85; normalized edit similarity >= 0.90"
            ),
            semantic_diagnostic_policy="OPTIONAL_NON_GATING_NOT_APPLICABLE_WHEN_ABSENT",
            manifest_digest="sha256:" + "0" * 64,
        )
    )


def build_benchmark_manifest(
    cases: tuple[BenchmarkCaseV1, ...],
    split_manifests: tuple[SplitManifestV1, ...],
    authority: AuthorityManifestV1,
    scorer: ScorerManifestV1,
    exclusion: ExclusionManifestV1,
) -> BenchmarkManifestV1:
    entries = tuple(
        sorted(
            ((case.case_id, case.case_payload_hash) for case in cases),
            key=lambda item: _utf8_key(item[0]),
        )
    )
    split_entries = tuple(
        (
            split_manifest.split_name,
            split_manifest.split_manifest_version,
            split_manifest.split_manifest_hash,
        )
        for split_manifest in sorted(
            split_manifests,
            key=lambda item: SPLIT_ORDER.index(item.split_name),
        )
    )
    return bind_benchmark_manifest(
        BenchmarkManifestV1(
            benchmark_semantic_version=BENCHMARK_SEMANTIC_VERSION,
            case_schema_version=CASE_SCHEMA_VERSION,
            case_entries=entries,
            split_manifests=split_entries,
            authority_manifest_hash=authority.authority_manifest_hash,
            scorer_manifest_hash=scorer.scorer_manifest_hash,
            contamination_exclusion_manifest_hash=exclusion.manifest_digest,
            benchmark_manifest_hash="sha256:" + "0" * 64,
        )
    )


def build_manifest_bundle(
    cases: tuple[BenchmarkCaseV1, ...],
    exclusion_entries: tuple[ExclusionEntry, ...],
    runtime_binding: RES71RuntimeBinding,
) -> ManifestBundleV1:
    """Construct all bound manifests in the frozen non-circular order."""

    bound_cases, split_manifests = build_split_manifests(cases)
    authority = build_authority_manifest(bound_cases, runtime_binding)
    scorer = build_scorer_manifest(bound_cases)
    exclusion = build_exclusion_manifest(exclusion_entries)
    benchmark = build_benchmark_manifest(bound_cases, split_manifests, authority, scorer, exclusion)
    bundle = ManifestBundleV1(
        cases=bound_cases,
        split_manifests=split_manifests,
        authority_manifest=authority,
        scorer_manifest=scorer,
        exclusion_manifest=exclusion,
        benchmark_manifest=benchmark,
    )
    validate_manifest_bundle(bundle)
    return bundle


def validate_manifest_bundle(bundle: ManifestBundleV1) -> None:
    """Recompute every digest and reject stale, circular, or cross-bound bindings."""

    from dynamislm.benchmark.authority import validate_res71_runtime_binding

    validate_res71_runtime_binding(bundle.authority_manifest.runtime_binding)
    cases = bundle.cases
    case_ids = tuple(case.case_id for case in cases)
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("benchmark manifest contains duplicate case IDs")
    for case in cases:
        validate_case_payload_hash(case)
    if tuple(item.split_name for item in bundle.split_manifests) != tuple(
        sorted(SPLIT_ORDER, key=lambda split: SPLIT_ORDER.index(split))
    ):
        raise ValueError("benchmark bundle must contain each split manifest exactly once")
    if tuple(sorted(case_ids, key=_utf8_key)) != tuple(
        case_id for case_id, _ in bundle.benchmark_manifest.case_entries
    ):
        raise ValueError("benchmark case entry ordering or membership is stale")
    expected_case_entries = tuple(
        sorted(
            ((case.case_id, case.case_payload_hash) for case in cases),
            key=lambda item: _utf8_key(item[0]),
        )
    )
    if bundle.benchmark_manifest.case_entries != expected_case_entries:
        raise ValueError("benchmark case entries do not bind current case hashes")
    for split_manifest in bundle.split_manifests:
        if split_manifest_hash(split_manifest) != split_manifest.split_manifest_hash:
            raise ValueError(f"stale split manifest hash: {split_manifest.split_name.value}")
        for record in split_manifest.membership_records:
            matching = tuple(case for case in cases if case.case_id == record.case_id)
            if len(matching) != 1:
                raise ValueError("split membership references unknown or duplicate case")
            case = matching[0]
            if case.case_payload_hash != record.case_payload_hash:
                raise ValueError("split membership case hash mismatch")
            if case.split.split_name is not record.split_name:
                raise ValueError("case split binding does not match split manifest")
            if case.split.split_manifest_hash != split_manifest.split_manifest_hash:
                raise ValueError("case split manifest binding is stale")
            if case.split.membership_digest != split_membership_digest(record):
                raise ValueError("case membership digest is stale")
    membership_case_ids = tuple(
        record.case_id
        for split_manifest in bundle.split_manifests
        for record in split_manifest.membership_records
    )
    if len(membership_case_ids) != len(set(membership_case_ids)) or set(membership_case_ids) != set(
        case_ids
    ):
        raise ValueError("split membership does not cover each case exactly once")
    from dynamislm.benchmark.split import validate_split_assignment

    validate_split_assignment(cases)
    from dynamislm.benchmark.contamination import validate_exclusion_completeness

    validate_exclusion_completeness(cases, bundle.exclusion_manifest.entries)
    expected_authority_hash = authority_manifest_hash(bundle.authority_manifest)
    if expected_authority_hash != bundle.authority_manifest.authority_manifest_hash:
        raise ValueError("stale authority manifest hash")
    expected_scorer_hash = scorer_manifest_hash(bundle.scorer_manifest)
    if expected_scorer_hash != bundle.scorer_manifest.scorer_manifest_hash:
        raise ValueError("stale scorer manifest hash")
    expected_scorer = build_scorer_manifest(cases)
    if expected_scorer != bundle.scorer_manifest:
        raise ValueError("scorer manifest entries do not bind current case profiles")
    expected_authority = build_authority_manifest(cases, bundle.authority_manifest.runtime_binding)
    if expected_authority != bundle.authority_manifest:
        raise ValueError("authority manifest entries do not bind current case authorities")
    expected_exclusion_hash = exclusion_manifest_hash(bundle.exclusion_manifest)
    if expected_exclusion_hash != bundle.exclusion_manifest.manifest_digest:
        raise ValueError("stale exclusion manifest hash")
    case_hashes = {case.case_id: case.case_payload_hash for case in cases}
    for entry in bundle.exclusion_manifest.entries:
        for case_id, case_hash in zip(
            entry.benchmark_case_ids, entry.benchmark_case_hashes, strict=True
        ):
            if case_id in case_hashes and case_hashes[case_id] != case_hash:
                raise ValueError("exclusion entry binds a stale case hash")
    if (
        bundle.benchmark_manifest.authority_manifest_hash
        != bundle.authority_manifest.authority_manifest_hash
    ):
        raise ValueError("benchmark manifest authority binding is stale")
    if (
        bundle.benchmark_manifest.scorer_manifest_hash
        != bundle.scorer_manifest.scorer_manifest_hash
    ):
        raise ValueError("benchmark manifest scorer binding is stale")
    if (
        bundle.benchmark_manifest.contamination_exclusion_manifest_hash
        != bundle.exclusion_manifest.manifest_digest
    ):
        raise ValueError("benchmark manifest exclusion binding is stale")
    expected_split_entries = tuple(
        (
            item.split_name,
            item.split_manifest_version,
            item.split_manifest_hash,
        )
        for item in sorted(
            bundle.split_manifests, key=lambda item: SPLIT_ORDER.index(item.split_name)
        )
    )
    if bundle.benchmark_manifest.split_manifests != expected_split_entries:
        raise ValueError("benchmark manifest split bindings are stale")
    if (
        benchmark_manifest_hash(bundle.benchmark_manifest)
        != bundle.benchmark_manifest.benchmark_manifest_hash
    ):
        raise ValueError("stale benchmark manifest hash")


__all__ = [
    "CASE_CONTENT_KEYS",
    "authority_manifest_hash",
    "benchmark_manifest_hash",
    "bind_authority_manifest",
    "bind_benchmark_manifest",
    "bind_case_payload",
    "bind_exclusion_manifest",
    "bind_scorer_manifest",
    "bind_split_manifest",
    "build_authority_manifest",
    "build_benchmark_manifest",
    "build_exclusion_manifest",
    "build_manifest_bundle",
    "build_scorer_manifest",
    "build_split_manifests",
    "canonical_case_content_json",
    "case_content_projection",
    "case_payload_hash",
    "exclusion_manifest_hash",
    "scorer_manifest_hash",
    "split_manifest_hash",
    "split_membership_digest",
    "validate_case_payload_hash",
    "validate_manifest_bundle",
]
