DECISION_ID: RES36-DR-001
STATUS: ADOPTED

QUESTION

Which deterministic movement-onset event method is registered for the first
CMJ event-detection foundation?

SCOPE

MOVEMENT_ONSET only. This decision defines the event boundary and detector
identity; it does not define braking, propulsion, impulse, force integration,
or any other CMJ phase or derived quantity.

SOURCES

- [The effect of three different start thresholds on the kinematics and kinetics of a countermovement jump](https://pubmed.ncbi.nlm.nih.gov/20664368/)
- [The effect of different movement onset thresholds on countermovement jump performance](https://pmc.ncbi.nlm.nih.gov/articles/PMC9783824/)
- [Reliability and magnitude of loaded countermovement jump performance variables: a technical examination of the jump threshold initiation](https://pubmed.ncbi.nlm.nih.gov/31711369/)
- Owen et al., 2014, [Journal of Strength and Conditioning Research](https://doi.org/10.1519/JSC.0000000000000311)

APPLICABILITY

These primary methods establish that movement-onset operationalizations are
materially different and can change downstream CMJ quantities, including in
loaded jumps. They support explicit method registration and parameter
preservation, but they do not establish biological validity for every device,
population, or force-processing pipeline in DynamisLM.

OPTIONS_CONSIDERED

- baseline-noise deviation using a force-platform baseline;
- fixed absolute-force deviation;
- relative system-weight deviation;
- a threshold crossing shifted backward by a fixed duration;
- registering multiple families immediately.

DECISION

Register `CMJ_MOVEMENT_ONSET_BASELINE_SD@1.0.0`. The detector uses the exact
RES-35 `SystemWeightResult` and its linked `WeighingSegment`/baseline QC for
the same qualified supported-force observation. Its threshold is

`baseline_mean_force_n - sigma_multiplier * baseline_standard_deviation_n`

and the event is the first sample of the earliest contiguous run of
`dwell_samples` samples strictly below that threshold, searched from the
explicit `search_start_index`. No backward shift is part of this registered
method.

RATIONALE

Baseline-deviation and relative/absolute threshold families are not
interchangeable. A baseline-SD family is a small, evidence-backed foundation
that can use the already-authorized RES-35 baseline without deriving system
mass. The multiplier, direction, dwell, baseline identity, baseline segment,
and search start are explicit parameters rather than hidden defaults.

PARAMETERS

- `direction = BELOW_THRESHOLD`;
- `sigma_multiplier` is required and finite, with no project-wide default;
- exact baseline observation, segment, mean, and standard deviation are
  required;
- `dwell_samples` is required and sample-count based;
- `search_start_index` is required and must not precede the weighing segment;
- crossing equality does not qualify;
- candidate tie-break: earliest qualifying run, with a structural QC flag when
  later qualifying runs also exist.

ASSUMPTIONS

The supplied force signal is already qualified under RES-34/RES-35 semantics,
is upward-positive vertical force in N, and has a valid regular or explicit
timebase. RES-35 descriptive QC is preserved; RES-36 does not invent a quiet-
standing acceptability rule.

LIMITATIONS

Only this baseline-SD family is registered. Relative-system-weight, fixed
absolute-deviation, and backward-shift alternatives remain distinct deferred
methods. This detector identifies an operational onset sample only; it does
not identify braking onset or any phase.

REGISTRY_OBJECTS_AFFECTED

- `CMJ_MOVEMENT_ONSET_EVENT_DEFINITION@1.0.0`;
- `CMJ_MOVEMENT_ONSET_BASELINE_SD_METHOD@1.0.0`;
- `CMJ_EVENT_COMPARABILITY_RULE@1.0.0`.

IMPLEMENTATION

`src/dynamislm/measurement/cmj/events.py` consumes a qualified total-force
input and a validated `SystemWeightResult`. It never imports or consumes
`SystemMassResult`, gravity, or body mass.

TESTS

Synthetic traces cover exact baseline linkage, parameter identity, clean
onset, no crossing, transient crossings that fail dwell, multiple candidates,
regular/explicit timebases, and immutable source samples.

VERSION

1.0.0
