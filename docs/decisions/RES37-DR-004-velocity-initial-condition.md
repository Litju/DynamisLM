# RES37-DR-004

DECISION_ID=RES37-DR-004
STATUS=ADOPTED
QUESTION=What initial condition and output support make supported-system COM velocity authoritative without asserting unobserved pre-start values?
SCOPE=RES-37 acceleration-to-velocity cumulative integration.

SOURCES=
- `docs/decisions/RES36-DR-001-movement-onset.md`
- `docs/decisions/RES36-DR-004-event-index-time-and-comparability.md`
- [Guess et al., 2020, CMJ COM velocity processing](https://pmc.ncbi.nlm.nih.gov/articles/PMC7761544/)
- [McMahon, Lake & Comfort, 2022, CMJ net-force and trapezoid processing](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0265999)

APPLICABILITY=Valid supported-system acceleration and an explicit initial-condition sample on the same source signal and system.

OPTIONS_CONSIDERED=
- silently set every pre-start array value to zero: rejected because it asserts unintegrated values;
- use an undocumented physical onset instant: rejected because RES-36 onset is an operational sample reference;
- require `v_z=0` at an explicit caller-supplied sample and emit a sliced series beginning there: adopted;
- reset velocity before each event or correct accumulated error: rejected as unregistered drift correction.

DECISION=Register `CMJ_ZERO_INITIAL_VERTICAL_VELOCITY` as the V1 initial-condition method. The condition is `v_z(t_start)=0 m/s` at an explicit sample, optionally linked to the exact RES-36 movement-onset event. The event/sample is an operational reference, not a claim that the threshold sample is the exact physical onset of nonzero velocity. The velocity series begins at that sample and contains only cumulative values supported by the integration interval; no pre-start values are emitted.

EQUATIONS=`v_z(t_start)=0`; then `v_z(t_i)=v_z(t_{i-1})+0.5*(a_z[i-1]+a_z[i])*(t_i-t_{i-1})`.

INPUTS=Supported-system acceleration; explicit inclusive interval whose start equals the initial-condition sample; `InitialVelocityCondition`; optional exact event occurrence.

ASSUMPTIONS=The zero initial condition is authorized as a force-platform quiet/pre-movement operational reference. The supplied event, when present, is sample-attached under RES-36.

INITIAL_CONDITIONS=Value 0.0 m/s; sample index and source signal mandatory; method, assumption text, and optional event ID serialized.

BOUNDARY_SEMANTICS=First output sample is the initial-condition sample with exactly the supplied value. Integration uses adjacent recorded acceleration samples through the inclusive interval end.

NUMERICAL_METHOD=Registered sample-attached trapezoidal integration; actual time deltas.

UNITS=Acceleration m/s²; initial and output velocity m/s.

FRAME_SIGN=Same registered vertical frame and upward-positive sign as acceleration.

LIMITATIONS=No physical onset interpolation, no pre-start zero fill, no takeoff-velocity jump-height estimator, no drift correction, and no claim that threshold onset is an exact physical velocity transition.

REGISTRY_OBJECTS_AFFECTED=`CMJ_SUPPORTED_SYSTEM_COM_VELOCITY_OPERATION`, velocity measurand/metric, `CMJ_ZERO_INITIAL_VERTICAL_VELOCITY`.

IMPLEMENTATION=`src/dynamislm/measurement/cmj/mechanics.py`; source-index mapping preserves the original timebase and provenance records the initial condition and event reference.

TESTS=Missing/misaligned initial condition refusals; exact constant acceleration; sliced support with no pre-start samples; regular and irregular timebases; optional RES-36 event linkage; serialization and consistency identity.

VERSION=RES37-P1E-1.0.0
