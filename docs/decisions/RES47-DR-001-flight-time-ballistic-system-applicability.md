# RES47-DR-001 — Flight-time ballistic system applicability

## DECISION_ID

`RES47-DR-001-flight-time-ballistic-system-applicability`

## STATUS

`ADOPTED`

## QUESTION

What explicit system and force conditions must be established before the
RES-38 flight-time equation may produce an authoritative ballistic height
estimate?

## PROBLEM

Events, a positive flight interval, and local gravity do not by themselves
establish free flight. A tether, anchored resistance, assistance, partial
support, changing system composition, or unresolved loading can introduce a
material vertical external force or change the modeled system. Applying
`h = g_local * t_f**2 / 8` in those states would overstate claim authority.

## SOURCES

- `docs/decisions/RES37-DR-001-supported-system-net-force.md`.
- Linthorne (2001), *Analysis of standing vertical jumps using a force
  platform*, https://bura.brunel.ac.uk/handle/2438/1392.
- McMahon, Lake & Comfort (2022), *Identifying and reporting position-specific
  countermovement jump outcome and phase characteristics within rugby league*,
  https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0265999.
- Xu et al. (2023), *A Systematic Review of the Methodology and Validation of
  Countermovement Jump Tests*, https://pmc.ncbi.nlm.nih.gov/articles/PMC10115716/.
- Eythorsdottir et al. (2024), *The Battle of the Equations: A Systematic
  Review of Jump Height Calculations Using Force Platforms*,
  https://pmc.ncbi.nlm.nih.gov/articles/PMC11561012/.

## APPLICABILITY

This correction applies only to the RES-38 physical/local-gravity flight-time
height estimator. It does not change RES-36 event detection, the descriptive
flight duration, RES-37 mechanics, the RES-46 qualified zero-velocity path, or
the RES-38 takeoff-velocity estimator.

## OPTIONS_CONSIDERED

1. Keep event validity, interval validity, and local gravity as the complete
   gate. Rejected because they do not establish free-flight force completeness.
2. Introduce a general force ontology or protocol reasoning engine. Rejected as
   disproportionate to this narrow authority correction.
3. Reuse the registered `CMJMechanicalSystemContract` together with an
   explicit registered protocol loading state. Adopted because it already
   expresses the required supported-system boundary and force model.

## DECISION

The flight-time estimate is authorized only when all of the following hold:

1. RES-36 takeoff and landing occurrences are valid, source-matched, and have
   a positive exact recorded event-time interval.
2. The gravity reference is explicit local gravitational acceleration.
3. The `CMJMechanicalSystemContract` identifies the supported physical system,
   force-platform-plus-gravity model, total supported force, gravity as the
   only other material vertical external force, and stable composition.
4. The resolved CMJ protocol explicitly classifies loading as either unloaded
   or a supported attached load, and agrees with the contract's system boundary.

The equation remains exactly:

```text
flight_time_s = landing.event_time_s - takeoff.event_time_s
height_m = gravity.value_m_per_s2 * flight_time_s**2 / 8
```

## SYSTEM_BOUNDARY

The modeled system is the registered `CMJ_SUPPORTED_SYSTEM_CONSTRUCT`. For an
unloaded trial this is the athlete-supported system. For a stable attached
supported load it is the combined athlete-plus-load system. The latter is a
supported-system result and is never relabeled as athlete body mass or
athlete-only COM height.

## FLIGHT_FORCE_MODEL

During flight, gravity is the only material modeled vertical external force;
air resistance remains the existing negligible-effect assumption. The
force-platform-plus-gravity contract must be explicit before flight-time
height is calculated.

## SUPPORTED_LOAD_SEMANTICS

`UNLOADED` is authorized when the protocol explicitly identifies no external
load and the contract excludes a supported external load. A supported external
load may be authorized when the protocol and contract explicitly establish
that the load remains attached and the athlete-plus-load system is one stable
free-flying system. This is a mechanics inference from the registered system
boundary, not permission to treat the load as athlete body mass.

## UNRESOLVED_PROTOCOL_SEMANTICS

Anchored elastic resistance, tethers, cables, external assistance, anchored
support, partial support, detached or transferred loads, changing composition,
unsupported loads, unknown loading, and unrecognized or missing protocol
loading semantics are refused. Unknown is never defaulted to unloaded.

## ASSUMPTIONS

The existing RES-38 assumptions remain first-class: ballistic vertical motion,
takeoff/landing height equivalence, negligible air resistance, and applicable
local gravity. `CMJ_SUPPORTED_SYSTEM_STABLE_ASSUMPTION` is additionally carried
by the flight-time method. The typed mechanical contract separately preserves
the gravity-only force model and stable system boundary; no duplicate prose-only
assumption is introduced.

## CLAIM_CEILING

An accepted output is an estimator-qualified supported-trial ballistic
flight-time height estimate. A loaded accepted output describes the combined
supported system and is not automatically athlete-only COM jump height.

## PROVENANCE_EFFECT

New flight-time results preserve the exact `CMJMechanicalSystemContract` in
typed estimator parameters, deterministic processing metadata, processing-run
parameters, and the RES-47 decision evidence reference. The protocol identity
and external-loading attribute remain in the source measurement identity.

## COMPARABILITY_EFFECT

The applicability contract is a material estimator dimension. Unloaded and
stable supported-load outputs are not automatically interchangeable, even when
their equation and numeric values match. Existing claim-relative comparison
returns bridge validation or insufficient-information states when system or
protocol applicability differs or is missing.

## REFUSAL_EFFECT

The refusal blocks only the RES-38 flight-time ballistic height estimate. It
does not erase valid takeoff or landing occurrences, descriptive flight
duration, RES-37 mechanics, the qualified takeoff-velocity estimator, or other
independent observations.

## SERIALIZATION_EFFECT

`SERIALIZATION_VERSION=3` is retained. `JumpHeightEstimatorParameters` already
has the optional v3 `system_contract` field, so no wire field or version change
is required. New flight-time results populate that field and require the
authority; an older unqualified v3 result is not silently reissued as a newly
authoritative result.

## LIMITATIONS

The contract does not measure takeoff/landing height equivalence, aerodynamic
effects, or biological COM location. It does not authorize COM-displacement
height, new phase methods, or a generic protocol reasoning framework.

## IMPLEMENTATION

Reuse `CMJMechanicalSystemContract` and the registered protocol
`external_loading` attribute in `src/dynamislm/measurement/cmj/jump_height.py`.
The existing RES-37 contract validation and RES-38 event/gravity gates remain
otherwise unchanged.

## TESTS

The test suite covers unchanged unloaded arithmetic and event-time semantics,
explicit local gravity, accepted stable free-flying supported loads, supported
system claim ceilings, anchored/tethered/assisted/partial/changing/unresolved
loading refusal, missing applicability metadata, refusal preservation of valid
events, takeoff-velocity regression, deterministic v3 serialization,
provenance, comparability, classification, and deferred COM displacement.

## VERSION

`RES47-P1F1-1.0.0`
