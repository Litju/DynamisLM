# RES38-DR-001 — Flight-time ballistic height estimator

## DECISION_ID

`RES38-DR-001-flight-time-estimator`

## STATUS

`DECIDED`

## QUESTION

Should RES-38 register a CMJ flight-time estimator, and what exact event,
timebase, gravity, and physical assumptions define it?

## SCOPE

The first registered flight-time estimator for a force-platform CMJ. This
decision does not define a universal `jump_height` field, an anatomical COM
height, a phase detector, or a COM-displacement estimator.

## SOURCES

- RES-36 decisions: `RES36-DR-002`, `RES36-DR-003`, and `RES36-DR-004`.
- RES-37 decisions: `RES37-DR-002`, `RES37-DR-003`, and `RES37-DR-005`.
- RES-44/45 gravity decisions.
- Linthorne (2001), *Analysis of standing vertical jumps using a force platform*,
  https://bura.brunel.ac.uk/handle/2438/1392.
- McMahon et al. (2022), *The effects of strength and conditioning interventions
  on ... countermovement jump*, https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0265999.
- Meylan, Nosaka, Green & Cronin (2011), PMID 20664368,
  https://pubmed.ncbi.nlm.nih.gov/20664368/.

## APPLICABILITY

Applicable only when takeoff/contact-loss and landing/contact-regain are
detected from the exact same source signal, trial, acquisition, and registered
timebase. The events are the sample-attached RES-36 occurrences; their recorded
event times are authoritative for this estimator.

## OPTIONS_CONSIDERED

1. Use the recorded event-time difference.
2. Add one sample, subtract one sample, use a half-sample correction, or
   interpolate a threshold crossing.
3. Estimate height from a separate displacement or apex phase.

## DECISION

Register option 1. Flight duration is exactly:

```text
flight_time_s = landing.event_time_s - takeoff.event_time_s
height_m = g_local * flight_time_s**2 / 8
```

There is no implicit sample correction, interpolation, resampling, or
backshift. Takeoff must use `CMJ_TAKEOFF_ABSOLUTE_FORCE@1.0.0`; landing must use
`CMJ_LANDING_ABSOLUTE_FORCE@1.0.0`. Both detector identities and parameters
remain part of the result identity and provenance.

## ESTIMAND

The shared RES-38 estimand is vertical ballistic takeoff-to-apex rise in metres.
The flight-time result is the flight-time-equivalent estimate of that estimand,
conditional on equivalent takeoff and landing vertical COM positions.

## ESTIMATOR

`CMJ_FLIGHT_TIME_JUMP_HEIGHT_ESTIMATOR@1.0.0`, operation
`CMJ_FLIGHT_TIME_JUMP_HEIGHT_OPERATION@1.0.0`.

## EQUATION

`h = g t_f² / 8`, derived from symmetric vertical ballistic flight with
`t_f = 2 v_takeoff / g`.

## INPUTS

- RES-36 takeoff/contact-loss event.
- RES-36 landing/contact-regain event.
- Their exact source observation and source timebase.
- An explicit `GravityReference` whose type is
  `LOCAL_GRAVITATIONAL_ACCELERATION`.

## EVENT_SEMANTICS

Events are attached to the first sample of the earliest qualifying dwell run.
For a regular timebase, RES-36 records `start_time_s + sample_index / fs`; for
an explicit timebase it records the supplied timestamp. The estimator uses
those stored times exactly. A positive duration and strict takeoff-before-
landing order are required.

## GRAVITY_SEMANTICS

V1 accepts only an explicit applicable local gravitational reference. The value,
reference type, source, unit, and uncertainty metadata are serialized in the
method parameters. `STANDARD_GRAVITY` is not silently substituted and does not
feed this physical/local-g operation.

## ASSUMPTIONS

- `BALLISTIC_VERTICAL_MOTION`.
- `TAKEOFF_LANDING_HEIGHT_EQUIVALENCE` — takeoff and landing vertical COM
  positions are equivalent for the symmetric-flight derivation. This is not
  measured or guaranteed by the force platform.
- `NEGLIGIBLE_AIR_RESISTANCE`.
- `LOCAL_GRAVITY_APPLICABLE`.

## CLASSIFICATION

`value_origin = MODEL_ESTIMATE`; `scientific_roles =
(PERFORMANCE_OUTCOME,)`. The arithmetic is deterministic, but the result is
not a direct measurement because the ballistic model and height-equivalence
assumption intervene.

## CLAIM_CEILING

The result may be described as an estimator-qualified, supported-trial CMJ
flight-time ballistic height estimate. It must not be described automatically
as anatomical athlete COM jump height. The force platform does not establish
takeoff/landing COM-height equivalence.

## PROVENANCE

The output preserves both event occurrences, their source observation/signal/
artifact/acquisition/identity/timebase, gravity, method, assumptions, evidence,
and the complete source provenance DAG.

## COMPARABILITY

Same method, detector identities/parameters, gravity identity, timebase
semantics, protocol, and processing state may be `COMPARABLE`. A different
estimator family or an unresolved material dimension is
`BRIDGE_VALIDATION_REQUIRED`; same numerical value is not interchangeability.

## REFUSAL

Refuse missing or wrong takeoff/landing, source mismatch, invalid interval,
missing/mismatched gravity, unsupported ballistic assumptions, and unregistered
method claims with granular RES-38 reason codes. A refusal blocks only the
flight-time height claim.

## LIMITATIONS

Landing posture can differ from takeoff posture. The registered method retains
that known limitation rather than treating the assumption as observed.

## IMPLEMENTATION

Implemented in `src/dynamislm/measurement/cmj/jump_height.py` as the scalar
`CMJJumpHeightResult` path.

## TESTS

Analytic flight-duration fixtures, exact event-time semantics, off-by-one
boundary checks, source mismatch refusals, explicit gravity checks, model
classification, provenance, and deterministic v3 round trips.

## VERSION

`1.0.0`
