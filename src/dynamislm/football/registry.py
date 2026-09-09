"""Registered RES-61 football-world operation identities."""

from __future__ import annotations

from dynamislm.measurement.identity import RegistryReference, ScientificIdentifier

RES61_REGISTRY_VERSION = "1.0.0"


MATCH_DAY_RELATIVE_LABEL_METHOD = RegistryReference(
    identifier=ScientificIdentifier(
        "dynamislm",
        "registered-operation",
        "match-day-relative-label",
        RES61_REGISTRY_VERSION,
    ),
    display_label="RES-61 calendar-day match-day-relative label",
)

# Explicit alias for callers that use the shorter operation terminology.
RES61_MATCH_DAY_RELATIVE_LABEL = MATCH_DAY_RELATIVE_LABEL_METHOD


__all__ = [
    "MATCH_DAY_RELATIVE_LABEL_METHOD",
    "RES61_MATCH_DAY_RELATIVE_LABEL",
    "RES61_REGISTRY_VERSION",
]
