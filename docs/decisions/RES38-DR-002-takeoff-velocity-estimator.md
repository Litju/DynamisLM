# RES38-DR-002 — Qualified takeoff-velocity ballistic apex-rise estimator

## DECISION_ID

`RES38-DR-002-takeoff-velocity-estimator`

## STATUS

`DECIDED`

## QUESTION

Should RES-38 register a ballistic height estimator from the RES-46-authorized
supported-system COM velocity, and which velocity sample is takeoff velocity?

## SCOPE

One scalar estimator consuming only `SupportedSystemComVelocityResult` with an
adjudicated `QualifiedZeroVelocityReference`. This decision does not authorize
legacy arbitrary `v0=0`, an event-linked integration start, a body-mass path, or
an athlete-only COM claim.

## SOURCES

- RES-36 takeoff and event-semantics decisions.
- RES-37 integration, physical-system acceleration, velocity, and relative
  displacement decisions.
- RES-44/45 gravity decisions.
- RES-46-DR-001 qualified zero-velocity integration start.
- Linthorne (2001), https://bura.brunel.ac.uk/handle/2438/1392.
- McMahon et al. (2022), https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0265999.

## APPLICABILITY

Applicable to a supported-system velocity curve whose source chain, source
sample support, system contract, local gravity, and RES-46 zero-velocity
authority are internally consistent with the takeoff event.

## OPTIONS_CONSIDERED

1. Use `velocity[takeoff.sample_index]`.
2. Use the preceding velocity sample.
3. Interpolate or define a new velocity event.

## DECISION

Register option 1. The V1 sample convention is
`CMJ_TAKEOFF_VELOCITY_EVENT_SAMPLE_CONVENTION@1.0.0`: the velocity sample whose
source index equals the registered takeoff event sample index. No preceding
sample, half-sample correction, or interpolation is implicit.

## ESTIMAND

The shared RES-38 estimand is vertical ballistic takeoff-to-apex rise in metres.
This method estimates the supported-system COM ballistic apex rise above its
takeoff position.

## ESTIMATOR

`CMJ_QUALIFIED_TAKEOFF_VELOCITY_JUMP_HEIGHT_ESTIMATOR@1.0.0`, operation
`CMJ_QUALIFIED_TAKEOFF_VELOCITY_JUMP_HEIGHT_OPERATION@1.0.0`.

## EQUATION

`h = v_takeoff² / (2 g_local)` for upward-positive takeoff velocity.

## INPUTS

- RES-36 registered takeoff/contact-loss event.
- RES-46-authorized `SupportedSystemComVelocityResult`.
- Its exact `QualifiedZeroVelocityReference` and complete upstream mechanics
  lineage.
- An explicit local `GravityReference` matching the physical mass/acceleration
  chain.

## EVENT_SEMANTICS

Takeoff remains the first sample of the qualifying below-threshold dwell run.
The event source signal, artifact, observation, identity, acquisition,
timebase, and sample support must be represented in the velocity mechanics
chain. The event sample must lie inside the velocity series support.

## GRAVITY_SEMANTICS

The estimator requires explicit local gravity and requires exact compatibility
with the local gravity recorded in the physical-system-mass processing run.
Standard gravity is not substituted and cannot be mixed into a local physical
mechanics chain.

## ASSUMPTIONS

- `BALLISTIC_VERTICAL_MOTION`.
- `NEGLIGIBLE_AIR_RESISTANCE`.
- `SUPPORTED_SYSTEM_STABLE`.
- `LOCAL_GRAVITY_APPLICABLE`.

## CLASSIFICATION

`value_origin = MODEL_ESTIMATE`; `scientific_roles =
(PERFORMANCE_OUTCOME,)`. The input velocity is a derived mechanical quantity;
the ballistic height output is a model estimate.

## CLAIM_CEILING

For unloaded trials, the result remains an estimator-qualified supported-system
COM ballistic apex-rise estimate. For loaded trials, the system is athlete plus
supported load and the result must not be relabeled athlete COM rise or athlete
jump height.

## PROVENANCE

The output preserves the takeoff event, source velocity observation and series,
source force/weight/mass/acceleration processing runs, qualified zero-velocity
reference, physical mass gravity metadata, takeoff sample convention, output
gravity, method, assumptions, and evidence.

## COMPARABILITY

The upstream mechanics identity, integration identity, qualified zero reference,
source timebase, event detector identity/parameters, gravity, system contract,
and filtering/drift state are material. Cross-family or cross-method
interchangeability requires bridge validation.

## REFUSAL

Refuse missing or wrong takeoff, source/sample support mismatch, legacy or
unqualified velocity, missing/mismatched gravity, unsupported system contract,
non-upward takeoff velocity, and unsupported assumptions. Independent valid
velocity and event observations remain describable.

## LIMITATIONS

The input velocity is based on the RES-46 stationarity adjudication and RES-37
supported-system mechanics. The estimator does not create an anatomical COM
trajectory or correct drift.

## IMPLEMENTATION

Implemented in `src/dynamislm/measurement/cmj/jump_height.py` as the scalar
`CMJJumpHeightResult` path.

## TESTS

Analytic velocity fixtures, event-sample versus preceding-sample oracles,
qualified-reference enforcement, source linkage, gravity compatibility, loaded
system semantics, provenance, refusal, and deterministic v3 round trips.

## VERSION

`1.0.0`
