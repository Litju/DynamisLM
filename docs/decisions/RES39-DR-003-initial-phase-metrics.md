# RES39-DR-003 — Initial phase-specific metrics

## QUESTION

Which phase metrics are deterministic and scientifically bounded enough for the
first V1 implementation?

## SOURCES

- McMahon et al. (2018), operational CMJ phase definitions:
  <https://eprints.chi.ac.uk/id/eprint/3266/1/UNDERSTANDINGTHEKEYPHASESOFTHECOUNTERMOVEMENTJUMPFORCE-TIMECURVE.pdf>
- RES-37 net-force, trapezoidal impulse, supported-system velocity, and
  relative-displacement decisions.
- RES-39 phase-landmark decision above.

## OPTIONS

Implement all common CMJ outputs, implement only duration/impulse/displacement
quantities with sealed upstream support, or defer all phase metrics until
aggregation and interpretation are authorized.

## DECISION

Implement exactly seven metrics:

- `UNWEIGHTING_DURATION`;
- `BRAKING_DURATION`;
- `PROPULSION_DURATION`;
- `BRAKING_NET_VERTICAL_IMPULSE`;
- `PROPULSION_NET_VERTICAL_IMPULSE`;
- `BRAKING_SUPPORTED_SYSTEM_COM_RELATIVE_DISPLACEMENT_CHANGE`;
- `PROPULSION_SUPPORTED_SYSTEM_COM_RELATIVE_DISPLACEMENT_CHANGE`.

Duration, impulse, and displacement results are numerical derived mechanical
quantities with empty scientific-role tags. Phase occurrences themselves are
structural entities, not automatically measurement observations.

Power is deferred because GRF times COM velocity and net-force times COM
velocity are not interchangeable. RFD, mean/peak force, RSI-mod, asymmetry,
normalization families, vendor strategy metrics, and trial aggregation are also
deferred. RES-40 remains unimplemented.

## PHASE_SYSTEM

All seven metrics require the exact V1 phase-system and phase-definition
references on the phase occurrence and output processing identity.

## BOUNDARIES

The metric boundaries are the sample-attached V1 phase boundaries. The
unweighting interval is movement onset to peak negative velocity; braking is
peak negative velocity to direction change; propulsion is direction change to
takeoff.

## SAMPLE/TIME SEMANTICS

The phase support is `[start_index, end_index]` with endpoint samples retained.
Duration is `end_time_s - start_time_s`, using source regular or explicit times.
The interval is required to have `end_index > start_index`.

Adjacent phase occurrences may share a boundary sample. For impulse, the sealed
RES-37 trapezoid integrates only the intervals `(start_index, end_index]`;
therefore `[peak, direction]` and `[direction, takeoff]` share a sample but do
not integrate the same time interval twice. No phase metric changes the RES-37
integration algorithm.

## EQUATIONS

`duration_phase = t_end - t_start`.

`J_phase = integral(F_net, t_start, t_end)` using the registered RES-37 sample-
attached trapezoid and the phase's inclusive endpoint support.

`delta_z_phase = z_end - z_start` from the sealed supported-system relative
vertical displacement series. This is not anatomical COM displacement.

## INPUTS

Duration requires a valid phase occurrence. Impulse requires the exact linked
RES-37 net vertical force result. Displacement change requires the exact linked
RES-37 supported-system relative displacement result with sample support for
both boundaries.

## ASSUMPTIONS

The upstream system contract is authorized and remains the supported system,
including attached supported load where present. No filtering, drift correction,
resampling, endpoint interpolation, or normalization is applied.

## CLAIM CEILING

Metrics are method-specific supported-system mechanical quantities. They are not
athlete-only eccentric/concentric measures, performance outcomes, joint power,
or biological validity claims.

## PROVENANCE

Each numerical observation records phase occurrence ID/system/definition,
boundary methods and convention, source metric series and observation, source
timebase, source system contract, integration method where applicable, equation,
software version, and decision/evidence lineage.

## COMPARABILITY

Metric values are comparable only under the same phase system, phase definition,
boundary methods, upstream mechanics identity, system contract, timebase,
filtering/drift state, and metric definition. Numeric equality cannot establish
comparability.

## REFUSAL

Unregistered metric, source mismatch, invalid interval, unsupported displacement
boundary, or missing upstream authority blocks only the requested metric and
preserves valid upstream results.

## LIMITATIONS

No trial selection, aggregation, normalization, or interpretation is included.
Sub-sample boundaries are not supported by V1.

## TESTS

Analytic fixtures cover exact durations, regular/irregular time, known braking
and propulsion impulses, displacement deltas, adjacent-boundary integration
support, loaded system identity, provenance, and granular refusal.

## VERSION

`RES39-P1G-1.0.0`; `SERIALIZATION_VERSION=3` retained.
