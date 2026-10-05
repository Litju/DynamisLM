# RES-373 Acceptance Receipt

```text
MISSION=RES-373
STATUS=PASS
ENTRY_HEAD=182689430d2adfe1227832a015bb4dc66ef39d73
BRANCH=work/res-21-performance-science-eval-v1
SELECTION_PROFILE=PSE-V1-PRODUCTION-SELECTION-SOLVER@1.0.0
```

## Engine-reference isolation

- `ProductionAuthoringPlanItemV1` now carries the exact
  `engine_reference_case_id` from validated proposed provenance. Engine-derived
  commitments require it; non-engine commitments cannot carry it.
- RES-369 adapts that value to the typed
  `RES71_ENGINE_REFERENCE_CASE` isolation identity. Existing conditional
  colocation semantics remain: any member may be `OUT`, and selected related
  members cannot cross splits.
- Final `BenchmarkCaseV1` isolation uses the same typed identity kind and the
  exact provenance field.
- Counterfactual checks pass with the same reference ID and different shingles,
  source families, and isolation clusters; one member `OUT` is legal, while a
  cross-split assignment is invalid and infeasible.

## Qualification

| Check | Result |
| --- | --- |
| Fixed 434, sealed RES-369 profile | `OPTIMAL`; 434 selected; split counts `260/87/87`; independent validation `VALID`; warm start used |
| Oversupply, sealed RES-369 profile | `OPTIMAL`; 434 selected; rejected candidate `OUT`; rejection backfill selected; sequential counterexample infeasible |
| RES-373 targeted regressions | `PASS` |
| Full CI (`./scripts/ci.sh`) | `PASS` — 1,164 tests |

Full CI also passed Ruff, formatting, mypy, repository policy, and the tracked
mutation check. The run completed in `1,076.25s`.

## Preservation checks

```text
RES71_REFERENCE_REGISTRY_MODIFIED=NO
DR001_MODIFIED=NO
RESERVE_POLICY_MODIFIED=NO
SOLVER_CANONICALIZATION_MODIFIED=NO
BENCHMARK_CASE_SERIALIZATION_V3_MODIFIED=NO
CASE_PAYLOAD_HASH_PROJECTION_MODIFIED=NO
PROTECTED_STORES_MODIFIED=NO
REAL_CANDIDATE_CONTENT_MODIFIED=NO
```

The non-V1 full-coverage test fixture now uses three existing RES-71 value
references, with each reference group assigned to one split. No RES-71 registry
or scientific reference values were changed.
