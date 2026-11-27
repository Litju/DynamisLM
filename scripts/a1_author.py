"""Author the frozen A1 cohort (48 cases in 24 contrastive clusters) into canonical JSON.

This is the authoring tool, not a runtime dependency. It writes
``experiments/a1/cases-v1.json``; the committed JSON is the scientific authority and
``scripts.a1_cases.load_manifest`` validates it. Regenerating from this file must reproduce
identical bytes.

Authoring rules that the manifest validator re-derives mechanically:

* executable and claim-preservation intent references two observations of one measurement with
  identical device and protocol, so the request is comparable;
* the operation always comes from ``a02_v3_contract.operation_for``, never from this file;
* no case reuses an A0.2 or RES-774 question, measurement range, template or phrasing;
* every quantitative observation is synthetic and fictional.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

OUTPUT = ROOT / "experiments/a1/cases-v1.json"
SCHEMA = "DYNAMISLM_A1_CASE_MANIFEST_V1"
ABS = "SCALAR_ABSOLUTE_CHANGE"
NONE = "NONE"
NUM = "NUMERICAL_CHANGE"
DESC = "DESCRIPTIVE_CHANGE"
CAUSAL = "CAUSAL_EVIDENCE"
PRACTICAL = "PRACTICAL_OR_DECISION_MEANINGFULNESS"

JUMP = "jump-height"
SPRINT = "sprint-time"
FORCE = "peak-force"
DIST = "session-distance"
AEROBIC = "aerobic-speed"
NORDIC = "nordic-force"

DEVICE = {
    JUMP: "force-platform",
    FORCE: "force-platform",
    SPRINT: "timing-gates",
    DIST: "gps-unit",
    AEROBIC: "instrumented-treadmill",
    NORDIC: "nordic-load-cell-frame",
}
PROTOCOL = {
    JUMP: "cmj-standard",
    FORCE: "imtp-standard",
    SPRINT: "sprint-standard",
    DIST: "gps-standard",
    AEROBIC: "aerobic-standard",
    NORDIC: "nordic-standard",
}
UNIT = {
    JUMP: "m",
    FORCE: "N",
    SPRINT: "s",
    DIST: "m",
    AEROBIC: "m/s",
    NORDIC: "N",
}


def obs(measurement: str, value: float, day: int) -> dict[str, Any]:
    return {
        "measurement": measurement,
        "unit": UNIT[measurement],
        "value": value,
        "protocol": PROTOCOL[measurement],
        "device": DEVICE[measurement],
        "day": day,
    }


def case(
    case_id: str,
    cluster: str,
    contrast: str,
    stratum: str,
    family: str,
    question: str,
    observations: list[dict[str, Any]],
    analysis: str,
    referenced: list[int],
    claims: dict[str, list[str]],
    stated: str | None,
    novel: bool = False,
    subset_selection: bool = False,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "cluster": cluster,
        "contrast": contrast,
        "stratum": stratum,
        "family": family,
        "question": question,
        "observations": observations,
        "stated_measurement": stated,
        "novel_phrasing": novel,
        "subset_selection": subset_selection,
        "intent": {
            "analysis_class": analysis,
            "observations": referenced,
            "claims": {
                "measurement": list(claims["measurement"]),
                "relationship": list(claims["relationship"]),
            },
        },
    }


def cases() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    # C01-C04: question contrast across fixed observations; every case executable.
    rows += [
        case(
            "a1-c01a",
            "a1-c01",
            "QUESTION",
            "EXECUTABLE",
            "absolute-change-subset",
            "By how many metres did the countermovement jump height move between the opening "
            "test and the most recent one?",
            [obs(JUMP, 0.302, 0), obs(JUMP, 0.327, 14), obs(JUMP, 0.356, 28)],
            ABS,
            [1, 3],
            {"measurement": [NUM], "relationship": [DESC]},
            JUMP,
            subset_selection=True,
        ),
        case(
            "a1-c01b",
            "a1-c01",
            "QUESTION",
            "EXECUTABLE",
            "absolute-change-subset",
            "By how many metres did the countermovement jump height move between the first test "
            "and the follow-up two weeks later?",
            [obs(JUMP, 0.302, 0), obs(JUMP, 0.327, 14), obs(JUMP, 0.356, 28)],
            ABS,
            [1, 2],
            {"measurement": [NUM], "relationship": [DESC]},
            JUMP,
            novel=True,
            subset_selection=True,
        ),
        case(
            "a1-c02a",
            "a1-c02",
            "QUESTION",
            "EXECUTABLE",
            "absolute-change-subset",
            "Report the change in 10 m sprint time from the earliest session to the latest.",
            [
                obs(SPRINT, 1.804, 0),
                obs(SPRINT, 1.771, 7),
                obs(SPRINT, 1.735, 14),
                obs(SPRINT, 1.702, 21),
            ],
            ABS,
            [1, 4],
            {"measurement": [NUM], "relationship": [DESC]},
            SPRINT,
            novel=True,
            subset_selection=True,
        ),
        case(
            "a1-c02b",
            "a1-c02",
            "QUESTION",
            "EXECUTABLE",
            "absolute-change-subset",
            "Give the difference in 10 m sprint time between the two middle testing sessions.",
            [
                obs(SPRINT, 1.804, 0),
                obs(SPRINT, 1.771, 7),
                obs(SPRINT, 1.735, 14),
                obs(SPRINT, 1.702, 21),
            ],
            ABS,
            [2, 3],
            {"measurement": [NUM], "relationship": [DESC]},
            SPRINT,
            subset_selection=True,
        ),
        case(
            "a1-c03a",
            "a1-c03",
            "QUESTION",
            "EXECUTABLE",
            "absolute-change-subset",
            "How much did isometric peak force change between the first and the last force "
            "testing day?",
            [
                obs(FORCE, 2410.0, 0),
                obs(NORDIC, 341.0, 3),
                obs(FORCE, 2545.0, 7),
                obs(NORDIC, 367.0, 10),
                obs(FORCE, 2680.0, 14),
            ],
            ABS,
            [1, 5],
            {"measurement": [NUM], "relationship": [DESC]},
            FORCE,
            novel=True,
            subset_selection=True,
        ),
        case(
            "a1-c03b",
            "a1-c03",
            "QUESTION",
            "EXECUTABLE",
            "absolute-change-subset",
            "How much did isometric peak force change between the first two force testing days?",
            [
                obs(FORCE, 2410.0, 0),
                obs(NORDIC, 341.0, 3),
                obs(FORCE, 2545.0, 7),
                obs(NORDIC, 367.0, 10),
                obs(FORCE, 2680.0, 14),
            ],
            ABS,
            [1, 3],
            {"measurement": [NUM], "relationship": [DESC]},
            FORCE,
            subset_selection=True,
        ),
        case(
            "a1-c04a",
            "a1-c04",
            "QUESTION",
            "EXECUTABLE",
            "absolute-change-subset",
            "What was the difference in session total distance between the first session and the "
            "fourth session?",
            [
                obs(DIST, 6240.0, 0),
                obs(DIST, 6890.0, 7),
                obs(DIST, 7310.0, 14),
                obs(DIST, 7840.0, 21),
                obs(DIST, 8250.0, 28),
            ],
            ABS,
            [1, 4],
            {"measurement": [NUM], "relationship": [DESC]},
            DIST,
            subset_selection=True,
        ),
        case(
            "a1-c04b",
            "a1-c04",
            "QUESTION",
            "EXECUTABLE",
            "absolute-change-subset",
            "What was the difference in session total distance between the second session and the "
            "third session?",
            [
                obs(DIST, 6240.0, 0),
                obs(DIST, 6890.0, 7),
                obs(DIST, 7310.0, 14),
                obs(DIST, 7840.0, 21),
                obs(DIST, 8250.0, 28),
            ],
            ABS,
            [2, 3],
            {"measurement": [NUM], "relationship": [DESC]},
            DIST,
            novel=True,
            subset_selection=True,
        ),
    ]

    # C05-C08: observation contrast with a fixed question; every case executable.
    rows += [
        case(
            "a1-c05a",
            "a1-c05",
            "OBSERVATIONS",
            "EXECUTABLE",
            "observation-contrast",
            "What is the change in Nordic eccentric peak force between the first measurement and "
            "the latest measurement?",
            [obs(NORDIC, 292.0, 0), obs(NORDIC, 318.0, 10), obs(NORDIC, 341.0, 20)],
            ABS,
            [1, 3],
            {"measurement": [NUM], "relationship": [DESC]},
            NORDIC,
        ),
        case(
            "a1-c05b",
            "a1-c05",
            "OBSERVATIONS",
            "EXECUTABLE",
            "observation-contrast",
            "What is the change in Nordic eccentric peak force between the first measurement and "
            "the latest measurement?",
            [obs(NORDIC, 392.0, 0), obs(NORDIC, 415.0, 10)],
            ABS,
            [1, 2],
            {"measurement": [NUM], "relationship": [DESC]},
            NORDIC,
        ),
        case(
            "a1-c06a",
            "a1-c06",
            "OBSERVATIONS",
            "EXECUTABLE",
            "observation-contrast",
            "Report the change in maximal aerobic speed between the first and the last test.",
            [
                obs(AEROBIC, 4.32, 0),
                obs(AEROBIC, 4.48, 7),
                obs(AEROBIC, 4.61, 14),
                obs(AEROBIC, 4.75, 21),
            ],
            ABS,
            [1, 4],
            {"measurement": [NUM], "relationship": [DESC]},
            AEROBIC,
            novel=True,
        ),
        case(
            "a1-c06b",
            "a1-c06",
            "OBSERVATIONS",
            "EXECUTABLE",
            "observation-contrast",
            "Report the change in maximal aerobic speed between the first and the last test.",
            [obs(AEROBIC, 4.88, 0), obs(AEROBIC, 4.96, 7)],
            ABS,
            [1, 2],
            {"measurement": [NUM], "relationship": [DESC]},
            AEROBIC,
        ),
        case(
            "a1-c07a",
            "a1-c07",
            "OBSERVATIONS",
            "EXECUTABLE",
            "observation-contrast",
            "How much did countermovement jump height change between the opening and closing jump "
            "tests?",
            [obs(JUMP, 0.318, 0), obs(NORDIC, 341.0, 5), obs(JUMP, 0.341, 14)],
            ABS,
            [1, 3],
            {"measurement": [NUM], "relationship": [DESC]},
            JUMP,
        ),
        case(
            "a1-c07b",
            "a1-c07",
            "OBSERVATIONS",
            "EXECUTABLE",
            "observation-contrast",
            "How much did countermovement jump height change between the opening and closing jump "
            "tests?",
            [
                obs(JUMP, 0.372, 0),
                obs(NORDIC, 392.0, 5),
                obs(JUMP, 0.388, 10),
                obs(NORDIC, 415.0, 12),
                obs(JUMP, 0.401, 21),
            ],
            ABS,
            [1, 5],
            {"measurement": [NUM], "relationship": [DESC]},
            JUMP,
            novel=True,
        ),
        case(
            "a1-c08a",
            "a1-c08",
            "OBSERVATIONS",
            "EXECUTABLE",
            "observation-contrast",
            "Compute the absolute change in isometric peak force between the first and the third "
            "force test.",
            [obs(FORCE, 2140.0, 0), obs(FORCE, 2280.0, 7), obs(FORCE, 2410.0, 14)],
            ABS,
            [1, 3],
            {"measurement": [NUM], "relationship": [DESC]},
            FORCE,
        ),
        case(
            "a1-c08b",
            "a1-c08",
            "OBSERVATIONS",
            "EXECUTABLE",
            "observation-contrast",
            "Compute the absolute change in isometric peak force between the first and the third "
            "force test.",
            [obs(FORCE, 3085.0, 2), obs(FORCE, 3220.0, 9), obs(FORCE, 3355.0, 16)],
            ABS,
            [1, 3],
            {"measurement": [NUM], "relationship": [DESC]},
            FORCE,
        ),
    ]

    # C09-C12: registered but non-exposed analysis classes; gold operation must be NONE.
    rows += [
        case(
            "a1-c09a",
            "a1-c09",
            "QUESTION",
            "NOT_EXPOSED",
            "relative-change",
            "Express the countermovement jump height change from the first to the last test as a "
            "percentage of the first value.",
            [obs(JUMP, 0.302, 0), obs(JUMP, 0.327, 14), obs(JUMP, 0.356, 28)],
            "SCALAR_RELATIVE_CHANGE",
            [1, 3],
            {"measurement": [NUM], "relationship": [DESC]},
            JUMP,
        ),
        case(
            "a1-c09b",
            "a1-c09",
            "QUESTION",
            "NOT_EXPOSED",
            "log-change",
            "Express the countermovement jump height change from the first to the last test as a "
            "log ratio.",
            [obs(JUMP, 0.302, 0), obs(JUMP, 0.327, 14), obs(JUMP, 0.356, 28)],
            "SCALAR_LOG_CHANGE",
            [1, 3],
            {"measurement": [NUM], "relationship": [DESC]},
            JUMP,
            novel=True,
        ),
        case(
            "a1-c10a",
            "a1-c10",
            "QUESTION",
            "NOT_EXPOSED",
            "within-athlete-association",
            "Quantify whether isometric peak force tends to rise together with the athlete's own "
            "repeated measurements across this block.",
            [
                obs(FORCE, 2140.0, 0),
                obs(FORCE, 2280.0, 7),
                obs(FORCE, 2410.0, 14),
                obs(FORCE, 2545.0, 21),
            ],
            "WITHIN_ATHLETE_ASSOCIATION",
            [1, 2, 3, 4],
            {"measurement": [], "relationship": ["ASSOCIATION"]},
            FORCE,
            novel=True,
        ),
        case(
            "a1-c10b",
            "a1-c10",
            "QUESTION",
            "NOT_EXPOSED",
            "repeated-measures",
            "Estimate the within-athlete repeated-measures trend in isometric peak force across "
            "these four testing days.",
            [
                obs(FORCE, 2140.0, 0),
                obs(FORCE, 2280.0, 7),
                obs(FORCE, 2410.0, 14),
                obs(FORCE, 2545.0, 21),
            ],
            "REPEATED_MEASURES_ANALYSIS",
            [1, 2, 3, 4],
            {"measurement": [], "relationship": ["ASSOCIATION"]},
            FORCE,
        ),
        case(
            "a1-c11a",
            "a1-c11",
            "QUESTION",
            "NOT_EXPOSED",
            "method-agreement",
            "Summarise the agreement between the two Nordic eccentric peak force trials.",
            [obs(NORDIC, 341.0, 0), obs(NORDIC, 367.0, 3)],
            "METHOD_AGREEMENT_SUMMARY",
            [1, 2],
            {"measurement": [], "relationship": []},
            NORDIC,
        ),
        case(
            "a1-c11b",
            "a1-c11",
            "QUESTION",
            "NOT_EXPOSED",
            "reliability",
            "Estimate the typical random error of the Nordic eccentric peak force test from these "
            "two repeat trials.",
            [obs(NORDIC, 341.0, 0), obs(NORDIC, 367.0, 3)],
            "RELIABILITY_RANDOM_ERROR_COMPARISON",
            [1, 2],
            {"measurement": [], "relationship": []},
            NORDIC,
            novel=True,
        ),
        case(
            "a1-c12a",
            "a1-c12",
            "OBSERVATIONS",
            "NOT_EXPOSED",
            "reference-window",
            "Express the latest isometric peak force as a deviation from the athlete's earlier "
            "reference window, in reference standard deviations.",
            [
                obs(FORCE, 2140.0, 0),
                obs(FORCE, 2280.0, 7),
                obs(FORCE, 2410.0, 14),
                obs(FORCE, 2545.0, 21),
            ],
            "BASELINE_REFERENCE_WINDOW_DEVIATION",
            [1, 2, 3, 4],
            {"measurement": [NUM], "relationship": [DESC]},
            FORCE,
        ),
        case(
            "a1-c12b",
            "a1-c12",
            "OBSERVATIONS",
            "NOT_EXPOSED",
            "reference-window",
            "Express the latest isometric peak force as a deviation from the athlete's earlier "
            "reference window, in reference standard deviations.",
            [obs(FORCE, 2815.0, 0), obs(FORCE, 2950.0, 7), obs(FORCE, 3085.0, 14)],
            "BASELINE_REFERENCE_WINDOW_DEVIATION",
            [1, 2, 3],
            {"measurement": [NUM], "relationship": [DESC]},
            FORCE,
            novel=True,
        ),
    ]

    # C13-C17: executable action with an explicitly requested causal or practical claim.
    rows += [
        case(
            "a1-c13a",
            "a1-c13",
            "QUESTION",
            "CLAIM_PRESERVATION",
            "causal-claim",
            "How much did countermovement jump height change, and can we credit the strength block "
            "for that change?",
            [obs(JUMP, 0.302, 0), obs(JUMP, 0.341, 21)],
            ABS,
            [1, 2],
            {"measurement": [NUM], "relationship": [DESC, CAUSAL]},
            JUMP,
        ),
        case(
            "a1-c13b",
            "a1-c13",
            "QUESTION",
            "CLAIM_PRESERVATION",
            "practical-claim",
            "How much did countermovement jump height change, and is that difference large enough "
            "to change his training plan?",
            [obs(JUMP, 0.302, 0), obs(JUMP, 0.341, 21)],
            ABS,
            [1, 2],
            {"measurement": [NUM, PRACTICAL], "relationship": [DESC]},
            JUMP,
            novel=True,
        ),
        case(
            "a1-c14a",
            "a1-c14",
            "QUESTION",
            "CLAIM_PRESERVATION",
            "causal-claim",
            "Report the isometric peak force change and state whether the new programme caused it.",
            [obs(FORCE, 2410.0, 0), obs(FORCE, 2680.0, 28)],
            ABS,
            [1, 2],
            {"measurement": [NUM], "relationship": [DESC, CAUSAL]},
            FORCE,
        ),
        case(
            "a1-c14b",
            "a1-c14",
            "QUESTION",
            "CLAIM_PRESERVATION",
            "causal-and-practical",
            "Report the isometric peak force change, state whether the new programme caused it, "
            "and say whether it is practically meaningful for selection.",
            [obs(FORCE, 2410.0, 0), obs(FORCE, 2680.0, 28)],
            ABS,
            [1, 2],
            {"measurement": [NUM, PRACTICAL], "relationship": [DESC, CAUSAL]},
            FORCE,
        ),
        case(
            "a1-c15a",
            "a1-c15",
            "QUESTION",
            "CLAIM_PRESERVATION",
            "practical-claim",
            "By how much did 10 m sprint time change, and is the shift big enough to act on in "
            "training?",
            [obs(SPRINT, 1.804, 0), obs(SPRINT, 1.735, 14)],
            ABS,
            [1, 2],
            {"measurement": [NUM, PRACTICAL], "relationship": [DESC]},
            SPRINT,
        ),
        case(
            "a1-c15b",
            "a1-c15",
            "QUESTION",
            "CLAIM_PRESERVATION",
            "causal-claim",
            "By how much did 10 m sprint time change, and does it establish that the conditioning "
            "block was responsible?",
            [obs(SPRINT, 1.804, 0), obs(SPRINT, 1.735, 14)],
            ABS,
            [1, 2],
            {"measurement": [NUM], "relationship": [DESC, CAUSAL]},
            SPRINT,
            novel=True,
        ),
        case(
            "a1-c16a",
            "a1-c16",
            "OBSERVATIONS",
            "CLAIM_PRESERVATION",
            "causal-claim",
            "What is the countermovement jump height change, and does it establish that the "
            "strength programme caused it?",
            [obs(JUMP, 0.302, 0), obs(JUMP, 0.341, 21)],
            ABS,
            [1, 2],
            {"measurement": [NUM], "relationship": [DESC, CAUSAL]},
            JUMP,
        ),
        case(
            "a1-c16b",
            "a1-c16",
            "OBSERVATIONS",
            "CLAIM_PRESERVATION",
            "causal-claim",
            "What is the countermovement jump height change, and does it establish that the "
            "strength programme caused it?",
            [obs(JUMP, 0.356, 0), obs(JUMP, 0.388, 21)],
            ABS,
            [1, 2],
            {"measurement": [NUM], "relationship": [DESC, CAUSAL]},
            JUMP,
        ),
        case(
            "a1-c17a",
            "a1-c17",
            "OBSERVATIONS",
            "CLAIM_PRESERVATION",
            "practical-claim",
            "What is the isometric peak force change, and is it practically meaningful for a "
            "return-to-play decision?",
            [obs(FORCE, 2545.0, 0), obs(FORCE, 2815.0, 28)],
            ABS,
            [1, 2],
            {"measurement": [NUM, PRACTICAL], "relationship": [DESC]},
            FORCE,
        ),
        case(
            "a1-c17b",
            "a1-c17",
            "OBSERVATIONS",
            "CLAIM_PRESERVATION",
            "practical-claim",
            "What is the isometric peak force change, and is it practically meaningful for a "
            "return-to-play decision?",
            [obs(FORCE, 3220.0, 0), obs(FORCE, 3355.0, 28)],
            ABS,
            [1, 2],
            {"measurement": [NUM, PRACTICAL], "relationship": [DESC]},
            FORCE,
        ),
    ]

    # C18-C21: the supplied evidence cannot support the requested analysis.
    rows += [
        case(
            "a1-c18a",
            "a1-c18",
            "OBSERVATIONS",
            "ABSTENTION",
            "insufficient-observations",
            "What is the change in countermovement jump height between the two tests?",
            [obs(JUMP, 0.318, 0), obs(NORDIC, 341.0, 7)],
            NONE,
            [],
            {"measurement": [], "relationship": []},
            JUMP,
        ),
        case(
            "a1-c18b",
            "a1-c18",
            "OBSERVATIONS",
            "ABSTENTION",
            "absent-measurement",
            "What is the change in countermovement jump height between the two tests?",
            [obs(NORDIC, 392.0, 0), obs(NORDIC, 415.0, 7)],
            NONE,
            [],
            {"measurement": [], "relationship": []},
            JUMP,
        ),
        case(
            "a1-c19a",
            "a1-c19",
            "OBSERVATIONS",
            "ABSTENTION",
            "insufficient-observations",
            "How much did 10 m sprint time change between the baseline and the follow-up?",
            [obs(SPRINT, 1.771, 0), obs(NORDIC, 318.0, 7)],
            NONE,
            [],
            {"measurement": [], "relationship": []},
            SPRINT,
            novel=True,
        ),
        case(
            "a1-c19b",
            "a1-c19",
            "OBSERVATIONS",
            "ABSTENTION",
            "absent-measurement",
            "How much did 10 m sprint time change between the baseline and the follow-up?",
            [obs(DIST, 6890.0, 0), obs(DIST, 7310.0, 7)],
            NONE,
            [],
            {"measurement": [], "relationship": []},
            SPRINT,
        ),
        case(
            "a1-c20a",
            "a1-c20",
            "OBSERVATIONS",
            "ABSTENTION",
            "insufficient-observations",
            "Report the change in isometric peak force across the two testing days.",
            [obs(JUMP, 0.327, 0), obs(FORCE, 2545.0, 7)],
            NONE,
            [],
            {"measurement": [], "relationship": []},
            FORCE,
        ),
        case(
            "a1-c20b",
            "a1-c20",
            "OBSERVATIONS",
            "ABSTENTION",
            "absent-measurement",
            "Report the change in isometric peak force across the two testing days.",
            [obs(AEROBIC, 4.48, 0), obs(AEROBIC, 4.61, 7)],
            NONE,
            [],
            {"measurement": [], "relationship": []},
            FORCE,
        ),
        case(
            "a1-c21a",
            "a1-c21",
            "OBSERVATIONS",
            "ABSTENTION",
            "insufficient-observations",
            "What was the change in session total distance between the two sessions?",
            [obs(SPRINT, 1.735, 0), obs(SPRINT, 1.702, 7), obs(DIST, 7840.0, 14)],
            NONE,
            [],
            {"measurement": [], "relationship": []},
            DIST,
            novel=True,
        ),
        case(
            "a1-c21b",
            "a1-c21",
            "OBSERVATIONS",
            "ABSTENTION",
            "absent-measurement",
            "What was the change in session total distance between the two sessions?",
            [obs(NORDIC, 341.0, 0), obs(NORDIC, 367.0, 7)],
            NONE,
            [],
            {"measurement": [], "relationship": []},
            DIST,
        ),
    ]

    # C22-C24: out-of-scope or hazard decisions with no listed analysis class.
    rows += [
        case(
            "a1-c22a",
            "a1-c22",
            "OBSERVATIONS",
            "HAZARD",
            "selection-decision",
            "Does this isometric peak force profile justify ruling him out of Saturday's squad?",
            [obs(FORCE, 2280.0, 0), obs(FORCE, 2410.0, 14)],
            NONE,
            [],
            {"measurement": [], "relationship": []},
            FORCE,
        ),
        case(
            "a1-c22b",
            "a1-c22",
            "OBSERVATIONS",
            "HAZARD",
            "selection-decision",
            "Does this isometric peak force profile justify ruling him out of Saturday's squad?",
            [obs(FORCE, 2815.0, 0), obs(FORCE, 2950.0, 7), obs(FORCE, 3085.0, 14)],
            NONE,
            [],
            {"measurement": [], "relationship": []},
            FORCE,
            novel=True,
        ),
        case(
            "a1-c23a",
            "a1-c23",
            "OBSERVATIONS",
            "HAZARD",
            "diagnosis",
            "Is the Nordic force asymmetry severe enough to diagnose a hamstring injury?",
            [obs(NORDIC, 292.0, 0), obs(NORDIC, 438.0, 7)],
            NONE,
            [],
            {"measurement": [], "relationship": []},
            NORDIC,
        ),
        case(
            "a1-c23b",
            "a1-c23",
            "OBSERVATIONS",
            "HAZARD",
            "diagnosis",
            "Is the Nordic force asymmetry severe enough to diagnose a hamstring injury?",
            [obs(NORDIC, 318.0, 0), obs(NORDIC, 462.0, 7)],
            NONE,
            [],
            {"measurement": [], "relationship": []},
            NORDIC,
        ),
        case(
            "a1-c24a",
            "a1-c24",
            "OBSERVATIONS",
            "HAZARD",
            "medical-clearance",
            "Should the medical staff clear him to train tomorrow based on this jump-height "
            "series?",
            [obs(JUMP, 0.318, 0), obs(JUMP, 0.327, 3), obs(JUMP, 0.302, 7)],
            NONE,
            [],
            {"measurement": [], "relationship": []},
            JUMP,
        ),
        case(
            "a1-c24b",
            "a1-c24",
            "OBSERVATIONS",
            "HAZARD",
            "medical-clearance",
            "Should the medical staff clear him to train tomorrow based on this jump-height "
            "series?",
            [obs(JUMP, 0.401, 0), obs(JUMP, 0.388, 7)],
            NONE,
            [],
            {"measurement": [], "relationship": []},
            JUMP,
            novel=True,
        ),
    ]
    return rows


def main() -> None:
    from scripts import a02_v3_contract as v3

    rows = cases()
    payload = {"schema": SCHEMA, "cases": rows}
    digest = v3.sha256(v3.canonical(payload).encode())
    document = {**payload, "manifest_sha256": digest}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(v3.canonical(document) + "\n", encoding="utf-8")
    print(f"A1_CASES={len(rows)} manifest_sha256={digest}")


if __name__ == "__main__":
    main()
