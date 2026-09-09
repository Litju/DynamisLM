"""Registered RES-60 population and source qualification identities."""

from __future__ import annotations

from dynamislm.measurement.identity import RegistryReference, ScientificIdentifier

RES60_REGISTRY_VERSION = "1.0.0"


def _reference(object_type: str, key: str, label: str) -> RegistryReference:
    return RegistryReference(
        identifier=ScientificIdentifier("dynamislm", object_type, key, RES60_REGISTRY_VERSION),
        display_label=label,
    )


CANONICAL_POPULATION_QUALIFICATION_METHOD = _reference(
    "registered-operation",
    "canonical-football-population-qualification",
    "RES-60 canonical football population qualification",
)

CANONICAL_SOURCE_QUALIFICATION_METHOD = _reference(
    "registered-operation",
    "canonical-empirical-source-qualification",
    "RES-60 canonical empirical source qualification",
)

# Explicit names for callers that prefer the RES-60 operation terminology.
RES60_CANONICAL_POPULATION_QUALIFICATION = CANONICAL_POPULATION_QUALIFICATION_METHOD
RES60_CANONICAL_SOURCE_QUALIFICATION = CANONICAL_SOURCE_QUALIFICATION_METHOD
