# RES66-DR-001 — Strength, IMTP and VBT scientific engine

DECISION_ID=RES66-DR-001
STATUS=ADOPTED_FOR_RES66
MISSION=RES-66-IMPLEMENTATION
SERIALIZATION_VERSION=3

## Question and scope

Which strength, isometric mid-thigh pull (IMTP), and velocity-based testing
(VBT) quantities can receive deterministic DynamisLM authority while keeping
exercise, protocol, load, device, phase, metric, value origin, and provenance
identity explicit?

This is an additive P1 scientific slice for IMTP, squat VBT, and bench-press
VBT. It does not prescribe training, infer fatigue/readiness/injury risk,
infer physiological mechanisms, choose an optimal/recommended load, train a
model, use a GPU, or perform model inference.

The following invariants are locked for this decision:

```text
1RM_MEASURED != 1RM_ESTIMATED
MEAN_CONCENTRIC_VELOCITY != MEAN_PROPULSIVE_VELOCITY != PEAK_VELOCITY
EXERCISE_LABEL != SCIENTIFIC_PROTOCOL_IDENTITY
DEVICE_CORRELATION != DEVICE_AGREEMENT
LOAD_VELOCITY_MODEL_ESTIMATE != DIRECT_STRENGTH_MEASUREMENT
VELOCITY_LOSS != FATIGUE_STATE
RFD != UNIVERSAL_METRIC
SAME_LOAD_VALUE != COMPARABLE_FIXED_LOAD_MEASUREMENT
```

## Authority inspected

The implementation reuses the sealed generic observation, measurement
identity, result, provenance, refusal, comparability, and Serialization V3
contracts. It also follows the source/context/processing-run validation
pattern fixed by RES-65. CMJ semantics, RES-64 external-load semantics,
RES-63 canonical dataset authority, and historical hashes are not changed.

The vertical identity is separate from CMJ. IMTP is not represented as a
renamed CMJ force test, and VBT bar velocity is not represented as supported
system COM velocity.

## Evidence reviewed

The following starting sources were resolved by PMID and their available
methods/abstracts were checked on 2026-09-15:

### IMTP

* Brady, Harrison and Comyns, PMID [29781788](https://pubmed.ncbi.nlm.nih.gov/29781788/), reviews IMTP force-time reliability and the heterogeneity of force-time analysis methods.
* Grgic et al., PMID [35309521](https://pubmed.ncbi.nlm.nih.gov/35309521/), systematic review of peak-force test-retest reliability; the review extracted protocol, posture, familiarisation and warm-up differences and reports heterogeneous reliability.
* Dos'Santos et al., PMID [28002178](https://pubmed.ncbi.nlm.nih.gov/28002178/), directly compares onset thresholds and recommends a 5-SD body-weight baseline threshold for time-specific force and RFD while showing that thresholds are not interchangeable.
* Guppy et al., PMID [35482542](https://pubmed.ncbi.nlm.nih.gov/35482542/), shows that short and traditional trial durations change time-dependent force, RFD and impulse and that analysis choices affect reliability.
* Stevens et al., PMID [41135598](https://pubmed.ncbi.nlm.nih.gov/41135598/), reports procedure, ranking and summarization effects for peak and early force measures.
* Haff et al., PMID [25259470](https://pubmed.ncbi.nlm.nih.gov/25259470/), compares predetermined endpoint RFD bands with peak-window and average-RFD methods and supports keeping them as distinct method identities.
* Dos'Santos et al., PMID [28933711](https://pubmed.ncbi.nlm.nih.gov/28933711/), shows hip-angle/posture effects on peak force, time-specific force, RFD and net force.

These sources justify preserving protocol, posture, sampling, filtering,
onset, window, force quantity, normalization, trial selection and aggregation
as identity dimensions. They do not justify a universal onset, universal RFD,
or universal normalization.

### VBT and load-velocity

* Garnacho-Castaño et al., PMID [25729300](https://pubmed.ncbi.nlm.nih.gov/25729300/), compares Tendo and T-Force outputs for bench press and full squat; the methods distinguish vendor average/peak concentric outputs from a 1000-Hz, filtered reference series and report proportional biases.
* Dorrell et al., PMID [29851551](https://pubmed.ncbi.nlm.nih.gov/29851551/), evaluates GymAware across free-weight squat, bench press, deadlift and CMJ with exercise-specific agreement/reliability.
* Fritschi et al., PMID [34564328](https://pubmed.ncbi.nlm.nih.gov/34564328/), compares devices and attachment positions against motion capture and defines mean and peak concentric velocity over exercise-specific phase rules.
* González-Galán et al., PMID [39409484](https://pubmed.ncbi.nlm.nih.gov/39409484/), directly compares Vitruve and T-Force in Smith-machine bench press and squat; it selects the fastest repetition per absolute load and finds exercise/velocity-range/device-dependent agreement, especially poorer peak-velocity agreement.
* Wannouch et al., PMID [40920738](https://pubmed.ncbi.nlm.nih.gov/40920738/), systematic review, requires criterion comparison and multidimensional validity/reliability evidence and emphasizes device and exercise heterogeneity.
* Greig et al., PMID [37493929](https://pubmed.ncbi.nlm.nih.gov/37493929/), systematic review/IPD meta-analysis; eligible models are exercise and equipment specific, extrapolate beyond calibration loads, and tend to overestimate 1RM.
* Janicijevic et al., PMID [33771947](https://pubmed.ncbi.nlm.nih.gov/33771947/), compares linear/polynomial models and terminal-velocity thresholds for paused and touch-and-go Smith-machine bench press and supports a protocol-specific general 0.17 m/s terminal velocity for that narrow setting.
* Sánchez-Medina and González-Badillo, PMID [21311352](https://pubmed.ncbi.nlm.nih.gov/21311352/), defines velocity loss against explicit set/repetition measurements but its physiological/fatigue interpretation is outside RES-66 authority.
* Claassen et al., PMID [42690493](https://pubmed.ncbi.nlm.nih.gov/42690493/), systematic review/meta-analysis available at the mission date; its heterogeneity and remaining measurement-error/agreement limitations reinforce device-, exercise- and model-specific identity.

The review evidence supports deterministic arithmetic on a qualified velocity
series. It does not turn a correlation into agreement, a vendor scalar into a
reconstructed raw bar trajectory, or a load-velocity estimate into measured
strength.

## Shared strength identity

The new `strength` package registers an explicit protocol identity with
unknown-preserving fields for exercise/variant, equipment and free-weight vs
Smith vs fixed-rig mode, range of motion, joint/posture and bar position, grip
and stance, pause/touch-and-go semantics, typed external load, device/system
and provider, sensor modality and attachment, sampling/timebase, processing
and software/firmware, repetition selection and trial selection. Absent
material fields remain unresolved; no exercise label fills them.

Loads preserve value, unit, implementation type, bar mass, added load, total
external load semantics and the distinction between physical load and a
percentage of 1RM. Fixed-load comparison uses the complete typed load
identity, not its numeric value alone.

## Disposition matrix

Every candidate quantity has exactly one RES-66 disposition.

| Quantity | V1 authority and exact identity | Disposition |
| --- | --- | --- |
| IMTP onset | Baseline mean + exactly `5.0 * sample_SD`, strict upward crossing, one-sample dwell, first sample of the earliest qualifying run, explicit baseline/search support, no interpolation. The method is adopted explicitly here; 5 SD is not a global onset default. | IMPLEMENT |
| IMTP peak force | Sampled maximum over exact onset-to-registered trial-end support. Gross vertical force and net force above the registered baseline are separate measurands/metrics. No continuous/interpolated maximum. | IMPLEMENT |
| IMTP force at time | Registered 50, 100, 150 and 200 ms windows from exact onset. Exact source sample only; a non-representable target time is refused rather than rounded or silently interpolated. | IMPLEMENT |
| IMTP impulse | Gross or net force, exact onset and explicit interval, sample-attached trapezoidal integration using actual timestamps. | IMPLEMENT |
| IMTP RFD | Average endpoint RFD `((F(T) - F(onset)) / T)` for registered 0–50, 0–100, 0–150 and 0–200 ms windows, exact endpoints, gross/net quantity retained. | IMPLEMENT |
| IMTP peak/derivative RFD | Differentiated-sample peak RFD, arbitrary moving windows and unregistered regressions are not V1 authority. | REJECT_FROM_RES66 |
| IMTP normalization | Absolute N and N/kg only. N/kg requires a typed, context-bound BODY_MASS observation; arbitrary caller scalars and allometric normalization are refused. | IMPLEMENT |
| IMTP trial selection/aggregation | Explicit best sampled peak, mean of all eligible trials, and mean of best N rules; no implicit selection. Short/traditional protocols remain distinct. | IMPLEMENT |
| Mean concentric velocity | Time mean `integral(v dt) / duration` over an exact qualified concentric support using actual timestamps. It is not a sample arithmetic mean or a vendor scalar relabel. | IMPLEMENT |
| Mean propulsive velocity | Represented as a distinct metric, but no V1 computation: acceleration/gravity/differentiation/filtering/boundary authority is not frozen for the target input contract. | REPRESENT_BUT_DO_NOT_COMPUTE |
| Peak velocity | Maximum sampled velocity over exact qualified concentric support; no interpolation. | IMPLEMENT |
| Repetition/phase authority | Set, rep, exercise/protocol, load and exact concentric support are required from a qualified upstream phase/evidence object. Scalar velocity cannot create a phase. | REPRESENT_BUT_DO_NOT_COMPUTE |
| Fixed-load longitudinal comparison | Same complete method identity and exact physical load may compare. Device differences require a registered bridge; protocol, metric, phase, processing, sampling, attachment, ROM or load mismatches fail closed. | IMPLEMENT |
| Measured 1RM | First-class direct/source-reported successful-repetition result with explicit protocol, load, rep, session and selection criteria. It cannot be constructed from a model. | IMPLEMENT |
| Estimated 1RM | Only a `MODEL_ESTIMATE` result from a registered individual linear model and a protocol-specific terminal-velocity assumption. Smith-machine bench press 0.17 m/s is the only V1 terminal assumption registered; other protocols refuse. | IMPLEMENT |
| Individual load-velocity model | Deterministic ordinary least-squares linear fit of typed calibration points with the same athlete/protocol/device and one registered velocity metric; coefficients, loads, diagnostics and terminal-velocity applicability are retained. | IMPLEMENT |
| Velocity loss | Mechanical within-set percentage with explicit first/fastest/best-previous reference rule, same set/rep metric/load identity and exact source provenance. It carries no fatigue/readiness authority. | IMPLEMENT |
| Canonical strength dataset mapping | Current promoted P2D authority contains no qualified IMTP force-time or VBT repetition series mapping. | REJECT_FROM_RES66 |

## Exact computational rules

### IMTP

For a qualified force series `F[i]` and timebase `t[i]`, the adopted onset
threshold is `baseline_mean + 5 * baseline_sample_SD`. The detector uses the
first sample of the earliest contiguous run satisfying `F[i] > threshold`.
The run must start at or after explicit search support and uses registered
one-sample dwell. Onset, baseline, threshold, direction, dwell, sample
convention and source context are immutable identity/provenance.

Peak uses `max(F[i])` over exact inclusive source samples. Net force above
baseline is `F[i] - baseline_mean` and is never relabelled as a universal net
force or as body-mass-normalized force.

Force-at-time uses only a source sample whose exact timestamp equals
`onset_time + T`; arbitrary times, nearest-sample substitution and hidden
rounding refuse. Impulse is the sum of sample-attached trapezoids over an
explicit inclusive interval. RFD is the endpoint difference divided by the
registered duration. No peak differentiated RFD is emitted.

### VBT

The source series remains outside `MeasurementResult` and is referenced by an
immutable source artifact/digest. Provider-processed velocity is recorded as
provider-derived; DynamisLM derives only reproducible statistics from the
qualified delivered series and does not claim raw bar-kinematics recovery.

Mean concentric velocity is the time-weighted trapezoidal mean over the exact
qualified phase. Peak velocity is the sampled maximum. The phase object binds
the source observation, set, rep, source series, exact indices/times, phase
definition, boundary method/parameters, and producing processing run.

MPV is not computed by averaging the concentric series. A future MPV method
would need registered propulsive acceleration, gravity reference,
differentiation, filtering, sampling and boundary semantics.

The individual load-velocity fit is `v = intercept + slope * load` with
ordinary least squares over at least two distinct physical loads, requiring a
negative slope for inverse load-velocity use. Estimated 1RM is
`(terminal_velocity - intercept) / slope`, only for the registered
Smith-machine bench protocol and 0.17 m/s assumption. Both outputs remain
model-derived and retain calibration provenance; a high R or R² never creates
device agreement or measured-strength authority.

Velocity loss is `100 * (reference - current) / reference`, with a positive
finite reference and an explicit reference-repetition rule. First, fastest and
best-previous references are distinct identities; cross-set and metric/load
mismatches refuse.

## Provenance and adversarial boundary

Every derived output is created with an exact source observation context and a
new processing run. The output identity, processing-run method/parameters,
source artifacts, source observations, source series, phase/rep entities and
result scalar are mutually revalidated on construction. Legitimate identity +
arbitrary value, legitimate source + arbitrary context, mutated method fields,
source-series digest changes, output-context rebinding, and rep/set/phase/load
substitution fail closed.

## Dataset and historical effects

`CANONICAL_STRENGTH_DATASET_MAPPING=NOT_AVAILABLE_IN_CURRENT_P2D_AUTHORITY`.
Fixtures are analytic, deterministic and clearly synthetic. No quarantined or
real empirical bytes are promoted. No RES-34--RES-50 CMJ meaning, RES-64
external-load meaning, RES-65 CMJ metric meaning, RES-62 longitudinal
authority, RES-63 canonical authority, or Serialization V3 hash is modified.

## Required machine-readable receipt

```text
IMTP_ONSET_STATUS=IMPLEMENT
IMTP_PEAK_FORCE_STATUS=IMPLEMENT
IMTP_FORCE_AT_TIME_STATUS=IMPLEMENT
IMTP_IMPULSE_STATUS=IMPLEMENT
IMTP_RFD_STATUS=IMPLEMENT
IMTP_NORMALIZATION_STATUS=IMPLEMENT
IMTP_TRIAL_SELECTION_STATUS=IMPLEMENT
VBT_MEAN_CONCENTRIC_VELOCITY_STATUS=IMPLEMENT
VBT_MEAN_PROPULSIVE_VELOCITY_STATUS=REPRESENT_BUT_DO_NOT_COMPUTE
VBT_PEAK_VELOCITY_STATUS=IMPLEMENT
VBT_REP_PHASE_AUTHORITY=QUALIFIED_UPSTREAM_EXPLICIT_PHASE_REQUIRED
VBT_FIXED_LOAD_COMPARISON_STATUS=IMPLEMENT
MEASURED_1RM_STATUS=IMPLEMENT
ESTIMATED_1RM_STATUS=IMPLEMENT_PROTOCOL_SPECIFIC_ONLY
LOAD_VELOCITY_MODEL_STATUS=IMPLEMENT_INDIVIDUAL_LINEAR_OLS
VELOCITY_LOSS_STATUS=IMPLEMENT_MECHANICAL_WITHIN_SET_ONLY
CANONICAL_STRENGTH_DATASET_MAPPING=NOT_AVAILABLE_IN_CURRENT_P2D_AUTHORITY
DEFERRED_WITH_REASON=VBT_MEAN_PROPULSIVE_VELOCITY requires unregistered acceleration/gravity/differentiation/filtering/sampling and propulsive-boundary semantics; scalar concentric velocity cannot be relabelled as MPV.
```

RES66_VERSION=1.0.0
