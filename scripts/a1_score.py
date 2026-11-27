"""Scoring for the A1 campaign (RES-832): strict, per-field, cluster-aware.

Scoring is a pure function of committed generations and frozen gold. It never reads a model and
never re-runs inference.

Strictness rules
----------------
* **Strict structured-output validity** means the generation is exactly one framed V3 tool call
  that parses and validates against the request's own observation ids. It is reported on its own
  axis and is *never* credited as scientific reasoning.
* **Full-action exact match** is normalised equality on all four action fields.
* **Acceptable match** additionally allows the judged alternatives declared for a case. The A1
  cohort has one gold action per case by construction, so exact and acceptable coincide; the
  distinction is kept because the retrospective RES-774 cohort has judged alternatives.
* **Relaxed semantic interpretation** is a *diagnostic* only. It is computed by a fixed, gold-
  blind rule set over malformed outputs and can never upgrade the strict score.

Statistics
----------
The scenario cluster is the unit of inference. Every arm is summarised by an equal-cluster mean
and a stratified cluster bootstrap interval, and every paired contrast is estimated by resampling
clusters jointly. Item-level McNemar results are reported descriptively only and are labelled
non-confirmatory, because items inside a cluster share their scenario. Equivalence is never
claimed from an interval that merely contains zero, and never without a prespecified margin.
"""

from __future__ import annotations

import math
import random
import re
from statistics import fmean
from typing import Any

from scripts import a02_v3_contract as v3

ALL_IDS = [f"observation-{index}" for index in range(1, v3.MAX_OBSERVATIONS + 1)]
BOOTSTRAP_DRAWS = 10000
BOOTSTRAP_SEED = 832001

# Prespecified practical-equivalence margin for the semantic contrasts. Entries are half-widths
# in proportion units on the acceptable-intent scale. Declared before any A1 output is observed.
EQUIVALENCE_MARGIN = 0.15

# Prespecified substantive-effect floor used by the H1 decision rule, exactly as registered.
SUBSTANTIVE_EFFECT = 0.20

_HEDGE = re.compile(
    r"\b(?:cannot|can't|unable|insufficient|not enough|no(?:t)? (?:provided|supplied)|"
    r"would need|requires? (?:more|additional)|insufficient evidence|not identifiable)\b",
    re.IGNORECASE,
)


def strict_parse(raw: str, request: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """Return (action, status). Status is PARSED or a fixed failure category."""
    ids = v3.observation_ids(request)
    try:
        action = v3.parse_action(raw, ids)
    except (ValueError, TypeError) as exc:
        message = str(exc)
        if "exactly one framed tool call" in message:
            return None, "FRAMING_INVALID"
        if "envelope" in message or "tool name" in message:
            return None, "ENVELOPE_INVALID"
        if "analysis_class" in message or "enumeration" in message:
            return None, "ENUM_INVALID"
        if "observation_ids" in message:
            return None, "OBSERVATION_REF_INVALID"
        if "target_claims" in message:
            return None, "CLAIM_INVALID"
        if "fields" in message:
            return None, "FIELD_SET_INVALID"
        return None, "INVALID_JSON"
    return v3.normalize_action(action), "PARSED"


def relaxed_action(raw: str, request: dict[str, Any]) -> dict[str, Any] | None:
    """Fixed, gold-blind recovery of a partially malformed action. Diagnostic only.

    The rule set is deliberately narrow and total: it never guesses an analysis class or an
    observation reference, and it only accepts values that appear verbatim in the output.
    """
    ids = set(v3.observation_ids(request))
    found: dict[str, Any] = {}
    for field in ("analysis_class", "operation"):
        match = re.search(rf'"{field}"\s*:\s*"([^"]*)"', raw)
        if match and (
            match.group(1) in (*v3.ANALYSIS_CLASSES, v3.NONE)
            if field == "analysis_class"
            else match.group(1) in (*v3.EXPOSED_OPERATIONS, v3.NONE)
        ):
            found[field] = match.group(1)
    refs = re.findall(r'"(observation-[1-9][0-9]*)"', raw)
    if refs and all(ref in ids for ref in refs) and len(set(refs)) == len(refs):
        found["observation_ids"] = sorted(refs, key=lambda item: int(item.split("-")[1]))
    claims: dict[str, list[str]] = {}
    for axis, levels in v3.CLAIM_AXES.items():
        block = re.search(rf'"{axis}"\s*:\s*\[([^\]]*)\]', raw)
        values = re.findall(r'"([^"]*)"', block.group(1)) if block else []
        if values and all(value in levels for value in values) and len(set(values)) == len(values):
            claims[axis] = values
    if len(claims) == len(v3.CLAIM_AXES):
        found["target_claims"] = claims
    if set(found) != set(v3.ACTION_FIELDS):
        return None
    try:
        v3.validate_arguments(found, list(ids))
    except ValueError:
        return None
    return v3.normalize_action(found)


def field_scores(action: dict[str, Any] | None, gold: dict[str, Any]) -> dict[str, Any]:
    if action is None:
        return {
            "analysis_class": 0,
            "operation": 0,
            "observation_set_exact": 0,
            "observation_f1": 0.0,
            "measurement_claim_exact": 0,
            "relationship_claim_exact": 0,
            "target_claims_exact": 0,
        }
    predicted = set(action["observation_ids"])
    expected = set(gold["observation_ids"])
    if not predicted and not expected:
        precision = recall = f1 = 1.0
    else:
        hit = len(predicted & expected)
        precision = hit / len(predicted) if predicted else 0.0
        recall = hit / len(expected) if expected else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "analysis_class": int(action["analysis_class"] == gold["analysis_class"]),
        "operation": int(action["operation"] == gold["operation"]),
        "observation_set_exact": int(predicted == expected),
        "observation_f1": f1,
        "measurement_claim_exact": int(
            action["target_claims"]["measurement"] == gold["target_claims"]["measurement"]
        ),
        "relationship_claim_exact": int(
            action["target_claims"]["relationship"] == gold["target_claims"]["relationship"]
        ),
        "target_claims_exact": int(action["target_claims"] == gold["target_claims"]),
    }


def score_row(
    *,
    case: dict[str, Any],
    gold: dict[str, Any],
    raw: str,
    request: dict[str, Any],
    acceptable: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    action, status = strict_parse(raw, request)
    alternatives = acceptable or [gold]
    relaxed = None if action is not None else relaxed_action(raw, request)
    strict_action = action
    row = {
        "case_id": case["case_id"],
        "cluster": case["cluster"],
        "stratum": case["stratum"],
        "parse_status": status,
        "structured_valid": int(action is not None),
        "exact": int(strict_action is not None and strict_action == gold),
        "acceptable": int(strict_action is not None and strict_action in alternatives),
        "relaxed_recovery": int(relaxed is not None),
        "relaxed_exact": int(relaxed is not None and relaxed == gold),
        "hedged": int(bool(_HEDGE.search(raw))),
        "no_action": int(
            action is not None
            and action["analysis_class"] == v3.NONE
            and action["operation"] == v3.NONE
            and not action["observation_ids"]
            and not any(action["target_claims"].values())
        ),
        "action": strict_action,
        "relaxed_action": relaxed,
    }
    row.update(field_scores(strict_action, gold))
    return row


def cluster_means(rows: list[dict[str, Any]], key: str) -> dict[str, float]:
    grouped: dict[str, list[float]] = {}
    for row in rows:
        grouped.setdefault(row["cluster"], []).append(float(row[key]))
    return {cluster: fmean(values) for cluster, values in grouped.items()}


def percentile(sorted_values: list[float], fraction: float) -> float:
    if not sorted_values:
        raise ValueError("empty sample")
    position = (len(sorted_values) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def cluster_bootstrap(
    rows: list[dict[str, Any]],
    key: str,
    *,
    draws: int = BOOTSTRAP_DRAWS,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Equal-cluster mean with a percentile cluster bootstrap interval."""
    means = cluster_means(rows, key)
    values = [means[key_] for key_ in sorted(means)]
    if not values:
        return {"estimate": None, "ci95": None, "clusters": 0}
    rng = random.Random(seed)
    n = len(values)
    samples = sorted(fmean(rng.choices(values, k=n)) for _ in range(draws))
    return {
        "estimate": fmean(values),
        "ci95": [percentile(samples, 0.025), percentile(samples, 0.975)],
        "clusters": n,
        "items": len(rows),
        "item_weighted": fmean(float(row[key]) for row in rows),
    }


def paired_bootstrap(
    left: list[dict[str, Any]],
    right: list[dict[str, Any]],
    key: str,
    *,
    draws: int = BOOTSTRAP_DRAWS,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Paired contrast resampling whole clusters jointly from both arms."""
    left_by = {(row["cluster"], row["case_id"]): float(row[key]) for row in left}
    right_by = {(row["cluster"], row["case_id"]): float(row[key]) for row in right}
    if set(left_by) != set(right_by):
        raise ValueError("paired contrast requires identical case inventories")
    diffs: dict[str, list[float]] = {}
    for (cluster, case_id), value in left_by.items():
        diffs.setdefault(cluster, []).append(value - right_by[(cluster, case_id)])
    clusters = sorted(diffs)
    means = [fmean(diffs[cluster]) for cluster in clusters]
    rng = random.Random(seed)
    n = len(means)
    samples = sorted(fmean(rng.choices(means, k=n)) for _ in range(draws))
    low, high = percentile(samples, 0.025), percentile(samples, 0.975)
    point = fmean(means)
    margin = EQUIVALENCE_MARGIN
    if low > -margin and high < margin:
        verdict = "PRACTICAL_EQUIVALENCE_WITHIN_MARGIN"
    elif low > 0:
        verdict = "IMPROVEMENT"
    elif high < 0:
        verdict = "DEGRADATION"
    else:
        verdict = "INCONCLUSIVE_DIFFERENCE"
    return {
        "estimate": point,
        "ci95": [low, high],
        "clusters": n,
        "items": len(left_by),
        "equivalent_margin": margin,
        "verdict": verdict,
    }


def mcnemar(left: list[dict[str, Any]], right: list[dict[str, Any]], key: str) -> dict[str, Any]:
    """Descriptive item-level McNemar. Never confirmatory when items share a cluster."""
    left_by = {row["case_id"]: int(row[key]) for row in left}
    right_by = {row["case_id"]: int(row[key]) for row in right}
    b = sum(1 for case in left_by if left_by[case] == 1 and right_by[case] == 0)
    c = sum(1 for case in left_by if left_by[case] == 0 and right_by[case] == 1)
    if b + c == 0:
        p = 1.0
    else:
        # Exact two-sided binomial test at p=0.5.
        import math as _math

        total = sum(_math.comb(b + c, index) for index in range(0, min(b, c) + 1)) / 2 ** (b + c)
        p = min(1.0, 2 * total)
    return {
        "left_only": b,
        "right_only": c,
        "p_value": p,
        "confidence": "DESCRIPTIVE_NON_CONFIRMATORY_CLUSTERED_ITEMS",
    }


def arm_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    keys = (
        "structured_valid",
        "exact",
        "acceptable",
        "relaxed_recovery",
        "relaxed_exact",
        "hedged",
        "no_action",
        "analysis_class",
        "operation",
        "observation_set_exact",
        "observation_f1",
        "measurement_claim_exact",
        "relationship_claim_exact",
        "target_claims_exact",
    )
    summary = {key: cluster_bootstrap(rows, key) for key in keys}
    summary["strata"] = {}
    for stratum in sorted({row["stratum"] for row in rows}):
        subset = [row for row in rows if row["stratum"] == stratum]
        summary["strata"][stratum] = {
            key: cluster_bootstrap(subset, key)
            for key in ("structured_valid", "exact", "acceptable")
        }
    summary["parse_status"] = {}
    for row in rows:
        summary["parse_status"][row["parse_status"]] = (
            summary["parse_status"].get(row["parse_status"], 0) + 1
        )
    return summary


def output_distribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for row in rows:
        action = row["action"] or row["relaxed_action"]
        text = v3.canonical(action) if action else "INVALID"
        counts[text] = counts.get(text, 0) + 1
    total = sum(counts.values()) or 1
    entropy = -sum((count / total) * math.log2(count / total) for count in counts.values() if count)
    top = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:5]
    return {
        "distinct": len(counts),
        "entropy_bits": entropy,
        "max_share": max(counts.values()) / total,
        "top": [{"action": action, "count": count} for action, count in top],
    }
