"""Contract tests for the frozen A1 campaign (RES-832).

These are falsification tests, not smoke tests. Each one asserts a property whose failure would
invalidate the campaign's science:

* the cohort is exactly 48 cases in 24 contrastive clusters with the registered allocation;
* no case reuses an A0.2 or RES-774 question;
* every gold action is derivable from the registry, never authored;
* the two principal representations carry the same scientific information;
* enrichment is the only arm that adds semantic help, and it is never gold-derived;
* no prompt contains gold, an analysis class name for a hazard case, or a gold claim level;
* the call manifest is frozen at or below the authorized workload, and is deduplicated;
* the runner refuses prompt drift, resumes without regenerating, and drops only a torn tail;
* scoring is strict, cluster-aware, and never upgrades a relaxed interpretation;
* paired contrasts distinguish improvement, degradation, equivalence and inconclusive evidence.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from scripts import a02_v3_contract as v3
from scripts import (
    a1_baselines,
    a1_cases,
    a1_manifest,
    a1_rehearsal,
    a1_retrospective,
    a1_run,
    a1_score,
)
from scripts import a1_representation as rep


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    return a1_cases.load_manifest()


# D6 and the shortcut comparison use the private RES-774 evidence root. That root lives outside
# Git, so the tests that require it are skipped on hosted CI, exactly as the repository already
# does for the sealed predecessor receipts. The CI-verifiable contract is covered separately.
needs_evidence = pytest.mark.skipif(
    not a1_retrospective.available(),
    reason="private RES-774 evidence lives outside Git; verified locally, not on hosted CI",
)


def test_cohort_allocation_and_clusters(manifest: dict[str, Any]) -> None:
    cases = manifest["cases"]
    assert len(cases) == 48
    clusters: dict[str, list[dict[str, Any]]] = {}
    for case in cases:
        clusters.setdefault(case["cluster"], []).append(case)
    assert len(clusters) == 24
    assert all(len(group) == 2 for group in clusters.values())
    counts: dict[str, int] = {}
    for case in cases:
        counts[case["stratum"]] = counts.get(case["stratum"], 0) + 1
    assert counts == {
        "EXECUTABLE": 16,
        "NOT_EXPOSED": 8,
        "CLAIM_PRESERVATION": 10,
        "ABSTENTION": 8,
        "HAZARD": 6,
    }
    assert sum(1 for case in cases if case["novel_phrasing"]) >= 12
    assert sum(1 for case in cases if case["subset_selection"]) == 8


def test_question_contrast_changes_gold_and_observation_contrast_does_not(
    manifest: dict[str, Any],
) -> None:
    clusters: dict[str, list[dict[str, Any]]] = {}
    for case in manifest["cases"]:
        clusters.setdefault(case["cluster"], []).append(case)
    for group in clusters.values():
        first, second = group
        if first["contrast"] == "QUESTION":
            assert first["observations"] == second["observations"]
            assert first["question"] != second["question"]
            assert a1_cases.gold_action(first) != a1_cases.gold_action(second) or (
                a1_cases.gold_action(first)["observation_ids"]
                != a1_cases.gold_action(second)["observation_ids"]
            )
        else:
            assert first["question"] == second["question"]
            assert first["observations"] != second["observations"]


def test_gold_is_registry_derived_not_authored(manifest: dict[str, Any]) -> None:
    for case in manifest["cases"]:
        gold = a1_cases.gold_action(case)
        intent = case["intent"]
        assert gold["analysis_class"] == intent["analysis_class"]
        assert gold["observation_ids"] == [
            f"observation-{index}" for index in intent["observations"]
        ]
        expected = v3.operation_for(intent["analysis_class"], len(intent["observations"]))
        assert gold["operation"] == expected
        if case["stratum"] in {"ABSTENTION", "HAZARD"}:
            assert gold["operation"] == v3.NONE
            assert gold["observation_ids"] == []


@needs_evidence
def test_no_case_reuses_a_historical_question(manifest: dict[str, Any]) -> None:
    from scripts import a02_v3_decision as decision
    from scripts import a1_retrospective

    questions = {case["question"].casefold() for case in manifest["cases"]}
    # Observation-contrast clusters intentionally hold the question fixed; question-contrast
    # clusters must not repeat any question.
    question_contrast = [
        case["question"].casefold() for case in manifest["cases"] if case["contrast"] == "QUESTION"
    ]
    assert len(question_contrast) == len(set(question_contrast))
    blind = a1_retrospective.cohort_request()
    historical = {row["question"].casefold() for row in blind if row.get("question")}
    assert not (questions & historical)
    protocol = decision.load_protocol()
    from scripts import a02_v3_synthetic as synthetic

    spec = protocol["data"]["training"]
    examples = synthetic.generate(spec["split"], spec["seed"], spec["count"])
    templates = {example["request"]["question"].casefold() for example in examples}
    assert not (questions & templates)


def test_case_manifest_is_byte_frozen(manifest: dict[str, Any]) -> None:
    raw = a1_cases.CASES_PATH.read_bytes()
    assert raw == (v3.canonical(manifest) + "\n").encode()
    assert a1_cases.digest_of_cases(manifest["cases"]) == manifest["manifest_sha256"]


def test_manifest_tampering_fails_closed(
    monkeypatch: pytest.MonkeyPatch, manifest: dict[str, Any], tmp_path: Path
) -> None:
    # A tampered case list no longer matches the pinned digest.
    broken = json.loads(json.dumps(manifest))
    broken["cases"][0]["question"] = "tampered"
    assert a1_cases.digest_of_cases(broken["cases"]) != manifest["manifest_sha256"]

    # A tampered file is rejected by the loader before any validation or inference.
    tampered_file = tmp_path / "cases-v1.json"
    tampered_file.write_text(v3.canonical(broken) + "\n", encoding="utf-8")
    monkeypatch.setattr(a1_cases, "CASES_PATH", tampered_file)
    with pytest.raises(ValueError):
        a1_cases.load_manifest()

    # Non-canonical bytes are rejected even when the digest field is recomputed.
    recomputed = json.loads(json.dumps(broken))
    recomputed["manifest_sha256"] = a1_cases.digest_of_cases(recomputed["cases"])
    tampered_file.write_text(json.dumps(recomputed, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        a1_cases.load_manifest()

    # A semantically broken allocation is rejected even with a valid digest.
    reallocated = json.loads(json.dumps(manifest))
    reallocated["cases"][0]["stratum"] = "HAZARD"
    reallocated["manifest_sha256"] = a1_cases.digest_of_cases(reallocated["cases"])
    tampered_file.write_text(v3.canonical(reallocated) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        a1_cases.load_manifest()


def test_historical_and_operational_representations_are_information_equivalent(
    manifest: dict[str, Any],
) -> None:
    for case in manifest["cases"]:
        historical = rep.historical_request(case)
        operational = rep.operational_request(case)
        assert historical["question"] == operational["question"] == case["question"]
        assert len(historical["observations"]) == len(operational["observations"])
        for left, right in zip(
            historical["observations"], operational["observations"], strict=True
        ):
            assert left["value"] == right["value"]
            assert left["unit"] == right["unit"]
            assert left["time"] == right["date"]
        # Registry ids and their human labels are one-to-one in this cohort.
        assert {
            rep.METRIC_LABEL[rep._metric_key(row["measurement"])]
            for row in operational["observations"]
        } == {row["measurement"] for row in historical["observations"]}
        assert {row["protocol"] for row in operational["observations"]} != set()
        # Comparability is stated explicitly in the historical arm, never inferred.
        assert historical["comparability_evidence"].endswith(".")


def test_historical_arm_has_no_case_varying_constant_strings(manifest: dict[str, Any]) -> None:
    constants = set()
    for case in manifest["cases"]:
        historical = rep.historical_request(case)
        constants.add(v3.canonical(historical["available_evidence"]))
        constants.add(v3.canonical(historical["missing_evidence"]))
        constants.add(v3.canonical(historical["football_context"]))
        constants.add(historical["source_documentation"])
    assert len(constants) == 4


def test_enrichment_is_the_only_arm_that_adds_semantic_help(manifest: dict[str, Any]) -> None:
    for case in manifest["cases"]:
        enriched = rep.enriched_request(case)
        operational = rep.operational_request(case)
        assert set(enriched) - set(operational) == {"objective"}
        objective = enriched["objective"]
        # Gold-blind: it names the stated measurement and never an analysis class, operation,
        # observation id or claim level.
        for name in v3.ANALYSIS_CLASSES:
            assert name not in objective
        for operation in v3.EXPOSED_OPERATIONS:
            assert operation not in objective
        assert "observation-" not in objective
        for level in (*v3.MEASUREMENT_LEVELS, *v3.RELATIONSHIP_LEVELS):
            assert level not in objective


def test_no_prompt_contains_gold_or_a_gold_claim(manifest: dict[str, Any]) -> None:
    for case in manifest["cases"]:
        gold = a1_cases.gold_action(case)
        nonempty = {axis: levels for axis, levels in gold["target_claims"].items() if levels}
        for arm in ("R-op", "R-hist", "D4-human", "D3-constant-claims"):
            request = rep.request_for(arm, case)
            text = v3.canonical(request)
            assert v3.TOOL_NAME not in text
            if case["stratum"] in {"ABSTENTION", "HAZARD"}:
                for name in v3.ANALYSIS_CLASSES:
                    if name not in case["question"]:
                        assert name not in text
            # A non-empty gold claim set must never be handed to the model as typed input.
            if nonempty:
                assert v3.canonical(nonempty) not in text


def test_restricted_projections_are_strictly_poorer(manifest: dict[str, Any]) -> None:
    case = manifest["cases"][0]
    full = rep.request_for("R-op", case)
    for keep in ("question", "observations", "metadata"):
        projected = rep.restricted_request(case, keep)
        assert projected != full
        if keep == "question":
            assert projected["observations"] == []
        if keep == "observations":
            assert projected["question"] == ""
        if keep == "metadata":
            assert all("value" not in row for row in projected["observations"])


def test_call_manifest_is_within_the_authorized_workload() -> None:
    sealed = a1_manifest.load_manifest()
    assert sealed["planned_generations"] <= 1336
    assert sealed["planned_conditions"] == 18
    assert sealed["planned_generations"] == sum(
        len(condition["items"]) for condition in sealed["conditions"]
    )
    # The CI-verifiable manifest excludes D6, which needs the private evidence root. The declared
    # total must still fit the authorized ceiling, and D6's fixed 192 calls are what fills it.
    assert sealed["retrospective_planned_generations"] == 192
    assert sealed["total_planned_generations"] <= 1336
    assert (
        sealed["total_planned_generations"]
        == sealed["planned_generations"] + sealed["retrospective_planned_generations"]
    )
    principal = [
        condition
        for condition in sealed["conditions"]
        if condition["role"] == "PRINCIPAL_FACTORIAL"
    ]
    assert len(principal) == 8
    assert all(len(condition["items"]) == 48 for condition in principal)
    assert sum(len(condition["items"]) for condition in principal) == 384


def test_call_manifest_deduplicates_identical_conditions() -> None:
    sealed = a1_manifest.load_manifest()
    keys = set()
    for condition in sealed["conditions"]:
        for item in condition["items"]:
            keys.add((condition["role"], item["prompt_sha256"], condition["decoder"]))
    # Principal arms deliberately repeat the same prompt across decoders; conditions themselves
    # must be unique on the full condition tuple.
    digests = [condition["condition_sha256"] for condition in sealed["conditions"]]
    assert len(digests) == len(set(digests))


def test_call_manifest_refuses_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    original = a1_manifest.manifest
    monkeypatch.setattr(a1_manifest, "manifest", lambda: {**original(), "planned_generations": 1})
    with pytest.raises(a1_manifest.ManifestError):
        a1_manifest.load_manifest()


def test_runner_refuses_prompt_drift(tmp_path: Path) -> None:
    condition = a1_manifest.load_manifest()["conditions"][0]
    tampered = json.loads(json.dumps(condition))
    tampered["items"][0]["prompt_sha256"] = "0" * 64
    restore = a1_rehearsal.use_stub_prompts()
    try:
        with pytest.raises(a1_run.GenerationError):
            a1_run.run_arm(
                a1_rehearsal.StubBackend(), tampered, identity={}, root=tmp_path, deadline_seconds=5
            )
    finally:
        restore()


def test_runner_resumes_without_regenerating(tmp_path: Path) -> None:
    condition = a1_manifest.load_manifest()["conditions"][0]
    backend = a1_rehearsal.StubBackend()
    restore = a1_rehearsal.use_stub_prompts()
    try:
        first = a1_run.run_arm(backend, condition, identity={}, root=tmp_path, deadline_seconds=60)
        assert first["committed"] == 48
        second = a1_run.run_arm(backend, condition, identity={}, root=tmp_path, deadline_seconds=60)
    finally:
        restore()
    assert second["generated_now"] == 0
    assert second["committed"] == 48
    assert second["complete"] is True
    lines = a1_run.arm_path(condition["arm"], tmp_path).read_bytes().split(b"\n")
    assert len([line for line in lines if line]) == 48


def test_runner_drops_only_a_torn_tail(tmp_path: Path) -> None:
    condition = a1_manifest.load_manifest()["conditions"][0]
    restore = a1_rehearsal.use_stub_prompts()
    try:
        a1_run.run_arm(
            a1_rehearsal.StubBackend(), condition, identity={}, root=tmp_path, deadline_seconds=60
        )
        path = a1_run.arm_path(condition["arm"], tmp_path)
        complete = path.read_bytes()
        # Drop the final committed line and leave an unterminated fragment behind it.
        keep = complete[: complete.rfind(b"\n", 0, len(complete) - 1) + 1]
        path.write_bytes(keep + b'{"torn"')
        state = a1_run.read_arm(path, condition["arm"], condition["items"])
        resumed = a1_run.run_arm(
            a1_rehearsal.StubBackend(), condition, identity={}, root=tmp_path, deadline_seconds=60
        )
    finally:
        restore()
    assert state["torn_tail_discarded"] is True
    assert len(state["entries"]) == 47
    assert resumed["complete"] is True
    assert resumed["generated_now"] == 1
    assert a1_run.arm_path(condition["arm"], tmp_path).read_bytes() == complete


def test_runner_detects_a_changed_committed_line(tmp_path: Path) -> None:
    condition = a1_manifest.load_manifest()["conditions"][0]
    restore = a1_rehearsal.use_stub_prompts()
    try:
        a1_run.run_arm(
            a1_rehearsal.StubBackend(), condition, identity={}, root=tmp_path, deadline_seconds=60
        )
    finally:
        restore()
    path = a1_run.arm_path(condition["arm"], tmp_path)
    lines = path.read_bytes().split(b"\n")
    record = v3.json_object(lines[1].decode())
    record["raw_output"] = "tampered"
    lines[1] = v3.canonical(record).encode()
    path.write_bytes(b"\n".join(lines))
    with pytest.raises(a1_run.GenerationError):
        a1_run.read_arm(path, condition["arm"], condition["items"])


def test_scorer_is_strict_and_reports_structure_separately(manifest: dict[str, Any]) -> None:
    case = manifest["cases"][0]
    request = rep.request_for("R-op", case)
    gold = a1_cases.gold_action(case)
    row = a1_score.score_row(case=case, gold=gold, raw=v3.format_action(gold), request=request)
    assert row["structured_valid"] == 1 and row["exact"] == 1
    assert row["observation_f1"] == 1.0
    invalid = a1_score.score_row(
        case=case, gold=gold, raw="I cannot determine this.", request=request
    )
    assert invalid["structured_valid"] == 0 and invalid["exact"] == 0
    assert invalid["hedged"] == 1


def test_relaxed_scoring_never_upgrades_the_strict_score(manifest: dict[str, Any]) -> None:
    case = manifest["cases"][0]
    request = rep.request_for("R-op", case)
    gold = a1_cases.gold_action(case)
    raw = v3.canonical(gold).replace("<tool_call>", "").replace("</tool_call>", "")
    row = a1_score.score_row(case=case, gold=gold, raw=raw, request=request)
    assert row["structured_valid"] == 0
    assert row["exact"] == 0
    # Diagnostic recovery may succeed, but it is reported on its own axis only.
    assert row["relaxed_recovery"] in (0, 1)
    if row["relaxed_recovery"]:
        assert row["relaxed_exact"] == 1
        assert row["exact"] == 0


def test_cluster_bootstrap_uses_clusters_not_items(manifest: dict[str, Any]) -> None:
    rows = []
    for index in range(20):
        rows.append(
            {
                "cluster": f"c{index}",
                "case_id": f"x{index}",
                "stratum": "EXECUTABLE",
                "exact": 1,
            }
        )
    summary = a1_score.cluster_bootstrap(rows, "exact", draws=500)
    assert summary["estimate"] == 1.0
    assert summary["clusters"] == 20
    assert summary["ci95"] == [1.0, 1.0]


def test_paired_verdict_separates_equivalence_from_inconclusive() -> None:
    left = [{"cluster": f"c{index}", "case_id": f"x{index}", "v": 1} for index in range(12)]
    right = [{"cluster": f"c{index}", "case_id": f"x{index}", "v": 1} for index in range(12)]
    same = a1_score.paired_bootstrap(left, right, "v", draws=400)
    assert same["estimate"] == 0.0
    assert same["verdict"] == "PRACTICAL_EQUIVALENCE_WITHIN_MARGIN"
    mixed = [
        {"cluster": f"c{index}", "case_id": f"x{index}", "v": 1 if index % 2 else 0}
        for index in range(12)
    ]
    inverted = [
        {"cluster": f"c{index}", "case_id": f"x{index}", "v": 0 if index % 2 else 1}
        for index in range(12)
    ]
    inconclusive = a1_score.paired_bootstrap(mixed, inverted, "v", draws=400)
    assert inconclusive["verdict"] == "INCONCLUSIVE_DIFFERENCE"


def test_mcnemar_is_labelled_non_confirmatory() -> None:
    left = [{"case_id": f"x{index}", "v": 1} for index in range(10)]
    right = [{"case_id": f"x{index}", "v": 0} for index in range(10)]
    result = a1_score.mcnemar(left, right, "v")
    assert result["confidence"] == "DESCRIPTIVE_NON_CONFIRMATORY_CLUSTERED_ITEMS"
    assert result["left_only"] == 10


def test_rule_baseline_never_actions_a_hazard(manifest: dict[str, Any]) -> None:
    for case in manifest["cases"]:
        if case["stratum"] != "HAZARD":
            continue
        request = rep.request_for("R-op", case)
        action = a1_baselines.rule_action(request, case["stated_measurement"])
        assert action["analysis_class"] == v3.NONE
        assert action["operation"] == v3.NONE


def test_rehearsal_runs_the_principal_block_end_to_end() -> None:
    result = a1_rehearsal.rehearsal()
    assert result["complete"] is True
    assert result["committed"] == 96
    assert result["arms"] == ["P-M0-R-hist-N", "P-M0-R-hist-C1"]


def test_shortcut_probe_selection_is_family_balanced() -> None:
    from scripts import a1_shortcut
    from scripts.a02_v3_decision import load_protocol

    examples = a1_shortcut.probe_examples(load_protocol())
    assert len(examples) == 140
    families: dict[str, int] = {}
    for example in examples:
        families[example["family"]] = families.get(example["family"], 0) + 1
    assert len(families) == 14
    assert set(families.values()) == {10}


def test_shortcut_probe_removes_the_named_component() -> None:
    from scripts import a1_shortcut
    from scripts.a02_v3_decision import load_protocol

    examples = a1_shortcut.probe_examples(load_protocol())
    objective = a1_shortcut.probe_cases(examples, "objective-only")[0]["request"]
    assert set(objective) == {"objective", "observations"}
    assert objective["observations"] == []
    observations = a1_shortcut.probe_cases(examples, "observations-only")[0]["request"]
    assert set(observations) == {"observations"}
    question = a1_shortcut.probe_cases(examples, "question-only")[0]["request"]
    assert set(question) == {"question", "observations"}


@needs_evidence
def test_retrospective_cohort_is_the_exposed_a03_population() -> None:
    from scripts import a1_retrospective

    cases = a1_retrospective.cohort_cases()
    assert len(cases) == 96
    assert len({case["cluster"] for case in cases}) == 48
    assert all(
        case["request"]["requested_claims"] == {"measurement": [], "relationship": []}
        for case in cases
    )


def test_no_fewshot_exemplar_is_an_a1_case(manifest: dict[str, Any]) -> None:
    cohort = {case["question"] for case in manifest["cases"]}
    for exemplar in rep.fewshot_exemplars():
        question = exemplar["request"].get("question", "")
        assert question not in cohort
        assert exemplar["action"].startswith("<tool_call>")
