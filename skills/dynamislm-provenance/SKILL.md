---
name: dynamislm-provenance
description: Protect immutable source-to-result lineage and reprocessing integrity for DynamisLM measurements.
---

## Purpose

Make every derived result auditable without overwriting historical scientific output.

## When to use

Use for acquisition, processing, reprocessing, versioning, persistence, caching, derived results, or evidence-lineage work.

## Canonical authority

Read [`docs/architecture/MEASUREMENT_DATA_PROVENANCE_V1.md`](../../docs/architecture/MEASUREMENT_DATA_PROVENANCE_V1.md).

## Hard invariants

```text
raw R + method v1 -> D1
raw R + method v2 -> D2
D2 MUST NOT overwrite D1
```

Preserve source artifact, acquisition, processing run, method/version, calculation-changing parameters, software/code version, output identity/result, evidence/decision references, and explicit lineage edges.

Keep computational/data provenance distinct from metrological traceability. They may both be represented, but they are not synonyms.

## Required workflow

Treat source artifacts and processing runs as immutable records. Create a new observation/result for every changed processing method or parameter set. Verify all lineage references and deterministic serialization.

## Failure/stop conditions

Stop on in-place result replacement, mutable lineage, missing processing version, hidden parameter changes, or provenance that cannot distinguish two reprocessing runs.

## Required evidence/output

Test same-source/different-method derivations, distinct output IDs, preserved prior provenance, and exact source-to-result edges.

## Non-goals

Do not conflate provenance with evidence validity, invent metrological traceability, or implement a complete database in P1A.
