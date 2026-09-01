<!-- Curated from the sealed Linear document: https://linear.app/alignerr-cmj/document/dynamislm-measurement-data-provenance-and-comparability-architecture-1d6c69cc2fc9 -->

## Status

`P0=SEALED`

This document defines the conceptual data and provenance architecture P1 must implement without prematurely fixing test-specific schemas.

## Scientific observation model

```text
ScientificMeasurementObservation
    = ObservationContext
    + MeasurementIdentity
    + MeasurementResult
    + Provenance
```

`MeasurementIdentity` is not the observed value itself. It identifies what was measured and how the result was produced. `MeasurementResult` carries the value/output and associated uncertainty/quality information. `Provenance` carries lineage.

## Containment + lineage architecture

The athlete/testing hierarchy is a containment structure, while scientific derivation is a DAG.

```text
Squad / Team Membership
          │
        Athlete
          │
        Session
          │
      TestInstance
   (family + protocol)
          │
         Trial
          │
          ├──── Acquisition / Device A ─── RawArtifact A
          │
          └──── Acquisition / Device B ─── RawArtifact B
                                         │
                                         ▼
                                  ProcessingRun
                              (method + parameters
                               + software version)
                                         │
                              ┌──────────┴──────────┐
                              ▼                     ▼
                    MeasurementObservation  MeasurementObservation
                              │                     │
                              └──────────┬──────────┘
                                         ▼
                                     AnalysisRun
                                         │
                                         ▼
                                        Result
                                         │
                                         ▼
                               ClaimCandidate / Report
```

This must support:

* multiple tests per session;
* multiple trials;
* multiple devices/acquisitions where relevant;
* missing tests;
* protocol changes;
* device/software changes;
* squad membership;
* reprocessing old raw data;
* multiple estimators from one raw artifact;
* analyses combining many sessions/athletes.

## MeasurementIdentity blocks

### Semantic identity

* construct;
* test family;
* protocol identity;
* measurand;
* metric definition;
* authorized aliases.

### Acquisition identity

* device/measuring system;
* raw signal/artifact;
* sensor/channel;
* sampling characteristics;
* calibration/reference state where material.

### Processing identity

* event definitions;
* phase definitions;
* estimator/algorithm;
* equation;
* method parameters;
* filtering;
* differentiation/integration;
* units;
* sign convention;
* normalization;
* trial selection;
* trial aggregation.

### Version identity

* processing/software version;
* method registry version;
* hardware/firmware version where material.

### Applicability/context

* athlete/session/test/trial identity;
* population context;
* environmental context where material;
* evidence applicability;
* uncertainty/quality status.

## Provenance contract

Every system-generated derived result must be traceable through:

```text
SOURCE DATA
    ↓
REGISTERED METHOD
    ↓
PARAMETERS
    ↓
SOFTWARE / ALGORITHM VERSION
    ↓
RESULT
```

The implementation must preserve at minimum:

* source artifact/measurement identifiers;
* Athlete–Session–TestInstance–Trial lineage;
* acquisition device/system metadata;
* protocol identity;
* sampling/channel information;
* calibration/reference status where material;
* registered method ID and version;
* event/phase definitions;
* equations/estimators;
* filters/transforms;
* all calculation-changing parameters;
* software/code version;
* output MeasurementIdentity;
* value/unit/normalization;
* uncertainty/quality status;
* trial inclusion/aggregation rules;
* evidence reference(s) and decision record;
* explicit dependency edges.

### Reprocessing invariant

```text
raw_observation R + algorithm_v1 = result D1
raw_observation R + algorithm_v2 = result D2

D2 MUST NOT OVERWRITE D1
```

Reprocessing creates a new result with distinct processing identity and provenance.

## Metrological traceability vs computational provenance

P1 must keep these concepts distinct:

* **Metrological traceability** concerns connection of a measurement result to a reference through a documented chain when applicable.
* **Computational/data provenance** concerns which data, methods, parameters and software produced a result.

Both may matter; they are not synonyms.

## Comparability is claim-relative

Two observations are not simply globally `same` or `different`. Their suitability depends on the requested claim.

Before a claim treats measurements as comparable, the system evaluates scientifically material dimensions including:

```text
construct
measurand
metric definition
estimator / algorithm
event definitions
phase definitions
protocol
device / measuring system
software / processing version
calibration / reference state
units
sign convention
normalization
filtering / sampling
trial selection
trial aggregation
population / context
uncertainty / applicable error model
```

## Comparability states

### `COMPARABLE`

No relevant known identity difference blocks the requested claim and required quality conditions are satisfied.

### `COMPARABLE_WITH_CONDITIONS`

A known difference exists, but registered evidence/rules authorize the requested claim under explicit conditions.

### `REQUIRES_TRANSFORMATION`

A registered deterministic transformation is required before comparability can be assessed. Transformation does not automatically make the measurements comparable.

### `BRIDGE_VALIDATION_REQUIRED`

A potentially material device/method/algorithm/protocol difference exists and no registered equivalence/agreement bridge is available.

### `NOT_COMPARABLE`

A known incompatibility in construct, measurand, definition or method blocks the requested claim.

### `INSUFFICIENT_INFORMATION`

Required metadata are missing, so the system cannot classify comparability.

## Hard comparability rules

```text
SAME_LABEL != SAME_IDENTITY
SAME_UNIT != SAME_MEASURAND
SAME_NUMBER != SAME_OBSERVATION
UNIT_CONVERSION != METHOD_HARMONIZATION
VALID_IN_ISOLATION != INTERCHANGEABLE
HIGH_CORRELATION != MEASUREMENT_AGREEMENT
RELIABILITY != ABSENCE_OF_SYSTEMATIC_BIAS
```

Different identities are not automatically non-comparable. They may become comparable through explicit transformation or validated bridging.

## P1 implementation constraint

P1 must implement the generic data/provenance/comparability primitives first, then enrich them through vertical scientific slices. It must not hard-code a global assumption that all instances of a human-readable metric name share one definition.
