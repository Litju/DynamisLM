# RES-249 A/B/C redesign benchmark receipt

```text
MISSION=PSE-V1-ABC-REDESIGN-BENCHMARK-001
STATUS=PASS
ENTRY_HEAD=30851a3b57458ef856584625fac8bb45f24ec7eb
IMPLEMENTATION_HEAD=bc1c507c2546d3a3c840d90b5ea24a44164af2fe
FINAL_HEAD=bc1c507c2546d3a3c840d90b5ea24a44164af2fe

BASELINE_ORIGIN_VECTOR=240/40/31/12/111
BASELINE_MUTATION_ROOTS=37
BASELINE_PREFIX_SELECTOR_REPRODUCED=YES
BASELINE_R1_VIOLATING_CELLS=14
BASELINE_BASE_STATUS=INFEASIBLE
BASELINE_COLOCATION_STATUS=INFEASIBLE
BASELINE_CNF_DIGESTS_MATCH_RES224=YES

DESIGN_A_R1=FAIL
DESIGN_A_BASE=INFEASIBLE
DESIGN_A_COLOCATION=INFEASIBLE
DESIGN_A_CROSSCHECK=FAIL
DESIGN_A_CONTENT_CHANGES=51
DESIGN_A_MUTATION_CHILDREN_REGENERATED=51
DESIGN_A_FORCEABLE_MIN=NOT_APPLICABLE_INFEASIBLE
DESIGN_A_RUNTIME_MEDIAN_S=142.673
DESIGN_A_PEAK_RSS_MB=725.0
DESIGN_A_DETERMINISM=PASS

DESIGN_B_R1=PASS
DESIGN_B_BASE=FEASIBLE
DESIGN_B_COLOCATION=FEASIBLE
DESIGN_B_CROSSCHECK=PASS
DESIGN_B_CONTENT_CHANGES=41
DESIGN_B_MUTATION_CHILDREN_REGENERATED=30
DESIGN_B_FORCEABLE_MIN=1
DESIGN_B_RUNTIME_MEDIAN_S=193.991
DESIGN_B_PEAK_RSS_MB=1244.6
DESIGN_B_DETERMINISM=PASS

DESIGN_C_R1=PASS
DESIGN_C_BASE=FEASIBLE
DESIGN_C_COLOCATION=FEASIBLE
DESIGN_C_CROSSCHECK=PASS
DESIGN_C_CONTENT_CHANGES=55
DESIGN_C_MUTATION_CHILDREN_REGENERATED=51
DESIGN_C_FORCEABLE_MIN=1
DESIGN_C_RUNTIME_MEDIAN_S=173.069
DESIGN_C_PEAK_RSS_MB=602.5
DESIGN_C_DETERMINISM=PASS

ABC_BENCHMARK_DIGEST=sha256:b75fd19c8ecdb87a085cb9de36c6ac10130e415406bf390677c7fb49eb26d2f6
SELECTED_DESIGN=B
SELECTION_BASIS=B_PASSES_GATES_1_TO_3_AND_DOMINATES_C_AT_4_LOWER_SCIENTIFIC_EDIT_SURFACE

PRODUCTION_AUTHORING_CHANGE_AUTHORIZED=NO
MATERIALIZATION_AUTHORIZED=NO

CANDIDATE_CONTENT_CHANGED=NO
PRODUCTION_AUTHORING_CHANGED=NO
MATERIALIZATION_RUN=NO
FINAL_SPLIT_ALLOCATION_PERFORMED=NO
RES225_COST_CLOSURE_RESUMED=NO
SPLIT_MEMBERSHIP_PERSISTED=NO

QA=PASS
TEST_COUNT=1131
QA_TRACKED_MUTATION=NONE

NEXT=implement-and-materialize-design-B (separate mission)
```

`IMPLEMENTATION_HEAD` is the code that produced every private record below;
this receipt is recorded in a later documentation-only commit.
`DESIGN_A_CROSSCHECK=FAIL` means "not PASS": CP-SAT proved both A models
INFEASIBLE, the bounded blind Glucose search was UNKNOWN at its 600 s cap on
both, and there was no disagreement. A's infeasibility is independently
certified by its R1 violation and the solver-free bound below. Runtime medians
are end-to-end per run (build + CP-SAT BASE/COLOCATION + PB encode + witness
model check + 60 s-capped blind Glucose per model).

## Selection trace

```text
A:ELIMINATED_AT=2_STRUCTURAL_R1
4_LOWER_SCIENTIFIC_EDIT_SURFACE:DOMINATES:B   (B 41 < C 55)
```

The strict hierarchy decided at criterion 4; criteria 5-8 were not needed and
no weighted score was used. For the record, B and C are tied or near-tied on
resilience (both FORCEABLE_MIN=1; B has fewer single-failure-fatal components,
40 vs 42), both pass determinism/restart, and B has the higher build time and
peak RSS.

## Method

All four columns use one code path:

- `build_redesign(strategy, sealed)` returns a typed `AbstractProductionDesign`
  for `CURRENT`, `A`, `B`, or `C`. Every strategy materializes through the same
  `materialize_plan` (typed metadata and placeholder hashes only).
- Strategies differ only in permitted action families, root baseline, and the
  lexicographic objective (no weighted score):
  - **A**: root reselection only. Objectives: capacity deficit, roots changed,
    root cells changed, max roots per cell, min V/H capacity, cells with
    capacity >= 3.
  - **B**: current roots as baseline plus the full vocabulary — root
    reselection / reparent to any compatible expert, root content replacement,
    semantic cell reassignment (role copied from a sealed variant in the target
    cell), and semantic template rebind. Objectives: capacity deficit, unique
    changed slots, roots changed, children regenerated, reassignments, parent
    changes, new template bindings, distribution deviation.
  - **C**: A's best root reselection first, then the smallest downstream
    B-family subset with roots fixed. Objectives (relative to A's plan):
    capacity deficit, downstream content changes, children regenerated,
    downstream actions, resilience. C's total edit surface is A's 51 plus 4.
- Inadmissible families are represented with mechanical reasons:
  lineage-size reduction (frozen 37 x 3), source/engine replacement (no
  demonstrated authority supply), synthetic replacement (frozen seed locks).
- The optimizer embeds the production COLOCATION constraint families (COUNT,
  CELL, ROW_TAG, ROW_ERROR, C18_REFUSAL, ANSWERABLE, SYNTHETIC_LOCK, CRITICAL)
  over every component a plan can produce, so a returned plan is
  COLOCATION-feasible by construction. A falls back to its least-deficient
  necessary-condition plan only when its exact action space is infeasible.
- The common validator then re-checks every design independently: scientific
  gate, R1 on BASE and COLOCATION, CP-SAT BASE/COLOCATION, and an independent
  PB/CNF (RES-224 encoder) + Glucose 4 path: witness model check against the
  independent CNF, blind bounded search, DRAT-checked UNSAT.
- Solver configuration is identical for every design: CP-SAT 9.15.6755,
  8 workers with `interleave_search` (deterministic), seed 0, presolve, no
  hints, deterministic-time bound 120.

## R1 definition

Validation and Hidden each hold 87 cases for 87 capability x family cells, so
every protected case must discharge a distinct cell. A component may enter a
protected split only when all its items discharge their own cell obligation
(C18 items additionally discharge refusal), its cells are pairwise distinct,
and no synthetic lock pins it to Public. R1 requires, per cell, >= 2 such
components with a distinct V/H matching and >= 3 covering components overall.
R1 is a necessary condition: an R1 violation alone certifies BASE and
COLOCATION infeasibility.

## Design A impossibility (solver-free)

Every lineage root carries three same-cell mutation children in its atomic
component, so a root component can never serve Validation or Hidden. A cell
with `s` semantic slots and `f` fixed V/H-eligible components therefore admits
at most `s + f - 2` roots under R1.

`comparability-overreach` requires 7 roots, all in C07. C07 has 4 cells, each
with 3 semantic slots and no source, engine, or synthetic component, so the
bound is `4 x (3 + 0 - 2) = 4 < 7`. No root reselection can satisfy R1; Design
A is infeasible for every choice of roots. A's column reports its
least-deficient relaxed plan (deficit 8; residual violations C07:F04 and
C07:F06).

Other operators are within their bounds (identity 12 >= 7, claim 8 >= 7,
refusal 22 >= 8, error 14 >= 8).

## Independent cross-check definition

- FEASIBLE: CP-SAT witness passes the production semantic validator
  (`_validate_exact_rank_assignment` + `_exact_aggregate_evidence`), and the
  independently encoded CNF accepts the witness (Glucose with the witness as
  assumptions), and the blind Glucose search does not return UNSAT.
- INFEASIBLE: blind Glucose UNSAT with a DRAT-trim `s VERIFIED` certificate and
  CP-SAT not FEASIBLE.
- Bounded blind Glucose search alone could not settle the feasible designs'
  COLOCATION models within 600 s; feasibility is certified by the witness model
  check against the independent encoding, never by an unchecked assertion.

## Benchmark matrix

Five deterministic runs per design, each in a fresh subprocess, on one machine
(8 cores, 19 GB, WSL2) with OR-Tools 9.15.6755, PySAT 1.9.dev15, PyPBLib 0.0.4.

| Metric | CURRENT | A | B | C |
|---|---|---|---|---|
| SCIENTIFIC_GATE | PASS | PASS | PASS | PASS |
| ORIGIN_COUNTS | 240/40/31/12/111 | 240/40/31/12/111 | 240/40/31/12/111 | 240/40/31/12/111 |
| LINEAGES x CHILDREN | 37x3 | 37x3 | 37x3 | 37x3 |
| R1_VIOLATING_CELLS | 14 | 2 | 0 | 0 |
| MIN_VH_ELIGIBLE_COMPONENTS | 0 | 0 | 2 | 2 |
| MEDIAN_VH_ELIGIBLE_COMPONENTS | 3 | 3 | 3 | 3 |
| MAX_VH_ELIGIBLE_COMPONENTS | 16 | 16 | 16 | 16 |
| CELLS_WITH_EXACTLY_2 / GE_3 | 11 / 62 | 34 / 51 | 34 / 53 | 36 / 51 |
| BASE_STATUS | INFEASIBLE | INFEASIBLE | FEASIBLE | FEASIBLE |
| COLOCATION_STATUS | INFEASIBLE | INFEASIBLE | FEASIBLE | FEASIBLE |
| CP-SAT BASE / COLOCATION | INFEASIBLE / INFEASIBLE | INFEASIBLE / INFEASIBLE | FEASIBLE / FEASIBLE | FEASIBLE / FEASIBLE |
| GLUCOSE BLIND BASE / COLOCATION | UNSAT / UNSAT | UNKNOWN / UNKNOWN | UNKNOWN / UNKNOWN | UNKNOWN / UNKNOWN |
| DRAT BASE / COLOCATION | PASS / PASS | NOT_APPLICABLE / NOT_APPLICABLE | NOT_APPLICABLE / NOT_APPLICABLE | NOT_APPLICABLE / NOT_APPLICABLE |
| INDEPENDENT_CROSSCHECK | PASS | FAIL (BASE UNKNOWN, COLOCATION UNKNOWN) | PASS | PASS |
| ROOTS_CHANGED | 0 | 17 | 10 | 17 |
| SEMANTIC_SLOTS_CHANGED (reassigned/rebound/root replaced) | 0 (0/0/0) | 0 (0/0/0) | 11 (11/0/0) | 4 (4/0/0) |
| MUTATION_LINEAGES_REPARENTED | 0 | 17 | 10 | 17 |
| MUTATION_CHILDREN_REGENERATED | 0 | 51 | 30 | 51 |
| CANDIDATE_IDS / HASHES CHANGED | 0 / 0 | 51 / 51 | 41 / 41 | 55 / 55 |
| AUTHOR_BATCH_TEMPLATE_IDS_CHANGED | 0 | 0 | 11 | 4 |
| SOURCE / ENGINE / SYNTHETIC CHANGED | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |
| TOTAL_CONTENT_CHANGES | 0 | 51 | 41 | 55 |
| ATOMIC_COMPONENTS (COLOCATION / BASE) | 194 / 218 | 194 / 218 | 200 / 224 | 196 / 220 |
| COMPONENT_SIZE_DISTRIBUTION | 1:77, 2:77, 3:1, 4:19, 5:12, 8:8 | 1:81, 2:78, 3:1, 4:15, 5:6, 8:13 | 1:85, 2:77, 3:1, 4:23, 5:4, 8:10 | 1:83, 2:78, 3:1, 4:17, 5:4, 8:13 |
| MAX_COMPONENT_SIZE | 8 | 8 | 8 | 8 |
| MUTATION_BLOCK_SIZES | 4:14, 5:11, 8:6 | 4:10, 5:5, 8:11 | 4:18, 5:3, 8:8 | 4:12, 5:3, 8:11 |
| FORCEABLE_MIN | N/A | N/A | 1 | 1 |
| FORCEABLE_P25 / MEDIAN / P75 / MAX | N/A | N/A | 2.0 / 3.0 / 3.0 / 16 | 2.0 / 3.0 / 3.0 / 16 |
| FORCEABLE_EQ1 | N/A | N/A | 8 | 8 |
| FORCEABLE_EQ2 | N/A | N/A | 60 | 64 |
| FORCEABLE_GE3 | N/A | N/A | 106 | 102 |
| DISTINCT_WITNESSES (bounded) | N/A | N/A | 45 | 38 |
| SINGLE_COMPONENT_FAILURE_FATAL | N/A | N/A | 40 | 42 |
| BUILD_TIME_MEDIAN_S | 0.0126 | 14.3343 | 69.842 | 48.3 |
| BASE_TIME_MEDIAN_S | 0.0859 | 0.0809 | 1.0548 | 1.0446 |
| COLOCATION_TIME_MEDIAN_S | 0.0856 | 0.085 | 1.0914 | 1.1509 |
| PB_ENCODE_TIME_MEDIAN_S | 1.2715 | 1.275 | 1.3275 | 1.3481 |
| SAT_TIME_MEDIAN_S (blind, 60 s cap per model) | 30.6064 | 126.6749 | 120.3134 | 120.3212 |
| END_TO_END_MEDIAN_S (min / max) | 32.5496 (31.5956 / 33.2541) | 142.673 (142.1415 / 143.9324) | 193.9912 (187.4256 / 206.9256) | 173.0687 (171.8831 / 179.5093) |
| CANONICAL_SELF_REDUCTION (once) | NOT_RUN_INFEASIBLE | NOT_RUN_INFEASIBLE | PASS 45.0966 s | PASS 43.0368 s |
| PEAK_RSS_MB | 725.0 | 725.0 | 1244.6 | 602.5 |
| CP-SAT VARS / CONSTRAINTS (COLOCATION) | 582 / 876 | 582 / 876 | 600 / 882 | 588 / 878 |
| CNF_VARIABLES (BASE / COLOCATION) | 51220 / 43564 | 50950 / 42881 | 53365 / 45361 | 51751 / 43611 |
| CNF_CLAUSES (BASE / COLOCATION) | 151230 / 128808 | 150420 / 126759 | 157563 / 134097 | 152783 / 128909 |
| PRIVATE_ARTIFACT_BYTES | 187362169 | 187356606 | 130519995 | 188147081 |
| DETERMINISM_5_OF_5 | PASS | PASS | PASS | PASS |
| RESTART_IDEMPOTENT | PASS | PASS | PASS | PASS |
| ENGINEERING_COMPLEXITY | N/A | LOW (1 families, 1 touch points, 1 solver models) | MEDIUM (2 families, 4 touch points, 1 solver models) | MEDIUM (2 families, 4 touch points, 2 solver models) |


FORCEABLE counts are over 87 cells x 2 protected splits. Cells with
FORCEABLE=1 include the C08 synthetic-locked and C16 engine cells, whose split
or lane structure admits one component per split.

## Adversarial perturbations (abstract copies only)

| Probe | A | B | C |
|---|---|---|---|
| Remove one low-redundancy component (C01:F01) | N/A (infeasible) | INFEASIBLE | INFEASIBLE |
| Reject one root (rebuild) | R1 FAIL (2), INFEASIBLE | survives, 41 changes | survives, 55 changes |
| Remove one newly selected target parent (rebuild) | R1 FAIL (2), INFEASIBLE | survives, 41 changes | survives, 55 changes |
| Force one protected-split choice (Validation) | N/A | FEASIBLE | FEASIBLE |
| Probe determinism (2 repeats) | PASS | PASS | PASS |

C01:F01 retains exactly two V/H-eligible components in B and C, so losing one
is fatal; this is the dominant low-redundancy risk for materialization review.

## Reliability

For every design: stale authority fingerprint rejected, interrupted
construction restarts to the identical design digest, a bounded
deterministic-time solve returns UNKNOWN and never FEASIBLE without a validated
witness, and private records refuse split-membership keys.

During the first benchmark attempt the 5-run probe showed B returning a
different equally optimal plan per process. That run was discarded; commit
`bc1c507` canonicalizes the pinned optimum (lexicographically smallest decision
vector, independent of search path), all private records were regenerated, and
B is 5/5 deterministic.

## Private artifacts

```text
PRIVATE_ARTIFACT_ROOT=/mnt/e/Data/Datasets/DynamisLM/PerformanceScienceEval/production/diagnostics/RES-249
SEALED_AUTHORITY_FINGERPRINT=sha256:0f017477a8e8d3ff01e890da41a01bb0b84371e27cccc78efba67cc9b21495ae
SEALED_BASELINE_FILE_SHA256=036935d6c51e920e78613d4f660c9239df5a398712b3bd6a81162f5b8f00aefc
BENCHMARK_MATRIX_FILE_SHA256=c65a1ec0a604a6fa971d1c86cb89bb5ed4e13cac086c7d689c658d5e5a65be3a
DESIGN_B_FILE_SHA256=da0b33dc8cf156714b50b7e01f20a74a9bb77bdba90e4cb14d87bcea6bc5b2c4
DESIGN_B_DIGEST=sha256:b451cbd57437deec803085c21643505b2b4b45d1e8d83909c067d4a95c1d74ad
DESIGN_B_CHANGED_CANDIDATE_IDS_DIGEST=sha256:db5387f7dfbd5b1d6858d8bd7b43744db3a75d04509eaf125c18d9375fbf0799
DESIGN_B_CAPACITY_MATRIX_DIGEST=sha256:5afed526f1012a2230855416232ee4fc94bedfeed2968334ec2f0aebbf825c7b
DESIGN_B_RESILIENCE_MATRIX_DIGEST=sha256:6f2007fcfb5abb99ac126452229a3677f0d0e68f9d229832e46307561021d13f
DESIGN_B_CANONICAL_WITNESS_DIGEST=sha256:641c6e498b5136ed127dd36f946b0525bbe2d9da24abde24d3bb4a9a7438aba7
PRIVATE_FILES=32
PRIVATE_BYTES=190507342
```

The sealed baseline, A/B/C abstract designs, R1 capacity matrices, feasibility
and independent-witness records, DRAT proofs, resilience matrices, run samples,
perturbation results, and the selection record stay outside Git. The private
authoring inputs and RES-223 plan hashes were re-checked unchanged around the
read-only baseline capture.

## Claim ceiling

The selection is over the frozen constitution as encoded by the production
exact models, the current 434-slot identities, and the RES-249 action
vocabulary. B's 41-slot edit surface is the proven optimum of that vocabulary
(every lexicographic level OPTIMAL). It is not a claim about candidate content
quality; materialized B content must still pass review, exclusion, duplication,
and the exact oracle in the follow-up mission.
