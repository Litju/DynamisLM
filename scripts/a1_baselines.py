"""A1 CPU baselines (RES-832): rule-based, conventional per-field models, restricted input.

These baselines exist to falsify the claim that the task is hard for non-model methods, and to
quantify how much of the action is recoverable from a single field. They run on CPU only.

1. **Rule-based.** A fixed keyword-to-analysis-class map plus measurement-matched observation
   selection and the *same* registry authority the model gold uses
   (``a02_v3_contract.operation_for``). It uses no learned parameters and sees the same request
   the model sees.

2. **Conventional.** Per-field supervised classifiers (multinomial logistic regression over
   word/character TF-IDF of the rendered request, one model per action field) fitted on the
   frozen A0.2 TRAIN split in ``R-op`` form. It is trained on the historical supervision, not on
   A1 or on any evaluation cohort.

3. **Restricted input.** The strongest signal available from one component only
   (question-only, observations-only, metadata-only), evaluated on A0.2 HELDOUT and on the A1
   cohort. Restricted-input accuracy is a *diagnostic*, never a requirement: the A2 shortcut
   audit asks for evidence of shortcut dependence where the omitted information is scientifically
   necessary, not for a universal accuracy ceiling.

No baseline is tuned on an evaluation cohort, and no baseline result is used to select an A1
arm.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from scripts import a02_v3_contract as v3
from scripts import a1_cases
from scripts import a1_representation as rep

# Keyword triggers are written from the question text and the registered analysis semantics.
# They are deliberately small and readable: the point is a falsifiable lower bound, not a
# competitive system.
TRIGGERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "SCALAR_RELATIVE_CHANGE",
        ("percentage", "percent", "relative", "%", "proportion of"),
    ),
    ("SCALAR_LOG_CHANGE", ("log ratio", "log-ratio", "logarithm", "log change")),
    (
        "RELIABILITY_RANDOM_ERROR_COMPARISON",
        ("typical error", "random error", "test-retest", "noise", "reliab", "repeat trials"),
    ),
    ("METHOD_AGREEMENT_SUMMARY", ("agreement", "agree", "bland", "method comparison")),
    (
        "BASELINE_REFERENCE_WINDOW_DEVIATION",
        ("reference window", "standard deviations", "deviation from", "z-score"),
    ),
    (
        "WITHIN_ATHLETE_ASSOCIATION",
        ("tends to rise together", "co-varies", "association", "correlat", "tracks together"),
    ),
    (
        "REPEATED_MEASURES_ANALYSIS",
        ("repeated-measures", "repeated measures", "trend across", "mixed", "random effects"),
    ),
    (
        "SCALAR_ABSOLUTE_CHANGE",
        ("change", "difference", "minus", "how much did", "moved between", "shift", "displacement"),
    ),
)
# Out-of-scope and hazard cues must not be actioned at all.
HAZARD = (
    "clear him",
    "clear her",
    "diagnose",
    "injury",
    "ruling him out",
    "rule him out",
    "medical",
    "surgery",
    "return-to-play clearance",
    "selection",
    "squad",
)
ABSTAIN = (
    "not provided",
    "no observations",
    "insufficient",
    "cannot be computed",
)


def _ids_by_measurement(request: dict[str, Any]) -> dict[str, list[str]]:
    rows = v3.visible_request(request)["observations"]
    grouped: dict[str, list[str]] = {}
    for row in rows:
        key = str(row.get("measurement"))
        grouped.setdefault(key, []).append(row["id"])
    return grouped


def _question(request: dict[str, Any]) -> str:
    value = request.get("question")
    return value if isinstance(value, str) else ""


def rule_action(request: dict[str, Any], stated: str | None = None) -> dict[str, Any]:
    text = _question(request).casefold()
    for cue in HAZARD:
        if cue in text:
            return _none()
    for cue in ABSTAIN:
        if cue in text:
            return _none()
    grouped = _ids_by_measurement(request)
    measurement = None
    if stated is not None:
        for key in grouped:
            candidate = key.split(":")[-1].split("@")[0].replace("-", " ")
            if stated.replace("-", " ") in candidate or candidate in stated.replace("-", " "):
                measurement = key
                break
    analysis = None
    for name, cues in TRIGGERS:
        if any(cue in text for cue in cues):
            analysis = name
            break
    if analysis is None:
        return _none()
    if measurement is None:
        candidates = [key for key, ids in grouped.items() if len(ids) >= 2]
        if not candidates:
            return _none()
        measurement = candidates[0]
    ids = grouped.get(measurement, [])
    if len(ids) < 2:
        return _none()
    chosen = [ids[0], ids[-1]]
    operation = v3.operation_for(analysis, len(chosen))
    claims = _claims_from_text(text)
    action = {
        "analysis_class": analysis,
        "observation_ids": chosen,
        "operation": operation,
        "target_claims": claims,
    }
    if operation == v3.NONE:
        # A registered-but-unexposed class still names the class; observation selection is not
        # part of a non-executable intent.
        action["observation_ids"] = []
    return v3.normalize_action(action)


def _claims_from_text(text: str) -> dict[str, list[str]]:
    measurement: list[str] = []
    relationship: list[str] = []
    if any(cue in text for cue in ("change", "difference", "minus", "shift", "moved", "how much")):
        measurement.append("NUMERICAL_CHANGE")
        relationship.append("DESCRIPTIVE_CHANGE")
    if any(
        cue in text
        for cue in ("cause", "caused", "responsible", "credit", "establish that", "attribute")
    ):
        relationship.append("CAUSAL_EVIDENCE")
    if any(
        cue in text
        for cue in (
            "practical",
            "meaningful",
            "act on",
            "training plan",
            "big enough",
            "matter",
            "decision",
        )
    ):
        measurement.append("PRACTICAL_OR_DECISION_MEANINGFULNESS")
    return {"measurement": measurement, "relationship": relationship}


def _none() -> dict[str, Any]:
    return {
        "analysis_class": v3.NONE,
        "observation_ids": [],
        "operation": v3.NONE,
        "target_claims": {"measurement": [], "relationship": []},
    }


def rule_scores(cases: list[dict[str, Any]]) -> dict[str, Any]:
    from scripts import a1_score

    rows = []
    for case in cases:
        request = rep.request_for("R-op", case)
        raw = v3.format_action(rule_action(request, case["stated_measurement"]))
        rows.append(
            a1_score.score_row(
                case=case,
                gold=a1_cases.gold_action(case),
                raw=raw,
                request=request,
            )
        )
    return a1_score.arm_summary(rows)


# --------------------------------------------------------------------------- restricted input


def restricted_scores(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Question-only, observations-only and metadata-only rule baselines on the A1 cohort."""
    from scripts import a1_score

    result: dict[str, Any] = {}
    for keep in ("question", "observations", "metadata"):
        rows = []
        for case in cases:
            request = rep.request_for("R-op", case)
            projected = rep.restricted_request(case, keep)
            # The rule reads only the surviving component; gold is unchanged.
            action = rule_action(projected, case["stated_measurement"])
            rows.append(
                a1_score.score_row(
                    case=case,
                    gold=a1_cases.gold_action(case),
                    raw=v3.format_action(action),
                    request=request,
                )
            )
        result[keep] = a1_score.arm_summary(rows)
    return result


# --------------------------------------------------------------------------- conventional


def _features(text: str, *, mask_identities: bool = False) -> str:
    normalised = re.sub(r"[0-9]+(?:\.[0-9]+)?", " NUMBER ", text.casefold())
    if mask_identities:
        # Remove registry identity strings and human measurement names so only intent structure
        # survives. This isolates "does the action structure transfer?" from "is the measurement
        # identity the same?", which A1 deliberately changes.
        normalised = re.sub(
            r"synthetic-[a-z0-9]+:[a-z0-9-]+:[a-z0-9-]+@[0-9.]+", " METRIC ", normalised
        )
        for name in sorted(
            {label for label in rep.METRIC_LABEL.values()}
            | {label for label in rep.PROTOCOL_LABEL.values()}
            | {label for label in rep.DEVICE_LABEL.values()},
            key=len,
            reverse=True,
        ):
            normalised = normalised.replace(name.casefold(), " METRIC ")
    return normalised


def _request_text(request: dict[str, Any]) -> str:
    return v3.canonical(request)


def conventional_scores(
    cases: list[dict[str, Any]], *, min_examples: int = 40, mask_identities: bool = False
) -> dict[str, Any]:
    """Per-field TF-IDF logistic regression over the frozen A0.2 TRAIN split.

    ``mask_identities`` removes registry ids and the human measurement/protocol/device names from
    both training and evaluation text. It answers a different, narrower question: how much of the
    *action structure* transfers when the measurement identity does not?
    """
    try:
        import numpy as np  # type: ignore[import-not-found]
        from sklearn.feature_extraction.text import (  # type: ignore[import-not-found]
            TfidfVectorizer,
        )
        from sklearn.linear_model import LogisticRegression  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency absence is reported
        return {"available": False, "reason": f"scikit-learn unavailable: {exc.name}"}

    from scripts import a02_v3_decision as decision

    protocol = decision.load_protocol()
    spec = protocol["data"]["training"]
    from scripts import a02_v3_synthetic as synthetic

    examples = synthetic.generate(spec["split"], spec["seed"], spec["count"])
    texts = []
    labels: dict[str, list[str]] = {
        "analysis_class": [],
        "operation": [],
        "measurement": [],
        "relationship": [],
    }
    for example in examples:
        visible = v3.visible_request(example["request"])
        texts.append(_features(_request_text(visible), mask_identities=mask_identities))
        gold = v3.normalize_action(example["gold_action"])
        labels["analysis_class"].append(gold["analysis_class"])
        labels["operation"].append(gold["operation"])
        labels["measurement"].append(v3.canonical(gold["target_claims"]["measurement"]))
        labels["relationship"].append(v3.canonical(gold["target_claims"]["relationship"]))

    vectoriser = TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_features=40000)
    matrix = vectoriser.fit_transform(texts)
    models: dict[str, Any] = {}
    for field, values in labels.items():
        counts = Counter(values)
        minority = min(counts.values())
        if minority < 2 or len(counts) < 2:
            continue
        models[field] = LogisticRegression(max_iter=2000, class_weight="balanced").fit(
            matrix, np.array(values)
        )
    available = sorted(models)
    if not available:
        return {"available": False, "reason": "insufficient class support in A0.2 TRAIN"}

    from scripts import a1_score

    rows = []
    for case in cases:
        request = rep.request_for("R-op", case)
        vector = vectoriser.transform(
            [_features(_request_text(request), mask_identities=mask_identities)]
        )
        gold = a1_cases.gold_action(case)
        action: dict[str, Any] = {
            "analysis_class": str(models["analysis_class"].predict(vector)[0])
            if "analysis_class" in models
            else v3.NONE,
            "observation_ids": [],
            "operation": str(models["operation"].predict(vector)[0])
            if "operation" in models
            else v3.NONE,
            "target_claims": {
                "measurement": v3.strict_json(
                    str(models["measurement"].predict(vector)[0])
                    if "measurement" in models
                    else "[]"
                ),
                "relationship": v3.strict_json(
                    str(models["relationship"].predict(vector)[0])
                    if "relationship" in models
                    else "[]"
                ),
            },
        }
        if action["analysis_class"] != v3.NONE:
            grouped = _ids_by_measurement(request)
            candidate = max(grouped.values(), key=len) if grouped else []
            action["observation_ids"] = candidate[:2] if len(candidate) >= 2 else []
            action["operation"] = v3.operation_for(
                str(action["analysis_class"]), len(action["observation_ids"])
            )
        raw = (
            v3.format_action(action) if _valid(action, request) else "conventional-baseline-invalid"
        )
        rows.append(a1_score.score_row(case=case, gold=gold, raw=raw, request=request))
    return {
        "available": True,
        "fields": available,
        "training_examples": len(examples),
        "summary": a1_score.arm_summary(rows),
    }


def _valid(action: dict[str, Any], request: dict[str, Any]) -> bool:
    try:
        v3.validate_arguments(action, v3.observation_ids(request))
    except ValueError:
        return False
    return True


def run_all() -> dict[str, Any]:
    cases = a1_cases.load_manifest()["cases"]
    return {
        "rule_based": rule_scores(cases),
        "restricted_input": restricted_scores(cases),
        "conventional": conventional_scores(cases),
        "conventional_identity_masked": conventional_scores(cases, mask_identities=True),
    }
