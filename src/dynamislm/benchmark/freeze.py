"""Final V1 freeze qualification, separate from infrastructure manifest validation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dynamislm.benchmark.constants import SPLIT_ORDER, PreflightStatus, Principal, SplitName
from dynamislm.benchmark.contamination import (
    ContaminationGateEvidence,
    ExclusionRegistry,
    build_contamination_gate_evidence,
    validate_exclusion_completeness,
)
from dynamislm.benchmark.contracts import ManifestBundleV1, OverlapDispositionV1
from dynamislm.benchmark.coverage import minimum_full_coverage_case_count, validate_case_coverage
from dynamislm.benchmark.hashing import validate_manifest_bundle
from dynamislm.benchmark.hidden import preflight_training_exclusion
from dynamislm.benchmark.protected import (
    ProtectedEvaluationStoreDescriptor,
    ProtectedStoreAccessEvidenceV1,
    ProtectedStoreAccessProbe,
    ProtectedStoreAccessRequest,
    preflight_protected_store_access,
    preflight_public_development_distribution,
    validate_protected_access_evidence,
    validate_protected_store_namespace_isolation,
)
from dynamislm.benchmark.public_repository import (
    ProtectedRepositoryLeakGuardV1,
    validate_protected_repository_boundary,
)
from dynamislm.benchmark.split import validate_split_assignment


@dataclass(frozen=True, slots=True)
class FinalV1FreezeValidation:
    benchmark_manifest_hash: str
    split_counts: tuple[tuple[SplitName, int], ...]
    case_count: int
    contamination_audit_count: int
    contamination_dispositions: tuple[OverlapDispositionV1, ...]
    contamination_disposition_digest: str
    hidden_case_count: int
    protected_access_evidence: tuple[tuple[SplitName, ProtectedStoreAccessEvidenceV1], ...]
    public_repository_guard: ProtectedRepositoryLeakGuardV1
    status: str = "PASS"

    @property
    def frozen_validation_access_evidence(self) -> ProtectedStoreAccessEvidenceV1:
        return dict(self.protected_access_evidence)[SplitName.FROZEN_VALIDATION]

    @property
    def hidden_final_access_evidence(self) -> ProtectedStoreAccessEvidenceV1:
        return dict(self.protected_access_evidence)[SplitName.HIDDEN_FINAL]


def validate_final_v1_freeze(
    bundle: ManifestBundleV1,
    *,
    exclusion_registry: ExclusionRegistry,
    contamination_gate: ContaminationGateEvidence,
    protected_stores: Mapping[SplitName, ProtectedEvaluationStoreDescriptor],
    protected_access_probe: ProtectedStoreAccessProbe | None,
    repository_root: str | Path,
) -> FinalV1FreezeValidation:
    """Require full coverage, public-leak guard, and both protected-store ACLs."""

    validate_manifest_bundle(bundle)
    cases = bundle.cases
    fixture_cases = tuple(
        case.case_id
        for case in cases
        if "FIXTURE" in case.adversarial_tags
        or "fixture" in case.provenance.population_scope.casefold()
    )
    if fixture_cases:
        raise ValueError("fixture-only cases cannot satisfy the FINAL V1 freeze gate")

    public_repository_guard = validate_protected_repository_boundary(
        cases,
        repository_root=repository_root,
        benchmark_manifest_hash=bundle.benchmark_manifest.benchmark_manifest_hash,
    )

    if len(cases) < minimum_full_coverage_case_count():
        raise ValueError("FINAL V1 freeze requires benchmark-scale full D/V/H coverage")
    coverage = validate_case_coverage(cases, require_all_splits=True)
    if coverage.status != "PASS":
        raise ValueError(f"FINAL V1 freeze coverage is incomplete: {coverage.reason}")
    validate_split_assignment(cases)
    validate_exclusion_completeness(cases, bundle.exclusion_manifest.entries)

    if exclusion_registry.entries != bundle.exclusion_manifest.entries:
        raise ValueError("FINAL V1 freeze private exclusion registry is stale")
    expected_audit_ids = tuple(
        sorted(
            (
                entry.artifact_id
                for entry in bundle.exclusion_manifest.entries
                if entry.benchmark_case_ids
            ),
            key=lambda item: item.encode("utf-8"),
        )
    )
    actual_audit_ids = tuple(item.candidate_artifact_id for item in contamination_gate.audits)
    if (
        contamination_gate.benchmark_manifest_hash
        != bundle.benchmark_manifest.benchmark_manifest_hash
        or contamination_gate.exclusion_manifest_hash != bundle.exclusion_manifest.manifest_digest
        or actual_audit_ids != expected_audit_ids
        or not contamination_gate.resolved
    ):
        raise ValueError("FINAL V1 freeze has an unresolved or stale contamination gate")
    recomputed_contamination_gate = build_contamination_gate_evidence(
        bundle,
        exclusion_registry,
        dispositions=contamination_gate.dispositions,
    )
    if recomputed_contamination_gate != contamination_gate:
        raise ValueError("FINAL V1 freeze contamination evidence does not recompute from artifacts")

    exclusion_preflight = preflight_training_exclusion(
        bundle.exclusion_manifest,
        expected_manifest_hash=bundle.exclusion_manifest.manifest_digest,
        cases=cases,
        benchmark_manifest=bundle.benchmark_manifest,
        private_audit_index=exclusion_registry,
        private_text_material_required=True,
    )
    if exclusion_preflight.status is not PreflightStatus.PASS:
        raise ValueError(
            f"FINAL V1 freeze exclusion preflight failed: {exclusion_preflight.reason}"
        )

    protected_splits = (SplitName.FROZEN_VALIDATION, SplitName.HIDDEN_FINAL)
    if set(protected_stores) != set(protected_splits):
        raise ValueError("FINAL V1 freeze requires stores for both protected evaluation splits")
    public_cases = tuple(
        case for case in cases if case.split.split_name is SplitName.PUBLIC_DEVELOPMENT
    )
    for case in public_cases:
        for artifact_kind in ("PAYLOAD", "ANSWER"):
            if (
                preflight_public_development_distribution(case, artifact_kind).status
                is not PreflightStatus.PASS
            ):
                raise ValueError(
                    "PUBLIC_DEVELOPMENT payloads and answers must remain distributable"
                )

    cases_by_protected_split = {
        split: tuple(
            sorted(
                (case for case in cases if case.split.split_name is split),
                key=lambda item: item.case_id.encode("utf-8"),
            )
        )
        for split in protected_splits
    }
    validate_protected_store_namespace_isolation(protected_stores)
    for split in protected_splits:
        store = protected_stores[split]
        protected_cases = cases_by_protected_split[split]
        expected_ids = tuple(case.case_id for case in protected_cases)
        expected_hashes = tuple((case.case_id, case.case_payload_hash) for case in protected_cases)
        if (
            store.protected_split is not split
            or store.benchmark_manifest_hash != bundle.benchmark_manifest.benchmark_manifest_hash
            or store.case_ids != expected_ids
            or store.case_hashes != expected_hashes
            or not store.payloads_available
            or not store.answers_available
            or store.storage_boundary != "EXTERNAL_PRIVATE"
            or not store.credential_namespace
        ):
            raise ValueError(f"FINAL V1 freeze {split} store policy or binding is incomplete")

    if protected_access_probe is None:
        raise ValueError("FINAL V1 freeze requires live protected-store access probes")
    access_evidence_by_split: dict[SplitName, ProtectedStoreAccessEvidenceV1] = {}
    for split in protected_splits:
        store = protected_stores[split]
        protected_cases = cases_by_protected_split[split]
        access_evidence = protected_access_probe.probe_access(
            store=store,
            benchmark_manifest=bundle.benchmark_manifest,
            protected_cases=protected_cases,
        )
        validate_protected_access_evidence(
            access_evidence,
            store=store,
            benchmark_manifest=bundle.benchmark_manifest,
            protected_cases=protected_cases,
        )
        for case in protected_cases:
            for artifact_kind in ("PAYLOAD", "ANSWER"):
                denied_access = tuple(
                    preflight_protected_store_access(
                        ProtectedStoreAccessRequest(
                            principal,
                            case.case_id,
                            artifact_kind,
                            "FINAL_V1_FREEZE_POLICY_CHECK",
                        ),
                        case=case,
                        benchmark_manifest=bundle.benchmark_manifest,
                        store=store,
                        access_evidence=access_evidence,
                    )
                    for principal in (
                        Principal.TRAINING,
                        Principal.DATA_PIPELINE,
                        Principal.MODEL_DEVELOPMENT,
                    )
                )
                evaluation_access = preflight_protected_store_access(
                    ProtectedStoreAccessRequest(
                        Principal.EVALUATION_SERVICE,
                        case.case_id,
                        artifact_kind,
                        "FINAL_V1_FREEZE_POLICY_CHECK",
                    ),
                    case=case,
                    benchmark_manifest=bundle.benchmark_manifest,
                    store=store,
                    access_evidence=access_evidence,
                )
                if (
                    any(item.status is not PreflightStatus.BLOCKED for item in denied_access)
                    or evaluation_access.status is not PreflightStatus.PASS
                ):
                    raise ValueError(f"FINAL V1 freeze {split} access policy is not enforced")
        access_evidence_by_split[split] = access_evidence

    split_counts = tuple(
        (split, sum(case.split.split_name is split for case in cases)) for split in SPLIT_ORDER
    )
    return FinalV1FreezeValidation(
        benchmark_manifest_hash=bundle.benchmark_manifest.benchmark_manifest_hash,
        split_counts=split_counts,
        case_count=len(cases),
        contamination_audit_count=len(contamination_gate.audits),
        contamination_dispositions=contamination_gate.dispositions,
        contamination_disposition_digest=contamination_gate.disposition_manifest_digest,
        hidden_case_count=len(cases_by_protected_split[SplitName.HIDDEN_FINAL]),
        protected_access_evidence=tuple(
            (split, access_evidence_by_split[split]) for split in protected_splits
        ),
        public_repository_guard=public_repository_guard,
    )


__all__ = ["FinalV1FreezeValidation", "validate_final_v1_freeze"]
