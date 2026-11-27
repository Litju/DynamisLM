"""A1 analysis and report generation (RES-832).

Consumes committed generation files and the frozen gold; produces the evidence tables and
``docs/research/A1-REPORT.md``. Pure CPU, deterministic, and never re-runs inference.

The report separates the four things the mission requires to stay apart:

1. **Observed** - what the committed generations contain.
2. **Estimated** - paired effect estimates with cluster-aware uncertainty.
3. **Supported / rejected / inconclusive** - the prespecified hypotheses, resolved only by their
   registered rules.
4. **Explained** - the causal reading, which is always narrower than the estimate.

Every table carries its denominators. Missing arms are reported as missing, never imputed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts import a02_v3_contract as v3
from scripts import a1_cases, a1_manifest, a1_run, a1_score
from scripts import a1_representation as rep

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs/research/A1-REPORT.md"
ANALYSIS = ROOT / "reports/a1/analysis-v1.json"
RUNS = ROOT / "experiments/a1/.runs"
RETROSPECTIVE_EVIDENCE = (
    Path.home()
    / ".local/share/dynamislm-evidence/RES-774-campaign.5lKrv0/committed/out/outputs.jsonl"
)
ANALYSIS_SCHEMA = "DYNAMISLM_A1_ANALYSIS_V1"


def _cases() -> dict[str, dict[str, Any]]:
    from scripts import a1_retrospective

    cases = {case["case_id"]: case for case in a1_cases.load_manifest()["cases"]}
    cases.update({case["case_id"]: case for case in a1_retrospective.cohort_cases()})
    return cases


def _acceptable(case: dict[str, Any]) -> list[dict[str, Any]]:
    if "acceptable_actions" in case:
        return list(case["acceptable_actions"])
    if "gold" in case:
        return [case["gold"]]
    return [a1_cases.gold_action(case)]


def _gold(case: dict[str, Any]) -> dict[str, Any]:
    if "gold" in case:
        return case["gold"]  # type: ignore[no-any-return]
    return a1_cases.gold_action(case)


def score_arm(arm: str, cases: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    path = a1_run.arm_path(arm, RUNS)
    if not path.is_file():
        return None
    entries = []
    for line in path.read_bytes().split(b"\n"):
        if not line:
            continue
        record = v3.json_object(line.decode())
        record.pop("line_sha256", None)
        entries.append(record)
    rows = []
    for record in entries:
        case = cases.get(record["case_id"])
        if case is None:
            raise ValueError(f"{arm}: unknown case {record['case_id']}")
        request = rep.request_for(
            "D7-probe"
            if record["case_id"].startswith("d7-")
            else "D6-retrospective"
            if record["case_id"].startswith("d6-")
            else "R-op",
            case,
        )
        rows.append(
            a1_score.score_row(
                case=case,
                gold=_gold(case),
                raw=record["raw_output"],
                request=request,
                acceptable=_acceptable(case),
            )
        )
    return {
        "arm": arm,
        "rows": rows,
        "summary": a1_score.arm_summary(rows),
        "distribution": a1_score.output_distribution(rows),
        "generations": len(rows),
    }


def _pair(
    left: dict[str, Any] | None,
    right: dict[str, Any] | None,
    key: str = "acceptable",
) -> dict[str, Any] | None:
    if left is None or right is None:
        return None
    if {row["case_id"] for row in left["rows"]} != {row["case_id"] for row in right["rows"]}:
        return None
    return {
        "left": left["arm"],
        "right": right["arm"],
        "metric": key,
        **a1_score.paired_bootstrap(left["rows"], right["rows"], key),
        "mcnemar": a1_score.mcnemar(left["rows"], right["rows"], key),
    }


def analyse() -> dict[str, Any]:
    manifest = a1_manifest.load_manifest()
    cases = _cases()
    arms: dict[str, Any] = {}
    for condition in manifest["conditions"]:
        scored = score_arm(condition["arm"], cases)
        if scored is not None:
            arms[condition["arm"]] = scored
    planned = [condition["arm"] for condition in manifest["conditions"]]
    missing = [arm for arm in planned if arm not in arms]
    contrasts = {
        "adaptation_op_C1": _pair(arms.get("P-M1-R-op-C1"), arms.get("P-M0-R-op-C1")),
        "adaptation_hist_C1": _pair(arms.get("P-M1-R-hist-C1"), arms.get("P-M0-R-hist-C1")),
        "representation_M1_C1": _pair(arms.get("P-M1-R-hist-C1"), arms.get("P-M1-R-op-C1")),
        "representation_M0_C1": _pair(arms.get("P-M0-R-hist-C1"), arms.get("P-M0-R-op-C1")),
        "decoder_M1_op": _pair(arms.get("P-M1-R-op-C1"), arms.get("P-M1-R-op-N")),
        "decoder_M0_op": _pair(arms.get("P-M0-R-op-C1"), arms.get("P-M0-R-op-N")),
        "interaction_adaptation_representation": _interaction(
            arms, "P-M1-R-hist-C1", "P-M1-R-op-C1", "P-M0-R-hist-C1", "P-M0-R-op-C1"
        ),
        "D1_corrected_system": _pair(arms.get("D1-corrected-system"), arms.get("P-M1-R-op-C1")),
        "D1_corrected_system_hist": _pair(
            arms.get("D1-corrected-system-hist"), arms.get("P-M1-R-hist-C1")
        ),
        "D2_enriched": _pair(arms.get("D2-enriched-objective"), arms.get("P-M1-R-op-C1")),
        "D3_constant_claims": _pair(arms.get("D3-constant-claims"), arms.get("P-M1-R-op-C1")),
        "D4_human_labels": _pair(arms.get("D4-human-labels"), arms.get("P-M1-R-op-C1")),
        "D5_three_shot_M1": _pair(arms.get("D5-three-shot"), arms.get("P-M1-R-op-C1")),
        "D5_three_shot_M0": _pair(arms.get("D5-three-shot-m0"), arms.get("P-M0-R-op-C1")),
        "D6_retrospective_base": _pair(arms.get("D6-M0-C1"), arms.get("D6-M0-N")),
    }
    return {
        "schema": ANALYSIS_SCHEMA,
        "case_manifest_sha256": manifest["case_manifest_sha256"],
        "planned_generations": manifest["planned_generations"],
        "planned_arms": len(planned),
        "completed_arms": len(arms),
        "completed_generations": sum(arm["generations"] for arm in arms.values()),
        "missing_arms": missing,
        "arms": {
            arm: {
                "summary": value["summary"],
                "distribution": value["distribution"],
                "generations": value["generations"],
                "stratified": value["summary"]["strata"],
            }
            for arm, value in arms.items()
        },
        "contrasts": contrasts,
        "hypotheses": _hypotheses(arms, contrasts),
        "baselines": _baselines(),
        "shortcuts": _shortcut_report(arms),
        "retrospective": _retrospective_compare(arms),
    }


def _interaction(arms: dict[str, Any], a: str, b: str, c: str, d: str) -> dict[str, Any] | None:
    """(A-B) - (C-D) over clusters: the adaptation-by-representation interaction."""
    if not all(name in arms for name in (a, b, c, d)):
        return None
    first = _pair(arms[a], arms[b])
    second = _pair(arms[c], arms[d])
    if first is None or second is None:
        return None
    return {
        "form": f"({a} - {b}) - ({c} - {d})",
        "estimate": first["estimate"] - second["estimate"],
        "ci95": [first["ci95"][0] - second["ci95"][1], first["ci95"][1] - second["ci95"][0]],
        "basis": "DIFFERENCE_OF_CLUSTER_PAIRED_CONTRASTS_CONSERVATIVE_INTERVAL",
        "verdict": "INTERACTION_PRESENT"
        if first["ci95"][0] - second["ci95"][1] > 0 or first["ci95"][1] - second["ci95"][0] < 0
        else "NO_CLEAR_INTERACTION",
    }


def _hypotheses(arms: dict[str, Any], contrasts: dict[str, Any]) -> dict[str, Any]:
    """Resolve the registered hypotheses only through their prespecified rules."""
    result: dict[str, Any] = {}

    # H1: representation mismatch contributed, judged on the adapted C1 contrast.
    rep_contrast = contrasts.get("representation_M1_C1")
    if rep_contrast is None:
        result["H1"] = {"status": "NOT_EVALUABLE", "reason": "required arms are absent"}
    else:
        low = rep_contrast["ci95"][0]
        point = rep_contrast["estimate"]
        if low > 0 and point >= a1_score.SUBSTANTIVE_EFFECT:
            status = "SUPPORTED"
        elif rep_contrast["verdict"] == "PRACTICAL_EQUIVALENCE_WITHIN_MARGIN":
            status = "REJECTED_PRACTICAL_EQUIVALENCE"
        elif low > 0:
            status = "DIRECTIONAL_NOT_SUBSTANTIVE"
        else:
            status = "INCONCLUSIVE"
        result["H1"] = {
            "status": status,
            "estimate": point,
            "ci95": rep_contrast["ci95"],
            "rule": "LB > 0 and point >= 0.20",
            "note": "R-hist minus R-op on acceptable intent, adapted model, C1 decoder",
        }

    # H5: constrained decoding fixed structure but not semantics.
    c1 = arms.get("P-M1-R-op-C1")
    native = arms.get("P-M1-R-op-N")
    if c1 is None or native is None:
        result["H5"] = {"status": "NOT_EVALUABLE", "reason": "required arms are absent"}
    else:
        semantic = contrasts.get("decoder_M1_op")
        assert semantic is not None
        structure_gain = (
            c1["summary"]["structured_valid"]["estimate"]
            - native["summary"]["structured_valid"]["estimate"]
        )
        if semantic["ci95"][1] <= 0:
            status = "SUPPORTED_SEMANTIC_NOT_IMPROVED"
        elif semantic["ci95"][0] > 0:
            status = "REJECTED_DECODER_IMPROVED_SEMANTICS"
        else:
            status = "INCONCLUSIVE_SEMANTIC_EFFECT"
        result["H5"] = {
            "status": status,
            "structure_gain": structure_gain,
            "semantic_delta": semantic["estimate"],
            "semantic_ci95": semantic["ci95"],
            "verdict": semantic["verdict"],
        }

    # H2: shortcut evidence. Requires the restricted-input probes, not a generalisation gap.
    probes = {
        variant: arms.get(f"D7-{variant}")
        for variant in ("objective-only", "question-only", "observations-only")
    }
    if any(value is None for value in probes.values()):
        result["H2"] = {"status": "NOT_EVALUABLE", "reason": "shortcut probes are absent"}
    else:
        objective = probes["objective-only"]
        observations_probe = probes["observations-only"]
        ceiling = probes["question-only"]
        assert objective is not None and observations_probe is not None and ceiling is not None
        restricted = max(
            objective["summary"]["exact"]["estimate"],
            observations_probe["summary"]["exact"]["estimate"],
        )
        full = ceiling["summary"]["exact"]["estimate"]
        ratio = restricted / full if full else None
        if ratio is not None and ratio >= 0.80:
            status = "SUPPORTED_RESTRICTED_INPUT_SHORTCUT"
        elif restricted > 0:
            status = "PARTIAL_RESTRICTED_SIGNAL"
        else:
            status = "REJECTED_NO_RESTRICTED_EXACT"
        result["H2"] = {
            "status": status,
            "restricted_exact": restricted,
            "question_only_exact": full,
            "restricted_over_question_ratio": ratio,
            "rule": "restricted exact >= 80% of question-only exact",
            "note": (
                "A generalisation gap alone is not shortcut evidence; these arms remove the "
                "component and hold gold fixed."
            ),
        }
    return result


def _baselines() -> dict[str, Any]:
    from scripts import a1_baselines

    return a1_baselines.run_all()


def _shortcut_report(arms: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for variant in ("objective-only", "question-only", "observations-only"):
        arm = arms.get(f"D7-{variant}")
        if arm is None:
            result[variant] = None
        else:
            result[variant] = {
                "exact": arm["summary"]["exact"],
                "acceptable": arm["summary"]["acceptable"],
                "analysis_class": arm["summary"]["analysis_class"],
                "observation_f1": arm["summary"]["observation_f1"],
                "distribution": arm["distribution"],
                "generations": arm["generations"],
            }
    return result


def _retrospective_compare(arms: dict[str, Any]) -> dict[str, Any]:
    """Compare the M0 retrospective arms with the historical M1 A0.3 result when available."""
    result: dict[str, Any] = {}
    historical = None
    if RETROSPECTIVE_EVIDENCE.is_file():
        historical = {"path": str(RETROSPECTIVE_EVIDENCE), "role": "HISTORICAL_M1_REFERENCE"}
    for decoder in ("N", "C1"):
        arm = arms.get(f"D6-M0-{decoder}")
        if arm is None:
            result[decoder] = None
            continue
        result[decoder] = {
            "generations": arm["generations"],
            "acceptable": arm["summary"]["acceptable"],
            "structured_valid": arm["summary"]["structured_valid"],
            "distribution": arm["distribution"],
            "historical_m1": historical,
            "label": "RETROSPECTIVE_NOT_FINAL_EVIDENCE",
        }
    return result


# --------------------------------------------------------------------------- rendering


def _fmt(value: float | None, digits: int = 3) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}"


def _ci(entry: dict[str, Any] | None) -> str:
    if entry is None or entry.get("ci95") is None:
        return "n/a"
    low, high = entry["ci95"]
    return f"{_fmt(entry['estimate'])} [{_fmt(low)}, {_fmt(high)}]"


def render(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    add = lines.append
    manifest = a1_manifest.load_manifest()
    add("# A1 - scientific failure diagnosis of the step-510 Action model")
    add("")
    add("**Status.** Execution report for RES-832. Inference only; no weights were trained or")
    add("modified. Every number below is computed from committed generations and frozen gold.")
    add("")
    add("## 1. Executed comparison arms")
    add("")
    add(
        f"Planned: **{analysis['planned_arms']} conditions / "
        f"{analysis['planned_generations']} generations**. "
        f"Completed: **{analysis['completed_arms']} conditions / "
        f"{analysis['completed_generations']} generations**."
    )
    add("")
    if analysis["missing_arms"]:
        add("Missing arms are reported, never imputed:")
        add("")
        for arm in analysis["missing_arms"]:
            add(f"- `{arm}` - not executed")
        add("")
    add("| Arm | Role | Generations | Exact | Acceptable | Structured valid |")
    add("| --- | --- | ---: | ---: | ---: | ---: |")
    conditions = {condition["arm"]: condition for condition in manifest["conditions"]}
    for arm, value in analysis["arms"].items():
        role = conditions[arm]["role"]
        summary = value["summary"]
        add(
            f"| `{arm}` | {role} | {value['generations']} | "
            f"{_ci(summary['exact'])} | {_ci(summary['acceptable'])} | "
            f"{_ci(summary['structured_valid'])} |"
        )
    add("")
    add("Estimates are equal-cluster means with 95% percentile cluster-bootstrap intervals.")
    add("")
    add("## 2. Representation effects")
    add("")
    _contrast_table(add, analysis, ("representation_M1_C1", "representation_M0_C1"))
    add("## 3. Untouched versus adapted")
    add("")
    _contrast_table(add, analysis, ("adaptation_op_C1", "adaptation_hist_C1"))
    add("## 4. Native versus constrained decoding")
    add("")
    _contrast_table(add, analysis, ("decoder_M1_op", "decoder_M0_op"))
    add("## 5. Shortcut-learning evidence")
    add("")
    add("| Probe | Generations | Exact | Acceptable | Analysis class | Observation F1 |")
    add("| --- | ---: | ---: | ---: | ---: | ---: |")
    for variant, value in analysis["shortcuts"].items():
        if value is None:
            add(f"| {variant} | 0 | n/a | n/a | n/a | n/a |")
            continue
        add(
            f"| {variant} | {value['generations']} | {_ci(value['exact'])} | "
            f"{_ci(value['acceptable'])} | {_ci(value['analysis_class'])} | "
            f"{_ci(value['observation_f1'])} |"
        )
    add("")
    add("## 6. Counterfactual and compositional findings")
    add("")
    add("Allocation and the per-stratum view of the principal arms:")
    add("")
    add("| Stratum | R-op C1 | R-hist C1 | M0 R-op C1 |")
    add("| --- | ---: | ---: | ---: |")
    principal = ("P-M1-R-op-C1", "P-M1-R-hist-C1", "P-M0-R-op-C1")
    strata = sorted(
        {
            name
            for arm in principal
            if arm in analysis["arms"]
            for name in analysis["arms"][arm]["stratified"]
        }
    )
    for stratum in strata:
        cells = []
        for arm in principal:
            entry = (
                analysis["arms"][arm]["stratified"].get(stratum, {}).get("acceptable")
                if arm in analysis["arms"]
                else None
            )
            cells.append(_ci(entry))
        add(f"| {stratum} | {cells[0]} | {cells[1]} | {cells[2]} |")
    add("")
    add("## 7. Per-field semantic errors")
    add("")
    add("| Arm | Class | Operation | Obs set | Obs F1 | Measure | Relate |")
    add("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for arm, value in analysis["arms"].items():
        summary = value["summary"]
        add(
            f"| `{arm}` | {_fmt(summary['analysis_class']['estimate'])} | "
            f"{_fmt(summary['operation']['estimate'])} | "
            f"{_fmt(summary['observation_set_exact']['estimate'])} | "
            f"{_fmt(summary['observation_f1']['estimate'])} | "
            f"{_fmt(summary['measurement_claim_exact']['estimate'])} | "
            f"{_fmt(summary['relationship_claim_exact']['estimate'])} |"
        )
    add("")
    add("## 8. Effect estimates and uncertainty")
    add("")
    add("All paired contrasts, including every diagnostic intervention:")
    add("")
    for name, contrast in analysis["contrasts"].items():
        if contrast is None:
            add(f"- `{name}` - not estimable (missing arm)")
            continue
        if "left" not in contrast:
            add(
                f"- `{name}` - {contrast['verdict']}, estimate "
                f"{_fmt(contrast['estimate'])}, interval {contrast['ci95']}"
            )
            continue
        add(
            f"- `{name}` ({contrast['left']} vs {contrast['right']}): "
            f"{_fmt(contrast['estimate'])} "
            f"[{_fmt(contrast['ci95'][0])}, {_fmt(contrast['ci95'][1])}] - "
            f"**{contrast['verdict']}**; descriptive McNemar "
            f"{contrast['mcnemar']['left_only']} vs {contrast['mcnemar']['right_only']} "
            f"(p = {_fmt(contrast['mcnemar']['p_value'])}, non-confirmatory)."
        )
    add("")
    add(
        "Items inside a cluster share their scenario, so item-level McNemar is descriptive "
        "only. Equivalence is claimed only inside the prespecified "
        f"±{a1_score.EQUIVALENCE_MARGIN} margin."
    )
    add("")
    add("## 9. Hypothesis status")
    add("")
    for name, value in analysis["hypotheses"].items():
        add(f"- **{name}: {value['status']}** - {v3.canonical(value)}")
    add("")
    add("## 10. CPU baselines")
    add("")
    baselines = analysis["baselines"]
    if "rule_based" not in baselines:
        add("CPU baselines were skipped in this run.")
        add("")
        return "\n".join(lines) + "\n"
    rule = baselines["rule_based"]
    add(
        f"Rule-based: exact {_ci(rule['exact'])}, acceptable {_ci(rule['acceptable'])}, "
        f"analysis class {_ci(rule['analysis_class'])}."
    )
    add("")
    add("| Restricted input | Exact | Acceptable |")
    add("| --- | ---: | ---: |")
    for key, value in baselines["restricted_input"].items():
        add(f"| {key} | {_ci(value['exact'])} | {_ci(value['acceptable'])} |")
    add("")
    conventional = baselines["conventional"]
    if conventional.get("available"):
        add(
            f"Conventional per-field TF-IDF logistic regression (fields: "
            f"{', '.join(conventional['fields'])}): exact "
            f"{_ci(conventional['summary']['exact'])}, analysis class "
            f"{_ci(conventional['summary']['analysis_class'])}."
        )
    else:
        add(f"Conventional baseline unavailable: {conventional.get('reason')}.")
    masked = baselines.get("conventional_identity_masked", {})
    if masked.get("available"):
        add(
            f"Conventional baseline with measurement identity masked: exact "
            f"{_ci(masked['summary']['exact'])}, analysis class "
            f"{_ci(masked['summary']['analysis_class'])}."
        )
    add("")
    return "\n".join(lines) + "\n"


def _contrast_table(add: Any, analysis: dict[str, Any], names: tuple[str, ...]) -> None:
    add("| Contrast | Estimate | 95% interval | Verdict |")
    add("| --- | ---: | --- | --- |")
    for name in names:
        contrast = analysis["contrasts"].get(name)
        if contrast is None:
            add(f"| `{name}` | n/a | n/a | not estimable |")
            continue
        add(
            f"| `{name}` | {_fmt(contrast['estimate'])} | "
            f"[{_fmt(contrast['ci95'][0])}, {_fmt(contrast['ci95'][1])}] | "
            f"{contrast['verdict']} |"
        )
    add("")


def write(analysis: dict[str, Any]) -> Path:
    ANALYSIS.parent.mkdir(parents=True, exist_ok=True)
    ANALYSIS.write_text(v3.canonical(analysis) + "\n", encoding="utf-8")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(render(analysis), encoding="utf-8")
    return REPORT


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-baselines", action="store_true", help="skip the CPU baselines")
    args = parser.parse_args()
    if args.no_baselines:
        global _baselines
        _baselines = lambda: {"skipped": True}  # noqa: E731
    analysis = analyse()
    path = write(analysis)
    print(
        json.dumps(
            {
                "report": str(path),
                "completed_arms": analysis["completed_arms"],
                "completed_generations": analysis["completed_generations"],
                "missing_arms": analysis["missing_arms"],
                "hypotheses": {k: v["status"] for k, v in analysis["hypotheses"].items()},
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
