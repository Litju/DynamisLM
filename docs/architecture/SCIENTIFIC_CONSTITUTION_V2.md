<!-- Curated from the authoritative Linear document: https://linear.app/alignerr-cmj/document/dynamislm-scientific-constitution-and-authority-architecture-v2-4e6605e810b7 -->

# DynamisLM — Scientific Constitution & Authority Architecture V2

## Status and version

`P0.2 = AUTHORIZED FOR IMPLEMENTATION`

`CONSTITUTION_VERSION=2.0.0`

This document is the current project-wide scientific authority for DynamisLM V2. It supersedes only the V1 clauses that defined a broad adult team-sport target population and treated the twelve performance-test families as the complete scientific world.

V1 remains historical provenance. It must not be rewritten as though it never existed. All V1 authority principles not explicitly superseded here remain in force.

## Project thesis

DynamisLM is a compact specialized reasoning language model for elite men's senior first-team top-division professional association-football performance science.

Its purpose is to reason correctly about what performance-science observations mean, whether they can be compared, what analysis class is scientifically admissible, what evidence applies, which deterministic scientific operations are required, what claim level the evidence supports, and when the correct action is refusal or a request for missing information. It is not an autonomous coach, a generic football chatbot, or a language model with implicit scientific-calculation authority.

The central architecture is:

```text
practitioner / researcher question
        +
football-world context
        +
scientific measurements
        +
provenance/evidence
        ↓
DynamisLM semantic + methodological reasoning
        ↓
typed scientific request / analysis intent
        ↓
registered deterministic Python authority
        ↓
structured scientific result + provenance + claim constraints
        ↓
DynamisLM bounded interpretation / explanation / refusal
```

## Canonical empirical target population

The canonical empirical target population is fixed as:

```text
SEX = MALE
AGE_CLASS = SENIOR
SPORT = ASSOCIATION_FOOTBALL
PROFESSIONAL_STATUS = PROFESSIONAL
SQUAD_LEVEL = FIRST_TEAM
COMPETITION_LEVEL = TOP_DOMESTIC_DIVISION
```

A dataset, cohort, subgroup or athlete observation is `CANONICAL_EMPIRICAL_TARGET` only when every required clause is established from source evidence and the relevant target subgroup is separable.

### Canonical exclusions

The following do not establish V2 canonical empirical population evidence:

- women's football;
- academy, youth or U23 populations;
- university or collegiate athletes;
- amateur or semi-professional players;
- lower-division professional players;
- futsal;
- rugby codes;
- basketball, handball, netball or other sports;
- generic trained adults;
- resistance-trained non-football cohorts;
- mixed cohorts where the exact V2 target subgroup cannot be separated;
- a study using the label `elite` without sufficient evidence of the required senior first-team top-division status.

These populations may still supply explicitly classified `INDIRECT_MEASUREMENT_EVIDENCE` for population-independent or weakly population-dependent mechanics, metrology, signal processing, statistics, device behavior and related method questions. They must not establish canonical football priors, norms, thresholds, meaningful-change criteria or athlete-performance expectations.

### Unresolved population policy

Unknown or ambiguous population status remains unresolved. The system must not infer first-team, top-division or senior status from vague labels such as `elite`, `professional`, `soccer players` or club affiliation alone. When required population metadata are missing, the canonical decision is quarantine / insufficient information rather than silent acceptance.

## Evidence-applicability hierarchy

Evidence applicability is claim-relative and role-relative. A source can be invalid for population priors while remaining valid for a mathematical or measurement-method decision.

### `CANONICAL_EMPIRICAL_TARGET`

Actual observed data from the exact V2 target population. These data may define target-world empirical distributions, cases, longitudinal examples and evaluation contexts subject to source, license and method constraints.

### `DIRECT_TARGET_POPULATION_EVIDENCE`

Scientific evidence directly studying the exact target population, but not necessarily exposing reusable athlete-level canonical data. For example, a top-flight first-team study may inform method applicability even when its raw cohort data are unavailable.

### `INDIRECT_MEASUREMENT_EVIDENCE`

Evidence from non-target populations that can validly inform population-independent or weakly population-dependent questions, including:

- mechanics;
- metrology;
- signal processing;
- event detection;
- estimator mathematics;
- measurement-device behavior;
- reliability methodology;
- statistical methodology;
- uncertainty propagation;
- algorithm validation.

Indirect measurement evidence must never silently establish target-population norms, priors, thresholds, meaningful-change criteria or athlete-performance expectations.

### `NONCANONICAL_CONTEXT_ONLY`

Material useful for terminology, implementation context, software or device documentation, or adversarial testing, but not accepted as empirical target evidence.

### `REJECTED_OR_UNRESOLVED`

Sources whose population, method, provenance, legality, integrity or identity is insufficient for the requested scientific role.

## V2 scientific world

The original twelve performance-test families remain part of DynamisLM. They are no longer the complete scientific world. V2 has three coupled scientific domains.

### A. Performance testing

The twelve performance-test families are:

1. Countermovement Jump — CMJ
2. Drop Jump — DJ
3. Isometric Mid-Thigh Pull — IMTP
4. Squat / Squat Velocity-Based Testing
5. Bench Press / Bench Press Velocity-Based Testing
6. Bench Press Throw
7. Medicine-Ball Throw Testing
8. Short Linear Sprint / Acceleration Testing
9. Maximum Sprint Velocity / High-Speed Sprint Testing
10. 505 Change-of-Direction Testing
11. 30–15 Intermittent Fitness Test
12. Repeated-Sprint Testing / RSA

These families retain the V1 rule:

```text
SAME LABEL != SAME SCIENTIFIC MEASUREMENT IDENTITY
```

Each family may contain multiple scientifically distinct protocols, devices, phases, estimators, metric definitions, selection rules and aggregation methods.

### B. External load / exposure

V2 adds first-class scientific representation for match and training exposure and external-load measurements, including where available and methodologically defined:

- GNSS / GPS;
- optical tracking;
- inertial and vendor-derived measures;
- match/training exposure;
- total distance;
- relative distance;
- maximum/peak speed;
- high-speed-running metrics;
- sprint metrics;
- acceleration/deceleration metrics;
- repeated-high-intensity-effort metrics when definitions are known;
- session/match duration and minutes exposure.

External-load labels do not create universal identities. Threshold values, individualized versus absolute threshold basis, provider, sampling, filtering, dwell rules, segmentation and software/processing semantics are part of identity where material. Vendor-derived metrics may be observed outputs in Knowledge Scope even when their proprietary equation is unavailable; DynamisLM may reason about the output under its exact provider/method identity, but Python must not fabricate authority for a hidden algorithm.

### C. Longitudinal football context

Professional-football context is a first-class scientific domain:

- athlete identity;
- first-team squad identity;
- club/team identity;
- competition identity;
- top-division status;
- season identity;
- training session;
- match session;
- testing session;
- match exposure;
- training exposure;
- microcycle context;
- match-day-relative context;
- repeated multi-device observations;
- multi-source longitudinal history.

Football-world context is separate from measurement identity, but it can determine evidence applicability, grouping, temporal alignment, admissible comparison and interpretation. `MD-1`, `MD+1`, etc. are not free-text labels; where used deterministically, they must be tied to an identified target match and explicit calendar relation.

## Fundamental scientific objects

The V1 observation object remains foundational:

```text
ScientificMeasurementObservation
    = ObservationContext
    + MeasurementIdentity
    + MeasurementResult
    + Provenance
```

A naked label/value pair is never sufficient scientific identity.

V2 adds the surrounding longitudinal world:

```text
CanonicalFootballPopulationIdentity
        +
FootballWorldContext
        +
ScientificMeasurementObservation[]
        +
MultiSourceProvenance
        ↓
LongitudinalAthletePerformanceRecord
```

A longitudinal record is a typed collection of immutable scientific observations whose independent identities and source lineage remain recoverable; it is not an unstructured spreadsheet row dump.

## Measurement identity dimensions

A scientific measurement identity may include, when material:

- construct;
- scientific domain;
- test family / exposure family;
- protocol;
- measurand;
- metric definition and aliases;
- device / measuring system / provider;
- raw signal / source artifact / channel;
- sampling characteristics;
- calibration/reference state;
- event definitions;
- phase definitions;
- estimator / algorithm / equation;
- method parameters;
- filtering / smoothing;
- integration / differentiation;
- units;
- sign convention;
- normalization;
- thresholds and threshold basis;
- trial/rep/event selection;
- aggregation;
- session segmentation;
- software / processing / registry version;
- hardware / firmware version where material;
- football-world context where material to interpretation;
- evidence / uncertainty / quality context.

Same label does not imply same identity. Different identities may become comparable only through an explicit registered comparability rule, transformation or validated bridge.

## Three-scope authority model

```text
KNOWLEDGE_SCOPE
!=
COMPUTATIONAL_AUTHORITY_SCOPE
!=
CLAIM_AUTHORITY_SCOPE
```

### Knowledge Scope

What DynamisLM must understand, including target-world football performance-science terminology, test protocols and methods, external-load concepts, longitudinal football context, vendor-specific and proprietary outputs, scientifically limited measures, and evidence applicability.

Knowledge does not imply computational or claim authority.

### Computational Authority Scope

What the registered deterministic engine can calculate, validate, transform or statistically analyze from sufficient inputs under an explicit registered method.

### Claim Authority Scope

What may be communicated given measurement identity, source provenance, population applicability, comparability, data adequacy, uncertainty/measurement error, analysis design, temporal structure, causal level and any explicit decision criterion.

## Language-model authority

DynamisLM may own:

- terminology and alias resolution;
- football-context extraction;
- test, construct and exposure resolution;
- protocol understanding;
- measurement, measurand and metric identity reasoning;
- direct/derived/model-estimate/inference classification;
- provider, device, method and software reasoning;
- missing-metadata detection;
- canonical-population ambiguity recognition;
- evidence-scope reasoning;
- registered analysis-class proposal;
- interpretation of structured deterministic results;
- within-vs-between reasoning;
- cross-test and cross-source reasoning;
- causal-language discipline;
- evidence-grounded explanation;
- granular scientific refusal;
- deciding when deeper reasoning or tool use is needed.

The LM does not gain accepted numerical authority merely because the underlying model can perform arithmetic or produce a convincing chain of thought.

## Deterministic Python authority

```text
ALL_ACCEPTED_SYSTEM_GENERATED_NUMERICAL_SCIENCE = DETERMINISTIC_PYTHON_AUTHORITY
```

Registered Python owns all accepted system-generated numerical operations, including:

- equations and arithmetic;
- units and conversions;
- signal processing and filtering;
- event and phase detection;
- integration and differentiation;
- normalization;
- threshold application;
- external-load metric derivation from available reproducible inputs;
- trial, repetition and event selection when algorithmic;
- aggregation;
- metric derivation;
- reliability;
- measurement error;
- agreement;
- uncertainty;
- confidence intervals;
- longitudinal descriptive statistics;
- within-athlete baseline/reference computations;
- repeated-measures analyses;
- mixed-effects and longitudinal models;
- meta-analysis;
- canonical population/source validation;
- registered comparability adjudication;
- registered claim-prerequisite validation;
- deterministic validation and refusal.

If an operation is not registered, or its prerequisites are unavailable, the correct result is an explicit refusal such as `COMPUTATION_NOT_REGISTERED` or `INSUFFICIENT_INFORMATION`.

## Numerical provenance and scientific role

The V1 value-origin taxonomy remains:

- `DIRECT_MEASUREMENT`;
- `DERIVED_MECHANICAL_QUANTITY`;
- `MODEL_ESTIMATE`.

Scientific role remains independently classified, including:

- `PERFORMANCE_OUTCOME`;
- `LATENT_CONSTRUCT_INTERPRETATION`;
- `PHYSIOLOGICAL_INFERENCE`.

These are separate axes. A performance outcome may be direct, derived or estimated. Provider/vendor-derived outputs must not be mislabeled as DynamisLM-computed values when the proprietary computation is not owned by the system.

## Longitudinal claim ladder

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

The system may not skip levels:

```text
NUMERICAL_CHANGE
!=
COMPARABLE_CHANGE
!=
CHANGE_BEYOND_MEASUREMENT_ERROR
!=
PRACTICAL_MEANINGFULNESS
!=
FATIGUE / READINESS / INJURY
```

No universal football-wide meaningful-change threshold, readiness score or fatigue threshold is authorized at project level.

## Within-athlete and between-athlete distinction

```text
BETWEEN_ATHLETE_ASSOCIATION
DOES NOT BY ITSELF ESTABLISH
WITHIN_ATHLETE_LONGITUDINAL_ASSOCIATION

WITHIN_ATHLETE_ASSOCIATION
DOES NOT BY ITSELF ESTABLISH
CAUSAL_EFFECT
```

The requested estimand and data-generating structure must be explicit. Squad-level distributions, between-player norms and top-flight cohort averages do not automatically create an individualized longitudinal decision rule for a player.

## Causal hierarchy

The causal levels remain:

- `LEVEL_0 — OBSERVATION`;
- `LEVEL_1 — DESCRIPTIVE_CHANGE`;
- `LEVEL_2 — ASSOCIATION`;
- `LEVEL_3 — TEMPORAL_ASSOCIATION`;
- `LEVEL_4 — MECHANISTIC_HYPOTHESIS`;
- `LEVEL_5 — CAUSAL_EVIDENCE`.

Routine monitoring data must not silently become causal evidence. Prediction remains orthogonal to causal level.

## Scientific refusal architecture

Refusal is claim-specific rather than a blanket rejection of data. High-level refusal classes include:

- `IDENTITY_UNRESOLVED`;
- `POPULATION_SCOPE_UNRESOLVED`;
- `CANONICAL_ELIGIBILITY_FAILED`;
- `COMPARABILITY_UNESTABLISHED`;
- `EVIDENCE_SCOPE_UNSUPPORTED`;
- `DATA_ADEQUACY_INSUFFICIENT`;
- `ANALYSIS_DESIGN_MISMATCH`;
- `UNCERTAINTY_LIMITS_CLAIM`;
- `CAUSAL_IDENTIFICATION_UNSUPPORTED`;
- `COMPUTATION_NOT_REGISTERED`.

A refused comparison does not invalidate the independent observations themselves. The refusal result should preserve the blocked claim, reason codes, missing information and what can still be safely described.

## Canonical-data rules

Canonical empirical data represent the target world. They must not be treated as unstructured language-model pretraining text by default.

```text
source dataset
    ↓
population/license/schema qualification
    ↓
immutable source artifact + provenance
    ↓
canonical football record
    ↓
registered deterministic engine
    ↓
verified scientific cases / references / evals
    ↓
model training or evaluation artifacts where licensed and authorized
```

Synthetic or deterministically generated records must never masquerade as observed athlete data. Their origin must be explicit and reproducible. Missingness must be preserved; silent interpolation, imputation or synthetic filling is not authorized unless a specific registered method owns that transformation and its scientific role is clear.

## Non-goals

DynamisLM V2 is not:

- an autonomous coach;
- an automatic training-program generator;
- a readiness-score generator;
- a fatigue-diagnosis engine;
- an injury predictor;
- a diagnostic, rehabilitation or return-to-play authority;
- a nutrition model;
- a tactical-analysis model;
- a sport-psychology model;
- a women's-football model;
- an academy-development model;
- a lower-division generalization model;
- an unrestricted sports-science chatbot;
- an LLM with authority to invent scientific numbers;
- a causal engine that promotes routine observational association into causal effect.

Future scope expansion requires an explicit new project-level decision. It does not happen because a convenient dataset becomes available.

## Retained V1 invariants

V2 retains:

- `ScientificMeasurementObservation` discipline;
- measurement-identity architecture;
- provenance and lineage requirements;
- `same-label != same-scientific-identity`;
- `Knowledge Scope != Computational Authority != Claim Authority`;
- `correlation != agreement`;
- between-athlete versus within-athlete separation;
- within-athlete association versus causal-effect separation;
- derived/estimated versus directly measured separation;
- performance change versus physiological mechanism separation;
- granular scientific refusal;
- evaluation-before-training;
- pull-based scientific implementation.

The locked invariant set is:

```text
METRIC_LABEL != SCIENTIFIC_MEASUREMENT_IDENTITY
CORRELATION != AGREEMENT
BETWEEN_ATHLETE_ASSOCIATION != WITHIN_ATHLETE_LONGITUDINAL_ASSOCIATION
WITHIN_ATHLETE_ASSOCIATION != CAUSAL_EFFECT
DERIVED_OR_ESTIMATED != DIRECTLY_MEASURED
PERFORMANCE_CHANGE != PHYSIOLOGICAL_MECHANISM
CANONICAL_POPULATION_EVIDENCE != INDIRECT_METHOD_EVIDENCE
FOOTBALL_CONTEXT != MEASUREMENT_IDENTITY
VENDOR_OUTPUT != DYNAMISLM_COMPUTATIONAL_AUTHORITY
```

## Implementation authority sequence

The V2 implementation sequence is:

```text
RES-59  Constitution V2
   ↓
RES-60  typed population/source gate
   ↓
RES-61  football-world ontology
   ↓
RES-62  multi-source longitudinal record
   ↓
RES-63  canonical dataset qualification
   ↓
RES-64→70 deterministic scientific-engine expansion
   ↓
RES-71  SCIENTIFIC_ENGINE_GATE
```

Until RES-71 records:

```text
SCIENTIFIC_ENGINE_GATE = PASS
```

the following are prohibited:

- model-runtime or inference integration;
- baseline inference benchmarking;
- paid GPU qualification;
- CPT/DAPT;
- SFT/PEFT;
- RLVR/GRPO;
- scaling experiments.

Candidate-model research notes may continue as planning. Operational model work is downstream of scientific truth readiness.

## V1/V2 supersession map

### Superseded from V1

- broad target population `TRAINED_OR_COMPETITIVE_ADULT_TEAM_SPORT_ATHLETES_NON_CLINICAL`;
- authorization of soccer/futsal/rugby/basketball/handball/netball as co-equal target populations;
- interpretation of the twelve test families as the entire scientific world.

### Retained from V1

- fundamental observation object;
- measurement-identity architecture;
- provenance requirement;
- two-axis classification;
- three-scope authority model;
- language-model versus deterministic-Python authority split;
- longitudinal claim ladder;
- within-vs-between distinction;
- correlation versus agreement distinction;
- causal hierarchy;
- granular refusal;
- evaluation-before-training principle;
- pull-based scientific implementation workflow.

V1 remains byte-for-byte historical provenance in this repository. Existing RES-34→RES-50 decision records and CMJ scientific authority remain valid unless a later decision explicitly supersedes a test-specific method.

## Constitution acceptance criteria

This Constitution is correctly implemented only when:

1. no current DynamisLM artifact can reasonably be read as authorizing non-target populations as canonical empirical data;
2. the football world includes performance testing, external load/exposure and longitudinal football context;
3. canonical eligibility is implemented as typed deterministic authority rather than an informal note;
4. the scientific engine owns all accepted system-generated numerical science;
5. indirect evidence remains usable for appropriate method questions without contaminating target-population empirical priors;
6. existing CMJ work remains valid unless explicitly superseded by a new method-level decision;
7. model/GPU work remains blocked until the scientific-engine qualification gate passes.
