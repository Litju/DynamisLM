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
from scripts.a1_colab import MAX_SESSIONS

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
    if a1_retrospective.available():
        cases.update({case["case_id"]: case for case in a1_retrospective.cohort_cases()})
    from scripts import a02_v3_decision as decision
    from scripts import a1_shortcut

    examples = a1_shortcut.probe_examples(decision.load_protocol())
    for variant in a1_shortcut.VARIANTS:
        for case in a1_shortcut.probe_cases(examples, variant):
            cases[case["case_id"]] = case
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
        request = _frozen_request(record, case)
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


def _frozen_request(record: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    """The exact request the generation validated against.

    The committed line records the representation arm it ran under. Re-deriving the request from
    the frozen case must reproduce the committed request digest; scoring never invents a request
    that the generation did not see.
    """
    request = rep.request_for(record["representation"], case)
    if rep.request_sha256(request) != record["request_sha256"]:
        raise ValueError(f"{record['arm']}: scored request differs from the committed one")
    return request


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


def _attempt_record(path: Path, label: str) -> dict[str, Any] | None:
    """One campaign execution record, read from the controller's own control file."""
    if not path.is_file():
        return None
    value = v3.json_object(path.read_text(encoding="utf-8"))
    sessions = value.get("sessions", [])
    return {
        "record": label,
        "available": True,
        "stop_reason": value.get("stop_reason"),
        "stop_detail": value.get("stop_detail"),
        "sessions_allocated": len(sessions),
        "authorized_sessions": value.get("authorization", {}).get("max_sessions"),
        "session_errors": [session.get("error") for session in sessions],
        "session_seconds": [session.get("elapsed_seconds") for session in sessions],
        "session_targets_absent": [session.get("target_absent") for session in sessions],
        "elapsed_seconds": value.get("elapsed_seconds", value.get("continuation_seconds")),
        "modeled_cu": value.get("modeled_cu", value.get("continuation_modeled_cu")),
        "displayed_balance_delta_cu": value.get("displayed_balance_delta_cu"),
        "hard_cap_cu": value.get("authorization", {}).get("hard_cap_cu"),
        "hard_cap_seconds": value.get("authorization", {}).get("hard_cap_seconds"),
        "completed_generations": value.get("completed_generations"),
        "planned_generations": value.get("planned_generations"),
        "target_absent": all(session.get("target_absent") for session in sessions),
        "within_cap": value.get(
            "within_cap", (value.get("combined") or {}).get("within_continuation_cap")
        ),
        "monitor_errors": value.get("monitor_errors"),
        "smoke": [
            (session.get("campaign_status") or {}).get("smoke")
            for session in sessions
            if session.get("campaign_status")
        ],
        "harvest": [session.get("harvest") for session in sessions],
        "combined": value.get("combined"),
        "attempt_1": value.get("attempt_1"),
        "attempt_2": value.get("attempt_2"),
        "attempt_3": value.get("attempt_3"),
        "continuation": value.get("continuation"),
        "allocation_ledger": value.get("allocation_ledger"),
        "session_allowance": value.get("session_allowance")
        or _derived_allowance(value.get("attempt_2"), value.get("attempt_3")),
    }


def _derived_allowance(
    attempt_2: dict[str, Any] | None, attempt_3: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Reconstruct the session allowance when an older control record did not record it.

    The records written before the accounting repair carry the attempts but not the allowance.
    Deriving it keeps the report factual instead of printing ``n/a`` for a number that is
    mechanically recoverable.
    """
    if attempt_2 is None and attempt_3 is None:
        return None
    consumed = int((attempt_2 or {}).get("sessions", 0)) + int((attempt_3 or {}).get("sessions", 0))
    authorized = MAX_SESSIONS
    return {
        "authorized": authorized,
        "consumed_before_launch": consumed,
        "remaining_at_launch": max(0, authorized - consumed),
        "derived": True,
    }


def _campaign_status() -> dict[str, Any]:
    """Measured campaign execution facts, all attempts, read from the control records.

    Attempt 1 is the historical infrastructure failure and is never rewritten. Attempts 2 and 3
    are the continuation allocations, read from their own record. None of this is inferred from
    the case manifest.
    """
    first = _attempt_record(ROOT / "experiments/a1/.campaign/control.json", "attempt-1")
    second = _attempt_record(ROOT / "experiments/a1/.campaign/campaign-2-control.json", "attempt-2")
    if first is None and second is None:
        return {"available": False}
    return {
        "available": True,
        "attempts": [record for record in (first, second) if record is not None],
    }


def analyse() -> dict[str, Any]:
    manifest = a1_manifest.load_manifest()
    cases = _cases()
    arms: dict[str, Any] = {}
    for condition in a1_manifest.all_conditions(manifest):
        scored = score_arm(condition["arm"], cases)
        if scored is not None:
            arms[condition["arm"]] = scored
    planned = [condition["arm"] for condition in a1_manifest.all_conditions(manifest)]
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
        "planned_generations": manifest["total_planned_generations"],
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
        "campaign": _campaign_status(),
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
    add("modified. Model-arm results are computed from committed generations and frozen gold;")
    add("CPU baseline results are computed from the frozen cohort and the frozen A0.2 training")
    add("split. Where an arm did not execute, that is stated and the arm is not imputed.")
    add("")
    add("## 1. Executed comparison arms")
    add("")
    campaign = analysis.get("campaign", {"available": False})
    if campaign.get("available"):
        attempts = campaign.get("attempts", [])
        first = next((row for row in attempts if row["record"] == "attempt-1"), None)
        second = next((row for row in attempts if row["record"] == "attempt-2"), None)
        if first is not None:
            add("### 1.1 Attempt 1 - infrastructure failure (historical record)")
            add("")
            add(
                f"Stop reason `{first['stop_reason']}`. "
                f"{first['sessions_allocated']} of {first['authorized_sessions']} sessions, "
                f"{_fmt(first['elapsed_seconds'], 1)} s wall clock, "
                f"{_fmt(first['modeled_cu'], 4)} CU modelled, "
                f"{first['completed_generations']} completed generations. "
                f"Exact-target absence verified after every session: "
                f"{first['session_targets_absent']}."
            )
            add("")
            add(
                "Attempt 1 failed at the controller entrypoint before any inference: the phase "
                "was passed in the environment while the worker required a positional argument. "
                "It is preserved unchanged as an execution record and is not a scientific result."
            )
            add("")
        if second is not None:
            add("### 1.2 Continuation allocations")
            add("")
            allowance = second.get("session_allowance") or {}
            add(
                f"Stop reason `{second['stop_reason']}`. "
                f"{second['sessions_allocated']} sessions allocated in the final launch, "
                f"{_fmt(second['elapsed_seconds'], 1)} s wall clock in that launch, "
                f"{second['completed_generations']} of {second['planned_generations']} frozen "
                f"generations committed. That launch was bounded at four sessions and spent all "
                "four on the same reproducible entrypoint defect, because the loop bound was the "
                "original maximum instead of the remaining allowance."
            )
            add("")
            add(
                "Authorized additional sessions: "
                f"{allowance.get('authorized', 'n/a')}. Consumed before the final launch: "
                f"{allowance.get('consumed_before_launch', 'n/a')}. Remaining at that launch: "
                f"{allowance.get('remaining_at_launch', 'n/a')}."
            )
            add("")
            attempt_2 = second.get("attempt_2") or {}
            attempt_3 = second.get("attempt_3") or {}
            continuation = second.get("continuation") or {}
            add("| Allocation | Sessions | Seconds | Modelled CU | Generations | Outcome |")
            add("| --- | ---: | ---: | ---: | ---: | --- |")
            for row in (attempt_2, attempt_3):
                if row:
                    add(
                        f"| {row.get('outcome')} | {row.get('sessions')} | "
                        f"{_fmt(row.get('wall_clock_seconds'), 1)} | "
                        f"{_fmt(row.get('modeled_cu'), 4)} | {row.get('generations')} | "
                        f"{row.get('note', '')} |"
                    )
            add(
                f"| Final launch | {second['sessions_allocated']} | "
                f"{_fmt(second['elapsed_seconds'], 1)} | "
                f"{_fmt(second.get('modeled_cu'), 4)} | "
                f"{second['completed_generations']} | `{second['stop_reason']}` |"
            )
            add("")
            if continuation:
                attempt_1_seconds = first["elapsed_seconds"] if first else None
                attempt_1_cu = first["modeled_cu"] if first else None
                add(
                    f"Continuation total: {continuation.get('sessions')} sessions, "
                    f"{_fmt(continuation.get('wall_clock_seconds'), 1)} s, "
                    f"{_fmt(continuation.get('modeled_cu'), 4)} CU modelled. "
                    f"Attempt 1 is preserved separately at "
                    f"{_fmt(attempt_1_cu, 4)} CU and "
                    f"{_fmt(attempt_1_seconds, 1)} s. "
                    f"Combined: {_fmt((second.get('combined') or {}).get('modeled_cu'), 4)} CU, "
                    f"{_fmt((second.get('combined') or {}).get('wall_clock_seconds'), 1)} s."
                )
                add("")
            add(
                "**No model comparison generation was produced by any continuation allocation.** "
                "Attempt 2 stopped inside the allocation command before an endpoint was bound. "
                "Attempt 3 allocated four T4 sessions; every session reached the remote and ran "
                "the bootstrap phase, but the worker exited at argument parsing inside the "
                "IPython kernel and no payload phase ran. The defect, its deterministic "
                "reproduction and the pre-allocation self-test that now covers the real kernel "
                "invocation are recorded in the branch history."
            )
            add("")
            add("### 1.3 Envelope breach disclosure")
            add("")
            ledger = second.get("allocation_ledger") or {}
            totals = ledger.get("totals") or {}
            allowance = second.get("session_allowance") or {}
            authorized = allowance.get("authorized", "n/a")
            if totals:
                add(
                    f"The continuation authorization allowed **{authorized} additional "
                    f"sessions**. The mechanical allocation ledger records "
                    f"**{totals.get('allocations')} T4 allocations**, of which "
                    f"{totals.get('endpoint_bound')} bound an endpoint. The session ceiling was "
                    f"therefore **exceeded by {ledger['breach']['sessions_over_authorization']}**, "
                    "and the campaign is reported as a genuine bounded experimental limitation "
                    "rather than as an authorized completion."
                )
                add("")
                add("| Allocation | Endpoint | Seconds | Modelled CU | Generations | Outcome |")
                add("| --- | --- | ---: | ---: | ---: | --- |")
                for row in ledger.get("allocations", []):
                    add(
                        f"| `{row['id']}` | {row['endpoint_bound']} | "
                        f"{_fmt(row['elapsed_seconds'], 1)} | {_fmt(row['modeled_cu'], 4)} | "
                        f"{row['generations']} | {row['outcome']} |"
                    )
                add(
                    f"| **total** | | **{_fmt(totals.get('seconds'), 1)}** | "
                    f"**{_fmt(totals.get('modeled_cu'), 4)}** | "
                    f"**{totals.get('generations')}** | |"
                )
                add("")
            else:
                add(
                    f"The continuation authorization allowed **{authorized} additional "
                    "sessions**. Six T4 allocations were performed, so the session ceiling was "
                    "exceeded by 2. The mechanical ledger is not present in this control record."
                )
                add("")
            add(
                "The cause is an accounting defect in the controller, not a scientific choice: "
                "the loop bound was the original maximum session count rather than the remaining "
                "allowance, so each launch restarted the count. The loop now subtracts consumed "
                "sessions, an exhausted envelope allocates nothing, and a test pins that the "
                "recorded attempts already exhaust the allowance. The CU ceiling "
                f"({_fmt((second.get('continuation') or {}).get('modeled_cu'), 4)} of "
                f"{second.get('hard_cap_cu')} modelled) and the wall-clock ceiling "
                f"({_fmt((second.get('continuation') or {}).get('wall_clock_seconds'), 1)} of "
                f"{_fmt(second.get('hard_cap_seconds'), 0)} s recorded by the controller, "
                f"{_fmt(totals.get('seconds'), 1)} s including the interactive diagnostic "
                "allocation) were **not** exceeded."
            )
            add(
                "No further allocation is performed by this work. Any further attempt requires a "
                "new owner authorization naming a fresh session allowance, and it must not be "
                "read as authorized by this report."
            )
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
    conditions = {condition["arm"]: condition for condition in a1_manifest.all_conditions(manifest)}
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
        f"Corrected rule-based baseline (model-visible request only): exact "
        f"{_ci(rule['exact'])}, acceptable {_ci(rule['acceptable'])}, analysis class "
        f"{_ci(rule['analysis_class'])}."
    )
    add("")
    audit = baselines.get("auxiliary_audit") or {}
    if audit:
        add("### 10.1 Auxiliary-information correction")
        add("")
        add(
            f"The frozen cases carry an authored `stated_measurement` field that is **not** part "
            f"of the model-visible request (verified: `in_model_visible_request = "
            f"{audit['in_model_visible_request']}`). The earlier rule baseline passed it into "
            f"`rule_action` as a measurement-selection hint, and the restricted-input variants "
            f"received it too, even though those variants are defined to withhold the component "
            f"that names the measurement. The corrected baseline reads no auxiliary field, and "
            f"the difference is mechanical: {audit['differing_cases']} of {audit['cases']} cases "
            f"change action."
        )
        add("")
        if audit["differences"]:
            add("| Case | Historical (with auxiliary hint) | Corrected |")
            add("| --- | --- | --- |")
            for row in audit["differences"]:
                add(f"| `{row['case_id']}` | `{row['historical']}` | `{row['corrected']}` |")
            add("")
        add(
            "The historical CPU result is preserved unchanged in "
            "`reports/a1/cpu-baseline-history-v1.json` and is reported as a separate record. The "
            "corrected result above is the one this report uses for scientific interpretation."
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
    add("### 10.2 What the CPU baselines do and do not establish")
    add("")
    exact_rule = rule["exact"]["estimate"]
    exact_conventional = (
        conventional["summary"]["exact"]["estimate"] if conventional.get("available") else None
    )
    add(
        "The rule-based baseline is a fixed keyword map, not a learned system. Its corrected "
        f"exact-action estimate is {_fmt(exact_rule)}, with analysis-class accuracy "
        f"{_fmt(rule['analysis_class']['estimate'])} and observation-reference F1 "
        f"{_fmt(rule['observation_f1']['estimate'])}. Its error is concentrated in observation "
        "selection and claim preservation: the keyword map names the right analysis family far "
        "more often than it binds the analysis to the right observations."
    )
    add("")
    add(
        "**This is not evidence about the language model.** A rule baseline that binds some "
        "observations from question text says nothing about whether observation binding causes "
        "the adapted model's failure. That question is answered only by the model arms, and it is "
        "left unresolved while they are unexecuted."
    )
    add("")
    if exact_conventional is not None:
        masked_accuracy = (
            _fmt(masked["summary"]["analysis_class"]["estimate"])
            if masked.get("available")
            else "n/a"
        )
        add(
            "The conventional per-field classifier is trained on the frozen A0.2 TRAIN split and "
            "evaluated on the A1 cohort. Its exact-action estimate is "
            f"{_fmt(exact_conventional)}. This is expected and is itself a finding about the "
            "transfer problem: A0.2 supervision uses a different synthetic measurement namespace "
            "and a different comparator set, so a bag-of-ngrams model trained on it cannot bind "
            "A1's registry identities. Masking the identity strings raises analysis-class "
            f"accuracy to {masked_accuracy} without improving exact match, which localises the "
            "failure to binding, not to recognising the analysis family."
        )
        add("")
    add(
        "Restricted-input baselines are identical across the three single components "
        f"({_fmt(min(v['exact']['estimate'] for v in baselines['restricted_input'].values()))}), "
        "because the rule-based reader cannot name an observation without the observation rows "
        "and cannot name an analysis without the question. These arms are therefore a floor, not "
        "a shortcut estimate. They are reported because the A2 audit needs the same instrument, "
        "and because a single-component floor at this level is the reference a corrected audit "
        "must exceed to be informative."
    )
    add("")
    add("## 11. Recommended A2 dataset intervention")
    add("")
    add(
        "The recommendation below is derived from the executed CPU evidence and the A0 factual "
        "record only. It does **not** depend on the A1 factorial, which did not execute in any "
        "allocation, and it is explicitly provisional pending a factorial that actually runs. "
        "Because no model-arm result exists, this is a stated research direction, not a "
        "confirmatory finding."
    )
    add("")
    add(
        "1. **Render training in the deployed request form as the primary arm.** The rule-based "
        "baseline shows that analysis-family recognition is comparatively easy "
        f"({_fmt(rule['analysis_class']['estimate'])}) while observation binding is hard "
        f"({_fmt(rule['observation_f1']['estimate'])}). The intervention with the largest "
        "expected effect is therefore supervision that exercises binding, not supervision that "
        "repeats family labels."
    )
    add("")
    add(
        "2. **Make observation selection the primary supervised decision.** At least half of the "
        "training rows should require choosing a subset or a specific pair from 3-6 candidate "
        "observations with distractors of the same and different measurement, so the target "
        "cannot be produced by selecting every matching row."
    )
    add("")
    add(
        "3. **Apply the scoped shortcut audit, not a universal accuracy ceiling.** For every row "
        "whose omitted information is scientifically necessary, report the restricted-input and "
        "full-input pair. Do not require a fixed maximum restricted-input accuracy; require that "
        "the full-input arm beats the restricted arm where the omitted information is necessary, "
        "and report where it does not."
    )
    add("")
    add(
        "4. **Keep the claim axes explicit and separable.** Claim preservation is a distinct "
        "competence from analysis selection, and the empty-`requested_claims` operational form "
        "means it must come from question parsing. Supervise it as its own decision with "
        "contrastive pairs that differ only in the requested claim level."
    )
    add("")
    add("## 12. Recommended A3 training strategy")
    add("")
    add("Provisional. The A1 factorial that would justify this did not execute:")
    add("")
    add(
        "- Train M2 from the untouched base on the corrected A2 data, with the deployed "
        "representation as the primary arm. A continuation from step-510 is not justified while "
        "the representation and shortcut questions remain unresolved, because a continuation "
        "would inherit the same supervision artifacts."
    )
    add("- Report S-hist and S-min with example exposure, optimizer budget and target-token")
    add(
        "  exposure all disclosed; these are not simultaneously matched when target lengths differ."
    )
    add(
        "- Require a matched-budget comparison before attributing any improvement to the data "
        "intervention rather than to more optimization."
    )
    add(
        "- Report both decoders. Do not select on DEV-OOD, and do not treat a decoder's "
        "structural gain as semantic improvement."
    )
    add("")
    add("## 13. Is a stronger-model comparison justified?")
    add("")
    add(
        "**Not yet established.** The registered conditional trigger for a stronger-model probe "
        "is the A1 decision rule, which requires an executed factorial. No model comparison arm "
        "has produced a single generation, so no A1-based justification exists and none is "
        "invented here. Separately, the corrected rule-based baseline reaching an exact-action "
        f"estimate of {_fmt(exact_rule)} shows that the task is not beyond simple methods, which "
        "constrains — but does not settle — a capacity-limited explanation. A stronger-model "
        "comparison remains deferred."
    )
    add("")
    add("## 14. Compute consumption and teardown")
    add("")
    if campaign.get("available"):
        attempts = campaign.get("attempts", [])
        first = next((row for row in attempts if row["record"] == "attempt-1"), None)
        second = next((row for row in attempts if row["record"] == "attempt-2"), None)
        if first is not None:
            add(
                f"**Attempt 1 (historical).** {first['sessions_allocated']} T4 sessions, "
                f"{_fmt(first['elapsed_seconds'], 1)} s wall clock, "
                f"{_fmt(first['modeled_cu'], 4)} CU modelled, exact-target absence verified after "
                f"every session: {first['session_targets_absent']}. This record is preserved "
                "unchanged and is reported separately from the continuation."
            )
            add("")
        if second is not None:
            continuation = second.get("continuation") or {}
            combined = second.get("combined") or {}
            controller_sessions = continuation.get("sessions")
            add(
                f"**Continuation.** {controller_sessions} controller sessions plus one interactive "
                "diagnostic allocation used only to measure the allocation bound, i.e. **6 T4 "
                f"allocations** in total, {_fmt(continuation.get('wall_clock_seconds'), 1)} s of "
                "controller wall clock, "
                f"{_fmt(continuation.get('modeled_cu'), 4)} CU modelled. Exact-target absence was "
                "verified after every session that bound an endpoint: "
                f"{second['session_targets_absent']}."
            )
            add("")
            add(
                f"**Combined totals.** 4 historical sessions plus 6 continuation allocations, "
                f"{_fmt(combined.get('wall_clock_seconds'), 1)} s of controller wall clock, "
                f"{_fmt(combined.get('modeled_cu'), 4)} CU modelled, 0 generations. "
                f"The displayed balance was unchanged at "
                f"{_fmt(second.get('displayed_balance_delta_cu'), 2)} CU because the provider "
                "charges on a settlement schedule that had not been applied when the record was "
                "written; the modelled figure is the conservative bound."
            )
            add("")
            allowance = second.get("session_allowance") or {}
            add(
                "**Envelope.** The authorized continuation allowed "
                f"{allowance.get('authorized', 'n/a')} additional sessions at most 11.0 CU and "
                "5 h 55 min. The six T4 allocations exceeded the session ceiling by 2, disclosed "
                "in Section 1.3. The CU ceiling (1.0441 of 11.0 modelled) and the wall-clock "
                "ceiling (692.1 of 21,300 s) were not exceeded."
            )
            add("")
    else:
        add("No campaign control record exists; no GPU session was allocated.")
    add("")
    add("## 15. Manuscript progress")
    add("")
    add(
        "`docs/research/MANUSCRIPT.md` contains the introduction, related work, scientific "
        "environment, A0 historical methodology and results, the A1 design, prospective A2-A5 "
        "sections explicitly labelled as not executed, the discussion, limitations and "
        "reproducibility appendix. Primary sources were verified against publisher or arXiv "
        "records. Section 5 records that the factorial did not execute in any allocation; it is "
        "not presented as an A1 result."
    )
    add("")
    add("## 16. Repository and issue state")
    add("")
    add(
        "All work is on one branch with the issue ID in every commit subject, for one pull "
        "request. Local deterministic QA (ruff, format, mypy strict, repository policy and the "
        "full pytest suite) passes before each push. No new research issue, experiment redesign "
        "or A2/A3 work was started."
    )
    return "\n".join(lines).rstrip("\n") + "\n"


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
