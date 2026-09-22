"""Hidden-final store abstraction and training-exclusion preflight."""

from __future__ import annotations

import re
from dataclasses import dataclass

from dynamislm.benchmark.constants import PreflightStatus, Principal, SplitName
from dynamislm.benchmark.contracts import BenchmarkCaseV1, BenchmarkManifestV1, ExclusionManifestV1
from dynamislm.benchmark.hashing import exclusion_manifest_hash


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
    hidden_case_hashes: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.store_id.strip() or not self.store_version.strip():
            raise ValueError("hidden store identity must be non-empty")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", self.benchmark_manifest_hash):
            raise ValueError("hidden store must bind a benchmark manifest digest")
        if not self.hidden_case_ids:
            raise ValueError("hidden store descriptor must identify hidden cases")
        if len(set(self.hidden_case_ids)) != len(self.hidden_case_ids):
            raise ValueError("hidden store case IDs must be unique")
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
    return HiddenPreflightResult(
        PreflightStatus.PASS, "training exclusion manifest verified", None, actual_hash
    )


__all__ = [
    "HiddenAccessDenied",
    "HiddenAccessRequest",
    "HiddenPreflightResult",
    "HiddenStoreDescriptor",
    "preflight_hidden_access",
    "preflight_training_exclusion",
    "resolve_hidden_artifact",
]
