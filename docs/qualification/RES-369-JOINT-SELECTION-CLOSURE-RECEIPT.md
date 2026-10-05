# RES-369 Joint Selection Closure Receipt

```text
MISSION=PSE-V1-UNIFIED-JOINT-SELECTION-ALLOCATION-001
STATUS=PASS
ENTRY_HEAD=7e4e5de28d510c1d6bb9a0dda93ed49685594f30
AUTHORITY_REMOTE_HEAD=7e4e5de28d510c1d6bb9a0dda93ed49685594f30
SEMANTIC_CONSTRAINT_SCHEMA=PSE-V1-JOINT-SELECTION-CONSTRAINTS@1.0.0
SOLVER_FAMILY=OR-TOOLS-CP-SAT
SOLVER_VERSION=9.15.6755
VALIDATOR_VERSION=PSE-V1-JOINT-SELECTION-VALIDATOR@1.0.0
PRODUCTION_SOLVER_PROFILE=PSE-V1-PRODUCTION-SELECTION-SOLVER@1.0.0
PRODUCTION_SOLVER_CONFIG=workers:8,random_seed:369,timeout_s:60,canonical_chunk_size:30,cp_model_presolve:false,randomize_search:false
FINAL_N=434
SPLITS=260/87/87
FINAL_COMPOSITION=RES126_BOUNDS
MUTATION_LINEAGES_MIN=20
FIXED434_STATUS=OPTIMAL
OVERSUPPLY_STATUS=OPTIMAL
SEQUENTIAL_COUNTEREXAMPLE=PASS
REJECTION_REMOVAL_STATUS=PASS
SMALL_N_ORACLE_EQUIVALENCE=PASS
CANONICAL_DETERMINISM=5/5_TOY
LEGACY_FINAL_ALLOCATOR_USED=NO
PROTECTED_MEMBERSHIP_PERSISTED=NO
MATERIALIZATION_RUN=NO
HUMAN_REVIEW_RUN=NO
FOCUSED_RES369=PASS_IN_FULL_CI; ISOLATED_OVERSUPPLY=PASS; INITIAL_MODULE_RUN_HAD_ONE_TIMEOUT_UNKNOWN
FULL_CI=PASS (1162 tests; 1041.11 s)
NEXT=P4A.3l
```

The published final head is recorded in the RES-369 Linear closure receipt.

## Closure corrections

If the independent semantic validator rejects a decoded CP-SAT witness, the solve receipt now reports `UNKNOWN`, clears the accepted plan, and emits `SEMANTIC_VALIDATION_FAILED`. A regression test injects an independently invalid receipt and checks all three outcomes.

The production-qualified profile is named and versioned as `PSE-V1-PRODUCTION-SELECTION-SOLVER@1.0.0`. Production-shape qualification passes that exact immutable config and a validated warm start; both receipts report `warm_start_used=true`. The generic solver defaults remain separate, so a PSE V1 production caller must explicitly pass the named profile.

## Production-shape receipt

The abstract fixtures were run sequentially in one process with the named profile. Both decoded plans passed independent validation.

| Qualification | Variables | Constraints | Wall (s) | Objective (s) | Canonicalization (s) | Deterministic time (s) | Process peak RSS (MB) | Validation (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Fixed 434 | 2,436 | 3,775 | 26.120 | 7.254 | 17.650 | 70.042 | 503.9 | 0.661 |
| Oversupply | 2,456 | 3,386 | 128.459 | 26.075 | 101.157 | 199.451 | 1,085.0 | 0.759 |

The initial focused module run had 21 passes and one expected-OPTIMAL assertion fail because oversupply canonicalization returned `FEASIBLE` at its configured timeout; the solver correctly reported `UNKNOWN`. The isolated oversupply rerun and the later full CI run both passed with the same named profile. This run-to-run limit is retained in the claims below.

## Legacy coupling and claim ceilings

- `selection_constraints.py` still imports the private `production._feasibility_row_eligible` predicate. This coupling remains a legacy semantic dependency; re-home it before deprecating the legacy production stack. It is recorded here and was not changed in this closure correction.
- `LEGACY_PHASE_E_NOT_USED=PASS` shows the joint solver does not call `split.allocate_splits()`. There is no finalization/materialization orchestrator wired by this change, so the result does not prove every historical production entrypoint is removed. Future materialization must be gated to the joint engine.
- `CANONICAL_DETERMINISM=5/5` is measured on a small toy problem. Production-shape plans use the canonical assignment objective, but 5/5 is not a five-run production-shape measurement.
- `peak_rss_mb` comes from process `ru_maxrss`, a process-lifetime high-water mark rather than isolated incremental solver RSS. The table's measurements share one process; the oversupply figure includes the earlier fixed-434 high-water mark.
- In the fresh measurements, canonicalization used most of the solve time, especially for oversupply. Canonicalization was not optimized in this closure; benchmark it after RES-3l changes the isolation graph.

No protected membership was persisted, no candidate prose was materialized, and no human review was performed.
