"""Deterministic football-world context operations."""

from __future__ import annotations

from dynamislm.football.models import (
    FootballSession,
    MatchDayRelativeLabel,
    MatchSession,
    _match_day_label,
    _validated_timezone,
)


def derive_match_day_relative_label(
    session: FootballSession,
    target_match: MatchSession | None = None,
    reference_timezone: str = "",
) -> MatchDayRelativeLabel:
    """Derive a calendar-day-relative label from one explicit target match.

    The dates are computed after converting both timestamps to the supplied
    IANA timezone.  This is calendar-day arithmetic, not elapsed-hours
    bucketing.  No fixture selection or nearest-match inference is performed.
    """

    if not isinstance(session, FootballSession):
        raise ValueError("session must be a FootballSession")
    if target_match is None:
        raise ValueError("an explicit target MatchSession is required")
    if not isinstance(target_match, MatchSession):
        raise ValueError("target_match must be a MatchSession")
    reference_zone = _validated_timezone(reference_timezone)
    session_local_date = session.start_at.astimezone(reference_zone).date()
    target_match_local_date = target_match.start_at.astimezone(reference_zone).date()
    day_offset = (session_local_date - target_match_local_date).days
    return MatchDayRelativeLabel(
        session=session,
        target_match=target_match,
        session_id=session.session_id,
        target_match_id=target_match.match_id,
        session_start_at=session.start_at,
        target_match_kickoff_at=target_match.start_at,
        reference_timezone=reference_timezone,
        session_local_date=session_local_date,
        target_match_local_date=target_match_local_date,
        day_offset=day_offset,
        label=_match_day_label(day_offset),
    )


# Readable operation alias; both names invoke the same registered semantics.
derive_match_day_relative = derive_match_day_relative_label


__all__ = ["derive_match_day_relative", "derive_match_day_relative_label"]
