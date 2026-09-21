"""RES-71 deterministic scientific-engine qualification contracts."""

from dynamislm.qualification.contracts import (
    CoverageRow,
    CoverageStatus,
    GateComponentStatus,
    OperationDisposition,
    ReferenceCase,
    ReferenceCaseStatus,
    ReferenceValue,
    RegisteredOperationInventoryEntry,
    UnresolvedComputation,
)
from dynamislm.qualification.gate import (
    RES71_GATE_RECEIPT_PATH,
    RES71_QUALIFIED_CONTENT_HEAD,
    build_gate_runtime_evidence,
    validate_gate_receipt,
)
from dynamislm.qualification.inventory import (
    RES71_REGISTRY_VERSION,
    build_coverage_matrix,
    build_registered_operation_inventory,
    build_unresolved_computation_inventory,
    discovered_registered_operation_ids,
    validate_coverage_matrix,
    validate_registered_operation_inventory,
    validate_unresolved_computation_inventory,
)
from dynamislm.qualification.references import (
    RES71_REFERENCE_INTERFACE_VERSION,
    RES71_SEALED_REFERENCE_DIGEST,
    get_reference_case,
    get_reference_cases,
    reference_case_digest,
    reference_case_manifest,
    validate_reference_cases,
)

__all__ = [
    "RES71_GATE_RECEIPT_PATH",
    "RES71_QUALIFIED_CONTENT_HEAD",
    "RES71_REFERENCE_INTERFACE_VERSION",
    "RES71_REGISTRY_VERSION",
    "RES71_SEALED_REFERENCE_DIGEST",
    "CoverageRow",
    "CoverageStatus",
    "GateComponentStatus",
    "OperationDisposition",
    "ReferenceCase",
    "ReferenceCaseStatus",
    "ReferenceValue",
    "RegisteredOperationInventoryEntry",
    "UnresolvedComputation",
    "build_coverage_matrix",
    "build_gate_runtime_evidence",
    "build_registered_operation_inventory",
    "build_unresolved_computation_inventory",
    "discovered_registered_operation_ids",
    "get_reference_case",
    "get_reference_cases",
    "reference_case_digest",
    "reference_case_manifest",
    "validate_coverage_matrix",
    "validate_gate_receipt",
    "validate_reference_cases",
    "validate_registered_operation_inventory",
    "validate_unresolved_computation_inventory",
]
