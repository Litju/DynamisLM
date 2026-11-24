"""Versioned synthetic scenario objects accepted by the research inference pipeline."""

from __future__ import annotations

import re
from dataclasses import dataclass

import dynamislm as d
from dynamislm.training_data.synthetic_science import make_record, reference
from scripts.a02_v3_contract import MAX_OBSERVATIONS

SCENARIO_SCHEMA = "DYNAMISLM_RESEARCH_SYNTHETIC_SCENARIO_V1"
CATALOGUE = (
    "absolute-change",
    "unit-incompatibility",
    "protocol-incompatibility",
    "cross-source-incompatibility",
    "missing-evidence",
    "single-observation",
)


@dataclass(frozen=True)
class SyntheticScenario:
    scenario_id: str
    source: d.MultiSourceAnalysisInput | None
    records: tuple[d.LongitudinalAthletePerformanceRecord, ...]
    schema: str = SCENARIO_SCHEMA


def validate_scenario(scenario: SyntheticScenario) -> None:
    """Require qualified fictional sources and restrict record bindings to this snapshot."""
    if (
        not isinstance(scenario, SyntheticScenario)
        or scenario.schema != SCENARIO_SCHEMA
        or not isinstance(scenario.scenario_id, str)
        or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", scenario.scenario_id)
        or not isinstance(scenario.records, tuple)
    ):
        raise ValueError("invalid synthetic scenario identity")
    entries: tuple[d.LongitudinalObservationEntry, ...]
    if scenario.source is None:
        if not scenario.records:
            return
        if (
            len(scenario.records) != 1
            or not isinstance(scenario.records[0], d.LongitudinalAthletePerformanceRecord)
            or len(scenario.records[0].entries) != 1
        ):
            raise ValueError("only one observation may be shown without an analysis snapshot")
        entries, athlete = scenario.records[0].entries, scenario.records[0].athlete
    elif isinstance(scenario.source, d.MultiSourceAnalysisInput):
        entries, athlete = scenario.source.entries, scenario.source.athlete
    else:
        raise ValueError("invalid synthetic source snapshot")
    if not 1 <= len(entries) <= MAX_OBSERVATIONS:
        raise ValueError("synthetic scenario observation count is outside the V3 bound")
    for entry in entries:
        if not entry.source_qualification_bindings or any(
            b.source_decision.source.data_origin != d.SourceDataOrigin.SYNTHETIC
            for b in entry.source_qualification_bindings
        ):
            raise ValueError("scenario requires qualified synthetic source bindings")
        artifacts = entry.observation.provenance.source_artifacts
        bound_ids = {i for b in entry.source_qualification_bindings for i in b.artifact_ids}
        if not artifacts or {a.artifact_id for a in artifacts} != bound_ids:
            raise ValueError("scenario provenance lacks exact artifact bindings")
        for artifact in artifacts:
            if not artifact.immutable or artifact.media_type != "application/synthetic":
                raise ValueError("scenario requires immutable synthetic artifacts")
    seen = set()
    for record in scenario.records:
        if (
            not isinstance(record, d.LongitudinalAthletePerformanceRecord)
            or record.origin != d.LongitudinalRecordOrigin.SYNTHETIC_DETERMINISTIC
            or record.athlete != athlete
        ):
            raise ValueError("scenario record differs from the synthetic athlete or origin")
        for entry in record.entries:
            key = entry.canonical_entry_hash
            if entry not in entries or key in seen:
                raise ValueError("scenario record entry is unbound or duplicated")
            seen.add(key)


def packaged_scenario(scenario_id: str) -> SyntheticScenario:
    if scenario_id not in CATALOGUE:
        raise ValueError("unknown packaged synthetic scenario")
    values = (
        (0.25,)
        if scenario_id == "single-observation"
        else ((0.25, 37.5) if scenario_id == "unit-incompatibility" else (0.25, 0.375))
    )
    record = make_record(
        "research-cli" if scenario_id == "absolute-change" else f"research-{scenario_id}",
        values,
        followup_unit=(
            d.UnitReference(reference("unit", "centimeter").identifier, "cm")
            if scenario_id == "unit-incompatibility"
            else None
        ),
        different_protocol=scenario_id == "protocol-incompatibility",
        different_source=scenario_id == "cross-source-incompatibility",
        different_method=scenario_id == "cross-source-incompatibility",
    )
    source = (
        d.build_multi_source_analysis_input(
            record.athlete, record.entries, d.MultiSourceAnalysisScope.SAME_SESSION
        )
        if len(record.entries) > 1
        else None
    )
    scenario = SyntheticScenario(
        scenario_id,
        source,
        () if scenario_id == "missing-evidence" else (record,),
    )
    validate_scenario(scenario)
    return scenario
