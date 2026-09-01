---
name: dynamislm-refusal-claims
description: Produce claim-specific scientific refusals that preserve safe descriptions of valid observations.
---

## Purpose

Protect claim authority without erasing data or turning the system into a blanket over-refusal mechanism.

## When to use

Use for interpretation, practitioner-facing outputs, analysis eligibility, benchmark cases, or scientific answerability.

## Canonical authority

Read [`docs/architecture/REASONING_CLAIMS_EVALUATION_V1.md`](../../docs/architecture/REASONING_CLAIMS_EVALUATION_V1.md).

## Hard invariants

High-level classes are `IDENTITY_UNRESOLVED`, `COMPARABILITY_UNESTABLISHED`, `EVIDENCE_SCOPE_UNSUPPORTED`, `DATA_ADEQUACY_INSUFFICIENT`, `ANALYSIS_DESIGN_MISMATCH`, `UNCERTAINTY_LIMITS_CLAIM`, `CAUSAL_IDENTIFICATION_UNSUPPORTED`, and `COMPUTATION_NOT_REGISTERED`.

Refusal blocks the requested claim, not necessarily the underlying observations. Preserve `blocked_claim`, `reason_codes[]`, `missing_information[]`, and `what_can_still_be_safely_described`.

Respect the ladder `OBSERVED_VALUE → NUMERICAL_CHANGE → COMPARABLE_CHANGE → CHANGE_RELATIVE_TO_MEASUREMENT_ERROR → PRACTICAL_OR_DECISION_MEANINGFULNESS` and causal levels L0–L5. Prediction is orthogonal to causal level.

## Required workflow

Identify the requested claim, the first unsupported prerequisite, and the strongest safe description. Use granular versioned reasons and link applicable evidence/rules.

## Failure/stop conditions

Stop on unsupported causal promotion, between-to-within inference, uncertainty-free interpretation, or refusal that discards independently valid observations.

## Required evidence/output

Test a blocked longitudinal comparison whose component observations remain independently describable, plus serialization of every refusal field.

## Non-goals

Do not invent universal thresholds, clinical claims, or a refusal class outside the sealed architecture.
