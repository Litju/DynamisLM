from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from scripts import a02_v3_decision as historical
from scripts import a02_v3_synthetic as synthetic
from scripts import a03_benchmark_seal as prospective_sealer
from scripts import a03_internal_config as config
from scripts import a03_internal_seal as sealer
from scripts.research_scenarios import packaged_scenario

from a03_internal_fixtures import (
    CAUSAL,
    CAUSAL_ABSTAIN,
    EXEC,
    OWNER,
    PRACTICAL_FLAG,
    RES69,
    Packet,
    action,
    hexid,
    judgment,
    scenario_text,
    valid_packet,
)
from dynamislm.serialization import canonical_json


def sealed(packet: Packet, tmp_path: Path) -> dict[str, Any]:
    return sealer.seal(packet.write(tmp_path / "packet"))


def refused(packet: Packet, tmp_path: Path, match: str) -> None:
    with pytest.raises(sealer.PacketRefusalError, match=match):
        sealed(packet, tmp_path)


def test_valid_internal_packet_seals_with_internal_identity(tmp_path: Path) -> None:
    packet = valid_packet()
    manifest = sealed(packet, tmp_path)
    assert manifest["mode"] == manifest["evidence_class"] == "INTERNAL_OWNER_ADJUDICATED"
    assert manifest["independence"] == "NONE"
    assert (manifest["clusters"], manifest["items"]) == (48, 108)
    assert manifest["stratum_clusters"] == dict.fromkeys(config.load_config()["strata"], 12)
    assert manifest["support"]["CAUSAL_OVERREACH"] == {"items": 36, "clusters": 24, "strata": 2}
    assert manifest["support"]["PRACTICAL_MEANING"]["items"] == 24
    assert manifest == sealer.seal(tmp_path / "packet")  # deterministic
    assert "gold" not in json.dumps({k: v for k, v in manifest.items() if k != "files"}).lower()


def test_blind_export_has_no_gold_or_sampling_metadata(tmp_path: Path) -> None:
    packet = valid_packet()
    directory = packet.write(tmp_path / "packet")
    exported = sealer.blind_export(directory)
    assert tuple(exported) == sealer.BLIND_FILES
    requests = [json.loads(line) for line in exported["blind-requests.jsonl"].splitlines()]
    scenarios = [json.loads(line) for line in exported["blind-scenarios.jsonl"].splitlines()]
    assert all(set(row) == {"item_id", "scenario_id", "question"} for row in requests)
    assert all(set(row) == {"scenario_id", "scenario"} for row in scenarios)
    assert [r["item_id"] for r in requests] == sorted(r["item_id"] for r in requests)
    assert len(requests) == 108 and len(scenarios) == 48
    blob = b"".join(exported.values()).decode()
    for forbidden in (
        "gold",
        "stratum",
        "AUTHORITY_HAZARD",
        "OUT_OF_SCOPE",
        "CAUSAL_OVERREACH",
        "acceptable_actions",
        "cluster-",
        "adjudicator",
        "narrative",
    ):
        assert forbidden not in blob
    # Exporting is itself deterministic and does not depend on authoring order.
    reordered = valid_packet()
    reordered.requests.reverse()
    assert sealer.blind_export(reordered.write(tmp_path / "other")) == exported


@pytest.mark.parametrize("stratum", config.load_config()["strata"])
def test_stratum_with_eleven_clusters_is_refused(tmp_path: Path, stratum: str) -> None:
    packet = valid_packet()
    victim = next(s["cluster_id"] for s in packet.scenarios if s["stratum"] == stratum)
    packet.drop_cluster(victim)
    refused(packet, tmp_path, "below the frozen cluster|insufficient")


def observe_only(*ids: str) -> dict[str, Any]:
    return judgment(
        "OBSERVATION_ONLY",
        [action(analysis="NONE", operation="NONE", ids=ids, measurement=("OBSERVED_VALUE",))],
        allowed=("OBSERVED_VALUE",),
    )


def test_cluster_with_one_or_four_items_is_refused(tmp_path: Path) -> None:
    packet = valid_packet()
    gone = packet.items_of(packet.scenarios[0]["cluster_id"])[-1]["item_id"]
    packet.requests = [r for r in packet.requests if r["item_id"] != gone]
    packet.gold = [g for g in packet.gold if g["item_id"] != gone]
    refused(packet, tmp_path / "one", "outside the frozen 2 to 3")
    packet = valid_packet()
    cluster = next(s["cluster_id"] for s in packet.scenarios if s["stratum"] == "AUTHORITY_HAZARD")
    assert len(packet.items_of(cluster)) == 3
    for k, text in enumerate(("zyxqv wvuts rqpon", "mlkji hgfed cbazy")):
        item = hexid(f"extra-{k}", 16)
        packet.requests.append(
            {"item_id": item, "cluster_id": cluster, "critical_families": [], "question": text}
        )
        packet.gold.append(
            {
                "item_id": item,
                "adjudicator_id": OWNER,
                "judgment": observe_only(f"observation-{k + 1}"),
                "rationale": "extra",
            }
        )
    refused(packet, tmp_path / "four", "outside the frozen 2 to 3")


def test_shifted_scaled_and_reflected_series_are_one_series() -> None:
    base = [0.2, 0.31, 0.27]
    keys = sealer.series_keys(base, 9)
    assert sealer.series_keys([10 * v + 4 for v in base], 9) == keys
    assert sealer.series_keys([-3 * v + 1 for v in base], 9) == keys
    assert sealer.series_keys([0.2, 0.27, 0.31], 9) != keys
    # Two-point series: normalization is vacuous, so shift and scale copies are detected directly.
    two = sealer.series_keys([1.0, 2.0], 9)
    assert two & sealer.series_keys([11.0, 12.0], 9)  # shifted copy
    assert two & sealer.series_keys([2.0, 4.0], 9)  # rescaled copy
    assert not two & sealer.series_keys([3.0, 7.0], 9)
    assert sealer.series_keys([], 9) == frozenset()
    assert sealer.series_keys([5.0, 5.0, 5.0], 9) == {("RAW", (5.0, 5.0, 5.0))}


def replace_scenario(packet: Packet, cluster_index: int, index: int, **kw: Any) -> None:
    scenario_id, text = scenario_text(index, **kw)
    row = packet.scenarios[cluster_index]
    row["scenario_id"], row["scenario"] = scenario_id, text


def test_shift_and_scale_duplicate_observation_series_is_refused(tmp_path: Path) -> None:
    packet = valid_packet()
    from scripts.research_scenarios import SyntheticScenario

    from dynamislm.serialization import from_canonical_json

    original = from_canonical_json(packet.scenarios[3]["scenario"], SyntheticScenario)
    values = tuple(sealer.scenario_series(original))
    replace_scenario(packet, 9, 300, values=tuple(round(7 * v + 0.5, 6) for v in values))
    refused(packet, tmp_path, "series is shared")


def test_exposed_or_packaged_series_and_scenarios_are_refused(tmp_path: Path) -> None:
    packet = valid_packet()
    replace_scenario(packet, 4, 301, values=(0.25, 0.375))  # packaged absolute-change series
    refused(packet, tmp_path / "exact", "exposed A0.2 or packaged observation series")
    packet = valid_packet()
    replace_scenario(packet, 4, 302, values=(0.30, 0.425))  # same difference: shifted copy
    refused(packet, tmp_path / "shift", "exposed A0.2 or packaged observation series")
    packaged = packaged_scenario("absolute-change")
    assert sealer.series_keys(sealer.scenario_series(packaged), 9) & sealer.exposure_series(9)


def test_duplicated_scenario_content_under_a_new_identity_is_refused(tmp_path: Path) -> None:
    from dataclasses import replace

    from scripts.research_scenarios import SyntheticScenario

    from dynamislm.serialization import from_canonical_json

    packet = valid_packet()
    clone = replace(
        from_canonical_json(packet.scenarios[2]["scenario"], SyntheticScenario),
        scenario_id="eval-" + "a" * 12,
    )
    packet.scenarios[7].update(scenario_id=clone.scenario_id, scenario=canonical_json(clone))
    refused(packet, tmp_path, "shared between clusters")


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        ("identity", ("ath-1", "other-label")),
        ("identity", ("other-ath", "label-1")),
        ("observations", {"obs-1"}),
        ("records", {"rec-1"}),
        ("artifacts", {"art-1"}),
        ("content", "content-1"),
    ],
)
def test_shared_fictional_identity_or_source_is_refused(kind: str, value: Any) -> None:
    def cluster(tag: int, **shared: Any) -> dict[str, Any]:
        return {
            "digest": f"digest-{tag}",
            "content": f"content-{tag}",
            "series": [0.1 * tag, 0.2 * tag * tag, 0.9],
            "identity": (f"ath-{tag}", f"label-{tag}"),
            "observations": {f"obs-{tag}"},
            "records": {f"rec-{tag}"},
            "artifacts": {f"art-{tag}"},
            "narrative": frozenset({(f"n{tag}", "x", "y")}),
            **shared,
        }

    cfg = config.load_config()
    sealer._distinct_clusters(cfg, {"a": cluster(1), "b": cluster(2)})
    with pytest.raises(sealer.PacketRefusalError, match="shared between clusters"):
        sealer._distinct_clusters(cfg, {"a": cluster(1), "b": cluster(2, **{kind: value})})


def test_cluster_narratives_that_overlap_are_refused(tmp_path: Path) -> None:
    packet = valid_packet()
    packet.scenarios[1]["narrative"] = packet.scenarios[0]["narrative"] + " extra"
    refused(packet, tmp_path, "narratives overlap")


def test_paraphrase_only_cluster_and_identical_gold_are_refused(tmp_path: Path) -> None:
    packet = valid_packet()
    first, second = packet.items_of(packet.scenarios[0]["cluster_id"])
    second["question"] = first["question"] + " please"
    refused(packet, tmp_path / "text", "paraphrase-only")
    packet = valid_packet()
    first, second = packet.items_of(packet.scenarios[0]["cluster_id"])
    packet.gold_of(second["item_id"])["judgment"] = json.loads(
        json.dumps(packet.gold_of(first["item_id"])["judgment"])
    )
    refused(packet, tmp_path / "gold", "must differ in gold")


def test_near_duplicate_question_across_clusters_is_refused(tmp_path: Path) -> None:
    packet = valid_packet()
    source = packet.items_of(packet.scenarios[0]["cluster_id"])[0]
    target = packet.items_of(packet.scenarios[20]["cluster_id"])[0]
    target["question"] = source["question"] + " tail"
    refused(packet, tmp_path, "questions overlap across clusters")


@pytest.mark.parametrize(
    "question",
    [
        prospective_sealer.EXPOSED_RESEARCH_CLI_QUESTION,
        "Report how much jump height changed between the two tests.",
        "absolute change",
    ],
)
def test_exposed_phrasing_is_refused(tmp_path: Path, question: str) -> None:
    packet = valid_packet()
    packet.items_of(packet.scenarios[5]["cluster_id"])[0]["question"] = question
    refused(packet, tmp_path, "exposed A0.2")


def test_heldout_objectives_questions_and_light_edits_are_refused(tmp_path: Path) -> None:
    examples = list(historical.heldout_examples(historical.load_protocol()))
    for k, field in enumerate(("objective", "question")):
        text = examples[3]["request"][field]
        packet = valid_packet()
        packet.items_of(packet.scenarios[6]["cluster_id"])[0]["question"] = text
        refused(packet, tmp_path / f"exact-{k}", "exposed A0.2")
        edited = valid_packet()
        edited.items_of(edited.scenarios[6]["cluster_id"])[0]["question"] = text + " today"
        refused(edited, tmp_path / f"edit-{k}", "exposed A0.2")


def test_every_exposed_heldout_request_text_is_covered() -> None:
    texts = {sealer.shingles(t, 3) for t in sealer.exposure_texts()}
    for row in list(historical.heldout_examples(historical.load_protocol()))[:20]:
        assert sealer.shingles(row["request"]["question"], 3) in texts
    assert any("measurement" in " ".join(g) for t in texts for g in t)
    assert synthetic.TEMPLATES  # the template corpus is the exposure source, not a copy


def test_missing_or_non_owner_adjudication_is_refused(tmp_path: Path) -> None:
    packet = valid_packet()
    packet.gold.pop()
    refused(packet, tmp_path / "missing", "unresolved|missing adjudication")
    packet = valid_packet()
    packet.gold[0]["adjudicator_id"] = "someone-else"
    refused(packet, tmp_path / "other", "non-owner")
    packet = valid_packet()
    packet.gold.append(dict(packet.gold[0]))
    refused(packet, tmp_path / "dup", "duplicate gold")


@pytest.mark.parametrize(
    "mutation",
    [
        {"independence": "PARTIAL"},
        {"owner_authored_all_items": False},
        {"gold_recorded_before_inference": False},
        {"no_a02_template_or_generator_reuse": False},
        {"schema": "DYNAMISLM_A03_PROSPECTIVE_PACKET_V1"},
    ],
)
def test_attestation_is_required_and_cannot_claim_independence(
    tmp_path: Path, mutation: dict[str, Any]
) -> None:
    packet = valid_packet()
    packet.attestation.update(mutation)
    refused(packet, tmp_path, "owner attestation")
    packet = valid_packet()
    del packet.attestation["owner_id"]
    with pytest.raises(ValueError, match="expected fields"):
        sealed(packet, tmp_path / "fields")


def test_family_gold_cannot_allow_the_family_claim(tmp_path: Path) -> None:
    packet = valid_packet()
    item = next(r for r in packet.requests if "CAUSAL_OVERREACH" in r["critical_families"])
    gold = packet.gold_of(item["item_id"])["judgment"]
    gold["allowed_claims"]["relationship"] = [CAUSAL]
    refused(packet, tmp_path, "must not allow the family's claim level")


def test_only_the_res69_absolute_change_may_be_an_execution_control(tmp_path: Path) -> None:
    packet = valid_packet()
    item = next(r for r in packet.requests if r["question"])
    other = "dynamislm:registered-operation:unit-normalization@1.0.0"
    packet.gold_of(item["item_id"])["judgment"] = {
        **judgment("EXECUTE", [action(operation=other)], allowed=("NUMERICAL_CHANGE",)),
        "dispatch_operation": other,
    }
    refused(packet, tmp_path, "only the RES-69 absolute change|invalid gold")
    assert RES69.endswith("longitudinal-absolute-change-v1@1.0.0")


def test_insufficient_effective_support_is_refused_after_valid_structure(tmp_path: Path) -> None:
    packet = valid_packet()
    for cluster in (
        s["cluster_id"] for s in packet.scenarios if s["stratum"] == "AUTHORITY_HAZARD"
    ):
        for k, item in enumerate(packet.items_of(cluster)):
            packet.gold_of(item["item_id"])["judgment"] = observe_only(f"observation-{k + 1}")
            item["critical_families"] = []
    refused(packet, tmp_path, "insufficient effective support")


@pytest.mark.parametrize("family", ["CAUSAL_OVERREACH", "PRACTICAL_MEANING"])
def test_missing_causal_or_practical_family_support_is_refused(tmp_path: Path, family: str) -> None:
    packet = valid_packet()
    for item in packet.requests:
        if family in item["critical_families"]:
            item["critical_families"].remove(family)
    refused(packet, tmp_path, f"insufficient effective support for {family}")


def test_family_support_needs_two_strata_and_twenty_four_items(tmp_path: Path) -> None:
    strata = {s["cluster_id"]: s["stratum"] for s in (valid_packet().scenarios)}
    packet = valid_packet()
    for item in packet.requests:  # causal items only in one stratum
        if strata[item["cluster_id"]] == "OUT_OF_SCOPE" and item["critical_families"] == [
            "CAUSAL_OVERREACH"
        ]:
            item["critical_families"] = []
    refused(packet, tmp_path / "strata", "insufficient family support for CAUSAL_OVERREACH")
    packet = valid_packet()
    dropped = next(
        i
        for i in packet.requests
        if strata[i["cluster_id"]] == "OUT_OF_SCOPE"
        and i["critical_families"] == ["PRACTICAL_MEANING"]
    )
    dropped["critical_families"] = []  # 23 practical items across two strata
    refused(packet, tmp_path / "items", "insufficient family support for PRACTICAL_MEANING")


def test_prospective_and_internal_packets_cannot_cross(tmp_path: Path) -> None:
    packet = valid_packet()
    directory = packet.write(tmp_path / "internal")
    with pytest.raises((ValueError, FileNotFoundError, KeyError)):
        prospective_sealer.seal(directory)
    prospective = tmp_path / "prospective"
    prospective.mkdir()
    for name in prospective_sealer.FILES:
        (prospective / name).write_bytes(b"{}\n")
    with pytest.raises(sealer.PacketRefusalError, match="packet files differ"):
        sealer.seal(prospective)
    assert sealer.SCHEMA != "DYNAMISLM_A03_PROSPECTIVE_PACKET_V1"


def test_scenario_identity_and_bytes_must_be_valid(tmp_path: Path) -> None:
    packet = valid_packet()
    packet.scenarios[0]["scenario_id"] = "eval-" + "b" * 12
    refused(packet, tmp_path / "id", "scenario identity differs")
    packet = valid_packet()
    packet.scenarios[0]["scenario_id"] = "named-by-stratum"
    refused(packet, tmp_path / "opaque", "opaque identifier")
    packet = valid_packet()
    packet.requests[0]["item_id"] = "familiar-intent-1"
    refused(packet, tmp_path / "item", "opaque identifier")
    packet = valid_packet()
    packet.scenarios[0]["scenario"] = packet.scenarios[0]["scenario"].replace(" ", "  ", 1) + " "
    refused(packet, tmp_path / "bytes", "validator")
    packet = valid_packet()
    packet.scenarios[0]["stratum"] = "SOMETHING_ELSE"
    refused(packet, tmp_path / "stratum", "unknown sampling stratum")
    packet = valid_packet()
    packet.requests[0]["cluster_id"] = "unknown-cluster"
    refused(packet, tmp_path / "cluster", "unknown cluster")


def test_gold_cannot_be_hidden_in_requests_or_use_unknown_references(tmp_path: Path) -> None:
    packet = valid_packet()
    packet.requests[0]["judgment"] = {}
    with pytest.raises(ValueError, match="expected fields"):
        sealed(packet, tmp_path / "leak")
    packet = valid_packet()
    first = packet.requests[0]["item_id"]
    packet.gold_of(first)["judgment"] = judgment(
        "EXECUTE", [action(ids=("observation-1", "observation-9"))], allowed=("NUMERICAL_CHANGE",)
    )
    refused(packet, tmp_path / "ref", "invalid gold judgment")
    assert CAUSAL_ABSTAIN and EXEC and PRACTICAL_FLAG


def test_execution_gold_that_the_engine_cannot_execute_is_refused(tmp_path: Path) -> None:
    packet = valid_packet()
    item = next(
        r
        for r in packet.requests
        if packet.gold_of(r["item_id"])["judgment"]["control"] == "EXECUTE"
    )
    # A single observation cannot satisfy the RES-69 two-entry support: valid V3 shape, no result.
    gold = packet.gold_of(item["item_id"])["judgment"]
    gold["acceptable_actions"] = [action(ids=("observation-1",))]
    gold["preferred_action"] = gold["acceptable_actions"][0]
    refused(packet, tmp_path, "not executable by the engine")


# ------------------------------------------------------------------ two-point screen (P1 review)


def collide(left: list[float], right: list[float]) -> bool:
    return bool(sealer.series_keys(left, 9, 6) & sealer.series_keys(right, 9, 6))


def test_two_point_rule_is_a_documented_numerical_duplicate_screen() -> None:
    cfg = config.load_config()["distinctness"]
    assert cfg["two_point_policy"] == "NUMERICAL_DUPLICATE_SCREEN_ONLY"
    assert cfg["two_point_decimals"] == 6
    protocol = config.PROTOCOL_PATH.read_text()
    assert "does not establish shape independence" in protocol
    assert "no evidence of scientific independence" in protocol
    base = [0.30, 0.45]
    assert collide(base, base)
    assert collide(base, [0.45, 0.30])  # time-reversed copy
    assert collide(base, [-0.30, -0.45])  # reflected copy
    assert collide(base, [0.40, 0.55])  # shifted copy (same difference)
    assert collide(base, [0.60, 0.90])  # rescaled copy (same ratio)
    assert collide(base, [0.45, 0.675])  # ratio read in the other direction (1.5 and 2/3)
    assert collide(base, [0.30000004, 0.45000004])  # inside the 6-decimal rounding
    assert not collide(base, [0.31, 0.52])
    assert not collide(base, [0.30, 0.46])


def test_two_point_screen_limits_are_false_negatives_beyond_rounding_and_nonlinear_copies() -> None:
    base = [0.30, 0.45]
    assert not collide(base, [0.3001, 0.4502])  # near-copy beyond the rounding is not caught
    assert not collide(base, [0.30**2, 0.45**2])  # a nonlinear transform is not caught
    assert collide([0.0, 2.0], [0.0, 5.0])  # a zero value makes all rescalings equal (a rejection)


def test_constant_single_and_nonfinite_series_are_screened_on_raw_values() -> None:
    assert not collide([0.3, 0.3], [0.5, 0.5])
    assert collide([0.3, 0.3], [0.3, 0.3])
    assert not collide([0.3], [0.5]) and collide([0.3], [0.3])
    assert sealer.series_keys([0.3, float("nan")], 9, 6) == {("NONFINITE", ("0.3", "nan"))}
    keys = sealer.series_keys([0.3, 0.45], 9, 6)
    assert {kind for kind, *_ in keys} == {"RAW", "SORTED", "ABSDELTA", "RATIO"}


def test_a_forty_eight_cluster_two_point_cohort_is_sealable(tmp_path: Path) -> None:
    manifest = sealed(valid_packet(points=2), tmp_path)
    assert manifest["clusters"] == 48 and manifest["independence"] == "NONE"


@pytest.mark.parametrize(
    "transform",
    [
        lambda a, b: (b, a),  # reversed
        lambda a, b: (a + 0.1, b + 0.1),  # shifted
        lambda a, b: (3 * a, 3 * b),  # rescaled
        lambda a, b: (-a, -b),  # reflected
        lambda a, b: (a + 1e-8, b + 1e-8),  # numerical near-duplicate
    ],
    ids=["reversed", "shifted", "rescaled", "reflected", "near_duplicate"],
)
def test_two_point_copies_across_clusters_are_refused(tmp_path: Path, transform: Any) -> None:
    from a03_internal_fixtures import two_point

    packet = valid_packet(points=2)
    copy = transform(*two_point(3))
    replace_scenario(packet, 11, 700, values=copy)
    refused(packet, tmp_path, "series is shared")


def test_two_point_clusters_still_need_unique_identity_observations_records_and_provenance(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    from scripts.research_scenarios import SyntheticScenario

    from dynamislm.serialization import from_canonical_json

    packet = valid_packet(points=2)
    original = from_canonical_json(packet.scenarios[2]["scenario"], SyntheticScenario)
    clone = replace(original, scenario_id="eval-" + "c" * 12)
    packet.scenarios[8].update(scenario_id=clone.scenario_id, scenario=canonical_json(clone))
    refused(packet, tmp_path, "shared between clusters")
