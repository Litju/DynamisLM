# RES68-DR-001 — Remaining explosive-test family closure

DECISION_ID=RES68-DR-001
STATUS=DESIGN_FIX_PASS
MISSION=RES-68-DESIGN-FIX-AND-IMPLEMENTATION-001
PHASE_A_DESIGN_FIX=PASS
PHASE_B_IMPLEMENTATION=GATED_AFTER_THIS_RECORD
SERIALIZATION_VERSION=3
IMPLEMENTATION_STARTED=NO_AT_FREEZE

## Exact mission boundary

This decision freezes the additive P1 scientific authority for three separate
families:

1. Drop Jump (DJ): ground-contact time, rebound flight time, flight-time
   jump-height estimate, JH/CT reactive strength index, and flight-time/contact
   time ratio.
2. Bench Press Throw (BPT): sampled maximum bar velocity and a DynamisLM
   time-weighted mean bar velocity over exact registered support; provider MV,
   Vmax and MPV representation boundaries; and power deferral.
3. Medicine-Ball Throw (MBT): exact protocol-scoped throw distance and
   instrumented release velocity from qualified trajectory evidence.

This decision does not create a shared `ExplosiveTestProtocol`,
`ExplosiveTestEvent`, `ExplosiveTestSeries`, or `ExplosivenessScore`. The three
families reuse generic kernel contracts only. DJ is not a CMJ subtype, BPT is
not a `VBTMeasurementIdentity`, and MBT is neither external-load nor field-test
aliasing.

No readiness, fatigue, injury, training-prescription, normative-score, causal,
model-training, GPU, or generic “explosiveness” authority is created.

## A. Corrected evidence matrix

| Evidence | Actual protocol/population/method inspected | Direct or supporting attribution | Frozen consequence | Limit |
| --- | --- | --- | --- | --- |
| McMahon, Lake, Stratford & Comfort (2021), *A Proposed Method for Evaluating Drop Jump Performance with One Force Platform*, DOI [10.3390/biomechanics1020015](https://doi.org/10.3390/biomechanics1020015) | 26 young male sports students; 0.30 m and 0.40 m boxes; adjacent force platforms; touchdown, takeoff, actual drop height and flight-time DJ variables | DIRECT DROP-JUMP EVIDENCE | Box height and realized drop height differ; force-platform DJ event/metric protocol can be registered; contact time, flight time and flight-time JH/CT are valid candidate outputs when their own event evidence is present | Does not establish a universal device, threshold, posture, or population bridge |
| Baca (1999), *A comparison of methods for analyzing drop jump performance*, PMID [10188749](https://pubmed.ncbi.nlm.nih.gov/10188749/) | Drop-jump method comparison including flight-time height and drop-height assumptions | DIRECT DROP-JUMP EVIDENCE | Flight-time height is a method-defined takeoff-to-landing estimator, not a universal jump-height identity | Method/device details are not generalized beyond the inspected protocol |
| Healy, Kenny & Harrison (2018), *Reactive Strength Index: A Poor Indicator of Reactive Strength?*, PMID [29182434](https://pubmed.ncbi.nlm.nih.gov/29182434/), DOI [10.1123/ijspp.2017-0511](https://doi.org/10.1123/ijspp.2017-0511) | 28 national/international sprinters; 0.30 m DJ; force-platform CT, flight time, JH, RSI=JH/CT and RSR=flight-time/CT | DIRECT DROP-JUMP EVIDENCE | RSI JH/CT and RSR FT/CT are distinct registered quantities despite high correlation; strategy and threshold/identity context matter | Reliability/correlation does not establish equivalence, universal thresholds, or interchangeability |
| Smith, Lamont & Barefoot (2024), *Comparison of Different Take-off Thresholds When Assessing Vertical Jump Performance*, DOI [10.70252/QBUA4521](https://doi.org/10.70252/QBUA4521) | 21 participants performing vertical jumps; 20 N, 10 N, 5 N, 1 N, 5SD and peak-residual-force takeoff thresholds | SUPPORTING GENERAL VERTICAL-JUMP/EVENT-DETECTION EVIDENCE | Threshold choice and signal noise belong in event-method identity; this is not direct DJ protocol evidence | Not a drop-jump-specific study; it cannot be cited as direct DJ validation |
| Xu et al. (2023), *A Systematic Review of the Different Calculation Methods for Measuring Jump Height During the Countermovement and Drop Jump Tests*, PMID [36940054](https://pubmed.ncbi.nlm.nih.gov/36940054/), DOI [10.1007/s40279-023-01828-x](https://doi.org/10.1007/s40279-023-01828-x) | Systematic review of CMJ/DJ height methods and equipment | SUPPORTING GENERAL JUMP-METHOD EVIDENCE | Flight time, impulse-momentum and double-integration methods have different estimands/assumptions; methods must not be collapsed | Review-level method comparison is not a DJ device-validation bridge |
| Eythorsdottir et al. (2024), *The Battle of the Equations: A Systematic Review of Jump Height Calculations Using Force Platforms*, DOI [10.1007/s40279-024-02098-x](https://doi.org/10.1007/s40279-024-02098-x) | Force-platform equations across CMJ, SJ, DJ and loaded jumps | SUPPORTING GENERAL JUMP-METHOD EVIDENCE | The same jump can yield materially different values under FT, ToV, ToV+D and DIS; jump type, purpose and definition govern method choice | It does not authorize cross-method equality |
| Eythorsdottir et al. (2026), *Navigating the Data Processing Maze: A Systematic Review of Jump Height Calculations Using Force Platforms*, PMID [41672931](https://pubmed.ncbi.nlm.nih.gov/41672931/), DOI [10.1002/ejsc.70114](https://doi.org/10.1002/ejsc.70114) | Current review of sampling, filtering, body-weight period, integration, event thresholds and gravity choices for force-platform jump height | SUPPORTING GENERAL JUMP-METHOD EVIDENCE | Processing, gravity and event identity are material serialized dimensions; no hidden defaults | Review does not turn any one processing choice into universal DJ authority |
| García-Ramos et al. (2018), *Assessment of Upper-Body Ballistic Performance Through the Bench Press Throw Exercise: Which Velocity Outcome Provides the Highest Reliability?*, PMID [29847530](https://pubmed.ncbi.nlm.nih.gov/29847530/), DOI [10.1519/JSC.0000000000002616](https://doi.org/10.1519/JSC.0000000000002616) | 21 men; concentric-only and eccentric-concentric BPT; five loads; T-Force velocity output; MV, MPV and Vmax | DIRECT BPT EVIDENCE | MV, MPV and Vmax have separate support definitions. Traditional MV runs from first positive bar velocity to maximum height/zero velocity and can include post-release upward travel; MPV uses the gravity-relative propulsive cutoff; Vmax is the maximum instantaneous velocity over the registered support | Reliability findings do not establish equivalence among metrics or providers |
| Vingren, Buddhadev & Hill (2011), *Smith Machine Counterbalance System Affects Measures of Maximal Bench Press Throw Performance*, PMID [21701283](https://pubmed.ncbi.nlm.nih.gov/21701283/), DOI [10.1519/JSC.0b013e31821eb67f](https://doi.org/10.1519/JSC.0b013e31821eb67f) | 24 adults; Smith-machine BPT with/without counterbalance; accelerometer-derived peak force, velocity and power | DIRECT BPT MECHANICAL-SYSTEM EVIDENCE | Counterbalance status is material BPT identity; counterbalanced and non-counterbalanced measures are not silently interchangeable | Does not authorize a generic power equation |
| Kobayashi et al. (2013), *Calculation of Force and Power during Bench Throws Using a Smith Machine: The Importance of Considering the Effect of Counterweights*, PMID [23459856](https://pubmed.ncbi.nlm.nih.gov/23459856/), DOI [10.1055/s-0032-1329955](https://doi.org/10.1055/s-0032-1329955) | 9 female collegiate judo athletes; counterweighted Smith-machine bench throws; LPT displacement; competing force/power equations | DIRECT COUNTERWEIGHTED-SMITH MECHANICS EVIDENCE | Future counterweighted-Smith power must bind the complete moving system and dynamic equation; `load × velocity` is rejected | Method-specific force/power equation is deferred from RES-68 V1 |
| Harris et al. (2011), *The Seated Medicine Ball Throw as a Test of Upper Body Power in Older Adults*, PMID [21572350](https://pubmed.ncbi.nlm.nih.gov/21572350/), DOI [10.1519/JSC.0b013e3181ecd27b](https://doi.org/10.1519/JSC.0b013e3181ecd27b) | Seated medicine-ball throw; 1.5 kg and 3.0 kg balls; distance outcome; older adults | DIRECT MBT PROTOCOL/DISTANCE EVIDENCE | Ball mass, seated posture, support and distance protocol are identity fields; distance remains a distance outcome | Population is older adults, not the fixed DynamisLM target population; no release-velocity authority |
| Mayhew et al. (2005), *Comparison of the Backward Overhead Medicine Ball Throw to Power Production in College Football Players*, PMID [16095399](https://pubmed.ncbi.nlm.nih.gov/16095399/), DOI [10.1519/15644.1](https://doi.org/10.1519/15644.1) | Standing backward overhead MBT in 40 NCAA Division II football players; distance and force-platform power association | DIRECT MBT PROTOCOL EVIDENCE; correlation only for relationship claim | Backward overhead and seated chest protocols remain different; correlation with power does not authorize distance-as-power | Does not establish a mechanical power equation or cross-protocol bridge |
| Thomas et al. (2006), *Influence of familiarization on a backward, overhead medicine ball explosive power test*, PMID [16440508](https://pubmed.ncbi.nlm.nih.gov/16440508/) | 28 adolescent male rugby players; six repeated backward-overhead throws; distance/familiarization | DIRECT MBT PROTOCOL/TRIAL-SELECTION EVIDENCE | Trial familiarization/selection is material identity; no universal best-trial rule is inferred | Population and protocol are not generalized to all MBT variants |

The first-pass vertical-jump threshold-sensitivity source is therefore retained
only as supporting general event-detection evidence. It is not direct evidence
for the DJ protocol. Direct DJ claims use direct DJ studies where available.

## B. Corrected DJ disposition matrix

| Quantity/claim | V1 disposition | Exact boundary |
| --- | --- | --- |
| DJ ground-contact time | IMPLEMENT | `rebound_takeoff_time - touchdown_time`, seconds |
| DJ rebound flight time | IMPLEMENT | `subsequent_landing_time - rebound_takeoff_time`, seconds |
| DJ flight-time jump height | IMPLEMENT | DJ-specific estimator `g * flight_time_s**2 / 8`, metres; takeoff-to-apex ballistic rise estimate |
| DJ RSI JH/CT | IMPLEMENT | `qualified_DJ_jump_height_m / qualified_DJ_contact_time_s`, m/s |
| DJ RSR FT/CT | IMPLEMENT | `qualified_DJ_flight_time_s / qualified_DJ_contact_time_s`, dimensionless 1 |
| DJ RSI JH/CT as RSR FT/CT | BLOCKED | Different measurands, units, metric IDs and operations; no alias or inference |
| Nominal box height as actual drop height | BLOCKED | No substitution; actual height is independently measured or UNKNOWN |
| Missing actual drop height blocks event/contact/flight/FT-height/ratios | BLOCKED | Claim-relative missingness; unrelated valid outputs remain describable |
| Actual-drop-height equality/normalization/mechanical exposure claim with missing actual height | BLOCKED | `INSUFFICIENT_INFORMATION` or claim-relative refusal |
| DJ as CMJ or CMJ RSI-mod | BLOCKED | Different family and scientific identity |
| Cross-device DJ equality | BLOCKED without bridge | Force plate, IMU, contact mat and optical methods require exact identity or registered bridge |

## C. Corrected BPT disposition matrix

| Quantity/claim | V1 disposition | Exact boundary |
| --- | --- | --- |
| BPT sampled maximum bar velocity | IMPLEMENT | Sampled maximum over exact registered support; no interpolation |
| DynamisLM time-weighted mean bar velocity | IMPLEMENT | Trapezoidal integral over actual sample timestamps divided by exact support duration |
| Traditional/provider MV | REPRESENT_BUT_DO_NOT_RELABEL | Provider/source origin and exact provider method remain intact |
| BPT mean propulsive velocity | REPRESENT_BUT_DO_NOT_COMPUTE | Provider MPV may be represented under its source definition; no DynamisLM MPV arithmetic in V1 |
| BPT Vmax provider value | REPRESENT_BUT_DO_NOT_RELABEL | Provider value remains SOURCE_REPORTED or PROVIDER_DERIVED |
| BPT mean power | REPRESENT_BUT_DO_NOT_COMPUTE | No generic V1 operation |
| BPT peak power | REPRESENT_BUT_DO_NOT_COMPUTE | No generic V1 operation |
| Generic BPT power | NOT_REGISTERED | No `external_load * bar_velocity` operation |
| Counterweighted-Smith specific power | FUTURE CANDIDATE | Requires exact moving-system mechanics and dynamic force equation |
| Generic post-release rejection | BLOCKED | Support inclusion is metric/method-specific; traditional MV may include post-release travel |
| Provider MV as DynamisLM-derived MV | BLOCKED | Different origin, operation, support and lineage |
| BPT as ordinary bench press or RES-66 VBT | BLOCKED | Distinct family/protocol identity |

## D. Confirmed MBT disposition matrix

| Quantity/claim | V1 disposition | Exact boundary |
| --- | --- | --- |
| MBT throw distance | IMPLEMENT | Exact origin-to-endpoint convention, first-contact/no-roll semantics and protocol variant |
| MBT instrumented release velocity | IMPLEMENT | Qualified trajectory/velocity evidence and explicit release event only |
| Release velocity inferred from distance | BLOCKED | No projectile inversion, assumed angle, or assumed release height |
| MBT distance as power | REJECT_FROM_RES68 | Distance is not a mechanical power result |
| Generic upper-body power from distance | REJECT_FROM_RES68 | No generic conversion or latent-score relabel |
| Protocol-independent normative score | REJECT_FROM_RES68 | No normative authority |
| Cross-protocol equivalence | REJECT_FROM_RES68 | Seated chest, standing chest, backward overhead, rotational, supine and push-press variants remain distinct |

## E. Exact measurands

### DJ

```text
DJ_GROUND_CONTACT_TIME_MEASURAND
    rebound contact interval, s
DJ_REBOUND_FLIGHT_TIME_MEASURAND
    rebound flight interval, s
DJ_FLIGHT_TIME_JUMP_HEIGHT_MEASURAND
    vertical ballistic takeoff-to-apex rise estimated from rebound flight time, m
DJ_RSI_JH_CT_MEASURAND
    DJ flight-time jump-height divided by rebound ground-contact time, m/s
DJ_RSR_FT_CT_MEASURAND
    DJ rebound flight time divided by rebound ground-contact time, 1
```

### BPT

```text
BPT_BAR_VELOCITY_MEASURAND
    bar velocity under an exact BPT protocol, device/frame and support definition, m/s
BPT_SAMPLED_MAXIMUM_BAR_VELOCITY_MEASURAND
    maximum sampled BPT bar velocity over registered support, m/s
BPT_DYNAMISLM_TIME_WEIGHTED_MEAN_BAR_VELOCITY_MEASURAND
    time-weighted mean BPT bar velocity over registered support, m/s
BPT_MEAN_PROPULSIVE_VELOCITY_MEASURAND
    provider-defined propulsive-support mean velocity, m/s; representation only in V1
BPT_MEAN_POWER_MEASURAND / BPT_PEAK_POWER_MEASURAND
    provider-defined power outputs; representation only in V1
```

### MBT

```text
MBT_THROW_DISTANCE_MEASURAND
    protocol-defined throw distance from registered origin to endpoint, m
MBT_INSTRUMENTED_RELEASE_VELOCITY_MEASURAND
    velocity at the explicit instrumented release event in the registered frame, m/s
```

## F. Exact metrics

Metric identifiers are family- and method-scoped. In particular,
`DJ_RSI_JH_CT_METRIC` and `DJ_RSR_FT_CT_METRIC` are never aliases, and
`BPT_PROVIDER_MEAN_VELOCITY_METRIC` is not
`BPT_DYNAMISLM_TIME_WEIGHTED_MEAN_BAR_VELOCITY_METRIC`.

## G. Exact registered operations

```text
DJ_GROUND_CONTACT_TIME_OPERATION@1.0.0
DJ_REBOUND_FLIGHT_TIME_OPERATION@1.0.0
DJ_FLIGHT_TIME_JUMP_HEIGHT_OPERATION@1.0.0
DJ_RSI_JH_CT_OPERATION@1.0.0
DJ_RSR_FT_CT_OPERATION@1.0.0

BPT_SOURCE_VELOCITY_SERIES_OPERATION@1.0.0
BPT_SAMPLED_MAXIMUM_BAR_VELOCITY_OPERATION@1.0.0
BPT_DYNAMISLM_TIME_WEIGHTED_MEAN_BAR_VELOCITY_OPERATION@1.0.0
BPT_PROVIDER_METRIC_SOURCE_OPERATION@1.0.0

MBT_SOURCE_DISTANCE_OPERATION@1.0.0
MBT_DISTANCE_FROM_REGISTERED_COORDINATES_OPERATION@1.0.0
MBT_INSTRUMENTED_RELEASE_VELOCITY_OPERATION@1.0.0
```

No V1 operation is registered for MPV arithmetic, generic BPT power, load ×
velocity power, MBT distance-as-power, normative scores, or cross-protocol
equivalence.

## H. Equations and units

DJ event ordering is strict:

```text
touchdown_time < rebound_takeoff_time < subsequent_landing_time
```

```text
contact_time_s = rebound_takeoff_time_s - touchdown_time_s
flight_time_s = subsequent_landing_time_s - rebound_takeoff_time_s
jump_height_m = gravity_m_per_s2 * flight_time_s**2 / 8
RSI_JH_CT_m_per_s = jump_height_m / contact_time_s
RSR_FT_CT_1 = flight_time_s / contact_time_s
```

The DJ flight-time estimator accepts the existing typed
`GravityReference` semantics. `STANDARD_GRAVITY` remains the exact registered
conventional reference `9.80665 m/s^2`; a supplied applicable local reference
remains distinct. No literal `9.81` default is introduced. Gravity identity,
source, unit, uncertainty metadata and method version are serialized.

The DJ flight-time estimate is a takeoff-to-apex ballistic-rise estimate
conditional on the registered flight-time assumptions, including the
takeoff/landing posture applicability assumption. It is not impulse-momentum,
double-integration, standing-reference displacement, or CMJ height.

BPT time-weighted mean for exact inclusive support indices `a..b` is:

```text
mean_velocity_m_per_s =
    Σ[i=a+1..b] 0.5 * (v[i-1] + v[i]) * (t[i] - t[i-1])
    ------------------------------------------------------
                         t[b] - t[a]
```

It uses sample-attached actual timestamps, finite samples, exact support,
positive duration, explicit velocity unit/frame/sign convention, and the exact
source-series digest. An arithmetic sample mean is not equivalent.

MBT coordinate distance, when a registered coordinate evidence object exists,
is:

```text
throw_distance_m = endpoint_coordinate_m - origin_coordinate_m
```

No origin, endpoint, release angle, release height, roll correction, or
projectile inversion is inferred.

## I. Protocol identity fields

### DJ protocol identity

Nominal box/drop height; actual drop height; actual-height method/source;
initiation mode; pre-drop posture/stillness; step-off leg; arms condition;
rebound strategy; explicit cue; support/platform configuration;
landing/rebound technique; pause/continuity semantics; protocol reference and
version; and explicit unknowns. Actual height is only populated when an
independent registered measurement method/source establishes it.

### BPT protocol identity

Machine type; fixed-vertical Smith/other Smith/free-weight/other identity;
counterbalance status and identity; effective/static resistance semantics;
moving-system load semantics; bar mass; added load; physical versus %1RM load
identity; concentric-only versus eccentric-concentric; pause/touch/bounce;
grip; ROM; feet/body support; release/catch semantics; provider/device/
modality; sampling/timebase; filtering/smoothing/resampling; software/
firmware; source-series digest; metric support definition; rep/trial
qualification and selection; and explicit unknowns.

### MBT protocol identity

Exact throw type; body posture; support/restraint condition; ball mass;
countermovement and lower-body contribution permissions; throw/arm technique;
starting position; release semantics; measurement method; distance origin and
endpoint conventions; first-contact/no-roll convention; device/provider/
modality for instrumented tests; trial qualification; trial selection; and
explicit unknowns.

## J. Event/support identity

DJ has family-specific occurrences for `TOUCHDOWN`, `REBOUND_TAKEOFF` and
`SUBSEQUENT_LANDING`. Each occurrence preserves sample index, exact event time,
detector method and parameters, source-series digest, source observation,
artifact, acquisition, measurement identity, timebase and provenance. No
interpolation, backshift, sorting or repair is implicit.

BPT support is a typed, exact, inclusive support bound to one metric operation,
source series digest, start/end indices and times, velocity unit/frame/sign,
and method semantics. A support may explicitly include post-release samples
when its metric definition does. There is no generic post-release invalidation.

### Authority boundary correction

```text
TYPED_OBJECT != SCIENTIFIC_ADJUDICATION_AUTHORITY
```

The family builders do not treat a caller-constructed dataclass, index pair,
boolean, status, or matching digest as scientific adjudication. Source/provider
normalization is the authority boundary and must preserve the upstream
processing run, exact source bindings, source/provider origin, and the
registered method parameters before a downstream result is minted.

For DJ, `DropJumpEventSourceEvidence` binds the event label, exact sample and
time, source series/artifact/acquisition, detector parameters, event status and
QC codes to the upstream event-processing provenance. The normalized
`DropJumpEventOccurrence` preserves that upstream provenance; DynamisLM does
not claim to have run the detector.

For BPT, `BPTMetricSupportSourceEvidence` binds the exact source series,
metric, inclusive support indices/timestamps, support definition, boundary
method/convention, post-release policy, protocol context, source/provider
origin and upstream processing provenance. Only its normalized
`BenchPressThrowMetricSupport` may feed Vmax or DynamisLM time-weighted MV.

For MBT, `MBTCoordinateSourceEvidence` binds origin/endpoint coordinates,
coordinate frame, origin/endpoint and first-contact/no-roll conventions,
source artifact/acquisition, protocol context, provider/origin and producing
provenance before coordinate distance is derived. `MBTReleaseEventSourceEvidence`
binds the release sample/time, trajectory digest, frame, release method,
protocol context, source artifact/acquisition, provider/origin and producing
provenance before release velocity is selected. Source-reported distance
remains source-reported and does not require redundant coordinate derivation.

## K. Source qualification requirements

Source/provider qualification is an upstream categorical observation, not a
caller-minted boolean. The normalized typed evidence must bind exact athlete,
session, test instance, trial/rep, source artifact, acquisition, provider,
context, method, processing lineage, source value origin, and qualification
measurand/metric identity. DynamisLM computation accepts only normalized
qualified evidence for qualified-trial claims. A caller cannot pass
`qualified=True`, `status="QUALIFIED"`, `best=True`, `eligible=True`, or an
equivalent free flag to mint authority.

## L. Provenance requirements

Every derived output preserves athlete/session/test/trial context; protocol;
device/provider/modality; acquisition; raw/source artifact; source-series
digest; timebase/sampling; processing/filtering; estimator/equation;
operation/version; parameters; software/registry/hardware/firmware where
known; source qualification; exact DJ events or BPT support; MBT release event
or coordinate conventions; evidence references; and explicit lineage edges.

Reprocessing is append-only:

```text
source R + method v1 -> D1
source R + method v2 -> D2
D2 does not overwrite D1
```

## M. Claim-relative comparability matrix

| Comparison | Result without registered bridge |
| --- | --- |
| Same family, same complete protocol/method/device/support identity | `COMPARABLE` |
| Same family, explicit registered conditional bridge | `COMPARABLE_WITH_CONDITIONS` |
| Unit-only change with explicitly requested registered transformation | `REQUIRES_TRANSFORMATION` |
| Different device/provider/software/filter/support where agreement is unregistered | `BRIDGE_VALIDATION_REQUIRED` |
| Different measurand, metric family, protocol variant, DJ-vs-CMJ or BPT-vs-ordinary bench press | `NOT_COMPARABLE` |
| Missing actual height for an actual-drop claim or missing material metadata | `INSUFFICIENT_INFORMATION` |
| DJ JH/CT versus DJ FT/CT | `NOT_COMPARABLE` |
| Provider BPT MV versus DynamisLM time-weighted MV | `BRIDGE_VALIDATION_REQUIRED` |
| Seated versus standing/overhead/rotational/supine/push-press MBT | `NOT_COMPARABLE` |

Comparability is claim-relative. Missing actual drop height does not poison
valid contact, flight, flight-time height, RSI or RSR outputs whose own
requirements are met; it blocks only actual-drop-dependent claims.

## N. Structured-refusal matrix

| Refusal condition | Blocked claim | Safe description retained |
| --- | --- | --- |
| DJ event absent/malformed/wrong family/source/protocol | Requested DJ derived metric | Independently valid typed event or earlier duration |
| DJ caller-selected index/status without upstream event evidence | DJ event authority | Source observation and any independently preserved upstream event data |
| DJ event order or duration non-positive/non-finite | Contact/flight/derived ratio as applicable | Event identities and recorded times |
| DJ invalid/missing gravity or unresolved flight assumptions | DJ flight-time height | Contact and flight time where independently valid |
| DJ JH/CT requested without valid jump height or denominator | RSI JH/CT | Contact time and any valid JH/flight output |
| DJ RSR requested without valid flight time or denominator | RSR FT/CT | Contact time and any valid flight output |
| Actual drop height missing for actual-drop claim | Equal exposure/normalization/mechanics claim | Rebound metrics not requiring actual height |
| BPT raw caller support indices | Any derived BPT support metric | Source series/provider values |
| BPT support without source/provider-qualified support evidence | Any derived BPT support metric | Exact source series/provider values |
| BPT missing counterbalance/load system/provider/device/support identity | Claim requiring that dimension | Source observation without the unsupported comparison/derivation |
| BPT provider MPV/power requested as DynamisLM arithmetic | Requested computation | Provider-reported value with origin/method if present |
| BPT generic load × velocity power | Generic power claim | Bar velocity and load as separately identified values |
| MBT scalar distance supplied as release velocity | Release velocity claim | Exact distance observation |
| MBT missing origin/end/first-contact convention or variant | Distance comparison/derivation | Source value and known protocol fields |
| MBT caller coordinates/endpoint booleans without coordinate source evidence | Derived MBT distance | Source-reported distance, if present |
| MBT caller-selected release sample without release-event source evidence | Instrumented release velocity | Qualified trajectory without an emitted release velocity |
| MBT distance relabelled power/normative score | Power/score claim | Exact distance |
| Any missing source/provenance/processing lineage | Derived/qualified claim | Independently describable source observations |

Refusals use the existing `RefusalResult` envelope and high-level classes,
with granular RES-68 reason strings, blocked claim, missing information, safe
descriptions, observation IDs and evidence references.

## O. Adversarial-test matrix

### DJ

Canonical event fixture; exact contact/flight/height/RSI/RSR gold cases;
distinct JH/CT and FT/CT identities; event order/source/protocol failures;
nominal-versus-actual height separation; unknown actual height permitting
unrelated rebound metrics; actual-height-dependent comparison refusal; CMJ
event supplied as DJ; missing landing preserving earlier contact output;
force-platform versus IMU/contact-mat/optical bridge requirement; malformed and
non-iterable fail-closed inputs; source/protocol/device lineage attacks; and
V3 canonical roundtrip/hash.

### BPT

Sampled maximum gold case; irregular-timebase weighted-mean gold case; exact
support identity; post-release support accepted when registered; provider MV
origin preserved and not relabelled; MV/Vmax/MPV metric separation;
counterbalance/moving-system-load/movement-pattern mismatch; ordinary bench
press/VBT relabelling; raw support indices; arithmetic sample mean
substitution; MPV/power/load×velocity refusal; provider power origin; malformed
series; lineage/provenance; and V3 roundtrip/hash.

### MBT

Exact coordinate-distance gold case; origin/end/first-contact/no-roll mismatch;
ball-mass, throw-type and posture/support mismatch; qualified instrumented
release velocity; distance-to-velocity and scalar relabelling refusal;
distance-as-power/normative/cross-protocol refusal; caller-minted qualification
refusal; malformed trajectory; provenance; and V3 roundtrip/hash.

### Generic

Same label/unit with different identity; forged provenance/output edge;
changed scalar with incompatible identity; same-source reprocessing creates a
distinct lineage/output; and missing material metadata fails closed.

## P. Existing-authority impact statement

The following authorities are explicitly unchanged:

```text
RES34_50_CHANGED=NO
RES60_64_CHANGED=NO
RES65_CHANGED=NO
RES66_CHANGED=NO
RES67_CHANGED=NO
SERIALIZATION_VERSION_CHANGED=NO
```

No CMJ event/result type, CMJ flight-time operation, CMJ gravity refusal,
RES-66 VBT identity, RES-64 external-load identity, RES-67 field-testing
identity, serializer semantics, historical hash, population/source authority,
football ontology, longitudinal authority, ingestion authority or refusal/
comparability kernel is broadened or mutated. New family registries and
family-specific types are additive and use the existing V3 registration
mechanism.

## Design-freeze disposition

```text
DJ_FLIGHT_TIME=IMPLEMENT
DJ_FLIGHT_TIME_JUMP_HEIGHT=IMPLEMENT
DJ_RSI_JH_CT=IMPLEMENT
DJ_RSR_FT_CT=IMPLEMENT
DJ_RSI_RSR_ALIASING=BLOCKED
NOMINAL_HEIGHT_AS_ACTUAL_HEIGHT=BLOCKED
MISSING_ACTUAL_HEIGHT_POISONS_UNRELATED_METRICS=BLOCKED
DJ_EVIDENCE_ATTRIBUTION=CORRECT
BPT_SUPPORT_IS_METRIC_SPECIFIC=PASS
POST_RELEASE_GENERIC_REJECTION=BLOCKED
PROVIDER_MV_AS_DYNAMISLM_MV=BLOCKED
GENERIC_BPT_POWER=NOT_REGISTERED
LOAD_TIMES_VELOCITY_AS_POWER=BLOCKED
COUNTERWEIGHT_SMITH_POWER_FUTURE_CANDIDATE=RECORDED
MBT_PROTOCOL_COLLAPSE=BLOCKED
MBT_DISTANCE_AS_POWER=BLOCKED
RES34_67_AUTHORITY_MUTATED=NO
SERIALIZATION_VERSION=3
DESIGN_FIX_STATUS=PASS
```

Implementation may now begin, but only as the additive family-scoped Phase B
described above. The final receipt must record actual QA facts and must not
pre-fill implementation or review PASS states.
