# RES-61-DR-001 — Football-world ontology and microcycle context

## Status

`ADOPTED`

`RES-61`

`CONSTITUTION_VERSION=2.0.0`

`SERIALIZATION_VERSION=3`

## Scientific and implementation question

What typed, immutable and provenance-aware context contract places a DynamisLM
scientific observation inside a professional-football world—athlete, squad/team,
competition, season, session, explicit exposure, target match and
match-day-relative context—without changing what the measurement physically
measured, inferring participation from session existence, or moving
longitudinal composition into this unit?

## Authority inspected

- `docs/architecture/SCIENTIFIC_CONSTITUTION_V2.md` — sealed V2 scientific
  world, target population, football-context boundary and RES-61 sequence.
- `docs/architecture/MEASUREMENT_DATA_PROVENANCE_V1.md` — observation,
  identity, provenance and immutable-record architecture.
- `docs/architecture/P1_EXECUTION_CONTRACT.md` — pull-based decision workflow
  and registered deterministic Python authority.
- `docs/architecture/REASONING_CLAIMS_EVALUATION_V1.md` — refusal and
  claim-relative context/comparability constraints.
- `docs/decisions/RES60-DR-001-canonical-population-and-source-gate.md` —
  existing population authority and the unchanged `CompetitionIdentity`,
  `SeasonIdentity`, `SquadLevel` and historical observation/evidence boundary.
- Existing V3 contracts in `src/dynamislm/measurement/`,
  `src/dynamislm/population/`, `src/dynamislm/provenance/`, and
  `src/dynamislm/serialization.py`.
- Existing repository tests, including the locked CMJ and RES-60
  serialization/hash regressions.

No broad literature review or external evidence search was required. The sealed
project contracts resolve the terminology and authority questions for this
ontology unit; the match-day rule is an explicit project method definition,
not a football-norm or physiological claim.

## Decisions

### 1. Athlete identity

`AthleteIdentity` contains a de-identified project-local
`InstanceIdentifier` whose `instance_type` is exactly `athlete`. An optional
display label is non-authoritative metadata. Names, dates of birth, passport
numbers, email addresses and other personally identifying data are not
required. The stable athlete ID is the identity used when linking an
`ObservationContext`, exposure or squad participation.

The football-world athlete identity is context/identity authority. It is not a
measurement identity and does not imply a canonical-population decision.

### 2. Team, squad and club semantics

`TeamIdentity` contains a typed `team_id` instance ID, an explicit reused
`SquadLevel`, a `TeamKind`, and an optional `RegistryReference` for the club
organization. `TeamKind` distinguishes a club squad from a national team,
other team and unknown scope. A club reference is therefore not silently used
as a first-team or athlete identity.

The team identity can represent first-team, U23, academy/youth, other or
unknown squad level. Membership facts are recorded separately by
`SquadParticipationContext`; that object never upgrades or replaces the
RES-60 canonical population/source gate.

### 3. Competition identity versus competition context

The existing public, registered and hashed `CompetitionIdentity` from RES-60
is reused without modification. `CompetitionContext` composes around it with
minimal typed metadata: competition kind, optional governing-association and
region references, optional domestic tier and evidence references.

The competition of a match is independent from the squad's canonical
top-domestic-division population clause. A first-team top-division squad may
have a domestic-league, domestic-cup or continental match. A continental or
cup `MatchSession` with no domestic tier is valid. RES-60 remains the authority
for population eligibility; RES-61 does not re-evaluate it from match context.

### 4. Season identity versus season context

The existing public, registered and hashed `SeasonIdentity` from RES-60 is
reused without modification. `SeasonContext` is an additive wrapper with
optional explicit `start_date`, `end_date` and evidence references. If both
dates are present, `start_date <= end_date` is required.

A display label such as `2025/26` is not temporal authority. Season boundaries
are unknown unless explicit dates or a later registered/source mapping supplies
them. A session stores the unchanged `SeasonIdentity`; an optional
`SeasonContext` must identify that same season.

### 5. Session model

`FootballSession` is the common immutable contract. It requires:

- an `InstanceIdentifier` of type `session`;
- a `TeamIdentity`;
- an unchanged `SeasonIdentity`;
- timezone-aware `start_at`;
- optional timezone-aware `end_at`, with `end_at >= start_at`;
- evidence/source references;
- optional structured environment, location, provider and season-context
  references.

Concrete types retain their semantics:

- `TrainingSession` — training context only, with an optional minimal typed
  training reference;
- `MatchSession` — a match ID, explicit opponent, competition context and
  venue role;
- `TestingSession` — testing context for CMJ, IMTP, sprint, VBT and future
  performance-test observations, with an optional typed test-family reference.

The session contract contains no GNSS formula, training-load metric, RPE
calculation, exercise prescription, tactical inference or test result.

### 6. Match opponent and home/away context

`MatchSession` requires a distinct opponent `TeamIdentity`. The studied team
and opponent cannot share the same team identity. `MatchVenueRole` is an
explicit enum: `HOME`, `AWAY`, `NEUTRAL` or `UNRESOLVED`; the default is
`UNRESOLVED`. No home/away role is inferred from field ordering, kickoff,
score, venue text or any other unstated convention.

No formation, tactical phase, xG, score interpretation or opponent-strength
model is part of this decision.

### 7. Explicit exposure

`MatchExposure` and `TrainingExposure` are separate typed contracts. They
contain an athlete, the relevant stable match/session ID(s), a typed
`ParticipationState`, optional observed duration in seconds and evidence
references.

The participation state is an observation of participation status, not a
calculation request. `STARTER` and `SUBSTITUTE_USED` may have absent/unknown
duration. `UNUSED_SUBSTITUTE` and `NOT_IN_MATCHDAY_SQUAD` cannot carry positive
played exposure. `PRESENT`, `PARTIAL`, `ABSENT` and `UNKNOWN` are available for
training exposure with the corresponding typed validation. Unknown duration
remains `None`.

No minutes are estimated from lineup status, first-team membership, a match
result timestamp or a session existing for the squad. A source with no
athlete-level exposure remains unknown; no silent attendance, full-match or
substitute-minute inference is authorized.

### 8. Squad participation

`SquadParticipationContext` explicitly links an athlete, team, season and
`SquadLevel`, with a stable participation ID and evidence references. It
records membership/participation facts only. It cannot establish the six
RES-60 canonical population clauses and cannot be used as a population/source
qualification shortcut.

### 9. Match-day-relative method

`MatchDayRelativeLabel` is a derived authority object, not a naked string. The
only registered RES-61 method is:

`dynamislm:registered-operation:match-day-relative-label@1.0.0`

`derive_match_day_relative_label(session, target_match, reference_timezone)`
requires one explicit `FootballSession`, one explicit `MatchSession` target,
and one valid IANA timezone name. It rejects a missing/non-match target and
rejects target team or season inconsistency.

The deterministic method is:

1. Convert the session start and target-match kickoff to the supplied
   `zoneinfo.ZoneInfo` timezone.
2. Take each converted local calendar date.
3. Compute `day_offset = session_local_date - target_match_local_date` in
   calendar days.
4. Format `0` as `MD`, negative offsets as `MD-<n>` and positive offsets as
   `MD+<n>`.

This is calendar-day-relative semantics, not `floor(elapsed_hours / 24)`. A
session at 23:30 on one local date and a target match at 00:30 on the next
local date is `MD-1`, even when elapsed time is one hour. The timezone name is
part of the method input and is retained in the derived object.

No nearest-match, next-match, previous-match, closest-kickoff or best-candidate
selection rule exists in RES-61.

### 10. Match-day-relative integrity

The derived object embeds the typed session and target match, their IDs and
authoritative timestamps, reference timezone, local dates, day offset, label and
registered method reference. Its constructor recomputes both local dates,
offset and label and verifies all duplicate bindings. V3 decoding invokes the
same constructor.

Therefore changing a cached label, offset, local date, timezone, timestamp,
method reference or identity binding fails closed. A structurally valid payload
such as `day_offset=-1` and `label="MD+2"` is rejected. No cached derivative
field is trusted without recomputation.

### 11. Microcycle context

`MicrocycleContext` is one explicit relationship between one session and one
explicit target match. It retains a context ID, session ID, target match ID,
`MatchDayRelativeLabel`, team, season, derivation method and evidence
references.

It is not a longitudinal calendar builder. RES-61 does not automatically
collect MD-4 through MD+1, fill missing sessions or summarize microcycle load.

### 12. Football-world context and observation placement

`FootballWorldContext` is an additive placement object containing athlete,
team, season, session, optional season context, optional squad participation,
optional typed exposure, optional microcycle context and an optional explicit
observation-context ID. Construction rejects athlete/team/season/session,
exposure and microcycle mismatches. Match exposure can attach only to a
`MatchSession`; training exposure can attach only to a `TrainingSession`.

`validate_observation_football_context` links the existing immutable
`ObservationContext` to this object by matching `athlete_id` and `session_id`,
and matching `context_id` when explicitly supplied by the world context.
`ObservationContext.population_context` remains the unchanged descriptive V1/V3
string. It is not consulted as authority and cannot override or repair typed
context inconsistency.

The boundary is therefore:

```text
FOOTBALL_WORLD_CONTEXT != MEASUREMENT_IDENTITY
FOOTBALL_CONTEXT may affect grouping/comparability/interpretation
FOOTBALL_CONTEXT does not change what was physically measured
```

### 13. Serialization and V3 compatibility

Every public RES-61 dataclass uses `@register_serializable_type`. New objects
use the existing strict canonical V3 envelope and immutable tuple fields.
Calendar `date` values are supported additively by the existing serializer;
existing datetime, dataclass and wire encodings are unchanged.

The following were not changed:

- `CompetitionIdentity` fields, module/class wire identifier or hash behavior;
- `SeasonIdentity` fields, module/class wire identifier or hash behavior;
- `ObservationContext` fields or wire identifier;
- `EvidenceApplicability` fields or wire identifier;
- `SERIALIZATION_VERSION`, which remains `3`;
- RES-60 population/source decisions and historical CMJ/V1 hash fixtures.

### 14. RES-62 boundary

RES-61 owns individual typed world-context units and their deterministic local
consistency. RES-62 owns longitudinal multi-source record composition,
cross-session source graphs, repeated observations, missingness across a
record, and any calendar/record builder that selects or combines multiple
sessions. RES-61 does not ingest datasets, scrape rosters, call fixture APIs,
or construct a season-long record.

## Future RES-63 mapping guidance

This section is guidance only; it is not an ingestion adapter, pandas schema or
canonical-data transformation.

| Source field(s) | Typed RES-61 destination | Mapping condition |
| --- | --- | --- |
| `player_id` | `AthleteIdentity(athlete_id=InstanceIdentifier("athlete", ...))` | Preserve the de-identified source key and source provenance; do not require PII. |
| team/squad key, squad level, optional club key | `TeamIdentity` | Distinguish club organization, first team, academy/U23 and national team; do not use club key alone as team identity. |
| season key/label | `SeasonIdentity` | Reuse the RES-60 identity; do not infer start/end dates from the display label. |
| explicit season start/end mapping | `SeasonContext` | Only a registered/source-backed calendar mapping may provide dates; validate ordering. |
| `date`, explicit timezone/time | `TrainingSession`, `MatchSession` or `TestingSession` | Build an aware datetime; reject naive values and preserve source references. |
| `competition` and competition kind/tier | `CompetitionIdentity` + `CompetitionContext` | Keep current match competition separate from the squad's canonical population tier. |
| `opponent`, explicit home/away role | `MatchSession` | Require a distinct opponent and encode venue role explicitly; never infer from column order. |
| explicit match key/kickoff | `MatchSession` | A match target for MD-relative context must be explicit. |
| `session_type` | concrete session class | Map only registered/typed values to training, match or testing; unknown stays unknown. |
| `starter/substitute` plus source participation status | `MatchExposure` | Use a typed participation state; do not estimate minutes from status alone. |
| observed duration/minutes | `MatchExposure.observed_duration_seconds` or `TrainingExposure.observed_duration_seconds` | Convert units only under a later registered ingestion rule and preserve whether the duration was observed. |
| explicit training attendance/duration | `TrainingExposure` | A squad training row alone is not athlete participation. |
| `MD-1`/`MD+1` label | `MatchDayRelativeLabel` | Treat source text as a candidate field only; recompute from session, explicit target match and timezone under the registered method. |

The RES-63 mapper must preserve unknown values and source/evidence references.
It must not fill missing exposure, select a nearest fixture, or treat
`population_context` free text as typed world authority.

## Alternatives rejected

- Mutating `ObservationContext` to add team, season or match fields — rejected
  because historical V3 wire shape is frozen and placement is additive.
- Moving `CompetitionIdentity` or `SeasonIdentity` from `population.models` —
  rejected because module/class identity is part of the wire contract.
- Replacing typed entities with `session_type="whatever"`, free-text MD labels
  or arbitrary environment strings — rejected because authority would be
  untyped and non-deterministic.
- Treating club organization as the team/squad identity — rejected because
  first-team, academy, U23, national-team and club scopes differ.
- Treating top-domestic-division population status as the type of every match —
  rejected because cup and continental fixtures are valid match contexts.
- Inferring exposure from session existence, roster membership, starter status
  or substitute status — rejected by the explicit-exposure contract.
- Choosing the nearest or next fixture for MD-relative context — rejected
  because target selection is outside this authority unit.
- Defining a full longitudinal calendar/microcycle load record — deferred to
  RES-62.

## Realization and qualification

- Registry: `src/dynamislm/football/registry.py`
- Typed contracts: `src/dynamislm/football/models.py`
- Deterministic MD operation: `src/dynamislm/football/context.py`
- Cross-contract validation: `src/dynamislm/football/validation.py`
- Focused synthetic/adversarial tests: `tests/test_football.py`

The focused suite covers valid training, match and testing sessions; identity
and time failures; explicit exposures; typed mismatch rejection; MD, MD-1,
MD+1, midnight and DST behavior; invalid timezone and missing target refusal;
derived-field and V3 wire tampering; observation placement; continental/cup
competition context; synthetic MD-4→MD+1 fixtures; and RES-60 identity hashes.
The full repository suite remains the authority for historical compatibility.

No scientific numerical formula or measurement-engine authority changed in this
unit.

## Review-driven hardening closeout

### Explicit season chronology

- `SeasonContext` bounds become active deterministic chronology constraints when
  supplied.
- Unknown bounds remain unknown; no missing season date is invented from a
  display label or another timestamp.
- Session timestamps must lie within every supplied authoritative context. The
  check uses the calendar date represented under the timezone carried by each
  aware timestamp, including an explicit session end when present; no season
  timezone is inferred.
- A world-level `SeasonContext` validates the embedded session, and conflicting
  duplicated world/session season contexts fail closed by requiring exact
  dataclass equality.
- Display labels still provide no inferred dates.

### Exposure temporal consistency

- Exposure and session existence remain independent; constructing a session
  never creates athlete exposure.
- When an explicit session end exists, attached observed exposure cannot exceed
  the known session duration computed by Python datetime subtraction.
- When no session end exists, no upper bound is invented and the observed
  duration remains independently representable.

### Compatibility

- No historical wire type changed; `SERIALIZATION_VERSION` remains `3`.
- No scientific numerical measurement authority changed.
