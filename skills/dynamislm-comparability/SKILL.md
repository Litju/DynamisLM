---
name: dynamislm-comparability
description: Enforce claim-relative comparability and deterministic-rule authority across measurement identities.
---

## Purpose

Prevent silent harmonization of measurements that share labels or units but differ scientifically.

## When to use

Use for multi-session, cross-device, cross-protocol, cross-method, cross-software, or longitudinal comparison work.

## Canonical authority

Read [`docs/architecture/MEASUREMENT_DATA_PROVENANCE_V1.md`](../../docs/architecture/MEASUREMENT_DATA_PROVENANCE_V1.md).

## Hard invariants

```text
SAME_LABEL != SAME_IDENTITY
SAME_UNIT != SAME_MEASURAND
HIGH_CORRELATION != MEASUREMENT_AGREEMENT
VALID_IN_ISOLATION != INTERCHANGEABLE
```

Use only these states: `COMPARABLE`, `COMPARABLE_WITH_CONDITIONS`, `REQUIRES_TRANSFORMATION`, `BRIDGE_VALIDATION_REQUIRED`, `NOT_COMPARABLE`, and `INSUFFICIENT_INFORMATION`.

## Required workflow

Accept a typed, claim-relative request containing candidate observations and any explicitly requested transformation. If a registered deterministic rule exists, invoke it and return its versioned result. A transformation request is not a comparability verdict.

## Failure/stop conditions

Without a registered rule or required metadata, return an explicit insufficient/unresolved result with missing information or `COMPARABILITY_NOT_REGISTERED`. Never accept an LM-supplied verdict as an override.

## Required evidence/output

Return state, granular reasons, conditions, transformations required, missing information, and rule/evidence references. Test deterministic round-trip and no-rule refusal paths.

## Non-goals

Do not add CMJ/VBT/device rules, global label merging, correlation-as-agreement logic, or an ontology of all comparability bridges in P1A.
