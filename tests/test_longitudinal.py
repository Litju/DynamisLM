from __future__ import annotations

import datetime as datetime_module
import json
from dataclasses import replace
from typing import Any, cast

import pytest

from dynamislm import (
    AcquisitionIdentity,
    AcquisitionRecord,
    AgeClass,
    AthleteIdentity,
    CanonicalSource,
    CohortScope,
    CohortScopeType,
    CompetitionContext,
    CompetitionIdentity,
    CompetitionKind,
    CompetitionTier,
    DataGranularity,
    FootballWorldContext,
    InstanceIdentifier,
    LicenseReuseMetadata,
    MeasurementIdentity,
    MeasurementResult,
    MetadataEntry,
    MultiSourceAnalysisInput,
    MultiSourceAnalysisScope,
    MultiSourceProcessingRun,
    MultiSourceProvenanceGraph,
    ObservationContext,
    PopulationDimension,
    PopulationEvidenceBinding,
    PopulationIdentity,
    ProcessingIdentity,
    ProcessingRun,
    ProfessionalStatus,
    Provenance,
    RegistryReference,
    ScalarValue,
    ScientificClassification,
    ScientificIdentifier,
    ScientificMeasurementObservation,
    SeasonContext,
    SeasonIdentity,
    SemanticIdentity,
    Sex,
    SourceArtifact,
    SourceArtifactQualificationBinding,
    SourceDataOrigin,
    Sport,
    SquadLevel,
    TeamIdentity,
    TeamKind,
    TestingSession,
    TrainingExposure,
    TrainingSession,
    ValueOrigin,
    VersionIdentity,
    build_longitudinal_observation_entry,
    build_longitudinal_record,
    build_longitudinal_source_manifest,
    build_multi_source_analysis_input,
    build_multi_source_processing_run,
    build_multi_source_provenance_graph,
    canonical_hash,
    canonical_json,
    from_canonical_json,
    graph_reaches,
)
from dynamislm.football.models import (
    MatchExposure,
    MatchSession,
    MatchVenueRole,
    ParticipationState,
)
from dynamislm.longitudinal import (
    RES62_MULTI_SOURCE_MANIFEST,
    RES62_SOFTWARE_VERSION,
    LongitudinalAthletePerformanceRecord,
    LongitudinalLineageEdge,
    LongitudinalLineageNode,
    LongitudinalLineageNodeKind,
    LongitudinalLineageRelation,
    LongitudinalObservationEntry,
    LongitudinalRecordOrigin,
    LongitudinalSourceManifestResult,
)
from dynamislm.population import (
    CanonicalSourceDecision,
    EvidenceClass,
    ReuseStatus,
    SubgroupSeparability,
    qualify_canonical_source,
)
from dynamislm.provenance import LineageEdge
from dynamislm.provenance import LineageRelation as SourceLineageRelation

UTC = datetime_module.UTC
SYNTHETIC_NAMESPACE = "synthetic-res62"
SYNTHETIC_LABEL = "SYNTHETIC RES-62"


def _instance(instance_type: str, key: str) -> InstanceIdentifier:
    return InstanceIdentifier(instance_type, f"SYNTHETIC-RES-62-{key}")


def _reference(object_type: str, key: str, label: str | None = None) -> RegistryReference:
    return RegistryReference(
        ScientificIdentifier(SYNTHETIC_NAMESPACE, object_type, key, "1.0.0"),
        f"{SYNTHETIC_LABEL} {label or key}",
    )


SEASON_A = SeasonIdentity(
    ScientificIdentifier(SYNTHETIC_NAMESPACE, "season", "2026-27", "1.0.0"),
    f"{SYNTHETIC_LABEL} 2026/27",
)
SEASON_B = SeasonIdentity(
    ScientificIdentifier(SYNTHETIC_NAMESPACE, "season", "2027-28", "1.0.0"),
    f"{SYNTHETIC_LABEL} 2027/28",
)
SEASON_A_CONTEXT = SeasonContext(
    season_identity=SEASON_A,
    start_date=datetime_module.date(2026, 8, 1),
    end_date=datetime_module.date(2027, 6, 1),
)
ATHLETE = AthleteIdentity(
    _instance("athlete", "first-team-athlete"),
    f"{SYNTHETIC_LABEL} de-identified first-team athlete",
)
OTHER_ATHLETE = AthleteIdentity(
    _instance("athlete", "other-athlete"),
    f"{SYNTHETIC_LABEL} other de-identified athlete",
)
TEAM_A = TeamIdentity(
    _instance("team", "club-a-first-team"),
    SquadLevel.FIRST_TEAM,
    TeamKind.CLUB_SQUAD,
    display_label=f"{SYNTHETIC_LABEL} club A first team",
)
TEAM_B = TeamIdentity(
    _instance("team", "club-b-first-team"),
    SquadLevel.FIRST_TEAM,
    TeamKind.CLUB_SQUAD,
    display_label=f"{SYNTHETIC_LABEL} club B first team",
)
OPPONENT = TeamIdentity(
    _instance("team", "opponent"),
    SquadLevel.FIRST_TEAM,
    TeamKind.CLUB_SQUAD,
    display_label=f"{SYNTHETIC_LABEL} opponent",
)
COMPETITION = CompetitionContext(
    competition_identity=CompetitionIdentity(
        ScientificIdentifier(SYNTHETIC_NAMESPACE, "competition", "top-flight", "1.0.0"),
        f"{SYNTHETIC_LABEL} top domestic division",
    ),
    competition_kind=CompetitionKind.DOMESTIC_LEAGUE,
    domestic_tier=CompetitionTier.TOP_DOMESTIC_DIVISION,
)


def _population(source_key: str) -> PopulationIdentity:
    values = (
        (PopulationDimension.SEX, Sex.MALE),
        (PopulationDimension.AGE_CLASS, AgeClass.SENIOR),
        (PopulationDimension.SPORT, Sport.ASSOCIATION_FOOTBALL),
        (PopulationDimension.PROFESSIONAL_STATUS, ProfessionalStatus.PROFESSIONAL),
        (PopulationDimension.SQUAD_LEVEL, SquadLevel.FIRST_TEAM),
        (PopulationDimension.COMPETITION_TIER, CompetitionTier.TOP_DOMESTIC_DIVISION),
    )
    return PopulationIdentity(
        sex=Sex.MALE,
        age_class=AgeClass.SENIOR,
        sport=Sport.ASSOCIATION_FOOTBALL,
        professional_status=ProfessionalStatus.PROFESSIONAL,
        squad_level=SquadLevel.FIRST_TEAM,
        competition_tier=CompetitionTier.TOP_DOMESTIC_DIVISION,
        competition_identity=CompetitionIdentity(
            ScientificIdentifier(
                SYNTHETIC_NAMESPACE, "population-competition", source_key, "1.0.0"
            ),
            f"{SYNTHETIC_LABEL} population competition",
        ),
        season=SEASON_A,
        evidence_bindings=tuple(
            PopulationEvidenceBinding(
                dimension=dimension,
                value=value,
                evidence_reference=_reference("evidence", f"{source_key}-{dimension.value}"),
            )
            for dimension, value in values
        ),
    )


def _source_decision(
    source_key: str,
    origin: SourceDataOrigin = SourceDataOrigin.SYNTHETIC,
) -> CanonicalSourceDecision:
    source = CanonicalSource(
        source_id=_reference("source", source_key, f"{SYNTHETIC_LABEL} provider {source_key}"),
        source_revision="SYNTHETIC-RES-62-revision-1",
        population=_population(source_key),
        cohort_scope=CohortScope(
            scope_type=CohortScopeType.WHOLE_COHORT,
            separability=SubgroupSeparability.EXACT_TARGET_COHORT,
        ),
        data_origin=origin,
        data_granularity=DataGranularity.ATHLETE_LEVEL,
        # License is independent from scientific source eligibility.
        license_reuse=LicenseReuseMetadata(ReuseStatus.UNKNOWN),
    )
    return qualify_canonical_source(source)


def _session(
    key: str,
    start_at: datetime_module.datetime,
    *,
    kind: str = "training",
    season: SeasonIdentity = SEASON_A,
    team: TeamIdentity = TEAM_A,
) -> TrainingSession | TestingSession | MatchSession:
    end_at = start_at + datetime_module.timedelta(hours=2)
    season_context = SEASON_A_CONTEXT if season is SEASON_A else None
    if kind == "training":
        return TrainingSession(
            session_id=_instance("session", key),
            team=team,
            season=season,
            start_at=start_at,
            end_at=end_at,
            season_context=season_context,
        )
    if kind == "testing":
        return TestingSession(
            session_id=_instance("session", key),
            team=team,
            season=season,
            start_at=start_at,
            end_at=end_at,
            season_context=season_context,
            test_type=_reference("test-family", "cmj", f"{SYNTHETIC_LABEL} CMJ testing"),
        )
    if kind == "match":
        return MatchSession(
            session_id=_instance("session", key),
            team=team,
            season=season,
            start_at=start_at,
            end_at=end_at,
            season_context=season_context,
            match_id=_instance("match", key),
            opponent_team=OPPONENT,
            competition_context=COMPETITION,
            venue_role=MatchVenueRole.HOME,
        )
    raise AssertionError(f"unsupported synthetic session kind {kind!r}")


def _entry(
    key: str,
    *,
    session: TrainingSession | TestingSession | MatchSession | None = None,
    observed_at: datetime_module.datetime | None = None,
    kind: str = "training",
    season: SeasonIdentity = SEASON_A,
    team: TeamIdentity = TEAM_A,
    athlete: AthleteIdentity = ATHLETE,
    device_key: str = "provider-a-device",
    artifact_key: str | None = None,
    artifact_digest: str | None = None,
    acquisition_key: str | None = None,
    measurement_key: str | None = None,
    processing_key: str | None = None,
    processing_method_key: str | None = None,
    processed: bool = True,
    value: float = 1.0,
    source_decision: CanonicalSourceDecision | None = None,
    exposure_state: ParticipationState | None = None,
) -> LongitudinalObservationEntry:
    if session is None:
        observed_at = observed_at or datetime_module.datetime(2026, 9, 1, 10, tzinfo=UTC)
        session = _session(
            key,
            observed_at - datetime_module.timedelta(hours=1),
            kind=kind,
            season=season,
            team=team,
        )
    else:
        observed_at = observed_at or session.start_at + datetime_module.timedelta(hours=1)
    artifact_key = artifact_key or key
    acquisition_key = acquisition_key or key
    measurement_key = measurement_key or key
    processing_key = processing_key or key
    processing_method_key = processing_method_key or processing_key
    artifact_id = _instance("artifact", artifact_key)
    observation_id = _instance("observation", key)
    device = _reference("device", device_key, f"{SYNTHETIC_LABEL} {device_key}")
    identity = MeasurementIdentity(
        identity_id=ScientificIdentifier(
            SYNTHETIC_NAMESPACE,
            "measurement-identity",
            f"{SYNTHETIC_LABEL.lower().replace(' ', '-')}-{measurement_key}",
            "1.0.0",
        ),
        semantic=SemanticIdentity(
            construct=_reference("construct", "vertical-jump", f"{SYNTHETIC_LABEL} construct"),
            test_family=_reference("test-family", "cmj", f"{SYNTHETIC_LABEL} CMJ"),
            protocol=_reference("protocol", "standard-cmj", f"{SYNTHETIC_LABEL} protocol"),
            measurand=_reference("measurand", "jump-height", f"{SYNTHETIC_LABEL} jump height"),
            metric_definition=_reference(
                "metric", "vertical-jump-height", f"{SYNTHETIC_LABEL} repeated metric"
            ),
        ),
        acquisition=AcquisitionIdentity(
            device=device,
            raw_artifact=artifact_id,
            sensor_channel=f"{SYNTHETIC_LABEL.lower()}-channel-{device_key}",
        ),
        processing=ProcessingIdentity(
            method_parameters=(MetadataEntry("fixture", SYNTHETIC_LABEL),),
        ),
        version=VersionIdentity(
            processing_method=_reference(
                "processing-method", processing_method_key, f"{SYNTHETIC_LABEL} source method"
            ),
            method_registry_version="1.0.0",
            software_version=f"{SYNTHETIC_LABEL}-source-software-1.0",
        ),
    )
    artifact = SourceArtifact(
        artifact_id=artifact_id,
        content_digest=artifact_digest
        or f"sha256:{SYNTHETIC_LABEL.lower().replace(' ', '-')}-{artifact_key}",
        media_type="application/vnd.synthetic-res62.measurement",
    )
    acquisition = AcquisitionRecord(
        acquisition_id=_instance("acquisition", acquisition_key),
        device=device,
        source_artifact_id=artifact_id,
        sensor_channel=identity.acquisition.sensor_channel,
    )
    source_edges: tuple[LineageEdge, ...]
    processing_runs: tuple[ProcessingRun, ...]
    if processed:
        processing_run = ProcessingRun(
            processing_run_id=_instance("processing-run", processing_key),
            source_artifact_ids=(artifact_id,),
            method=_reference(
                "processing-method", processing_method_key, f"{SYNTHETIC_LABEL} processing"
            ),
            parameters=(MetadataEntry("fixture_processing", SYNTHETIC_LABEL),),
            software_version=f"{SYNTHETIC_LABEL}-processing-1.0",
            output_entity_id=observation_id,
        )
        source_edges = (
            LineageEdge(
                artifact_id.qualified,
                acquisition.acquisition_id.qualified,
                SourceLineageRelation.ACQUIRED_AS,
            ),
            LineageEdge(
                acquisition.acquisition_id.qualified,
                processing_run.processing_run_id.qualified,
                SourceLineageRelation.PROCESSED_AS,
            ),
            LineageEdge(
                processing_run.processing_run_id.qualified,
                observation_id.qualified,
                SourceLineageRelation.PRODUCED,
            ),
        )
        processing_runs = (processing_run,)
    else:
        source_edges = (
            LineageEdge(
                artifact_id.qualified,
                acquisition.acquisition_id.qualified,
                SourceLineageRelation.ACQUIRED_AS,
            ),
            LineageEdge(
                acquisition.acquisition_id.qualified,
                observation_id.qualified,
                SourceLineageRelation.PRODUCED,
            ),
        )
        processing_runs = ()
    observation_context = ObservationContext(
        context_id=_instance("context", key),
        athlete_id=athlete.athlete_id,
        session_id=session.session_id,
        test_instance_id=_instance("test-instance", key),
        trial_id=_instance("trial", key),
        observed_at=observed_at,
        population_context=f"{SYNTHETIC_LABEL} descriptive context only",
    )
    observation = ScientificMeasurementObservation(
        observation_id=observation_id,
        context=observation_context,
        identity=identity,
        result=MeasurementResult(
            result_id=_instance("result", key),
            value=ScalarValue(value),
            unit=None,
            classification=ScientificClassification(ValueOrigin.DIRECT_MEASUREMENT, ()),
        ),
        provenance=Provenance(
            provenance_id=_instance("provenance", key),
            source_artifacts=(artifact,),
            acquisitions=(acquisition,),
            processing_runs=processing_runs,
            lineage_edges=source_edges,
        ),
    )
    exposure: TrainingExposure | MatchExposure | None = None
    if exposure_state is not None:
        if kind == "training":
            exposure = TrainingExposure(
                athlete=athlete,
                training_session_id=session.session_id,
                participation_state=exposure_state,
            )
        elif kind == "match":
            assert isinstance(session, MatchSession)
            exposure = MatchExposure(
                athlete=athlete,
                match_id=session.match_id,
                match_session_id=session.session_id,
                participation_state=exposure_state,
            )
    world = FootballWorldContext(
        context_id=_instance("football-world-context", key),
        athlete=athlete,
        team=team,
        season=season,
        session=session,
        season_context=SEASON_A_CONTEXT if season is SEASON_A else None,
        exposure=exposure,
        observation_context_id=observation_context.context_id,
    )
    decision = source_decision or _source_decision(device_key)
    binding = SourceArtifactQualificationBinding.from_decision(decision, (artifact_id,))
    return build_longitudinal_observation_entry(observation, world, (binding,))


def _fixture_entries() -> tuple[LongitudinalObservationEntry, ...]:
    entries: list[LongitudinalObservationEntry] = []
    for week in range(10):
        day = datetime_module.datetime(2026, 9, 1, tzinfo=UTC) + datetime_module.timedelta(
            days=7 * week
        )
        training = _session(f"training-week-{week}", day.replace(hour=9), kind="training")
        entries.append(
            _entry(
                f"training-week-{week}",
                session=training,
                observed_at=day.replace(hour=10),
                device_key="provider-a-device",
                processed=week % 2 == 0,
                exposure_state=(
                    ParticipationState.UNKNOWN if week == 3 else ParticipationState.PRESENT
                ),
            )
        )
        if week != 5:
            testing = _session(f"testing-week-{week}", day.replace(hour=13), kind="testing")
            entries.append(
                _entry(
                    f"testing-week-{week}-device-a",
                    session=testing,
                    observed_at=day.replace(hour=14),
                    kind="testing",
                    device_key="provider-b-device",
                    processed=True,
                )
            )
            if week == 0:
                # One session, two independent measurement identities/devices.
                entries.append(
                    _entry(
                        "testing-week-0-device-c",
                        session=testing,
                        observed_at=day.replace(hour=14, minute=1),
                        kind="testing",
                        device_key="provider-c-device",
                        processed=True,
                    )
                )
        if week % 2 == 0:
            match = _session(f"match-week-{week}", day.replace(hour=20), kind="match")
            entries.append(
                _entry(
                    f"match-week-{week}",
                    session=match,
                    observed_at=day.replace(hour=20, minute=30),
                    kind="match",
                    device_key="provider-d-device",
                    processed=True,
                    exposure_state=ParticipationState.UNKNOWN,
                )
            )
    return tuple(entries)


def _tampered(value: object) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(canonical_json(value)))


def test_synthetic_res62_fixture_spans_ten_weeks_and_preserves_missingness() -> None:
    entries = _fixture_entries()
    record = build_longitudinal_record(
        ATHLETE,
        entries,
        LongitudinalRecordOrigin.SYNTHETIC_DETERMINISTIC,
    )

    dates = {entry.observed_at.date() for entry in record.entries}
    assert len(record.entries) == len(entries)
    assert (max(dates) - min(dates)).days == 63
    assert record.origin is LongitudinalRecordOrigin.SYNTHETIC_DETERMINISTIC
    assert all("SYNTHETIC-RES-62" in entry.source_observation_id.value for entry in entries)
    assert not any(
        entry.session_id == _instance("session", "testing-week-5") for entry in record.entries
    )
    assert any(
        entry.football_context.exposure is not None
        and entry.football_context.exposure.participation_state is ParticipationState.UNKNOWN
        for entry in record.entries
    )


def test_same_date_different_sessions_survive_without_merging() -> None:
    date = datetime_module.datetime(2026, 9, 20, tzinfo=UTC)
    testing = _session("same-date-testing", date.replace(hour=9), kind="testing")
    training = _session("same-date-training", date.replace(hour=16), kind="training")
    first = _entry(
        "same-date-testing-observation",
        session=testing,
        observed_at=date.replace(hour=10),
        kind="testing",
    )
    second = _entry(
        "same-date-training-observation", session=training, observed_at=date.replace(hour=17)
    )

    record = build_longitudinal_record(
        ATHLETE,
        (second, first),
        LongitudinalRecordOrigin.SYNTHETIC_DETERMINISTIC,
    )

    assert len(record.entries) == 2
    assert {entry.session_id for entry in record.entries} == {
        testing.session_id,
        training.session_id,
    }


def test_same_session_multiple_devices_keep_independent_measurement_identities() -> None:
    start = datetime_module.datetime(2026, 9, 21, 9, tzinfo=UTC)
    session = _session("same-session-multi-device", start, kind="testing")
    first = _entry("same-session-device-a", session=session, kind="testing", device_key="device-a")
    second = _entry("same-session-device-b", session=session, kind="testing", device_key="device-b")

    record = build_longitudinal_record(
        ATHLETE,
        (first, second),
        LongitudinalRecordOrigin.SYNTHETIC_DETERMINISTIC,
    )

    assert len(record.entries) == 2
    assert len({entry.observation.identity.identity_id for entry in record.entries}) == 2
    assert len({entry.observation.identity.acquisition.device for entry in record.entries}) == 2


def test_same_value_label_timestamp_but_different_observation_ids_survive() -> None:
    observed_at = datetime_module.datetime(2026, 9, 22, 10, tzinfo=UTC)
    first = _entry("same-value-a", observed_at=observed_at, value=42.0, device_key="device-a")
    second = _entry("same-value-b", observed_at=observed_at, value=42.0, device_key="device-b")

    record = build_longitudinal_record(
        ATHLETE,
        (first, second),
        LongitudinalRecordOrigin.SYNTHETIC_DETERMINISTIC,
    )

    assert len(record.entries) == 2
    assert first.observation.identity.display_label == second.observation.identity.display_label


def test_builder_collapses_exact_duplicate_but_rejects_result_and_context_conflicts() -> None:
    entry = _entry("dedup-exact")
    assert (
        len(
            build_longitudinal_record(
                ATHLETE,
                (entry, entry),
                LongitudinalRecordOrigin.SYNTHETIC_DETERMINISTIC,
            ).entries
        )
        == 1
    )

    changed_result = replace(
        entry.observation,
        result=replace(entry.observation.result, value=ScalarValue(99.0)),
    )
    changed_result_entry = build_longitudinal_observation_entry(
        changed_result,
        entry.football_context,
        entry.source_qualification_bindings,
    )
    with pytest.raises(ValueError, match="conflicting duplicate observation ID"):
        build_longitudinal_record(
            ATHLETE,
            (entry, changed_result_entry),
            LongitudinalRecordOrigin.SYNTHETIC_DETERMINISTIC,
        )

    changed_world = replace(
        entry.football_context,
        context_id=_instance("football-world-context", "dedup-context-changed"),
    )
    changed_world_entry = build_longitudinal_observation_entry(
        entry.observation,
        changed_world,
        entry.source_qualification_bindings,
    )
    with pytest.raises(ValueError, match="conflicting duplicate observation ID"):
        build_longitudinal_record(
            ATHLETE,
            (entry, changed_world_entry),
            LongitudinalRecordOrigin.SYNTHETIC_DETERMINISTIC,
        )


def test_entry_calls_res61_validation_and_enforces_observation_chronology() -> None:
    entry = _entry("chronology")
    before_session = replace(
        entry.observation.context,
        observed_at=entry.football_context.session.start_at - datetime_module.timedelta(seconds=1),
    )
    observation = replace(entry.observation, context=before_session)
    with pytest.raises(ValueError, match="must not precede session start"):
        build_longitudinal_observation_entry(
            observation,
            entry.football_context,
            entry.source_qualification_bindings,
        )

    mismatched_world = replace(
        entry.football_context,
        athlete=OTHER_ATHLETE,
    )
    with pytest.raises(ValueError, match="observation athlete_id"):
        build_longitudinal_observation_entry(
            entry.observation,
            mismatched_world,
            entry.source_qualification_bindings,
        )


def test_multi_season_record_is_valid_and_keeps_each_world_context() -> None:
    first = _entry(
        "season-a-entry", observed_at=datetime_module.datetime(2026, 9, 1, 10, tzinfo=UTC)
    )
    second_session = _session(
        "season-b-entry",
        datetime_module.datetime(2027, 9, 1, 9, tzinfo=UTC),
        season=SEASON_B,
        team=TEAM_B,
    )
    second = _entry(
        "season-b-entry",
        session=second_session,
        observed_at=datetime_module.datetime(2027, 9, 1, 10, tzinfo=UTC),
        season=SEASON_B,
        team=TEAM_B,
    )

    record = build_longitudinal_record(
        ATHLETE,
        (second, first),
        LongitudinalRecordOrigin.SYNTHETIC_DETERMINISTIC,
    )

    assert len(record.season_ids) == 2
    assert {entry.football_context.team.team_id for entry in record.entries} == {
        TEAM_A.team_id,
        TEAM_B.team_id,
    }


def test_source_artifact_qualification_gate_and_exact_coverage() -> None:
    observed_decision = _source_decision("observed", SourceDataOrigin.ACTUAL_OBSERVED_MEASURED)
    observed_entry = _entry("observed-entry", source_decision=observed_decision)
    observed_record = build_longitudinal_record(
        ATHLETE,
        (observed_entry,),
        LongitudinalRecordOrigin.OBSERVED_CANONICAL,
    )
    assert observed_record.origin is LongitudinalRecordOrigin.OBSERVED_CANONICAL
    assert observed_decision.evidence_class is EvidenceClass.CANONICAL_EMPIRICAL_TARGET

    synthetic_entry = _entry("synthetic-gate", source_decision=_source_decision("synthetic"))
    with pytest.raises(ValueError, match="OBSERVED_CANONICAL"):
        build_longitudinal_record(
            ATHLETE,
            (synthetic_entry,),
            LongitudinalRecordOrigin.OBSERVED_CANONICAL,
        )

    unresolved_entry = _entry(
        "unresolved-gate",
        source_decision=_source_decision("unresolved", SourceDataOrigin.UNKNOWN),
    )
    with pytest.raises(ValueError, match="OBSERVED_CANONICAL"):
        build_longitudinal_record(
            ATHLETE,
            (unresolved_entry,),
            LongitudinalRecordOrigin.OBSERVED_CANONICAL,
        )
    with pytest.raises(ValueError, match="SYNTHETIC_DETERMINISTIC"):
        build_longitudinal_record(
            ATHLETE,
            (observed_entry,),
            LongitudinalRecordOrigin.SYNTHETIC_DETERMINISTIC,
        )

    with pytest.raises(ValueError, match="exactly match"):
        build_longitudinal_observation_entry(
            synthetic_entry.observation,
            synthetic_entry.football_context,
            (),
        )
    extra_binding = SourceArtifactQualificationBinding.from_decision(
        _source_decision("extra-artifact"),
        (_instance("artifact", "not-in-observation"),),
    )
    with pytest.raises(ValueError, match="exactly match"):
        build_longitudinal_observation_entry(
            synthetic_entry.observation,
            synthetic_entry.football_context,
            (*synthetic_entry.source_qualification_bindings, extra_binding),
        )


def test_same_artifact_conflicting_qualification_decisions_are_rejected() -> None:
    first = _entry("shared-artifact-a", artifact_key="shared-artifact")
    second = _entry(
        "shared-artifact-b",
        artifact_key="shared-artifact",
        source_decision=_source_decision("different-source"),
    )

    with pytest.raises(ValueError, match="conflicting qualification decisions"):
        build_longitudinal_record(
            ATHLETE,
            (first, second),
            LongitudinalRecordOrigin.SYNTHETIC_DETERMINISTIC,
        )


def test_analysis_scope_authority_distinguishes_session_season_and_cross_season() -> None:
    day = datetime_module.datetime(2026, 10, 1, tzinfo=UTC)
    same_session = _session("scope-same-session", day.replace(hour=9), kind="testing")
    same_a = _entry(
        "scope-same-a", session=same_session, kind="testing", observed_at=day.replace(hour=10)
    )
    same_b = _entry(
        "scope-same-b",
        session=same_session,
        kind="testing",
        observed_at=day.replace(hour=10, minute=1),
    )
    assert isinstance(
        build_multi_source_analysis_input(
            ATHLETE,
            (same_b, same_a),
            MultiSourceAnalysisScope.SAME_SESSION,
        ),
        MultiSourceAnalysisInput,
    )

    different_session = _session("scope-different-session", day.replace(hour=16), kind="training")
    different = _entry(
        "scope-different", session=different_session, observed_at=day.replace(hour=17)
    )
    with pytest.raises(ValueError, match="SAME_SESSION"):
        build_multi_source_analysis_input(
            ATHLETE,
            (same_a, different),
            MultiSourceAnalysisScope.SAME_SESSION,
        )
    assert isinstance(
        build_multi_source_analysis_input(
            ATHLETE,
            (same_a, different),
            MultiSourceAnalysisScope.WITHIN_SEASON,
        ),
        MultiSourceAnalysisInput,
    )

    season_b_session = _session(
        "scope-season-b",
        datetime_module.datetime(2027, 9, 1, 9, tzinfo=UTC),
        season=SEASON_B,
        team=TEAM_B,
    )
    season_b_entry = _entry(
        "scope-season-b",
        session=season_b_session,
        season=SEASON_B,
        team=TEAM_B,
        observed_at=datetime_module.datetime(2027, 9, 1, 10, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="WITHIN_SEASON"):
        build_multi_source_analysis_input(
            ATHLETE,
            (same_a, season_b_entry),
            MultiSourceAnalysisScope.WITHIN_SEASON,
        )
    cross = build_multi_source_analysis_input(
        ATHLETE,
        (season_b_entry, same_a),
        MultiSourceAnalysisScope.CROSS_SEASON,
    )
    assert cross.scope is MultiSourceAnalysisScope.CROSS_SEASON

    cross_athlete = _entry("scope-cross-athlete", athlete=OTHER_ATHLETE)
    with pytest.raises(ValueError, match="one athlete"):
        build_multi_source_analysis_input(
            ATHLETE,
            (same_a, cross_athlete),
            MultiSourceAnalysisScope.WITHIN_SEASON,
        )


def test_analysis_input_dedup_order_and_identity_are_deterministic() -> None:
    first = _entry(
        "input-order-a", observed_at=datetime_module.datetime(2026, 9, 1, 10, tzinfo=UTC)
    )
    second = _entry(
        "input-order-b", observed_at=datetime_module.datetime(2026, 9, 2, 10, tzinfo=UTC)
    )
    forward = build_multi_source_analysis_input(
        ATHLETE,
        (first, second),
        MultiSourceAnalysisScope.WITHIN_SEASON,
    )
    reverse = build_multi_source_analysis_input(
        ATHLETE,
        (second, first),
        MultiSourceAnalysisScope.WITHIN_SEASON,
    )
    deduped = build_multi_source_analysis_input(
        ATHLETE,
        (first, second, first),
        MultiSourceAnalysisScope.WITHIN_SEASON,
    )

    assert forward == reverse
    assert forward.input_id == reverse.input_id
    assert deduped == forward
    with pytest.raises(ValueError, match="at least two"):
        build_multi_source_analysis_input(
            ATHLETE,
            (first, first),
            MultiSourceAnalysisScope.WITHIN_SEASON,
        )


def test_manifest_is_structural_and_reversing_sources_has_no_first_source_effect() -> None:
    entries = (
        _entry("manifest-a", device_key="device-a"),
        _entry("manifest-b", device_key="device-b"),
        _entry("manifest-c", device_key="device-c"),
    )
    forward_input = build_multi_source_analysis_input(
        ATHLETE,
        entries,
        MultiSourceAnalysisScope.WITHIN_SEASON,
    )
    reverse_input = build_multi_source_analysis_input(
        ATHLETE,
        tuple(reversed(entries)),
        MultiSourceAnalysisScope.WITHIN_SEASON,
    )
    forward = build_longitudinal_source_manifest(forward_input)
    reverse = build_longitudinal_source_manifest(reverse_input)

    assert forward_input.input_id == reverse_input.input_id
    assert forward.processing_run == reverse.processing_run
    assert forward.output_entity_id == reverse.output_entity_id
    assert forward.manifest_hash == reverse.manifest_hash
    assert forward.provenance_graph == reverse.provenance_graph
    assert "mean" not in canonical_json(forward).lower()
    assert "first_source" not in canonical_json(forward)
    assert not hasattr(forward, "primary_source")
    assert forward.method_reference == RES62_MULTI_SOURCE_MANIFEST


def test_reprocessing_changes_processing_and_output_identity_without_mutating_prior_result() -> (
    None
):
    entries = (_entry("reprocess-a"), _entry("reprocess-b", device_key="device-b"))
    analysis_input = build_multi_source_analysis_input(
        ATHLETE,
        entries,
        MultiSourceAnalysisScope.WITHIN_SEASON,
    )
    result_a = build_longitudinal_source_manifest(
        analysis_input,
        parameters=(MetadataEntry("processing_mode", "A"),),
    )
    run_b = build_multi_source_processing_run(
        analysis_input,
        method=RES62_MULTI_SOURCE_MANIFEST,
        parameters=(MetadataEntry("processing_mode", "B"),),
        software_version=RES62_SOFTWARE_VERSION,
    )
    graph_b = build_multi_source_provenance_graph(analysis_input, run_b)
    result_b = LongitudinalSourceManifestResult(
        analysis_input=analysis_input,
        processing_run=run_b,
        selected_observation_ids=analysis_input.source_observation_ids,
        selected_entry_hashes=analysis_input.selected_entry_hashes,
        source_count=len(analysis_input.entries),
        manifest_hash=canonical_hash(
            {
                "analysis_input_id": analysis_input.input_id,
                "scope": analysis_input.scope,
                "selected_observation_ids": analysis_input.source_observation_ids,
                "selected_entry_hashes": analysis_input.selected_entry_hashes,
            }
        ),
        provenance_graph=graph_b,
    )

    assert result_a.processing_run.processing_run_id != result_b.processing_run.processing_run_id
    assert result_a.output_entity_id != result_b.output_entity_id
    assert result_a.provenance_graph != result_b.provenance_graph
    assert result_a == build_longitudinal_source_manifest(
        analysis_input,
        parameters=(MetadataEntry("processing_mode", "A"),),
    )


def test_complete_graph_contains_all_source_lineage_and_reaches_final_output() -> None:
    first = _entry(
        "graph-shared-a", artifact_key="graph-shared-artifact", acquisition_key="shared-acq"
    )
    second = _entry(
        "graph-shared-b",
        artifact_key="graph-shared-artifact",
        acquisition_key="shared-acq",
        device_key="provider-a-device",
    )
    third = _entry("graph-third", device_key="provider-c-device", processed=True)
    analysis_input = build_multi_source_analysis_input(
        ATHLETE,
        (third, second, first),
        MultiSourceAnalysisScope.WITHIN_SEASON,
    )
    result = build_longitudinal_source_manifest(analysis_input)
    graph = result.provenance_graph

    kinds = {node.kind for node in graph.nodes}
    assert {
        LongitudinalLineageNodeKind.SOURCE_ARTIFACT,
        LongitudinalLineageNodeKind.ACQUISITION_RECORD,
        LongitudinalLineageNodeKind.SOURCE_PROCESSING_RUN,
        LongitudinalLineageNodeKind.SOURCE_OBSERVATION,
        LongitudinalLineageNodeKind.FOOTBALL_WORLD_CONTEXT,
        LongitudinalLineageNodeKind.SOURCE_QUALIFICATION,
        LongitudinalLineageNodeKind.LONGITUDINAL_ENTRY,
        LongitudinalLineageNodeKind.ANALYSIS_INPUT,
        LongitudinalLineageNodeKind.MULTI_SOURCE_PROCESSING_RUN,
        LongitudinalLineageNodeKind.DERIVED_RESULT,
    } <= kinds
    assert (
        sum(
            node.node_id == _instance("artifact", "graph-shared-artifact").qualified
            for node in graph.nodes
        )
        == 1
    )
    for observation_id in analysis_input.source_observation_ids:
        assert graph_reaches(graph, observation_id.qualified, result.output_entity_id.qualified)
    assert all(
        graph_reaches(graph, observation_id.qualified, analysis_input.input_id.qualified)
        for observation_id in analysis_input.source_observation_ids
    )


def test_one_observation_can_retain_multiple_source_artifacts_explicitly() -> None:
    original = _entry("multi-artifact-original")
    provenance = original.observation.provenance
    original_artifact = provenance.source_artifacts[0]
    original_acquisition = provenance.acquisitions[0]
    original_run = provenance.processing_runs[0]
    second_artifact = SourceArtifact(
        artifact_id=_instance("artifact", "multi-artifact-second"),
        content_digest="sha256:SYNTHETIC-RES-62-second-artifact",
        media_type="application/vnd.synthetic-res62.measurement",
    )
    second_acquisition = AcquisitionRecord(
        acquisition_id=_instance("acquisition", "multi-artifact-second"),
        device=original_acquisition.device,
        source_artifact_id=second_artifact.artifact_id,
        sensor_channel="SYNTHETIC-RES-62-second-channel",
    )
    multi_artifact_run = replace(
        original_run,
        source_artifact_ids=(original_artifact.artifact_id, second_artifact.artifact_id),
    )
    multi_artifact_provenance = replace(
        provenance,
        source_artifacts=(original_artifact, second_artifact),
        acquisitions=(original_acquisition, second_acquisition),
        processing_runs=(multi_artifact_run,),
        lineage_edges=(
            LineageEdge(
                original_artifact.artifact_id.qualified,
                original_acquisition.acquisition_id.qualified,
                SourceLineageRelation.ACQUIRED_AS,
            ),
            LineageEdge(
                second_artifact.artifact_id.qualified,
                second_acquisition.acquisition_id.qualified,
                SourceLineageRelation.ACQUIRED_AS,
            ),
            LineageEdge(
                original_acquisition.acquisition_id.qualified,
                multi_artifact_run.processing_run_id.qualified,
                SourceLineageRelation.PROCESSED_AS,
            ),
            LineageEdge(
                second_acquisition.acquisition_id.qualified,
                multi_artifact_run.processing_run_id.qualified,
                SourceLineageRelation.PROCESSED_AS,
            ),
            LineageEdge(
                multi_artifact_run.processing_run_id.qualified,
                original.observation.observation_id.qualified,
                SourceLineageRelation.PRODUCED,
            ),
        ),
    )
    observation = replace(original.observation, provenance=multi_artifact_provenance)
    decision = original.source_qualification_bindings[0].canonical_source_decision
    binding = SourceArtifactQualificationBinding.from_decision(
        decision,
        (original_artifact.artifact_id, second_artifact.artifact_id),
    )
    entry = build_longitudinal_observation_entry(
        observation,
        original.football_context,
        (binding,),
    )
    result = build_longitudinal_source_manifest(
        build_multi_source_analysis_input(
            ATHLETE,
            (entry, _entry("multi-artifact-peer")),
            MultiSourceAnalysisScope.WITHIN_SEASON,
        )
    )

    artifact_ids = {
        artifact.artifact_id.qualified for artifact in multi_artifact_provenance.source_artifacts
    }
    graph_artifact_ids = {
        node.node_id
        for node in result.provenance_graph.nodes
        if node.kind is LongitudinalLineageNodeKind.SOURCE_ARTIFACT
    }
    assert artifact_ids <= graph_artifact_ids


def test_graph_rejects_conflicting_shared_artifact_acquisition_and_processing_nodes() -> None:
    shared_artifact_a = _entry(
        "conflict-artifact-a", artifact_key="conflict-artifact", artifact_digest="sha256:content-a"
    )
    shared_artifact_b = _entry(
        "conflict-artifact-b", artifact_key="conflict-artifact", artifact_digest="sha256:content-b"
    )
    input_artifact = build_multi_source_analysis_input(
        ATHLETE,
        (shared_artifact_a, shared_artifact_b),
        MultiSourceAnalysisScope.WITHIN_SEASON,
    )
    with pytest.raises(ValueError, match="conflicting kind or canonical hash"):
        build_longitudinal_source_manifest(input_artifact)

    shared_acquisition_a = _entry(
        "conflict-acquisition-a",
        acquisition_key="conflict-acquisition",
        device_key="device-a",
    )
    shared_acquisition_b = _entry(
        "conflict-acquisition-b",
        acquisition_key="conflict-acquisition",
        device_key="device-b",
    )
    input_acquisition = build_multi_source_analysis_input(
        ATHLETE,
        (shared_acquisition_a, shared_acquisition_b),
        MultiSourceAnalysisScope.WITHIN_SEASON,
    )
    with pytest.raises(ValueError, match="conflicting kind or canonical hash"):
        build_longitudinal_source_manifest(input_acquisition)

    shared_run_a = _entry(
        "conflict-run-a",
        processing_key="conflict-run",
        processing_method_key="method-a",
    )
    shared_run_b = _entry(
        "conflict-run-b",
        processing_key="conflict-run",
        processing_method_key="method-b",
    )
    input_run = build_multi_source_analysis_input(
        ATHLETE,
        (shared_run_a, shared_run_b),
        MultiSourceAnalysisScope.WITHIN_SEASON,
    )
    with pytest.raises(ValueError, match="conflicting kind or canonical hash"):
        build_longitudinal_source_manifest(input_run)


def _rebuild_graph(
    graph: MultiSourceProvenanceGraph,
    *,
    remove_node_ids: frozenset[str] = frozenset(),
    remove_edges: frozenset[tuple[str, str, str]] = frozenset(),
    extra_nodes: tuple[LongitudinalLineageNode, ...] = (),
) -> MultiSourceProvenanceGraph:
    nodes = tuple(
        node for node in (*graph.nodes, *extra_nodes) if node.node_id not in remove_node_ids
    )
    edges = tuple(
        edge
        for edge in graph.edges
        if (
            edge.from_id,
            edge.to_id,
            edge.relation.value,
        )
        not in remove_edges
        and edge.from_id not in remove_node_ids
        and edge.to_id not in remove_node_ids
    )
    return MultiSourceProvenanceGraph(
        nodes=tuple(
            sorted(nodes, key=lambda node: (node.kind.value, node.node_id, node.content_hash))
        ),
        edges=tuple(
            sorted(edges, key=lambda edge: (edge.from_id, edge.to_id, edge.relation.value))
        ),
    )


def test_result_rejects_missing_lineage_nodes_edges_unrelated_nodes_and_unreachable_sources() -> (
    None
):
    result = build_longitudinal_source_manifest(
        build_multi_source_analysis_input(
            ATHLETE,
            (_entry("graph-missing-a"), _entry("graph-missing-b", device_key="device-b")),
            MultiSourceAnalysisScope.WITHIN_SEASON,
        )
    )
    graph = result.provenance_graph
    source_entry = result.analysis_input.entries[0]
    source_observation_id = source_entry.source_observation_id.qualified
    artifact_id = source_entry.observation.provenance.source_artifacts[0].artifact_id.qualified
    acquisition_id = source_entry.observation.provenance.acquisitions[0].acquisition_id.qualified
    processing_id = source_entry.observation.provenance.processing_runs[
        0
    ].processing_run_id.qualified

    for missing_id in (source_observation_id, artifact_id, acquisition_id, processing_id):
        missing_graph = _rebuild_graph(graph, remove_node_ids=frozenset({missing_id}))
        with pytest.raises(ValueError, match="does not match"):
            replace(result, provenance_graph=missing_graph)

    source_edge = next(
        edge for edge in graph.edges if edge.from_id == artifact_id and edge.to_id == acquisition_id
    )
    edge_key = (source_edge.from_id, source_edge.to_id, source_edge.relation.value)
    missing_edge_graph = _rebuild_graph(graph, remove_edges=frozenset({edge_key}))
    with pytest.raises(ValueError, match="does not match"):
        replace(result, provenance_graph=missing_edge_graph)

    unrelated = LongitudinalLineageNode(
        node_id=_instance("observation", "unrelated-cross-athlete").qualified,
        kind=LongitudinalLineageNodeKind.SOURCE_OBSERVATION,
        content_hash=canonical_hash(OTHER_ATHLETE),
    )
    unrelated_graph = _rebuild_graph(graph, extra_nodes=(unrelated,))
    with pytest.raises(ValueError, match="does not match"):
        replace(result, provenance_graph=unrelated_graph)

    selected_entry_node = source_entry.canonical_entry_id.qualified
    input_node = result.analysis_input.input_id.qualified
    unreachable_edge = next(
        edge
        for edge in graph.edges
        if edge.from_id == selected_entry_node and edge.to_id == input_node
    )
    unreachable_key = (
        unreachable_edge.from_id,
        unreachable_edge.to_id,
        unreachable_edge.relation.value,
    )
    unreachable_graph = _rebuild_graph(graph, remove_edges=frozenset({unreachable_key}))
    with pytest.raises(ValueError, match="does not match"):
        replace(result, provenance_graph=unreachable_graph)


def test_graph_direct_validation_rejects_endpoint_duplicates_and_cycles() -> None:
    result = build_longitudinal_source_manifest(
        build_multi_source_analysis_input(
            ATHLETE,
            (_entry("graph-attack-a"), _entry("graph-attack-b")),
            MultiSourceAnalysisScope.WITHIN_SEASON,
        )
    )
    graph = result.provenance_graph
    cycle_edge = LongitudinalLineageEdge(
        from_id=result.output_entity_id.qualified,
        to_id=result.analysis_input.input_id.qualified,
        relation=LongitudinalLineageRelation.ANALYZED_AS,
    )
    cycle_edges = tuple(
        sorted(
            (*graph.edges, cycle_edge),
            key=lambda edge: (edge.from_id, edge.to_id, edge.relation.value),
        )
    )
    with pytest.raises(ValueError, match="acyclic"):
        MultiSourceProvenanceGraph(nodes=graph.nodes, edges=cycle_edges)

    missing_endpoint_edge = LongitudinalLineageEdge(
        from_id="missing:node",
        to_id=result.analysis_input.input_id.qualified,
        relation=LongitudinalLineageRelation.SELECTED_AS,
    )
    missing_edges = tuple(
        sorted(
            (*graph.edges, missing_endpoint_edge),
            key=lambda edge: (edge.from_id, edge.to_id, edge.relation.value),
        )
    )
    with pytest.raises(ValueError, match="endpoint"):
        MultiSourceProvenanceGraph(nodes=graph.nodes, edges=missing_edges)


def test_v3_roundtrip_and_hash_for_all_public_res62_dataclasses() -> None:
    entry_a = _entry("roundtrip-a")
    entry_b = _entry("roundtrip-b", device_key="device-b")
    record = build_longitudinal_record(
        ATHLETE,
        (entry_b, entry_a),
        LongitudinalRecordOrigin.SYNTHETIC_DETERMINISTIC,
    )
    analysis_input = build_multi_source_analysis_input(
        ATHLETE,
        (entry_b, entry_a),
        MultiSourceAnalysisScope.WITHIN_SEASON,
    )
    run = build_multi_source_processing_run(analysis_input)
    result = build_longitudinal_source_manifest(analysis_input)
    binding = entry_a.source_qualification_bindings[0]
    node = result.provenance_graph.nodes[0]
    edge = result.provenance_graph.edges[0]
    values: tuple[object, ...] = (
        binding,
        entry_a,
        record,
        analysis_input,
        run,
        node,
        edge,
        result.provenance_graph,
        result,
    )

    for value in values:
        serialized = canonical_json(value)
        restored = from_canonical_json(serialized, type(value))
        assert restored == value
        assert canonical_json(restored) == serialized
        assert canonical_hash(restored) == canonical_hash(value)


def test_v3_semantic_tamper_rejects_record_input_run_result_and_graph_mutations() -> None:
    entry_a = _entry("tamper-a")
    entry_b = _entry("tamper-b", device_key="device-b")
    record = build_longitudinal_record(
        ATHLETE,
        (entry_a, entry_b),
        LongitudinalRecordOrigin.SYNTHETIC_DETERMINISTIC,
    )
    analysis_input = build_multi_source_analysis_input(
        ATHLETE,
        (entry_a, entry_b),
        MultiSourceAnalysisScope.WITHIN_SEASON,
    )
    run = build_multi_source_processing_run(analysis_input)
    result = build_longitudinal_source_manifest(analysis_input)

    record_mutations: list[dict[str, Any]] = []
    tampered_record = _tampered(record)
    tampered_record["payload"]["origin"] = "OBSERVED_CANONICAL"
    record_mutations.append(tampered_record)
    tampered_record = _tampered(record)
    tampered_record["payload"]["entries"] = list(reversed(tampered_record["payload"]["entries"]))
    record_mutations.append(tampered_record)
    tampered_record = _tampered(record)
    del tampered_record["payload"]["entries"][0]
    record_mutations.append(tampered_record)
    tampered_record = _tampered(record)
    tampered_record["payload"]["record_id"]["value"] = "forged-record-id"
    record_mutations.append(tampered_record)
    for wire in record_mutations:
        with pytest.raises(ValueError):
            from_canonical_json(json.dumps(wire), LongitudinalAthletePerformanceRecord)

    input_wire = _tampered(analysis_input)
    input_wire["payload"]["scope"] = MultiSourceAnalysisScope.SAME_SESSION.value
    with pytest.raises(ValueError):
        from_canonical_json(json.dumps(input_wire), MultiSourceAnalysisInput)

    run_wire = _tampered(run)
    run_wire["payload"]["processing_run_id"]["value"] = "forged-processing-run"
    with pytest.raises(ValueError):
        from_canonical_json(json.dumps(run_wire), MultiSourceProcessingRun)

    result_mutations: list[dict[str, Any]] = []
    result_wire = _tampered(result)
    result_wire["payload"]["source_count"] = 99
    result_mutations.append(result_wire)
    result_wire = _tampered(result)
    result_wire["payload"]["manifest_hash"] = "sha256:" + "0" * 64
    result_mutations.append(result_wire)
    result_wire = _tampered(result)
    result_wire["payload"]["result_id"]["value"] = "forged-result"
    result_mutations.append(result_wire)
    result_wire = _tampered(result)
    graph_payload = result_wire["payload"]["provenance_graph"]
    graph_payload["nodes"][0]["content_hash"] = "sha256:" + "1" * 64
    result_mutations.append(result_wire)
    for wire in result_mutations:
        with pytest.raises(ValueError):
            from_canonical_json(json.dumps(wire), LongitudinalSourceManifestResult)


def test_cmj_style_migration_wraps_without_mutating_existing_observation_or_provenance() -> None:
    entry = _entry("cmj-migration", kind="testing")
    observation = entry.observation
    identity_hash = canonical_hash(observation.identity)
    result_hash = canonical_hash(observation.result)
    provenance_hash = canonical_hash(observation.provenance)

    migrated = build_longitudinal_observation_entry(
        observation,
        entry.football_context,
        entry.source_qualification_bindings,
    )

    assert migrated.observation is observation
    assert canonical_hash(migrated.observation.identity) == identity_hash
    assert canonical_hash(migrated.observation.result) == result_hash
    assert canonical_hash(migrated.observation.provenance) == provenance_hash
    assert migrated.observation.observation_id == observation.observation_id
