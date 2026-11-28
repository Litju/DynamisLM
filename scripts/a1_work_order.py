"""The transported A1 inference work order and its remote verification (RES-832).

This module is the transport boundary. It carries no case cohort, no gold and no adjudication
metadata, and it imports nothing that does: verification is a pure recomputation over the
transported bytes using the canonical V3 digest functions. That is what lets the remote T4 prove
it is executing the sealed prompts without being able to read the authored evaluation material.

``a1_payload`` builds the work order locally and imports this module; the worker imports only this
module. The split is deliberate: a remote archive that contains ``a1_cases`` or the case manifest
would expose evaluation inputs, and a boundary that can drift is not a boundary.
"""

from __future__ import annotations

import hashlib
from typing import Any

from scripts import a02_v3_contract as v3

WORK_ORDER_SCHEMA = "DYNAMISLM_A1_INFERENCE_WORK_ORDER_V1"
SMOKE_SCHEMA = "DYNAMISLM_A1_SMOKE_INPUT_V1"
# Keys that would leak evaluation material into the transported payload.
FORBIDDEN_KEYS = frozenset(
    {
        "gold",
        "acceptable_actions",
        "acceptable",
        "intent",
        "stratum",
        "family",
        "labels",
        "subset_selection",
        "novel_phrasing",
        "contrast",
        "stated_measurement",
        "cluster_gold",
        "judgment",
        "preferred_action",
        "control",
    }
)


class PayloadError(ValueError):
    pass


def canonical_digest(value: Any) -> str:
    return v3.sha256(v3.canonical(value).encode())


def screen(value: Any, path: str) -> None:
    """Refuse a payload that would expose any evaluation key, at any depth."""
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_KEYS:
                raise PayloadError(f"payload would expose {path}.{key}")
            screen(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            screen(child, f"{path}[{index}]")


def verify(value: dict[str, Any]) -> dict[str, Any]:
    """Recompute every transported digest. Fails closed on any drift or exposure."""
    if value.get("schema") != WORK_ORDER_SCHEMA:
        raise PayloadError("A1 work order schema differs")
    screen(value, "work_order")
    conditions = value.get("conditions")
    if not isinstance(conditions, list) or len(conditions) != value.get("planned_conditions"):
        raise PayloadError("A1 work order condition inventory differs")
    planned = 0
    for condition in conditions:
        if not isinstance(condition, dict) or not isinstance(condition.get("items"), list):
            raise PayloadError("A1 work order condition shape differs")
        for item in condition["items"]:
            if canonical_digest(item["request"]) != item["request_sha256"]:
                raise PayloadError(f"{condition['arm']}: transported request digest differs")
            if canonical_digest(item["messages"]) != item["prompt_sha256"]:
                raise PayloadError(f"{condition['arm']}: transported prompt digest differs")
            planned += 1
    if planned != value.get("planned_generations"):
        raise PayloadError("A1 work order generation count differs")
    if conditions and value.get("priority") is None:
        raise PayloadError("A1 work order priority order is absent")
    smoke = value.get("smoke") or {}
    if smoke.get("schema") != SMOKE_SCHEMA:
        raise PayloadError("A1 smoke input schema differs")
    if canonical_digest(smoke["request"]) != smoke["request_sha256"]:
        raise PayloadError("A1 smoke request digest differs")
    if canonical_digest(smoke["messages"]) != smoke["prompt_sha256"]:
        raise PayloadError("A1 smoke prompt digest differs")
    if len(smoke.get("conditions") or []) != 4:
        raise PayloadError("A1 smoke conditions differ")
    return value


def digest(path: Any) -> str:
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()
