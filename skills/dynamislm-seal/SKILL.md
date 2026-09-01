---
name: dynamislm-seal
description: Enforce evidence-backed completion, Git sealing, and exact handoff discipline for DynamisLM units.
---

## Purpose

Prevent a unit from being declared complete merely because code exists.

## When to use

Use before completion claims, PR merge, Linear status transitions, or handoff.

## Canonical authority

Read the active Linear issue and [`docs/architecture/P1_EXECUTION_CONTRACT.md`](../../docs/architecture/P1_EXECUTION_CONTRACT.md).

## Hard invariants

Before sealing, verify: authorized scope; scientific decision where required; implementation; tests; static QA; evidence; provenance/version implications; comparability/refusal implications; an achievement commit; passing remote CI where applicable; clean worktree; synchronized Linear; and an exact next unit.

Every independently complete and qualified achievement receives its own commit before work proceeds.

## Required workflow

Run the local core gate, inspect the full diff for secrets/blobs/scope drift, run the applicable independent review, push/open or update the PR, wait for CI, verify the merged SHA and clean `main`, then write exact Linear evidence.

## Failure/stop conditions

Do not mark a unit Done with red CI, uncommitted work, stale architecture, unsupported claims, missing evidence, or an unnamed next authorization. Never use "mostly done" as a status.

## Required evidence/output

Report repository visibility/license, canonical path/environment, branch/PR/merge SHA, exact QA commands and test count, CI run, worktree state, skill checks, Linear states, and next authorized unit.

## Non-goals

Do not use sealing as permission to expand scope, deploy, train, or implement the next unit.
