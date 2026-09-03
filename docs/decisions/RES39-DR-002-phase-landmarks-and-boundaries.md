# RES39-DR-002 — Phase landmarks and boundaries

## QUESTION

How are peak negative velocity, direction change, and propulsion onset selected
from sampled supported-system COM velocity without hiding a threshold or
interpolation convention?

## SOURCES

- McMahon et al. (2018), operational definitions of unweighting, braking, and
  propulsion, including peak negative COM velocity and zero-velocity language:
  <https://eprints.chi.ac.uk/id/eprint/3266/1/UNDERSTANDINGTHEKEYPHASESOFTHECOUNTERMOVEMENTJUMPFORCE-TIMECURVE.pdf>
- Harry et al. (2020), distinct unloading/yielding/braking/concentric/propulsion
  framework: <https://doi.org/10.1249/MSS.0000000000002197>
- RES-36 event-index/time semantics and RES-46 qualified velocity authority.

## OPTIONS

For peak negative velocity: search the whole trial, search movement onset to
takeoff, or search another hidden window. For direction change: exact zero only,
first nonnegative sample, first positive sample, explicit positive threshold, or
registered sub-sample interpolation.

## DECISION

V1 searches the inclusive source-index interval from movement onset through
takeoff. It selects the minimum velocity value and resolves ties to the earliest
source sample. The selected value must be strictly negative; otherwise the
peak-negative-velocity landmark is refused.

V1 selects direction change as the first sample strictly satisfying
`v_i > 0.0 m/s` after the selected peak-negative-velocity sample and no later
than takeoff. This is also propulsion onset under this V1 system because the
selected phase definition explicitly says so. That local identity does not
create a global `ZERO_VELOCITY == PROPULSION_ONSET` alias.

An exact zero sample is not selected as the V1 direction-change boundary. A
negative-to-positive gap is represented by the selected positive sample and its
preceding source sample; no hidden 0.01 m/s threshold is used.

## PHASE_SYSTEM

`dynamislm:phase-system:cmj-force-com-velocity-v1@1.0.0` with the registered
peak-negative landmark method and first-strictly-positive boundary method.

## BOUNDARIES

`MOVEMENT_ONSET` and `TAKEOFF_CONTACT_LOSS` are the exact RES-36 occurrences.
The peak-negative boundary is a derived sample landmark. The direction-change
boundary and propulsion-onset boundary select the same source sample in V1 but
remain distinct role-specific boundary records; both carry the registered
first-strictly-positive method reference.

## SAMPLE/TIME SEMANTICS

The source sample index is retained. Regular time is computed from the source
regular timebase; explicit time is copied from the source explicit timebase.
The source velocity observation, series, source signal, source observation,
artifact, acquisition, identity, and timebase must all agree with both RES-36
events. No sub-sample boundary exists in V1.

## EQUATIONS

`peak_index = first argmin_i(v_i)` over
`movement_onset.sample_index <= i <= takeoff.sample_index`, with the additional
requirement `v_peak < 0`.

`direction_change_index = first i > peak_index such that v_i > 0.0 m/s`.

`boundary_time = source_timebase(boundary_index)`.

## INPUTS

One authorized `SupportedSystemComVelocityResult` and exact RES-36 movement
onset/takeoff occurrences from the same source.

## ASSUMPTIONS

The velocity series is already qualified by RES-46. The sign convention is
upward-positive. The selected positive sample is an operational sampled
boundary, not a claim that the physical zero crossing occurred at that sample.

## CLAIM CEILING

The landmarks identify deterministic sampled boundaries for this phase system.
They do not claim continuous-time zero crossing, joint action, or equivalence to
another literature phase system.

## PROVENANCE

Each landmark records its source velocity series/observation, source entities,
source timebase, search start/end, selected index/value, tie policy, direction
rule, threshold policy, interpolation policy, system identity, decision, and
processing run.

## COMPARABILITY

Peak search interval, tie rule, direction rule, event detector methods and
parameters, velocity authority, timebase, filtering, and drift state are
material method dimensions.

## REFUSAL

Missing qualified velocity, mismatched source, no strictly negative minimum, or
no strictly positive sample after the minimum yields a granular refusal. A
valid movement-onset or takeoff event is preserved.

## LIMITATIONS

V1 does not interpolate the zero crossing and therefore does not estimate its
continuous-time location. Explicit irregular timebases are supported only as
provided by the source.

## TESTS

Tests cover a unique minimum, tied minimums, exact-zero turnaround,
negative-to-positive off-by-one behavior, regular and irregular time, absence
of the 0.01 threshold, and absence of unregistered interpolation.

## VERSION

`RES39-P1G-1.0.0`; `SERIALIZATION_VERSION=3` retained.
