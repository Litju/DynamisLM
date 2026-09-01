---
name: dynamislm-measurement-model
description: Preserve DynamisLM's typed observation, identity, result, provenance, and two-axis measurement semantics.
---

## Purpose

Keep the scientific object model compositional and prevent an everything-object or label/value shortcut.

## When to use

Use for measurement schemas, registry primitives, ingestion, processing outputs, scientific records, or their serialization.

## Canonical authority

Read [`docs/architecture/MEASUREMENT_DATA_PROVENANCE_V1.md`](../../docs/architecture/MEASUREMENT_DATA_PROVENANCE_V1.md) and the constitution.

## Hard invariants

```text
ScientificMeasurementObservation
    = ObservationContext
    + MeasurementIdentity
    + MeasurementResult
    + Provenance
```

- `MeasurementIdentity` describes what/how; it never contains the observed result value.
- `ObservationContext` owns athlete, session, test-instance, trial, time, population, and material environment context.
- `MeasurementResult` owns the tagged output, quality, uncertainty/status metadata.
- Evidence applicability is separately versionable and is not a mutable conclusion embedded in identity.
- Value origin and scientific role are independent axes: direct/derived/model versus performance/latent/physiological.
- Physical instrument output is a measurement subject to method/device uncertainty, not unconditional ground truth.

## Required workflow

Model each boundary as a distinct typed object, use stable registry IDs plus explicit versions, and make nested contracts immutable. Add a field only when it has a concrete reusable P1 need.

## Failure/stop conditions

Reject naked metric labels, identity/value coupling, context duplication, collapsed taxonomy axes, mutable nested metadata, or raw-signal blobs inside a result.

## Required evidence/output

Add focused construction, immutability, serialization, and boundary tests for every new contract field.

## Non-goals

Do not build a complete ontology, persistence layer, raw-signal engine, or test-specific metric model in a generic kernel unit.
