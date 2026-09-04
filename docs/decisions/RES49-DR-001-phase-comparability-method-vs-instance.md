# RES49-DR-001 — Phase comparability method identity versus trial-instance realization

DECISION_ID=RES49-DR-001
STATUS=ADOPTED
QUESTION=Which phase fields establish scientific method comparability, and which fields only identify one realized trial?
PROBLEM=RES-39 phase comparison keys compare observed samples, trial support, source timestamps, integration coordinates, and zero-reference realization details as though they were method identity. This over-refuses same-method V1 phase metrics from distinct trials.

## METHOD_IDENTITY

Method identity answers how the metric was defined, detected, processed, and
calculated. It retains the registered phase system and definition, boundary
roles and conventions, detector identities and material parameters, landmark
tie/threshold/interpolation rules, velocity operation and integration method,
qualified zero-reference authority, timing method characteristics, acquisition
processing, protocol/device/system identity, and metric definition.

## TRIAL_INSTANCE_IDENTITY

Trial-instance identity answers where and when this occurrence realized those
rules. It includes exact observation, signal, artifact, acquisition, event,
phase, boundary, source, sample, timestamp, interval, and QC realization data.
These fields remain in result identity and provenance but do not create a
cross-trial method mismatch by themselves.

## CURRENT_KEY_AUDIT

`_phase_event_semantic_key`: definition, detector method, and material detector
parameters are `METHOD_SEMANTIC`; `source_sample_count`, `sample_index`, and
the concrete `SignalTimebase` values are `TRIAL_INSTANCE_REALIZATION` or a
mixed timebase representation. The effective baseline threshold and baseline
QC/segment coordinates are realized observations, not a new detector method.

`_phase_integration_interval_key`: interval kind, boundary convention,
integration method, and event-bound method semantics are `METHOD_SEMANTIC`;
source signal and start/end indices are `TRIAL_INSTANCE_REALIZATION`.

`_event_boundary_key`: boundary role, registered method/definition,
detector-method parameters, tie/threshold/interpolation policies, and timing
method characteristics are `METHOD_SEMANTIC`; event IDs, event coordinates,
derived search endpoints, and exact timestamp values are
`TRIAL_INSTANCE_REALIZATION`.

`_phase_velocity_processing_key`: registered operations, processing policies,
units, axes/frames/sign, gravity/mass/system semantics, and selection/method
references are `METHOD_SEMANTIC`; source IDs, embedded interval coordinates,
zero-reference IDs/index/QC numeric values, weighing segment coordinates, and
trial sample support are `TRIAL_INSTANCE_REALIZATION`.

`_phase_method_key`: the aggregate is `METHOD_SEMANTIC` only after consuming
the separated method keys above. It must not reintroduce instance coordinates
through a nested source, event, interval, reference, or timebase value.

## EVENT_METHOD_KEY

Retain event definition and detector method IDs/versions, threshold family,
absolute threshold or baseline-SD method parameters, direction, dwell, and
declared detector search semantics. Under the current RES-36 contract, the
configured detector `search_start_index` is an explicit method parameter and is
retained. Exclude occurrence index/time, trial length, source IDs, baseline
observation/segment coordinates, realized baseline statistics, and effective
threshold realization. The resulting event sample/time is a trial realization.

The configured RES-36 detector `search_start_index` is distinct from the
`CMJPhaseBoundary.search_start_index` / `search_end_index` values derived from
realized events or landmarks. Those phase search supports remain
`TRIAL_INSTANCE_REALIZATION` and are excluded from method identity.

A future typed relative search-origin contract may replace the raw configured
integer with registered semantics; that redesign is out of scope for RES-49.

## BOUNDARY_METHOD_KEY

Retain boundary role, registered boundary/event method and definition,
normalized event detector method parameters, tie policy, strict-positive or
other threshold rule, interpolation policy, and timing method. Exclude
event/sample/time/source coordinates and search endpoints derived from the
realized onset, peak, direction, or takeoff occurrences.

## INTEGRATION_METHOD_KEY

Retain registered interval kind when method-relevant, sample-attached boundary
convention, trapezoidal integration method, and any event-bound method keys.
Exclude the realized interval source signal and start/end indices. The phase
and metric objects still validate exact interval/source lineage internally.

## ZERO_REFERENCE_METHOD_KEY

Retain qualified zero-reference method and evidence decision, the registered
unit/zero-value convention, weighing/reference selection method and parameters,
and the QC authority state that controls admissibility. Exclude source
observation/signal/artifact/identity IDs, weighing segment coordinates,
reference sample index, and QC numeric realizations when the registered
authority method is unchanged.

## TIMEBASE_METHOD_KEY

Retain regular versus explicit timing kind, declared sample rate when present,
clock reference, description, and existing CMJ acquisition identity rules.
Regular 1000 Hz and regular 500 Hz remain distinct; regular and explicit remain
distinct absent a bridge. Regular start time and explicit absolute timestamp
origins are trial realizations, not method identity.

## FIELDS_RETAINED_FOR_COMPARABILITY

Phase-system/definition IDs, boundary roles/conventions, detector and landmark
method IDs/versions and material parameters, tie/threshold/interpolation rules,
velocity operation/integration/initial-condition authority, processing and
filter/resampling/drift policies, timing characteristics, protocol, device,
measuring system, firmware/calibration, channel/axis/frame/sign, supported
system/loading contract, metric/measurand/unit/operation, and claim-relative
acquisition identity remain material.

## FIELDS_REMOVED_FROM_METHOD_COMPARABILITY

Observed event and boundary indices/times, realized phase support and duration,
trial length, derived search-window endpoints, velocity interval indices,
absolute explicit timestamp values, source observation/signal/artifact/
acquisition/identity/result/occurrence IDs, zero-reference IDs/indexes/segment
coordinates/QC numeric values, and equivalent trial-instance lineage fields.

## PROVENANCE_POLICY

No serialized scientific observation or provenance field is removed. Exact
coordinates and source IDs remain available for audit, lineage, and result
identity.

## INSTANCE_VALIDATION_POLICY

Within-object source validation remains exact: source membership, same-source
events, sample support, timestamp formulas, mechanics lineage, integration
support, phase endpoints, and provenance edges continue to be enforced.

## COMPARABILITY_EFFECT

Same registered methods with different realized coordinates, values, durations,
trial lengths, or absolute timestamp origins may be `COMPARABLE` when all
material method/acquisition/system dimensions match.

## REFUSAL_EFFECT

True phase-system, phase-definition, boundary-rule, detector-parameter,
integration-method, zero-reference-authority, timebase/sampling, loading, and
supported-system differences retain bridge-required or not-comparable outcomes
under the existing refusal architecture.

## SERIALIZATION_EFFECT

Comparator logic only changes. `SERIALIZATION_VERSION=3`; historical serialized
objects, provenance, and canonical hashes are unchanged.

## LIMITATIONS

Explicit timing method characteristics remain bounded by the registered CMJ
acquisition identity. A later claim that requires exact timestamp-pattern or
trial-specific QC equivalence needs a more specific registered rule.

## IMPLEMENTATION

`src/dynamislm/measurement/cmj/phases.py` separates
`_phase_event_method_key`, `_phase_boundary_method_key`,
`_velocity_integration_method_key`, `_zero_velocity_reference_method_key`,
`_timebase_method_key`, source-identity, processing, and aggregate method keys.
No RES-39 arithmetic/detection or RES-40 code changes.

## TESTS

The reproduction test uses same-method V1 braking metrics with onset/peak/
direction/takeoff coordinates `(4,6,7,8)` and `(5,7,8,9)` and is expected to
fail on the unrepaired RES-39 comparator. Follow-up tests cover retained method
mismatches, timing/sampling nuance, zero-reference authority, provenance, and
serialization invariants.

## VERSION

RES49-P1G1-1.0.0
