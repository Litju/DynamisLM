"""Prospective A0.2 V3 scientific-action contract (RES-541).

V3 repairs the V2 contract defects diagnosed in RES541-DR-001 without revising V2:

* every model-visible observation carries an explicit ``id`` (``observation-N`` in request
  order), and actions reference observations only by those ids;
* the model-facing request has no transcript ``schema``/``origin`` constants; untrusted data
  is isolated under one ``untrusted_request`` key;
* ``target_claims`` lists only explicitly requested levels; RES-70 prerequisite expansion is
  computed by trusted code and never counted as model intent;
* the action is a compact closed object with explicit ``NONE`` sentinels. Units, values and
  the objective are not part of the action because trusted code already holds them.

Operation availability is derived mechanically from the canonical RES-70 capability registry
and the registered-operation inventory, never restated by hand.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dynamislm.analysis import (
    CANONICAL_ANALYSIS_CAPABILITY_REGISTRY,
    AnalysisCapabilityDisposition,
    AnalysisClass,
)
from dynamislm.claims.registry import RES70_CLAIM_POLICIES, ClaimAxis
from dynamislm.qualification import build_registered_operation_inventory

ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = ROOT / "experiments/a02/development-profile-v3.json"
ACTION_PROMPT_PATH = ROOT / "experiments/a02/system-action-development-v3.txt"
TOOL_SCHEMA_PATH = ROOT / "experiments/a02/submit-scientific-action-tool-v3.json"
TOOL_NAME = "submit_scientific_action_v3"
NONE = "NONE"
ACTION_TEMPLATE_DATE = datetime(2026, 11, 9, tzinfo=UTC)
MAX_ACTION_BYTES = 2048
MAX_OBSERVATIONS = 16
OPEN = "<tool_call>"
CLOSE = "</tool_call>"
REQUEST_KEY = "untrusted_request"
_ID = re.compile(r"observation-([1-9][0-9]*)\Z")

# Model-visible registered operations: the same four as V2, so distractors are retained.
EXPOSED_OPERATIONS = (
    "dynamislm:registered-operation:duration-normalized-distance@1.0.0",
    "dynamislm:registered-operation:longitudinal-absolute-change-v1@1.0.0",
    "dynamislm:registered-operation:longitudinal-within-athlete-sample-sd-v1@1.0.0",
    "dynamislm:registered-operation:unit-normalization@1.0.0",
)
ANALYSIS_CLASSES = tuple(item.value for item in AnalysisClass)

# Support-shape tokens whose arity can be checked from observation count alone. Any other
# token makes the operation unavailable to a V3 action (fail closed).
_ARITY = {"exactly-two-scalar-entries": 2}

MEASUREMENT_LEVELS = tuple(
    policy.level.value
    for policy in sorted(RES70_CLAIM_POLICIES, key=lambda p: p.ordinal)
    if policy.axis is ClaimAxis.MEASUREMENT_CHANGE
)
RELATIONSHIP_LEVELS = tuple(
    policy.level.value
    for policy in sorted(RES70_CLAIM_POLICIES, key=lambda p: p.ordinal)
    if policy.axis is not ClaimAxis.MEASUREMENT_CHANGE
)
CLAIM_AXES = {"measurement": MEASUREMENT_LEVELS, "relationship": RELATIONSHIP_LEVELS}
ACTION_FIELDS = ("analysis_class", "operation", "observation_ids", "target_claims")

# Top-level keys that would let untrusted data masquerade as action or transcript structure.
_FORBIDDEN_REQUEST_KEYS = {"schema", "origin", "payload", "name", "arguments", *ACTION_FIELDS}
_QUOTED_TEXT_FIELD = "user_provided_quoted_text"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(
        value, allow_nan=False, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def strict_json(text: str) -> Any:
    def reject_constant(_: str) -> None:
        raise ValueError("nonfinite JSON number")

    try:
        return json.loads(text, object_pairs_hook=_unique_pairs, parse_constant=reject_constant)
    except (ValueError, RecursionError) as exc:
        raise ValueError("invalid JSON") from exc


def json_object(text: str) -> dict[str, Any]:
    value = strict_json(text)
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


# --------------------------------------------------------------------------- authority


def operation_for(analysis_class: str, observation_count: int) -> str:
    """Registered model-visible operation for an analysis class and support size, else NONE."""
    if analysis_class == NONE:
        return NONE
    capability = CANONICAL_ANALYSIS_CAPABILITY_REGISTRY.resolve(AnalysisClass(analysis_class))
    if (
        capability is None
        or capability.disposition is not AnalysisCapabilityDisposition.IMPLEMENTED
        or capability.registered_operation_reference is None
    ):
        return NONE
    operation = capability.registered_operation_reference.stable_id
    shape = capability.required_support_shape
    if operation not in EXPOSED_OPERATIONS or not shape or any(t not in _ARITY for t in shape):
        return NONE
    if any(_ARITY[token] != observation_count for token in shape):
        return NONE
    return operation


def operation_descriptions() -> dict[str, str]:
    """Describe each exposed operation from the inventory and capability registry."""
    inventory = {entry.operation_id: entry for entry in build_registered_operation_inventory()}
    descriptions = {}
    for operation in EXPOSED_OPERATIONS:
        entry = inventory[operation]
        implements = []
        for analysis in AnalysisClass:
            capability = CANONICAL_ANALYSIS_CAPABILITY_REGISTRY.resolve(analysis)
            if (
                capability is not None
                and capability.disposition is AnalysisCapabilityDisposition.IMPLEMENTED
                and capability.registered_operation_reference is not None
                and capability.registered_operation_reference.stable_id == operation
            ):
                counts = sorted(
                    {_ARITY[t] for t in capability.required_support_shape if t in _ARITY}
                )
                implements.append(
                    f"{analysis.value} with exactly {counts[0]} observations"
                    if len(counts) == 1
                    else analysis.value
                )
        descriptions[operation] = (
            f"{entry.label}. Implements "
            + (", ".join(implements) if implements else "no listed analysis_class")
            + "."
        )
    return descriptions


def prerequisite_expansion(axis: str, targets: list[str]) -> list[str]:
    """RES-70 lower-level prerequisites implied by target levels (trusted-side only)."""
    policies = {
        policy.level.value: policy
        for policy in RES70_CLAIM_POLICIES
        if (policy.axis is ClaimAxis.MEASUREMENT_CHANGE) == (axis == "measurement")
    }
    expanded: set[str] = set()
    for level in targets:
        current = policies[level]
        while current.required_lower_level is not None:
            lower = current.required_lower_level.value
            expanded.add(lower)
            current = policies[lower]
    order = CLAIM_AXES[axis]
    return [level for level in order if level in expanded and level not in targets]


# --------------------------------------------------------------------------- tool schema


def build_tool_schema() -> dict[str, Any]:
    descriptions = operation_descriptions()
    return {
        "name": TOOL_NAME,
        "description": (
            "Submit one closed scientific-action proposal for trusted Python authorization. "
            "This tool does not authorize or calculate."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "analysis_class": {
                    "type": "string",
                    "enum": [*ANALYSIS_CLASSES, NONE],
                    "description": "The analysis the user requests, or NONE if no single "
                    "listed analysis class fits the objective.",
                },
                "operation": {
                    "type": "string",
                    "enum": [*EXPOSED_OPERATIONS, NONE],
                    "description": "The registered operation that implements analysis_class "
                    "for the number of referenced observations, or NONE. "
                    + " ".join(f"{op}: {text}" for op, text in descriptions.items()),
                },
                "observation_ids": {
                    "type": "array",
                    "uniqueItems": True,
                    "maxItems": MAX_OBSERVATIONS,
                    "items": {"type": "string", "pattern": "^observation-[1-9][0-9]*$"},
                    "description": "Ids of the request observations the analysis uses.",
                },
                "target_claims": {
                    "type": "object",
                    "properties": {
                        axis: {
                            "type": "array",
                            "uniqueItems": True,
                            "items": {"type": "string", "enum": list(levels)},
                        }
                        for axis, levels in CLAIM_AXES.items()
                    },
                    "required": list(CLAIM_AXES),
                    "additionalProperties": False,
                    "description": "Only the claim levels the user explicitly requests. "
                    "Do not add lower levels a requested level presupposes.",
                },
            },
            "required": list(ACTION_FIELDS),
            "additionalProperties": False,
        },
    }


def tool_schema() -> dict[str, Any]:
    value = json_object(TOOL_SCHEMA_PATH.read_text(encoding="utf-8"))
    if value != build_tool_schema():
        raise ValueError("A0.2 V3 tool schema differs from its registry derivation")
    return value


def load_profile() -> dict[str, Any]:
    profile = json_object(PROFILE_PATH.read_text(encoding="utf-8"))
    if profile.get("schema") != "RES541_A02_DEVELOPMENT_PROFILE_V3":
        raise ValueError("A0.2 V3 profile schema differs")
    for key, path in profile["inputs"].items():
        if key.endswith("_sha256"):
            continue
        if sha256((ROOT / path).read_bytes()) != profile["inputs"][f"{key}_sha256"]:
            raise ValueError(f"A0.2 V3 profile input hash differs: {key}")
    return profile


# --------------------------------------------------------------------------- request


def visible_request(request: dict[str, Any]) -> dict[str, Any]:
    """Model-visible request with bijective observation ids; values remain data."""
    if not isinstance(request, dict) or not isinstance(request.get("observations"), list):
        raise ValueError("V3 request must contain an observation list")
    forbidden = _FORBIDDEN_REQUEST_KEYS & set(request)
    if forbidden:
        raise ValueError(f"V3 request contains reserved keys: {sorted(forbidden)}")
    observations = request["observations"]
    if len(observations) > MAX_OBSERVATIONS:
        raise ValueError("V3 request has too many observations")
    visible = copy.deepcopy(request)
    rows = []
    for index, row in enumerate(observations, start=1):
        if not isinstance(row, dict) or "id" in row:
            raise ValueError("V3 observations must be objects without a preassigned id")
        rows.append({"id": f"observation-{index}", **copy.deepcopy(row)})
    visible["observations"] = rows
    text = canonical({REQUEST_KEY: visible})
    if TOOL_NAME in text or OPEN in text or CLOSE in text:
        raise ValueError("V3 untrusted request contains action framing")
    return visible


def observation_ids(request: dict[str, Any]) -> list[str]:
    return [row["id"] for row in visible_request(request)["observations"]]


def user_message(request: dict[str, Any]) -> str:
    return canonical({REQUEST_KEY: visible_request(request)})


def build_action_messages(request: dict[str, Any]) -> list[dict[str, str]]:
    system = ACTION_PROMPT_PATH.read_text(encoding="utf-8").rstrip("\n")
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_message(request)},
    ]


def build_action_prompt(tokenizer: Any, request: dict[str, Any]) -> dict[str, Any]:
    messages = build_action_messages(request)
    kwargs = {
        "enable_thinking": False,
        "strftime_now": ACTION_TEMPLATE_DATE.strftime,
        "xml_tools": [tool_schema()],
    }
    token_ids = tokenizer.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=True, **kwargs
    )
    rendered = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True, **kwargs
    )
    if tokenizer.encode(rendered, add_special_tokens=False) != token_ids:
        raise ValueError("V3 prompt does not reproduce tokenizer ids")
    if "RES403-MODEL-TRANSCRIPT-1" in rendered.split(_QUOTED_TEXT_FIELD)[0]:
        raise ValueError("V3 prompt exposes a transcript schema outside quoted user text")
    return {
        "messages": messages,
        "rendered_prompt": rendered,
        "rendered_prompt_sha256": sha256(rendered.encode()),
        "prompt_token_ids": token_ids,
        "prompt_tokens": len(token_ids),
    }


# --------------------------------------------------------------------------- action


def format_action(action: dict[str, Any]) -> str:
    return f"{OPEN}{canonical({'name': TOOL_NAME, 'arguments': action})}{CLOSE}"


def normalize_action(action: dict[str, Any]) -> dict[str, Any]:
    """Canonical order for set-valued fields; used for comparison only."""
    ids = sorted(action["observation_ids"], key=lambda ref: int(ref.split("-")[1]))
    claims = {
        axis: [level for level in levels if level in action["target_claims"][axis]]
        for axis, levels in CLAIM_AXES.items()
    }
    return {**action, "observation_ids": ids, "target_claims": claims}


def validate_arguments(action: object, visible_ids: list[str]) -> dict[str, Any]:
    if not isinstance(action, dict) or set(action) != set(ACTION_FIELDS):
        raise ValueError("V3 action fields differ")
    if action["analysis_class"] not in (*ANALYSIS_CLASSES, NONE):
        raise ValueError("V3 analysis_class is not in the closed enumeration")
    if action["operation"] not in (*EXPOSED_OPERATIONS, NONE):
        raise ValueError("V3 operation is not in the closed enumeration")
    refs = action["observation_ids"]
    if (
        not isinstance(refs, list)
        or len(refs) > MAX_OBSERVATIONS
        or any(not isinstance(ref, str) or not _ID.fullmatch(ref) for ref in refs)
        or len(set(refs)) != len(refs)
    ):
        raise ValueError("V3 observation_ids are invalid")
    if any(ref not in visible_ids for ref in refs):
        raise ValueError("V3 observation_ids reference an id absent from the request")
    claims = action["target_claims"]
    if not isinstance(claims, dict) or set(claims) != set(CLAIM_AXES):
        raise ValueError("V3 target_claims axes differ")
    for axis, levels in CLAIM_AXES.items():
        values = claims[axis]
        if (
            not isinstance(values, list)
            or any(not isinstance(v, str) or v not in levels for v in values)
            or len(set(values)) != len(values)
        ):
            raise ValueError(f"V3 target_claims.{axis} is invalid")
    return action


def parse_action(content: object, visible_ids: list[str]) -> dict[str, Any]:
    """Strict native parse: exactly one framed tool call and nothing else."""
    if not isinstance(content, str):
        raise ValueError("V3 action must be text")
    size = len(content.encode("utf-8", errors="strict"))
    if not 0 < size <= MAX_ACTION_BYTES or not (
        content.startswith(OPEN) and content.endswith(CLOSE)
    ):
        raise ValueError("V3 action must be exactly one framed tool call")
    envelope = strict_json(content[len(OPEN) : -len(CLOSE)])
    if not isinstance(envelope, dict) or set(envelope) != {"name", "arguments"}:
        raise ValueError("V3 tool-call envelope differs")
    if envelope["name"] != TOOL_NAME:
        raise ValueError("V3 tool name differs")
    return validate_arguments(envelope["arguments"], visible_ids)
