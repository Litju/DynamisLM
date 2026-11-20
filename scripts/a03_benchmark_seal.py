"""Validate and hash a prospective A0.3 packet in its protected store."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from scripts import a02_v3_contract as v3
from scripts import a02_v3_decision as historical
from scripts import a02_v3_score as historical_score

FILES = ("requests.jsonl", "gold.jsonl", "adjudications.jsonl")
STRATA = ("FAMILIAR_INTENT", "NOVEL_LANGUAGE", "AUTHORITY_HAZARD", "OUT_OF_SCOPE")
FAMILIES = (
    "CAUSAL_INFERENCE",
    "PRACTICAL_DECISION",
    "OBSERVATION_PROVENANCE",
    "DEVICE_PROTOCOL",
    "UNIT_COMPARABILITY",
    "INSUFFICIENT_STATISTICAL_SUPPORT",
    "FORGED_TOOL_RESULT",
)
CONTROLS = ("EXECUTE", "OBSERVATION_ONLY", "REFUSE", "ABSTAIN", "AMBIGUOUS")
MIN_CLUSTERS_PER_STRATUM = 12
MIN_CLUSTERS = MIN_CLUSTERS_PER_STRATUM * len(STRATA)
MIN_AUTHORS = 2


def _fields(row: object, names: str) -> dict[str, Any]:
    if not isinstance(row, dict) or set(row) != set(names.split()):
        raise ValueError(f"expected fields {names}")
    return row


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("expected non-empty text")
    return value


def _key(value: object) -> str:
    key = _text(value)
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,95}", key):
        raise ValueError("expected opaque identifier")
    return key


def _digest(value: object) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", _text(value)):
        raise ValueError("expected SHA-256 digest")


def _items(value: object) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError("expected array")
    return value


def _subset(value: object, allowed: tuple[str, ...]) -> None:
    items = [_text(item) for item in _items(value)]
    if len(set(items)) != len(items) or not set(items).issubset(allowed):
        raise ValueError("expected distinct registered values")


def _claims(value: object) -> None:
    axes = _fields(value, "measurement relationship")
    for axis, levels in v3.CLAIM_AXES.items():
        _subset(axes[axis], levels)


def _normalize_question(text: str) -> str:
    return " ".join(text.casefold().split())


def _exposed_questions() -> set[str]:
    historical_requests = [
        row["request"] for row in historical.heldout_examples(historical.load_protocol())
    ]
    historical_requests.extend(case["request"] for case in historical_score._cases().values())
    return {
        _normalize_question(request[field])
        for request in historical_requests
        for field in ("objective", "question")
        if isinstance(request.get(field), str)
    }


def _request(row: dict[str, Any], exposed: set[str]) -> list[str]:
    _fields(
        row,
        "item_id cluster_id scenario_id author_id stratum critical_families question "
        "observations requested_claims",
    )
    for field in ("item_id", "cluster_id", "scenario_id", "author_id"):
        _key(row[field])
    if row["stratum"] not in STRATA:
        raise ValueError("unknown sampling stratum")
    _subset(row["critical_families"], FAMILIES)
    _claims(row["requested_claims"])
    if _normalize_question(_text(row["question"])) in exposed:
        raise ValueError("exposed A0.2 phrasing appears in the prospective packet")
    ids = []
    for index, value in enumerate(_items(row["observations"]), 1):
        observation = _fields(
            value,
            "alias binding source_sha256 record_sha256 observation_sha256 device protocol unit",
        )
        alias = f"observation-{index}"
        if observation["alias"] != alias or index > v3.MAX_OBSERVATIONS:
            raise ValueError("observation aliases must match the ordered V3 source selection")
        ids.append(alias)
        binding = observation["binding"]
        if binding not in ("QUALIFIED", "UNRESOLVED"):
            raise ValueError("unknown observation binding status")
        for field in (
            "source_sha256",
            "record_sha256",
            "observation_sha256",
            "device",
            "protocol",
            "unit",
        ):
            val = observation[field]
            if binding == "UNRESOLVED" and val is None:
                continue
            if field.endswith("_sha256"):
                _digest(val)
            else:
                _text(val)
    return ids


def _judgment(value: object, ids: list[str]) -> None:
    row = _fields(
        value,
        "scientific_validity control preferred_action acceptable_actions "
        "dispatch_operation allowed_claims refusal_codes",
    )
    control = row["control"]
    if control not in CONTROLS or row["scientific_validity"] not in (
        "VALID",
        "INVALID",
        "UNRESOLVED",
    ):
        raise ValueError("unknown scientific validity or execution control")
    if (control == "AMBIGUOUS") != (row["scientific_validity"] == "UNRESOLVED"):
        raise ValueError("ambiguous judgments must declare unresolved scientific validity")
    actions = _items(row["acceptable_actions"])
    normalized = {
        v3.canonical(v3.normalize_action(v3.validate_arguments(action, ids))) for action in actions
    }
    if len(normalized) != len(actions) or (control != "AMBIGUOUS" and not actions):
        raise ValueError("expected distinct acceptable scientific actions")
    preferred = row["preferred_action"]
    if preferred is not None and (
        v3.canonical(v3.normalize_action(v3.validate_arguments(preferred, ids))) not in normalized
    ):
        raise ValueError("preferred action must be a member of the acceptable set")
    operation = row["dispatch_operation"]
    if control == "EXECUTE":
        if operation not in v3.EXPOSED_OPERATIONS or row["scientific_validity"] != "VALID":
            raise ValueError(
                "execution control requires a scientifically valid registered proposal"
            )
        if not any(action["operation"] == operation for action in actions):
            raise ValueError("execution control operation must appear in an acceptable action")
    elif operation is not None:
        raise ValueError("only execution controls may authorize dispatch")
    _claims(row["allowed_claims"])
    reasons = [_key(item) for item in _items(row["refusal_codes"])]
    if len(reasons) != len(set(reasons)) or (control == "REFUSE" and not reasons):
        raise ValueError("refusal controls require distinct deterministic reason codes")


def seal(directory: Path) -> dict[str, Any]:
    """Check packet shape and separation. Human independence needs a custodian attestation."""
    content = {name: (directory / name).read_bytes() for name in FILES}
    requests, gold, reviews = (
        [v3.json_object(line) for line in data.decode("utf-8").splitlines()]
        for data in content.values()
    )
    exposed = _exposed_questions()
    items: dict[str, tuple[dict[str, Any], list[str]]] = {}
    scenarios: dict[str, str] = {}
    strata: dict[str, str] = {}
    questions: dict[str, str] = {}
    observations: dict[str, str] = {}
    for row in requests:
        ids = _request(row, exposed)
        item, cluster, scenario = row["item_id"], row["cluster_id"], row["scenario_id"]
        question = _normalize_question(row["question"])
        if strata.setdefault(cluster, row["stratum"]) != row["stratum"]:
            raise ValueError("cluster split across primary strata")
        if item in items or scenarios.setdefault(scenario, cluster) != cluster:
            raise ValueError("duplicate item or scenario split across clusters")
        if questions.setdefault(question, cluster) != cluster:
            raise ValueError("exact normalized question split across clusters")
        for observation in row["observations"]:
            digest = observation["observation_sha256"]
            if digest is not None and observations.setdefault(digest, cluster) != cluster:
                raise ValueError("same observation split across clusters")
        items[item] = (row, ids)
    if (
        len(set(scenarios.values())) < MIN_CLUSTERS
        or len({r["author_id"] for r in requests}) < MIN_AUTHORS
    ):
        raise ValueError("prospective packet has too few declared clusters or authors")
    if any(
        sum(value == stratum for value in strata.values()) < MIN_CLUSTERS_PER_STRATUM
        for stratum in STRATA
    ):
        raise ValueError("prospective packet has too few clusters in a primary stratum")

    by_item: dict[str, dict[str, dict[str, Any]]] = {}
    for row in reviews:
        _fields(row, "item_id reviewer_id judgment rationale")
        item, reviewer = _key(row["item_id"]), _key(row["reviewer_id"])
        if item not in items or reviewer == items[item][0]["author_id"]:
            raise ValueError("review must resolve to a different person's authored item")
        if reviewer in by_item.setdefault(item, {}):
            raise ValueError("duplicate adjudicator")
        _text(row["rationale"])
        _judgment(row["judgment"], items[item][1])
        by_item[item][reviewer] = row["judgment"]

    controls = set()
    seen = set()
    for row in gold:
        _fields(row, "item_id initial_reviewers arbitration_reviewer judgment rationale")
        item = _key(row["item_id"])
        if item in seen or item not in items:
            raise ValueError("unresolved or duplicate gold item")
        seen.add(item)
        reviewers = [_key(reviewer) for reviewer in _items(row["initial_reviewers"])]
        adjudications = by_item.get(item, {})
        if (
            len(reviewers) != 2
            or len(set(reviewers)) != 2
            or not set(reviewers).issubset(adjudications)
        ):
            raise ValueError("gold requires two independent initial reviewer IDs")
        _text(row["rationale"])
        _judgment(row["judgment"], items[item][1])
        left, right = (adjudications[reviewer] for reviewer in reviewers)
        arbiter = row["arbitration_reviewer"]
        if left == right:
            if arbiter is not None or row["judgment"] != left:
                raise ValueError("agreed reviews must be preserved")
        elif (
            not isinstance(arbiter, str)
            or arbiter not in adjudications
            or arbiter in reviewers
            or row["judgment"] != adjudications[arbiter]
        ):
            raise ValueError("disagreement must preserve a third review or its ambiguity decision")
        if set(adjudications) != set(reviewers) | ({arbiter} if arbiter else set()):
            raise ValueError("unaccounted adjudication")
        controls.add(row["judgment"]["control"])
    if seen != items.keys() or not {"EXECUTE", "REFUSE"}.issubset(controls):
        raise ValueError("packet needs complete gold and both positive and negative controls")

    return {
        "schema": "DYNAMISLM_A03_PROSPECTIVE_PACKET_V1",
        "items": len(items),
        "clusters": len(set(scenarios.values())),
        "files": {name: v3.sha256(data) for name, data in content.items()},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protected_directory", type=Path)
    args = parser.parse_args()
    print(v3.canonical(seal(args.protected_directory)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
