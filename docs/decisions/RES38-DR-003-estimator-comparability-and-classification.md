# RES38-DR-003 — Estimator classification and comparability

## DECISION_ID

`RES38-DR-003-estimator-comparability-and-classification`

## STATUS

`DECIDED`

## QUESTION

Do flight-time and takeoff-velocity outputs share an estimand, and can equal
numeric values be treated as interchangeable?

## SCOPE

Output identity, scientific classification, claim-relative comparison, and
refusal behavior for the two RES-38 estimators.

## SOURCES

- Scientific constitution and measurement/provenance architecture.
- RES-36 event identity and RES-37/46 mechanics identity decisions.
- RES-44/45 gravity decisions.
- RES38-DR-001 and RES38-DR-002.
- Linthorne (2001), https://bura.brunel.ac.uk/handle/2438/1392.
- Smith, Lamont & Barefoot (2024), https://pubmed.ncbi.nlm.nih.gov/38863789/.

## APPLICABILITY

Applies to scalar `CMJJumpHeightResult` objects produced by a registered V1
method. It does not establish a biological validity bridge between methods.

## OPTIONS_CONSIDERED

1. Give every method a different measurand merely because its algorithm differs.
2. Use one shared vertical ballistic takeoff-to-apex estimand while preserving
   distinct estimator and operation identities.
3. Publish one unqualified generic CMJ jump-height identity.

## DECISION

Choose option 2. The estimators target the same underlying intended vertical
ballistic takeoff-to-apex rise, but operationalize it with different evidence
and assumptions. Their method identity, equation, events, gravity, upstream
mechanics, and provenance remain distinct. Option 3 is prohibited.

## ESTIMAND

`CMJ_JUMP_HEIGHT_MEASURAND@1.0.0` — vertical ballistic takeoff-to-apex rise.

## ESTIMATOR

The output identity stores both `ProcessingIdentity.estimator` and
`ProcessingIdentity.registered_operation`; the two registered references are
not aliases and are never collapsed by a label or unit.

## EQUATION

Flight time: `h = g t_f² / 8`.

Takeoff velocity: `h = v_takeoff² / (2 g)`.

## INPUTS

The exact event, velocity, gravity, system, detector, sample convention, and
upstream processing inputs defined in RES38-DR-001/002.

## EVENT_SEMANTICS

Event definitions, detector methods, detector parameters, sample-attached
index/time convention, source identity, and timebase are material comparison
dimensions. Trial-specific occurrence IDs and measured event indices are
lineage/value data, not method equivalence.

## GRAVITY_SEMANTICS

Gravity type, value, unit, source, and physical-chain compatibility are material
comparison dimensions. A standard/local distinction is never erased by numeric
rounding.

## ASSUMPTIONS

Assumptions are first-class registered references carried by the method and
serialized parameters. In particular, takeoff/landing height equivalence is
not inferred for flight-time outputs.

## CLASSIFICATION

Every numeric output is `MODEL_ESTIMATE` with explicit role
`PERFORMANCE_OUTCOME`. It is not `DIRECT_MEASUREMENT` and not merely a
`DERIVED_MECHANICAL_QUANTITY`.

## CLAIM_CEILING

An equal value means only equal reported scalar values under their respective
methods. It does not establish equal method validity, athlete-COM equivalence,
or interchangeability.

## PROVENANCE

Provenance is method-specific and append-only. Comparability never replaces or
flattens the source DAG.

## COMPARABILITY

- Same estimator and all material registered dimensions: `COMPARABLE`.
- Different estimator family with shared estimand: `BRIDGE_VALIDATION_REQUIRED`.
- Gravity/event/upstream/system/filtering mismatch: `BRIDGE_VALIDATION_REQUIRED`.
- Missing metadata: `INSUFFICIENT_INFORMATION`.
- A genuinely different measurand: `NOT_COMPARABLE`.

## REFUSAL

Comparability refusals use the existing claim-relative refusal class and retain
both estimates as independently describable. A cross-estimator comparison must
not silently pass because values match.

## LIMITATIONS

No RES-38 bridge validation study is registered; therefore no cross-estimator
interchangeability claim is authorized.

## IMPLEMENTATION

Implemented by `CMJJumpHeightComparabilityRequest`,
`compare_cmj_jump_height_estimates`, and
`refusal_for_cmj_jump_height_comparability`.

## TESTS

Same-method comparability, cross-method equal-value and disagreement fixtures,
gravity/event/upstream mismatches, explicit bridge state, and refusal mapping.

## VERSION

`1.0.0`
