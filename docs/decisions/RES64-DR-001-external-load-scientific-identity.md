# RES64-DR-001 — External-load scientific identity and deterministic metrics

## Control

`DECISION_ID=RES64-DR-001`

`SPEC_VERSION=1.0.0`

`STATUS=ADOPTED_FOR_IMPLEMENTATION`

`MISSION=RES-64`

`CONSTITUTION_VERSION=2.0.0`

`SERIALIZATION_VERSION=3`

`MODEL_TRAINING_USE=NOT_AUTHORIZED`

`GPU_WORK_AUTHORIZED=NO`

This record adds the authorized external-load / exposure scientific slice. It
does not reopen P0, modify CMJ authority, rewrite the RES-63 canonical
artifact, or authorize model work.

## Scientific question

How can DynamisLM represent match/training exposure and external-load values
from GNSS, optical tracking, inertial systems, and source/provider tables so
that metric identity, method, threshold, event, aggregation, processing,
normalization, provenance, and comparability remain explicit while only
reproducible operations receive DynamisLM computational authority?

The governing rules are:

```text
SAME_LABEL != SAME_MEASUREMENT
SOURCE_REPORTED_VALUE != DYNAMISLM_DERIVATION
PROVIDER_DERIVED_OBSERVATION != DYNAMISLM_COMPUTATIONAL_AUTHORITY
```

## Authority inspected

- `docs/architecture/SCIENTIFIC_CONSTITUTION_V2.md` — current sealed project
  scope, external-load domain, authority split, and non-goals.
- `docs/architecture/MEASUREMENT_DATA_PROVENANCE_V1.md` — observation,
  identity, provenance, reprocessing, and claim-relative comparability.
- `docs/architecture/REASONING_CLAIMS_EVALUATION_V1.md` — refusal and claim
  boundaries.
- `docs/architecture/P1_EXECUTION_CONTRACT.md` — registered-operation and
  decision-record workflow.
- `docs/decisions/RES60-DR-001-canonical-population-and-source-gate.md` —
  population/source qualification authority.
- `docs/decisions/RES61-DR-001-football-world-ontology.md` — typed football
  context authority.
- `docs/decisions/RES62-DR-001-longitudinal-record-and-multisource-provenance.md`
  — immutable composition and multi-source lineage authority.
- `docs/decisions/RES63-DR-001-canonical-dataset-ingestion.md` — Source A
  variable identity, canonical mapping, quarantine, and raw/canonical byte
  boundary.
- Existing generic contracts under `src/dynamislm/measurement/`,
  `src/dynamislm/provenance/`, `src/dynamislm/comparability/`,
  `src/dynamislm/refusal/`, and `src/dynamislm/serialization.py`.

Targeted domain evidence was required because the identity and refusal
dimensions in this slice are scientific requirements, not only software
conventions. The review-fix evidence below is deliberately bounded to the
decisions implemented here; it is not a general external-load literature
review.

## Targeted scientific evidence for identity and refusal boundaries

| Decision dimension | Evidence | Implementation consequence |
| --- | --- | --- |
| Absolute and individualized speed thresholds | The systematic review by Gualtieri et al. reports non-standard, wide ranges of HSR and sprint thresholds and distinguishes absolute from individualized thresholds ([DOI](https://doi.org/10.3389/fspor.2023.1116293)). Clemente et al. map the methodological choices and evidence gaps for arbitrary versus individualized thresholds ([DOI](https://doi.org/10.5114/biolsport.2023.122480)). | Threshold value, unit, basis, and individualized reference are identity fields; 20, 25, and 30 km/h are not silently interchangeable. |
| GNSS/LPS/optical comparability | The GNSS/LPS validation scoping review reports heterogeneous reference systems and methods and cautions against comparing results across validation studies ([DOI](https://doi.org/10.1136/bmjsem-2020-000794)). The team-sport tracking review reports differences between optical and GPS-derived distance/HSR and identifies sampling, satellite signal, and software filtering as material factors ([DOI](https://doi.org/10.1186/s40798-022-00408-z)). | Modality, measuring system, sampling, processing, and validated bridge status remain explicit; a unit match alone cannot authorize direct comparison. |
| Filtering and minimum-effort duration | Varley et al. show that filtering choices and minimum effort durations materially change HSR, sprint, and acceleration event counts ([DOI](https://doi.org/10.1123/ijspp.2016-0534)). Delves et al. document substantial reporting gaps in acceleration/deceleration derivation and cleaning methods ([DOI](https://doi.org/10.1186/s40798-021-00332-8)). | The registered V1 event path records and executes its boundary, interpolation, dwell, gap, filtering, smoothing, and resampling semantics; unsupported variants refuse. |
| Device/provider processing dependence | Malone et al. report substantial between-device variability in acceleration/deceleration occurrences and changes after software updates ([DOI](https://doi.org/10.1123/IJSPP.2013-0187)). | Provider, device, algorithm, software, and processing identity are retained and unresolved provider algorithms fail closed for comparability. |
| PlayerLoad/provider-load limits | PlayerLoad is described as a Catapult proprietary accelerometer metric with limited methodological transparency and unresolved construct limitations ([PMC review](https://pmc.ncbi.nlm.nih.gov/articles/PMC7052708/)). | PlayerLoad remains `PROVIDER_DERIVED`, non-recomputable, and cannot acquire DynamisLM authority through relabelling. |
| Metabolic-power limits | Buchheit et al. test the validity/reliability of GPS-estimated metabolic power in soccer-specific drills and identify limits of the estimate ([DOI](https://doi.org/10.1055/s-0035-1555927)). The systematic review finds unresolved effects of acceleration validity, sampling, filtering, walking/recovery, and context ([PMC review](https://pmc.ncbi.nlm.nih.gov/articles/PMC9596658/)). | Source A metabolic-power bands remain provider-derived identities; no metabolic-power algorithm is invented or recomputed here. |
| Measurement-result and method context | The BIPM International Vocabulary of Metrology defines a measurement result as quantity values attributed to a measurand together with relevant information ([JCGM 200:2012](https://doi.org/10.59161/JCGM200-2012)). ISO 5725-1:2023 treats method/result accuracy under explicitly controlled measurement conditions and distinguishes trueness from precision ([ISO 5725-1:2023](https://www.iso.org/standard/69418.html)). | Numerical results are separated from identity, but typed result construction must retain the exact input observation/evidence, method, unit, context, and provenance. |
| Source A system and acquisition | The primary UNIFESP/Domus Dados Source A documentation identifies Catapult VECTOR7 and reports GNSS (GPS/GLONASS/SBAS) at 18 Hz, Catapult ClearSky LPS at 10 Hz, accelerometer sampled at 1 kHz and provided at 100 Hz, and gyroscope/magnetometer at 100 Hz ([dataset documentation](https://domusdados.unifesp.br/dataset.xhtml?persistentId=hdl%3A20.500.12682%2Frdp%2FGMXME8)). It also describes the IMA, sprint, RHIE, metabolic-power, and PlayerLoad source variables. | The dataset/repository provider remains UNIFESP Domus Dados / Dataverse in the Source A variable identity, while the external measurement-system provider is Catapult and the device is VECTOR7. Known frequencies are structured; firmware, filtering, and proprietary algorithm details remain unknown. |

These sources support the refusal dimensions without authorizing a new
acceleration/deceleration, RHIE, PlayerLoad, or metabolic-power algorithm.

## Existing abstractions reused

RES-64 reuses the existing generic kernel without introducing a second
observation or provenance system:

1. `ScientificMeasurementObservation` remains the composite
   `ObservationContext + MeasurementIdentity + MeasurementResult + Provenance`.
2. `ExternalLoadMeasurementIdentity` is a typed `MeasurementIdentity`
   extension. Existing generic and CMJ identities are unchanged.
3. `MeasurementResult` and `ScientificClassification` carry output values,
   units, quality/status, uncertainty status, and the independent value-origin
   axis. Existing value-origin members remain valid; the external slice adds
   explicit `SOURCE_REPORTED`, `PROVIDER_DERIVED`, and `DYNAMISLM_DERIVED`
   members for this domain.
4. Existing `SourceArtifact`, `AcquisitionRecord`, `ProcessingRun`,
   `Provenance`, `LineageEdge`, and `create_derived_observation` remain the
   source and derived-result lineage authorities.
5. Existing `ComparabilityResult`, `ComparabilityState`,
   `ComparabilityReasonCode`, `ComparabilityAuthority` semantics, and
   `RefusalResult` are reused. External rules return the same typed result
   envelope and never accept a manual comparability override.
6. RES-61 football context and RES-62 longitudinal records remain wrappers
   around the unchanged observation leaf. RES-63 `SourceVariableIdentity`,
   `SourceVariableRegistry`, and `CanonicalEmpiricalRecord` remain the
   source-variable and canonical-row authorities.

The narrow new abstractions are external-load identity blocks, an operation
registry, raw velocity samples/summary results, and a Source A interpretation
mapping. None stores raw signal bytes in a result or duplicates source
lineage.

## Domain boundaries and metric vocabulary

The external-load domain represents observations and reproducible derivations
for:

- session/match duration and minutes exposure;
- total distance and duration-normalized relative distance;
- maximum/peak speed;
- thresholded high-speed-running and sprint distance, time, and event-count
  identities;
- acceleration/deceleration event identities;
- repeated-high-intensity-effort identities only when a complete registered
  definition is supplied;
- provider inertial/load outputs such as PlayerLoad; and
- optical-tracking analogues with their own modality/provider/method identity.

These names are metric-family labels, not universal definitions. A metric
family is identity-bearing together with its measurand, provider/system,
threshold, event, aggregation, processing, and normalization metadata.

RES-64 does not authorize training prescription, ACWR decision authority,
fatigue/readiness/injury inference, return-to-play, causal effects, tactical
analysis, player selection, optimization, model inference/training, or GPU
work.

## External-load measurement identity

`ExternalLoadMeasurementIdentity` extends the generic identity with:

### Modality

The closed registered vocabulary is:

```text
GNSS
OPTICAL_TRACKING
INERTIAL
SOURCE_REPORTED
OTHER_REGISTERED
```

GNSS, optical, inertial, and source-reported values are not aliases for one
another. A provider table may report a derived value from a GNSS or inertial
system; its provider/method identity is retained.

### Value origin

The external slice uses these explicit origins:

```text
DIRECT_MEASUREMENT
SOURCE_REPORTED
PROVIDER_DERIVED
DYNAMISLM_DERIVED
```

`MeasurementResult.classification.value_origin` and the external identity
origin must agree when an observation is built. A provider-derived output is
not relabelled as a direct measurement or a DynamisLM derivation.

### System identity

`ExternalLoadSystemIdentity` records the measurement-system provider, known
device/system, model, `SamplingCharacteristics`, acquisition characteristics,
firmware/software versions, and provider processing version when known. For
Source A, the dataset authority remains `UNIFESP Domus Dados / Dataverse` in
the source-variable identity, while the measurement-system provider is
`Catapult` and the device is `VECTOR7`. `None` means unknown where the field
is material; it is never filled with a default sampling rate, device, or
algorithm. Structured acquisition metadata distinguish sensor acquisition
frequency from provider-delivered frequency; they do not assert an algorithm
frequency.

### Threshold identity

`ExternalLoadThresholdIdentity` records threshold quantity, value, unit,
absolute versus individualized basis, individualized reference when
applicable, and inclusive/exclusive boundary semantics. It has explicit
`NONE` and `UNKNOWN` states. `20 km/h`, `25 km/h`, and `30 km/h` are distinct
threshold identities. A value in a different registered unit may be
deterministically converted for a unit-equivalence check; that does not erase
the original declared unit or method identity.

### Event identity

`ExternalLoadEventDefinition` records the registered event definition,
minimum duration/dwell, hysteresis, gap allowance, start/end rules, and
acceleration/deceleration threshold identities. Zero is a possible explicit
parameter; absent metadata are unknown. Event counts are never computed from
an event label alone.

### Aggregation identity

`ExternalLoadAggregationIdentity` records session definition, interval/window,
match/training/other context, and whole-session versus period/segment scope.
Different segmentation is a different measurement identity. Unknown
segmentation is not treated as whole-session.

### Processing identity

`ExternalLoadProcessingIdentity` records filtering status and method,
smoothing, resampling, differentiation and threshold-interpolation methods,
registered operation, calculation-changing parameters, and method/software
versions. Unknown
filtering, sampling, provider algorithm, or processing state remains explicit
and blocks comparisons where material.

### Normalization identity

`ExternalLoadNormalizationIdentity` records one of:

```text
NONE
DURATION_NORMALIZED
BODY_MASS_NORMALIZED
OTHER_REGISTERED
UNKNOWN
```

Duration normalization is registered only for distance divided by an
explicit valid duration. Body-mass and other normalization may be represented
only with a registered identity; RES-64 does not implement a body-mass
normalization operation.

## Direct, source, provider, and derived semantics

Source A's `CanonicalEmpiricalRecord` remains the RES-63 intermediate and is
not rewritten. The RES-64 mapping layer is an interpretation from an exact
source-variable identity to an external-load identity. It preserves the
source-variable ID, original label, provider, method family, threshold/band,
source aggregation context, and resolution/missing-information fields.
The qualified Source A variable registry remains bound to its RES-63
`sha256:02e2019a112edf70bba425bf1f8ef719e4d03e8fb72d039c351f4f1e7754fcf0`
identity; a partial or substituted registry cannot authorize mapping.

For Source A:

- `Matchduration(min)` maps as `SOURCE_REPORTED` with source-reported
  match-exposure semantics.
- `TotalDistance(m)`, `Relativedistance(m/min)`, `Maxvelocity(km/h)`, exact
  threshold-distance columns, sprint, IMA, RHIE, and Playerload columns map
  as `PROVIDER_DERIVED` observations with Catapult VECTOR7 measurement-system
  identity. The original source-variable identity continues to retain
  UNIFESP/Domus Dados as the dataset authority.
- `Distance>20,0km/h(m)` and `Distance>25,0km/h(m)` are separate mappings and
  separate identities; no generic `HSR_DISTANCE` collapse is permitted.
- Playerload, IMA, RHIE, and other provider outputs retain unresolved or
  partial proprietary processing metadata. Their values remain usable as
  source/provider observations but are not recomputable by DynamisLM from the
  canonical table. Event-shaped IMA/RHIE outputs retain their dedicated
  registered metric/event identities and count units where the Source A
  definition supports them; this does not invent their algorithms.
- No source mapping claims that the public table contains raw GNSS, optical,
  or inertial waveforms.

## Deterministic operation authority

The following operations are registered:

1. **Unit normalization.** The operation converts only registered compatible
   units, including `km/h ↔ m/s`, `minutes ↔ seconds`, `km ↔ m`, and the
   distance-rate units needed for relative distance. It rejects incompatible
   dimensions, non-finite values, and ambiguous units.
2. **Duration-normalized distance.** The authoritative operation consumes a
   total-distance `ScientificMeasurementObservation` and a duration
   `ScientificMeasurementObservation`. It extracts each value and unit from
   the observation result, verifies metric family, measurand, unit, origin,
   athlete/session/context, aggregation, and provenance bindings, and passes
   only those extracted values to the pure `D / T` helper. Missing duration is
   not zero; zero duration is a typed refusal. The derived identity includes
   the exact denominator identity and the result retains both input
   observations and a new derived observation/provenance lineage.
3. **Velocity threshold summary from actual samples.** The only threshold
   summary operation accepts `ExternalLoadVelocitySeriesEvidence`, which
   binds immutable timestamped samples to one measurement identity, context,
   source artifact, acquisition, processing run, sampling declaration, and
   provenance. A bare `VelocitySeries` or separately supplied identity is
   refused. The operation requires the registered speed measurand, exact V1
   event-definition/start/end references, explicit no-hysteresis semantics,
   explicit processing/filtering status, and explicit aggregation identity.
   It uses piecewise-linear interpolation between consecutive samples,
   integrates time and speed over the portions satisfying the boundary,
   rejects non-monotone/non-finite samples and undeclared gaps, and uses the
   exact dwell/gap semantics for event counts. The result contains typed
   DynamisLM-derived time, distance, and applicable event-count results; the
   raw fields are compatibility views of those results. It does not infer a
   sampling rate, filtering, dwell, gap rule, or threshold.

Acceleration/deceleration event algorithms, repeated-high-intensity effort
   algorithms, metabolic-power bands, and provider PlayerLoad/IMA/RHIE
   equations are not implemented as DynamisLM authority in RES-64. When raw
   inputs or exact registered semantics are absent, the operation returns a
   typed refusal with the missing information and preserves the independent
   source observation.

## Comparability and refusal

External-load comparison is claim-relative and returns the existing typed
`ComparabilityResult` states. A result is direct-comparable only when all
material identity dimensions agree after registered unit normalization and
the data are not missing required semantics. No manual `force comparable`
flag exists.

The registered rule refuses direct equivalence, with granular reasons, for at
least:

- different threshold values or definitions, including 20 versus 25 km/h;
- absolute versus individualized threshold basis;
- GNSS versus optical tracking without a validated bridge;
- provider-derived load outputs from different providers/algorithms;
- different session segmentation or aggregation;
- different dwell/minimum event duration for event metrics;
- unknown filtering versus known filtering where processing is material;
- total distance versus duration-normalized relative distance; and
- unresolved threshold, event, provider-algorithm, sampling, or segmentation
  metadata.

Known material method/device/processing differences resolve to
`BRIDGE_VALIDATION_REQUIRED` (direct equivalence is blocked); irreconcilable
measurand/metric-family differences resolve to `NOT_COMPARABLE`; missing
identity resolves to `INSUFFICIENT_INFORMATION`. A unit-only difference with
a registered compatible conversion is a `REQUIRES_TRANSFORMATION` request
when the caller explicitly requests transformation, and otherwise is
evaluated after deterministic unit normalization. A transformation request is
never itself a comparability verdict.

Unknown semantics have explicit reason codes and are never defaulted:

```text
UNKNOWN_THRESHOLD
UNKNOWN_THRESHOLD_BASIS
UNKNOWN_DWELL_RULE
UNKNOWN_EVENT_DEFINITION
UNKNOWN_FILTERING
UNKNOWN_SAMPLING_RATE
UNKNOWN_PROVIDER_ALGORITHM
UNKNOWN_SESSION_SEGMENTATION
```

## Provenance and Serialization V3

Provider observations retain the existing source/canonical provenance and
their exact source-variable identity. DynamisLM-derived results use a new
processing run and output observation/result identity. Relative-distance
results retain the two source observations; threshold results retain the
evidence-bound velocity series and its provenance. Reprocessing or changed
parameters create a new output; prior results are not overwritten.

All new public dataclasses use the existing V3 serializer. Existing valid
generic, CMJ, football, population, ingestion, and RES-62 objects retain
their historical fields and hashes. `SERIALIZATION_VERSION` remains `3`.

## Implementation and tests

The realization is limited to:

- `src/dynamislm/external_load/identity.py` — typed external identity blocks;
- `src/dynamislm/external_load/registry.py` — operation, unit, metric, and
  decision references;
- `src/dynamislm/external_load/metrics.py` — deterministic unit,
  evidence-bound normalization, velocity-series evidence, and typed threshold
  output operations;
- `src/dynamislm/external_load/comparability.py` — registered identity rule
  and granular fail-closed reasons;
- `src/dynamislm/external_load/mapping.py` — Source A interpretation layer;
- `tests/test_external_load.py` — construction, adversarial negative,
  mapping, computation, provenance boundary, serialization, and
  historical-regression tests.

No real raw bytes, canonical rows, model code, GPU code, or RES-65+ science is
added.
