# RES40-DR-002 — CMJ scalar session aggregation

DECISION_ID=RES40-DR-002
STATUS=ADOPTED
SCOPE=Selected-trial projection and arithmetic aggregation of CMJ scalar observations.

## DECISION

V1 has two registered session operations:

* `CMJ_SELECTED_SINGLE_TRIAL_PROJECTION_V1` projects one target scalar from
  the trial selected by a `TrialSelectionDecision`.
* `CMJ_ARITHMETIC_MEAN_V1` computes exactly `sum(x_i) / n` over selected,
  directly comparable scalar observations.

Selection and aggregation are separate. A selection by qualified jump height
estimator X may project braking impulse from the same selected trial; the
target is never independently ranked. The selected trial identity, ranking
metric/method, target metric, and all counts are retained in the immutable
session result.

Only scalar `ScalarValue` inputs are accepted. Raw signals, vectors, curves,
events, phase occurrences/boundaries, provenance structures, and strategy or
shape objects are refused. V1 has no weighting, median, trimmed mean,
winsorization, imputation, z-score, normalization, or vendor composite.

All contributing target observations must be directly comparable under the
existing metric-specific CMJ authorities. Same labels or units do not create a
bridge. Estimator, phase-system, phase-definition, device, protocol, loading,
processing, and normalization mismatches remain refused.

## COUNTS

The result preserves declared-candidate, eligible, selected, and contributing
counts. The candidate opportunity set and the contributing set are material:
mean-of-2 is not directly comparable to mean-of-3, and maximum-of-2 is not
directly comparable to maximum-of-3, absent future bridge authority. Exact
trial and observation IDs remain provenance/instance information.

Missing ranking observations, refused observations, and undeclared
available-case inputs do not produce a summary. A selected-trial projection
requires its target only for the selected trial; an eligible but unselected
target is not required. An arithmetic mean requires a target for every
selected/contributing trial. A registered explicit exclusion can reduce the
honest eligible and contributing counts and is retained in the selection
decision.

## CLASSIFICATION_AND_UNCERTAINTY

Homogeneous derived mechanical inputs remain `DERIVED_MECHANICAL_QUANTITY`;
homogeneous model-estimate inputs remain `MODEL_ESTIMATE`. Aggregation never
adds `PERFORMANCE_OUTCOME` or relabels a model estimate as a direct
measurement. The result carries `NOT_ASSESSED` uncertainty with an explicit
statement that deterministic aggregation is not measurement-error or
reliability analysis.

## PROVENANCE

The output is a new frozen `ScientificMeasurementObservation`. Source trial
and observation IDs, including every ranking dependency, source identities,
acquisition/device/protocol/loading semantics, selection and aggregation
rule/version, equation, counts, evidence, processing run, and lineage edges
are retained. Source observations are never overwritten.

## LIMITATIONS

No statistical uncertainty, SD-based reliability quantity, SEM, MDC, SWC,
responsiveness, meaningful change, readiness, fatigue, or causal/physiological
claim is computed. Power, RFD, RSI-mod, asymmetry, normalization families,
landing strategy metrics, and unregistered anatomical COM methods remain out
of scope.

## REGISTRY

`CMJ_REGISTRY_VERSION=1.0.0`

`CMJ_ARITHMETIC_MEAN_V1`, `CMJ_SELECTED_SINGLE_TRIAL_PROJECTION_V1`, and
`CMJ_SESSION_AGGREGATION_OPERATION` are registered in the CMJ registry.
