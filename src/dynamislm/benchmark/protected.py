"""Protected evaluation-store contracts for validation and hidden cases."""

from __future__ import annotations

import datetime as datetime_module
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from dynamislm.benchmark.constants import PreflightStatus, Principal, SplitName
from dynamislm.benchmark.contracts import BenchmarkCaseV1, BenchmarkManifestV1
from dynamislm.serialization import canonical_hash

PROTECTED_ACCESS_EVIDENCE_MAX_AGE_SECONDS = 300
_PROTECTED_SPLITS = frozenset({SplitName.FROZEN_VALIDATION, SplitName.HIDDEN_FINAL})
_PROTECTED_BYTE_KINDS = ("PAYLOAD", "ANSWER")


class ProtectedStoreAccessDenied(PermissionError):  # noqa: N818 - public contract name is explicit
    """Raised for denied or unverifiable access to protected evaluation bytes."""


@dataclass(frozen=True, slots=True, init=False)
class ProtectedEvaluationStoreDescriptor:
    """Public metadata binding one protected split to its private byte store."""

    store_id: str
    store_version: str
    protected_split: SplitName
    benchmark_manifest_hash: str
    case_ids: tuple[str, ...]
    payloads_available: bool
    answers_available: bool
    storage_boundary: str
    credential_namespace: str
    case_hashes: tuple[tuple[str, str], ...]

    def __init__(
        self,
        *,
        store_id: str,
        store_version: str,
        benchmark_manifest_hash: str,
        payloads_available: bool,
        answers_available: bool,
        storage_boundary: str,
        credential_namespace: str,
        protected_split: SplitName | str | None = None,
        case_ids: tuple[str, ...] | None = None,
        case_hashes: tuple[tuple[str, str], ...] = (),
        hidden_case_ids: tuple[str, ...] | None = None,
        hidden_case_hashes: tuple[tuple[str, str], ...] | None = None,
    ) -> None:
        # The hidden_* keyword aliases preserve the pre-existing hidden-only API.
        if protected_split is None:
            if hidden_case_ids is None and hidden_case_hashes is None:
                raise ValueError("protected evaluation store must identify its protected split")
            split = SplitName.HIDDEN_FINAL
        else:
            split = SplitName(protected_split)
        if case_ids is not None and hidden_case_ids is not None and case_ids != hidden_case_ids:
            raise ValueError("protected and legacy hidden case IDs disagree")
        if hidden_case_ids is not None and split is not SplitName.HIDDEN_FINAL:
            raise ValueError("hidden case ID aliases are only valid for HIDDEN_FINAL")
        selected_case_ids = case_ids if case_ids is not None else hidden_case_ids
        if selected_case_ids is None:
            raise ValueError("protected evaluation store must identify protected cases")
        if hidden_case_hashes is not None:
            if split is not SplitName.HIDDEN_FINAL:
                raise ValueError("hidden case hash aliases are only valid for HIDDEN_FINAL")
            if case_hashes and case_hashes != hidden_case_hashes:
                raise ValueError("protected and legacy hidden case hashes disagree")
            selected_case_hashes = hidden_case_hashes
        else:
            selected_case_hashes = case_hashes

        object.__setattr__(self, "store_id", store_id)
        object.__setattr__(self, "store_version", store_version)
        object.__setattr__(self, "protected_split", split)
        object.__setattr__(self, "benchmark_manifest_hash", benchmark_manifest_hash)
        object.__setattr__(self, "case_ids", selected_case_ids)
        object.__setattr__(self, "payloads_available", payloads_available)
        object.__setattr__(self, "answers_available", answers_available)
        object.__setattr__(self, "storage_boundary", storage_boundary)
        object.__setattr__(self, "credential_namespace", credential_namespace)
        object.__setattr__(self, "case_hashes", selected_case_hashes)
        self.__post_init__()

    def __post_init__(self) -> None:
        if self.protected_split not in _PROTECTED_SPLITS:
            raise ValueError("protected evaluation stores only serve protected splits")
        if not self.store_id.strip() or not self.store_version.strip():
            raise ValueError("protected store identity must be non-empty")
        if self.storage_boundary != "EXTERNAL_PRIVATE":
            raise ValueError("protected split bytes require an EXTERNAL_PRIVATE store")
        if not self.credential_namespace.strip():
            raise ValueError("protected store requires a separate credential namespace")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", self.benchmark_manifest_hash):
            raise ValueError("protected store must bind a benchmark manifest digest")
        if not self.case_ids:
            raise ValueError("protected store descriptor must identify protected cases")
        if any(not isinstance(case_id, str) or not case_id.strip() for case_id in self.case_ids):
            raise ValueError("protected store case IDs must be non-empty strings")
        if len(set(self.case_ids)) != len(self.case_ids):
            raise ValueError("protected store case IDs must be unique")
        if self.case_ids != _canonical_case_ids(self.case_ids):
            raise ValueError("protected store case IDs must use canonical ordering")
        if tuple(case_id for case_id, _ in self.case_hashes) != self.case_ids:
            raise ValueError("protected store hashes must bind the complete canonical case-ID set")
        if any(
            not isinstance(case_id, str)
            or not isinstance(case_hash, str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", case_hash)
            for case_id, case_hash in self.case_hashes
        ):
            raise ValueError("protected store case hashes must be canonical SHA-256 digests")
        if not isinstance(self.payloads_available, bool) or not isinstance(
            self.answers_available, bool
        ):
            raise ValueError("protected store availability flags must be boolean")

    @property
    def hidden_case_ids(self) -> tuple[str, ...]:
        """Legacy alias; meaningful only for a HIDDEN_FINAL descriptor."""

        return self.case_ids

    @property
    def hidden_case_hashes(self) -> tuple[tuple[str, str], ...]:
        """Legacy alias; meaningful only for a HIDDEN_FINAL descriptor."""

        return self.case_hashes


def _canonical_case_ids(case_ids: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted(case_ids, key=lambda item: item.encode("utf-8")))


@dataclass(frozen=True, slots=True)
class ProtectedStoreAccessGrantV1:
    principal: Principal | str
    artifact_kind: str
    credential_present: bool
    read_allowed: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "principal", Principal(self.principal))
        if self.artifact_kind not in _PROTECTED_BYTE_KINDS:
            raise ValueError("protected access evidence only covers PAYLOAD or ANSWER bytes")
        if not isinstance(self.credential_present, bool) or not isinstance(self.read_allowed, bool):
            raise ValueError("protected access grant results must be boolean observations")


@dataclass(frozen=True, slots=True, init=False)
class ProtectedStoreAccessEvidenceV1:
    protected_split: SplitName
    store_id: str
    store_version: str
    credential_namespace: str
    benchmark_manifest_hash: str
    case_hashes: tuple[tuple[str, str], ...]
    control_plane_id: str
    probe_id: str
    checked_at: datetime_module.datetime
    grants: tuple[ProtectedStoreAccessGrantV1, ...]
    evidence_digest: str

    def __init__(
        self,
        *,
        store_id: str,
        store_version: str,
        credential_namespace: str,
        benchmark_manifest_hash: str,
        control_plane_id: str,
        probe_id: str,
        checked_at: datetime_module.datetime,
        grants: tuple[ProtectedStoreAccessGrantV1, ...],
        evidence_digest: str,
        protected_split: SplitName | str | None = None,
        case_hashes: tuple[tuple[str, str], ...] | None = None,
        hidden_case_hashes: tuple[tuple[str, str], ...] | None = None,
    ) -> None:
        # The hidden_case_hashes keyword alias preserves old receipts as HIDDEN_FINAL.
        if protected_split is None:
            if hidden_case_hashes is None:
                raise ValueError("protected access evidence must identify its split")
            split = SplitName.HIDDEN_FINAL
        else:
            split = SplitName(protected_split)
        if (
            case_hashes is not None
            and hidden_case_hashes is not None
            and (case_hashes != hidden_case_hashes)
        ):
            raise ValueError("protected and legacy hidden case hashes disagree")
        selected_hashes = case_hashes if case_hashes is not None else hidden_case_hashes
        if selected_hashes is None:
            raise ValueError("protected access evidence must bind case hashes")
        object.__setattr__(self, "protected_split", split)
        object.__setattr__(self, "store_id", store_id)
        object.__setattr__(self, "store_version", store_version)
        object.__setattr__(self, "credential_namespace", credential_namespace)
        object.__setattr__(self, "benchmark_manifest_hash", benchmark_manifest_hash)
        object.__setattr__(self, "case_hashes", selected_hashes)
        object.__setattr__(self, "control_plane_id", control_plane_id)
        object.__setattr__(self, "probe_id", probe_id)
        object.__setattr__(self, "checked_at", checked_at)
        object.__setattr__(self, "grants", grants)
        object.__setattr__(self, "evidence_digest", evidence_digest)
        self.__post_init__()

    def __post_init__(self) -> None:
        if self.protected_split not in _PROTECTED_SPLITS:
            raise ValueError("access evidence only applies to protected evaluation splits")
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
        case_ids = tuple(case_id for case_id, _ in self.case_hashes)
        if not case_ids or case_ids != _canonical_case_ids(case_ids):
            raise ValueError("access evidence case hashes must use canonical case-ID ordering")
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("access evidence cannot duplicate protected case IDs")
        for case_id, case_hash in self.case_hashes:
            if not case_id.strip() or not re.fullmatch(r"sha256:[0-9a-f]{64}", case_hash):
                raise ValueError("access evidence contains an invalid protected case identity/hash")
        if self.checked_at.tzinfo is None or self.checked_at.utcoffset() is None:
            raise ValueError("access evidence timestamp must include an explicit timezone")
        if not isinstance(self.grants, tuple):
            raise ValueError("access evidence grants must be an immutable tuple")
        if any(not isinstance(item, ProtectedStoreAccessGrantV1) for item in self.grants):
            raise ValueError("access evidence grants must be typed")
        grant_keys = tuple(
            (Principal(grant.principal).value, grant.artifact_kind) for grant in self.grants
        )
        if grant_keys != tuple(sorted(set(grant_keys))):
            raise ValueError("access evidence grants must be unique and canonically ordered")
        expected_keys = {
            (principal.value, artifact_kind)
            for principal in Principal
            for artifact_kind in _PROTECTED_BYTE_KINDS
        }
        if set(grant_keys) != expected_keys:
            raise ValueError("access evidence must probe every principal and protected byte kind")
        for grant in self.grants:
            expected_allowed = Principal(grant.principal) is Principal.EVALUATION_SERVICE
            if (
                grant.credential_present is not expected_allowed
                or grant.read_allowed is not expected_allowed
            ):
                raise ValueError(
                    "only EVALUATION_SERVICE may have protected-byte credentials and read access"
                )
        if self.evidence_digest != protected_access_evidence_digest(self):
            raise ValueError("protected access evidence digest is stale or forged")

    @property
    def hidden_case_hashes(self) -> tuple[tuple[str, str], ...]:
        """Legacy alias; meaningful only for a HIDDEN_FINAL receipt."""

        return self.case_hashes


class ProtectedStoreAccessProbe(Protocol):
    def probe_access(
        self,
        *,
        store: ProtectedEvaluationStoreDescriptor,
        benchmark_manifest: BenchmarkManifestV1,
        protected_cases: tuple[BenchmarkCaseV1, ...],
    ) -> ProtectedStoreAccessEvidenceV1: ...


def _access_evidence_payload(evidence: ProtectedStoreAccessEvidenceV1) -> dict[str, object]:
    return {
        "protected_split": evidence.protected_split,
        "store_id": evidence.store_id,
        "store_version": evidence.store_version,
        "credential_namespace": evidence.credential_namespace,
        "benchmark_manifest_hash": evidence.benchmark_manifest_hash,
        "case_hashes": evidence.case_hashes,
        "control_plane_id": evidence.control_plane_id,
        "probe_id": evidence.probe_id,
        "checked_at": evidence.checked_at,
        "grants": evidence.grants,
    }


def protected_access_evidence_digest(evidence: ProtectedStoreAccessEvidenceV1) -> str:
    return canonical_hash(_access_evidence_payload(evidence))


def build_protected_access_evidence(
    *,
    protected_split: SplitName | str,
    store_id: str,
    store_version: str,
    credential_namespace: str,
    benchmark_manifest_hash: str,
    case_hashes: tuple[tuple[str, str], ...],
    control_plane_id: str,
    probe_id: str,
    checked_at: datetime_module.datetime,
    grants: tuple[ProtectedStoreAccessGrantV1, ...],
) -> ProtectedStoreAccessEvidenceV1:
    """Build a digest-bound receipt from a live protected-store ACL probe."""

    normalized_split = SplitName(protected_split)
    payload = {
        "protected_split": normalized_split,
        "store_id": store_id,
        "store_version": store_version,
        "credential_namespace": credential_namespace,
        "benchmark_manifest_hash": benchmark_manifest_hash,
        "case_hashes": case_hashes,
        "control_plane_id": control_plane_id,
        "probe_id": probe_id,
        "checked_at": checked_at,
        "grants": grants,
    }
    return ProtectedStoreAccessEvidenceV1(
        protected_split=normalized_split,
        store_id=store_id,
        store_version=store_version,
        credential_namespace=credential_namespace,
        benchmark_manifest_hash=benchmark_manifest_hash,
        case_hashes=case_hashes,
        control_plane_id=control_plane_id,
        probe_id=probe_id,
        checked_at=checked_at,
        grants=grants,
        evidence_digest=canonical_hash(payload),
    )


def validate_protected_access_evidence(
    evidence: ProtectedStoreAccessEvidenceV1,
    *,
    store: ProtectedEvaluationStoreDescriptor,
    benchmark_manifest: BenchmarkManifestV1,
    protected_cases: tuple[BenchmarkCaseV1, ...],
    now: datetime_module.datetime | None = None,
) -> None:
    """Require a fresh ACL receipt for this exact store, split, and case/hash set."""

    if not isinstance(evidence, ProtectedStoreAccessEvidenceV1):
        raise TypeError("live protected access probe must return ProtectedStoreAccessEvidenceV1")
    current_time = now or datetime_module.datetime.now(datetime_module.UTC)
    if current_time.tzinfo is None or current_time.utcoffset() is None:
        raise ValueError("access evidence validation time must be timezone-aware")
    expected_case_hashes = tuple(
        sorted(
            ((case.case_id, case.case_payload_hash) for case in protected_cases),
            key=lambda item: item[0].encode("utf-8"),
        )
    )
    if (
        any(case.split.split_name is not store.protected_split for case in protected_cases)
        or not expected_case_hashes
        or evidence.protected_split is not store.protected_split
        or evidence.store_id != store.store_id
        or evidence.store_version != store.store_version
        or evidence.credential_namespace != store.credential_namespace
        or evidence.benchmark_manifest_hash != benchmark_manifest.benchmark_manifest_hash
        or evidence.case_hashes != expected_case_hashes
        or store.case_ids != tuple(case_id for case_id, _ in expected_case_hashes)
        or store.case_hashes != expected_case_hashes
        or store.benchmark_manifest_hash != benchmark_manifest.benchmark_manifest_hash
    ):
        raise ValueError("live protected access evidence is stale or bound to different cases")
    age_seconds = (current_time - evidence.checked_at).total_seconds()
    if age_seconds < 0 or age_seconds > PROTECTED_ACCESS_EVIDENCE_MAX_AGE_SECONDS:
        raise ValueError("live protected access evidence is stale or from the future")


def validate_protected_store_namespace_isolation(
    stores: Mapping[SplitName, ProtectedEvaluationStoreDescriptor],
) -> None:
    """Require exact validation/hidden stores with distinct normalized namespaces."""

    expected_splits = (SplitName.FROZEN_VALIDATION, SplitName.HIDDEN_FINAL)
    if set(stores) != set(expected_splits):
        raise ValueError("protected stores must cover FROZEN_VALIDATION and HIDDEN_FINAL exactly")
    namespace_owner: dict[str, SplitName] = {}
    for split in expected_splits:
        store = stores[split]
        if store.protected_split is not split:
            raise ValueError(f"protected store descriptor does not match {split}")
        normalized = unicodedata.normalize("NFKC", store.credential_namespace).strip().casefold()
        if normalized in namespace_owner:
            raise ValueError(
                "FROZEN_VALIDATION and HIDDEN_FINAL credential namespaces must be distinct"
            )
        namespace_owner[normalized] = split


@dataclass(frozen=True, slots=True)
class ProtectedStoreAccessRequest:
    principal: Principal | str
    case_id: str
    artifact_kind: str
    purpose: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "principal", Principal(self.principal))
        for name in ("case_id", "artifact_kind", "purpose"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must be non-empty")
        if self.artifact_kind not in _PROTECTED_BYTE_KINDS:
            raise ValueError("protected access request must target PAYLOAD or ANSWER bytes")


@dataclass(frozen=True, slots=True)
class ProtectedPreflightResult:
    status: PreflightStatus
    reason: str
    case_hash: str | None
    manifest_hash: str | None


def preflight_protected_store_access(
    request: ProtectedStoreAccessRequest,
    *,
    case: BenchmarkCaseV1,
    benchmark_manifest: BenchmarkManifestV1,
    store: ProtectedEvaluationStoreDescriptor | None,
    access_evidence: ProtectedStoreAccessEvidenceV1 | None,
    now: datetime_module.datetime | None = None,
) -> ProtectedPreflightResult:
    """Check every boundary before evaluation-service byte resolution."""

    manifest_hash = benchmark_manifest.benchmark_manifest_hash
    if case.case_id != request.case_id:
        return ProtectedPreflightResult(PreflightStatus.BLOCKED, "case ID mismatch", None, None)
    if case.split.split_name not in _PROTECTED_SPLITS:
        return ProtectedPreflightResult(
            PreflightStatus.BLOCKED,
            "requested case is not in a protected evaluation split",
            case.case_payload_hash,
            manifest_hash,
        )
    if store is None:
        return ProtectedPreflightResult(
            PreflightStatus.BLOCKED,
            "protected evaluation store descriptor is unavailable",
            case.case_payload_hash,
            manifest_hash,
        )
    if request.principal is not Principal.EVALUATION_SERVICE:
        return ProtectedPreflightResult(
            PreflightStatus.BLOCKED,
            "protected payload/answer bytes are inaccessible to non-evaluation principals",
            case.case_payload_hash,
            manifest_hash,
        )
    if store.protected_split is not case.split.split_name:
        return ProtectedPreflightResult(
            PreflightStatus.BLOCKED,
            "protected store is bound to a different split",
            case.case_payload_hash,
            manifest_hash,
        )
    if access_evidence is None:
        return ProtectedPreflightResult(
            PreflightStatus.BLOCKED,
            "fresh live protected-store access evidence is required",
            case.case_payload_hash,
            manifest_hash,
        )
    try:
        _validate_single_case_access_evidence(
            access_evidence,
            store=store,
            benchmark_manifest=benchmark_manifest,
            case=case,
            now=now,
        )
    except (TypeError, ValueError) as exc:
        return ProtectedPreflightResult(
            PreflightStatus.BLOCKED,
            str(exc),
            case.case_payload_hash,
            manifest_hash,
        )
    if request.case_id not in store.case_ids:
        return ProtectedPreflightResult(
            PreflightStatus.BLOCKED,
            "case is absent from the bound protected store",
            case.case_payload_hash,
            manifest_hash,
        )
    store_hashes = dict(store.case_hashes)
    if store_hashes.get(request.case_id) != case.case_payload_hash:
        return ProtectedPreflightResult(
            PreflightStatus.BLOCKED,
            "protected store case hash is absent or stale",
            case.case_payload_hash,
            manifest_hash,
        )
    grants = {(grant.principal, grant.artifact_kind): grant for grant in access_evidence.grants}
    grant = grants.get((request.principal, request.artifact_kind))
    if grant is None or not grant.credential_present or not grant.read_allowed:
        return ProtectedPreflightResult(
            PreflightStatus.BLOCKED,
            "live access evidence lacks the evaluation-service credential/read grant",
            case.case_payload_hash,
            manifest_hash,
        )
    if request.artifact_kind == "PAYLOAD" and not store.payloads_available:
        return ProtectedPreflightResult(
            PreflightStatus.BLOCKED,
            "protected payload is unavailable",
            case.case_payload_hash,
            manifest_hash,
        )
    if request.artifact_kind == "ANSWER" and not store.answers_available:
        return ProtectedPreflightResult(
            PreflightStatus.BLOCKED,
            "protected answer is unavailable",
            case.case_payload_hash,
            manifest_hash,
        )
    return ProtectedPreflightResult(
        PreflightStatus.PASS,
        "protected access preflight passed; byte resolution remains evaluation-service owned",
        case.case_payload_hash,
        manifest_hash,
    )


def _validate_single_case_access_evidence(
    evidence: ProtectedStoreAccessEvidenceV1,
    *,
    store: ProtectedEvaluationStoreDescriptor,
    benchmark_manifest: BenchmarkManifestV1,
    case: BenchmarkCaseV1,
    now: datetime_module.datetime | None,
) -> None:
    expected_hashes = store.case_hashes
    if (
        not isinstance(evidence, ProtectedStoreAccessEvidenceV1)
        or evidence.protected_split is not store.protected_split
        or evidence.store_id != store.store_id
        or evidence.store_version != store.store_version
        or evidence.credential_namespace != store.credential_namespace
        or evidence.benchmark_manifest_hash != benchmark_manifest.benchmark_manifest_hash
        or evidence.case_hashes != expected_hashes
        or dict(evidence.case_hashes).get(case.case_id) != case.case_payload_hash
        or store.benchmark_manifest_hash != benchmark_manifest.benchmark_manifest_hash
    ):
        raise ValueError(
            "live protected access evidence is stale or bound to a different store/case"
        )
    current_time = now or datetime_module.datetime.now(datetime_module.UTC)
    if current_time.tzinfo is None or current_time.utcoffset() is None:
        raise ValueError("access evidence validation time must be timezone-aware")
    age_seconds = (current_time - evidence.checked_at).total_seconds()
    if age_seconds < 0 or age_seconds > PROTECTED_ACCESS_EVIDENCE_MAX_AGE_SECONDS:
        raise ValueError("live protected access evidence is stale or from the future")


def preflight_public_development_distribution(
    case: BenchmarkCaseV1, artifact_kind: str
) -> ProtectedPreflightResult:
    """Confirm that public-development payloads and answers are distributable."""

    if artifact_kind not in _PROTECTED_BYTE_KINDS:
        return ProtectedPreflightResult(
            PreflightStatus.BLOCKED, "unsupported distributable artifact kind", None, None
        )
    if case.split.split_name is not SplitName.PUBLIC_DEVELOPMENT:
        return ProtectedPreflightResult(
            PreflightStatus.BLOCKED,
            "only PUBLIC_DEVELOPMENT payloads and answers are distributable",
            case.case_payload_hash,
            None,
        )
    return ProtectedPreflightResult(
        PreflightStatus.PASS,
        "PUBLIC_DEVELOPMENT artifact is distributable subject to training exclusion",
        case.case_payload_hash,
        None,
    )


def resolve_protected_artifact(
    request: ProtectedStoreAccessRequest,
    *,
    case: BenchmarkCaseV1,
    benchmark_manifest: BenchmarkManifestV1,
    store: ProtectedEvaluationStoreDescriptor | None,
    access_evidence: ProtectedStoreAccessEvidenceV1 | None,
) -> None:
    """Keep byte resolution unimplemented in this pre-materialization mission."""

    result = preflight_protected_store_access(
        request,
        case=case,
        benchmark_manifest=benchmark_manifest,
        store=store,
        access_evidence=access_evidence,
    )
    if result.status is not PreflightStatus.PASS:
        raise ProtectedStoreAccessDenied(result.reason)
    raise ProtectedStoreAccessDenied(
        "protected artifact resolution is evaluation-service-only and unimplemented"
    )


# Compatibility aliases retain the hidden-only API while using the generalized contract.
HIDDEN_ACCESS_EVIDENCE_MAX_AGE_SECONDS = PROTECTED_ACCESS_EVIDENCE_MAX_AGE_SECONDS
HiddenAccessDenied = ProtectedStoreAccessDenied
HiddenAccessGrantV1 = ProtectedStoreAccessGrantV1
HiddenAccessRequest = ProtectedStoreAccessRequest
HiddenPreflightResult = ProtectedPreflightResult
HiddenStoreAccessEvidenceV1 = ProtectedStoreAccessEvidenceV1
HiddenStoreAccessProbe = ProtectedStoreAccessProbe
HiddenStoreDescriptor = ProtectedEvaluationStoreDescriptor


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
    grants: tuple[ProtectedStoreAccessGrantV1, ...],
) -> ProtectedStoreAccessEvidenceV1:
    return build_protected_access_evidence(
        protected_split=SplitName.HIDDEN_FINAL,
        store_id=store_id,
        store_version=store_version,
        credential_namespace=credential_namespace,
        benchmark_manifest_hash=benchmark_manifest_hash,
        case_hashes=hidden_case_hashes,
        control_plane_id=control_plane_id,
        probe_id=probe_id,
        checked_at=checked_at,
        grants=grants,
    )


def hidden_access_evidence_digest(evidence: ProtectedStoreAccessEvidenceV1) -> str:
    return protected_access_evidence_digest(evidence)


def validate_hidden_access_evidence(
    evidence: ProtectedStoreAccessEvidenceV1,
    *,
    store: ProtectedEvaluationStoreDescriptor,
    benchmark_manifest: BenchmarkManifestV1,
    hidden_cases: tuple[BenchmarkCaseV1, ...],
    now: datetime_module.datetime | None = None,
) -> None:
    if store.protected_split is not SplitName.HIDDEN_FINAL:
        raise ValueError("hidden access validation requires a HIDDEN_FINAL store")
    validate_protected_access_evidence(
        evidence,
        store=store,
        benchmark_manifest=benchmark_manifest,
        protected_cases=hidden_cases,
        now=now,
    )


def preflight_hidden_access(
    request: ProtectedStoreAccessRequest,
    *,
    case: BenchmarkCaseV1,
    benchmark_manifest: BenchmarkManifestV1,
    store: ProtectedEvaluationStoreDescriptor | None,
    access_evidence: ProtectedStoreAccessEvidenceV1 | None = None,
) -> ProtectedPreflightResult:
    if case.split.split_name is not SplitName.HIDDEN_FINAL:
        return ProtectedPreflightResult(
            PreflightStatus.BLOCKED,
            "requested case is not HIDDEN_FINAL",
            case.case_payload_hash,
            benchmark_manifest.benchmark_manifest_hash,
        )
    return preflight_protected_store_access(
        request,
        case=case,
        benchmark_manifest=benchmark_manifest,
        store=store,
        access_evidence=access_evidence,
    )


def resolve_hidden_artifact(
    request: ProtectedStoreAccessRequest,
    *,
    case: BenchmarkCaseV1,
    benchmark_manifest: BenchmarkManifestV1,
    store: ProtectedEvaluationStoreDescriptor | None,
) -> None:
    if case.split.split_name is not SplitName.HIDDEN_FINAL:
        raise ProtectedStoreAccessDenied("requested case is not HIDDEN_FINAL")
    resolve_protected_artifact(
        request,
        case=case,
        benchmark_manifest=benchmark_manifest,
        store=store,
        access_evidence=None,
    )


__all__ = [
    "PROTECTED_ACCESS_EVIDENCE_MAX_AGE_SECONDS",
    "ProtectedEvaluationStoreDescriptor",
    "ProtectedPreflightResult",
    "ProtectedStoreAccessDenied",
    "ProtectedStoreAccessEvidenceV1",
    "ProtectedStoreAccessGrantV1",
    "ProtectedStoreAccessProbe",
    "ProtectedStoreAccessRequest",
    "build_protected_access_evidence",
    "preflight_protected_store_access",
    "preflight_public_development_distribution",
    "protected_access_evidence_digest",
    "resolve_protected_artifact",
    "validate_protected_access_evidence",
    "validate_protected_store_namespace_isolation",
]
