"""Frozen A1 diagnostic cohort: 48 synthetic cases in 24 contrastive clusters (RES-832).

Every case is one canonical scenario plus one question. Gold is derived mechanically from a
declared intent spec (analysis class, referenced observations, requested claim levels) with the
operation taken from the same registry authority the runtime uses
(``a02_v3_contract.operation_for``). The question text is authored independently and is checked
against a committed trigger lexicon, so a phrasing/gold disagreement is a validation failure
rather than a silent mismatch.

Nothing here is empirical. No A0.2 or RES-774 case, template, measurement range or phrasing is
reused; the identity namespace is ``synthetic-a1``. Generating this cohort authorizes no
training and no inference.
"""

from __future__ import annotations

import functools
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import dynamislm as d
from dynamislm.measurement.identity import UnitReference
from dynamislm.population import ReuseStatus, SubgroupSeparability, qualify_canonical_source
from dynamislm.provenance import LineageRelation
from scripts import a02_v3_contract as v3
from scripts.research_scenarios import SyntheticScenario, validate_scenario

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "experiments/a1/cases-v1.json"
SCHEMA = "DYNAMISLM_A1_CASE_MANIFEST_V1"
NAMESPACE = "synthetic-a1"
ABS = "SCALAR_ABSOLUTE_CHANGE"
NONE = v3.NONE

# ---------------------------------------------------------------- synthetic registry authority

UNITS = {
    "m": UnitReference(d.ScientificIdentifier(NAMESPACE, "unit", "metre", "1.0.0"), "m"),
    "cm": UnitReference(d.ScientificIdentifier(NAMESPACE, "unit", "centimetre", "1.0.0"), "cm"),
    "s": UnitReference(d.ScientificIdentifier(NAMESPACE, "unit", "second", "1.0.0"), "s"),
    "N": UnitReference(d.ScientificIdentifier(NAMESPACE, "unit", "newton", "1.0.0"), "N"),
    "m/s": UnitReference(
        d.ScientificIdentifier(NAMESPACE, "unit", "metre-per-second", "1.0.0"), "m/s"
    ),
}

MEASUREMENTS: dict[str, dict[str, str]] = {
    # key -> construct, test family, protocol, measurand, metric, default unit, human label
    "jump-height": {
        "construct": "jump",
        "family": "countermovement-jump",
        "protocol": "cmj-standard",
        "measurand": "jump-height",
        "metric": "cmj-height",
        "unit": "m",
        "label": "countermovement jump height",
    },
    "sprint-time": {
        "construct": "sprint",
        "family": "sprint-10m",
        "protocol": "sprint-standard",
        "measurand": "sprint-time",
        "metric": "sprint-10m-time",
        "unit": "s",
        "label": "10 m sprint time",
    },
    "peak-force": {
        "construct": "force",
        "family": "isometric-mid-thigh-pull",
        "protocol": "imtp-standard",
        "measurand": "peak-force",
        "metric": "imtp-peak-force",
        "unit": "N",
        "label": "isometric peak force",
    },
    "session-distance": {
        "construct": "external-load",
        "family": "gps-session",
        "protocol": "gps-standard",
        "measurand": "total-distance",
        "metric": "session-total-distance",
        "unit": "m",
        "label": "session total distance",
    },
    "aerobic-speed": {
        "construct": "endurance",
        "family": "incremental-treadmill",
        "protocol": "aerobic-standard",
        "measurand": "maximal-aerobic-speed",
        "metric": "maximal-aerobic-speed",
        "unit": "m/s",
        "label": "maximal aerobic speed",
    },
    "nordic-force": {
        "construct": "eccentric-strength",
        "family": "nordic-hamstring",
        "protocol": "nordic-standard",
        "measurand": "eccentric-peak-force",
        "metric": "nordic-eccentric-peak-force",
        "unit": "N",
        "label": "Nordic eccentric peak force",
    },
}

DEVICE_KEYS = frozenset(
    {
        "force-platform",
        "timing-gates",
        "gps-unit",
        "instrumented-treadmill",
        "nordic-load-cell-frame",
    }
)

POPULATION_TEXT = (
    "SYNTHETIC elite men's senior first-team top-division professional association football"
)


def ref(kind: str, key: str) -> d.RegistryReference:
    return d.RegistryReference(
        d.ScientificIdentifier(NAMESPACE, kind, key, "1.0.0"),
        f"SYNTHETIC A1 {key}",
    )


def inst(kind: str, key: str) -> d.InstanceIdentifier:
    return d.InstanceIdentifier(kind, f"SYNTHETIC-A1-{key}")


def metric_stable_id(measurement: str) -> str:
    return ref("metric", MEASUREMENTS[measurement]["metric"]).stable_id


def protocol_stable_id(protocol: str) -> str:
    return ref("protocol", protocol).stable_id


def device_stable_id(device: str) -> str:
    return ref("device", device).stable_id


def human_measurement(measurement: str) -> str:
    return MEASUREMENTS[measurement]["label"]


def human_device(device: str) -> str:
    return device.replace("-", " ")


def human_protocol(protocol: str) -> str:
    return protocol.replace("-", " ")


# ---------------------------------------------------------------- scenario construction


def _observation(
    *,
    case_key: str,
    index: int,
    measurement: str,
    value: float,
    unit: str,
    protocol: str,
    device: str,
    method: str,
    observed_at: datetime,
    decision: Any,
    athlete: Any,
    team: Any,
    season: Any,
    session: Any,
) -> Any:
    spec = MEASUREMENTS[measurement]
    key = f"{case_key}-{index}"
    artifact_id = inst("artifact", key)
    artifact = d.SourceArtifact(
        artifact_id,
        d.canonical_hash((case_key, index, value, unit, protocol, device)),
        "application/synthetic",
    )
    acquisition = d.AcquisitionRecord(
        inst("acquisition", key), ref("device", device), artifact_id, sensor_channel="SYNTHETIC-A1"
    )
    obs_id = inst("observation", key)
    run = d.ProcessingRun(
        inst("processing-run", key),
        (artifact_id,),
        ref("processing-method", method),
        (),
        "SYNTHETIC-A1-1",
        obs_id,
    )
    context = d.ObservationContext(
        context_id=inst("context", key),
        athlete_id=athlete.athlete_id,
        session_id=session.session_id,
        test_instance_id=inst("test-instance", case_key),
        trial_id=inst("trial", key),
        observed_at=observed_at,
        population_context=POPULATION_TEXT,
    )
    identity = d.MeasurementIdentity(
        identity_id=ref("measurement-identity", spec["metric"]).identifier,
        semantic=d.SemanticIdentity(
            construct=ref("construct", spec["construct"]),
            test_family=ref("test-family", spec["family"]),
            protocol=ref("protocol", protocol),
            measurand=ref("measurand", spec["measurand"]),
            metric_definition=ref("metric", spec["metric"]),
        ),
        acquisition=d.AcquisitionIdentity(
            device=ref("device", device), raw_artifact=artifact_id, sensor_channel="SYNTHETIC-A1"
        ),
        processing=d.ProcessingIdentity(),
        version=d.VersionIdentity(
            processing_method=ref("processing-method", method),
            method_registry_version="1.0.0",
            software_version="SYNTHETIC-A1-1",
        ),
    )
    observation = d.ScientificMeasurementObservation(
        observation_id=obs_id,
        context=context,
        identity=identity,
        result=d.MeasurementResult(
            result_id=inst("result", key),
            value=d.ScalarValue(value),
            unit=UNITS[unit],
            classification=d.ScientificClassification(d.ValueOrigin.DIRECT_MEASUREMENT, ()),
        ),
        provenance=d.Provenance(
            provenance_id=inst("provenance", key),
            source_artifacts=(artifact,),
            acquisitions=(acquisition,),
            processing_runs=(run,),
            lineage_edges=(
                d.LineageEdge(
                    artifact_id.qualified,
                    acquisition.acquisition_id.qualified,
                    LineageRelation.ACQUIRED_AS,
                ),
                d.LineageEdge(
                    acquisition.acquisition_id.qualified,
                    run.processing_run_id.qualified,
                    LineageRelation.PROCESSED_AS,
                ),
                d.LineageEdge(
                    run.processing_run_id.qualified, obs_id.qualified, LineageRelation.PRODUCED
                ),
            ),
        ),
    )
    world = d.FootballWorldContext(
        context_id=inst("football-world-context", key),
        athlete=athlete,
        team=team,
        season=season,
        session=session,
        observation_context_id=context.context_id,
    )
    binding = d.SourceArtifactQualificationBinding.from_decision(decision, (artifact_id,))
    return d.build_longitudinal_observation_entry(observation, world, (binding,))


def build_scenario(spec: dict[str, Any]) -> SyntheticScenario:
    """Build one validated synthetic scenario from a declarative observation list."""
    case_key = spec["case_id"]
    season_ref = ref("season", "2026-27")
    season = d.SeasonIdentity(season_ref.identifier, "SYNTHETIC season")
    athlete = d.AthleteIdentity(inst("athlete", case_key), f"SYNTHETIC athlete {case_key}")
    team = d.TeamIdentity(
        inst("team", "club-first-team"),
        d.SquadLevel.FIRST_TEAM,
        d.TeamKind.CLUB_SQUAD,
        display_label="SYNTHETIC elite club first team",
    )
    dimensions = (
        (d.PopulationDimension.SEX, d.Sex.MALE),
        (d.PopulationDimension.AGE_CLASS, d.AgeClass.SENIOR),
        (d.PopulationDimension.SPORT, d.Sport.ASSOCIATION_FOOTBALL),
        (d.PopulationDimension.PROFESSIONAL_STATUS, d.ProfessionalStatus.PROFESSIONAL),
        (d.PopulationDimension.SQUAD_LEVEL, d.SquadLevel.FIRST_TEAM),
        (d.PopulationDimension.COMPETITION_TIER, d.CompetitionTier.TOP_DOMESTIC_DIVISION),
    )
    population = d.PopulationIdentity(
        sex=d.Sex.MALE,
        age_class=d.AgeClass.SENIOR,
        sport=d.Sport.ASSOCIATION_FOOTBALL,
        professional_status=d.ProfessionalStatus.PROFESSIONAL,
        squad_level=d.SquadLevel.FIRST_TEAM,
        competition_tier=d.CompetitionTier.TOP_DOMESTIC_DIVISION,
        season=season,
        evidence_bindings=tuple(
            d.PopulationEvidenceBinding(dim, value, ref("evidence", dim.value))
            for dim, value in dimensions
        ),
    )
    source = d.CanonicalSource(
        source_id=ref("source", "fictional-a1-session"),
        source_revision="SYNTHETIC-1",
        population=population,
        cohort_scope=d.CohortScope(
            d.CohortScopeType.WHOLE_COHORT, SubgroupSeparability.EXACT_TARGET_COHORT
        ),
        data_origin=d.SourceDataOrigin.SYNTHETIC,
        data_granularity=d.DataGranularity.ATHLETE_LEVEL,
        license_reuse=d.LicenseReuseMetadata(ReuseStatus.UNKNOWN),
    )
    decision = qualify_canonical_source(source)
    start = datetime(2026, 9, 7, 9, tzinfo=UTC)
    span = max(row["day"] for row in spec["observations"])
    session = d.TestingSession(
        session_id=inst("session", case_key),
        team=team,
        season=season,
        start_at=start,
        end_at=start + timedelta(days=span + 1),
    )
    entries = tuple(
        _observation(
            case_key=case_key,
            index=index,
            measurement=row["measurement"],
            value=row["value"],
            unit=row["unit"],
            protocol=row["protocol"],
            device=row["device"],
            method=f"{row['protocol']}-method",
            observed_at=start + timedelta(days=row["day"], minutes=10 * (index + 1)),
            decision=decision,
            athlete=athlete,
            team=team,
            season=season,
            session=session,
        )
        for index, row in enumerate(spec["observations"])
    )
    record = d.build_longitudinal_record(
        athlete, entries, d.LongitudinalRecordOrigin.SYNTHETIC_DETERMINISTIC
    )
    source_input = (
        d.build_multi_source_analysis_input(
            athlete, entries, d.MultiSourceAnalysisScope.SAME_SESSION
        )
        if len(entries) > 1
        else None
    )
    scenario = SyntheticScenario(
        case_key,
        source_input,
        (record,) if entries else (),
    )
    validate_scenario(scenario)
    return scenario


def observation_rows(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Reproduce ``BoundRequest.model_request()`` observation rows exactly."""
    start = datetime(2026, 9, 7, 9, tzinfo=UTC)
    return [
        {
            "date": (start + timedelta(days=row["day"], minutes=10 * (index + 1))).isoformat(),
            "measurement": metric_stable_id(row["measurement"]),
            "protocol": protocol_stable_id(row["protocol"]),
            "device": device_stable_id(row["device"]),
            "value": row["value"],
            "unit": row["unit"],
        }
        for index, row in enumerate(spec["observations"])
    ]


def operational_request(spec: dict[str, Any]) -> dict[str, Any]:
    """The exact deployed request: ``research_ask.prepare_request(...).model_request()``.

    The host that produced the A0.3 failure supplied no typed claim request, so
    ``requested_claims`` is semantically empty on both principal representations. Claim
    preservation therefore depends entirely on parsing the question text. The enrichment arm
    that populates this field is a separate, disclosed intervention (D3), never the principal
    comparison.
    """
    from scripts import research_ask

    bound = research_ask.prepare_request(build_scenario(spec), spec["question"])
    return bound.model_request()


@functools.cache
def operational_row(spec_key: str, spec_json: str) -> dict[str, Any]:
    """Memoised deployed request; the scenario builders are pure and expensive."""
    return operational_request(v3.json_object(spec_json))


def deployed_request(spec: dict[str, Any]) -> dict[str, Any]:
    return operational_row(spec["case_id"], v3.canonical(spec))


def gold_action(spec: dict[str, Any]) -> dict[str, Any]:
    """Mechanically derived gold: registry operation authority, never a free-text judgment."""
    intent = spec["intent"]
    ids = [f"observation-{index}" for index in intent["observations"]]
    action = {
        "analysis_class": intent["analysis_class"],
        "observation_ids": ids,
        "operation": v3.operation_for(intent["analysis_class"], len(ids)),
        "target_claims": {
            "measurement": list(intent["claims"]["measurement"]),
            "relationship": list(intent["claims"]["relationship"]),
        },
    }
    v3.validate_arguments(action, [f"observation-{i}" for i in range(1, v3.MAX_OBSERVATIONS + 1)])
    return v3.normalize_action(action)


def load_manifest() -> dict[str, Any]:
    data = CASES_PATH.read_bytes()
    manifest = v3.json_object(data.decode("utf-8"))
    if manifest.get("schema") != SCHEMA or set(manifest) != {"schema", "cases", "manifest_sha256"}:
        raise ValueError("A1 case manifest schema differs")
    if data != (v3.canonical(manifest) + "\n").encode():
        raise ValueError("A1 case manifest is not canonical JSON")
    if digest_of_cases(manifest["cases"]) != manifest["manifest_sha256"]:
        raise ValueError("A1 case manifest is not bound to its own digest")
    validate_manifest(manifest)
    return manifest


# ---------------------------------------------------------------- validation


def digest_of_cases(cases: list[dict[str, Any]]) -> str:
    payload = v3.canonical({"schema": SCHEMA, "cases": cases}).encode()
    return v3.sha256(payload)


def validate_manifest(manifest: dict[str, Any]) -> None:
    cases = manifest["cases"]
    if len(cases) != 48:
        raise ValueError("A1 cohort must contain exactly 48 cases")
    clusters: dict[str, list[dict[str, Any]]] = {}
    seen: set[str] = set()
    for case in cases:
        if case["case_id"] in seen:
            raise ValueError("duplicate A1 case id")
        seen.add(case["case_id"])
        clusters.setdefault(case["cluster"], []).append(case)
    if len(clusters) != 24 or any(len(group) != 2 for group in clusters.values()):
        raise ValueError("A1 cohort must contain 24 clusters of exactly two cases")

    # Allocation.
    expected = {
        "EXECUTABLE": 16,
        "NOT_EXPOSED": 8,
        "CLAIM_PRESERVATION": 10,
        "ABSTENTION": 8,
        "HAZARD": 6,
    }
    observed: dict[str, int] = {name: 0 for name in expected}
    for case in cases:
        observed[case["stratum"]] += 1
        gold = gold_action(case)
        if case["stratum"] == "EXECUTABLE" and gold["operation"] == NONE:
            raise ValueError("executable case must name an exposed registered operation")
        if case["stratum"] == "NOT_EXPOSED" and (
            gold["analysis_class"] == NONE or gold["operation"] != NONE
        ):
            raise ValueError("not-exposed case must name a registered class with operation NONE")
        if case["stratum"] in {"ABSTENTION", "HAZARD"} and (
            gold["analysis_class"] != NONE or gold["operation"] != NONE or gold["observation_ids"]
        ):
            raise ValueError("abstention and hazard cases must request no action")
        if case["stratum"] == "CLAIM_PRESERVATION" and gold["operation"] == NONE:
            raise ValueError("claim-preservation case must keep an executable operation")
        if gold["observation_ids"] != sorted(
            gold["observation_ids"], key=lambda item: int(item.split("-")[1])
        ):
            raise ValueError("gold observation order differs")
        if len(case["observations"]) < 1:
            raise ValueError("case must carry at least one observation")
        for row in case["observations"]:
            if row["measurement"] not in MEASUREMENTS or row["unit"] not in UNITS:
                raise ValueError("case observation names an unknown synthetic measurement or unit")
            spec = MEASUREMENTS.get(row["measurement"])
            if spec is None or row["protocol"] != spec["protocol"]:
                raise ValueError("case observation protocol differs from its measurement authority")
            if row["device"] not in DEVICE_KEYS:
                raise ValueError("case observation names an unknown synthetic device")
            if row["unit"] != spec["unit"]:
                raise ValueError("case observation unit differs from its measurement authority")
            if not isinstance(row["value"], int | float) or not 0 < row["value"] < 1e6:
                raise ValueError("case observation value is outside the synthetic numeric bound")
            if not 0 <= row["day"] <= 60:
                raise ValueError("case observation day offset is outside the synthetic bound")
        if len(case["question"].encode()) > 900:
            raise ValueError("A1 question exceeds the authored bound")
        if any(
            level not in v3.MEASUREMENT_LEVELS for level in gold["target_claims"]["measurement"]
        ):
            raise ValueError("gold measurement claim level differs")
        if any(
            level not in v3.RELATIONSHIP_LEVELS for level in gold["target_claims"]["relationship"]
        ):
            raise ValueError("gold relationship claim level differs")
    if observed != expected:
        raise ValueError(f"A1 stratum allocation differs: {observed}")

    subset = [c for c in cases if c["subset_selection"]]
    if len(subset) < 8 or any(c["stratum"] != "EXECUTABLE" for c in subset):
        raise ValueError("at least eight executable cases must require observation selection")
    for case in subset:
        if not 3 <= len(case["observations"]) <= 5:
            raise ValueError("observation-selection case must carry three to five observations")
        if len(case["intent"]["observations"]) != 2:
            raise ValueError("observation-selection case must reference exactly two observations")
    if sum(1 for c in cases if c["novel_phrasing"]) < 12:
        raise ValueError("at least twelve A1 cases must use novel phrasing")
    if sum(1 for c in cases if c["contrast"] == "QUESTION") + sum(
        1 for c in cases if c["contrast"] == "OBSERVATIONS"
    ) != 48 or any(c["contrast"] not in {"QUESTION", "OBSERVATIONS"} for c in cases):
        raise ValueError("every A1 case must declare its cluster contrast")
    for cluster, group in clusters.items():
        kinds = {case["contrast"] for case in group}
        if len(kinds) != 1:
            raise ValueError(f"cluster {cluster} declares inconsistent contrast types")
        first, second = group
        if first["contrast"] == "QUESTION":
            if first["observations"] != second["observations"]:
                raise ValueError(f"cluster {cluster} must hold observations fixed")
            if first["question"] == second["question"]:
                raise ValueError(f"cluster {cluster} must vary the question")
        else:
            if first["question"] != second["question"]:
                raise ValueError(f"cluster {cluster} must hold the question fixed")
            if first["observations"] == second["observations"]:
                raise ValueError(f"cluster {cluster} must vary the observations")
        if gold_action(first) == gold_action(second) and first["contrast"] == "QUESTION":
            raise ValueError(f"cluster {cluster} question contrast changes no gold field")
