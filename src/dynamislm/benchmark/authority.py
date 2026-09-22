"""Authority and RES-71 bindings used by PerformanceScience-Eval V1."""

from __future__ import annotations

from dynamislm.analysis import (
    CANONICAL_ANALYSIS_CAPABILITY_REGISTRY,
    RES70_ANALYSIS_REGISTRY_VERSION,
)
from dynamislm.benchmark.constants import SERIALIZATION_V3, AuthorityKind
from dynamislm.benchmark.contracts import (
    AuthorityBinding,
    RES71OperationBinding,
    RES71RefusalBinding,
    RES71RuntimeBinding,
)
from dynamislm.claims import CANONICAL_CLAIM_POLICY_REGISTRY, RES70_CLAIM_REGISTRY_VERSION
from dynamislm.comparability import RES70_REGISTRY_VERSION, canonical_registry_hash
from dynamislm.qualification import (
    RES71_QUALIFIED_CONTENT_HEAD,
    RES71_REFERENCE_INTERFACE_VERSION,
    RES71_SEALED_REFERENCE_DIGEST,
    build_registered_operation_inventory,
    build_unresolved_computation_inventory,
    get_reference_case,
    validate_gate_receipt,
    validate_reference_cases,
)
from dynamislm.qualification.contracts import (
    RegisteredOperationInventoryEntry,
)
from dynamislm.serialization import canonical_hash

RES71_REFERENCE_INTERFACE_ID = "res71-reference-interface"
RES71_REFERENCE_INTERFACE_BINDING = (
    f"{RES71_REFERENCE_INTERFACE_ID}@{RES71_REFERENCE_INTERFACE_VERSION}"
)


def build_res71_runtime_binding() -> RES71RuntimeBinding:
    """Recompute the exact runtime binding; no caller values are accepted."""

    validate_reference_cases()
    if validate_gate_receipt().value != "PASS":
        raise ValueError("RES-71 gate receipt did not validate")
    return RES71RuntimeBinding(
        interface_id=RES71_REFERENCE_INTERFACE_ID,
        interface_version=RES71_REFERENCE_INTERFACE_VERSION,
        interface_binding=RES71_REFERENCE_INTERFACE_BINDING,
        sealed_reference_digest=RES71_SEALED_REFERENCE_DIGEST,
        serialization_version=SERIALIZATION_V3,
        qualified_content_head=RES71_QUALIFIED_CONTENT_HEAD,
        gate_receipt="docs/qualification/RES71-GATE-RECEIPT.json",
        gate_runtime_validator="dynamislm.qualification.gate:validate_gate_receipt",
        gate_validation="PASS",
    )


def validate_res71_runtime_binding(binding: RES71RuntimeBinding) -> None:
    expected = build_res71_runtime_binding()
    if binding != expected:
        raise ValueError("RES-71 runtime binding is stale, forged, or invalid")


def _operation_inventory_digest() -> str:
    entries = build_registered_operation_inventory()
    return canonical_hash(entries)


def _unresolved_inventory_digest() -> str:
    return canonical_hash(build_unresolved_computation_inventory())


def _reference_snapshot(reference: object) -> dict[str, object]:
    """Return the complete live identity for a registry reference."""

    return {"reference": reference}


def _live_authority_snapshot(
    kind: AuthorityKind,
) -> tuple[str, tuple[str, ...], str]:
    """Resolve RES-60/62/69 authority from the live registries.

    These snapshots hash the registry contents as well as the version. A
    benchmark binding therefore cannot be made valid by copying the RES-71
    operation-inventory digest into an unrelated authority slot.
    """

    if kind is AuthorityKind.RES60_POPULATION:
        from dynamislm.population import (
            CANONICAL_POPULATION_DIMENSIONS,
            CANONICAL_POPULATION_QUALIFICATION_METHOD,
            CANONICAL_SOURCE_QUALIFICATION_METHOD,
            CANONICAL_SOURCE_REQUIREMENTS,
            RES60_REGISTRY_VERSION,
        )

        references = tuple(
            sorted(
                (
                    CANONICAL_POPULATION_QUALIFICATION_METHOD,
                    CANONICAL_SOURCE_QUALIFICATION_METHOD,
                ),
                key=lambda item: item.stable_id.encode("utf-8"),
            )
        )
        population_payload: dict[str, object] = {
            "authority_kind": kind.value,
            "registry_version": RES60_REGISTRY_VERSION,
            "references": tuple(_reference_snapshot(item) for item in references),
            "canonical_population_dimensions": CANONICAL_POPULATION_DIMENSIONS,
            "canonical_source_requirements": CANONICAL_SOURCE_REQUIREMENTS,
        }
        return (
            RES60_REGISTRY_VERSION,
            tuple(item.stable_id for item in references),
            canonical_hash(population_payload),
        )
    if kind is AuthorityKind.RES62_PROVENANCE:
        from dynamislm.longitudinal import (
            LONGITUDINAL_RECORD_METHOD,
            MULTI_SOURCE_ANALYSIS_INPUT_METHOD,
            RES62_MULTI_SOURCE_MANIFEST,
            RES62_REGISTRY_VERSION,
            RES62_SOFTWARE_VERSION,
        )

        references = tuple(
            sorted(
                (
                    LONGITUDINAL_RECORD_METHOD,
                    MULTI_SOURCE_ANALYSIS_INPUT_METHOD,
                    RES62_MULTI_SOURCE_MANIFEST,
                ),
                key=lambda item: item.stable_id.encode("utf-8"),
            )
        )
        provenance_payload: dict[str, object] = {
            "authority_kind": kind.value,
            "registry_version": RES62_REGISTRY_VERSION,
            "software_version": RES62_SOFTWARE_VERSION,
            "references": tuple(_reference_snapshot(item) for item in references),
        }
        return (
            RES62_REGISTRY_VERSION,
            tuple(item.stable_id for item in references),
            canonical_hash(provenance_payload),
        )
    if kind is AuthorityKind.RES69_STATISTICS:
        from dynamislm.longitudinal.statistics import registry as res69_registry
        from dynamislm.measurement.identity import RegistryReference

        references = tuple(
            sorted(
                {
                    value
                    for name in res69_registry.__all__
                    if isinstance(value := getattr(res69_registry, name), RegistryReference)
                },
                key=lambda item: item.stable_id.encode("utf-8"),
            )
        )
        statistics_payload: dict[str, object] = {
            "authority_kind": kind.value,
            "registry_version": res69_registry.RES69_REGISTRY_VERSION,
            "software_version": res69_registry.RES69_SOFTWARE_VERSION,
            "references": tuple(_reference_snapshot(item) for item in references),
            "operation_registry": res69_registry.RES69_OPERATION_REGISTRY,
            "scale_registry": res69_registry.RES69_SCALE_REGISTRY,
            "reliability_assumption_registry": (
                res69_registry.RES69_RELIABILITY_ASSUMPTION_DECLARATION_REGISTRY
            ),
            "registered_scale_keys": res69_registry.REGISTERED_SCALE_KEYS,
            "unregistered_scale_keys": res69_registry.UNREGISTERED_SCALE_KEYS,
            "scale_registry_audit": res69_registry.SCALE_REGISTRY_AUDIT,
        }
        return (
            res69_registry.RES69_REGISTRY_VERSION,
            tuple(item.stable_id for item in references),
            canonical_hash(statistics_payload),
        )
    raise ValueError(f"{kind.value} is not a live RES-60/62/69 authority")


def _operation_entry(operation_id: str) -> RegisteredOperationInventoryEntry:
    matches = tuple(
        item for item in build_registered_operation_inventory() if item.operation_id == operation_id
    )
    if len(matches) != 1:
        raise ValueError(f"operation is not a live RES-71 registered identity: {operation_id}")
    return matches[0]


def bind_res71_operation(
    operation_id: str,
    *,
    reference_case_id: str | None = None,
    runtime_binding: RES71RuntimeBinding | None = None,
) -> RES71OperationBinding:
    """Resolve one live operation and optionally one exact reference case."""

    runtime = build_res71_runtime_binding()
    if runtime_binding is not None:
        validate_res71_runtime_binding(runtime_binding)
        runtime = runtime_binding
    entry = _operation_entry(operation_id)
    reference_digest: str | None = None
    if reference_case_id is not None:
        reference = get_reference_case(reference_case_id)
        if reference.operation_id != operation_id:
            raise ValueError("reference case does not bind the requested operation")
        reference_digest = canonical_hash(reference)
    return RES71OperationBinding(
        operation_id=entry.operation_id,
        method_version=entry.method_version,
        scientific_family=entry.scientific_family,
        disposition=entry.disposition.value,
        operation_inventory_digest=_operation_inventory_digest(),
        input_contract=entry.input_contract,
        output_contract=entry.output_contract,
        provenance_contract=entry.provenance_contract,
        refusal_path=entry.refusal_path,
        tolerance_contract=entry.tolerance_contract,
        authority_references=entry.authority_references,
        runtime_binding=runtime,
        reference_case_id=reference_case_id,
        reference_case_digest=reference_digest,
    )


def validate_res71_operation_binding(binding: RES71OperationBinding) -> None:
    if not isinstance(binding, RES71OperationBinding):
        raise TypeError("binding must be RES71OperationBinding")
    expected = bind_res71_operation(
        binding.operation_id,
        reference_case_id=binding.reference_case_id,
        runtime_binding=binding.runtime_binding,
    )
    if binding != expected:
        raise ValueError(
            "RES-71 operation binding does not match live inventory/reference authority"
        )


def bind_res71_refusal(
    capability: str,
    *,
    runtime_binding: RES71RuntimeBinding | None = None,
) -> RES71RefusalBinding:
    """Resolve one canonical unresolved-computation row and its refusal route."""

    runtime = build_res71_runtime_binding()
    if runtime_binding is not None:
        validate_res71_runtime_binding(runtime_binding)
        runtime = runtime_binding
    rows = tuple(
        item for item in build_unresolved_computation_inventory() if item.capability == capability
    )
    if len(rows) != 1:
        raise ValueError(f"capability is not a live RES-71 unresolved identity: {capability}")
    row = rows[0]
    return RES71RefusalBinding(
        capability=row.capability,
        registered_operation_id=row.registered_operation_id,
        disposition=row.disposition.value,
        expected_refusal_class=row.expected_refusal_class,
        expected_reason_codes=row.expected_reason_codes,
        safe_description=row.safe_description,
        unresolved_inventory_digest=_unresolved_inventory_digest(),
        refusal_path=row.refusal_path,
        authority_references=row.authority_references,
        runtime_binding=runtime,
    )


def validate_res71_refusal_binding(binding: RES71RefusalBinding) -> None:
    if not isinstance(binding, RES71RefusalBinding):
        raise TypeError("binding must be RES71RefusalBinding")
    expected = bind_res71_refusal(binding.capability, runtime_binding=binding.runtime_binding)
    if binding != expected:
        raise ValueError("RES-71 refusal binding does not match live unresolved authority")


def _canonical_registry_digest(kind: AuthorityKind) -> tuple[str, str, tuple[str, ...]]:
    if kind is AuthorityKind.RES70_CLAIM:
        return (
            RES70_CLAIM_REGISTRY_VERSION,
            CANONICAL_CLAIM_POLICY_REGISTRY.canonical_hash,
            ("res70-claim-policy-registry", "RES-70-CLAIM-AUTHORITY"),
        )
    if kind is AuthorityKind.RES70_ANALYSIS:
        return (
            RES70_ANALYSIS_REGISTRY_VERSION,
            CANONICAL_ANALYSIS_CAPABILITY_REGISTRY.canonical_hash,
            ("res70-analysis-capability-registry", "RES-70-ANALYSIS-AUTHORITY"),
        )
    if kind is AuthorityKind.RES70_COMPARABILITY:
        return (
            RES70_REGISTRY_VERSION,
            canonical_registry_hash(),
            ("res70-comparability-registry", "RES-70-COMPARABILITY-AUTHORITY"),
        )
    if kind is AuthorityKind.RES71_RUNTIME:
        return (
            RES71_REFERENCE_INTERFACE_VERSION,
            RES71_SEALED_REFERENCE_DIGEST,
            (RES71_REFERENCE_INTERFACE_ID, RES71_REFERENCE_INTERFACE_BINDING),
        )
    if kind in {
        AuthorityKind.RES60_POPULATION,
        AuthorityKind.RES62_PROVENANCE,
        AuthorityKind.RES69_STATISTICS,
    }:
        version, references, digest = _live_authority_snapshot(kind)
        return (version, digest, references)
    raise ValueError(f"{kind.value} is not a single canonical registry authority")


def make_authority_binding(
    authority_kind: AuthorityKind | str,
    *,
    governed_field_ids: tuple[str, ...],
    source_reference_id: str | None = None,
) -> AuthorityBinding:
    """Build only a binding whose digest is obtained from a live authority."""

    kind = AuthorityKind(authority_kind)
    if kind is AuthorityKind.RES71_RUNTIME:
        version, digest, references = _canonical_registry_digest(kind)
        source = source_reference_id or references[0]
        if source not in references:
            raise ValueError("caller cannot choose an unregistered RES-71 runtime reference")
        return AuthorityBinding(kind.value, source, version, digest, governed_field_ids)
    if kind in {
        AuthorityKind.RES70_CLAIM,
        AuthorityKind.RES70_ANALYSIS,
        AuthorityKind.RES70_COMPARABILITY,
        AuthorityKind.RES60_POPULATION,
        AuthorityKind.RES62_PROVENANCE,
        AuthorityKind.RES69_STATISTICS,
    }:
        version, digest, references = _canonical_registry_digest(kind)
        source = source_reference_id or references[0]
        if source not in references:
            raise ValueError("caller cannot choose an unregistered canonical authority reference")
        return AuthorityBinding(kind.value, source, version, digest, governed_field_ids)
    raise ValueError("make_authority_binding only constructs canonical registry bindings")


def validate_authority_binding(binding: AuthorityBinding) -> None:
    """Reject unknown authority kinds and caller-minted RES-71/RES-70 values."""

    if not isinstance(binding, AuthorityBinding):
        raise TypeError("authority binding must be AuthorityBinding")
    try:
        kind = AuthorityKind(binding.authority_kind)
    except ValueError as exc:
        raise ValueError(f"unknown authority kind: {binding.authority_kind}") from exc
    if kind in {
        AuthorityKind.RES71_RUNTIME,
        AuthorityKind.RES70_CLAIM,
        AuthorityKind.RES70_ANALYSIS,
        AuthorityKind.RES70_COMPARABILITY,
        AuthorityKind.RES60_POPULATION,
        AuthorityKind.RES62_PROVENANCE,
        AuthorityKind.RES69_STATISTICS,
    }:
        version, digest, references = _canonical_registry_digest(kind)
        if binding.version != version or binding.digest != digest:
            raise ValueError("authority binding digest/version is not canonical")
        if binding.source_reference_id not in references:
            raise ValueError("authority binding reference is not canonical")
    elif kind is AuthorityKind.RES71_OPERATION:
        entry = _operation_entry(binding.source_reference_id)
        if (
            binding.version != entry.method_version
            or binding.digest != _operation_inventory_digest()
        ):
            raise ValueError("RES-71 operation authority binding is stale or caller-minted")
    elif kind is AuthorityKind.RES71_REFERENCE_CASE:
        reference = get_reference_case(binding.source_reference_id)
        if binding.version != reference.case_version or binding.digest != canonical_hash(reference):
            raise ValueError("RES-71 reference-case authority binding is stale or caller-minted")
    elif kind is AuthorityKind.RES71_UNRESOLVED:
        rows = tuple(
            item
            for item in build_unresolved_computation_inventory()
            if item.capability == binding.source_reference_id
        )
        if (
            len(rows) != 1
            or binding.version != "1.0.0"
            or binding.digest != _unresolved_inventory_digest()
        ):
            raise ValueError("RES-71 unresolved authority binding is stale or caller-minted")
    elif kind in {
        AuthorityKind.SOURCE_DOCUMENT,
        AuthorityKind.SOURCE_EVIDENCE_SPAN,
        AuthorityKind.EXPERT_RUBRIC,
        AuthorityKind.GENERATOR,
        AuthorityKind.MUTATION_PARENT,
    }:
        # These are case-local authorities, but their content digest remains mandatory.
        _ = binding.digest
    else:  # pragma: no cover - exhaustive guard for future enum additions
        raise ValueError("unsupported authority kind")


def validate_authority_bindings(bindings: tuple[AuthorityBinding, ...]) -> None:
    if not bindings:
        raise ValueError("at least one authority binding is required")
    for binding in bindings:
        validate_authority_binding(binding)


__all__ = [
    "RES71_REFERENCE_INTERFACE_BINDING",
    "RES71_REFERENCE_INTERFACE_ID",
    "bind_res71_operation",
    "bind_res71_refusal",
    "build_res71_runtime_binding",
    "make_authority_binding",
    "validate_authority_binding",
    "validate_authority_bindings",
    "validate_res71_operation_binding",
    "validate_res71_refusal_binding",
    "validate_res71_runtime_binding",
]
