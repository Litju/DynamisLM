"""Hidden-final store abstraction and training-exclusion preflight."""

from __future__ import annotations

import datetime as datetime_module
import re
from dataclasses import dataclass
from typing import Protocol

from dynamislm.benchmark.constants import PreflightStatus, Principal, SplitName
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
from dynamislm.serialization import canonical_hash

HIDDEN_ACCESS_EVIDENCE_MAX_AGE_SECONDS = 300
_HIDDEN_READ_ARTIFACTS = ("PAYLOAD", "ANSWER")


class HiddenAccessDenied(PermissionError):  # noqa: N818 - public contract name is frozen
    """Raised for denied or unverifiable hidden-final access."""


@dataclass(frozen=True, slots=True)
class HiddenStoreDescriptor:
    store_id: str
    store_version: str
    benchmark_manifest_hash: str
    hidden_case_ids: tuple[str, ...]
    payloads_available: bool
    answers_available: bool
    storage_boundary: str
    credential_namespace: str
    hidden_case_hashes: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.store_id.strip() or not self.store_version.strip():
            raise ValueError("hidden store identity must be non-empty")
        if self.storage_boundary != "EXTERNAL_PRIVATE":
            raise ValueError("hidden-final bytes require an EXTERNAL_PRIVATE store")
        if not self.credential_namespace.strip():
            raise ValueError("hidden store requires a separate credential namespace")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", self.benchmark_manifest_hash):
            raise ValueError("hidden store must bind a benchmark manifest digest")
        if not self.hidden_case_ids:
            raise ValueError("hidden store descriptor must identify hidden cases")
        if any(
            not isinstance(case_id, str) or not case_id.strip() for case_id in self.hidden_case_ids
        ):
            raise ValueError("hidden store case IDs must be non-empty strings")
        if len(set(self.hidden_case_ids)) != len(self.hidden_case_ids):
            raise ValueError("hidden store case IDs must be unique")
        if self.hidden_case_ids != tuple(
            sorted(self.hidden_case_ids, key=lambda item: item.encode("utf-8"))
        ):
            raise ValueError("hidden store case IDs must use canonical ordering")
        case_hash_ids = tuple(case_id for case_id, _ in self.hidden_case_hashes)
        if case_hash_ids != self.hidden_case_ids:
            raise ValueError("hidden store hashes must bind the complete canonical case-ID set")
        if any(
            not isinstance(case_id, str)
            or not isinstance(case_hash, str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", case_hash)
            for case_id, case_hash in self.hidden_case_hashes
        ):
            raise ValueError("hidden store case hashes must be canonical SHA-256 digests")
        if not isinstance(self.payloads_available, bool) or not isinstance(
            self.answers_available, bool
        ):
            raise ValueError("hidden store availability flags must be boolean")


@dataclass(frozen=True, slots=True)
class HiddenAccessGrantV1:
    principal: Principal | str
    artifact_kind: str
    credential_present: bool
    read_allowed: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "principal", Principal(self.principal))
        if self.artifact_kind not in _HIDDEN_READ_ARTIFACTS:
            raise ValueError("hidden access evidence only covers PAYLOAD or ANSWER bytes")
        if not isinstance(self.credential_present, bool) or not isinstance(self.read_allowed, bool):
            raise ValueError("hidden access grant results must be boolean observations")


@dataclass(frozen=True, slots=True)
class HiddenStoreAccessEvidenceV1:
    store_id: str
    store_version: str
    credential_namespace: str
    benchmark_manifest_hash: str
    hidden_case_hashes: tuple[tuple[str, str], ...]
    control_plane_id: str
    probe_id: str
    checked_at: datetime_module.datetime
    grants: tuple[HiddenAccessGrantV1, ...]
    evidence_digest: str

    def __post_init__(self) -> None:
        for name in (
            "store_id",
            "store_version",
            "credential_namespace",
            "control_plane_id",
            "probe_id",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must be non-empty")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", self.benchmark_manifest_hash):
            raise ValueError("access evidence must bind a benchmark manifest digest")
        case_ids = tuple(case_id for case_id, _ in self.hidden_case_hashes)
        if not case_ids or case_ids != tuple(
            sorted(case_ids, key=lambda item: item.encode("utf-8"))
        ):
            raise ValueError("access evidence case hashes must use canonical case-ID ordering")
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("access evidence cannot duplicate hidden case IDs")
        for case_id, case_hash in self.hidden_case_hashes:
            if not case_id.strip() or not re.fullmatch(r"sha256:[0-9a-f]{64}", case_hash):
                raise ValueError("access evidence contains an invalid hidden case identity/hash")
        if self.checked_at.tzinfo is None or self.checked_at.utcoffset() is None:
            raise ValueError("access evidence timestamp must include an explicit timezone")
        if any(not isinstance(item, HiddenAccessGrantV1) for item in self.grants):
            raise ValueError("access evidence grants must be typed")
        grant_keys = tuple(
            (Principal(grant.principal).value, grant.artifact_kind) for grant in self.grants
        )
        if grant_keys != tuple(sorted(set(grant_keys))):
            raise ValueError("access evidence grants must be unique and canonically ordered")
        expected_keys = {
            (principal.value, artifact_kind)
            for principal in Principal
            for artifact_kind in _HIDDEN_READ_ARTIFACTS
        }
        if set(grant_keys) != expected_keys:
            raise ValueError("access evidence must probe every principal and hidden byte kind")
        for grant in self.grants:
            expected_allowed = Principal(grant.principal) is Principal.EVALUATION_SERVICE
            if (
                grant.credential_present is not expected_allowed
                or grant.read_allowed is not expected_allowed
            ):
                raise ValueError(
                    "only EVALUATION_SERVICE may have hidden-byte credentials and read access"
                )
        if self.evidence_digest != hidden_access_evidence_digest(self):
            raise ValueError("hidden access evidence digest is stale or forged")


class HiddenStoreAccessProbe(Protocol):
    def probe_access(
        self,
        *,
        store: HiddenStoreDescriptor,
        benchmark_manifest: BenchmarkManifestV1,
        hidden_cases: tuple[BenchmarkCaseV1, ...],
    ) -> HiddenStoreAccessEvidenceV1: ...


def _hidden_access_evidence_payload(
    evidence: HiddenStoreAccessEvidenceV1,
) -> dict[str, object]:
    return {
        "store_id": evidence.store_id,
        "store_version": evidence.store_version,
        "credential_namespace": evidence.credential_namespace,
        "benchmark_manifest_hash": evidence.benchmark_manifest_hash,
        "hidden_case_hashes": evidence.hidden_case_hashes,
        "control_plane_id": evidence.control_plane_id,
        "probe_id": evidence.probe_id,
        "checked_at": evidence.checked_at,
        "grants": evidence.grants,
    }


def hidden_access_evidence_digest(evidence: HiddenStoreAccessEvidenceV1) -> str:
    return canonical_hash(_hidden_access_evidence_payload(evidence))


def build_hidden_access_evidence(
    *,
    store_id: str,
    store_version: str,
    credential_namespace: str,
    benchmark_manifest_hash: str,
    hidden_case_hashes: tuple[tuple[str, str], ...],
    control_plane_id: str,
    probe_id: str,
    checked_at: datetime_module.datetime,
    grants: tuple[HiddenAccessGrantV1, ...],
) -> HiddenStoreAccessEvidenceV1:
    """Bind a live control-plane probe receipt without storing hidden bytes."""

    payload = {
        "store_id": store_id,
        "store_version": store_version,
        "credential_namespace": credential_namespace,
        "benchmark_manifest_hash": benchmark_manifest_hash,
        "hidden_case_hashes": hidden_case_hashes,
        "control_plane_id": control_plane_id,
        "probe_id": probe_id,
        "checked_at": checked_at,
        "grants": grants,
    }
    return HiddenStoreAccessEvidenceV1(
        store_id=store_id,
        store_version=store_version,
        credential_namespace=credential_namespace,
        benchmark_manifest_hash=benchmark_manifest_hash,
        hidden_case_hashes=hidden_case_hashes,
        control_plane_id=control_plane_id,
        probe_id=probe_id,
        checked_at=checked_at,
        grants=grants,
        evidence_digest=canonical_hash(payload),
    )


def validate_hidden_access_evidence(
    evidence: HiddenStoreAccessEvidenceV1,
    *,
    store: HiddenStoreDescriptor,
    benchmark_manifest: BenchmarkManifestV1,
    hidden_cases: tuple[BenchmarkCaseV1, ...],
    now: datetime_module.datetime | None = None,
) -> None:
    """Require a fresh external ACL probe bound to this exact hidden case set."""

    if not isinstance(evidence, HiddenStoreAccessEvidenceV1):
        raise TypeError("live hidden access probe must return HiddenStoreAccessEvidenceV1")
    current_time = now or datetime_module.datetime.now(datetime_module.UTC)
    if current_time.tzinfo is None or current_time.utcoffset() is None:
        raise ValueError("access evidence validation time must be timezone-aware")
    expected_case_hashes = tuple(
        sorted(
            ((case.case_id, case.case_payload_hash) for case in hidden_cases),
            key=lambda item: item[0].encode("utf-8"),
        )
    )
    if (
        evidence.store_id != store.store_id
        or evidence.store_version != store.store_version
        or evidence.credential_namespace != store.credential_namespace
        or evidence.benchmark_manifest_hash != benchmark_manifest.benchmark_manifest_hash
        or evidence.hidden_case_hashes != expected_case_hashes
    ):
        raise ValueError("live hidden access evidence is stale or bound to different hidden cases")
    age_seconds = (current_time - evidence.checked_at).total_seconds()
    if age_seconds < 0 or age_seconds > HIDDEN_ACCESS_EVIDENCE_MAX_AGE_SECONDS:
        raise ValueError("live hidden access evidence is stale or from the future")


@dataclass(frozen=True, slots=True)
class HiddenAccessRequest:
    principal: Principal | str
    case_id: str
    artifact_kind: str
    purpose: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "principal", Principal(self.principal))
        for name in ("case_id", "artifact_kind", "purpose"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must be non-empty")
        if self.artifact_kind not in {"PAYLOAD", "ANSWER", "METADATA"}:
            raise ValueError("unsupported hidden artifact kind")


@dataclass(frozen=True, slots=True)
class HiddenPreflightResult:
    status: PreflightStatus
    reason: str
    case_hash: str | None
    manifest_hash: str | None


def preflight_hidden_access(
    request: HiddenAccessRequest,
    *,
    case: BenchmarkCaseV1,
    benchmark_manifest: BenchmarkManifestV1,
    store: HiddenStoreDescriptor | None,
    access_evidence: HiddenStoreAccessEvidenceV1 | None = None,
) -> HiddenPreflightResult:
    """Verify access policy and bindings before any hidden artifact is resolved."""

    if case.case_id != request.case_id:
        return HiddenPreflightResult(PreflightStatus.BLOCKED, "case ID mismatch", None, None)
    if case.split.split_name is not SplitName.HIDDEN_FINAL:
        return HiddenPreflightResult(
            PreflightStatus.BLOCKED,
            "requested case is not HIDDEN_FINAL",
            case.case_payload_hash,
            benchmark_manifest.benchmark_manifest_hash,
        )
    if request.principal is not Principal.EVALUATION_SERVICE:
        return HiddenPreflightResult(
            PreflightStatus.BLOCKED,
            "hidden payload/answer is inaccessible to non-evaluation principals",
            case.case_payload_hash,
            benchmark_manifest.benchmark_manifest_hash,
        )
    if store is None:
        return HiddenPreflightResult(
            PreflightStatus.BLOCKED,
            "hidden store descriptor is unavailable",
            case.case_payload_hash,
            benchmark_manifest.benchmark_manifest_hash,
        )
    if store.benchmark_manifest_hash != benchmark_manifest.benchmark_manifest_hash:
        return HiddenPreflightResult(
            PreflightStatus.BLOCKED,
            "hidden store is bound to a stale benchmark manifest",
            case.case_payload_hash,
            benchmark_manifest.benchmark_manifest_hash,
        )
    if access_evidence is not None:
        evidence_case_hashes = dict(access_evidence.hidden_case_hashes)
        if (
            access_evidence.store_id != store.store_id
            or access_evidence.store_version != store.store_version
            or access_evidence.credential_namespace != store.credential_namespace
            or access_evidence.benchmark_manifest_hash != benchmark_manifest.benchmark_manifest_hash
            or evidence_case_hashes.get(case.case_id) != case.case_payload_hash
        ):
            return HiddenPreflightResult(
                PreflightStatus.BLOCKED,
                "live access evidence is stale or bound to a different store/case",
                case.case_payload_hash,
                benchmark_manifest.benchmark_manifest_hash,
            )
        grants = {(grant.principal, grant.artifact_kind): grant for grant in access_evidence.grants}
        grant = grants.get((request.principal, request.artifact_kind))
        expected_read = request.principal is Principal.EVALUATION_SERVICE
        if (
            grant is None
            or grant.credential_present is not expected_read
            or grant.read_allowed is not expected_read
        ):
            return HiddenPreflightResult(
                PreflightStatus.BLOCKED,
                "live access evidence does not enforce the hidden store role boundary",
                case.case_payload_hash,
                benchmark_manifest.benchmark_manifest_hash,
            )
    if request.case_id not in store.hidden_case_ids:
        return HiddenPreflightResult(
            PreflightStatus.BLOCKED,
            "hidden case is absent from the bound store",
            case.case_payload_hash,
            benchmark_manifest.benchmark_manifest_hash,
        )
    hidden_hashes = dict(store.hidden_case_hashes)
    if hidden_hashes.get(request.case_id) != case.case_payload_hash:
        return HiddenPreflightResult(
            PreflightStatus.BLOCKED,
            "hidden store case hash is absent or stale",
            case.case_payload_hash,
            benchmark_manifest.benchmark_manifest_hash,
        )
    if request.artifact_kind == "PAYLOAD" and not store.payloads_available:
        return HiddenPreflightResult(
            PreflightStatus.BLOCKED,
            "hidden payload is unavailable",
            case.case_payload_hash,
            benchmark_manifest.benchmark_manifest_hash,
        )
    if request.artifact_kind == "ANSWER" and not store.answers_available:
        return HiddenPreflightResult(
            PreflightStatus.BLOCKED,
            "hidden answer is unavailable",
            case.case_payload_hash,
            benchmark_manifest.benchmark_manifest_hash,
        )
    return HiddenPreflightResult(
        PreflightStatus.PASS,
        "hidden access preflight passed; artifact resolution remains evaluation-service owned",
        case.case_payload_hash,
        benchmark_manifest.benchmark_manifest_hash,
    )


def resolve_hidden_artifact(
    request: HiddenAccessRequest,
    *,
    case: BenchmarkCaseV1,
    benchmark_manifest: BenchmarkManifestV1,
    store: HiddenStoreDescriptor | None,
) -> None:
    """Deliberately do not materialize hidden payloads in the V1 implementation."""

    result = preflight_hidden_access(
        request,
        case=case,
        benchmark_manifest=benchmark_manifest,
        store=store,
    )
    if result.status is not PreflightStatus.PASS:
        raise HiddenAccessDenied(result.reason)
    raise HiddenAccessDenied(
        "hidden artifact resolution is evaluation-service-only and unimplemented"
    )


def preflight_training_exclusion(
    exclusion_manifest: ExclusionManifestV1 | None,
    *,
    expected_manifest_hash: str | None,
    cases: tuple[BenchmarkCaseV1, ...] | None = None,
    benchmark_manifest: BenchmarkManifestV1 | None = None,
    private_audit_index: ExclusionRegistry | None = None,
    private_text_material_required: bool = False,
) -> HiddenPreflightResult:
    """Fail closed before a training/data workflow can construct a corpus."""

    if exclusion_manifest is None or expected_manifest_hash is None:
        return HiddenPreflightResult(
            PreflightStatus.BLOCKED, "exclusion manifest digest is absent", None, None
        )
    actual_hash = exclusion_manifest_hash(exclusion_manifest)
    if actual_hash != exclusion_manifest.manifest_digest or actual_hash != expected_manifest_hash:
        return HiddenPreflightResult(
            PreflightStatus.BLOCKED,
            "exclusion manifest is stale or unverifiable",
            None,
            actual_hash,
        )
    entries = exclusion_manifest.entries
    if len({entry.artifact_id for entry in entries}) != len(entries):
        return HiddenPreflightResult(
            PreflightStatus.BLOCKED,
            "exclusion registry contains duplicate artifact IDs",
            None,
            actual_hash,
        )
    if cases is not None:
        try:
            validate_exclusion_completeness(cases, entries)
        except ValueError as exc:
            return HiddenPreflightResult(
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
                    return HiddenPreflightResult(
                        PreflightStatus.BLOCKED,
                        f"exclusion registry has conflicting hashes for case: {case_id}",
                        None,
                        actual_hash,
                    )
                case_pairs[case_id] = case_hash
        if not case_pairs:
            return HiddenPreflightResult(
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
                return HiddenPreflightResult(
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
                    return HiddenPreflightResult(
                        PreflightStatus.BLOCKED,
                        f"exclusion artifact has stale or duplicate case coverage: {artifact_id}",
                        None,
                        actual_hash,
                    )
            if not artifact_by_id[f"split:{case_id}"].membership_digests:
                return HiddenPreflightResult(
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
            return HiddenPreflightResult(
                PreflightStatus.BLOCKED,
                "exclusion registry has incomplete manifest artifact coverage",
                None,
                actual_hash,
            )
        if benchmark_manifest is not None:
            expected_pairs = dict(benchmark_manifest.case_entries)
            if expected_pairs != case_pairs:
                return HiddenPreflightResult(
                    PreflightStatus.BLOCKED,
                    "exclusion registry case coverage does not match benchmark manifest",
                    None,
                    actual_hash,
                )
    if private_text_material_required:
        if private_audit_index is None or len(private_audit_index.entries) != len(
            private_audit_index.artifacts
        ):
            return HiddenPreflightResult(
                PreflightStatus.BLOCKED,
                "private audit index is required for the mandatory fuzzy comparison",
                None,
                actual_hash,
            )
    return HiddenPreflightResult(
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
