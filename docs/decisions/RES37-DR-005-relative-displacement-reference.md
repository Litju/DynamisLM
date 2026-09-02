# RES37-DR-005

DECISION_ID=RES37-DR-005
STATUS=ADOPTED
QUESTION=What coordinate reference and integration semantics define RES-37 supported-system COM displacement?
SCOPE=Velocity-to-displacement cumulative integration only.

SOURCES=
- `docs/decisions/RES37-DR-002-impulse-and-integration-semantics.md`
- `docs/decisions/RES37-DR-004-velocity-initial-condition.md`
- [McMahon, Lake & Comfort, 2022, force-platform displacement processing](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0265999)
- [Guess et al., 2020, CMJ COM waveform processing](https://pmc.ncbi.nlm.nih.gov/articles/PMC7761544/)

APPLICABILITY=Valid supported-system COM velocity with an explicit displacement-origin contract.

OPTIONS_CONSIDERED=
- report absolute COM position: rejected because force-platform integration supplies no anatomical height origin;
- silently set an anatomical COM height to zero: rejected because it overclaims coordinate information;
- define relative displacement zero at the velocity initial-condition sample: adopted;
- detrend, force landing to zero, or apply a zero-velocity update: rejected because no correction is registered.

DECISION=Register `CMJ_RELATIVE_DISPLACEMENT_ZERO_ORIGIN`. The output is `SUPPORTED_SYSTEM_COM_RELATIVE_VERTICAL_DISPLACEMENT`. Its coordinate origin is zero at the explicit first velocity sample/initial-condition reference. This is a coordinate origin, not anatomical COM height zero and not `ABSOLUTE_COM_POSITION`. Integrate velocity with the same registered trapezoidal method, preserve upward-positive sign, and leave the uncorrected cumulative result unchanged.

EQUATIONS=`d_z(t_start)=0 m`; then `d_z(t_i)=d_z(t_{i-1})+0.5*(v_z[i-1]+v_z[i])*(t_i-t_{i-1})`.

INPUTS=Supported-system COM velocity; explicit zero-origin object linked to the velocity series and start sample.

ASSUMPTIONS=Velocity is already valid under the RES-46 qualified zero-velocity integration-start contract (RES46-DR-001 and the corrected RES37-DR-004). The relative coordinate is sufficient for V1 and does not encode anatomical height.

INITIAL_CONDITIONS=Displacement value 0.0 m at the velocity series start; no endpoint constraint.

BOUNDARY_SEMANTICS=Output support matches the supplied velocity series. First sample is exactly the declared origin; every later value is the cumulative integral over recorded adjacent samples.

NUMERICAL_METHOD=Registered sample-attached trapezoidal integration using actual time deltas; no hidden endpoint correction.

UNITS=Input m/s; output m.

FRAME_SIGN=Registered vertical frame; upward positive.

LIMITATIONS=Relative only; no absolute COM position, landing-zero enforcement, detrending, spline, filtering, zero-velocity update, jump height, or phase displacement.

REGISTRY_OBJECTS_AFFECTED=`CMJ_SUPPORTED_SYSTEM_COM_RELATIVE_DISPLACEMENT_OPERATION`, displacement measurand/metric, `CMJ_RELATIVE_DISPLACEMENT_ZERO_ORIGIN`.

IMPLEMENTATION=`src/dynamislm/measurement/cmj/mechanics.py`; origin, source velocity identity, series mapping, and correction state are provenance-bearing.

TESTS=Missing/misaligned origin refusal; constant velocity quadratic displacement; exact zero-force/zero-velocity conservation; loaded-system label; no drift repair; provenance and v3 roundtrip.

VERSION=RES37-P1E-1.0.0
