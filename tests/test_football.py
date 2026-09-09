from __future__ import annotations

import datetime as datetime_module
import json
from dataclasses import replace
from zoneinfo import ZoneInfo

import pytest

from dynamislm import (
    AthleteIdentity,
    CompetitionContext,
    CompetitionIdentity,
    CompetitionKind,
    CompetitionTier,
    FootballSession,
    FootballWorldContext,
    InstanceIdentifier,
    MatchDayRelativeLabel,
    MatchExposure,
    MatchSession,
    MatchVenueRole,
    MetadataEntry,
    MicrocycleContext,
    ObservationContext,
    ParticipationState,
    RegistryReference,
    ScientificIdentifier,
    SeasonContext,
    SeasonIdentity,
    SquadLevel,
    SquadParticipationContext,
    TeamIdentity,
    TeamKind,
    TestingSession,
    TrainingExposure,
    TrainingSession,
    canonical_hash,
    canonical_json,
    derive_match_day_relative_label,
    from_canonical_json,
    validate_observation_football_context,
)

SYNTHETIC_NAMESPACE = "synthetic-res61"


def _instance(instance_type: str, key: str) -> InstanceIdentifier:
    return InstanceIdentifier(instance_type, f"synthetic-res61-{key}")


def _reference(object_type: str, key: str, label: str) -> RegistryReference:
    return RegistryReference(
        ScientificIdentifier(SYNTHETIC_NAMESPACE, object_type, key, "1.0.0"),
        f"SYNTHETIC RES-61 {label}",
    )


SEASON = SeasonIdentity(
    ScientificIdentifier(SYNTHETIC_NAMESPACE, "season", "2026-27", "1.0.0"),
    "SYNTHETIC RES-61 2026/27",
)
SEASON_CONTEXT = SeasonContext(
    season_identity=SEASON,
    start_date=datetime_module.date(2026, 8, 1),
    end_date=datetime_module.date(2027, 5, 31),
    evidence_references=(_reference("source", "season", "season calendar"),),
)
CLUB = _reference("club", "example-club", "de-identified club")
TEAM = TeamIdentity(
    team_id=_instance("team", "first-team"),
    squad_level=SquadLevel.FIRST_TEAM,
    team_kind=TeamKind.CLUB_SQUAD,
    club_reference=CLUB,
    display_label="SYNTHETIC RES-61 first-team squad",
)
OTHER_TEAM = TeamIdentity(
    team_id=_instance("team", "opponent"),
    squad_level=SquadLevel.FIRST_TEAM,
    team_kind=TeamKind.CLUB_SQUAD,
    display_label="SYNTHETIC RES-61 opponent squad",
)
OTHER_SEASON = SeasonIdentity(
    ScientificIdentifier(SYNTHETIC_NAMESPACE, "season", "2027-28", "1.0.0"),
    "SYNTHETIC RES-61 2027/28",
)
ATHLETE_ONE = _instance("athlete", "athlete-one")
ATHLETE_TWO = _instance("athlete", "athlete-two")
ATHLETE = AthleteIdentity(
    athlete_id=ATHLETE_ONE,
    display_label="SYNTHETIC RES-61 athlete one",
)
ATHLETE_TWO_IDENTITY = AthleteIdentity(
    athlete_id=ATHLETE_TWO,
    display_label="SYNTHETIC RES-61 athlete two",
)
DOMESTIC_COMPETITION = CompetitionContext(
    competition_identity=CompetitionIdentity(
        ScientificIdentifier(SYNTHETIC_NAMESPACE, "competition", "domestic-league", "1.0.0"),
        "SYNTHETIC RES-61 top domestic league",
    ),
    competition_kind=CompetitionKind.DOMESTIC_LEAGUE,
    governing_association_reference=_reference("association", "national", "national association"),
    region_reference=_reference("region", "example", "example region"),
    domestic_tier=CompetitionTier.TOP_DOMESTIC_DIVISION,
    evidence_references=(_reference("source", "competition", "competition source"),),
)
CONTINENTAL_COMPETITION = CompetitionContext(
    competition_identity=CompetitionIdentity(
        ScientificIdentifier(SYNTHETIC_NAMESPACE, "competition", "continental-cup", "1.0.0"),
        "SYNTHETIC RES-61 continental cup",
    ),
    competition_kind=CompetitionKind.CONTINENTAL,
    evidence_references=(_reference("source", "continental", "continental source"),),
)


def _at(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int = 0,
    *,
    timezone: str = "Europe/London",
) -> datetime_module.datetime:
    return datetime_module.datetime(
        year,
        month,
        day,
        hour,
        minute,
        tzinfo=ZoneInfo(timezone),
    )


def _training(
    key: str = "md-1",
    *,
    start_at: datetime_module.datetime | None = None,
    season: SeasonIdentity = SEASON,
    team: TeamIdentity = TEAM,
    season_context: SeasonContext | None = SEASON_CONTEXT,
) -> TrainingSession:
    return TrainingSession(
        session_id=_instance("session", f"training-{key}"),
        team=team,
        season=season,
        start_at=start_at or _at(2026, 9, 11, 10),
        end_at=(start_at or _at(2026, 9, 11, 10)) + datetime_module.timedelta(hours=2),
        season_context=season_context if season is SEASON else None,
        evidence_references=(_reference("source", f"training-{key}", "training source"),),
        environment=(MetadataEntry("surface", "SYNTHETIC_TEST_SURFACE"),),
        provider_references=(_reference("provider", "synthetic-provider", "provider"),),
    )


def _testing(
    key: str = "cmj",
    *,
    start_at: datetime_module.datetime | None = None,
) -> TestingSession:
    test_start = start_at or _at(2026, 9, 10, 9)
    return TestingSession(
        session_id=_instance("session", f"testing-{key}"),
        team=TEAM,
        season=SEASON,
        start_at=test_start,
        end_at=test_start + datetime_module.timedelta(hours=2),
        season_context=SEASON_CONTEXT,
        test_type=_reference("test-family", "cmj", "CMJ testing session"),
        evidence_references=(_reference("source", f"testing-{key}", "testing source"),),
    )


def _match(
    key: str = "target",
    *,
    start_at: datetime_module.datetime | None = None,
    season: SeasonIdentity = SEASON,
    team: TeamIdentity = TEAM,
    opponent: TeamIdentity = OTHER_TEAM,
    competition: CompetitionContext = DOMESTIC_COMPETITION,
    season_context: SeasonContext | None = SEASON_CONTEXT,
) -> MatchSession:
    kickoff = start_at or _at(2026, 9, 12, 20)
    return MatchSession(
        session_id=_instance("session", f"match-{key}"),
        match_id=_instance("match", key),
        team=team,
        season=season,
        start_at=kickoff,
        end_at=kickoff + datetime_module.timedelta(hours=2),
        season_context=season_context if season is SEASON else None,
        opponent_team=opponent,
        competition_context=competition,
        venue_role=MatchVenueRole.HOME,
        evidence_references=(_reference("source", f"match-{key}", "match source"),),
    )


TARGET_MATCH = _match()
MATCH_EXPOSURE = MatchExposure(
    athlete=ATHLETE,
    match_id=TARGET_MATCH.match_id,
    match_session_id=TARGET_MATCH.session_id,
    participation_state=ParticipationState.STARTER,
    observed_duration_seconds=90 * 60,
    evidence_references=(_reference("source", "match-exposure", "match exposure source"),),
)
TRAINING_SESSION = _training()
TRAINING_EXPOSURE = TrainingExposure(
    athlete=ATHLETE,
    training_session_id=TRAINING_SESSION.session_id,
    participation_state=ParticipationState.PRESENT,
    observed_duration_seconds=90 * 60,
    evidence_references=(_reference("source", "training-exposure", "training exposure source"),),
)
UNUSED_SUBSTITUTE_EXPOSURE = MatchExposure(
    athlete=ATHLETE_TWO_IDENTITY,
    match_id=TARGET_MATCH.match_id,
    match_session_id=TARGET_MATCH.session_id,
    participation_state=ParticipationState.UNUSED_SUBSTITUTE,
    observed_duration_seconds=None,
    evidence_references=(_reference("source", "unused-substitute", "lineup source"),),
)
SQUAD_PARTICIPATION = SquadParticipationContext(
    participation_id=_instance("squad-participation", "athlete-one"),
    athlete=ATHLETE,
    team=TEAM,
    season=SEASON,
    squad_level=SquadLevel.FIRST_TEAM,
    evidence_references=(_reference("source", "squad", "squad source"),),
)
ATHLETE_TWO_SQUAD_PARTICIPATION = replace(
    SQUAD_PARTICIPATION,
    participation_id=_instance("squad-participation", "athlete-two"),
    athlete=ATHLETE_TWO_IDENTITY,
)

SYNTHETIC_SESSION_FIXTURE = (
    _training("md-4", start_at=_at(2026, 9, 8, 10)),
    _training("md-3", start_at=_at(2026, 9, 9, 10)),
    _testing("md-2", start_at=_at(2026, 9, 10, 9)),
    _training("md-1", start_at=_at(2026, 9, 11, 10)),
    TARGET_MATCH,
    _training("md+1", start_at=_at(2026, 9, 13, 10)),
)


def _label_for(session: TrainingSession = TRAINING_SESSION) -> MatchDayRelativeLabel:
    return derive_match_day_relative_label(session, TARGET_MATCH, "Europe/London")


def _microcycle_for(session: TrainingSession = TRAINING_SESSION) -> MicrocycleContext:
    label = _label_for(session)
    return MicrocycleContext(
        microcycle_id=_instance("microcycle", session.session_id.value),
        session_id=session.session_id,
        target_match_id=TARGET_MATCH.match_id,
        match_day_relative=label,
        team=TEAM,
        season=SEASON,
        evidence_references=(_reference("source", "microcycle", "microcycle source"),),
    )


def _world(
    session: FootballSession = TRAINING_SESSION,
    *,
    athlete: AthleteIdentity = ATHLETE,
    team: TeamIdentity = TEAM,
    season: SeasonIdentity = SEASON,
    season_context: SeasonContext | None = SEASON_CONTEXT,
    exposure: MatchExposure | TrainingExposure | None = None,
    microcycle_context: MicrocycleContext | None = None,
    squad_participation: SquadParticipationContext | None = SQUAD_PARTICIPATION,
) -> FootballWorldContext:
    return FootballWorldContext(
        context_id=_instance("football-world-context", session.session_id.value),
        athlete=athlete,
        team=team,
        season=season,
        session=session,
        season_context=season_context if season is SEASON else None,
        squad_participation=squad_participation,
        exposure=exposure,
        microcycle_context=microcycle_context,
        observation_context_id=_instance("context", session.session_id.value),
    )


def _observation_context(
    *,
    athlete_id: InstanceIdentifier = ATHLETE_ONE,
    session_id: InstanceIdentifier = TRAINING_SESSION.session_id,
    context_key: str = "training-md-1",
    population_context: str = "SYNTHETIC RES-61 descriptive context",
) -> ObservationContext:
    return ObservationContext(
        context_id=_instance("context", context_key),
        athlete_id=athlete_id,
        session_id=session_id,
        test_instance_id=_instance("test-instance", context_key),
        trial_id=_instance("trial", context_key),
        observed_at=_at(2026, 9, 11, 10),
        population_context=population_context,
    )


def test_valid_training_match_and_testing_sessions_are_typed() -> None:
    assert isinstance(TRAINING_SESSION, TrainingSession)
    assert isinstance(TARGET_MATCH, MatchSession)
    assert isinstance(_testing(), TestingSession)
    assert TARGET_MATCH.competition_context.competition_kind is CompetitionKind.DOMESTIC_LEAGUE
    assert TARGET_MATCH.venue_role is MatchVenueRole.HOME


def test_synthetic_fixture_covers_md_minus_four_through_plus_one() -> None:
    expected = ("MD-4", "MD-3", "MD-2", "MD-1", "MD", "MD+1")
    derived = tuple(
        derive_match_day_relative_label(session, TARGET_MATCH, "Europe/London")
        for session in SYNTHETIC_SESSION_FIXTURE
    )

    assert tuple(label.label for label in derived) == expected
    assert all(
        "SYNTHETIC RES-61" in reference.display_label
        for label in derived
        for reference in (label.target_match.evidence_references)
    )


def test_synthetic_fixture_has_two_explicit_exposure_states() -> None:
    starter_world = _world(TARGET_MATCH, exposure=MATCH_EXPOSURE, microcycle_context=None)
    unused_world = _world(
        TARGET_MATCH,
        athlete=ATHLETE_TWO_IDENTITY,
        exposure=UNUSED_SUBSTITUTE_EXPOSURE,
        microcycle_context=None,
        squad_participation=ATHLETE_TWO_SQUAD_PARTICIPATION,
    )

    assert starter_world.exposure is MATCH_EXPOSURE
    assert unused_world.exposure is UNUSED_SUBSTITUTE_EXPOSURE
    assert unused_world.exposure.observed_duration_seconds is None


def test_continental_match_does_not_require_domestic_tier() -> None:
    continental_match = _match(competition=CONTINENTAL_COMPETITION)

    assert continental_match.competition_context.domestic_tier is None
    assert continental_match.competition_context.competition_kind is CompetitionKind.CONTINENTAL


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("session_id", _instance("match", "wrong-session-kind")),
        ("team", "not-a-team"),
        ("season", "not-a-season"),
        ("start_at", datetime_module.datetime(2026, 9, 11, 10)),
    ),
)
def test_session_identity_and_datetime_types_fail_closed(field: str, value: object) -> None:
    kwargs = {
        "session_id": _instance("session", "type-check"),
        "team": TEAM,
        "season": SEASON,
        "start_at": _at(2026, 9, 11, 10),
    }
    kwargs[field] = value

    with pytest.raises(ValueError):
        TrainingSession(**kwargs)  # type: ignore[arg-type]


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValueError, match="explicit timezone"):
        _training(start_at=datetime_module.datetime(2026, 9, 11, 10))


def test_end_before_start_is_rejected() -> None:
    with pytest.raises(ValueError, match="on or after"):
        TrainingSession(
            session_id=_instance("session", "invalid-end"),
            team=TEAM,
            season=SEASON,
            start_at=_at(2026, 9, 11, 12),
            end_at=_at(2026, 9, 11, 11),
        )


def test_season_context_requires_ordered_explicit_bounds() -> None:
    with pytest.raises(ValueError, match="on or before"):
        SeasonContext(
            season_identity=SEASON,
            start_date=datetime_module.date(2027, 1, 1),
            end_date=datetime_module.date(2026, 1, 1),
        )


def test_session_before_explicit_season_start_is_rejected() -> None:
    with pytest.raises(ValueError, match="season"):
        _training("before-season-start", start_at=_at(2026, 7, 31, 10))


def test_session_after_explicit_season_end_is_rejected() -> None:
    with pytest.raises(ValueError, match="season"):
        _training("after-season-end", start_at=_at(2027, 6, 1, 10))


def test_session_end_outside_explicit_season_bounds_is_rejected() -> None:
    with pytest.raises(ValueError, match="season"):
        replace(
            TRAINING_SESSION,
            end_at=_at(2027, 6, 1, 10),
        )


def test_partial_season_bounds_preserve_unknown_bound() -> None:
    start_only = SeasonContext(
        season_identity=SEASON,
        start_date=datetime_module.date(2026, 8, 1),
    )
    end_only = SeasonContext(
        season_identity=SEASON,
        end_date=datetime_module.date(2027, 5, 31),
    )

    with pytest.raises(ValueError, match="season"):
        replace(
            TRAINING_SESSION,
            start_at=_at(2026, 7, 31, 10),
            season_context=start_only,
        )
    assert replace(TRAINING_SESSION, season_context=start_only).season_context == start_only

    with pytest.raises(ValueError, match="season"):
        replace(
            TRAINING_SESSION,
            start_at=_at(2027, 6, 1, 10),
            end_at=_at(2027, 6, 1, 12),
            season_context=end_only,
        )
    assert replace(TRAINING_SESSION, season_context=end_only).season_context == end_only


def test_conflicting_duplicate_season_contexts_are_rejected() -> None:
    conflicting_context = SeasonContext(
        season_identity=SEASON,
        start_date=SEASON_CONTEXT.start_date,
        end_date=datetime_module.date(2027, 6, 1),
        evidence_references=SEASON_CONTEXT.evidence_references,
    )
    session = replace(TRAINING_SESSION, season_context=conflicting_context)

    with pytest.raises(ValueError, match="season_context"):
        _world(session, season_context=SEASON_CONTEXT)


def test_identical_duplicate_season_contexts_are_valid() -> None:
    world = _world(TRAINING_SESSION, season_context=SEASON_CONTEXT)

    assert world.season_context == world.session.season_context


def test_session_only_season_context_is_valid_when_world_context_is_absent() -> None:
    world = _world(TRAINING_SESSION, season_context=None)

    assert world.season_context is None
    assert world.session.season_context == SEASON_CONTEXT


def test_world_only_season_context_validates_session_chronology() -> None:
    session_without_context = replace(TRAINING_SESSION, season_context=None)
    world = _world(session_without_context, season_context=SEASON_CONTEXT)

    assert world.season_context == SEASON_CONTEXT
    assert world.session.season_context is None

    outside_session = replace(
        session_without_context,
        start_at=_at(2027, 6, 1, 10),
        end_at=_at(2027, 6, 1, 12),
    )
    with pytest.raises(ValueError, match="season"):
        _world(outside_session, season_context=SEASON_CONTEXT)


def test_season_bounds_use_the_timestamp_calendar_date_without_timezone_conversion() -> None:
    local_start = datetime_module.datetime(
        2026,
        8,
        1,
        0,
        30,
        tzinfo=ZoneInfo("Asia/Tokyo"),
    )
    local_end = local_start + datetime_module.timedelta(hours=2)
    session = replace(
        TRAINING_SESSION,
        start_at=local_start,
        end_at=local_end,
    )

    assert session.start_at.date() == datetime_module.date(2026, 8, 1)
    assert session.start_at.astimezone(datetime_module.UTC).date() == datetime_module.date(
        2026,
        7,
        31,
    )


def test_same_team_as_opponent_is_rejected() -> None:
    with pytest.raises(ValueError, match="opponent team must be distinct"):
        _match(opponent=TEAM)


def test_squad_participation_is_explicit_and_does_not_qualify_population() -> None:
    context = _world()

    assert context.squad_participation is SQUAD_PARTICIPATION
    assert context.exposure is None


def test_match_exposure_requires_explicit_duration_but_allows_unknown_duration() -> None:
    starter = MATCH_EXPOSURE
    unknown_duration = replace(starter, observed_duration_seconds=None)

    assert starter.observed_duration_seconds == 5400
    assert unknown_duration.participation_state is ParticipationState.STARTER
    assert unknown_duration.observed_duration_seconds is None


def test_exposure_cannot_exceed_known_session_duration() -> None:
    too_long_match_exposure = replace(MATCH_EXPOSURE, observed_duration_seconds=7200.1)
    too_long_training_exposure = replace(TRAINING_EXPOSURE, observed_duration_seconds=7200.1)

    with pytest.raises(ValueError, match="duration"):
        _world(TARGET_MATCH, exposure=too_long_match_exposure, microcycle_context=None)
    with pytest.raises(ValueError, match="duration"):
        _world(TRAINING_SESSION, exposure=too_long_training_exposure, microcycle_context=None)


def test_exposure_at_or_below_known_session_duration_is_valid() -> None:
    exact_match_exposure = replace(MATCH_EXPOSURE, observed_duration_seconds=7200)
    exact_training_exposure = replace(TRAINING_EXPOSURE, observed_duration_seconds=7200)

    _world(TARGET_MATCH, exposure=exact_match_exposure, microcycle_context=None)
    _world(TRAINING_SESSION, exposure=exact_training_exposure, microcycle_context=None)
    _world(TARGET_MATCH, exposure=MATCH_EXPOSURE, microcycle_context=None)
    _world(TRAINING_SESSION, exposure=TRAINING_EXPOSURE, microcycle_context=None)


def test_observed_exposure_remains_unbounded_when_session_end_is_unknown() -> None:
    open_match = replace(TARGET_MATCH, end_at=None)
    long_exposure = replace(MATCH_EXPOSURE, observed_duration_seconds=36000)

    world = _world(open_match, exposure=long_exposure, microcycle_context=None)

    assert world.session.end_at is None
    assert world.exposure == long_exposure


def test_unused_substitute_cannot_carry_positive_exposure() -> None:
    with pytest.raises(ValueError, match="cannot carry positive exposure"):
        MatchExposure(
            athlete=ATHLETE,
            match_id=TARGET_MATCH.match_id,
            match_session_id=TARGET_MATCH.session_id,
            participation_state=ParticipationState.UNUSED_SUBSTITUTE,
            observed_duration_seconds=1,
        )


def test_unknown_participation_does_not_infer_minutes() -> None:
    exposure = MatchExposure(
        athlete=ATHLETE,
        match_id=TARGET_MATCH.match_id,
        match_session_id=TARGET_MATCH.session_id,
        participation_state=ParticipationState.UNKNOWN,
    )

    assert exposure.observed_duration_seconds is None


def test_session_existence_does_not_create_training_exposure() -> None:
    context = _world(TRAINING_SESSION, exposure=None)

    assert context.exposure is None


def test_match_and_training_exposures_attach_only_to_their_session_types() -> None:
    with pytest.raises(ValueError, match="MatchExposure can attach only to MatchSession"):
        _world(TRAINING_SESSION, exposure=MATCH_EXPOSURE)
    with pytest.raises(ValueError, match="TrainingExposure can attach only to TrainingSession"):
        _world(TARGET_MATCH, exposure=TRAINING_EXPOSURE)


def test_world_context_rejects_athlete_team_and_season_mismatches() -> None:
    with pytest.raises(ValueError, match="world athlete"):
        _world(exposure=replace(MATCH_EXPOSURE, athlete=ATHLETE_TWO_IDENTITY))
    with pytest.raises(ValueError, match="world team"):
        _world(team=OTHER_TEAM)
    with pytest.raises(ValueError, match="world season"):
        _world(season=OTHER_SEASON)


@pytest.mark.parametrize(
    ("session_start", "expected_label", "expected_offset"),
    (
        (_at(2026, 9, 12, 8), "MD", 0),
        (_at(2026, 9, 11, 8), "MD-1", -1),
        (_at(2026, 9, 13, 8), "MD+1", 1),
    ),
)
def test_match_day_relative_uses_local_calendar_dates(
    session_start: datetime_module.datetime,
    expected_label: str,
    expected_offset: int,
) -> None:
    session = _training("relative", start_at=session_start)
    label = derive_match_day_relative_label(session, TARGET_MATCH, "Europe/London")

    assert label.label == expected_label
    assert label.day_offset == expected_offset


def test_match_day_relative_midnight_edge_is_calendar_day_not_elapsed_hours() -> None:
    midnight_target = _match(
        "midnight-target",
        start_at=_at(2026, 9, 12, 0, 30, timezone="UTC"),
    )
    session = _training(
        "midnight-session",
        start_at=_at(2026, 9, 11, 23, 30, timezone="UTC"),
    )

    label = derive_match_day_relative_label(session, midnight_target, "UTC")

    assert label.target_match_local_date == datetime_module.date(2026, 9, 12)
    assert label.session_local_date == datetime_module.date(2026, 9, 11)
    assert label.day_offset == -1
    assert label.label == "MD-1"


def test_match_day_relative_dst_conversion_is_deterministic() -> None:
    dst_target = _match(
        "dst-target",
        start_at=_at(2026, 3, 29, 0, 30, timezone="UTC"),
        season_context=None,
    )
    session = _training(
        "dst-session",
        start_at=_at(2026, 3, 29, 23, 30, timezone="UTC"),
        season_context=None,
    )

    label = derive_match_day_relative_label(session, dst_target, "Europe/London")

    assert label.target_match_local_date == datetime_module.date(2026, 3, 29)
    assert label.session_local_date == datetime_module.date(2026, 3, 30)
    assert label.label == "MD+1"


def test_match_day_relative_requires_valid_timezone_and_explicit_target_match() -> None:
    with pytest.raises(ValueError, match="valid IANA timezone"):
        derive_match_day_relative_label(TRAINING_SESSION, TARGET_MATCH, "Not/AZone")
    with pytest.raises(ValueError, match="explicit target"):
        derive_match_day_relative_label(TRAINING_SESSION, None, "UTC")
    with pytest.raises(ValueError, match="MatchSession"):
        derive_match_day_relative_label(TRAINING_SESSION, TRAINING_SESSION, "UTC")  # type: ignore[arg-type]


def test_match_day_relative_rejects_different_target_team_or_season() -> None:
    different_team_target = _match(
        "different-team",
        team=OTHER_TEAM,
        opponent=TEAM,
    )
    different_season_target = _match("different-season", season=OTHER_SEASON)

    with pytest.raises(ValueError, match="same studied team"):
        derive_match_day_relative_label(TRAINING_SESSION, different_team_target, "UTC")
    with pytest.raises(ValueError, match="same season"):
        derive_match_day_relative_label(TRAINING_SESSION, different_season_target, "UTC")


def test_match_day_relative_and_microcycle_derived_fields_cannot_be_tampered() -> None:
    label = _label_for()
    with pytest.raises(ValueError, match="label does not match"):
        replace(label, label="MD+2")
    with pytest.raises(ValueError, match="day_offset"):
        replace(label, day_offset=2, label="MD+2")
    with pytest.raises(ValueError, match="target_match_local_date"):
        replace(label, reference_timezone="Asia/Tokyo")
    with pytest.raises(ValueError, match="derivation_id"):
        replace(label, reference_timezone="Europe/Paris")
    with pytest.raises(ValueError, match="session_id"):
        replace(label, session_id=_instance("session", "forged"))
    with pytest.raises(ValueError, match="session"):
        replace(_microcycle_for(), session_id=_instance("session", "forged"))


def test_match_day_relative_v3_wire_tampering_fails_on_decode() -> None:
    label = _label_for()
    serialized = canonical_json(label)

    tampered_label = json.loads(serialized)
    tampered_label["payload"]["label"] = "MD+2"
    with pytest.raises(ValueError, match="invalid .*payload"):
        from_canonical_json(json.dumps(tampered_label), MatchDayRelativeLabel)

    tampered_timezone = json.loads(serialized)
    tampered_timezone["payload"]["reference_timezone"] = "Asia/Tokyo"
    with pytest.raises(ValueError, match="invalid .*payload"):
        from_canonical_json(json.dumps(tampered_timezone), MatchDayRelativeLabel)

    tampered_id = json.loads(serialized)
    tampered_id["payload"]["session_id"]["value"] = "synthetic-res61-forged"
    with pytest.raises(ValueError, match="invalid .*payload"):
        from_canonical_json(json.dumps(tampered_id), MatchDayRelativeLabel)

    tampered_method = json.loads(serialized)
    tampered_method["payload"]["method_reference"]["identifier"]["key"] = "unregistered"
    with pytest.raises(ValueError, match="invalid .*payload"):
        from_canonical_json(json.dumps(tampered_method), MatchDayRelativeLabel)


def test_world_context_v3_season_bound_tampering_fails_on_decode() -> None:
    serialized = canonical_json(_world())
    tampered = json.loads(serialized)
    tampered["payload"]["session"]["season_context"]["end_date"] = "2026-09-10"

    with pytest.raises(ValueError, match="invalid .*payload"):
        from_canonical_json(json.dumps(tampered), FootballWorldContext)


def test_world_context_v3_conflicting_season_context_tampering_fails_on_decode() -> None:
    serialized = canonical_json(_world())
    tampered = json.loads(serialized)
    tampered["payload"]["season_context"]["end_date"] = "2027-06-01"

    with pytest.raises(ValueError, match="invalid .*payload"):
        from_canonical_json(json.dumps(tampered), FootballWorldContext)


def test_world_context_v3_exposure_duration_tampering_fails_on_decode() -> None:
    match_world = _world(TARGET_MATCH, exposure=MATCH_EXPOSURE, microcycle_context=None)
    training_world = _world(TRAINING_SESSION, exposure=TRAINING_EXPOSURE, microcycle_context=None)

    for world in (match_world, training_world):
        serialized = canonical_json(world)
        tampered = json.loads(serialized)
        tampered["payload"]["exposure"]["observed_duration_seconds"] = 7200.1

        with pytest.raises(ValueError, match="invalid .*payload"):
            from_canonical_json(json.dumps(tampered), FootballWorldContext)


def test_world_context_rejects_microcycle_for_a_different_session() -> None:
    microcycle = _microcycle_for()
    other_session = _training("other", start_at=_at(2026, 9, 10, 10))

    with pytest.raises(ValueError, match="microcycle session"):
        _world(other_session, microcycle_context=microcycle, squad_participation=None)


def test_observation_context_link_is_additive_and_ignores_free_text_population_label() -> None:
    world = _world()
    observation = _observation_context(
        population_context="elite professional first-team top-division athlete",
    )
    linked_world = replace(world, observation_context_id=observation.context_id)

    validate_observation_football_context(observation, linked_world)


def test_observation_context_link_rejects_athlete_or_session_mismatch() -> None:
    world = _world()
    with pytest.raises(ValueError, match="observation athlete_id"):
        validate_observation_football_context(
            _observation_context(athlete_id=ATHLETE_TWO),
            world,
        )
    with pytest.raises(ValueError, match="observation session_id"):
        validate_observation_football_context(
            _observation_context(session_id=_instance("session", "wrong")),
            world,
        )


def test_free_text_cannot_repair_a_typed_observation_mismatch() -> None:
    observation = _observation_context(
        athlete_id=_instance("athlete", "wrong"),
        population_context="elite professional",
    )

    with pytest.raises(ValueError, match="observation athlete_id"):
        validate_observation_football_context(observation, _world())


def test_res60_competition_and_season_wire_hashes_remain_unchanged() -> None:
    competition = CompetitionIdentity(
        ScientificIdentifier("test", "competition", "top-flight-1", "1.0.0"),
        "Example top domestic division",
    )
    season = SeasonIdentity(
        ScientificIdentifier("test", "season", "2025-26", "1.0.0"),
        "2025/26",
    )

    assert canonical_hash(competition) == (
        "sha256:2cef76339ea545352367b055fb7fa93d1b18c31deaa532921e32e50c5471ac27"
    )
    assert canonical_hash(season) == (
        "sha256:31577f604e44139a4c3fa06fcb44c71b9b94a596912e36d91e1ba1c66a9a1577"
    )
    for value, cls in ((competition, CompetitionIdentity), (season, SeasonIdentity)):
        restored = from_canonical_json(canonical_json(value), cls)
        assert restored == value
        assert canonical_hash(restored) == canonical_hash(value)


def test_principal_football_world_types_roundtrip_and_hash_deterministically() -> None:
    label = _label_for()
    microcycle = _microcycle_for()
    world = _world(microcycle_context=microcycle)
    values = (
        ATHLETE,
        TEAM,
        DOMESTIC_COMPETITION,
        SEASON_CONTEXT,
        TRAINING_SESSION,
        TARGET_MATCH,
        _testing(),
        SQUAD_PARTICIPATION,
        MATCH_EXPOSURE,
        TRAINING_EXPOSURE,
        label,
        microcycle,
        world,
    )

    for value in values:
        serialized = canonical_json(value)
        restored = from_canonical_json(serialized, type(value))
        assert restored == value
        assert canonical_json(restored) == serialized
        assert canonical_hash(restored) == canonical_hash(value)


def test_world_context_with_explicit_match_exposure_roundtrips() -> None:
    world = _world(
        TARGET_MATCH,
        exposure=MATCH_EXPOSURE,
        microcycle_context=None,
        squad_participation=SQUAD_PARTICIPATION,
    )
    restored = from_canonical_json(canonical_json(world), FootballWorldContext)

    assert restored == world
    assert isinstance(restored.exposure, MatchExposure)


def test_training_exposure_does_not_require_roster_or_population_inference() -> None:
    exposure = TrainingExposure(
        athlete=ATHLETE_TWO_IDENTITY,
        training_session_id=TRAINING_SESSION.session_id,
        participation_state=ParticipationState.UNKNOWN,
    )

    assert exposure.observed_duration_seconds is None
    assert exposure.athlete.athlete_id == ATHLETE_TWO


def test_team_kind_keeps_club_and_squad_identity_explicit() -> None:
    national_team = TeamIdentity(
        team_id=_instance("team", "national"),
        squad_level=SquadLevel.FIRST_TEAM,
        team_kind=TeamKind.NATIONAL_TEAM,
    )

    assert TEAM.team_kind is TeamKind.CLUB_SQUAD
    assert TEAM.club_reference is CLUB
    assert national_team.team_kind is TeamKind.NATIONAL_TEAM
    assert national_team.club_reference is None
