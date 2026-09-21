# RES-71 scientific-engine qualification report

Mission: `RES-71-SCIENTIFIC-ENGINE-GATE-001`

Qualified base: `7508a9025759c2863d163e09b22f325494828602`

Scope: deterministic V2 scientific truth layer only.

## Executive result

The qualification harness independently audits the merged RES-59 and
RES-63–70 implementation surface. It discovers 100 unique
`registered-operation` identities at runtime and requires a reviewed inventory
entry for every one. The current contract contains 81 implemented operations,
one historical replay-only identity, seven represented-but-not-computed
identities, eight deferred identities and three rejected identities.

The deferred and rejected surfaces are explicit refusal authority. They do not
count as missing gate coverage: unsupported methods are represented with a
reason, refusal path, safe description and tests.

The formal gate decision is sealed in `RES71-GATE-RECEIPT.json` after final QA.

## Entry and upstream authority

The entry checks were performed before mutation:

| Check | Result |
|---|---|
| One worktree | PASS |
| Branch | `work/res-71-scientific-engine-qualification-gate` |
| `HEAD` | `7508a9025759c2863d163e09b22f325494828602` |
| `origin/main` | `7508a9025759c2863d163e09b22f325494828602` |
| Worktree | clean at entry |
| Linear RES-71 | In Progress; no LM/GPU work authorized |

The qualification treats the sealed V2 constitution, measurement/provenance
architecture, RES-60–70 decision records/receipts, and merged repository state
as upstream authority. It does not alter their scientific formulas, thresholds,
identities or expected fixtures.

## Qualification components

| Component | Evidence | Result |
|---|---|---|
| Registered-operation inventory | `build_registered_operation_inventory()` equals live runtime registry | PASS |
| V2 coverage matrix | 12 required scientific domains | PASS |
| Unresolved computation inventory | 23 explicit refusal/representation entries | PASS |
| Identity/provenance | typed records, source/method/version/lineage checks and adversarial cases | PASS |
| Numerical integrity | independent gold values, finite/domain refusals, serialization/hash checks | PASS |
| Scientific boundaries | same-label collision, causal/estimand/refusal cases and upstream adversarial suites | PASS |
| Dataset compatibility | RES-63 canonical/quarantine authority and lineage coverage | PASS |
| Verifier interface | 12 immutable reference cases plus canonical manifest/digest adapter | PASS |

## Scientific boundary attacks

The qualification suite explicitly covers:

- same display label with a different measurand or method;
- method identity versus method instance and historical V1 versus current V2;
- within-athlete versus between-athlete estimands and pseudoreplication;
- correlation/agreement and bridge requirements;
- direct, derived, provider-derived and model-estimated value origin;
- nonfinite values, invalid domains and missing method prerequisites;
- numerical change versus measurement error and practical meaning;
- measurement change versus readiness, fatigue or injury interpretation;
- association versus causal evidence;
- canonical target-population evidence versus indirect method evidence;
- cross-source bridge and threshold abuse;
- claim-authority escalation and safe observation descriptions after refusal.

The existing RES-70 adversarial tests and new RES-71 cases are both run. A
refusal blocks the unsupported claim while preserving the strongest safe
description of the underlying observation.

## Scope prohibition

This qualification adds no model runtime, inference path, benchmark harness,
GPU work, CPT/DAPT, SFT/PEFT or RLVR/GRPO implementation. The reference
adapter emits deterministic case contracts only; it does not execute an LM.

## Reproduction

```text
./scripts/ci.sh
python scripts/res71_reference_cases.py --digest
python scripts/res71_reference_cases.py --manifest
```

The exact final commit and component statuses are recorded in the formal gate
receipt.
