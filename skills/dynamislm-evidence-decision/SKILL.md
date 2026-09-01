---
name: dynamislm-evidence-decision
description: Enforce pull-based, explicit scientific decisions when an authorized implementation unit encounters unresolved definitions.
---

## Purpose

Keep evidence work proportional to a concrete scientific implementation decision.

## When to use

Use when a measurement definition, method, applicability, comparability rule, uncertainty model, or claim boundary is unresolved.

## Canonical authority

Read [`docs/architecture/P1_EXECUTION_CONTRACT.md`](../../docs/architecture/P1_EXECUTION_CONTRACT.md) and [`docs/decisions/README.md`](../../docs/decisions/README.md).

## Hard invariants

```text
IMPLEMENTATION UNIT
→ SCIENTIFIC DECISION REQUIRED?
→ TARGETED RESEARCH IF NECESSARY
→ EXPLICIT DECISION RECORD
→ REGISTER METHOD / IDENTITY
→ IMPLEMENT
→ TEST
→ EVIDENCE RECORD
→ SEAL
```

Record the exact question, sources inspected, population/method applicability, adopted decision, material alternatives, assumptions, limitations, registry/method version, and realizing implementation/tests.

## Required workflow

First check whether sealed authority already resolves the question. If not, perform only targeted research, write the decision record, then register the identity/method before coding.

## Failure/stop conditions

Stop on project-wide literature sweeps, undocumented evidence conclusions, or pooled statistics produced by an LM. Use deterministic Python for any authorized quantitative synthesis.

## Required evidence/output

Link the decision record to the registry object, code, tests, and provenance implications.

## Non-goals

Do not reopen P0 or launch literature/reliability/meta-analysis work without a concrete authorized decision.
