# RES40-DR-001 — CMJ trial sets, eligibility, and selection

DECISION_ID=RES40-DR-001
STATUS=ADOPTED
SCOPE=Declared CMJ candidate trial sets, explicit eligibility decisions, and registered trial selection.

## QUESTION

How does DynamisLM select trials for a session without silently dropping trials,
inventing a universal “best” trial, or confusing a ranking metric with the
metric later reported?

## EVIDENCE_ROLE

Turner et al. (2024, PMID 38319955) compared mean and best-of-three CMJ
summaries and found that reliability behavior can differ by summary choice.
Lake and McMahon (2018, PMID 30413012) showed that force-time shape can vary
within a participant and cautioned against indiscriminate averaging of curves.
Xu et al. (2023, PMID 36940054) reviewed materially different jump-height
calculation methods and equipment. These sources establish that selection,
aggregation, and estimator/device identity matter; they do not establish a
universal best trial or a universal mean-of-N rule.

## DECISION

`DeclaredCandidateTrialSet` preserves athlete, session, CMJ test family, an
explicit ordered tuple of distinct trial IDs, the aligned candidate observation
IDs, and the declared count. The order is supplied by the caller and is the
only V1 deterministic tie-break order.

Every declared candidate receives a `TrialEligibilityDecision`. V1 statuses
are `ELIGIBLE`, `EXCLUDED`, and `UNRESOLVED`. An exclusion requires a registered
eligibility-policy reference, a reason, the trial ID, and observation IDs.
Unresolved or missing candidates are not silently converted to available-case
inputs.

The only V1 selection rules are:

* `CMJ_SELECT_ALL_DECLARED_ELIGIBLE_V1` selects every explicitly eligible
  candidate.
* `CMJ_SELECT_EXTREME_BY_REGISTERED_METRIC_V1` requires a ranking metric,
  ranking method/estimator, direction (`MAXIMIZE` or `MINIMIZE`), and the
  registered `EARLIEST_DECLARED_CANDIDATE` tie policy.

Extreme ranking first establishes direct comparability for every participating
ranking observation through the existing CMJ metric-specific comparability
authority. A bridge-required, not-comparable, or insufficient result refuses
the ranking. Exact ties select the first candidate in the declared tuple; UUID,
hash, dictionary, and storage order never break ties.

The selection decision returns trial identity, the ranking observation IDs and
values aligned to the eligible declared order, a canonical ranking-method
semantic key, and all candidate, eligibility, exclusion, selected, and
ranking-observation counts. For the V1 extreme rule, ranking observations are
the declared candidate observations and their immutable provenance is retained.
It never returns a metric-shopping instruction and never independently
maximizes a later target metric.

## SOURCE_INVARIANTS

All supplied candidate observations must resolve to the declared athlete,
session, CMJ test family, and distinct declared trial. Wrong-source, duplicate,
wrong-family, or missing required inputs refuse the operation while leaving
source observations intact.

## LIMITATIONS

No universal `BEST_TRIAL` exists. No reliability, SEM, MDC, SWC, responsiveness,
readiness, fatigue, or causal interpretation is authorized. Vendor-selected
trials and unregistered exclusion rules have no V1 authority.

## REGISTRY

`CMJ_REGISTRY_VERSION=1.0.0`

`CMJ_SELECT_ALL_DECLARED_ELIGIBLE_V1`,
`CMJ_SELECT_EXTREME_BY_REGISTERED_METRIC_V1`, and
`CMJ_TIE_EARLIEST_DECLARED_CANDIDATE_V1` are registered in the CMJ registry.
`CMJ_EXPLICIT_TRIAL_EXCLUSION_POLICY_V1` is the only V1 policy that can turn
an explicitly documented trial exclusion into an honest reduced candidate set.

## IMPLEMENTATION_AND_TESTS

Implemented in `src/dynamislm/measurement/cmj/session.py` with adversarial
tests for source invariants, explicit eligibility, missing trials, direction,
metric comparability, estimator mismatch, and declared-order ties.
