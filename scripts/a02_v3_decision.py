"""Preregistered V3 model-comparison protocol and two-stage decision rule (RES-541).

Evidence binding: every arm's records must reproduce the regenerated preregistered held-out
examples exactly (identity, order, family, request hash), name the expected arm, decoder,
model revision, contract profile and protocol, and carry a raw output whose hash matches.
Correctness is recomputed here from the raw output; no reported ``exact`` field is trusted.

Two stages, never conflated:

* Stage 1 (zero-shot arms only) concludes one of three things (amendment P5, recorded before any
  model observation). ``ADOPT_REPAIRED_CONTRACT_WITH_CONSTRAINED_DECODING`` needs the point
  estimate AND the template-cluster-aware 95% lower bound to reach the threshold on both the
  overall and the critical-family exact rate. A point pass whose bound does not reach it is
  ``INCONCLUSIVE_INSUFFICIENT_INDEPENDENT_EVIDENCE``: neither adoption nor eligibility. A point
  failure on a complete, valid evaluation is ``ADAPTATION_STUDY_ELIGIBLE_NOT_AUTHORIZED``,
  which warrants proposing an adaptation study, never shows that adaptation would help and
  authorizes no training.
* Stage 2 (adapted arms observed) can conclude ``ADAPTATION_BENEFIT_DEMONSTRATED``,
  ``ESCALATE_TO_STRONGER_MODEL_COMPARISON`` or ``ADAPTATION_BENEFIT_NOT_DEMONSTRATED``.

Uncertainty: the item-level paired bootstrap is kept, a template-clustered paired bootstrap is
added because examples sharing a template are correlated, and the more conservative lower
bound governs. Per-family Wilson intervals are reported. The held-out set is a synthetic
development split from the same generator families as training: results bound performance on
that generator, not scientific generalization.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from typing import Any

from scripts import a02_v3_contract as v3
from scripts import a02_v3_gold as gold
from scripts import a02_v3_synthetic as synthetic

PROTOCOL_PATH = v3.ROOT / "experiments/a02/model-comparison-protocol-v3.json"
ARM_DECODER = {
    "ZERO_SHOT_UNCONSTRAINED": "native",
    "ZERO_SHOT_CONSTRAINED": "constrained",
    "ADAPTED_UNCONSTRAINED": "native",
    "ADAPTED_CONSTRAINED": "constrained",
}
ZERO_SHOT_ARMS = ("ZERO_SHOT_UNCONSTRAINED", "ZERO_SHOT_CONSTRAINED")
RECORD_SCHEMA = "RES541_A02_V3_ARM_RECORD_V1"


class EvidenceError(ValueError):
    """Arm evidence does not bind to the preregistered examples and provenance."""


def protocol_sha256() -> str:
    return v3.sha256(PROTOCOL_PATH.read_bytes())


def load_protocol() -> dict[str, Any]:
    protocol = v3.json_object(PROTOCOL_PATH.read_text(encoding="utf-8"))
    if protocol.get("schema") != "RES541_A02_V3_MODEL_COMPARISON_PROTOCOL_V1":
        raise ValueError("V3 comparison protocol schema differs")
    if protocol["contract_profile_sha256"] != v3.sha256(v3.PROFILE_PATH.read_bytes()):
        raise ValueError("V3 comparison protocol is not bound to the current contract profile")
    splits = {}
    for name in ("training", "heldout_evaluation"):
        spec = protocol["data"][name]
        examples = synthetic.generate(spec["split"], spec["seed"], spec["count"])
        if synthetic.manifest_sha256(examples) != spec["manifest_sha256"]:
            raise ValueError(f"V3 {name} manifest differs from its preregistered hash")
        splits[name] = examples
    pinned = protocol["data"]["generated_semantics"]
    if (
        v3.ROOT / pinned["path"] != gold.GENERATED_SEMANTICS_PATH
        or v3.sha256(gold.GENERATED_SEMANTICS_PATH.read_bytes()) != pinned["sha256"]
    ):
        raise ValueError("V3 generated-phrasing semantics differ from their preregistered hash")
    for name in ("training", "heldout_evaluation"):
        gold.verify_generated_gold(splits[name])
    if not synthetic.leakage_audit(splits["training"], splits["heldout_evaluation"])["clean"]:
        raise ValueError("V3 preregistered splits are not leakage-clean")
    return protocol


def heldout_examples(protocol: dict[str, Any]) -> list[dict[str, Any]]:
    spec = protocol["data"]["heldout_evaluation"]
    return synthetic.generate(spec["split"], spec["seed"], spec["count"])


def example_id(example: dict[str, Any]) -> str:
    return f"{example['split']}:{example['seed']}:{example['index']}"


def request_sha256(request: dict[str, Any]) -> str:
    return v3.sha256(v3.canonical(request).encode())


def make_record(
    *,
    protocol: dict[str, Any],
    arm: str,
    example: dict[str, Any],
    raw_output: str,
    truncated: bool,
    model: dict[str, str],
) -> dict[str, Any]:
    """The record a worker emits for one arm and one held-out example."""
    return {
        "schema": RECORD_SCHEMA,
        "arm": arm,
        "decoder": ARM_DECODER[arm],
        "example_id": example_id(example),
        "family": example["family"],
        "request_sha256": request_sha256(example["request"]),
        "raw_output": raw_output,
        "raw_output_sha256": v3.sha256(raw_output.encode("utf-8", errors="surrogatepass")),
        "truncated": truncated,
        "model_id": model["id"],
        "model_revision": model["revision"],
        "contract_profile_sha256": protocol["contract_profile_sha256"],
        "protocol_sha256": protocol_sha256(),
    }


def bind_arm(
    protocol: dict[str, Any],
    arm: str,
    records: Sequence[dict[str, Any]],
    *,
    model: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Verify one arm's evidence and recompute per-example correctness from raw output."""
    if arm not in ARM_DECODER:
        raise EvidenceError(f"unknown arm: {arm}")
    examples = heldout_examples(protocol)
    expected_ids = [example_id(e) for e in examples]
    ids = [record.get("example_id") for record in records]
    if len(set(ids)) != len(ids):
        raise EvidenceError(f"{arm}: duplicated example records")
    if set(ids) != set(expected_ids):
        missing = sorted(set(expected_ids) - set(ids))[:3]
        unexpected = sorted(str(i) for i in set(ids) - set(expected_ids))[:3]
        raise EvidenceError(
            f"{arm}: example set differs (missing {missing}, unexpected {unexpected})"
        )
    if ids != expected_ids:
        raise EvidenceError(f"{arm}: records are not in preregistered order")
    model = model or protocol["candidate_model"]
    expected_constants = {
        "schema": RECORD_SCHEMA,
        "arm": arm,
        "decoder": ARM_DECODER[arm],
        "model_id": model["id"],
        "model_revision": model["revision"],
        "contract_profile_sha256": protocol["contract_profile_sha256"],
        "protocol_sha256": protocol_sha256(),
    }
    rows = []
    for example, record in zip(examples, records, strict=True):
        for key, value in expected_constants.items():
            if record.get(key) != value:
                raise EvidenceError(f"{arm}:{record['example_id']}: {key} differs")
        if record.get("family") != example["family"]:
            raise EvidenceError(f"{arm}:{record['example_id']}: family label differs")
        if record.get("request_sha256") != request_sha256(example["request"]):
            raise EvidenceError(f"{arm}:{record['example_id']}: request differs")
        raw = record.get("raw_output")
        if not isinstance(raw, str) or record.get("raw_output_sha256") != v3.sha256(
            raw.encode("utf-8", errors="surrogatepass")
        ):
            raise EvidenceError(f"{arm}:{record['example_id']}: raw output hash differs")
        action = None
        if not record.get("truncated"):
            try:
                action = v3.parse_action(raw, v3.observation_ids(example["request"]))
            except (TypeError, ValueError, UnicodeError):
                action = None
        if ARM_DECODER[arm] == "constrained" and action is None:
            raise EvidenceError(f"{arm}:{record['example_id']}: constrained output is invalid")
        rows.append(
            {
                "example": record["example_id"],
                "family": example["family"],
                "template": example["template_id"],
                "strict_valid": action is not None,
                "exact": action is not None
                and v3.normalize_action(action) == example["gold_action"],
            }
        )
    return rows


# --------------------------------------------------------------------------- statistics


def _rate(rows: Sequence[dict[str, Any]], key: str = "exact") -> float:
    return sum(bool(r[key]) for r in rows) / len(rows) if rows else 0.0


def wilson(successes: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, centre - half), min(1.0, centre + half))


def _percentile_lower(values: list[float], alpha: float) -> float:
    values.sort()
    return values[int(alpha / 2 * len(values))]


def paired_bootstrap_lower(
    a: Sequence[bool], b: Sequence[bool], *, resamples: int, seed: int, alpha: float
) -> float:
    """Item-level lower bound of the (1 - alpha) percentile interval for mean(a - b)."""
    n = len(a)
    rng = random.Random(seed)
    diffs = []
    for _ in range(resamples):
        picks = [rng.randrange(n) for _ in range(n)]
        diffs.append(sum(a[i] - b[i] for i in picks) / n)
    return _percentile_lower(diffs, alpha)


def clustered_bootstrap_lower(
    a: Sequence[bool],
    b: Sequence[bool],
    clusters: Sequence[str],
    *,
    resamples: int,
    seed: int,
    alpha: float,
) -> float:
    """Paired bootstrap resampling whole clusters (templates) with replacement."""
    groups: dict[str, list[int]] = {}
    for index, cluster in enumerate(clusters):
        groups.setdefault(cluster, []).append(index)
    keys = sorted(groups)
    rng = random.Random(seed)
    diffs = []
    for _ in range(resamples):
        picks = [i for _ in keys for i in groups[keys[rng.randrange(len(keys))]]]
        diffs.append(sum(a[i] - b[i] for i in picks) / len(picks))
    return _percentile_lower(diffs, alpha)


def _summary(rows: list[dict[str, Any]], critical: set[str]) -> dict[str, Any]:
    per_family = {}
    for family in sorted({r["family"] for r in rows}):
        subset = [r for r in rows if r["family"] == family]
        wins = sum(r["exact"] for r in subset)
        per_family[family] = {
            "exact": wins / len(subset),
            "n": len(subset),
            "wilson95": wilson(wins, len(subset)),
        }
    critical_rows = [r for r in rows if r["family"] in critical]
    return {
        "exact": _rate(rows),
        "exact_wilson95": wilson(sum(r["exact"] for r in rows), len(rows)),
        "strict_valid": _rate(rows, "strict_valid"),
        "critical_exact": _rate(critical_rows),
        "family": per_family,
    }


def _gain_lower(
    adapted: list[dict[str, Any]], base: list[dict[str, Any]], stats: dict[str, Any], offset: int
) -> dict[str, float]:
    a = [bool(r["exact"]) for r in adapted]
    b = [bool(r["exact"]) for r in base]
    seed = stats["seed"] + offset
    item = paired_bootstrap_lower(
        a, b, resamples=stats["resamples"], seed=seed, alpha=stats["alpha"]
    )
    clustered = clustered_bootstrap_lower(
        a,
        b,
        [r["template"] for r in base],
        resamples=stats["resamples"],
        seed=seed,
        alpha=stats["alpha"],
    )
    return {"item": item, "template_clustered": clustered, "governing": min(item, clustered)}


def cluster_design(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Cluster structure of the evidence: how many independent-looking units there really are."""
    sizes: dict[str, int] = {}
    for row in rows:
        sizes[row["template"]] = sizes.get(row["template"], 0) + 1
    total = sum(sizes.values())
    return {
        "items": total,
        "template_clusters": len(sizes),
        "min_cluster_items": min(sizes.values()),
        "max_cluster_items": max(sizes.values()),
        # Kish effective number of equal-sized clusters: (sum n)^2 / sum n^2.
        "effective_clusters": total * total / sum(n * n for n in sizes.values()),
    }


def _rate_bounds(
    rows: list[dict[str, Any]], stats: dict[str, Any], offset: int
) -> dict[str, float]:
    """Item-level and template-clustered lower bounds on the exact rate of ``rows``."""
    hits = [bool(r["exact"]) for r in rows]
    never = [False] * len(hits)
    seed = stats["seed"] + offset
    item = paired_bootstrap_lower(
        hits, never, resamples=stats["resamples"], seed=seed, alpha=stats["alpha"]
    )
    clustered = clustered_bootstrap_lower(
        hits,
        never,
        [r["template"] for r in rows],
        resamples=stats["resamples"],
        seed=seed,
        alpha=stats["alpha"],
    )
    return {"item": item, "template_clustered": clustered, "governing": min(item, clustered)}


def leave_one_template_out(
    rows: Sequence[dict[str, Any]], critical: set[str], thresholds: dict[str, float]
) -> dict[str, Any]:
    """Recompute the point rates with each template removed, to show what drives the result."""
    templates = sorted({r["template"] for r in rows})
    per_template = []
    for template in templates:
        kept = [r for r in rows if r["template"] != template]
        kept_critical = [r for r in kept if r["family"] in critical]
        exact = _rate(kept)
        critical_exact = _rate(kept_critical) if kept_critical else None
        per_template.append(
            {
                "template": template,
                "items_removed": len(rows) - len(kept),
                "exact": exact,
                "critical_exact": critical_exact,
                "point_thresholds_hold": exact >= thresholds["exact"]
                and critical_exact is not None
                and critical_exact >= thresholds["critical_exact"],
            }
        )
    worst = min(per_template, key=lambda t: (t["exact"], t["template"]))
    return {
        "templates": per_template,
        "min_exact": worst["exact"],
        "worst_template_for_exact": worst["template"],
        "min_critical_exact": min(
            (t["critical_exact"] for t in per_template if t["critical_exact"] is not None),
            default=None,
        ),
        "point_thresholds_hold_after_every_removal": all(
            t["point_thresholds_hold"] for t in per_template
        ),
    }


CONFIDENCE_LIMITATIONS = (
    "Percentile bootstrap bounds from about 15 template clusters (about 8 effective) are "
    "approximate and can be optimistic or unstable when a few large clusters dominate.",
    "Resampling treats templates as the only dependence; the measurement and values drawn per "
    "example are not modelled.",
    "The bound describes this synthetic generator only and says nothing about real requests.",
    "The lower bound is the smaller of the item-level and template-clustered percentile "
    "bounds, so it is conservative by construction.",
)


def decide(
    evidence: Mapping[str, Sequence[dict[str, Any]]], protocol: dict[str, Any]
) -> dict[str, Any]:
    """Apply the preregistered two-stage rule to bound arm evidence."""
    rule = protocol["decision_rule"]
    stats = rule["statistics"]
    critical = set(rule["critical_families"])
    if set(ZERO_SHOT_ARMS) - set(evidence):
        raise EvidenceError("both zero-shot arms are required")
    rows = {arm: bind_arm(protocol, arm, records) for arm, records in evidence.items()}
    report: dict[str, Any] = {arm: _summary(r, critical) for arm, r in rows.items()}
    zu, zc = report["ZERO_SHOT_UNCONSTRAINED"], report["ZERO_SHOT_CONSTRAINED"]
    report["strict_parse_valid_gap"] = zc["strict_valid"] - zu["strict_valid"]
    report["decoder_condition_exact_gap"] = {
        "value": zc["exact"] - zu["exact"],
        "interpretation": "Includes constrained-search and selection effects, not syntax alone; "
        "never credited as understanding.",
    }
    report["template_clusters"] = len({r["template"] for r in rows["ZERO_SHOT_CONSTRAINED"]})
    report["cluster_design"] = cluster_design(rows["ZERO_SHOT_CONSTRAINED"])
    for arm in ZERO_SHOT_ARMS:
        arm_critical = [r for r in rows[arm] if r["family"] in critical]
        report[arm]["exact_lower_bounds"] = _rate_bounds(rows[arm], stats, 2)
        report[arm]["critical_exact_lower_bounds"] = _rate_bounds(arm_critical, stats, 3)
    report["critical_cluster_design"] = cluster_design(
        [r for r in rows["ZERO_SHOT_CONSTRAINED"] if r["family"] in critical]
    )
    sufficient = rule["zero_shot_sufficient"]
    report["leave_one_template_out"] = leave_one_template_out(
        rows["ZERO_SHOT_CONSTRAINED"], critical, sufficient
    )
    report["confidence_limitations"] = list(CONFIDENCE_LIMITATIONS)
    report["evidence_scope"] = "SYNTHETIC_DEVELOPMENT_ONLY"
    report["claim_ceiling"] = protocol["claim_ceiling"]

    point_ok = (
        zc["exact"] >= sufficient["exact"] and zc["critical_exact"] >= sufficient["critical_exact"]
    )
    bound_ok = (
        zc["exact_lower_bounds"]["governing"] >= sufficient["lower_bound"]
        and zc["critical_exact_lower_bounds"]["governing"] >= sufficient["lower_bound"]
    )
    report["sufficiency_basis"] = {
        "point_thresholds_met": point_ok,
        "lower_bound_thresholds_met": bound_ok,
        "rule": "adoption needs the point estimate and the template-cluster-aware 95% lower "
        "bound to reach the threshold on both the overall and the critical-family exact rate",
    }
    if point_ok and bound_ok:
        return {**report, "stage": 1, "decision": sufficient["decision"]}
    if point_ok:
        return {**report, "stage": 1, "decision": sufficient["inconclusive_decision"]}
    if not {"ADAPTED_UNCONSTRAINED", "ADAPTED_CONSTRAINED"} & set(rows):
        return {**report, "stage": 1, "decision": rule["stage_1_otherwise"]}
    if "ADAPTED_CONSTRAINED" not in rows:
        raise EvidenceError("stage 2 requires the constrained adapted arm")

    benefit = rule["adaptation_benefit"]
    sc = report["ADAPTED_CONSTRAINED"]
    crit = [i for i, r in enumerate(rows["ZERO_SHOT_CONSTRAINED"]) if r["family"] in critical]
    gain = _gain_lower(rows["ADAPTED_CONSTRAINED"], rows["ZERO_SHOT_CONSTRAINED"], stats, 0)
    critical_gain = _gain_lower(
        [rows["ADAPTED_CONSTRAINED"][i] for i in crit],
        [rows["ZERO_SHOT_CONSTRAINED"][i] for i in crit],
        stats,
        1,
    )
    regressions = sorted(
        family
        for family, value in sc["family"].items()
        if value["exact"] < zc["family"][family]["exact"] - benefit["max_family_regression"]
    )
    checks = {
        "minimum_gain": sc["exact"] - zc["exact"] >= benefit["minimum_gain"],
        "gain_lower_bound_above_zero": gain["governing"] > 0,
        "adapted_exact_floor": sc["exact"] >= benefit["adapted_exact_floor"],
        "critical_not_worse": critical_gain["governing"] >= benefit["critical_lower_bound_floor"],
        "no_family_regression": not regressions,
    }
    report.update(
        stage=2,
        adaptation_checks=checks,
        gain_lower_bounds=gain,
        critical_gain_lower_bounds=critical_gain,
        family_regressions=regressions,
    )
    if all(checks.values()):
        return {**report, "decision": benefit["decision"]}
    if max(zc["exact"], sc["exact"]) < rule["escalate_stronger_model_below"]:
        return {**report, "decision": "ESCALATE_TO_STRONGER_MODEL_COMPARISON"}
    return {**report, "decision": rule["stage_2_otherwise"]}


def estimate_zero_shot_seconds(
    *,
    examples: int,
    prompt_tokens: int,
    cached_fed_tokens: int,
    scorer_calls: int,
    action_cap: int,
    first_token_seconds: float,
    decode_tokens_per_second: float,
    load_seconds: float,
) -> dict[str, float]:
    """Engineering estimate (not a bound) for both zero-shot arms on one T4.

    Constrained: one prompt prefill per example, then one incremental forward per scored
    option, each costed as one decode step. Unconstrained: one prefill plus the full action
    cap at the measured decode rate. Prefill cost is the measured first-token latency.
    """
    if prompt_tokens >= cached_fed_tokens or scorer_calls <= 0:
        raise ValueError("cached work must exceed one prompt prefill")
    step = 1.0 / decode_tokens_per_second
    constrained = examples * (first_token_seconds + scorer_calls * step)
    unconstrained = examples * (first_token_seconds + action_cap * step)
    return {
        "constrained_arm_seconds": round(constrained, 1),
        "unconstrained_arm_seconds": round(unconstrained, 1),
        "model_load_seconds": load_seconds,
        "total_seconds": round(constrained + unconstrained + load_seconds, 1),
    }
