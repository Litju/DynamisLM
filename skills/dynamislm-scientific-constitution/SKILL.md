---
name: dynamislm-scientific-constitution
description: Protect DynamisLM's current V2 scientific scope and authority architecture during project-level changes.
---

## Purpose

Prevent scope drift or accidental reopening of the V2 scientific constitution while allowing only authorized downstream implementation work.

## When to use

Use for changes to scientific architecture, ontology, data semantics, claim boundaries, or project scope.

## Canonical authority

Read [`docs/architecture/SCIENTIFIC_CONSTITUTION_V2.md`](../../docs/architecture/SCIENTIFIC_CONSTITUTION_V2.md). It is the repository representation of the current Linear authority. Read [`docs/architecture/SCIENTIFIC_CONSTITUTION_V1.md`](../../docs/architecture/SCIENTIFIC_CONSTITUTION_V1.md) only as historical provenance.

## Hard invariants

- `P0.2 = SEALED`.
- The canonical population is `SEX=MALE`, `AGE_CLASS=SENIOR`, `SPORT=ASSOCIATION_FOOTBALL`, `PROFESSIONAL_STATUS=PROFESSIONAL`, `SQUAD_LEVEL=FIRST_TEAM`, `COMPETITION_LEVEL=TOP_DOMESTIC_DIVISION`.
- The three scientific domains are Performance Testing, External Load / Exposure and Longitudinal Football Context.
- The original twelve families remain Performance Testing scope, not the complete DynamisLM scientific world.
- `KNOWLEDGE_SCOPE != COMPUTATIONAL_AUTHORITY_SCOPE != CLAIM_AUTHORITY_SCOPE`.
- `ALL_ACCEPTED_SYSTEM_GENERATED_NUMERICAL_SCIENCE = DETERMINISTIC_PYTHON_AUTHORITY`.
- Model-runtime/inference/GPU work is prohibited until RES-71 records `SCIENTIFIC_ENGINE_GATE = PASS`.
- A new metric, protocol, device, or estimator variant normally receives a distinct identity, method, evidence rule, or comparability rule; it does not silently reopen P0.

## Required workflow

Check the requested change against the V2 constitution, preserve V1 as historical provenance, implement only the authorized unit, and preserve the pull-based research model: targeted evidence only when a concrete decision requires it.

## Failure/stop conditions

Stop and report the exact conflict if the request authorizes a noncanonical population as canonical evidence, treats the twelve families as the whole scientific world, moves numerical authority into the LM, begins operational model/GPU work before RES-71, or redesigns a retained V1 invariant.

## Required evidence/output

Record the affected V2 authority document, the scope decision, and any new scientific decision record. Link implementation and tests. Existing RES-34→RES-50 CMJ authority remains valid unless a later method-level decision explicitly supersedes it.

## Non-goals

Do not duplicate the full constitution, perform project-wide literature review, mutate the historical V1 constitution, or create test-family skills before their contracts are authorized.
