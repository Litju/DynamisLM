"""Typed professional-football world contracts.

These objects describe where an observation sits in the football world.  They
do not redefine a measurement, calculate load, or infer participation from a
session existing for a squad.
"""

from __future__ import annotations

import datetime as datetime_module
import math
from dataclasses import dataclass
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dynamislm.football.registry import MATCH_DAY_RELATIVE_LABEL_METHOD
from dynamislm.measurement.identity import (
    InstanceIdentifier,
    MetadataEntry,
    RegistryReference,
    ScientificIdentifier,
    require_tuple,
)
from dynamislm.population.models import (
    CompetitionIdentity,
    CompetitionTier,
    SeasonIdentity,
    SquadLevel,
)
from dynamislm.serialization import canonical_hash, register_serializable_type


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")


def _require_optional_text(value: str | None, field_name: str) -> None:
    if value is not None:
        _require_text(value, field_name)


def _require_instance_identifier(
    value: object,
    expected_instance_type: str,
    field_name: str,
) -> InstanceIdentifier:
    if not isinstance(value, InstanceIdentifier):
        raise ValueError(f"{field_name} must be an InstanceIdentifier")
    if value.instance_type != expected_instance_type:
        raise ValueError(
            f"{field_name} must identify a {expected_instance_type}, got {value.instance_type!r}"
        )
    return value


def _require_scientific_identifier(value: object, field_name: str) -> ScientificIdentifier:
    if not isinstance(value, ScientificIdentifier):
        raise ValueError(f"{field_name} must be a ScientificIdentifier")
    return value


def _require_optional_registry_reference(
    value: RegistryReference | None,
    field_name: str,
) -> None:
    if value is not None and not isinstance(value, RegistryReference):
        raise ValueError(f"{field_name} must be a RegistryReference when present")


def _require_registry_references(
    values: tuple[RegistryReference, ...],
    field_name: str,
) -> None:
    require_tuple(values, field_name)
    if any(not isinstance(value, RegistryReference) for value in values):
        raise ValueError(f"{field_name} must contain RegistryReference values")


def _require_metadata_entries(values: tuple[MetadataEntry, ...], field_name: str) -> None:
    require_tuple(values, field_name)
    if any(not isinstance(value, MetadataEntry) for value in values):
        raise ValueError(f"{field_name} must contain MetadataEntry values")


def _require_aware_datetime(
    value: datetime_module.datetime,
    field_name: str,
) -> None:
    if not isinstance(value, datetime_module.datetime):
        raise ValueError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include an explicit timezone")


def _require_calendar_date(value: datetime_module.date, field_name: str) -> None:
    if isinstance(value, datetime_module.datetime) or not isinstance(value, datetime_module.date):
        raise ValueError(f"{field_name} must be a calendar date")


def _validated_timezone(reference_timezone: str) -> ZoneInfo:
    _require_text(reference_timezone, "reference_timezone")
    try:
        return ZoneInfo(reference_timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(
            f"reference_timezone must be a valid IANA timezone: {reference_timezone!r}"
        ) from exc


def _same_athlete(left: AthleteIdentity, right: AthleteIdentity) -> bool:
    return left.athlete_id == right.athlete_id


def _same_team(left: TeamIdentity, right: TeamIdentity) -> bool:
    return (
        left.team_id == right.team_id
        and left.squad_level is right.squad_level
        and left.team_kind is right.team_kind
        and (
            left.club_reference is None
            or right.club_reference is None
            or left.club_reference.identifier == right.club_reference.identifier
        )
    )


def _same_season(left: SeasonIdentity, right: SeasonIdentity) -> bool:
    return left.identifier == right.identifier


class TeamKind(StrEnum):
    """Organization scope of a team identity; a club is not a squad."""

    CLUB_SQUAD = "CLUB_SQUAD"
    NATIONAL_TEAM = "NATIONAL_TEAM"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


@register_serializable_type
@dataclass(frozen=True, slots=True)
class AthleteIdentity:
    """Stable de-identified project-local athlete identity."""

    athlete_id: InstanceIdentifier
    display_label: str | None = None

    def __post_init__(self) -> None:
        _require_instance_identifier(self.athlete_id, "athlete", "athlete_id")
        _require_optional_text(self.display_label, "display_label")

    @property
    def identifier(self) -> InstanceIdentifier:
        """Compatibility/readability alias for the stable athlete instance ID."""

        return self.athlete_id

    @property
    def stable_id(self) -> str:
        return self.athlete_id.qualified


@register_serializable_type
@dataclass(frozen=True, slots=True)
class TeamIdentity:
    """A concrete squad/team identity, explicitly distinct from a club."""

    team_id: InstanceIdentifier
    squad_level: SquadLevel
    team_kind: TeamKind = TeamKind.CLUB_SQUAD
    club_reference: RegistryReference | None = None
    display_label: str | None = None

    def __post_init__(self) -> None:
        _require_instance_identifier(self.team_id, "team", "team_id")
        if not isinstance(self.squad_level, SquadLevel):
            raise ValueError("squad_level must be a SquadLevel")
        if not isinstance(self.team_kind, TeamKind):
            raise ValueError("team_kind must be a TeamKind")
        _require_optional_registry_reference(self.club_reference, "club_reference")
        _require_optional_text(self.display_label, "display_label")

    @property
    def identifier(self) -> InstanceIdentifier:
        return self.team_id

    @property
    def stable_id(self) -> str:
        return self.team_id.qualified


class CompetitionKind(StrEnum):
    """Minimal competition classification needed for football-world context."""

    DOMESTIC_LEAGUE = "DOMESTIC_LEAGUE"
    DOMESTIC_CUP = "DOMESTIC_CUP"
    CONTINENTAL = "CONTINENTAL"
    INTERNATIONAL = "INTERNATIONAL"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CompetitionContext:
    """Richer match competition context composed around RES-60 identity."""

    competition_identity: CompetitionIdentity
    competition_kind: CompetitionKind
    governing_association_reference: RegistryReference | None = None
    region_reference: RegistryReference | None = None
    domestic_tier: CompetitionTier | None = None
    evidence_references: tuple[RegistryReference, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.competition_identity, CompetitionIdentity):
            raise ValueError("competition_identity must be a CompetitionIdentity")
        if not isinstance(self.competition_kind, CompetitionKind):
            raise ValueError("competition_kind must be a CompetitionKind")
        _require_optional_registry_reference(
            self.governing_association_reference,
            "governing_association_reference",
        )
        _require_optional_registry_reference(self.region_reference, "region_reference")
        if self.domestic_tier is not None and not isinstance(self.domestic_tier, CompetitionTier):
            raise ValueError("domestic_tier must be a CompetitionTier when present")
        _require_registry_references(self.evidence_references, "evidence_references")

    @property
    def identity(self) -> CompetitionIdentity:
        return self.competition_identity

    @property
    def kind(self) -> CompetitionKind:
        return self.competition_kind

    @property
    def source_references(self) -> tuple[RegistryReference, ...]:
        return self.evidence_references


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SeasonContext:
    """Optional explicit calendar bounds around an unchanged SeasonIdentity."""

    season_identity: SeasonIdentity
    start_date: datetime_module.date | None = None
    end_date: datetime_module.date | None = None
    evidence_references: tuple[RegistryReference, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.season_identity, SeasonIdentity):
            raise ValueError("season_identity must be a SeasonIdentity")
        if self.start_date is not None:
            _require_calendar_date(self.start_date, "start_date")
        if self.end_date is not None:
            _require_calendar_date(self.end_date, "end_date")
        if self.start_date is not None and self.end_date is not None:
            if self.start_date > self.end_date:
                raise ValueError("start_date must be on or before end_date")
        _require_registry_references(self.evidence_references, "evidence_references")

    @property
    def season(self) -> SeasonIdentity:
        return self.season_identity

    @property
    def identity(self) -> SeasonIdentity:
        return self.season_identity

    @property
    def source_references(self) -> tuple[RegistryReference, ...]:
        return self.evidence_references


def _validate_session_within_season_context(
    start_at: datetime_module.datetime,
    end_at: datetime_module.datetime | None,
    season_context: SeasonContext | None,
) -> None:
    """Validate session chronology against any explicit season calendar bounds."""

    if end_at is not None and end_at < start_at:
        raise ValueError("end_at must be on or after start_at")
    if season_context is None:
        return

    session_start_date = start_at.date()
    session_end_date = end_at.date() if end_at is not None else None

    if season_context.start_date is not None:
        if session_start_date < season_context.start_date:
            raise ValueError("session start date must be on or after season start_date")
        if session_end_date is not None and session_end_date < season_context.start_date:
            raise ValueError("session end date must be on or after season start_date")
    if season_context.end_date is not None:
        if session_start_date > season_context.end_date:
            raise ValueError("session start date must be on or before season end_date")
        if session_end_date is not None and session_end_date > season_context.end_date:
            raise ValueError("session end date must be on or before season end_date")


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class FootballSession:
    """Common typed contract for training, match, and testing sessions."""

    session_id: InstanceIdentifier
    team: TeamIdentity
    season: SeasonIdentity
    start_at: datetime_module.datetime
    end_at: datetime_module.datetime | None = None
    season_context: SeasonContext | None = None
    evidence_references: tuple[RegistryReference, ...] = ()
    environment: tuple[MetadataEntry, ...] = ()
    provider_references: tuple[RegistryReference, ...] = ()
    location_reference: RegistryReference | None = None
    environment_reference: RegistryReference | None = None

    def __post_init__(self) -> None:
        _require_instance_identifier(self.session_id, "session", "session_id")
        if not isinstance(self.team, TeamIdentity):
            raise ValueError("team must be a TeamIdentity")
        if not isinstance(self.season, SeasonIdentity):
            raise ValueError("season must be a SeasonIdentity")
        _require_aware_datetime(self.start_at, "start_at")
        if self.end_at is not None:
            _require_aware_datetime(self.end_at, "end_at")
        if self.season_context is not None:
            if not isinstance(self.season_context, SeasonContext):
                raise ValueError("season_context must be a SeasonContext when present")
            if not _same_season(self.season, self.season_context.season_identity):
                raise ValueError("season_context must identify the session season")
        _validate_session_within_season_context(
            self.start_at,
            self.end_at,
            self.season_context,
        )
        _require_registry_references(self.evidence_references, "evidence_references")
        _require_metadata_entries(self.environment, "environment")
        _require_registry_references(self.provider_references, "provider_references")
        _require_optional_registry_reference(self.location_reference, "location_reference")
        _require_optional_registry_reference(self.environment_reference, "environment_reference")

    @property
    def source_references(self) -> tuple[RegistryReference, ...]:
        return self.evidence_references

    @property
    def start_datetime(self) -> datetime_module.datetime:
        return self.start_at

    @property
    def end_datetime(self) -> datetime_module.datetime | None:
        return self.end_at


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class TrainingSession(FootballSession):
    """A training session; no training-load or classification heuristics."""

    training_type: RegistryReference | None = None

    def __post_init__(self) -> None:
        FootballSession.__post_init__(self)
        _require_optional_registry_reference(self.training_type, "training_type")


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class TestingSession(FootballSession):
    """A testing session that supplies when/where context for measurements."""

    __test__ = False
    test_type: RegistryReference | None = None

    def __post_init__(self) -> None:
        FootballSession.__post_init__(self)
        _require_optional_registry_reference(self.test_type, "test_type")

    @property
    def testing_type(self) -> RegistryReference | None:
        return self.test_type


class MatchVenueRole(StrEnum):
    """Explicitly evidenced match role; unresolved is the safe default."""

    HOME = "HOME"
    AWAY = "AWAY"
    NEUTRAL = "NEUTRAL"
    UNRESOLVED = "UNRESOLVED"


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class MatchSession(FootballSession):
    """A match session with explicit opponent, competition, and venue role."""

    match_id: InstanceIdentifier
    opponent_team: TeamIdentity
    competition_context: CompetitionContext
    venue_role: MatchVenueRole = MatchVenueRole.UNRESOLVED

    def __post_init__(self) -> None:
        FootballSession.__post_init__(self)
        _require_instance_identifier(self.match_id, "match", "match_id")
        if not isinstance(self.opponent_team, TeamIdentity):
            raise ValueError("opponent_team must be a TeamIdentity")
        if _same_team(self.team, self.opponent_team):
            raise ValueError("studied team and opponent team must be distinct")
        if not isinstance(self.competition_context, CompetitionContext):
            raise ValueError("competition_context must be a CompetitionContext")
        if not isinstance(self.venue_role, MatchVenueRole):
            raise ValueError("venue_role must be a MatchVenueRole")

    @property
    def studied_team(self) -> TeamIdentity:
        return self.team

    @property
    def opponent(self) -> TeamIdentity:
        return self.opponent_team

    @property
    def competition(self) -> CompetitionContext:
        return self.competition_context

    @property
    def kickoff(self) -> datetime_module.datetime:
        return self.start_at

    @property
    def home_away_role(self) -> MatchVenueRole:
        return self.venue_role


class ParticipationState(StrEnum):
    """Explicit match/training participation state; unknown is not played."""

    STARTER = "STARTER"
    SUBSTITUTE_USED = "SUBSTITUTE_USED"
    UNUSED_SUBSTITUTE = "UNUSED_SUBSTITUTE"
    NOT_IN_MATCHDAY_SQUAD = "NOT_IN_MATCHDAY_SQUAD"
    PRESENT = "PRESENT"
    PARTIAL = "PARTIAL"
    ABSENT = "ABSENT"
    UNKNOWN = "UNKNOWN"


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class FootballExposure:
    """Common explicit exposure contract; session existence is never exposure."""

    athlete: AthleteIdentity
    participation_state: ParticipationState
    observed_duration_seconds: float | None = None
    evidence_references: tuple[RegistryReference, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.athlete, AthleteIdentity):
            raise ValueError("athlete must be an AthleteIdentity")
        if not isinstance(self.participation_state, ParticipationState):
            raise ValueError("participation_state must be a ParticipationState")
        if self.observed_duration_seconds is not None:
            if isinstance(self.observed_duration_seconds, bool) or not isinstance(
                self.observed_duration_seconds,
                int | float,
            ):
                raise ValueError("observed_duration_seconds must be numeric when present")
            if not math.isfinite(float(self.observed_duration_seconds)):
                raise ValueError("observed_duration_seconds must be finite")
            if self.observed_duration_seconds < 0:
                raise ValueError("observed_duration_seconds must not be negative")
            object.__setattr__(
                self,
                "observed_duration_seconds",
                float(self.observed_duration_seconds),
            )
        _require_registry_references(self.evidence_references, "evidence_references")

    @property
    def duration_seconds(self) -> float | None:
        return self.observed_duration_seconds

    @property
    def source_references(self) -> tuple[RegistryReference, ...]:
        return self.evidence_references


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class MatchExposure(FootballExposure):
    """Explicit player participation in one identified match session."""

    match_id: InstanceIdentifier
    match_session_id: InstanceIdentifier

    def __post_init__(self) -> None:
        FootballExposure.__post_init__(self)
        _require_instance_identifier(self.match_id, "match", "match_id")
        _require_instance_identifier(self.match_session_id, "session", "match_session_id")
        if self.participation_state in (
            ParticipationState.UNUSED_SUBSTITUTE,
            ParticipationState.NOT_IN_MATCHDAY_SQUAD,
        ) and self.observed_duration_seconds not in (None, 0, 0.0):
            raise ValueError(
                "unused or out-of-squad match participation cannot carry positive exposure"
            )
        if self.participation_state in (
            ParticipationState.PRESENT,
            ParticipationState.PARTIAL,
            ParticipationState.ABSENT,
        ):
            raise ValueError("match exposure requires a match participation state")

    @property
    def session_id(self) -> InstanceIdentifier:
        return self.match_session_id


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class TrainingExposure(FootballExposure):
    """Explicit player participation in one identified training session."""

    training_session_id: InstanceIdentifier

    def __post_init__(self) -> None:
        FootballExposure.__post_init__(self)
        _require_instance_identifier(self.training_session_id, "session", "training_session_id")
        if self.participation_state in (
            ParticipationState.STARTER,
            ParticipationState.SUBSTITUTE_USED,
            ParticipationState.UNUSED_SUBSTITUTE,
            ParticipationState.NOT_IN_MATCHDAY_SQUAD,
        ):
            raise ValueError("training exposure requires a training participation state")
        if (
            self.participation_state is ParticipationState.ABSENT
            and self.observed_duration_seconds not in (None, 0, 0.0)
        ):
            raise ValueError("absent training participation cannot carry positive exposure")

    @property
    def session_id(self) -> InstanceIdentifier:
        return self.training_session_id


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SquadParticipationContext:
    """Membership/participation fact, independent of canonical population eligibility."""

    participation_id: InstanceIdentifier
    athlete: AthleteIdentity
    team: TeamIdentity
    season: SeasonIdentity
    squad_level: SquadLevel
    evidence_references: tuple[RegistryReference, ...] = ()

    def __post_init__(self) -> None:
        _require_instance_identifier(
            self.participation_id,
            "squad-participation",
            "participation_id",
        )
        if not isinstance(self.athlete, AthleteIdentity):
            raise ValueError("athlete must be an AthleteIdentity")
        if not isinstance(self.team, TeamIdentity):
            raise ValueError("team must be a TeamIdentity")
        if not isinstance(self.season, SeasonIdentity):
            raise ValueError("season must be a SeasonIdentity")
        if not isinstance(self.squad_level, SquadLevel):
            raise ValueError("squad_level must be a SquadLevel")
        if (
            self.team.squad_level is not SquadLevel.UNKNOWN
            and self.squad_level is not SquadLevel.UNKNOWN
            and self.team.squad_level is not self.squad_level
        ):
            raise ValueError("squad_level must match the team squad level")
        _require_registry_references(self.evidence_references, "evidence_references")

    @property
    def source_references(self) -> tuple[RegistryReference, ...]:
        return self.evidence_references


def _match_day_label(day_offset: int) -> str:
    if day_offset == 0:
        return "MD"
    sign = "+" if day_offset > 0 else "-"
    return f"MD{sign}{abs(day_offset)}"


def _match_day_derivation_id(
    session: FootballSession,
    target_match: MatchSession,
    session_id: InstanceIdentifier,
    target_match_id: InstanceIdentifier,
    session_start_at: datetime_module.datetime,
    target_match_kickoff_at: datetime_module.datetime,
    reference_timezone: str,
    method_reference: RegistryReference,
) -> ScientificIdentifier:
    digest = canonical_hash(
        {
            "session": session,
            "target_match": target_match,
            "session_id": session_id,
            "target_match_id": target_match_id,
            "session_start_at": session_start_at,
            "target_match_kickoff_at": target_match_kickoff_at,
            "reference_timezone": reference_timezone,
            "method_reference": method_reference,
        }
    ).removeprefix("sha256:")
    return ScientificIdentifier(
        "dynamislm",
        "match-day-relative-label",
        digest,
        MATCH_DAY_RELATIVE_LABEL_METHOD.identifier.version,
    )


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class MatchDayRelativeLabel:
    """Derived calendar-day relation bound to one session and one target match."""

    session: FootballSession
    target_match: MatchSession
    session_id: InstanceIdentifier
    target_match_id: InstanceIdentifier
    session_start_at: datetime_module.datetime
    target_match_kickoff_at: datetime_module.datetime
    reference_timezone: str
    session_local_date: datetime_module.date
    target_match_local_date: datetime_module.date
    day_offset: int
    label: str
    method_reference: RegistryReference = MATCH_DAY_RELATIVE_LABEL_METHOD
    derivation_id: ScientificIdentifier | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.session, FootballSession):
            raise ValueError("session must be a FootballSession")
        if not isinstance(self.target_match, MatchSession):
            raise ValueError("target_match must be a MatchSession")
        if not _same_team(self.session.team, self.target_match.team):
            raise ValueError("session and target_match must belong to the same studied team")
        if not _same_season(self.session.season, self.target_match.season):
            raise ValueError("session and target_match must belong to the same season")
        _require_instance_identifier(self.session_id, "session", "session_id")
        _require_instance_identifier(self.target_match_id, "match", "target_match_id")
        if self.session_id != self.session.session_id:
            raise ValueError("session_id must match the embedded session")
        if self.target_match_id != self.target_match.match_id:
            raise ValueError("target_match_id must match the embedded target_match")
        _require_aware_datetime(self.session_start_at, "session_start_at")
        _require_aware_datetime(self.target_match_kickoff_at, "target_match_kickoff_at")
        if self.session_start_at != self.session.start_at:
            raise ValueError("session_start_at must match the embedded session")
        if self.target_match_kickoff_at != self.target_match.start_at:
            raise ValueError("target_match_kickoff_at must match the embedded target_match")
        reference_zone = _validated_timezone(self.reference_timezone)
        _require_calendar_date(self.session_local_date, "session_local_date")
        _require_calendar_date(self.target_match_local_date, "target_match_local_date")
        expected_session_date = self.session.start_at.astimezone(reference_zone).date()
        expected_match_date = self.target_match.start_at.astimezone(reference_zone).date()
        if self.session_local_date != expected_session_date:
            raise ValueError("session_local_date does not match the registered timezone method")
        if self.target_match_local_date != expected_match_date:
            raise ValueError(
                "target_match_local_date does not match the registered timezone method"
            )
        if isinstance(self.day_offset, bool) or not isinstance(self.day_offset, int):
            raise ValueError("day_offset must be an integer")
        expected_offset = (expected_session_date - expected_match_date).days
        if self.day_offset != expected_offset:
            raise ValueError("day_offset does not match the embedded timestamps and timezone")
        _require_text(self.label, "label")
        if self.label != _match_day_label(expected_offset):
            raise ValueError("label does not match day_offset")
        if self.method_reference != MATCH_DAY_RELATIVE_LABEL_METHOD:
            raise ValueError("method_reference must be the registered match-day-relative method")
        expected_derivation_id = _match_day_derivation_id(
            self.session,
            self.target_match,
            self.session_id,
            self.target_match_id,
            self.session_start_at,
            self.target_match_kickoff_at,
            self.reference_timezone,
            self.method_reference,
        )
        if self.derivation_id is None:
            object.__setattr__(self, "derivation_id", expected_derivation_id)
        else:
            _require_scientific_identifier(self.derivation_id, "derivation_id")
            if self.derivation_id != expected_derivation_id:
                raise ValueError("derivation_id does not match the authoritative method inputs")

    @property
    def relative_label(self) -> str:
        return self.label


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class MicrocycleContext:
    """One session-to-one-target-match context unit, not a season calendar."""

    microcycle_id: InstanceIdentifier
    session_id: InstanceIdentifier
    target_match_id: InstanceIdentifier
    match_day_relative: MatchDayRelativeLabel
    team: TeamIdentity
    season: SeasonIdentity
    derivation_method: RegistryReference = MATCH_DAY_RELATIVE_LABEL_METHOD
    evidence_references: tuple[RegistryReference, ...] = ()

    def __post_init__(self) -> None:
        _require_instance_identifier(self.microcycle_id, "microcycle", "microcycle_id")
        _require_instance_identifier(self.session_id, "session", "session_id")
        _require_instance_identifier(self.target_match_id, "match", "target_match_id")
        if not isinstance(self.match_day_relative, MatchDayRelativeLabel):
            raise ValueError("match_day_relative must be a MatchDayRelativeLabel")
        if not isinstance(self.team, TeamIdentity):
            raise ValueError("team must be a TeamIdentity")
        if not isinstance(self.season, SeasonIdentity):
            raise ValueError("season must be a SeasonIdentity")
        if self.session_id != self.match_day_relative.session_id:
            raise ValueError("session_id must match match_day_relative")
        if self.target_match_id != self.match_day_relative.target_match_id:
            raise ValueError("target_match_id must match match_day_relative")
        if not _same_team(self.team, self.match_day_relative.session.team):
            raise ValueError("team must match match_day_relative session team")
        if not _same_season(self.season, self.match_day_relative.session.season):
            raise ValueError("season must match match_day_relative session season")
        if self.derivation_method != self.match_day_relative.method_reference:
            raise ValueError("derivation_method must match match_day_relative method")
        _require_registry_references(self.evidence_references, "evidence_references")

    @property
    def source_references(self) -> tuple[RegistryReference, ...]:
        return self.evidence_references


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class FootballWorldContext:
    """Additive football-world placement for one scientific observation."""

    context_id: InstanceIdentifier
    athlete: AthleteIdentity
    team: TeamIdentity
    season: SeasonIdentity
    session: FootballSession
    season_context: SeasonContext | None = None
    squad_participation: SquadParticipationContext | None = None
    exposure: MatchExposure | TrainingExposure | None = None
    microcycle_context: MicrocycleContext | None = None
    observation_context_id: InstanceIdentifier | None = None

    def __post_init__(self) -> None:
        _require_instance_identifier(self.context_id, "football-world-context", "context_id")
        if not isinstance(self.athlete, AthleteIdentity):
            raise ValueError("athlete must be an AthleteIdentity")
        if not isinstance(self.team, TeamIdentity):
            raise ValueError("team must be a TeamIdentity")
        if not isinstance(self.season, SeasonIdentity):
            raise ValueError("season must be a SeasonIdentity")
        if not isinstance(self.session, FootballSession):
            raise ValueError("session must be a FootballSession")
        if not _same_team(self.team, self.session.team):
            raise ValueError("world team must match session team")
        if not _same_season(self.season, self.session.season):
            raise ValueError("world season must match session season")
        if self.season_context is not None:
            if not isinstance(self.season_context, SeasonContext):
                raise ValueError("season_context must be a SeasonContext when present")
            if not _same_season(self.season, self.season_context.season_identity):
                raise ValueError("world season must match season_context")
            _validate_session_within_season_context(
                self.session.start_at,
                self.session.end_at,
                self.season_context,
            )
        if (
            self.season_context is not None
            and self.session.season_context is not None
            and self.season_context != self.session.season_context
        ):
            raise ValueError("world and session season_context must match exactly")
        if self.squad_participation is not None:
            if not isinstance(self.squad_participation, SquadParticipationContext):
                raise ValueError(
                    "squad_participation must be a SquadParticipationContext when present"
                )
            if not _same_athlete(self.athlete, self.squad_participation.athlete):
                raise ValueError("world athlete must match squad participation athlete")
            if not _same_team(self.team, self.squad_participation.team):
                raise ValueError("world team must match squad participation team")
            if not _same_season(self.season, self.squad_participation.season):
                raise ValueError("world season must match squad participation season")
        if self.exposure is not None:
            self._validate_exposure()
        if self.microcycle_context is not None:
            if not isinstance(self.microcycle_context, MicrocycleContext):
                raise ValueError("microcycle_context must be a MicrocycleContext when present")
            if self.microcycle_context.session_id != self.session.session_id:
                raise ValueError("microcycle session must match world session")
            if not _same_team(self.team, self.microcycle_context.team):
                raise ValueError("microcycle team must match world team")
            if not _same_season(self.season, self.microcycle_context.season):
                raise ValueError("microcycle season must match world season")
        if self.observation_context_id is not None:
            _require_instance_identifier(
                self.observation_context_id,
                "context",
                "observation_context_id",
            )

    def _validate_exposure(self) -> None:
        exposure = self.exposure
        if not isinstance(exposure, MatchExposure | TrainingExposure):
            raise ValueError("exposure must be a MatchExposure or TrainingExposure")
        if not _same_athlete(self.athlete, exposure.athlete):
            raise ValueError("world athlete must match exposure athlete")
        if isinstance(exposure, MatchExposure):
            if not isinstance(self.session, MatchSession):
                raise ValueError("MatchExposure can attach only to MatchSession")
            if exposure.match_id != self.session.match_id:
                raise ValueError("match exposure match_id must match world match session")
            if exposure.match_session_id != self.session.session_id:
                raise ValueError("match exposure session must match world session")
        elif isinstance(exposure, TrainingExposure):
            if not isinstance(self.session, TrainingSession):
                raise ValueError("TrainingExposure can attach only to TrainingSession")
            if exposure.training_session_id != self.session.session_id:
                raise ValueError("training exposure session must match world session")

        if (
            exposure.observed_duration_seconds is not None
            and self.session.end_at is not None
            and exposure.observed_duration_seconds
            > (self.session.end_at - self.session.start_at).total_seconds()
        ):
            raise ValueError("observed exposure duration cannot exceed known session duration")

    @property
    def world_context_id(self) -> InstanceIdentifier:
        return self.context_id

    @property
    def match_exposure(self) -> MatchExposure | None:
        return self.exposure if isinstance(self.exposure, MatchExposure) else None

    @property
    def training_exposure(self) -> TrainingExposure | None:
        return self.exposure if isinstance(self.exposure, TrainingExposure) else None

    @property
    def microcycle(self) -> MicrocycleContext | None:
        return self.microcycle_context


# Readable aliases preserve one wire type for each concept.
CompetitionType = CompetitionKind
HomeAwayRole = MatchVenueRole
MatchParticipationState = ParticipationState
TrainingParticipationState = ParticipationState


__all__ = [
    "AthleteIdentity",
    "CompetitionContext",
    "CompetitionKind",
    "CompetitionType",
    "FootballExposure",
    "FootballSession",
    "FootballWorldContext",
    "HomeAwayRole",
    "MatchDayRelativeLabel",
    "MatchExposure",
    "MatchParticipationState",
    "MatchSession",
    "MatchVenueRole",
    "MicrocycleContext",
    "ParticipationState",
    "SeasonContext",
    "SquadParticipationContext",
    "TeamIdentity",
    "TeamKind",
    "TestingSession",
    "TrainingExposure",
    "TrainingParticipationState",
    "TrainingSession",
]
