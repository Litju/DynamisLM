---
name: dynamislm-authority-boundary
description: Keep authoritative numerical science in registered deterministic Python operations and out of the language-model layer.
---

## Purpose

Prevent silent transfer of computational authority to an LM or an unregistered helper.

## When to use

Use for model/tool interaction, analysis planning, numerical science, thresholds, transformations, comparability, or future runtime design.

## Canonical authority

Read [`docs/architecture/SCIENTIFIC_CONSTITUTION_V1.md`](../../docs/architecture/SCIENTIFIC_CONSTITUTION_V1.md) and [`docs/architecture/REASONING_CLAIMS_EVALUATION_V1.md`](../../docs/architecture/REASONING_CLAIMS_EVALUATION_V1.md).

## Hard invariants

```text
ALL_ACCEPTED_SYSTEM-GENERATED_NUMERICAL_SCIENCE
= DETERMINISTIC_PYTHON_AUTHORITY
```

The LM may resolve semantics, extract protocols, propose/select analysis classes, request registered operations, interpret structured outputs, reason about evidence/claims, and refuse unsupported claims. Deterministic software owns formulas, arithmetic, units, signal processing, events/phases, derivation, statistics, uncertainty, thresholds, meta-analysis, and registered comparability adjudication.

## Required workflow

Represent model output as a typed request. Validate prerequisites and dispatch only to a registered deterministic operation. Return a structured result with method/version/provenance. If no operation exists, return `COMPUTATION_NOT_REGISTERED`.

## Failure/stop conditions

Stop on any API that accepts an LM-supplied formula, threshold, event, phase, estimator, numerical result, or comparability override as authoritative.

## Required evidence/output

Identify the registered operation and version, inputs, output, provenance, and refusal path. Test that missing registration cannot be bypassed.

## Non-goals

Do not add an LM runtime, training stack, numerical engine, or test-specific operation in P1A.
