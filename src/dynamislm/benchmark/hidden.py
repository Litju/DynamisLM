"""Compatibility exports and training-exclusion preflight for PSE-V1."""

from __future__ import annotations

from dynamislm.benchmark.constants import PreflightStatus
from dynamislm.benchmark.contamination import (
    ExclusionRegistry,
    validate_exclusion_completeness,
)
from dynamislm.benchmark.contracts import (
    BenchmarkCaseV1,
    BenchmarkManifestV1,
    ExclusionManifestV1,
)
from dynamislm.benchmark.hashing import exclusion_manifest_hash
from dynamislm.benchmark.protected import (
    HIDDEN_ACCESS_EVIDENCE_MAX_AGE_SECONDS,
    HiddenAccessDenied,
    HiddenAccessGrantV1,
    HiddenAccessRequest,
    HiddenPreflightResult,
    HiddenStoreAccessEvidenceV1,
    HiddenStoreAccessProbe,
    HiddenStoreDescriptor,
    ProtectedPreflightResult,
    build_hidden_access_evidence,
    hidden_access_evidence_digest,
    preflight_hidden_access,
    resolve_hidden_artifact,
    validate_hidden_access_evidence,
)


def preflight_training_exclusion(
    exclusion_manifest: ExclusionManifestV1 | None,
    *,
    expected_manifest_hash: str | None,
    cases: tuple[BenchmarkCaseV1, ...] | None = None,
    benchmark_manifest: BenchmarkManifestV1 | None = None,
    private_audit_index: ExclusionRegistry | None = None,
    private_text_material_required: bool = False,
) -> ProtectedPreflightResult:
    """Fail closed before a training/data workflow can construct a corpus."""

    if exclusion_manifest is None or expected_manifest_hash is None:
        return ProtectedPreflightResult(
            PreflightStatus.BLOCKED, "exclusion manifest digest is absent", None, None
        )
    actual_hash = exclusion_manifest_hash(exclusion_manifest)
    if actual_hash != exclusion_manifest.manifest_digest or actual_hash != expected_manifest_hash:
        return ProtectedPreflightResult(
            PreflightStatus.BLOCKED,
            "exclusion manifest is stale or unverifiable",
            None,
            actual_hash,
        )
    entries = exclusion_manifest.entries
    if len({entry.artifact_id for entry in entries}) != len(entries):
        return ProtectedPreflightResult(
            PreflightStatus.BLOCKED,
            "exclusion registry contains duplicate artifact IDs",
            None,
            actual_hash,
        )
    if cases is not None:
        try:
            validate_exclusion_completeness(cases, entries)
        except ValueError as exc:
            return ProtectedPreflightResult(
                PreflightStatus.BLOCKED,
                str(exc),
                None,
                actual_hash,
            )
    else:
        case_pairs: dict[str, str] = {}
        for entry in entries:
            for case_id, case_hash in zip(
                entry.benchmark_case_ids, entry.benchmark_case_hashes, strict=True
            ):
                prior_hash = case_pairs.get(case_id)
                if prior_hash is not None and prior_hash != case_hash:
                    return ProtectedPreflightResult(
                        PreflightStatus.BLOCKED,
                        f"exclusion registry has conflicting hashes for case: {case_id}",
                        None,
                        actual_hash,
                    )
                case_pairs[case_id] = case_hash
        if not case_pairs:
            return ProtectedPreflightResult(
                PreflightStatus.BLOCKED,
                "exclusion registry has no case ID/hash coverage",
                None,
                actual_hash,
            )
        artifact_by_id = {entry.artifact_id: entry for entry in entries}
        for case_id, case_hash in case_pairs.items():
            required_ids = (
                f"case:{case_id}",
                f"prompt:{case_id}",
                f"answer:{case_id}",
                f"split:{case_id}",
            )
            if any(item not in artifact_by_id for item in required_ids):
                return ProtectedPreflightResult(
                    PreflightStatus.BLOCKED,
                    f"exclusion registry has incomplete core artifact coverage: {case_id}",
                    None,
                    actual_hash,
                )
            for artifact_id in required_ids:
                entry = artifact_by_id[artifact_id]
                if entry.benchmark_case_ids != (case_id,) or entry.benchmark_case_hashes != (
                    case_hash,
                ):
                    return ProtectedPreflightResult(
                        PreflightStatus.BLOCKED,
                        f"exclusion artifact has stale or duplicate case coverage: {artifact_id}",
                        None,
                        actual_hash,
                    )
            if not artifact_by_id[f"split:{case_id}"].membership_digests:
                return ProtectedPreflightResult(
                    PreflightStatus.BLOCKED,
                    f"split membership digest is absent: {case_id}",
                    None,
                    actual_hash,
                )
        required_manifest_ids = {
            "manifest:benchmark",
            "manifest:authority",
            "manifest:scorer",
            "manifest:exclusion",
        }
        if any(item not in artifact_by_id for item in required_manifest_ids):
            return ProtectedPreflightResult(
                PreflightStatus.BLOCKED,
                "exclusion registry has incomplete manifest artifact coverage",
                None,
                actual_hash,
            )
        if benchmark_manifest is not None:
            expected_pairs = dict(benchmark_manifest.case_entries)
            if expected_pairs != case_pairs:
                return ProtectedPreflightResult(
                    PreflightStatus.BLOCKED,
                    "exclusion registry case coverage does not match benchmark manifest",
                    None,
                    actual_hash,
                )
    if private_text_material_required:
        if private_audit_index is None or len(private_audit_index.entries) != len(
            private_audit_index.artifacts
        ):
            return ProtectedPreflightResult(
                PreflightStatus.BLOCKED,
                "private audit index is required for the mandatory fuzzy comparison",
                None,
                actual_hash,
            )
    return ProtectedPreflightResult(
        PreflightStatus.PASS, "training exclusion manifest verified", None, actual_hash
    )


__all__ = [
    "HIDDEN_ACCESS_EVIDENCE_MAX_AGE_SECONDS",
    "HiddenAccessDenied",
    "HiddenAccessGrantV1",
    "HiddenAccessRequest",
    "HiddenPreflightResult",
    "HiddenStoreAccessEvidenceV1",
    "HiddenStoreAccessProbe",
    "HiddenStoreDescriptor",
    "build_hidden_access_evidence",
    "hidden_access_evidence_digest",
    "preflight_hidden_access",
    "preflight_training_exclusion",
    "resolve_hidden_artifact",
    "validate_hidden_access_evidence",
]
