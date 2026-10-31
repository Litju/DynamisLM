"""Original RES-402 fictional support; no empirical or evaluation cases are consumed."""

from datetime import UTC, datetime, timedelta

import dynamislm as d
from dynamislm.longitudinal.statistics import StatisticalSupport, build_statistical_support
from dynamislm.measurement.cmj.registry import METER
from dynamislm.population import ReuseStatus, SubgroupSeparability, qualify_canonical_source
from dynamislm.provenance import LineageRelation


def reference(kind: str, key: str) -> d.RegistryReference:
    return d.RegistryReference(
        d.ScientificIdentifier("synthetic-res402", kind, key, "1.0.0"), f"SYNTHETIC RES-402 {key}"
    )


def instance(kind: str, key: str) -> d.InstanceIdentifier:
    return d.InstanceIdentifier(kind, f"SYNTHETIC-RES402-{key}")


def make_support(
    key: str, values: tuple[float, ...], *, wrong_unit: bool = False, different_method: bool = False
) -> StatisticalSupport:
    """Build exact synthetic observation/source/football lineage using RES-62 builders."""
    season = d.SeasonIdentity(reference("season", "2026-27").identifier, "SYNTHETIC season")
    athlete = d.AthleteIdentity(instance("athlete", key), f"SYNTHETIC athlete {key}")
    team = d.TeamIdentity(
        instance("team", "club-first-team"),
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
            d.PopulationEvidenceBinding(dim, value, reference("evidence", dim.value))
            for dim, value in dimensions
        ),
    )
    source = d.CanonicalSource(
        source_id=reference("source", "fictional-cmj"),
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
    start = datetime(2026, 8, 12, 9, tzinfo=UTC)
    session = d.TestingSession(
        session_id=instance("session", key),
        team=team,
        season=season,
        start_at=start,
        end_at=start + timedelta(hours=2),
    )
    entries = []
    for index, value in enumerate(values):
        item = f"{key}-{index}"
        artifact_id = instance("artifact", item)
        device = reference("device", "fictional-force-platform")
        method = reference(
            "processing-method",
            "cmj-method" if not different_method or index == 0 else "unbridged-other-method",
        )
        identity = d.MeasurementIdentity(
            identity_id=reference("measurement-identity", "fictional-cmj-height").identifier,
            semantic=d.SemanticIdentity(
                construct=reference("construct", "jump"),
                test_family=reference("test-family", "cmj"),
                protocol=reference("protocol", "cmj-standard"),
                measurand=reference("measurand", "jump-height"),
                metric_definition=reference("metric", "cmj-height"),
            ),
            acquisition=d.AcquisitionIdentity(
                device=device, raw_artifact=artifact_id, sensor_channel="SYNTHETIC-force"
            ),
            processing=d.ProcessingIdentity(),
            version=d.VersionIdentity(
                processing_method=method,
                method_registry_version="1.0.0",
                software_version="SYNTHETIC-RES402-1",
            ),
        )
        artifact = d.SourceArtifact(
            artifact_id, d.canonical_hash((item, value)), "application/synthetic"
        )
        acquisition = d.AcquisitionRecord(
            instance("acquisition", item), device, artifact_id, sensor_channel="SYNTHETIC-force"
        )
        obs_id = instance("observation", item)
        run = d.ProcessingRun(
            instance("processing-run", item),
            (artifact_id,),
            method,
            (),
            "SYNTHETIC-RES402-1",
            obs_id,
        )
        context = d.ObservationContext(
            context_id=instance("context", item),
            athlete_id=athlete.athlete_id,
            session_id=session.session_id,
            test_instance_id=instance("test-instance", key),
            trial_id=instance("trial", item),
            observed_at=start + timedelta(minutes=10 + index),
            population_context=(
                "SYNTHETIC elite male senior professional top-division first-team football"
            ),
        )
        observation = d.ScientificMeasurementObservation(
            observation_id=obs_id,
            context=context,
            identity=identity,
            result=d.MeasurementResult(
                result_id=instance("result", item),
                value=d.ScalarValue(value),
                unit=METER
                if not wrong_unit or index == 0
                else d.UnitReference(reference("unit", "wrong-seconds").identifier, "s"),
                classification=d.ScientificClassification(d.ValueOrigin.DIRECT_MEASUREMENT, ()),
            ),
            provenance=d.Provenance(
                provenance_id=instance("provenance", item),
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
            context_id=instance("football-world-context", item),
            athlete=athlete,
            team=team,
            season=season,
            session=session,
            observation_context_id=context.context_id,
        )
        binding = d.SourceArtifactQualificationBinding.from_decision(decision, (artifact_id,))
        entries.append(d.build_longitudinal_observation_entry(observation, world, (binding,)))
    entry_tuple = tuple(entries)
    record = d.build_longitudinal_record(
        athlete, entry_tuple, d.LongitudinalRecordOrigin.SYNTHETIC_DETERMINISTIC
    )
    analysis_input = d.build_multi_source_analysis_input(
        athlete, entry_tuple, d.MultiSourceAnalysisScope.SAME_SESSION
    )
    return build_statistical_support(analysis_input, entry_tuple, source_records=(record,))
