# RES39-DR-001 — CMJ force-platform COM-velocity phase system V1

## QUESTION

Which single computational CMJ phase system is authorized for RES-39, and what
does its terminology mean? The governing constraint is that a shared label does
not establish a shared definition, boundary, or mechanical interpretation.

## SOURCES

- McMahon, Suchomel, Lake & Comfort (2018), *Understanding the Key Phases of
  the Countermovement Jump Force-Time Curve*, accepted manuscript:
  <https://eprints.chi.ac.uk/id/eprint/3266/1/UNDERSTANDINGTHEKEYPHASESOFTHECOUNTERMOVEMENTJUMPFORCE-TIMECURVE.pdf>
- Harry, Barker & Paquette (2020), *A Joint Power Approach to Define
  Countermovement Jump Phases Using Force Platforms*, DOI:
  <https://doi.org/10.1249/MSS.0000000000002197>
- RES-36 event decisions; RES-37 supported-system mechanics decisions;
  RES-46 qualified velocity decision.

## OPTIONS

1. Adopt a single force-platform / supported-system COM-velocity operational
   system associated with McMahon et al. (2018).
2. Adopt the Harry et al. joint-power-informed unloading/yielding/braking
   terminology as the computational system.
3. Merge labels from both traditions into a universal ontology.

## DECISION

Option 1 is authorized as `CMJ_FORCE_COM_VELOCITY_PHASE_SYSTEM_V1`, registry
version `1.0.0`. V1 contains only `UNWEIGHTING`, `BRAKING`, and `PROPULSION`.
The system consumes the exact RES-46-qualified RES-37 supported-system COM
velocity series and reuses the sealed RES-36 movement-onset and takeoff events.

The Harry et al. terminology remains a distinct scientific system. In that
framework, eccentric action is yielding plus braking; that statement is not a
global alias in this repository. `BRAKING` is not globally `ECCENTRIC`,
`PROPULSION` is not globally `CONCENTRIC`, and `UNWEIGHTING` is not globally
`YIELDING`.

## PHASE_SYSTEM

- ID: `dynamislm:phase-system:cmj-force-com-velocity-v1@1.0.0`
- Definitions:
  `dynamislm:phase-definition:cmj-force-com-velocity-unweighting-v1@1.0.0`,
  `...:braking-v1@1.0.0`, and `...:propulsion-v1@1.0.0`.
- Software implementation identity: `dynamislm-res39-1.0.0`.

## BOUNDARIES

- `UNWEIGHTING`: sealed movement onset through peak negative supported-system
  COM velocity.
- `BRAKING`: peak negative supported-system COM velocity through the V1
  direction-change boundary.
- `PROPULSION`: the V1 propulsion-onset boundary, which selects the same source
  sample as direction change but is represented by its own role-specific
  boundary record, through sealed takeoff/contact loss.

Flight and landing remain independent RES-36 events, not phase occurrences.
No `ECCENTRIC`, `CONCENTRIC`, `YIELDING`, `AMORTIZATION`, `FLIGHT`, or
`LANDING_IMPACT` computational phase object is added by this decision.

## SAMPLE/TIME SEMANTICS

Every V1 phase boundary is attached to an existing source sample. Regular time
is `start_time_s + sample_index / sample_rate_hz`; explicit time is the exact
`times_s[sample_index]`. A transition between negative and positive samples is
not represented as an exact physical zero unless an independently registered
operation later authorizes that representation.

## EQUATIONS

No equation is introduced here. The phase system consumes the already-qualified
velocity output of RES-37/46 and preserves its supported-system, sign, timebase,
and integration identity.

## INPUTS

- one exact RES-46-authorized supported-system COM velocity result;
- one exact RES-36 movement-onset occurrence;
- one exact RES-36 takeoff/contact-loss occurrence;
- common source observation, signal, artifact, acquisition, identity, and
  timebase support.

## ASSUMPTIONS

The source velocity sign convention is upward-positive, as required by the
upstream mechanics contract. The input represents the supported system (an
athlete plus any attached supported load), not athlete-only mechanics.

## CLAIM CEILING

V1 supports operational phase intervals and the registered phase metrics only.
It does not establish anatomical COM equivalence, universal phase semantics,
joint power, muscle action, performance outcome status, or biological validity
of a synthetic fixture.

## PROVENANCE

Phase-system and phase-definition references, source velocity identity and
series, source events, boundary methods, source timebase, system contract,
RES-39 software version, decision references, and exact source entities must be
retained on every phase occurrence and metric.

## COMPARABILITY

The phase-system ID/version, phase definition, boundary methods, event methods,
velocity authority, timebase, filtering/drift state, and supported-system
contract are material. A shared label alone is never sufficient.

## REFUSAL

Unregistered phase systems, unqualified velocity, source mismatch, unresolved
landmarks, or invalid intervals produce granular RES-39 refusals. They do not
invalidate independently valid upstream events, velocity, force, or jump-height
estimators.

## LIMITATIONS

This is one deliberately narrow computational system. It is not a universal
CMJ ontology and does not implement the Harry et al. system.

## TESTS

Tests cover versioned identity, non-aliasing, qualified-source checks,
sample/time semantics, serialization, and refusal preservation.

## VERSION

`RES39-P1G-1.0.0`; `SERIALIZATION_VERSION=3` retained.
