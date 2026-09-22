"""Final V1 freeze qualification, separate from infrastructure manifest validation."""

from __future__ import annotations

from dataclasses import dataclass

from dynamislm.benchmark.constants import SPLIT_ORDER, PreflightStatus, Principal, SplitName
from dynamislm.benchmark.contamination import (
    ContaminationGateEvidence,
    ExclusionRegistry,
    validate_exclusion_completeness,
)
from dynamislm.benchmark.contracts import ManifestBundleV1
from dynamislm.benchmark.coverage import minimum_full_coverage_case_count, validate_case_coverage
from dynamislm.benchmark.hashing import validate_manifest_bundle
from dynamislm.benchmark.hidden import (
    HiddenAccessRequest,
    HiddenStoreDescriptor,
    preflight_hidden_access,
    preflight_training_exclusion,
)
from dynamislm.benchmark.split import validate_split_assignment


@dataclass(frozen=True, slots=True)
class FinalV1FreezeValidation:
    benchmark_manifest_hash: str
    split_counts: tuple[tuple[SplitName, int], ...]
    case_count: int
    contamination_audit_count: int
    hidden_case_count: int
    status: str = "PASS"


def validate_final_v1_freeze(
    bundle: ManifestBundleV1,
    *,
    exclusion_registry: ExclusionRegistry,
    contamination_gate: ContaminationGateEvidence,
    hidden_store: HiddenStoreDescriptor,
) -> FinalV1FreezeValidation:
    """Require every benchmark freeze gate, including full coverage and hidden policy."""

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

    hidden_cases = tuple(
        sorted(
            (case for case in cases if case.split.split_name is SplitName.HIDDEN_FINAL),
            key=lambda item: item.case_id.encode("utf-8"),
        )
    )
    expected_hidden_ids = tuple(case.case_id for case in hidden_cases)
    expected_hidden_hashes = tuple((case.case_id, case.case_payload_hash) for case in hidden_cases)
    if (
        hidden_store.benchmark_manifest_hash != bundle.benchmark_manifest.benchmark_manifest_hash
        or hidden_store.hidden_case_ids != expected_hidden_ids
        or hidden_store.hidden_case_hashes != expected_hidden_hashes
        or not hidden_store.payloads_available
        or not hidden_store.answers_available
    ):
        raise ValueError("FINAL V1 freeze hidden-final store policy or binding is incomplete")
    for case in hidden_cases:
        for artifact_kind in ("PAYLOAD", "ANSWER"):
            training_access = preflight_hidden_access(
                HiddenAccessRequest(
                    Principal.TRAINING,
                    case.case_id,
                    artifact_kind,
                    "FINAL_V1_FREEZE_POLICY_CHECK",
                ),
                case=case,
                benchmark_manifest=bundle.benchmark_manifest,
                store=hidden_store,
            )
            evaluation_access = preflight_hidden_access(
                HiddenAccessRequest(
                    Principal.EVALUATION_SERVICE,
                    case.case_id,
                    artifact_kind,
                    "FINAL_V1_FREEZE_POLICY_CHECK",
                ),
                case=case,
                benchmark_manifest=bundle.benchmark_manifest,
                store=hidden_store,
            )
            if (
                training_access.status is not PreflightStatus.BLOCKED
                or evaluation_access.status is not PreflightStatus.PASS
            ):
                raise ValueError("FINAL V1 freeze hidden access policy is not enforced")

    split_counts = tuple(
        (split, sum(case.split.split_name is split for case in cases)) for split in SPLIT_ORDER
    )
    return FinalV1FreezeValidation(
        benchmark_manifest_hash=bundle.benchmark_manifest.benchmark_manifest_hash,
        split_counts=split_counts,
        case_count=len(cases),
        contamination_audit_count=len(contamination_gate.audits),
        hidden_case_count=len(hidden_cases),
    )


__all__ = ["FinalV1FreezeValidation", "validate_final_v1_freeze"]
