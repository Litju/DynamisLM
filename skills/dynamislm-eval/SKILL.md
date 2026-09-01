---
name: dynamislm-eval
description: Keep DynamisLM capability claims observable, falsifiable, and bounded by the authorized evaluation phase.
---

## Purpose

Ensure later model behavior is evaluated by scientific capability and error asymmetry rather than unsupported aggregate claims.

## When to use

Use for model-facing tests, benchmark design, evaluation contracts, SFT/RLVR data, or capability claims.

## Canonical authority

Read [`docs/architecture/REASONING_CLAIMS_EVALUATION_V1.md`](../../docs/architecture/REASONING_CLAIMS_EVALUATION_V1.md).

## Hard invariants

Future capability families include semantic/protocol/identity resolution, same-label/different-measurand detection, direct/derived/model/inference classification, comparability, missing metadata, analysis-class selection, within-vs-between reasoning, refusal, causal classification, deterministic-result interpretation, evidence-bounded interpretation, and unsupported-claim rate.

Critical error classes include `FALSE_SCIENTIFIC_ACCEPTANCE`, `INVENTED_NUMERICAL_SCIENCE`, `FALSE_COMPARABILITY_ACCEPTANCE`, `CAUSAL_OVERCLAIM`, and `BETWEEN_TO_WITHIN_MISINFERENCE`. Over-refusal remains measurable.

## Required workflow

Translate each capability claim into an observable test contract with adversarial cases and contamination controls appropriate to its authorized phase.

## Failure/stop conditions

Do not invent benchmark datasets, scoring weights, training claims, or model results in P1A. Do not replace task-level evidence with a single aggregate score.

## Required evidence/output

For current generic contracts, test deterministic API behavior and scientific invariants only. For later model evaluation, preserve split/version/contamination and error-class evidence.

## Non-goals

Do not build Dynamis-Eval datasets, train a model, or define unapproved scoring policy in the bootstrap unit.
