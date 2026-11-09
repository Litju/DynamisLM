"""Independent V3 gold derivation and gold-derivability gate (RES-541).

Every gold field is derived from the model-visible request plus a cited authority:

* ``observation_ids``: visible ids of observations of the requested measurement;
* ``analysis_class`` / ``target_claims``: closed objective-phrase rules in
  ``objective-semantics-v3.json``, each citing RES-70 claim levels;
* ``operation``: the RES-70 capability registry and operation inventory
  (``a02_v3_contract.operation_for``).

The derivation never reads the V1/V2 expected actions. Agreement with them is checked
separately, as a cross-check, and every divergence is reported rather than hidden.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dynamislm.analysis import CANONICAL_ANALYSIS_CAPABILITY_REGISTRY, AnalysisClass
from scripts import a02_dev_protocol, a02_experiment
from scripts import a02_v3_contract as v3

SEMANTICS_PATH = v3.ROOT / "experiments/a02/objective-semantics-v3.json"


class DerivationUnsupportedError(ValueError):
    """The request cannot be grounded by the declared V3 authorities."""


def load_semantics(path: Path = SEMANTICS_PATH) -> dict[str, Any]:
    semantics = v3.json_object(path.read_text(encoding="utf-8"))
    if semantics.get("schema") != "RES541_A02_OBJECTIVE_SEMANTICS_V3":
        raise ValueError("V3 objective semantics schema differs")
    ids = [rule["id"] for rule in semantics["rules"]]
    phrases = [rule["phrase"].lower() for rule in semantics["rules"]]
    if len(set(ids)) != len(ids) or len(set(phrases)) != len(phrases):
        raise ValueError("V3 objective semantics rules are not unique")
    for rule in semantics["rules"]:
        analysis = rule["analysis_class"]
        if analysis is not None and analysis not in v3.ANALYSIS_CLASSES:
            raise ValueError(f"V3 semantics rule names an unknown analysis class: {rule['id']}")
        for axis, levels in v3.CLAIM_AXES.items():
            if any(level not in levels for level in rule[axis]):
                raise ValueError(f"V3 semantics rule names an unknown claim level: {rule['id']}")
        if not rule.get("justification"):
            raise ValueError(f"V3 semantics rule lacks a justification: {rule['id']}")
    return semantics


def derive_gold(request: dict[str, Any], semantics: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return ``{"action": ..., "justification": ...}`` or raise DerivationUnsupportedError."""
    semantics = load_semantics() if semantics is None else semantics
    visible = v3.visible_request(request)
    objective = visible.get("objective")
    if not isinstance(objective, str) or not objective:
        raise DerivationUnsupportedError("request has no objective")
    lowered = objective.lower()
    matched = []
    for rule in semantics["rules"]:
        count = lowered.count(rule["phrase"].lower())
        if count > 1:
            raise DerivationUnsupportedError(f"objective repeats phrase: {rule['id']}")
        if count == 1:
            matched.append(rule)
    if not any(not rule.get("composite_marker") for rule in matched):
        raise DerivationUnsupportedError("objective matches no declared semantic rule")

    claims = {
        axis: [level for level in levels if any(level in rule[axis] for rule in matched)]
        for axis, levels in v3.CLAIM_AXES.items()
    }
    analyses = sorted({r["analysis_class"] for r in matched if r["analysis_class"] is not None})
    composite = (
        any(rule.get("composite_marker") for rule in matched)
        or len(analyses) > 1
        or any(len(levels) > 1 for levels in claims.values())
    )
    if composite:
        analysis = v3.NONE
    elif len(analyses) == 1:
        analysis = analyses[0]
    else:
        raise DerivationUnsupportedError("objective names claims but no analysis class")

    measurement = visible.get("measurement")
    ids = [row["id"] for row in visible["observations"] if row.get("measurement") == measurement]
    operation = v3.operation_for(analysis, len(ids))
    action = {
        "analysis_class": analysis,
        "operation": operation,
        "observation_ids": ids,
        "target_claims": claims,
    }
    v3.validate_arguments(action, [row["id"] for row in visible["observations"]])
    capability = (
        None
        if analysis == v3.NONE
        else CANONICAL_ANALYSIS_CAPABILITY_REGISTRY.resolve(AnalysisClass(analysis))
    )
    justification = {
        "objective": objective,
        "matched_rules": [rule["id"] for rule in matched],
        "analysis_class": "composite: NONE" if composite else f"rule {analyses[0]}",
        "observation_ids": {
            "rule": "visible observations whose measurement equals request.measurement",
            "evidence": [
                {"pointer": f"/observations/{i}/id", "value": row["id"]}
                for i, row in enumerate(visible["observations"])
                if row["id"] in ids
            ],
        },
        "operation": {
            "rule": "RES-70 capability registry: IMPLEMENTED, exposed, support shape arity",
            "capability": None
            if capability is None
            else {
                "reference": capability.capability_reference.stable_id,
                "disposition": capability.disposition.value,
                "registered_operation": None
                if capability.registered_operation_reference is None
                else capability.registered_operation_reference.stable_id,
                "support_shape": list(capability.required_support_shape),
            },
            "observation_count": len(ids),
        },
        "target_claims_prerequisites_not_counted": {
            axis: v3.prerequisite_expansion(axis, levels) for axis, levels in claims.items()
        },
    }
    return {"action": action, "justification": justification}


def _resolve_pointer(document: Any, pointer: str) -> Any:
    current = document
    for token in pointer.lstrip("/").split("/"):
        current = current[int(token)] if isinstance(current, list) else current[token]
    return current


def audit_case(request: dict[str, Any], semantics: dict[str, Any]) -> dict[str, Any]:
    """Gold-derivability checks for one request; every check must be True."""
    gold = derive_gold(request, semantics)
    again = derive_gold(request, semantics)
    visible = v3.visible_request(request)
    action, why = gold["action"], gold["justification"]
    ids = [row["id"] for row in visible["observations"]]
    rules = {rule["id"]: rule for rule in semantics["rules"]}
    checks = {
        "deterministic": v3.canonical(gold) == v3.canonical(again),
        "ids_bijective": len(set(ids)) == len(ids) == len(visible["observations"])
        and ids == [f"observation-{i}" for i in range(1, len(ids) + 1)],
        "gold_ids_visible": all(ref in ids for ref in action["observation_ids"]),
        "id_evidence_resolves": all(
            _resolve_pointer(visible, item["pointer"]) == item["value"]
            for item in why["observation_ids"]["evidence"]
        ),
        "objective_phrases_visible": all(
            rules[rule_id]["phrase"].lower() in visible["objective"].lower()
            for rule_id in why["matched_rules"]
        ),
        "claims_from_matched_rules_only": all(
            any(level in rules[rule_id][axis] for rule_id in why["matched_rules"])
            for axis in v3.CLAIM_AXES
            for level in action["target_claims"][axis]
        ),
        "operation_from_registry": action["operation"]
        == v3.operation_for(action["analysis_class"], len(action["observation_ids"])),
        "targets_exclude_prerequisites": all(
            not set(why["target_claims_prerequisites_not_counted"][axis])
            & set(action["target_claims"][axis])
            for axis in v3.CLAIM_AXES
        ),
    }
    return {"action": action, "checks": checks, "derivable": all(checks.values())}


def v2_divergence(case_id: str, action: dict[str, Any]) -> dict[str, Any]:
    """Field-level comparison with the frozen V2 gold (report only, never a correction)."""
    v2 = a02_dev_protocol.expected_intent(case_id)
    as_v2 = {
        "analysis_class": v2["analysis_class"] or v3.NONE,
        "operation": v2["operation"] or v3.NONE,
        "observation_ids": [row["reference"] for row in v2["observations"]],
        "target_claims": {
            "measurement": v2["requested_claims"]["measurement_levels"],
            "relationship": v2["requested_claims"]["relationship_levels"],
        },
    }
    a, b = v3.normalize_action(action), v3.normalize_action(as_v2)
    return {
        "differing_fields": sorted(key for key in v3.ACTION_FIELDS if a[key] != b[key]),
        "v2": as_v2,
    }


def audit_exposed_cases() -> dict[str, Any]:
    semantics = load_semantics()
    cases = json.loads(a02_experiment.CASES_PATH.read_bytes())["cases"]
    rows = []
    for case in cases:
        audit = audit_case(case["request"], semantics)
        rows.append(
            {
                "case_id": case["case_id"],
                **audit,
                "v2_divergence": v2_divergence(case["case_id"], audit["action"]),
            }
        )
    return {
        "schema": "RES541_A02_V3_GOLD_DERIVABILITY_V1",
        "cases": rows,
        "derivable": {
            "numerator": sum(row["derivable"] for row in rows),
            "denominator": len(rows),
        },
    }
