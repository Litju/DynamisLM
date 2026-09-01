---
name: dynamislm-scientific-constitution
description: Protect DynamisLM's sealed P0 scientific scope and authority architecture during project-level changes.
---

## Purpose

Prevent scope drift or accidental reopening of P0 while allowing authorized P1 vertical work.

## When to use

Use for changes to scientific architecture, ontology, data semantics, claim boundaries, or project scope.

## Canonical authority

Read [`docs/architecture/SCIENTIFIC_CONSTITUTION_V1.md`](../../docs/architecture/SCIENTIFIC_CONSTITUTION_V1.md). It is the repository copy of the sealed Linear authority.

## Hard invariants

- P0 is sealed.
- The target population is `TRAINED_OR_COMPETITIVE_ADULT_TEAM_SPORT_ATHLETES_NON_CLINICAL`.
- The fixed domain remains exactly CMJ, Drop Jump, IMTP, Squat/Squat VBT, Bench Press/Bench VBT, Bench Press Throw, Medicine-Ball Throw, Short Linear Sprint/Acceleration, Maximum Sprint Velocity/High-Speed Sprint, 505 Change of Direction, 30–15 IFT, and RSA.
- `KNOWLEDGE_SCOPE != COMPUTATIONAL_AUTHORITY_SCOPE != CLAIM_AUTHORITY_SCOPE`.
- A new metric, protocol, device, or estimator variant normally receives a distinct identity, method, evidence rule, or comparability rule; it does not silently reopen P0.

## Required workflow

Check the requested change against the canonical constitution, implement only the authorized P1 unit, and preserve the pull-based research model: targeted evidence only when a concrete decision requires it.

## Failure/stop conditions

Stop and report the exact conflict if the request removes a fixed family, changes the target population, moves numerical authority into the LM, or redesigns a sealed P0 invariant.

## Required evidence/output

Record the affected authority document, the scope decision, and any new scientific decision record. Link implementation and tests.

## Non-goals

Do not duplicate the full constitution, perform project-wide literature review, or create test-family skills before their contracts are authorized.
