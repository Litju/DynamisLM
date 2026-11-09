"""Preregistered V3 model-comparison protocol and decision rule (RES-541).

The decision is computed only from held-out synthetic intent results; the ten exposed A0.2
cases are development diagnostics and never a decision input. Training is not assumed to be
the answer: the rule can select the repaired zero-shot contract, adaptation, escalation to a
stronger model, or no adoption.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from typing import Any

from scripts import a02_v3_contract as v3
from scripts import a02_v3_synthetic as synthetic

PROTOCOL_PATH = v3.ROOT / "experiments/a02/model-comparison-protocol-v3.json"
ARMS = (
    "ZERO_SHOT_UNCONSTRAINED",
    "ZERO_SHOT_CONSTRAINED",
    "ADAPTED_UNCONSTRAINED",
    "ADAPTED_CONSTRAINED",
)


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
    if not synthetic.leakage_audit(splits["training"], splits["heldout_evaluation"])["clean"]:
        raise ValueError("V3 preregistered splits are not leakage-clean")
    return protocol


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


def _accuracy(rows: Sequence[dict[str, Any]]) -> float:
    return sum(bool(r["exact"]) for r in rows) / len(rows) if rows else 0.0


def _paired_bootstrap_lower(
    a: Sequence[bool], b: Sequence[bool], *, resamples: int, seed: int, alpha: float
) -> float:
    """Lower bound of the (1 - alpha) percentile interval for mean(a) - mean(b), paired."""
    n = len(a)
    rng = random.Random(seed)
    diffs = []
    for _ in range(resamples):
        picks = [rng.randrange(n) for _ in range(n)]
        diffs.append(sum(a[i] - b[i] for i in picks) / n)
    diffs.sort()
    return diffs[int(alpha / 2 * resamples)]


def decide(results: dict[str, list[dict[str, Any]]], protocol: dict[str, Any]) -> dict[str, Any]:
    """Apply the preregistered rule to per-example held-out rows.

    Each row: ``{"example": "<split>:<seed>:<index>", "family": str, "exact": bool}``.
    Arms must be scored on identical examples in identical order.
    """
    rule = protocol["decision_rule"]
    stats = rule["statistics"]
    critical = set(rule["critical_families"])
    keys = [r["example"] for r in results["ZERO_SHOT_CONSTRAINED"]]
    for arm, rows in results.items():
        if arm not in ARMS or [r["example"] for r in rows] != keys:
            raise ValueError("decision arms must cover identical held-out examples in order")
    if len(keys) != protocol["data"]["heldout_evaluation"]["count"]:
        raise ValueError("decision requires the complete preregistered held-out set")

    def summary(arm: str) -> dict[str, Any]:
        rows = results[arm]
        families = sorted({r["family"] for r in rows})
        return {
            "exact": _accuracy(rows),
            "critical_exact": _accuracy([r for r in rows if r["family"] in critical]),
            "family_exact": {f: _accuracy([r for r in rows if r["family"] == f]) for f in families},
        }

    report: dict[str, Any] = {arm: summary(arm) for arm in results}
    zc = report["ZERO_SHOT_CONSTRAINED"]
    if "ZERO_SHOT_UNCONSTRAINED" in report:
        report["syntax_attributable_gap_not_credited"] = (
            zc["exact"] - report["ZERO_SHOT_UNCONSTRAINED"]["exact"]
        )

    if (
        zc["exact"] >= rule["zero_shot_sufficient"]["exact"]
        and zc["critical_exact"] >= (rule["zero_shot_sufficient"]["critical_exact"])
    ):
        return {**report, "decision": "ADOPT_REPAIRED_CONTRACT_WITH_CONSTRAINED_DECODING"}

    if "ADAPTED_CONSTRAINED" not in results:
        return {**report, "decision": "ADAPTATION_ARM_REQUIRED"}

    sc = report["ADAPTED_CONSTRAINED"]
    a = [bool(r["exact"]) for r in results["ADAPTED_CONSTRAINED"]]
    z = [bool(r["exact"]) for r in results["ZERO_SHOT_CONSTRAINED"]]
    crit = [i for i, r in enumerate(results["ZERO_SHOT_CONSTRAINED"]) if r["family"] in critical]
    gain_lower = _paired_bootstrap_lower(
        a, z, resamples=stats["resamples"], seed=stats["seed"], alpha=stats["alpha"]
    )
    critical_lower = _paired_bootstrap_lower(
        [a[i] for i in crit],
        [z[i] for i in crit],
        resamples=stats["resamples"],
        seed=stats["seed"] + 1,
        alpha=stats["alpha"],
    )
    regressions = sorted(
        family
        for family, value in sc["family_exact"].items()
        if value
        < zc["family_exact"][family] - rule["adaptation_justified"]["max_family_regression"]
    )
    justified = rule["adaptation_justified"]
    checks = {
        "minimum_gain": sc["exact"] - zc["exact"] >= justified["minimum_gain"],
        "gain_ci_lower_above_zero": gain_lower > 0,
        "adapted_exact_floor": sc["exact"] >= justified["adapted_exact_floor"],
        "critical_not_worse": critical_lower >= justified["critical_ci_lower_floor"],
        "no_family_regression": not regressions,
    }
    report.update(
        adaptation_checks=checks,
        gain_ci_lower=gain_lower,
        critical_gain_ci_lower=critical_lower,
        family_regressions=regressions,
    )
    if all(checks.values()):
        return {**report, "decision": "ADAPTATION_JUSTIFIED"}
    escalate = rule["escalate_stronger_model_below"]
    if max(zc["exact"], sc["exact"]) < escalate:
        return {**report, "decision": "ESCALATE_TO_STRONGER_MODEL_COMPARISON"}
    return {**report, "decision": "INCONCLUSIVE_NO_ADOPTION"}
