"""Registered RES-62 longitudinal data and lineage operation identities."""

from __future__ import annotations

from dynamislm.measurement.identity import RegistryReference, ScientificIdentifier

RES62_REGISTRY_VERSION = "1.0.0"
RES62_SOFTWARE_VERSION = "dynamislm-res62-1.0.0"


def _reference(object_type: str, key: str, label: str) -> RegistryReference:
    return RegistryReference(
        identifier=ScientificIdentifier("dynamislm", object_type, key, RES62_REGISTRY_VERSION),
        display_label=label,
    )


LONGITUDINAL_RECORD_METHOD = _reference(
    "registered-operation",
    "longitudinal-athlete-performance-record",
    "RES-62 immutable longitudinal athlete-performance record",
)

MULTI_SOURCE_ANALYSIS_INPUT_METHOD = _reference(
    "registered-operation",
    "multi-source-analysis-input",
    "RES-62 canonical multi-source analysis-input construction",
)

RES62_MULTI_SOURCE_MANIFEST = _reference(
    "registered-operation",
    "res62-multi-source-manifest",
    "RES-62 structural multi-source source manifest",
)

# Readable aliases for callers that use the longer operation terminology.
RES62_MULTI_SOURCE_MANIFEST_OPERATION = RES62_MULTI_SOURCE_MANIFEST
BUILD_LONGITUDINAL_SOURCE_MANIFEST = RES62_MULTI_SOURCE_MANIFEST


__all__ = [
    "BUILD_LONGITUDINAL_SOURCE_MANIFEST",
    "LONGITUDINAL_RECORD_METHOD",
    "MULTI_SOURCE_ANALYSIS_INPUT_METHOD",
    "RES62_MULTI_SOURCE_MANIFEST",
    "RES62_MULTI_SOURCE_MANIFEST_OPERATION",
    "RES62_REGISTRY_VERSION",
    "RES62_SOFTWARE_VERSION",
]
