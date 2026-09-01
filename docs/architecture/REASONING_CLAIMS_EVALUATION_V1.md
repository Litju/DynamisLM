<!-- Curated from the sealed Linear document: https://linear.app/alignerr-cmj/document/dynamislm-reasoning-claims-refusal-and-evaluation-architecture-v1-1478e6df58b6 -->

## Status

`P0=SEALED`

This document defines the scientific reasoning architecture that constrains every later model-training and evaluation decision.

## Longitudinal claim ladder

DynamisLM may not skip conceptual levels:

```text
OBSERVED_VALUE
      ↓
NUMERICAL_CHANGE
      ↓
COMPARABLE_CHANGE
      ↓
CHANGE_RELATIVE_TO_MEASUREMENT_ERROR
      ↓
PRACTICAL_OR_DECISION_MEANINGFULNESS
```

### `OBSERVED_VALUE`

A value was recorded under a particular MeasurementIdentity and provenance context.

### `NUMERICAL_CHANGE`

A deterministic arithmetic difference exists. This alone does not establish scientific comparability.

### `COMPARABLE_CHANGE`

The observations satisfy the claim-relative comparability contract.

### `CHANGE_RELATIVE_TO_MEASUREMENT_ERROR`

An applicable measurement-error/uncertainty model exists and the change is interpreted against it.

### `PRACTICAL_OR_DECISION_MEANINGFULNESS`

A separate justified decision/utility criterion exists. Detectability does not automatically establish practical importance.

## Longitudinal invariants

```text
STATISTICAL_EVIDENCE_OF_CHANGE
!= CHANGE_EXCEEDING_APPLICABLE_MEASUREMENT_ERROR
!= PRACTICALLY_OR_DECISION_MEANINGFUL_CHANGE
```

No universal meaningful-change threshold is locked in P0. TE, CV, SEM, MDC/SDC, responsiveness, confidence intervals and repeated-baseline estimates answer different questions and must be applied under registered assumptions.

## Between-athlete / within-athlete contract

```text
BETWEEN_ATHLETE_ASSOCIATION
DOES_NOT_BY_ITSELF_ESTABLISH
WITHIN_ATHLETE_LONGITUDINAL_ASSOCIATION

WITHIN_ATHLETE_ASSOCIATION
DOES_NOT_BY_ITSELF_ESTABLISH
CAUSAL_EFFECT
```

DynamisLM must identify the estimand actually requested.

Registered analysis families may later include:

* cross-sectional correlation;
* repeated-measures correlation;
* person-mean centering;
* mixed-effects models;
* random intercepts / random slopes;
* change-score models;
* time-varying covariates;
* lagged models;
* multilevel squad structures.

P0 does not freeze one universal model. It freezes the obligation to distinguish between, within, and causal questions.

## Cross-test relationship taxonomy

DynamisLM distinguishes:

### `CORRELATION`

Statistical covariation under a declared design/estimand.

### `SHARED_MECHANICAL_DETERMINANTS`

Plausible/common physical or biomechanical contributors. This does not establish metric equivalence.

### `TEMPORAL_COVARIATION`

A longitudinal relationship after appropriate repeated-measures structure is accounted for.

### `PREDICTION`

X contains information useful for predicting Y under an explicit predictive validation protocol. Predictive accuracy is orthogonal to causal authority.

### `MECHANISTIC_HYPOTHESIS`

A scientifically grounded potential explanation that is not yet an identified causal effect.

### `CAUSAL_EFFECT`

A causal estimand and defensible identification/design strategy support an effect claim.

Tests may relate without being interchangeable.

## Causal claim hierarchy

### `LEVEL_0 — OBSERVATION`

Description of a scientifically identified measurement.

### `LEVEL_1 — DESCRIPTIVE_CHANGE`

Description of temporal change between comparable observations. Stronger statements about detectability require applicable uncertainty/error analysis.

### `LEVEL_2 — ASSOCIATION`

A statistical relationship under the declared between/within estimand.

### `LEVEL_3 — TEMPORAL_ASSOCIATION`

Longitudinal association with explicit temporal ordering and appropriate repeated-measures structure.

### `LEVEL_4 — MECHANISTIC_HYPOTHESIS`

A plausible explanatory mechanism supported by the observed relationship plus external mechanical/biological rationale, stated explicitly as hypothesis.

### `LEVEL_5 — CAUSAL_EVIDENCE`

An explicit causal question/estimand, temporal structure, defensible design or identification strategy, assumptions, bias/confounding control, analysis and uncertainty justify a causal claim.

Routine observational athlete-monitoring data must not silently become Level 5.

Prediction is not a causal level.

## Scientific refusal architecture

Refusal is claim-specific, not a blanket rejection of the underlying data.

### High-level classes

#### `IDENTITY_UNRESOLVED`

Representative reasons:

* insufficient method information;
* insufficient protocol information;
* insufficient device metadata;
* proprietary definition unresolved;
* metric definition mismatch;
* measurand mismatch;
* event/phase definition mismatch.

#### `COMPARABILITY_UNESTABLISHED`

Representative reasons:

* unit/normalization mismatch;
* protocol mismatch;
* device comparability not established;
* software pipeline comparability not established;
* trial aggregation mismatch;
* measurement agreement not established.

#### `EVIDENCE_SCOPE_UNSUPPORTED`

Representative reasons:

* population generalization unsupported;
* validity not established;
* measurement-error reference not applicable.

#### `DATA_ADEQUACY_INSUFFICIENT`

Representative reasons:

* insufficient longitudinal data;
* insufficient sample size for requested analysis;
* temporal alignment inadequate;
* material missingness/quality failure.

#### `ANALYSIS_DESIGN_MISMATCH`

Representative reasons:

* between/within inference mismatch;
* independence assumption violated;
* clustering/dependence not handled;
* estimator prerequisites unmet.

#### `UNCERTAINTY_LIMITS_CLAIM`

The requested claim is stronger than the available measurement uncertainty permits.

#### `CAUSAL_IDENTIFICATION_UNSUPPORTED`

The requested causal claim lacks an adequate causal design/identification strategy.

#### `COMPUTATION_NOT_REGISTERED`

The requested quantity, threshold, estimator or analysis has no registered deterministic implementation or its required inputs are unavailable.

### Refusal result

```text
RefusalResult {
    status
    blocked_claim
    reason_codes[]
    missing_information[]
    what_can_still_be_safely_described
}
```

A blocked comparison does not erase valid separate observations.

## Practitioner question classes

1. `MEASUREMENT_IDENTITY_AND_PROVENANCE`
   * What exactly is this value and how was it produced?
2. `COMPARABILITY_AND_HARMONIZATION`
   * Can these observations be compared, transformed or bridged?
3. `INDIVIDUAL_LONGITUDINAL_CHANGE`
   * What changed in this athlete and what claim level is supported?
4. `GROUP_OR_SQUAD_CHANGE`
   * What changed in the group and what group-level estimand is being reported?
5. `RELATIONSHIP_AND_MULTILEVEL_STRUCTURE`
   * Are X and Y related, and is the relationship between athletes, within athletes, or both?
6. `CONSTRUCT_AND_CLAIM_INTERPRETATION`
   * What scientific construct/interpretation is actually supported by this observation?
7. `METHOD_AND_ANALYSIS_REASONING`
   * Which protocol/method details matter and what analysis class is appropriate?
8. `ANSWERABILITY_AND_REFUSAL`
   * What information or scientific condition prevents the requested claim?

## Model-training research objective

> Improve the probability that, given practitioner language, structured athlete measurements, MeasurementIdentity/provenance metadata, applicable evidence and deterministic numerical results, DynamisLM selects the scientifically correct semantic identity, admissible analysis class, comparability state, claim level, interpretation or justified refusal—while reducing unsupported scientific acceptance and never acquiring authoritative numerical-science ownership.

Trainable/evaluable transformations include:

```text
language → terminology/test/protocol resolution
measurement → identity resolution
identity → direct/derived/model/inference classification
measurement pair/set → comparability state
question + design → analysis class
longitudinal structure → within/between estimand
result + evidence → bounded interpretation
requested statement → causal level
missing prerequisites → granular refusal
```

## Dynamis-Eval conceptual contract

Every claimed model capability must become observable and falsifiable.

Dynamis-Eval must ultimately cover:

* semantic resolution;
* protocol extraction;
* MeasurementIdentity resolution;
* same-label/different-measurand detection;
* direct/derived/model/inferred classification;
* device/method comparability;
* missing-metadata detection;
* analysis-class selection;
* within-vs-between reasoning;
* scientific refusal;
* causal-level classification;
* deterministic-result interpretation;
* evidence-bound interpretation;
* unsupported-claim rate.

## Error asymmetry

Critical errors include:

```text
FALSE_SCIENTIFIC_ACCEPTANCE
INVENTED_NUMERICAL_SCIENCE
FALSE_COMPARABILITY_ACCEPTANCE
CAUSAL_OVERCLAIM
BETWEEN_TO_WITHIN_MISINFERENCE
```

High-severity errors include:

```text
WRONG_MEASUREMENT_IDENTITY
WRONG_ANALYSIS_CLASS
DIRECT_DERIVED_COLLAPSE
UNSUPPORTED_LATENT_OR_PHYSIOLOGICAL_INFERENCE
```

Over-refusal, under-specified refusal and excessive conservatism must also be measured. Aggregate accuracy alone is not an adequate project metric.

## Evaluation-before-training rule

Before serious model adaptation, relevant Dynamis-Eval splits must be frozen and contamination-controlled. Model stages are compared per capability; a single aggregate score may summarize but never replace task-level evidence.
