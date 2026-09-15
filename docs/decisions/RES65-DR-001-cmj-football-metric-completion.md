# RES65-DR-001 — CMJ football metric completion

DECISION_ID=RES65-DR-001
STATUS=ADOPTED_FOR_RES65
MISSION=RES-65-IMPLEMENTATION
SERIALIZATION_VERSION=3

## Question and scope

Which force, power, takeoff-velocity, RSI-modified, RFD, and bilateral
asymmetry quantities can be added as a completion layer over the sealed
RES-34--RES-50 CMJ authority without creating a universal metric label or
mutating historical meaning?

This decision registers only method-specific supported-system quantities. It
does not create a new CMJ detector, mechanics engine, phase system,
jump-height estimator, session-selection rule, athlete-only COM claim,
readiness/fatigue claim, injury-risk claim, or physiological mechanism claim.

## Implementation inventory before RES-65 formulas

The following inventory was mechanically traced from the current implementation
and its tests:

| Authority | Existing implementation | RES-65 use |
| --- | --- | --- |
| Total supported vertical force | `construct_total_supported_vertical_force()` in `weighing.py`; `SINGLE_PLATFORM` and valid `BILATERAL_PRECOMBINED` pass through, `BILATERAL_SEPARATE` uses the registered elementwise bilateral sum | sole force source for force and power metrics |
| Net vertical force | `derive_net_vertical_force()` in `mechanics.py`; `F_net,z = F_total,z - SYSTEM_WEIGHT` | retained for historical mechanics; never substituted for power force |
| Supported-system COM velocity | `derive_supported_system_com_velocity()` and `SupportedSystemComVelocityResult`; RES-46 qualified zero-velocity reference and RES-37 trapezoidal integration | exact source for power and takeoff-velocity projection |
| Movement onset | `detect_movement_onset()` with `CMJ_MOVEMENT_ONSET_BASELINE_SD_METHOD` and exact RES-35 baseline/QC | whole-movement support and RSI-mod denominator |
| Takeoff | `detect_takeoff()` with `CMJ_TAKEOFF_ABSOLUTE_FORCE_METHOD` | whole-movement support, power phase end, and exact velocity projection |
| Phase system | `CMJ_FORCE_COM_VELOCITY_PHASE_SYSTEM_V1`; `CMJPhaseOccurrence` from `construct_cmj_phase_occurrences()` | braking and propulsion support only; no eccentric/concentric alias |
| Phase occurrences/support | `CMJPhaseOccurrence` and `CMJPhaseSampleSupport`; inclusive endpoint samples, no interpolation | exact phase boundaries and source event lineage |
| Historical phase metrics | `CMJPhaseMetricResult` and RES-39 operations | unchanged; new metrics do not reuse or relabel its values |
| Jump-height estimators | `CMJJumpHeightResult`: historical V1 flight-time, authoritative V2 flight-time, and qualified takeoff-velocity estimators | RSI-mod consumes the exact result object and preserves estimator identity |
| Session selection/aggregation | RES-40/50 `select_trials()`, `project_selected_trial()`, and `aggregate_cmj_session()` | new scalar wrappers are admitted through the existing metric-aware path |
| Acquisition/bilateral channels | `CMJAcquisitionIdentity`, `CMJChannelIdentity`, `BILATERAL_SEPARATE`, left/right roles, matching context/protocol/axis/frame/sign/timebase/timestamp/sample support, and immutable provenance | sufficient for narrowly bound asymmetry when the exact total-force phase source is also supplied |

The acquisition arrangement enum alone is not treated as proof. The
asymmetry constructor re-executes the registered bilateral total-force
operation, requires the exact left/right source objects, and verifies that its
result is the phase occurrence's source. Pre-combined bilateral and
single-platform inputs cannot produce an asymmetry result.

## Evidence reviewed

The following primary or methodological sources were opened and their methods
were checked rather than inferred from titles or abstracts:

* Maffiuletti et al. (2016), *Rate of force development: physiological and
  methodological considerations*, DOI
  [10.1007/s00421-016-3346-6](https://doi.org/10.1007/s00421-016-3346-6), PMID
  [26941023](https://pubmed.ncbi.nlm.nih.gov/26941023/). The review identifies
  force-onset, baseline noise, sampling, filtering, and slope/window choices
  as material RFD methodology.
* Owen et al. (2014), *Development of a criterion method to determine peak
  mechanical power output in a countermovement jump*, DOI
  [10.1519/JSC.0000000000000311](https://doi.org/10.1519/JSC.0000000000000311),
  PMID [24276298](https://pubmed.ncbi.nlm.nih.gov/24276298/). The criterion
  method defines instantaneous force-platform power as vertical force times
  whole-body COM velocity and specifies sampling/integration and initiation
  dependencies.
* Mundy et al. (2016), *Agreement between the force platform method and the
  combined method measurements of power output during the loaded countermovement
  jump*, DOI
  [10.1080/14763141.2015.1123761](https://doi.org/10.1080/14763141.2015.1123761),
  PMID [27075378](https://pubmed.ncbi.nlm.nih.gov/27075378/). The study shows
  method agreement limits are material and a standardized power method is
  required.
* Vieira and Tufano (2021), *Reactive strength index-modified: reliability,
  between group comparison, and relationship between its associated
  variables*, DOI
  [10.5114/biolsport.2021.100363](https://doi.org/10.5114/biolsport.2021.100363),
  PMID [34475626](https://pubmed.ncbi.nlm.nih.gov/34475626/), full text
  [PMC8329976](https://pmc.ncbi.nlm.nih.gov/articles/PMC8329976/). The data
  processing section explicitly defines `RSImod = JH / TTT`, with velocity-
  based jump height and TTT from movement initiation to takeoff.
* Janicijevic et al. (2022), *Single-leg mechanical performance and inter-leg
  asymmetries during bilateral countermovement jumps: A comparison of
  different calculation methods*, DOI
  [10.1016/j.gaitpost.2022.05.012](https://doi.org/10.1016/j.gaitpost.2022.05.012),
  PMID [35569352](https://pubmed.ncbi.nlm.nih.gov/35569352/), open full text
  [repository record](https://digibug.ugr.es/handle/10481/75584). The method
  calculates synchronized left/right peak and mean force in CMJ phases and
  reports direction-bearing standard percentage differences; it also shows
  peak and mean force asymmetries are distinct.
* Lake et al. (2018), *Do the peak and mean force methods of assessing vertical
  jump force asymmetry agree?*, DOI
  [10.1080/14763141.2018.1465116](https://doi.org/10.1080/14763141.2018.1465116),
  PMID [29782223](https://pubmed.ncbi.nlm.nih.gov/29782223/). Peak and mean
  force methods are not interchangeable even when agreement is substantial.
* Dos'Santos et al. (2024), *Validity of the Hawkin Dynamics wireless dual
  force platform system against a piezoelectric laboratory grade system for
  vertical countermovement jump variables*, DOI
  [10.1519/JSC.0000000000004785](https://doi.org/10.1519/JSC.0000000000004785),
  PMID [38781471](https://pubmed.ncbi.nlm.nih.gov/38781471/). The comparison
  evaluates phase force/power outputs from synchronously acquired dual
  platforms and reports fixed/proportional bias for several variables, which
  supports preserving source processing and platform identity.

The existing RES-34--RES-50 decision records remain the primary repository
authority for source identity, event samples, timebases, mechanics, phases,
jump-height estimators, provenance, comparability, and refusal.

## Disposition matrix

`INPUT_AUTHORITY` names typed objects already sealed or registered by this
decision. `PHASE/EVENT_SUPPORT` is always exact sample support; no hidden
crossing interpolation is introduced. `NORMALIZATION` is `NONE` for every
implemented output.

| METRIC | SCIENTIFIC_DEFINITION | INPUT_AUTHORITY | PHASE/EVENT_SUPPORT | PROCESSING_DEPENDENCIES | NORMALIZATION | COMPUTATIONAL_AUTHORITY | COMPARABILITY | STATUS |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Whole-movement sampled peak total supported vertical force | `max(F_total,z[i])` over inclusive movement-onset through takeoff samples | `TotalSupportedForceResult` | exact RES-36 movement-onset and takeoff occurrences | source force unit/axis/frame/sign/timebase/processing state; sample maximum; no interpolation | none | `CMJ_SAMPLE_PEAK_TOTAL_SUPPORTED_VERTICAL_FORCE_OPERATION` | metric, support, source processing, timebase, phase/event methods, and acquisition identity are material | IMPLEMENT |
| Whole-movement time-weighted mean total supported vertical force | `integral(F_total,z dt) / (t_end-t_start)` using sample-attached trapezoids | `TotalSupportedForceResult` | exact movement-onset through takeoff samples | actual regular or explicit timestamps; trapezoidal integration; no sample arithmetic mean | none | `CMJ_TIME_WEIGHTED_MEAN_TOTAL_SUPPORTED_VERTICAL_FORCE_OPERATION` | distinct from sampled peak and from arithmetic mean; timebase and support are material | IMPLEMENT |
| Braking sampled peak total supported vertical force | sampled maximum total supported force over the exact RES-39 braking occurrence | `TotalSupportedForceResult` | `CMJPhaseOccurrence` labelled `BRAKING` | source phase system/definition/boundaries; sample maximum; no interpolation | none | registered sample-peak force operation | distinct from propulsion, whole movement, and mean force | IMPLEMENT |
| Braking time-weighted mean total supported vertical force | trapezoidal time mean of total supported force over exact braking support | `TotalSupportedForceResult` | exact RES-39 braking occurrence | actual timestamps; no arithmetic sample mean | none | registered time-weighted force-mean operation | distinct from peak force and propulsion mean | IMPLEMENT |
| Propulsion sampled peak total supported vertical force | sampled maximum total supported force over the exact RES-39 propulsion occurrence | `TotalSupportedForceResult` | `CMJPhaseOccurrence` labelled `PROPULSION` | source phase system/definition/boundaries; sample maximum; no interpolation | none | registered sample-peak force operation | distinct from braking, whole movement, and mean force | IMPLEMENT |
| Propulsion time-weighted mean total supported vertical force | trapezoidal time mean of total supported force over exact propulsion support | `TotalSupportedForceResult` | exact RES-39 propulsion occurrence | actual timestamps; no arithmetic sample mean | none | registered time-weighted force-mean operation | distinct from peak force and braking mean | IMPLEMENT |
| Braking peak negative external mechanical power | `min(P_total[i])`, where `P_total[i] = F_total,z[i] * v_supported-system-COM,z[i]`, requiring a negative sampled value | total supported force plus exact `SupportedSystemComVelocityResult` | exact RES-39 braking occurrence | identical source trial/timebase/sample mapping; signed power; no absolute value | none | `CMJ_TOTAL_SUPPORTED_FORCE_TIMES_SUPPORTED_SYSTEM_COM_VELOCITY_OPERATION` plus sampled signed extremum | force quantity, velocity quantity, support, sign, filtering, timebase, system contract, and mean/peak operation are material | IMPLEMENT |
| Braking mean signed external mechanical power | trapezoidal time mean of signed `P_total` over braking support | same as above | exact RES-39 braking occurrence | actual timestamps; signed trapezoidal mean; no `abs(power)` | none | registered signed time-mean power operation | distinct from peak power and propulsion power | IMPLEMENT |
| Propulsion peak positive external mechanical power | `max(P_total[i])` over propulsion support, requiring a positive sampled value | same as above | exact RES-39 propulsion occurrence | identical force/velocity source binding; signed power; no absolute value | none | registered sampled signed extremum | distinct from braking power and mean power | IMPLEMENT |
| Propulsion mean signed external mechanical power | trapezoidal time mean of signed `P_total` over propulsion support | same as above | exact RES-39 propulsion occurrence | actual timestamps; signed trapezoidal mean | none | registered signed time-mean power operation | distinct from peak power and braking power | IMPLEMENT |
| Whole-movement peak power | mixed-sign whole-movement signed power extremum | force plus velocity could be available, but V1 support would mix phase meanings | no new whole-movement power support | no additional V2 use case justifies a mixed support identity | none | none | no generic whole-movement label is exposed | DEFER_WITH_REASON — phase-specific signed power is the narrow supported scope |
| Takeoff-velocity scalar | exact projection of `SupportedSystemComVelocityResult.samples[takeoff.sample_index]` | exact sealed velocity result plus exact takeoff occurrence | registered takeoff event sample | no second integration; event-sample convention; source velocity identity retained | none | `CMJ_TAKEOFF_VELOCITY_SCALAR_PROJECTION_OPERATION` | source velocity operation, zero reference, integration, event method/sample convention, timebase, and source identity are material | IMPLEMENT |
| RSI-modified from flight-time jump height | `JH_flight-time / (t_takeoff - t_movement-onset)` | exact registered `CMJJumpHeightResult` with flight-time estimator plus exact RES-36 onset/takeoff | onset and takeoff event times; no caller duration | exact numerator estimator and exact event methods/timebase; positive denominator | none | `CMJ_RSI_MOD_FLIGHT_TIME_OPERATION` | flight-time numerator and all event/upstream identities are material | IMPLEMENT |
| RSI-modified from takeoff-velocity jump height | `JH_takeoff-velocity / (t_takeoff - t_movement-onset)` | exact registered `CMJJumpHeightResult` with qualified takeoff-velocity estimator plus exact onset/takeoff | same denominator semantics | exact numerator estimator and exact event methods/timebase; positive denominator | none | `CMJ_RSI_MOD_TAKEOFF_VELOCITY_OPERATION` | distinct from flight-time RSI-mod even when scalar values match | IMPLEMENT |
| RFD family | rate of change of a named force quantity under an explicit onset/window/endpoint/differentiation method | current force/event inputs do not include one sealed RFD method | no RFD phase/window is registered | published methods vary by onset, window, regression/endpoint/difference, filtering, sampling, smoothing, and interpolation | none | none | no RFD output or comparison key is exposed | DEFER_WITH_REASON — exact scientific method authority is absent; generic `dF/dt` would be false authority |
| Braking peak-force asymmetry | `100 * (right_peak - left_peak) / left_peak` over exact synchronized braking support | exact raw left/right `CMJForceInput` pair plus exact total-force phase source | RES-39 braking occurrence; synchronous support, not limb-specific event timing | registered bilateral sum re-executed; same trial/clock/axis/frame/sign/processing/sample support; signed direction; nonzero left denominator | none | `CMJ_LEFT_RIGHT_FORCE_ASYMMETRY_OPERATION` with peak metric identity | equation, peak/mean statistic, phase, source channel roles, processing/timebase, and numerator order are material | IMPLEMENT |
| Braking mean-force asymmetry | `100 * (right_time_mean - left_time_mean) / left_time_mean` over exact synchronized braking support | same bilateral source binding | exact RES-39 braking occurrence | same support and time-weighted mean semantics as force metrics | none | same asymmetry operation with mean metric identity | not interchangeable with peak asymmetry | IMPLEMENT |
| Propulsion peak-force asymmetry | same signed equation using sampled propulsion peaks | same bilateral source binding | exact RES-39 propulsion occurrence | same synchronized source binding and sample maximum | none | same asymmetry operation with peak metric identity | not interchangeable with braking or mean asymmetry | IMPLEMENT |
| Propulsion mean-force asymmetry | same signed equation using time-weighted propulsion means | same bilateral source binding | exact RES-39 propulsion occurrence | same synchronized source binding and trapezoidal time means | none | same asymmetry operation with mean metric identity | not interchangeable with peak asymmetry | IMPLEMENT |
| Relative force/power normalization | any N/kg, W/kg, or percentage normalization of a CMJ force/power output | a denominator authority would be required | inherited support would still need a normalization identity | no body-mass alias; no physical-system-mass substitution without a separately registered operation | not applicable | none | no normalization bridge is registered | REJECT_FROM_RES65 — no V2 use case and no explicit denominator method |
| Vendor strategy bundles or ratios | labels such as “explosiveness”, “eccentric utilization”, “efficiency”, or “fatigue index” | no registered construct/claim authority | not applicable | would require additional identity and evidence | not applicable | none | no vendor label is computational authority | REJECT_FROM_RES65 |

## Registered identities and equations

### Force

All force metrics use `TOTAL_SUPPORTED_VERTICAL_FORCE`, never
`NET_VERTICAL_FORCE`. Peak means maximum of the recorded samples in the
declared inclusive support and is recorded as `SAMPLE_MAXIMUM`. It does not
claim a continuous-time maximum. Mean means the single RES-65
`TIME_WEIGHTED_TRAPEZOIDAL_MEAN` method:

```text
mean_time(F, a, b) =
    sum(i=a+1..b) 0.5 * (F[i-1] + F[i]) * (t[i] - t[i-1])
    ----------------------------------------------------------------
                         t[b] - t[a]
```

The timebase may be the exact regular or explicit source timebase already
validated upstream. No sample arithmetic mean is exposed under the RES-65
time-mean identity.

### Power

The only power force identity is `TOTAL_SUPPORTED_VERTICAL_FORCE`; the only
velocity identity is `SUPPORTED_SYSTEM_COM_VERTICAL_VELOCITY`. The same
physical supported-system contract, source trial, sample support, timebase,
axis/frame/sign, and processing lineage are required. The signed series is:

```text
P_total[i] = F_total_supported_vertical[i]
             * v_supported_system_COM_vertical[i]
```

Braking peak is the sampled minimum and must be negative. Propulsion peak is
the sampled maximum and must be positive. Means are signed trapezoidal time
means. `abs(power)` is not an operation. The claim ceiling is supported-system
external mechanical power under the registered force-platform model; no joint
power or muscle power is emitted.

### Takeoff velocity and RSI-modified

Takeoff velocity is a strict projection of the already sealed velocity result:

```text
takeoff_velocity = velocity.samples[
    takeoff.sample_index - velocity.series.sample_start_index
]
```

The event sample convention is
`CMJ_TAKEOFF_VELOCITY_EVENT_SAMPLE_CONVENTION`. No second integration or
caller-supplied scalar is accepted.

RSI-modified is registered twice because the numerator estimator is material:

```text
TTT = takeoff.event_time_s - movement_onset.event_time_s
RSI_mod = jump_height.value_m / TTT
```

The flight-time and takeoff-velocity numerator identities remain distinct even
when their reported height values are equal. RSI-modified is a method-specific
ratio with unit `m/s`, classified as a model estimate with no inferred
scientific role; it is not ordinary drop-jump RSI and does not carry readiness,
fatigue, reactive-strength, or physiological-mechanism authority.

### Bilateral asymmetry

The only V1 equation is direction-bearing and uses the left value as the
denominator, matching the explicitly checked Janicijevic method description:

```text
asymmetry_percent = 100 * (right_value - left_value) / left_value
```

The left denominator must be finite and nonzero. Positive means the registered
right value exceeds the registered left value; negative means the reverse. No
dominant or affected limb is inferred. Peak and time-mean values, braking and
propulsion supports, and all source channel identities are separate metric
identities.

## RFD and asymmetry authority boundaries

RFD is not computed. The repository has a sealed movement-onset detector, but
that does not choose an RFD onset, fixed window, endpoint, regression rule,
finite-difference rule, filter, smoothing method, sampling qualification, or
interpolation method. A generic first difference or `dF/dt` would therefore
create arbitrary authority.

Asymmetry is computed only after the registered bilateral total-force
construction succeeds. The constructor verifies both raw individual channels
are left/right, distinct, same athlete/session/test/trial/protocol, same
acquisition timestamp and exact timebase, same vertical axis/frame/sign, same
sample support, known processing state, and complete immutable source
provenance. A pre-combined bilateral source has no limb-resolved inputs and is
refused.

## Dataset authority

`CANONICAL_CMJ_DATASET_MAPPING=NOT_AVAILABLE_IN_CURRENT_P2D_AUTHORITY`.

The qualified RES-63 Source A canonical source contains provider summary
variables such as `Jumps>40cm(IMA)` but no canonical CMJ force-time trace
mapping sufficient for RES-65. Sources B--D are quarantined or otherwise not
promoted for this purpose. RES-65 does not promote data, fabricate traces,
map external-load fields, or alter RES-63 qualification. Numerical tests use
analytic and clearly synthetic fixtures only.

## Provenance and comparability

Every implemented result stores exact source observations, signals/artifacts,
acquisitions, source measurement identities, event/phase occurrences, method
references, processing policies, timebase, support, equation, and RES-65
processing-run lineage. Result constructors recompute authoritative scalar
values from their typed source objects where practical; a legitimate identity
paired with an arbitrary scalar is invalid.

RES-65 extends the existing CMJ comparison path. Material dimensions include
metric/statistic, phase or event support, total-versus-net force quantity,
sample-versus-time mean/peak method, signed power force and velocity identities,
mean-power method, source processing/filtering/sampling/timebase, system
contract, event/phase methods, RSI numerator estimator, and asymmetry equation
and channel roles. Missing or incompatible dimensions fail closed; no manual
force-comparable override is available.

## Historical and scope effects

No RES-34--RES-50 decision record is edited. Existing acquisitions, events,
mechanics, jump-height results, phases, phase metrics, session semantics,
serialization V3, and historical hashes retain their prior meaning. RES-65 is
additive and uses a separate `RES65` software/method identity. It does not
change RES-63 canonical authority, RES-64 external-load science, football-world
authority, model training, GPU work, inference, or RES-66+ implementation.

## Machine-readable receipt

```text
FORCE_PEAK_STATUS=IMPLEMENTED
FORCE_MEAN_STATUS=IMPLEMENTED
FORCE_PEAK_METHOD=SAMPLE_MAXIMUM_OVER_EXACT_INCLUSIVE_SUPPORT
FORCE_MEAN_METHOD=TIME_WEIGHTED_TRAPEZOIDAL_MEAN
POWER_STATUS=IMPLEMENTED
POWER_FORCE_QUANTITY=TOTAL_SUPPORTED_VERTICAL_FORCE
POWER_VELOCITY_QUANTITY=SUPPORTED_SYSTEM_COM_VERTICAL_VELOCITY
POWER_MEAN_METHOD=SIGNED_TIME_WEIGHTED_TRAPEZOIDAL_MEAN
TAKEOFF_VELOCITY_SCALAR_STATUS=IMPLEMENTED
RSI_MOD_STATUS=IMPLEMENTED
RSI_MOD_NUMERATOR_AUTHORITY=EXACT_REGISTERED_JUMP_HEIGHT_ESTIMATOR; FLIGHT_TIME_AND_TAKEOFF_VELOCITY_REMAIN_DISTINCT
RSI_MOD_DENOMINATOR_AUTHORITY=RES36_TAKEOFF_EVENT_TIME_MINUS_RES36_MOVEMENT_ONSET_EVENT_TIME
RFD_STATUS=DEFERRED_WITH_REASON
RFD_METHODS=NONE; ONSET_WINDOW_ENDPOINT_DIFFERENTIATION_FILTERING_AND_SAMPLING_AUTHORITY_NOT_FROZEN
ASYMMETRY_STATUS=IMPLEMENTED
ASYMMETRY_METHODS=BRAKING_PEAK_FORCE; BRAKING_TIME_MEAN_FORCE; PROPULSION_PEAK_FORCE; PROPULSION_TIME_MEAN_FORCE
ASYMMETRY_SOURCE_BINDING=PASS
CANONICAL_CMJ_DATASET_MAPPING=NOT_AVAILABLE_IN_CURRENT_P2D_AUTHORITY
```

## Version

`RES65-P3B-1.0.0`; `SERIALIZATION_VERSION=3` retained.
