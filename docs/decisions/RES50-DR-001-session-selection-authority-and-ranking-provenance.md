# RES50-DR-001 — Session selection authority and ranking provenance

DECISION_ID=RES50-DR-001
STATUS=ADOPTED
QUESTION=How does a CMJ session result prove its selected target, ranking method, and complete computational lineage?

## SELECTED_TARGET_CARDINALITY

`CMJ_SELECTED_SINGLE_TRIAL_PROJECTION_V1` requires a target observation only
for the one `selected_trial_id`. Eligible but unselected trials do not create a
target requirement. `CMJ_ARITHMETIC_MEAN_V1` requires one valid target for
every selected/contributing trial; it never computes an available-case mean.

## RANKING_METHOD_SEMANTIC_IDENTITY

Extreme selection derives one canonical `ranking_method_key` from every
eligible ranking observation. The existing phase, jump-height, mechanics,
acquisition, protocol, device, system, loading, timebase, processing, event,
zero-reference, unit, normalization, and version authorities supply the key.
All ranking observations must be directly comparable and must have the same
canonical key. The caller-supplied nominal metric and method are checked against
the observations and are not the method authority.

## TRIAL_INSTANCE_EXCLUSIONS_FROM_METHOD_KEY

The key excludes trial and observation IDs, artifact/acquisition/identity IDs,
event and phase occurrence IDs, event times, realized event or phase
coordinates, sample indices, realized zero-reference coordinates, trial
duration, source sample count, and explicit timestamp origin. Configured
detector parameters, including `search_start_index`, remain method identity.

## SELECT_ALL_AUTHORITY

`CMJ_SELECT_ALL_DECLARED_ELIGIBLE_V1` must select exactly all eligible trials
in declared candidate order. It carries no ranking metric, method, method key,
direction, tie policy, ranking IDs, ranking values, or ranking provenance.

## EXTREME_SELECTION_AUTHORITY

`CMJ_SELECT_EXTREME_BY_REGISTERED_METRIC_V1` requires one ranking observation,
finite ranking value, and aligned ranking ID for each eligible trial; the
registered direction and `CMJ_TIE_EARLIEST_DECLARED_CANDIDATE_V1` tie policy
are retained. The ranking observations are the declared candidate observations
for the V1 decision, preserving their eligible declared order.

## DETERMINISTIC_WINNER_RECOMPUTATION

`TrialSelectionDecision` accepts only the two registered selection rules. Its
constructor, canonical deserializer, and `replace(...)` path recompute argmax
or argmin from the retained eligible order, values, direction, and tie policy.
The selected trial must equal that winner. Missing, non-finite, misaligned, or
unregistered fields fail closed.

## RANKING_PROVENANCE

Extreme decisions retain an immutable, order-aligned tuple of the actual
ranking observations' `Provenance` records. Projection/aggregation can also
validate an explicit tuple of the actual ranking observations. The session
processing run receives a direct lineage edge from every ranking observation,
including unselected ranking trials, so ranking dependencies are computational
lineage rather than metadata-only IDs. Their artifacts, acquisitions,
processing runs, and evidence are merged into the new output provenance.

## TARGET_PROVENANCE

Every selected/contributing target observation remains an explicit source of
the new session processing run. Its artifacts, acquisitions, processing runs,
evidence, and lineage are retained. Target source, athlete, session, test
family, scalar, method, and comparability checks fail closed.

## DEDUPLICATION

Ranking and target provenance is merged by stable identity. Shared artifacts,
acquisitions, processing runs, edges, and evidence are emitted once. Conflicting
records with the same source identity refuse the session result. Source
observations are immutable; reprocessing creates a new output observation.

## SERIALIZATION

`SERIALIZATION_VERSION=3` remains unchanged. The new ranking method key and
ranking provenance fields are additive v3 fields; optional fields use their
declared defaults when absent from older v3 wire objects. Canonical roundtrips
preserve selection authority, session results, and the complete lineage graph.
RES-39 and RES-49 phase/metric historical hashes are unchanged.

## P2_MULTI_SOURCE_ACQUISITION_HANDOFF

The current session aggregate inherits one source-acquisition-shaped identity
from its first contributing target observation. RES-50 preserves every source
acquisition in provenance, including ranking sources, but does not define a
multi-source derived-record identity. Complete multi-source acquisition and
canonical record semantics are explicitly deferred to RES-19.

## LIMITATIONS

This decision adds no CMJ metric, biomechanics, phase definition, jump-height
estimator, reliability quantity, uncertainty statistic, readiness/fatigue
interpretation, causal claim, or P2 canonical record. No universal `BEST`
selection rule is introduced.

## IMPLEMENTATION

Implemented in `src/dynamislm/measurement/cmj/session.py` with additive v3
deserialization support in `src/dynamislm/serialization.py`. The session
output remains a new scalar `ScientificMeasurementObservation` and retains the
existing RES-40 selection and aggregation evidence.

## TESTS

The RES-50 matrix covers selected-only projection targets, complete selected
means, source mismatch refusal, full ranking method identity, method-versus-
instance separation, registered-rule self-validation, deterministic winner
recomputation, ranking/target lineage, deduplication, canonical roundtrip,
and historical hash regression. The full suite contains 239 passing tests.

## VERSION

RES50-DR-001 v1.0.0; `SERIALIZATION_VERSION=3`.
