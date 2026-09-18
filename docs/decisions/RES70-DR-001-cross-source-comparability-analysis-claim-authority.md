# RES-70-DR-001 — Cross-source comparability, bridge authority, analysis capability, and claim authority

## Status

`FROZEN / DESIGN ONLY`

`MISSION=RES-70-SCIENTIFIC-DESIGN-001`

`BASE_MAIN=83041cd3e69e0dc0947c181b19effd5402bd5a38`

`CONSTITUTION_VERSION=2.0.0`

`SERIALIZATION_VERSION=3` — unchanged

`PRODUCTION_IMPLEMENTATION_AUTHORIZED=NO`

This record freezes the scientific and software design for RES-70. It does
not implement production code, numerical operations, bridges, tests, model
runtime behavior, or LM tool calling. A future implementation mission must
realize this record without weakening the sealed RES-34→69 contracts.

## Decision summary

RES-70 uses four deterministic authority layers:

```text
typed request
    ↓
exact identity/context/provenance revalidation
    ↓
pairwise cross-source comparability and optional registered bridge execution
    ↓
registered analysis-capability prerequisite validation
    ↓
registered deterministic analysis result
    ↓
two-axis claim-authority validation and evidence applicability
    ↓
structured authorization or claim-specific refusal
```

The design freezes the following:

| Contract | Status | Frozen decision |
| --- | --- | --- |
| Cross-source comparability | FROZEN | Reuse the existing six states; add an additive cross-source wrapper, material-dimension findings, pairwise-only evaluation, and no transitive closure. |
| Bridge/transformation authority | FROZEN | A registered bridge declares an operation and applicability; numerical transformations must execute and emit a new provenance-bound result before they can support comparison. |
| Analysis capability registry | FROZEN | The caller proposes an analysis class; Python resolves the canonical capability entry and either authorizes it or returns a refusal. |
| Claim authority | FROZEN | Use two orthogonal ordered axes: measurement/change evidence and relationship/causal inference. Prediction remains separate. |
| Evidence applicability | FROZEN | Method validity, source quality, population relevance, contextual relevance, and statistical adequacy remain separate typed dimensions; no confidence score. |
| Level of analysis | FROZEN | Every analysis carries an explicit unit/cluster/estimand identity; pooled observations never silently become independent subjects. |
| Refusal taxonomy | FROZEN | Reuse generic `RefusalResult` and add only RES-70-specific granular reason codes. |
| LM boundary | FROZEN | The LM may propose and request; deterministic Python owns registration, prerequisites, transformations, calculations, and claim promotion/refusal. |

## Authority provenance

Every rule in this record is classified so repository facts, external
methodological support, and RES-70 design choices are not conflated.

### Repository facts

The current merged repository establishes:

- `ScientificMeasurementObservation` is
  `ObservationContext + MeasurementIdentity + MeasurementResult + Provenance`.
- `MeasurementIdentity` contains semantic, acquisition, processing, and version
  identity; the result value is not part of identity.
- `ComparabilityState` already contains
  `COMPARABLE`, `COMPARABLE_WITH_CONDITIONS`, `REQUIRES_TRANSFORMATION`,
  `BRIDGE_VALIDATION_REQUIRED`, `NOT_COMPARABLE`, and
  `INSUFFICIENT_INFORMATION`.
- `ComparabilityRequest`/`ComparabilityResult` are claim-relative, immutable,
  V3-serializable contracts. `TransformationRequest` is explicitly a request,
  not a verdict.
- Family-specific comparators already return the generic result envelope:
  CMJ acquisition/derived/event/phase/mechanics/metric/session/jump-height,
  external load, field testing, VBT, Drop Jump, Bench Press Throw, and
  Medicine-Ball Throw each retain family-owned material identity rules.
- RES-62 owns exact longitudinal entries, immutable analysis inputs, explicit
  temporal scope, source qualification bindings, missingness, and additive
  provenance graphs.
- RES-69 owns deterministic statistical support, scale authority,
  reliability-design authority, method-comparison authority, operation
  dispositions, result envelopes, and claim-specific refusal construction.
- RES-60 owns canonical population/source decisions and explicit V2 evidence
  applicability. RES-61 owns football-world context and match/training/testing
  placement. Neither is replaced by RES-70.
- Serialization V3, canonical hashes, immutable tuples, registry references,
  and append-only reprocessing are existing authority. `serialization.py` is
  not a RES-70 implementation target.

### Literature-supported methodological rules

The evidence table at the end records the targeted sources. Their bounded
consequences are:

- correlation describes association, not agreement or interchangeability;
- cross-group/time comparison requires evidence that the measurement has the
  same meaning under the intended comparison, not merely a common label;
- repeated observations have an experimental/observational unit and dependence
  structure that must be represented in the analysis;
- within-person and between-person effects are distinct estimands;
- random measurement error, systematic trial effects, and retest association
  are different reliability quantities;
- statistical significance does not itself establish effect magnitude or
  practical importance;
- causal and transportability claims require an explicit target, design,
  estimand, assumptions, and evidence-applicability argument.

### RES-70 design choices

RES-70 operationalizes those rules conservatively for this repository:

- comparability is pairwise and claim-relative;
- registry keys are semantic and never observation-instance keys;
- bridge declarations cannot alter values or provenance;
- only an executed registered transformation can supply transformed numerical
  support;
- evidence applicability is a vector of typed judgments, not a scalar score;
- claim authority is a product of two ordered axes, not one universal ladder;
- no deferred RES-69 method is made executable by registering a prerequisite
  schema;
- an unsupported stronger claim produces a refusal while preserving safe lower
  descriptions.

## Current repository reconnaissance and reuse boundary

| Concern | Existing authority | RES-70 treatment |
| --- | --- | --- |
| Generic comparability | `src/dynamislm/comparability/models.py`, `authority.py` | Reuse states, request/result invariants, deterministic rule dispatch, and transformation-request semantics. Additive wrappers only; no historical hash/wire mutation. |
| Family comparability | `src/dynamislm/measurement/**/comparability.py`, `src/dynamislm/external_load/comparability.py` | Consume family results as leaf authority. Do not duplicate CMJ, external-load, field-test, strength, DJ, BPT, or MBT rules in RES-70. |
| Longitudinal support | `src/dynamislm/longitudinal/models.py`, `record.py`, `lineage.py`, `statistics/support.py` | Reuse exact entry/input/support hashes, explicit exclusions, no-imputation policy, and complete source graphs. |
| RES-69 statistical authority | `src/dynamislm/longitudinal/statistics/models.py`, `registry.py`, `validation.py` | Reuse `StatisticalSupport`, `StatisticalComparabilityEvidence`, `StatisticalAnalysisRun`, `StatisticalResult`, scale/reliability/method-comparison authority, and operation disposition. Add an upper capability gate; do not implement deferred methods. |
| Measurement identity | `src/dynamislm/measurement/identity.py`, `observation.py`, `result.py`, `taxonomy.py` | Treat labels and values as non-authoritative shortcuts. Use full typed identity and independent value-origin/scientific-role axes. |
| Population/source qualification | `src/dynamislm/population/`, `src/dynamislm/evidence/` | Reuse canonical decisions and V2 applicability. Add claim-relative aggregation of applicability axes without replacing RES-60 decisions. |
| Football context | `src/dynamislm/football/` | Reuse typed match/training/testing context and exposure. Context may be claim-relevant without becoming measurement identity. |
| Refusal | `src/dynamislm/refusal/models.py`, RES-69 validation | Reuse `RefusalResult`, high-level classes, observation preservation, and safe-description behavior. Add only RES-70-local granular codes. |
| Serialization/public exports | `src/dynamislm/serialization.py`, package `__init__.py` files | Register new types with V3 and export them additively. Do not change `SERIALIZATION_VERSION` or existing hashes. |
| Repository policy | `scripts/repository_policy.py`, `scripts/ci.sh`, `tests/test_repository_policy.py` | Future implementation must preserve synthetic-fixture-only policy and QA mutation checks. This mission adds documentation only. |

The Codebase Memory architecture and call-path review identified
`ComparabilityAuthority.adjudicate`, RES-69
`validate_comparable_entries`, RES-69 `build_analysis_run`, and the RES-62
provenance builders as the main downstream seams. RES-70 therefore composes
above them rather than introducing a parallel observation, support, or
provenance model.

## 1. Cross-source comparability

### 1.1 Material dimensions

The RES-70 dimension vocabulary is typed. A caller may request attention to a
dimension, but cannot remove a dimension that the registered rule marks as
material for the claim.

```text
CONSTRUCT
TEST_FAMILY
MEASURAND
METRIC_DEFINITION
PROTOCOL
EVENT_DEFINITION
PHASE_DEFINITION
UNIT
NORMALIZATION
ESTIMATOR
REGISTERED_PROCESSING_OPERATION
PROCESSING_PARAMETERS
FILTERING_SMOOTHING_RESAMPLING
SAMPLING_AND_TIMEBASE
CALIBRATION_REFERENCE
DEVICE_MEASURING_SYSTEM
PROVIDER
SOFTWARE_ALGORITHM_VERSION
HARDWARE_FIRMWARE_VERSION
SIGN_CONVENTION_AND_REFERENCE_FRAME
THRESHOLD_IDENTITY
TRIAL_SELECTION_POLICY
AGGREGATION_POLICY
SESSION_SEGMENTATION
ACQUISITION_CONTEXT
EXPOSURE_CONTEXT_MATCH_OR_TRAINING
VALUE_ORIGIN
UNCERTAINTY_ERROR_MODEL
POPULATION_APPLICABILITY
EVIDENCE_APPLICABILITY
```

`FOOTBALL_WORLD_CONTEXT` is not copied into `MeasurementIdentity`. It is
evaluated as a separate claim-relevant context dimension. For example, a
match-versus-training comparison may be scientifically blocked for a match
claim even when both observations have identical measurement identities.

The following are hard rules:

```text
same label                  != same identity
same unit                   != same measurand
same number                 != same observation
unit conversion             != method harmonization
valid in isolation          != interchangeable
high correlation            != agreement
same athlete                != same context
same context                != same method
```

Display labels, aliases, provider column names, and caller descriptions may be
diagnostic metadata only. They cannot satisfy an identity comparison.

### 1.2 Typed request and decision

The future additive cross-source contract is:

```text
ObservationAuthorityReference {
    observation_id
    observation_hash
    identity_hash
    result_hash
    context_hash
    provenance_hash
}

CrossSourceComparabilityRequest {
    request_id
    left_observation: ObservationAuthorityReference
    right_observation: ObservationAuthorityReference
    claim_intent: registered claim/analysis intent reference
    requested_transformations: TransformationRequest[]
    requested_dimensions: ComparabilityDimension[]  # advisory only
    claim_context: typed match/training/population context
}

CrossSourceComparabilityDecision {
    decision_id
    request_hash
    state: ComparabilityState
    dimension_findings[]
    conditions[]
    transformations_required[]
    bridge_application_reference: optional
    rule_reference
    evidence_references[]
    registry_version
    registry_hash
    observation/provenance references
}
```

`ObservationAuthorityReference` is an exact input/provenance reference; it is
not a semantic registry key. The validator must resolve the referenced
observations and recompute every supplied hash before deciding.

`dimension_findings` retain, for each material dimension, one of
`MATCH`, `MISMATCH`, `UNKNOWN`, `BRIDGED`, or `NOT_APPLICABLE`, together with
the stable semantic IDs/hashes and the rule-derived reason code. A human label
is never the finding value.

The existing `ComparabilityRequest` and `ComparabilityResult` remain valid
leaf contracts. The RES-70 decision composes them or adapts a family result;
it does not change their serialized shape.

### 1.3 State semantics

| State | Meaning in RES-70 | Numerical support allowed? |
| --- | --- | --- |
| `COMPARABLE` | All claim-relevant identity/context dimensions are resolved and directly compatible under one registered deterministic rule. | Yes, subject to the separate analysis/claim prerequisites. |
| `COMPARABLE_WITH_CONDITIONS` | A registered bridge or conditional rule establishes compatibility for this named claim, and all conditions are explicit and satisfied. | Yes, with the conditions and bridge evidence bound to the support. |
| `REQUIRES_TRANSFORMATION` | A registered deterministic transformation is named or required, but it has not yet been executed and bound to output provenance. | No transformed support; return the request/result state only. |
| `BRIDGE_VALIDATION_REQUIRED` | A material identity/method/device/context difference exists and no applicable registered bridge has established claim-relative compatibility. | No cross-source comparison claim. Independent observations remain describable. |
| `NOT_COMPARABLE` | The construct, measurand, metric meaning, protocol, or other irreconcilable claim dimension is incompatible. | No comparison of the requested claim. |
| `INSUFFICIENT_INFORMATION` | Required metadata, provenance, evidence applicability, or registry authority is absent or conflicting. | No claim; request missing information or a registered rule. |

Direct comparability means `COMPARABLE`. A bridge-mediated comparison is not
silently relabelled as direct comparability; it is at least
`COMPARABLE_WITH_CONDITIONS`, with the bridge and its applicability conditions
in the decision. A bridge can be valid for one claim and invalid for another.

### 1.4 Pairwise-only, non-transitive evaluation

RES-70 V1 does not infer a relation by graph closure:

```text
A ~ B and B ~ C  does not imply  A ~ C
```

For an analysis involving more than two observations, Python evaluates every
pair required by the registered analysis capability or consumes an exact
multi-observation rule. A `CrossSourceComparabilityMatrix` may store pairwise
decisions, but it has no transitive `reachable => comparable` operation.

Registry/bridge semantic keys exclude observation-instance IDs, athlete IDs,
timestamps, session IDs, source-artifact IDs, acquisition-instance IDs,
processing-run IDs, and result-instance IDs. Exact decisions and provenance
must include those instance references. This separation prevents both
observation-instance leakage into reusable authority and loss of exact source
lineage.

### 1.5 Family adapter boundary

Family-specific comparators remain the first authority for family-owned
dimensions. A RES-70 adapter may:

1. construct the existing family request from exact typed observations;
2. invoke the registered family rule;
3. preserve its result, reasons, conditions, evidence, and rule reference; and
4. add claim-level context/population/evidence findings that the family rule
   does not own.

It may not reinterpret a family `BRIDGE_VALIDATION_REQUIRED` as comparable,
merge family metric labels, or invent a bridge. The existing generic
`ComparabilityAuthority` remains the no-rule/one-rule deterministic dispatch
primitive.

## 2. Bridge and transformation authority

### 2.1 Registered bridge contract

The future immutable `BridgeRegistration` contains:

```text
BridgeRegistration {
    bridge_reference: RegistryReference(object_type="comparability-bridge")
    source_semantic_key: complete identity key, no observation instances
    target_semantic_key: complete identity key, no observation instances
    claim_scope: exact claim/analysis intent references
    bridge_mode: DECLARATIVE_EQUIVALENCE | NUMERICAL_TRANSFORMATION
    transformation_operation: registered deterministic operation reference
    source_units: exact UnitReference tuple
    target_units: exact UnitReference tuple
    fixed_parameters: canonical MetadataEntry tuple
    domain_constraints: registered typed range/boundary contract
    applicability_conditions: registered typed context/evidence conditions
    method_version: registry/method reference and version
    evidence_references: exact EvidenceReference tuple
    evidence_applicability: claim-relative applicability references
    uncertainty_model: registered propagation/limitation reference
    invertibility: EXACT | APPROXIMATE | NON_INVERTIBLE_LOSSY
    lossiness_description: required for non-exact modes
    provenance_rule: registered lineage/provenance method reference
    registry_version
    bridge_hash
}
```

The bridge hash is derived from all material fields. Duplicate source/target
keys, duplicate stable references, conflicting versions, absent evidence, or
an operation that is not registered as deterministic fail registry integrity.
The canonical production bridge registry is the only production authority;
caller-provided registries and synthetic test bridges cannot authorize public
claims.

### 2.2 Declaration is not execution

The following invariant is explicit:

```text
DECLARED_COMPATIBILITY != EXECUTED_TRANSFORMATION
```

`TransformationRequest` remains only a request. It cannot change a value,
unit, identity, comparability state, or provenance. `BridgeRegistration`
declares what a registered operation is allowed to do; it does not execute it.

For `NUMERICAL_TRANSFORMATION`, the only claim-eligible path is:

```text
BridgeRequest
    → resolve canonical BridgeRegistration
    → validate source semantic key, domain, units, parameters, and conditions
    → execute the registered deterministic operation
    → create a new derived observation/result
    → create a new ProcessingRun and explicit lineage edges
    → bind uncertainty/lossiness output
    → re-run cross-source comparability on the transformed observation
```

The source observation is immutable. The transformed value receives a new
observation/result identity and `DYNAMISLM_DERIVED`/appropriate derived origin
classification. The output identity binds source observation hash, bridge
reference/hash, operation/version, parameters, software version, target
identity, and uncertainty policy. Re-running the same source with changed
bridge version or parameters produces a distinct output; it never overwrites
the previous one.

For `DECLARATIVE_EQUIVALENCE`, no numeric value is changed. The bridge may
support `COMPARABLE_WITH_CONDITIONS` only when its evidence and applicability
conditions are resolved for the named claim. It cannot be presented as an
executed transformation or as direct equality.

No caller field named `bridge_valid`, `force_comparable`, `conversion_applied`,
`transformed`, `agreement_ok`, or equivalent is accepted as authority. The
validator recomputes execution status and all hashes.

### 2.3 Uncertainty and lossiness

A numerical bridge must either execute a registered uncertainty propagation
method or explicitly emit a registered limited/unknown uncertainty status.
Unknown or material unpropagated uncertainty blocks every claim requiring
measurement-error comparison or practical meaning. A lossy bridge must state
the loss and its claim conditions; it cannot be used as a reversible identity
alias. A unit-only conversion remains a method operation, not proof of method
equivalence.

The existing RES-64 unit operations may be reused as bridge operations only
through this execution boundary when transformed values are used in a later
analysis. Existing family comparison behavior is not rewritten in this
design.

## 3. Analysis capability and prerequisite validation

### 3.1 Analysis classes

The RES-70 capability registry covers at least:

```text
SCALAR_ABSOLUTE_CHANGE
SCALAR_RELATIVE_CHANGE
SCALAR_LOG_CHANGE
BASELINE_REFERENCE_WINDOW_DEVIATION
RELIABILITY_RANDOM_ERROR_COMPARISON
METHOD_AGREEMENT_SUMMARY
WITHIN_ATHLETE_ASSOCIATION
BETWEEN_ATHLETE_ASSOCIATION
REPEATED_MEASURES_ANALYSIS
MIXED_EFFECTS_ANALYSIS
CROSS_TEST_ASSOCIATION
```

`METHOD_AGREEMENT_SUMMARY` is deliberately named as a summary operation. A
summary of B-minus-A bias and SD is not an automatic interchangeability or
agreement-acceptability claim.

### 3.2 Request, registry, and authorization contracts

```text
AnalysisLevelIdentity {
    unit_of_analysis: TRIAL | TEST_INSTANCE | SESSION | ATHLETE | GROUP
    estimand_level: WITHIN_ATHLETE | BETWEEN_ATHLETE | JOINT_MULTILEVEL | GROUP
    subject_key: typed key
    clustering_keys: typed key tuple
    grouping_keys: typed key tuple
    temporal_order_policy: registered reference
    pooling_policy: registered reference
}

AnalysisCapability {
    capability_reference
    analysis_class
    registered_operation_reference: optional RES-69/future operation
    estimator_reference: optional
    disposition: IMPLEMENTED | REPRESENT_ONLY | DEFERRED | REJECTED
    required_support_shape
    required_identity_dimensions
    required_comparability_states
    required_bridge_execution
    required_level_of_analysis
    required_statistical_authority
    required_evidence_axes
    required_context
    output_claim_floor
    registry_version
    capability_hash
}

AnalysisAuthorizationRequest {
    request_id
    analysis_class
    exact StatisticalSupport or exact support snapshot reference
    exact identities/hashes and comparability decisions
    requested AnalysisLevelIdentity
    evidence applicability bundle
    football/context constraints
    requested parameters (only registered parameter names/types)
}

AnalysisAuthorization {
    authorization_id
    status: AUTHORIZED | REFUSED
    capability_reference/hash
    operation/estimator references
    support/input/identity/comparability hashes
    resolved level-of-analysis identity
    registry/software versions
    reason_codes and missing_information
    safe lower-level descriptions
    authorization_hash
}
```

An authorization is a derived record. Public validation recomputes it from
the canonical registry and exact input hashes; a caller cannot construct an
authoritative `AUTHORIZED` value by setting a boolean or copying a registry
reference.

The capability registry is above, not a replacement for, the RES-69 operation
registry. An operation may be registered as implemented and still be refused
because support, scale, reliability, level, comparability, or applicability
authority is absent.

### 3.3 Prerequisite matrix

| Analysis class | Structural prerequisites | Existing V1 production disposition |
| --- | --- | --- |
| Scalar absolute change | Exactly two valid scalar entries; explicit baseline/follow-up temporal order; exact target identity and unit; required pairwise comparability evidence for a comparable-change claim; no hidden conversion. | RES-69 arithmetic operation exists. RES-70 may authorize only after the exact support/comparability gates pass. |
| Scalar relative change | Absolute-change prerequisites; canonical production scale semantics; nonzero denominator; registered ratio-scale policy. | Operation exists, but the production scale registry has zero keys, so public production authorization refuses until an owning scale authority is registered. |
| Scalar log change | Absolute-change prerequisites; canonical strictly-positive ratio-scale semantics; positive values; registered log estimator. | Operation exists, but the current production scale registry is empty; refuse production claims. |
| Baseline/reference-window deviation | One current entry; explicit prior reference entries; current excluded from reference; at least two reference entries; positive reference SD; exact window/exclusion policy; comparable target support. | RES-69 operation exists and is bounded to descriptive deviation, not meaningfulness or readiness. |
| Reliability/random-error comparison | Source-bound reliability design authority; exact replicate/subject mapping; stable underlying quantity declaration; systematic trial-effect assessment; exact error scale; balanced/complete support; independent subject units. | RES-69 numerical operation exists, but the canonical production reliability-assumption registry is empty; public reliability authorization refuses until an owner supplies a declaration. |
| Method-agreement summary | Source-bound method-comparison design authority; same target construct/measurand; exact pairings; one pair per independent subject; fixed B-minus-A sign; exact common units; no hidden transformation. | RES-69 narrow bias/SD summary is implemented. It does not authorize LoA, interchangeability, equivalence, or acceptability. |
| Within-athlete association | Repeated observations for the same athlete; explicit time/occasion identity; within-person estimand; repeated-measures operation and design authority; no between-person substitution. | RES-69 repeated-measures correlation is deferred; refuse `COMPUTATION_NOT_REGISTERED`. |
| Between-athlete association | Independent athlete units; explicit one-unit-per-athlete/aggregation policy; cross-sectional estimand; population/source applicability; registered association operation. | No RES-69 operation authorizes this class; refuse. |
| Repeated-measures analysis | Repeated observations, exact clustering/occasion structure, missingness policy, temporal support, registered model/estimator and design authority. | Deferred in RES-69; RES-70 registers prerequisites only and does not implement it. |
| Mixed-effects analysis | Explicit fixed/random effects, nesting, grouping, covariance/estimator, convergence/adequacy policy, level identity, and source/design authority. | `MIXED_EFFECTS` is deferred in RES-69; refuse. |
| Cross-test association | Two distinct registered test/construct identities, explicit temporal/context alignment or lag policy, athlete/occasion structure, cross-test association operation, and evidence applicability. | No cross-test association operation is registered; refuse. |

The matrix is intentionally asymmetric: an exact scalar change may be
computable while the stronger comparable, error-relative, or practical claim
is blocked. A deferred operation never becomes executable merely because its
prerequisites are represented.

### 3.4 Capability decision flow

Python evaluates, in order:

1. request shape and canonical support/hash integrity;
2. operation/capability registry integrity and disposition;
3. exact observation/result/identity/provenance resolution;
4. source/population/football-context qualification;
5. pairwise comparability and bridge-execution requirements;
6. level-of-analysis and independence/cluster requirements;
7. scale, reliability, method-comparison, or other RES-69 authority;
8. minimum support shape and explicit temporal/missingness policy; and
9. software/registry/version consistency.

The first unmet prerequisite is the primary refusal cause. All deterministically
discovered material causes may be retained in stable canonical order. If any
gate fails, no registered operation is dispatched through the RES-70 analysis
boundary.

## 4. Claim authority

### 4.1 Two orthogonal axes

RES-70 does not place every claim on one line. It uses a product of two ordered
axes plus an optional prediction axis:

```text
Measurement/change axis:
OBSERVED_VALUE
  < NUMERICAL_CHANGE
  < COMPARABLE_CHANGE
  < CHANGE_RELATIVE_TO_MEASUREMENT_ERROR
  < PRACTICAL_OR_DECISION_MEANINGFULNESS

Relationship/causal axis:
OBSERVATION
  < DESCRIPTIVE_CHANGE
  < ASSOCIATION
  < TEMPORAL_ASSOCIATION
  < MECHANISTIC_HYPOTHESIS
  < CAUSAL_EVIDENCE

Prediction: separate registered predictive-validity contract; not a causal level.
```

The two base labels are intentionally not equated: `OBSERVED_VALUE` is a
measurement-result claim, while `OBSERVATION` is a relationship/causal-axis
base description. A claim can request only one axis, both axes, or neither
when it asks for identity/provenance description.

The ordered axes form a partial order, not a single ladder. For example,
`CHANGE_RELATIVE_TO_MEASUREMENT_ERROR` does not imply `ASSOCIATION`, and
`TEMPORAL_ASSOCIATION` does not imply `PRACTICAL_OR_DECISION_MEANINGFULNESS`.

### 4.2 Typed claim contracts

```text
ClaimIntent {
    claim_reference
    measurement_level: optional MeasurementClaimLevel
    relationship_level: optional RelationshipClaimLevel
    predictive_intent: optional registered prediction intent
    target: INDIVIDUAL | ATHLETE_WITHIN | ATHLETE_BETWEEN | GROUP | POPULATION
    analysis_reference: optional AnalysisAuthorization reference
    evidence_applicability_reference
    decision_criterion_reference: optional
}

ClaimAuthorityResult {
    decision_id
    status: AUTHORIZED | PARTIALLY_AUTHORIZED | REFUSED
    allowed_measurement_levels[]
    allowed_relationship_levels[]
    prediction_status
    blocked_claims[]
    first_blocking_prerequisite
    reason_codes[]
    missing_information[]
    safe_descriptions[]
    support/analysis/comparability/bridge/evidence hashes
    registry/software versions
    decision_hash
}
```

`PARTIALLY_AUTHORIZED` means a requested strong claim is blocked while a
weaker claim about the same valid observation/result remains authorized. It is
not permission to phrase the blocked claim indirectly.

### 4.3 Exact claim prerequisites

| Claim level | Required evidence/authority | Explicit non-implication |
| --- | --- | --- |
| `OBSERVED_VALUE` | Exact valid observation, complete identity, result status/quality, source/provenance integrity. | Does not imply change, comparability, error-relative change, or mechanism. |
| `NUMERICAL_CHANGE` | Exact registered change operation; valid scalar support; exact units or an executed registered conversion; declared baseline/follow-up or reference window. | Does not imply comparable scientific change. |
| `COMPARABLE_CHANGE` | Numerical-change authority plus affirmative pairwise comparability (`COMPARABLE` or fulfilled `COMPARABLE_WITH_CONDITIONS`), exact bridge bindings if applicable, and claim-relevant context/evidence. | Does not imply change beyond error or practical importance. |
| `CHANGE_RELATIVE_TO_MEASUREMENT_ERROR` | Comparable change plus source/protocol-bound registered error/reliability authority, applicable error scale, uncertainty propagation, and exact support/design match. | Does not imply practical meaning, fatigue, readiness, injury, or mechanism. |
| `PRACTICAL_OR_DECISION_MEANINGFULNESS` | Error-relative or otherwise justified change plus an explicit registered decision/utility criterion and applicable population/context evidence. No generic threshold or p-value may substitute. | Does not imply a physiological mechanism or causal effect. |
| `OBSERVATION` | Exact typed observation/relationship description. | Does not imply descriptive change, association, or causality. |
| `DESCRIPTIVE_CHANGE` | Exact temporal support and descriptive change authority; no causal wording. | Temporal order alone is not causality. |
| `ASSOCIATION` | Registered association operation, declared estimand, adequate independent units/level, exact support, and statistical authority. | Association is not a causal effect. |
| `TEMPORAL_ASSOCIATION` | Association prerequisites plus explicit time ordering, repeated-measures design, and registered temporal/lag estimator. | Temporal precedence is not identification of a causal effect. |
| `MECHANISTIC_HYPOTHESIS` | Association/temporal result plus external mechanism evidence with explicit applicability and hypothesis status. | A plausible mechanism is not causal evidence. |
| `CAUSAL_EVIDENCE` | Explicit causal estimand, design/identification strategy, temporal structure, confounding/control assumptions, target-population applicability, registered causal operation, and uncertainty. | Routine monitoring, correlation, temporal order, or a p-value cannot promote to this level. |

The following boundaries are invariants:

```text
NUMERICAL_CHANGE != COMPARABLE_CHANGE
COMPARABLE_CHANGE != CHANGE_RELATIVE_TO_MEASUREMENT_ERROR
CHANGE_RELATIVE_TO_MEASUREMENT_ERROR != PRACTICAL_OR_DECISION_MEANINGFULNESS
ASSOCIATION != CAUSAL_EFFECT
TEMPORAL_ORDER != CAUSALITY
STATISTICAL_SIGNIFICANCE != PRACTICAL_IMPORTANCE
METHOD_VALIDITY != POPULATION_APPLICABILITY
```

## 5. Evidence applicability

### 5.1 Orthogonal applicability vector

RES-70 introduces an additive `ClaimEvidenceApplicability` composition. It
reuses `ApplicabilityDecision`, `V2EvidenceApplicability`, canonical source
decisions, evidence references, and RES-69 support/design evidence.

```text
ApplicabilityAssessment {
    axis: METHOD_VALIDITY | SOURCE_QUALITY | POPULATION_RELEVANCE |
          CONTEXTUAL_RELEVANCE | STATISTICAL_ADEQUACY
    decision: SUPPORTED | LIMITED | UNSUPPORTED | UNASSESSED
    required_for_claim: bool
    evidence_references[]
    source/decision/authority references[]
    conditions[]
    rationale
}

ClaimEvidenceApplicability {
    claim_intent_reference
    assessments: one typed assessment per required axis
    registry_version/hash
    applicability_hash
}
```

There is no `confidence_score`, weighted average, or single evidence grade
that can hide an unsupported axis. A limited method can be valid in isolation
while population relevance is unsupported; that combination can support a
method description but not a target-population norm or decision claim.

### 5.2 Canonical source and target rules

- `CANONICAL_EMPIRICAL_TARGET` and
  `DIRECT_TARGET_POPULATION_EVIDENCE` can satisfy target-population
  applicability only when their RES-60 decisions and claim role support it.
- `INDIRECT_MEASUREMENT_EVIDENCE` may support mechanics, metrology, signal
  processing, reliability methodology, statistics, or device behavior when an
  explicit V2 applicability record says so. It cannot silently establish
  canonical football norms, practical thresholds, or population expectations.
- `NONCANONICAL_CONTEXT_ONLY` and `REJECTED_OR_UNRESOLVED` cannot satisfy a
  required claim axis.
- Source quality/integrity is independent of population relevance. A source can
  be high-quality but non-target, or target-relevant but too poorly identified
  for a particular claim.
- Match/training contextual relevance is evaluated from typed RES-61 context
  and exposure, not a free-text session label.
- Statistical adequacy is the design/support question for the requested
  estimand; it is not a substitute for method validity or source quality.

## 6. Within-athlete versus between-athlete authority

### 6.1 Explicit level identity

Every analysis request must bind:

```text
unit_of_analysis
subject_key
repeated-measure key
cluster/nesting keys
grouping keys
temporal ordering/lag policy
pooling/aggregation policy
requested estimand level
```

The minimum level vocabulary is:

```text
TRIAL
TEST_INSTANCE
SESSION
ATHLETE_WITHIN
ATHLETE_BETWEEN
GROUP_OR_SQUAD
POPULATION
JOINT_MULTILEVEL
```

### 6.2 Non-negotiable level rules

- A between-athlete association requires independent athlete units. Repeated
  rows from one athlete cannot increase the subject count unless a registered
  model explicitly represents the clustering.
- A within-athlete association requires repeated observations linked to the
  same athlete and a registered within-person estimand. A pooled correlation
  cannot be relabelled as within-athlete behavior.
- Repeated measurements are not independent subjects. The support must retain
  athlete/session/trial structure and the analysis must declare the dependence
  policy.
- A within-athlete change is not a population effect. Population or squad
  generalization requires separate population/source applicability and a
  corresponding estimand.
- Cross-test association does not require the tests to be comparable measures;
  it requires distinct exact identities plus an association design. Association
  does not authorize substituting one test for another.
- `JOINT_MULTILEVEL` is permitted only when a registered mixed/multilevel
  estimator and its random/fixed effect design exist. RES-70 does not implement
  one.

## 7. Refusal taxonomy and fail-closed behavior

### 7.1 Reuse

Every RES-70 refusal uses the existing `RefusalResult` envelope and high-level
classes. It retains exact observation IDs where available and states what can
still be safely described.

### 7.2 RES-70-local reason codes

Only reasons not already expressible by the generic/ref-69 taxonomy are added:

```text
RES70_UNRESOLVED_IDENTITY
RES70_COMPARABILITY_AUTHORITY_MISSING
RES70_BRIDGE_REQUIRED
RES70_BRIDGE_NOT_EXECUTED
RES70_BRIDGE_EXECUTION_FAILED
RES70_BRIDGE_CONDITIONS_UNSATISFIED
RES70_INCOMPATIBLE_CONTEXT
RES70_NORMALIZATION_MISMATCH
RES70_METHOD_VERSION_MISMATCH
RES70_THRESHOLD_IDENTITY_MISMATCH
RES70_STATISTICAL_AUTHORITY_INSUFFICIENT
RES70_WRONG_LEVEL_OF_ANALYSIS
RES70_PSEUDOREPLICATION_RISK
RES70_UNSUPPORTED_CLAIM_ESCALATION
RES70_UNSUPPORTED_CAUSAL_CLAIM
RES70_INSUFFICIENT_EVIDENCE_APPLICABILITY
RES70_APPLICABILITY_AXIS_UNASSESSED
RES70_TRANSITIVITY_NOT_ESTABLISHED
RES70_REGISTRY_INTEGRITY_FAILURE
```

Mapping examples:

| RES-70 reason | Generic refusal class |
| --- | --- |
| unresolved identity, context, threshold, or method version | `IDENTITY_UNRESOLVED` or `COMPARABILITY_UNESTABLISHED` |
| bridge required/not executed/conditions unsatisfied | `COMPARABILITY_UNESTABLISHED` |
| statistical authority, wrong level, pseudo-replication | `ANALYSIS_DESIGN_MISMATCH` or `DATA_ADEQUACY_INSUFFICIENT` |
| unsupported evidence axis | `EVIDENCE_SCOPE_UNSUPPORTED` |
| claim escalation or practical meaning without criterion | `UNCERTAINTY_LIMITS_CLAIM` |
| unsupported causal claim | `CAUSAL_IDENTIFICATION_UNSUPPORTED` |
| deferred/unregistered operation or bad registry | `COMPUTATION_NOT_REGISTERED` |

### 7.3 Safe fallback behavior

Examples of safe partial output:

- blocked cross-device change → retain each exact observation and its identity;
- blocked bridge → retain source/provider values as source/provider outputs;
- blocked error-relative claim → retain a valid comparable/numerical result if
  that lower claim was independently authorized;
- blocked within-athlete inference → retain descriptive per-athlete values and
  the between-athlete result only if that was the requested/authorized level;
- blocked causal claim → retain observation, descriptive change, or association
  output with the causal level explicitly refused.

No refusal erases an independently valid observation. No safe description may
use wording that implies the blocked stronger claim.

## 8. Provenance and determinism

Every authorized RES-70 decision/result must be reproducible from:

```text
exact source observation/entry IDs and canonical hashes
measurement identity/result/context/provenance hashes
RES-60/61 source and context decisions
pairwise comparability decisions and rule references
bridge registration and executed output/provenance, if any
RES-69 support/scale/reliability/method-comparison authority
analysis capability registry version/hash
requested analysis and level-of-analysis identity
claim intent and evidence-applicability bundle
software and registry versions
processing/provenance graph references
authorization/refusal/claim decision hashes
```

Rules:

- No stochastic or model-dependent decision logic exists in RES-70 V1.
- No caller-supplied formula, threshold, unit conversion, scale flag, bridge
  validity flag, sample-size verdict, or numerical result is authoritative.
- Every numerical transformation creates an append-only derived observation.
- Every analysis result reuses RES-69 `StatisticalAnalysisRun`/provenance
  semantics rather than inventing a second run graph.
- Every registry is immutable, versioned, hashable, duplicate-free, and
  resolved from the canonical production instance.
- Canonical ordering and V3 serialization are used for all new contracts.

## 9. LM boundary

| LM may | LM may not |
| --- | --- |
| propose an analysis class | mint comparability |
| propose a claim class/axis level | select an arbitrary transformation |
| request a named registered bridge | bypass support, identity, or level prerequisites |
| provide a scientific question/context candidate | promote claim authority |
| extract candidate protocol/context metadata for typed validation | declare causality, readiness, fatigue, injury, or population applicability |
| interpret an authorized structured result | fabricate a formula, threshold, evidence grade, or numerical result |

The LM request is data. Python decides whether the request is admissible,
whether a bridge executes, which operation is allowed, and which claim levels
are supported.

## 10. Proposed future public API

The following is an additive API plan, not code in this mission:

```python
# dynamislm.comparability
assess_cross_source_comparability(request) -> CrossSourceComparabilityDecision
execute_registered_bridge(request) -> BridgeExecutionResult | RefusalResult
validate_cross_source_decision(decision) -> None

# dynamislm.analysis
authorize_analysis(request) -> AnalysisAuthorization | RefusalResult
execute_authorized_analysis(authorization) -> StatisticalResult | RefusalResult
validate_analysis_authorization(authorization) -> None

# dynamislm.claims
authorize_claim(intent) -> ClaimAuthorityResult
validate_claim_authority(result) -> None

# dynamislm.evidence
build_claim_evidence_applicability(...) -> ClaimEvidenceApplicability
validate_claim_evidence_applicability(...) -> None
```

The public functions accept typed immutable contracts and canonical registries
only. A low-level operation may still be tested independently under its owning
RES authority, but a RES-70 claim-eligible result must carry an authorized
RES-70 decision reference.

## 11. Exact implementation file plan

This is the authorized future implementation shape. None of these production
files is created by RES-70-DR-001.

### New files

```text
src/dynamislm/comparability/res70_models.py
    ObservationAuthorityReference, ComparabilityDimension,
    DimensionFinding, CrossSourceComparabilityRequest/Decision,
    BridgeRegistration, BridgeApplicationRequest/ExecutionResult.

src/dynamislm/comparability/res70_registry.py
    bridge references, bridge registry, comparability rule registry/version/hash.

src/dynamislm/comparability/res70_authority.py
    pairwise-only adjudication, bridge resolution, no-transitive-closure gate.

src/dynamislm/comparability/res70_validation.py
    hash/relation/registry/provenance and execution validation.

src/dynamislm/analysis/models.py
    AnalysisClass, AnalysisLevelIdentity, AnalysisCapability,
    AnalysisAuthorizationRequest, AnalysisAuthorization.

src/dynamislm/analysis/registry.py
    canonical RES-70 capability matrix and registry integrity/version/hash.

src/dynamislm/analysis/authority.py
    deterministic prerequisite evaluation and operation dispatch gate.

src/dynamislm/analysis/validation.py
    support, level, evidence, comparability, registry and hash validation.

src/dynamislm/claims/models.py
    MeasurementClaimLevel, RelationshipClaimLevel, ClaimIntent,
    ClaimAuthorityResult, prediction-axis contract.

src/dynamislm/claims/registry.py
    claim prerequisite policies and decision-criterion references.

src/dynamislm/claims/authority.py
    two-axis claim authorization and escalation refusal.

src/dynamislm/claims/validation.py
    claim-result recomputation and V3/tamper validation.

src/dynamislm/evidence/res70.py
    ApplicabilityAxis, ApplicabilityAssessment,
    ClaimEvidenceApplicability and validation.
```

### Additive edits in the implementation mission

```text
src/dynamislm/comparability/__init__.py
src/dynamislm/analysis/__init__.py
src/dynamislm/claims/__init__.py
src/dynamislm/evidence/__init__.py
src/dynamislm/__init__.py
```

Only exports and registrations are additive. `serialization.py`, existing
RES-34→69 dataclasses, family comparators, and historical hashes are not
rewritten.

### Future focused tests

```text
tests/test_res70_comparability.py
tests/test_res70_bridges.py
tests/test_res70_analysis_capability.py
tests/test_res70_claim_authority.py
tests/test_res70_evidence_and_levels.py
tests/test_res70_adversarial.py
```

Tests must use clearly synthetic fixtures only and must attempt to falsify the
authority boundaries. They are not part of this design mission.

## 12. Adversarial qualification matrix

| Attack/negative case | Required deterministic response |
| --- | --- |
| Same metric label, different measurand | `NOT_COMPARABLE`; label ignored. |
| Same unit, different construct/protocol/metric definition | `NOT_COMPARABLE` or `BRIDGE_VALIDATION_REQUIRED` according to the registered rule; never direct comparison. |
| Same values, different observation IDs | Preserve both observations; no deduplication by value. |
| A~B and B~C offered as an A~C shortcut | `RES70_TRANSITIVITY_NOT_ESTABLISHED`; require direct A/C adjudication. |
| Caller passes `force_comparable=True` | Reject unknown/non-authoritative input; no state change. |
| Caller asks for a unit conversion but does not provide executed output | `REQUIRES_TRANSFORMATION` / `RES70_BRIDGE_NOT_EXECUTED`. |
| Hidden conversion in a derived scalar | Refuse; output must have a registered operation and new provenance. |
| Bridge source/target key contains observation-instance ID | Registry integrity failure. |
| Bridge declaration exists but domain/range/evidence does not apply | `INSUFFICIENT_INFORMATION` or `BRIDGE_CONDITIONS_UNSATISFIED`. |
| Bridge operation changes value but returns original observation ID | Reject forged output/provenance linkage. |
| Lossy bridge with no uncertainty/limitation policy | Refuse error-relative/practical claims. |
| Caller selects an unregistered estimator/formula/threshold | `COMPUTATION_NOT_REGISTERED`. |
| Caller supplies scale/ratiometric/positive flag | Ignore flag; resolve canonical RES-69 scale authority. |
| Caller names deferred RES-69 repeated correlation/mixed-effects method | Refuse; do not implement or dispatch it. |
| Between-athlete rows relabelled as within-athlete | `RES70_WRONG_LEVEL_OF_ANALYSIS`. |
| Multiple trials counted as independent subjects | `RES70_PSEUDOREPLICATION_RISK`. |
| Repeated measurements treated as independent observations | Refuse unless registered dependence model is present. |
| Within-athlete change generalized to the population | Block population claim; retain within-athlete description. |
| Match observation compared with training observation for a match claim | `RES70_INCOMPATIBLE_CONTEXT` or conditional result only under a registered policy. |
| Method validity used as population applicability | Block target-population claim; keep method statement. |
| Indirect method evidence used for canonical football norm | `RES70_INSUFFICIENT_EVIDENCE_APPLICABILITY`. |
| Statistical significance used as practical meaning | Block practical claim without a decision criterion. |
| Comparable change relabelled as physiological mechanism | Block latent/physiological escalation. |
| Association relabelled as causal effect | `RES70_UNSUPPORTED_CAUSAL_CLAIM`. |
| Temporal order relabelled as causal identification | `CAUSAL_IDENTIFICATION_UNSUPPORTED`. |
| Forged registry version/hash or duplicate key | `RES70_REGISTRY_INTEGRITY_FAILURE`. |
| Tampered support/identity/bridge/decision hash on V3 decode | Decode/construction failure. |
| Valid source observation plus blocked comparison | Preserve safe independent source description. |

## 13. Explicit reuse, new work, deferral, and rejection

### REUSE_FROM_RES69

- `StatisticalSupport`, exact RES-62 input/entry references, exclusions,
  missingness, and support hashes.
- `StatisticalComparabilityEvidence` as the only affirmative evidence path
  into existing RES-69 calculations.
- `StatisticalAnalysisRun`, `StatisticalResult`, `StatisticalEstimate`,
  `StatisticalNonComputable`, and existing deterministic provenance graphs.
- RES-69 scale-semantic registry, reliability-assumption authority,
  method-comparison authority, operation registry/disposition, exact-unit rule,
  and refusal factories.
- RES-69 distinctions between descriptive within-athlete SD, random error,
  method-comparison bias/SD, and claim interpretation.

### NEW_IN_RES70

- Claim-relative cross-source wrapper and material-dimension findings.
- Pairwise comparability matrix with an explicit no-transitivity invariant.
- Registered bridge declaration, execution, uncertainty/lossiness, and
  append-only transformed-observation contract.
- Analysis-capability registry above the RES-69 operation registry.
- Explicit level-of-analysis/estimand/cluster identity and pseudo-replication
  gate.
- Two-axis claim model, typed claim intents/results, claim escalation rules,
  and prediction separation.
- Orthogonal evidence-applicability bundle and RES-70 decision provenance.
- RES-70-local granular refusal codes and registry integrity checks.

### DEFER_TO_LATER

- Any RES-69 operation currently `DEFER`, `REPRESENT_BUT_DO_NOT_COMPUTE`, or
  `REJECT`, including repeated-measures correlation, mixed effects, ICC/MDC,
  confidence intervals, covariance propagation, and classical agreement limits.
- Family-specific cross-device/provider/protocol bridges until each owning
  scientific decision supplies evidence, domain limits, uncertainty, and tests.
- Generic meaningful-change thresholds, practical utility policies, readiness,
  fatigue, injury, and physiological interpretation.
- A general causal-inference engine, transport estimator, or predictive model.
- LM runtime/tool-calling/model-training integration.
- Persistence/database implementation beyond existing immutable contracts.

### REJECTED

- Label/name, unit-only, numeric-equality, or correlation-based comparability.
- Transitive comparability or bridge chaining without direct registered support.
- Caller-minted bridge validity, formulas, thresholds, units, scale semantics,
  sample-size adequacy, population applicability, or causal status.
- Hidden value transformation or in-place reprocessing.
- A scalar confidence score collapsing evidence axes.
- A single linear claim ladder that conflates measurement change and causal
  inference.
- Between/within substitution, pseudo-replication, or observation-instance
  semantic registry keys.
- Any RES-70 implementation that opportunistically fills a deferred RES-69
  method.

## 14. Targeted evidence table

| Source | Type | Finding used | RES-70 consequence | Limits/applicability |
| --- | --- | --- | --- | --- |
| [Bland & Altman, 1986, *Lancet*, PMID 2868172, DOI 10.1016/S0140-6736(86)90837-8](https://pubmed.ncbi.nlm.nih.gov/2868172/) | Primary methodological paper | Correlation is not an agreement/interchangeability analysis; method comparison needs differences/repeatability context. | Keep association and agreement/comparability separate; require method-comparison authority and do not promote correlation. | Developed for clinical measurement-method comparison; RES-70 uses the boundary, not a universal acceptance limit. |
| [Bland & Altman, 1999, *Statistical Methods in Medical Research*, PMID 10501650, DOI 10.1177/096228029900800204](https://pubmed.ncbi.nlm.nih.gov/10501650/) | Methodological paper | Agreement requires paired same-subject method differences and must account for repeated measurements. | Bind exact pairing, method identity, replicate design, and authority; do not infer interchangeability from a summary alone. | No generic football/device limits are adopted. |
| [Vandenberg & Lance, 2000, DOI 10.1177/109442810031002](https://doi.org/10.1177/109442810031002) | Methodological review with longitudinal example | Measurement invariance is a prerequisite for substantive cross-group comparisons. | Treat cross-source equivalence as an identity/evidence problem; a bridge must establish claim-relative invariance/equivalence where relevant. | Psychometric invariance tests do not mechanically replace physical-method validation. |
| [Lazic, 2010, *BMC Neuroscience*, DOI 10.1186/1471-2202-11-5](https://pmc.ncbi.nlm.nih.gov/articles/PMC2817684/) | Methodological analysis | Pseudoreplication arises when non-independent replicates are used as independent units. | Require explicit experimental unit, clustering, and independence/replicate policy. | Domain is neuroscience; the dependence principle is general. |
| [Curran & Bauer, 2011, DOI 10.1146/annurev.psych.093008.100356](https://doi.org/10.1146/annurev.psych.093008.100356) | Longitudinal methods review | Within-person and between-person effects must be disaggregated in longitudinal models. | Make the estimand/level identity mandatory and refuse pooled relabelling. | The review does not select one universal model for football monitoring. |
| [Hopkins, 2000, *Sports Medicine*, PMID 10907753, DOI 10.2165/00007256-200030010-00001](https://pubmed.ncbi.nlm.nih.gov/10907753/) | Sports-methods reliability paper | Reliability includes within-subject random variation, systematic trial change, and retest correlation; typical error and correlation answer different questions. | Reuse RES-69 reliability/error distinctions; require source-bound design authority and block generic SEM/MDC/meaningful change. | No universal error scale or threshold is imported into RES-70. |
| [Wasserstein & Lazar, 2016, ASA p-value statement, DOI 10.1080/00031305.2016.1154108](https://doi.org/10.1080/00031305.2016.1154108) | Professional methodological statement | P-values require context and do not supply effect magnitude or practical importance by themselves. | Keep statistical evidence, measurement error, and practical/decision criteria as separate claim prerequisites. | This is not a football-specific decision threshold. |
| [Hernán & Robins, 2020, *Causal Inference: What If*](https://miguelhernan.org/whatifbook) | Authoritative methodological book | Causal claims require an explicit causal question/design/estimand and assumptions, including for longitudinal data. | Keep causal evidence separate from observation, association, and temporal association; require a registered causal operation. | RES-70 does not implement causal inference. |
| [Bareinboim & Pearl, 2016, *PNAS*, PMID 27382148, DOI 10.1073/pnas.1510507113](https://pubmed.ncbi.nlm.nih.gov/27382148/) | Primary causal/transportability paper | Transporting causal information across populations requires explicit assumptions about source/target differences and data fusion. | Keep population relevance separate from method validity; no silent target-population generalization. | Transportability theory is not a license for routine athlete-monitoring causal claims. |
| [Degtiar & Rose, 2023, DOI 10.1146/annurev-statistics-042522-103837](https://doi.org/10.1146/annurev-statistics-042522-103837) | Methodological review | Internal validity and external validity/target-population applicability are distinct and require assumptions. | Use separate population/context applicability axes; a valid method can have limited target applicability. | The review concerns causal effect generalization; RES-70 applies the distinction more broadly and conservatively. |

## 15. Deferred scientific questions, not RES-70 blockers

The generic architecture is frozen without pretending to answer operation- or
bridge-specific scientific questions. The following are explicitly deferred
to the owning future implementation/decision record; RES-70 V1 refuses any
claim that needs them:

1. What agreement/equivalence limits are acceptable for a particular device,
   provider, protocol, population, and claim? A future bridge owner must supply
   claim-specific evidence and uncertainty; there is no universal limit.
2. What sample-size, covariance, missingness, and convergence rules are needed
   for a particular repeated-measures or mixed-effects estimator? The operation
   is not registered in RES-69, so RES-70 does not choose a number now.
3. What practical/decision criterion applies to a particular staff decision?
   A future criterion must be explicitly registered with its population/context
   applicability; no generic smallest worthwhile change is adopted.
4. What causal identification strategy, if any, is appropriate for a future
   question? A future causal mission must define the estimand/design and
   evidence; RES-70 only enforces the boundary.

These are not missing decisions needed to freeze the RES-70 generic authority
architecture. They are intentionally typed `DEFERRED`/`REJECTED` capability
entries, so no production claim can proceed while they are absent.

## 16. Acceptance criteria for the future implementation

The RES-70 implementation may be declared complete only if deterministic
tests demonstrate:

1. no label, unit, correlation, caller flag, or transitive path mints
   comparability;
2. every numerical bridge output has a new output identity, executed method,
   uncertainty/lossiness status, and complete provenance;
3. a declared but unexecuted transformation cannot enter statistical support;
4. unknown, conflicting, or missing material dimensions fail closed;
5. deferred RES-69 operations remain refused;
6. within/between/pseudo-replication attacks are blocked;
7. evidence axes remain separately inspectable and no scalar confidence score
   is emitted as authority;
8. claim promotion stops at the first unsupported prerequisite and preserves
   safe lower descriptions;
9. causal/readiness/fatigue/injury escalation is refused without the required
   registered design and evidence;
10. V3 round-trip/hash/tamper tests cover every new type and all historical
    RES-34→69 hashes remain unchanged; and
11. all authorized decisions can be reproduced from their recorded hashes,
    registry versions, software version, and provenance references.

## Design freeze disposition

```text
RES70_DESIGN_STATUS=FROZEN
RES70_PRODUCTION_IMPLEMENTATION=NOT_STARTED
SCIENTIFIC_NUMERICAL_AUTHORITY_CHANGED=NO
SERIALIZATION_VERSION_CHANGED=NO
RES34_TO_RES69_AUTHORITY_CHANGED=NO
```

The next authorized action is a separate implementation mission that realizes
this record and adds adversarial tests. RES-70-DR-001 itself does not authorize
production code, tests, bridges, deferred statistics, or model work.
