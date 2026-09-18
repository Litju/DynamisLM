# RES-69 DR-001: Longitudinal reliability, uncertainty, and within-athlete statistics

Status: `FROZEN / IMPLEMENTED V1`

Mission: `RES-69-IMPLEMENTATION-001`

## Scope and authority

RES-69 adds a deterministic statistical layer beneath the existing
RES-62 longitudinal authority. It does not replace or copy
`LongitudinalObservationEntry`, `MultiSourceAnalysisInput`,
`MultiSourceProcessingRun`, or `MultiSourceProvenanceGraph`. Because one
RES-62 input is intentionally scoped to one athlete, a multi-subject
reliability study is represented by an immutable tuple of existing RES-62
inputs, one per subject.

All accepted numerical estimates are computed by registered standard-library
Python operations. The language-model layer cannot supply formulas,
thresholds, units, scale flags, denominators, comparability verdicts, or
numerical results.

RES-60 population/source qualification, RES-61 football context, RES-62
record/input/lineage, RES-63 ingestion, and RES-64 through RES-68 family
authorities remain unchanged and are consumed as existing evidence.

## Level-of-analysis distinctions

The implementation keeps these quantities distinct:

* a numerical longitudinal change is not an interpretation of improvement,
  decline, fatigue, readiness, adaptation, or meaningfulness;
* descriptive within-athlete sample SD is not repeatability random-error SD;
* a replicate mean shift is not random error and is not labelled learning or
  fatigue;
* a method-comparison bias/SD summary is not interchangeability or agreement
  acceptability;
* a between-subject tuple of pairs is not a within-athlete longitudinal
  association or causal effect.

## Implemented V1 operations

The registered operations are:

1. absolute change, `follow-up - baseline`, for exactly two observations;
2. arithmetic relative and percent change from one ratio-change estimand;
3. natural log ratio for registered strictly-positive ratio-scale support;
4. explicit count-window and time-window mean, median, sample SD, minimum,
   maximum, and range;
5. current-minus-prior-reference-mean divided by prior reference sample SD;
6. centered timestamp OLS intercept and slope;
7. descriptive within-athlete sample SD;
8. two-replicate mean trial shift, SD of differences, and random-error SD;
9. two-replicate pooled raw relative error percent; and
10. simple B-minus-A method-comparison bias and SD of differences.

The scale-dependent operations in items 2, 3, and 9 (and the log-scale
reliability operation) remain registered deterministic paths, but the
current production scale registry has zero keys. They therefore refuse for
real production data until an owning scientific registry supplies an
authorized production entry.

Every numerical output is a `StatisticalEstimate` with its own typed unit.
The `StatisticalResult` contains the immutable support snapshot and an
immutable `StatisticalAnalysisRun` with RES-62 processing runs and provenance
graphs.

## Equations and minimum support

For two observations:

```text
change = follow-up - baseline
relative_change = (follow-up - baseline) / baseline
percent_change = 100 * relative_change
log_ratio = ln(follow-up / baseline)
```

Relative and percent outputs share the same registered arithmetic ratio-change
run and support. A displayed exponential transformation of a log ratio is
not treated as a second percent-change estimand.

For a window of `n` scalar observations:

```text
mean = sum(x) / n
sample_SD = sqrt(sum((x - mean)^2) / (n - 1))
range = maximum - minimum
```

Mean, median, minimum, maximum, and range require `n >= 1`; sample SD
requires `n >= 2`. For `n = 1`, range is explicitly represented as zero and
sample SD is explicitly represented as non-computable in the result envelope.
Window selection is never implicit: all omitted RES-62 entries have an
explicit exclusion reason and status.

For a current value and an explicitly prior reference window:

```text
z_reference = (current - reference_mean) / reference_sample_SD
```

The current observation is not part of the reference statistics. The reference
window has at least two observations and positive sample SD.

For exact timestamps, let `x_i` be elapsed seconds from the earliest included
timestamp:

```text
beta_1 = sum((x_i - xbar) * (y_i - ybar)) / sum((x_i - xbar)^2)
beta_0 = ybar - beta_1 * xbar
```

The intercept has the dependent metric unit. The slope has a deterministic
typed numerator-per-second unit. No observation-index time substitution,
p-value, confidence interval, causal trend, or adaptation-rate claim is
implemented.

For `N` complete, ordered two-replicate subject pairs:

```text
d_i = y_i2 - y_i1
mean_trial_shift = mean(d_i)
sd_difference = sample_SD(d_i)
random_error_sd = sd_difference / sqrt(2)
```

`TWO_REPLICATE_WITHIN_SUBJECT_RANDOM_ERROR_SD_V1` is the one canonical V1
estimator. The public typical-error name is an alias to this operation; it is
not a second numerical authority. `N >= 2` is required for random-error SD.

For the RAW_RELATIVE design only, the denominator is derived from the exact
same pair support:

```text
raw_reference_mean = sum_i(y_i1 + y_i2) / (2N)
raw_relative_error_percent = 100 * random_error_sd / raw_reference_mean
```

The denominator identity is
`TWO_REPLICATE_POOLED_RAW_GRAND_MEAN_V1`. It cannot be supplied by a caller,
and unbalanced support is refused. This is not a generic coefficient of
variation.

For a LOG_MULTIPLICATIVE design:

```text
log_d_i = ln(y_i2) - ln(y_i1)
mean_log_shift = mean(log_d_i)
sd_log_difference = sample_SD(log_d_i)
te_log = sd_log_difference / sqrt(2)
factor = exp(te_log)
lower_factor = exp(-te_log)
upper_factor = exp(te_log)
```

If percentage bounds are exposed, they are separately derived:

```text
lower_percent = 100 * (1 - exp(-te_log))
upper_percent = 100 * (exp(te_log) - 1)
```

The canonical factor interval is preserved. The implementation never emits a
naive symmetric `+/- x%` representation.

## Exact-unit rule

`UnitReference` remains identity-only. Direct scalar arithmetic requires exact
equality of the common `UnitReference`. Compatible physical dimensions do not
prove that a conversion was executed. Metres and centimetres, or m/s and
km/h, are refused unless a future registered conversion operation supplies the
conversion and provenance. Each derived estimate owns its own unit: source
units for changes/errors/BA, registered dimensionless and percent units for
ratios, a registered log-ratio representation for log ratios, and a typed
derived unit for OLS slope.

## Scale-semantic authority

`MeasurementScaleSemanticKeyV1` is derived from stable construct, test-family,
measurand, metric-definition, unit, normalization, registered operation,
estimator, optional protocol constraint, and optional explicitly registered
scale-relevant parameters. Observation ID, result ID, athlete, timestamp,
session, source artifact, acquisition instance, and processing-run instance
are excluded.

Lookup is `MeasurementIdentity -> semantic key -> exactly one registered
MeasurementScaleSemantics`. Caller flags such as `ratio_scale=True`,
`positive=True`, `meaningful_zero=True`, or `log_allowed=True` never confer
authority. Missing or conflicting registry entries fail closed.

The machine-readable scale audit is exposed as `SCALE_REGISTRY_AUDIT`,
`REGISTERED_SCALE_KEYS`, `UNREGISTERED_SCALE_KEYS`, and
`WHY_EACH_REGISTERED_KEY_IS_AUTHORIZED` in
`dynamislm.longitudinal.statistics.registry`. The V1 production registry
contains zero production entries. This is deliberate: the RES-34..68
family registries own the scientific metric identities, while no RES-69
scale decision was authorized to import those family-specific identities into
the generic package. The complete audit is therefore an explicit set of
unregistered public scalar-metric categories in `UNREGISTERED_SCALE_KEYS`,
and `WHY_EACH_REGISTERED_KEY_IS_AUTHORIZED` is empty. Synthetic tests may add
one exact `MeasurementScaleSemantics` entry only through the
`SYNTHETIC_TEST` origin and a new immutable registry value. The exact
RES-34..68 metric-ID enumeration is recorded in
`docs/decisions/RES69-SCALE-REGISTRY-AUDIT.md`. Public calculators resolve
only the canonical production registry; a caller-supplied synthetic registry
or synthetic entry can never authorize a `StatisticalResult`.

## Reliability-design authority

`ReliabilityAssumptionSourceEvidence` carries explicit stable-quantity,
systematic-trial-effect, and error-scale claims. The registered
`ReliabilityAssumptionAssessment` normalizer binds those claims to the exact
support ID/hash, source records, source artifacts/provenance, protocol,
evidence references, producing method, registry version, immutable source
evidence hash, and authority token. `ReliabilityDesignEvidence` accepts only
that assessment; free enum fields cannot mint design authority. Only the
validated design normalizer produces a `ReliabilityDesignAuthority` with
`AuthorityStatus.SOURCE_BOUND`; direct construction or an unverified
assessment is refused by public calculations.

The normalized authority binds the study/design identity, exact athletes,
ordered replicate references, RES-62 entry and observation IDs/hashes, source
record IDs/hashes, session/occasion/trial mapping, target identity and
measurand, method/device/rater references, protocol/evidence references,
repeatability question, stable-underlying-quantity assessment, systematic
trial-effect assessment, error-scale assessment, missingness policy,
balanced-design status, source artifacts, source provenance, producing method,
registry version, source-evidence hash, and authority hash.

## Method-comparison authority and BA boundary

`MethodComparisonDesignEvidence` is normalized only after its exact subject
pairings, stable `MethodComparisonMethodKeyV1` method keys, target
construct/measurand, metrics, units,
occasion policy, `B_MINUS_A` sign convention, no-hidden-transformation state,
one-pair-per-subject policy, source lineage, evidence, producing method, and
registry version match the actual support. Direct construction of
`MethodComparisonDesignAuthority` is unverified and cannot authorize BA.

The stable method key uses material semantic, processing, version, unit, and
acquisition dimensions while excluding observation-instance, result,
artifact, acquisition-instance, processing-run, athlete, session, and
timestamp identities. The producing method must equal the registered
`RES69_METHOD_COMPARISON_DESIGN_OPERATION`.

V1 emits only:

```text
difference_i = B_i - A_i
bias = mean(difference_i)
sd_difference = sample_SD(difference_i)
```

Methods/devices may differ when the source-bound method-comparison authority
proves the same target construct and measurand. Exact common units remain
mandatory. Classical lower/upper limits of agreement are registered as
`REPRESENT_BUT_DO_NOT_COMPUTE`; a request returns a structured refusal.
Coverage, acceptable agreement, interchangeability, substitute validity, and
equivalence are not numerically or semantically inferred.

## Represented, deferred, and rejected work

The operation registry represents but does not calculate:

* SEM from a registered ICC;
* MDC/SDC;
* ICC variants; and
* classical BA limits.

It defers log BA, repeated-measures BA, confidence intervals, covariance
propagation, repeated-measures correlation, and mixed-effects models. Generic
SEM, generic meaningful change, and readiness/fatigue/injury interpretation
are rejected. These dispositions are structured registry outcomes, not
placeholder arithmetic.

## Missingness and provenance

Only exact selected entries are included. Missing, invalid, or excluded
observations are not imputed, zero-filled, or silently dropped. Support stores
the full RES-62 input IDs/hashes, selected entries, explicit exclusions and
reasons/statuses, source records, time-window identity, comparability
evidence, and support hash.

Every result stores its support snapshot and a new analysis-run identity. The
run stores operation and estimator identities, exact calculation-changing
parameters, software version, registry version, RES-62 processing runs,
complete source provenance graphs, evidence references, scale identity where
applicable, design-authority hashes, and output hash. A changed method,
parameter set, support, registry version, or software version therefore
creates a new immutable run/result identity.

## Dependencies, limitations, and non-goals

No production dependency was added. All arithmetic uses Python standard
library `math`, `math.fsum`, and `statistics`; Serialization V3 remains
version `3`. Real empirical bytes and canonical rows remain outside Git.

V1 does not provide a cross-source claim-authority ladder, bridge registry,
LM-selected analysis validation, causal authority, readiness/fatigue
classification, injury prediction, model training, GPU code, or any RES-70+
work. Reliability and BA results are descriptive statistical outputs bounded
by their source/protocol authorities and do not establish practical meaning.

## Adversarial guarantees and implementation evidence

`tests/test_longitudinal_statistics.py` covers gold fixtures and negative
cases for temporal order, identity, exact units, unregistered scale semantics,
caller flags, zero/nonpositive domains, explicit windows, reference leakage,
duplicate timestamps, source-bound reliability and method-comparison
authorities, incomplete/unbalanced pairs, derived raw denominators,
log-factor asymmetry, synthetic scale-authority refusal, source-bound
assumption binding/tampering, stable method-key resolution across instance
IDs, BA LoA refusal, serialization round-trips, support and authority
tampering, and V3 hash stability.

The existing `tests/test_longitudinal.py` remains authoritative for RES-62 and
passes without semantic mutation.
