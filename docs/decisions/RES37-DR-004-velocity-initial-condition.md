# RES37-DR-004

DECISION_ID=RES37-DR-004
STATUS=SUPERSEDED_BY_RES46
QUESTION=What initial condition and output support make supported-system COM velocity authoritative without asserting unobserved pre-start values?
SCOPE=RES-37 acceleration-to-velocity cumulative integration.
SUPERSEDED_BY=RES46-DR-001

SOURCES=
- `docs/decisions/RES36-DR-001-movement-onset.md`
- `docs/decisions/RES36-DR-004-event-index-time-and-comparability.md`
- [Guess et al., 2020, CMJ COM velocity processing](https://pmc.ncbi.nlm.nih.gov/articles/PMC7761544/)
- [McMahon, Lake & Comfort, 2022, CMJ net-force and trapezoid processing](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0265999)

APPLICABILITY=Valid supported-system acceleration and an explicit initial-condition sample on the same source signal and system.

OPTIONS_CONSIDERED=
- silently set every pre-start array value to zero: rejected because it asserts unintegrated values;
- use an undocumented physical onset instant: rejected because RES-36 onset is an operational sample reference;
- require `v_z=0` at an explicit caller-supplied sample and emit a sliced series beginning there: superseded because an index does not establish physical zero velocity;
- reset velocity before each event or correct accumulated error: rejected as unregistered drift correction.

DECISION=The historical RES-37 arbitrary-sample initial-condition contract is not authoritative. Under RES-46, authoritative velocity requires the distinct registered `QualifiedZeroVelocityReference` derived from the exact RES-35 `SystemWeightResult` weighing segment. The reference sample must lie inside that half-open segment and equal the inclusive integration interval start. The RES-36 movement-onset event is not a zero-velocity authority, and no optional event-linked velocity path is registered in V1. The velocity series still begins at the qualified sample and contains only cumulative values supported by the integration interval; no pre-start values are emitted.

EQUATIONS=`v_z(t_start)=0`; then `v_z(t_i)=v_z(t_{i-1})+0.5*(a_z[i-1]+a_z[i])*(t_i-t_{i-1})`.

INPUTS=Supported-system acceleration; explicit inclusive interval whose start equals the qualified reference sample; `QualifiedZeroVelocityReference` derived from the exact compatible RES-35 `SystemWeightResult`.

ASSUMPTIONS=RES-46 adopts the exact RES-35 weighing segment as a protocol-defined pre-movement reference identity. Descriptive RES-35 QC does not universally adjudicate physiological stillness.

INITIAL_CONDITIONS=Value 0.0 m/s; exact source signal, artifact, measurement identity, SYSTEM_WEIGHT observation, weighing segment, method/evidence reference, and sample index are serialized in `QualifiedZeroVelocityReference`. Free-form assumption text and an optional event cannot authorize the physical operation.

BOUNDARY_SEMANTICS=First output sample is the initial-condition sample with exactly the supplied value. Integration uses adjacent recorded acceleration samples through the inclusive interval end.

NUMERICAL_METHOD=Registered sample-attached trapezoidal integration; actual time deltas.

UNITS=Acceleration m/s²; initial and output velocity m/s.

FRAME_SIGN=Same registered vertical frame and upward-positive sign as acceleration.

LIMITATIONS=No physical onset interpolation, no pre-start zero fill, no takeoff-velocity jump-height estimator, no drift correction, and no claim that threshold onset is an exact physical velocity transition.

REGISTRY_OBJECTS_AFFECTED=`CMJ_SUPPORTED_SYSTEM_COM_VELOCITY_OPERATION`, velocity measurand/metric, legacy `CMJ_ZERO_INITIAL_VERTICAL_VELOCITY`, and `CMJ_QUALIFIED_ZERO_VELOCITY_REFERENCE`.

IMPLEMENTATION=`src/dynamislm/measurement/cmj/mechanics.py`; source-index mapping preserves the original timebase and provenance records the qualified reference. See RES46-DR-001 for the current authority model.

TESTS=Historical arbitrary-sample and optional event-linked paths are not authoritative and must refuse; RES-46 tests the qualified reference, exact source/segment linkage, provenance, comparability, serialization, and unchanged trapezoidal/constant-acceleration arithmetic. Existing regular and irregular timebase integration tests remain applicable; no backshift test is claimed.

VERSION=RES37-P1E-1.1.0
