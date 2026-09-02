# RES37-DR-002

DECISION_ID=RES37-DR-002
STATUS=ADOPTED
QUESTION=What deterministic integration method and interval boundary semantics govern RES-37 impulse and cumulative kinematics?
SCOPE=Scalar NET_VERTICAL_IMPULSE and cumulative acceleration-to-velocity or velocity-to-relative-displacement integration.

SOURCES=
- `docs/decisions/RES36-DR-004-event-index-time-and-comparability.md`
- `docs/decisions/RES45-DR-003-processing-output-entity-contract.md`
- [Linthorne, 2001, Analysis of standing vertical jumps using a force platform](https://bura.brunel.ac.uk/handle/2438/1392)
- [Linthorne, 2001 DOI record](http://dx.doi.org/10.1119/1.1397460)
- [McMahon, Lake & Comfort, 2022, force-platform CMJ processing](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0265999)
- [Guess et al., 2020, CMJ force-time processing](https://pmc.ncbi.nlm.nih.gov/articles/PMC7761544/)

APPLICABILITY=Validated finite CMJ force, acceleration, or velocity series with a registered regular or explicit timebase and an explicit RES-37 integration interval.

OPTIONS_CONSIDERED=
- nominal sample-rate multiplication: rejected for explicit or irregular timestamps;
- hidden interpolation at an event crossing: rejected because RES-36 events are sample-attached and no interpolation is registered;
- sample-attached trapezoidal integration using adjacent recorded samples: adopted;
- implicitly pass integer endpoints: rejected because an interval is a scientific object with source, method, and boundary identity.

DECISION=Register sample-attached trapezoidal integration. For samples `y_i` at timestamps `t_i`, `I_i = I_{i-1} + 0.5*(y_{i-1}+y_i)*(t_i-t_{i-1})`. Regular timebases use their exact `1/fs` interval; explicit timebases use the actual adjacent timestamp difference. `CMJIntegrationInterval` uses inclusive endpoint sample indices `[start_sample_index, end_sample_index]` and therefore includes the trapezoid ending at the end sample. Event-bounded intervals resolve to the event sample selected by RES-36; the event sample is included, with no sub-sample interpolation. Explicit sample intervals and event-bounded intervals remain distinct kinds.

EQUATIONS=
- `J = sum(i=start+1..end) 0.5*(F_net,z[i-1]+F_net,z[i])*(t_i-t_{i-1})`;
- `v_i = v_{i-1} + 0.5*(a[i-1]+a[i])*(t_i-t_{i-1})`;
- `d_i = d_{i-1} + 0.5*(v[i-1]+v[i])*(t_i-t_{i-1})`.

INPUTS=Immutable source series; inclusive interval; registered integration method/version; for event-bounded intervals, exact source event occurrence references.

ASSUMPTIONS=Adjacent samples represent the values used by the registered numerical approximation. A regular timebase start time affects timestamps but not adjacent deltas. No sample is manufactured between recorded samples.

INITIAL_CONDITIONS=Scalar impulse has no state. Cumulative integration starts from the explicitly supplied initial value at the interval start; velocity and displacement define their own conditions in RES37-DR-004 and RES37-DR-005.

BOUNDARY_SEMANTICS=Event endpoint is the first qualifying sample of the RES-36 dwell run, included as the final endpoint sample. The preceding sample is not selected as an alternative endpoint, and no crossing interpolation is performed.

NUMERICAL_METHOD=Registered `CMJ_TRAPEZOIDAL_INTEGRATION_METHOD`; deterministic core-Python arithmetic over adjacent samples and actual timestamp deltas.

UNITS=Force integral N·s; acceleration integral m/s; velocity integral m; all units explicit.

FRAME_SIGN=Input axis/frame/sign are preserved; positive vertical direction is upward.

LIMITATIONS=No phase labels, braking/propulsive intervals, endpoint correction, zero-velocity update, detrending, spline, filtering, resampling, or drift repair.

REGISTRY_OBJECTS_AFFECTED=`CMJ_TRAPEZOIDAL_INTEGRATION_METHOD`, `CMJ_INCLUSIVE_SAMPLE_INTEGRATION_BOUNDARY`, `CMJ_NET_VERTICAL_IMPULSE_OPERATION`, `NEWTON_SECOND`, `METERS_PER_SECOND`, `METER`.

IMPLEMENTATION=`src/dynamislm/measurement/cmj/mechanics.py`; interval and method are serialized and included in processing parameters and provenance.

TESTS=Regular nonzero-start timebases at multiple rates; explicit irregular timestamps; exact scalar and cumulative oracles; event endpoint off-by-one fixture; no interpolation; serialization and consistency identities.

VERSION=RES37-P1E-1.0.0
