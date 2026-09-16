# RES67-DR-001 — Field-testing scientific engine

DECISION_ID=RES67-DR-001
STATUS=READY_FOR_FINAL_REVIEW
MISSION=RES-67-REVIEW-FIX-1
SERIALIZATION_VERSION=3

## Decision boundary

This is the additive P1 scientific slice for typed short sprint timing,
cumulative and interval splits, segment-average velocity, qualified maximum
sprint velocity, the standard 505 change-of-direction test, registered COD
deficit, repeated-sprint ability (RSA), and the canonical 30–15 intermittent
fitness test (IFT) VIFT result. It does not prescribe training, diagnose
fatigue, infer readiness, injury risk, VO2max, maximal aerobic speed, causal
effects, or perform model training, GPU work, or model inference.

The slice reuses the generic observation/result/provenance contracts and the
RES-66 source-qualified and deterministic multi-source patterns. It adds no
CMJ, strength, or RES-64 external-load semantics.

The controlling distinctions are:

```text
TIMING_GATE_TIME != RADAR_VELOCITY != GNSS_VELOCITY != OPTICAL_VELOCITY
CUMULATIVE_SPLIT_TIME != INTERVAL_SPLIT_TIME
SEGMENT_AVERAGE_VELOCITY != INSTANTANEOUS_VELOCITY != MAXIMUM_SPRINT_VELOCITY
SPLIT_TIMES != ACCELERATION_AUTHORITY
505_TOTAL_TIME != COD_DEFICIT
RSA_BEST != RSA_MEAN != RSA_TOTAL != RSA_PERCENT_DECREMENT
RSA_PERCENT_DECREMENT != PHYSIOLOGICAL_FATIGUE_STATE
VIFT != VO2MAX != MAXIMAL_AEROBIC_SPEED != MAXIMUM_SPRINT_SPEED
DEVICE_CORRELATION != DEVICE_AGREEMENT
```

## Evidence decision questions

1. Which short-sprint quantities can be computed from typed timing evidence?
2. Which velocity-domain estimator can receive narrow maximum-speed authority?
3. Which 505 layout and COD-deficit reference are registered for V1?
4. Which RSA protocol and summary/decrement equations are registered?
5. Which exact 30–15 IFT protocol and source-qualified stage evidence can mint
   VIFT?
6. Which comparisons require exact identity or a device/method bridge?

## Review-fix authority decisions

Field-test quality control is not computed by DynamisLM. Source ingestion may
construct a typed categorical observation from an imported/provider field, but
the scientific path accepts only that pre-existing observation:

```text
SOURCE_INGESTION
    → ScientificMeasurementObservation
    → normalize_field_test_qualification(source_observation, target_observation)
```

The normalizer receives no caller verdict, eligibility flag, completion flag,
miss count, termination reason or replacement provenance. It validates the
qualification measurand/metric, target observation ID, exact context, source
artifact/acquisition lineage, source/provider value origin and immutable
processing lineage. `QUALIFIED` and `REJECTED` remain upstream categorical
reports; neither can be minted by the DynamisLM normalization path.

IFT stage completion is a separate source/provider categorical observation
bound to the exact stage observation, canonical protocol, stage index and
target velocity. Optional checkpoint/miss information is preserved as source
metadata only. A bare `miss_count=3` never authorizes
`THREE_CONSECUTIVE_CONTROL_ZONE_FAILURES`. V1 termination authority is an
explicit source/provider termination observation; ordered-event derivation is
an authorized future representation, not invented by this slice. VIFT is the
velocity of the last source-qualified successfully completed canonical stage.

RSA V1 is the Impellizzeri soccer repeated-shuttle method: natural grass,
one preliminary 40 m shuttle criterion sprint, five minutes of recovery before
the RSA set, six 40 m repetitions as 20 m out plus 20 m return with one 180°
turn, and 20 s passive recovery. The start cue is an acoustic five-second
countdown. The timing trigger and reaction-time inclusion/exclusion semantics
remain `UNKNOWN`; no 30 cm start offset or photocell crossing semantics are
inferred. A typed, source-qualified criterion sprint is mandatory for every
RSA aggregation, and the first RSA repetition must satisfy:

```text
first_rsa_time <= criterion_time * 1.025
```

Failure returns an invalid/refused registered set and is never silently
aggregated. `RSA_PERCENT_DECREMENT_METRIC` uses the dedicated
`RSA_PERCENT_DECREMENT_MEASURAND` with unit `%` and the registered mechanical
equation:

```text
100 * (total_sprint_time / (best_sprint_time * number_of_sprints) - 1)
```

It is not a fatigue, readiness, recovery or physiological measurand.

## Targeted evidence inspected

The following sources were inspected for the decision-specific method and
measurement boundaries. Review summaries and correlation coefficients were
not promoted to individual-level agreement or universal device equivalence.

### Sprint and velocity

* Haugen & Buchheit (2016), *Sprint Running Performance Monitoring*, PMID
  [26660758](https://pubmed.ncbi.nlm.nih.gov/26660758/), DOI
  [10.1007/s40279-015-0446-0](https://doi.org/10.1007/s40279-015-0446-0).
  Starting procedures, trigger devices, environment and timing technology can
  materially change short-sprint times; dual-beam timing, laser and video are
  distinguished from manual/single-beam methods.
* Simperingham, Cronin & Ross (2016), *Advances in Sprint Acceleration
  Profiling*, PMID [26914267](https://pubmed.ncbi.nlm.nih.gov/26914267/), DOI
  [10.1007/s40279-016-0508-y](https://doi.org/10.1007/s40279-016-0508-y).
  Radar and laser acceleration outputs have method-specific limitations,
  particularly during the first few steps; arbitrary time windows and
  treadmill/overground outputs are not interchangeable.
* Altmann et al. (2019), *Validity and reliability of speed tests used in
  soccer*, PMID [31412057](https://pubmed.ncbi.nlm.nih.gov/31412057/), DOI
  [10.1371/journal.pone.0220982](https://doi.org/10.1371/journal.pone.0220982).
  Linear, COD and repeated-sprint tests are heterogeneous; total/average
  times and percent-decrement scores have different reliability behavior.
* Thron et al. (2024), *Assessing anaerobic speed reserve*, PMID
  [38252665](https://pubmed.ncbi.nlm.nih.gov/38252665/), DOI
  [10.1371/journal.pone.0296866](https://doi.org/10.1371/journal.pone.0296866).
  Satellite-derived sprint-profile quantities are compared with distinct
  criterion methods and do not establish universal equivalence.
* Koyama et al. (2021), *How far from the gold standard?*, PMID
  [33891640](https://pubmed.ncbi.nlm.nih.gov/33891640/).
  GPS/LPM bias depends on action; COD acceleration validity is materially
  poorer than some maximal-speed comparisons, so device identity and action
  support remain bound.

### 505 and COD deficit

* Nimphius et al. (2016), *Change of Direction Deficit*, PMID
  [26982972](https://pubmed.ncbi.nlm.nih.gov/26982972/), DOI
  [10.1519/JSC.0000000000001421](https://doi.org/10.1519/JSC.0000000000001421).
  The inspected methods used a standing start 30 cm behind the start line,
  three 505 trials for each left/right turn with randomized side order and
  three minutes between trials; the mean of the three 505 trials was used.
  The linear reference was the mean 0–10 m split from the 30 m sprint, and
  COD deficit was mean 505 time minus mean 10 m time. Preferred/nonpreferred
  labels were derived later and are not used as substitutes for LEFT/RIGHT.
* Barber et al. (2016), *Reliability of the 505 Change-of-Direction Test in
  Netball Players*, PMID [26309330](https://pubmed.ncbi.nlm.nih.gov/26309330/).
  Stationary-start and flying-start 505 variants showed different learning
  and reliability behavior; they remain distinct protocol identities.

### RSA

* Impellizzeri et al. (2008), *Validity of a repeated-sprint test for
  football*, PMID [18415931](https://pubmed.ncbi.nlm.nih.gov/18415931/), DOI
  [10.1055/s-2008-1038491](https://doi.org/10.1055/s-2008-1038491).
  The soccer RSSA protocol supports a preliminary 40 m shuttle criterion,
  five minutes before the RSA set, six 40 m (20 + 20 m, 180° turn) shuttle
  sprints with 20 s passive recovery, an acoustic five-second countdown, and
  a first-repetition criterion of no more than 2.5% slowing. Exact timing
  trigger and reaction-time semantics are not promoted when unresolved.
* Castagna et al. (2018), *Reliability Characteristics and Applicability of
  a Repeated Sprint Ability Test*, PMID
  [28759539](https://pubmed.ncbi.nlm.nih.gov/28759539/).
  A 5 × 30 m, 30 s active-recovery protocol is a different protocol and
  decrement variables showed large variability.
* Glaister et al. (2008), *The reliability and validity of fatigue measures
  during multiple-sprint work*, PMID
  [18714226](https://pubmed.ncbi.nlm.nih.gov/18714226/), DOI
  [10.1519/JSC.0b013e318181ab80](https://doi.org/10.1519/JSC.0b013e318181ab80).
  The inspected comparison covered multiple decrement equations and found
  protocol/reliability sensitivity; V1 registers one mechanical equation,
  not a generic fatigue index.

### 30–15 IFT

* Buchheit (2008), *The 30–15 intermittent fitness test*, PMID
  [18550949](https://pubmed.ncbi.nlm.nih.gov/18550949/), DOI
  [10.1519/JSC.0b013e3181635b2e](https://doi.org/10.1519/JSC.0b013e3181635b2e).
  The canonical method is a 40 m shuttle with 30 s running, 15 s recovery,
  an 8.0 km/h initial speed and 0.5 km/h stage increments.
* Buchheit-method protocol description inspected in an open methods report:
  3 m control zones, prerecorded audio pace, and termination after voluntary
  exhaustion or failure to reach the required zone on three consecutive
  occasions. These fields are protocol identity, not caller defaults.
* Grgic et al. (2020), *Test-retest reliability of the 30–15 IFT*, PMID
  [32422345](https://pubmed.ncbi.nlm.nih.gov/32422345/).
  Reliability of end-test velocity is distinct from criterion agreement.
* 2026 validity/agreement systematic review, PMID
  [41896967](https://pubmed.ncbi.nlm.nih.gov/41896967/).
  Correlations and group-level validity do not establish individual-level
  agreement with laboratory measures; VIFT is not relabelled VO2max, MAS or
  maximum sprint speed.

## Registered protocol identities

### Shared field-test identity

Every source observation carries a typed protocol identity and generic
`ScientificMeasurementObservation` containing context, measurement identity,
measurement result and immutable provenance. Material fields include the
test family, protocol/version, surface, environment, course layout, start
position and offset, initiation and reaction-time semantics, triggers, timing
device/provider/modality, gate topology/height, sampling/timebase, filtering,
smoothing/interpolation, software/firmware, trial/repetition selection,
side/turn-leg convention, distance definitions and exact support. Unprovided
material fields stay unresolved; no field is silently inferred.

### Short linear sprint V1

Timing authority is a source-reported time in seconds over an exact typed
distance/split. The source identity preserves start convention and timing
origin, trigger, device, topology, reaction-time semantics, acquisition and
processing. Self-initiated photocell crossing, audio/gun trigger, pressure-pad,
first-movement, first-force-change and manual stopwatch starts remain distinct.

### Maximum sprint velocity V1

Maximum sprint velocity requires a velocity-domain source series from an
explicitly identified radar, laser, GNSS/GPS, LPS, optical or other registered
system. The source preserves the device/provider, sampling/timebase,
filtering/smoothing, vendor processing, axis/frame, series digest, trial and
exact support. V1 registers only:

```text
SAMPLED_MAXIMUM = max(sampled velocity over the exact registered support)
```

No interpolation or dwell threshold is applied by default. A sustained-for-X-
milliseconds estimator is represented as a distinct future identity and has
no V1 numeric operation. Provider-processed velocity remains provider-derived
source evidence.

### Standard 505 V1

The one registered V1 layout is:

```text
15 m approach
5 m timed entry to the turn line
180° turn
5 m timed exit back through the same gate
```

Timing starts 5 m before the turn line and ends on return through that same
gate; only the timed 10 m is the 505 result. V1 preserves standing/flying
start convention, gate identity, turn side, plant/turn-leg convention and
source adjudication. Modified, stationary-start and flying-start variants are
not equal unless their own protocol identity is registered.

### RSA V1

RSA is protocol-specific. V1 registers the soccer repeated-shuttle protocol:
one preliminary 40 m shuttle criterion sprint, followed by five minutes of
recovery, then the RSA set of six 40 m repetitions (20 + 20 m, one 180° turn)
with 20 s passive recovery on natural grass. The start cue is an acoustic
five-second countdown; timing trigger and reaction-time semantics are unknown.
Linear tests, 5 × 30 m with 30 s active recovery, and any other distance,
repetition, recovery, surface, timing or layout remain distinct identities.

### 30–15 IFT V1

V1 registers the exact 40 m shuttle protocol with 30 s run, 15 s
protocol-defined walking/passive recovery, 8.0 km/h initial velocity, 0.5
km/h increments, 3 m control zone and registered prerecorded audio pace.
Termination is voluntary exhaustion or three consecutive control-zone misses.
The 28 m, ice-hockey, track/no-COD and shortened-start variants are separate
protocols.

## Disposition matrix

Every candidate quantity has exactly one RES-67 disposition.

| Quantity | V1 authority | Disposition |
| --- | --- | --- |
| Cumulative sprint split time | Exact typed cumulative split result in seconds | IMPLEMENT |
| Interval sprint split time | Difference of compatible same-trial cumulative splits only | IMPLEMENT |
| Segment-average velocity | Exact segment distance divided by exact interval time, in m/s | IMPLEMENT |
| Sprint acceleration | No split-derived `dv/dt`; no registered time-resolved method | REPRESENT_BUT_DO_NOT_COMPUTE |
| Maximum sprint velocity | Sampled maximum of an explicitly typed velocity series over exact support | IMPLEMENT |
| Sustained maximum sprint velocity | Requires a separate dwell/sustain estimator and evidence | DEFER_WITH_REASON |
| Standard 505 total time | Exact standard V1 timed 10 m result, side-specific and source-qualified | IMPLEMENT |
| COD deficit | Mean standard 505 time minus mean typed 0–10 m cumulative sprint reference | IMPLEMENT |
| 505 asymmetry | No single evidence-adopted numerator/denominator/sign convention | REPRESENT_BUT_DO_NOT_COMPUTE |
| RSA per-repetition time | Typed, qualified, ordered source repetition result | IMPLEMENT |
| RSA best time | Minimum of the complete registered repetition series | IMPLEMENT |
| RSA mean time | Total divided by the complete registered repetition count | IMPLEMENT |
| RSA total time | Sum of the complete registered repetition series | IMPLEMENT |
| RSA percent decrement | Registered `100 * (total / (best * n) - 1)` mechanical descriptor | IMPLEMENT |
| RSA alternate decrement equations | Distinct methods, not aliases of V1 S_dec | REJECT_FROM_RES67 |
| RSA decrement as fatigue/readiness | Not physiological or readiness authority | REJECT_FROM_RES67 |
| 30–15 IFT protocol | Exact canonical V1 protocol identity | IMPLEMENT |
| VIFT | Velocity of the last successfully completed source-qualified stage | IMPLEMENT |
| VIFT as VO2max | Correlation/agreement evidence does not authorize relabelling | REJECT_FROM_RES67 |
| VIFT as MAS | Intermittent end-test velocity is not MAS authority | REJECT_FROM_RES67 |
| VIFT as maximum sprint speed | Distinct intermittent fitness and velocity-domain constructs | REJECT_FROM_RES67 |
| Generic field-test asymmetry | No exact registered convention | REJECT_FROM_RES67 |
| Canonical field-test dataset mapping | No promoted P2D field-test mapping found | REJECT_FROM_RES67 |

## Exact computation and provenance rules

`INTERVAL_SPLIT_TIME` requires two cumulative split observations with the
same athlete/session/test/trial, protocol, clock/time origin, start trigger,
timing system, processing identity and reaction-time semantics. It computes
`t[a,b] = t[0,b] - t[0,a]` and refuses non-positive intervals and independently
clocked observations.

`SEGMENT_AVERAGE_VELOCITY` accepts only an exact typed segment matching the
interval split and computes `segment_distance / interval_elapsed_time`. It is
never relabelled as instantaneous, peak or maximum sprint velocity.

Acceleration is represented but not computed. Adjacent split-average
velocities do not establish a time-resolved acceleration series.

COD deficit requires a standard V1 505 aggregate and a registered mean
0–10 m cumulative sprint reference. It rejects arbitrary same-unit scalars,
wrong distance/protocol/selection, side rebinding and cross-athlete sources.
It is a derived performance quantity only.

RSA aggregation requires one typed, source-qualified preliminary criterion
sprint plus exactly one qualified repetition for every index `1..n`, with no
missing or duplicate middle repetition. The first repetition must be no more
than 2.5% slower than the criterion sprint. Best, mean, total and percent
decrement have distinct metric identities and processing operations. The V1
decrement uses its own percentage measurand and is a mechanical
performance-decrement descriptor; the public refusal path explicitly rejects
it as physiological fatigue.

VIFT accepts only source-qualified stage/test evidence. For canonical stage
index `k`:

```text
stage_velocity(k) = 8.0 + 0.5 * (k - 1)  # km/h, 1-indexed
VIFT = velocity of the last successfully completed stage
```

Caller-provided stage counts, completion enums, termination enums or VIFT
scalars cannot mint a result. Stage completion and termination are pre-existing
source/provider observations bound to the source observation, exact protocol,
context and immutable provenance. Miss counts are preserved only when the
source supplies them and are never interpreted as consecutive failures by
count alone.

All multi-source results use the RES-66 deterministic trial-free analysis
context and an exact union of source provenance with explicit lineage edges.
No first-source context inheritance is permitted. Changed source series,
sampling, filtering, support, processing, artifact digest, protocol, device,
or source qualification fails closed.

## Comparability authority

Comparisons are claim-relative and use the generic states
`COMPARABLE`, `COMPARABLE_WITH_CONDITIONS`, `REQUIRES_TRANSFORMATION`,
`BRIDGE_VALIDATION_REQUIRED`, `NOT_COMPARABLE` and
`INSUFFICIENT_INFORMATION`. Sprint time comparisons require compatible
distance, split type, start position/trigger, reaction-time semantics, timing
technology/topology, processing and material surface/environment. Maximum
velocity comparisons additionally require estimator, device/method, sampling,
filtering and support equality. 505 comparisons require layout, timed section,
start convention, side semantics and device equality. RSA comparisons require
exact protocol, distance, repetitions, recovery, timing and metric identity.
30–15 comparisons require exact protocol/version. Cross-device comparisons
return `BRIDGE_VALIDATION_REQUIRED` unless a registered bridge exists; no
correlation is promoted to agreement.

## Dataset and historical authority

```text
CANONICAL_FIELD_TEST_DATASET_MAPPING=NOT_AVAILABLE_IN_CURRENT_P2D_AUTHORITY
```

Only deterministic, clearly synthetic fixtures are added. Serialization V3
is unchanged. RES-61 football-world, RES-62 longitudinal/multi-source,
RES-63 canonical-data, RES-64 external-load, RES-65 CMJ, and RES-66 strength
meaning remain unchanged.

## Implementation and tests

The realizing implementation is additive under
`src/dynamislm/measurement/field_testing/`, with public registry, identity,
sprint, COD, RSA, IFT and comparability modules. Tests cover construction,
immutability, Serialization V3 round trips, exact numerical gold fixtures,
source/provenance binding, multi-source context lineage, protocol/device
comparability and the adversarial relabelling/rebinding attacks listed in the
RES-67 mission, including caller-minted adjudication, RSA criterion validity,
IFT termination authority and percentage-measurand tampering.

The decision receipt is maintained at
`docs/decisions/RES67-RECEIPT.json`.

## Machine-readable status

SPRINT_CUMULATIVE_SPLIT_STATUS=IMPLEMENT
SPRINT_INTERVAL_SPLIT_STATUS=IMPLEMENT
SPRINT_SEGMENT_AVERAGE_VELOCITY_STATUS=IMPLEMENT
SPRINT_ACCELERATION_STATUS=REPRESENT_BUT_DO_NOT_COMPUTE
MAXIMUM_SPRINT_VELOCITY_STATUS=IMPLEMENT
MAX_SPEED_ESTIMATOR=SAMPLED_MAXIMUM
CROSS_DEVICE_MAX_SPEED_EQUIVALENCE=BLOCKED
STANDARD_505_STATUS=IMPLEMENT_STANDARD_V1_SOURCE_QUALIFIED
505_COD_DEFICIT_STATUS=IMPLEMENT_REGISTERED_MEAN_505_MINUS_MEAN_10M
505_ASYMMETRY_STATUS=REPRESENT_BUT_DO_NOT_COMPUTE
RSA_BEST_TIME_STATUS=IMPLEMENT
RSA_MEAN_TIME_STATUS=IMPLEMENT
RSA_TOTAL_TIME_STATUS=IMPLEMENT
RSA_PERCENT_DECREMENT_STATUS=IMPLEMENT_REGISTERED_MECHANICAL_S_DEC
RSA_FATIGUE_INTERPRETATION=BLOCKED
IFT30_15_PROTOCOL_STATUS=IMPLEMENT_CANONICAL_40M_V1
VIFT_STATUS=IMPLEMENT_SOURCE_QUALIFIED_LAST_COMPLETED_STAGE
VIFT_AS_VO2MAX=BLOCKED
VIFT_AS_MAS=BLOCKED
VIFT_AS_MSS=BLOCKED
CANONICAL_FIELD_TEST_DATASET_MAPPING=NOT_AVAILABLE_IN_CURRENT_P2D_AUTHORITY
TIMING_GATE_SEGMENT_AVERAGE_AS_MAX_SPEED=BLOCKED
SPRINT_ACCELERATION_AUTHORITY=REPRESENT_BUT_DO_NOT_COMPUTE
FIELD_TEST_QC_COMPUTED_BY_DYNAMISLM=NO
FIELD_TEST_SOURCE_QUALIFICATION=PRE_EXISTING_TYPED_SOURCE_OBSERVATION_NORMALIZED_WITHOUT_VERDICT
UPSTREAM_ADJUDICATION_AUTHORITY=PASS
IFT_STAGE_COMPLETION_AUTHORITY=SOURCE_QUALIFIED
IFT_TERMINATION_AUTHORITY=SOURCE_QUALIFIED_OR_ORDERED_EVENT_DERIVATION
BARE_MISS_COUNT_AS_CONSECUTIVE_FAILURES=BLOCKED
RSA_PROTOCOL_EVIDENCE_MATCH=PASS
RSA_START_CUE=ACOUSTIC_5_SECOND_COUNTDOWN
RSA_TIMING_TRIGGER=UNKNOWN
RSA_REACTION_TIME_SEMANTICS=UNKNOWN
RSA_CRITERION_SPRINT_REQUIRED=YES
RSA_FIRST_REP_VALIDITY_THRESHOLD=2.5_PERCENT
RSA_CRITERION_SPRINT_BOUND=PASS
RSA_2_5_PERCENT_VALIDITY_RULE_BOUND=PASS
RSA_PERCENT_DECREMENT_MEASURAND=dynamislm:measurand:rsa-percent-decrement@1.0.0
RSA_PERCENT_DECREMENT_AS_FATIGUE=BLOCKED
RSA_DECREMENT_AS_FATIGUE=BLOCKED
