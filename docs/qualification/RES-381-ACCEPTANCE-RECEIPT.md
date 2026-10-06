# RES-381 Acceptance Receipt

```text
MISSION=PSE-V1-CANONICAL-PLAN-REPRODUCIBILITY-001
STATUS=PASS
ENTRY_BRANCH=work/res-21-performance-science-eval-v1
ENTRY_HEAD=8443ca9e502637a9fde7d580028847d6e4b769e8
ENTRY_REMOTE_HEAD=8443ca9e502637a9fde7d580028847d6e4b769e8
ENTRY_TREE=CLEAN
WORK_BRANCH=julitocrztuga/res-381-p4a3l-r1-restore-canonical-joint-selection-reproducibility
PR_BASE=work/res-21-performance-science-eval-v1
FINAL_HEAD=REPORTED_IN_TASK_COMPLETION_MESSAGE
REMOTE_HEAD=REPORTED_IN_TASK_COMPLETION_MESSAGE
PR=REPORTED_IN_TASK_COMPLETION_MESSAGE

ROOT_CAUSE=30-candidate base-4 objectives exceeded binary64 exact-integer precision; CP-SAT returned OPTIMAL while the exact integer lower bound remained below the decoded objective
REPAIR=Fail closed on a nonmatching exact integer lower bound; qualify 15-candidate chunks in production profile v2
SOLVER_PROFILE=PSE-V1-PRODUCTION-SELECTION-SOLVER@1.0.0 preserved unchanged
CANONICALIZATION_PROFILE=PSE-V1-PRODUCTION-SELECTION-SOLVER@2.0.0; workers=8, random_seed=369, timeout_s=120, canonical_chunk_size=15, cp_model_presolve=false, randomize_search=false

OVERSUPPLY_PROBLEM_DIGEST=sha256:cdbacca413757e3295f97af0ae6ff06425d54161d1445f7420210f4410c83986
APPROVED_POOL_DIGEST=sha256:bde9abd144ce11eaecaaa87e94b4e02a581044614d7e7aa04c1b0de8be102014
AUTHORITY_DIGEST=sha256:0e4a80b7147fdd8a3f0df0f16c4478419d21d009f476c81513c6da512f96d2da
CONSTRAINT_INVENTORY_DIGEST=sha256:dc9d25f9e0f2850a794380693a4ad878eb70b788a3e08fc6a8f07e50425230aa
VALIDATED_WARM_START_PLAN_DIGEST=sha256:657543a3fe2ca381ad66aaf8ca7dac81de875bad0bd0214876501c9b5131e5a4
ORTOOLS=9.15.6755

PRE_REPAIR_UNIQUE_PLAN_DIGESTS=7 in 12 controlled local runs; 4 previously recorded; 11 distinct across both evidence sets
FIRST_DIVERGENT_CHUNK=3 (zero-based; candidates cell:C09:F12:0 through cell:C12:F07:2)
FIRST_DIVERGENT_CANDIDATE=cell:C12:F07:0

POST_REPAIR_FRESH_PROCESS_RUNS=5
POST_REPAIR_SAME_PROCESS_RUNS=5
POST_REPAIR_UNIQUE_PLAN_DIGESTS=1
POST_REPAIR_PLAN_DIGEST=sha256:7fad1ac2e83005996879b1f8d5ffb03c2536e93f87ebe2aae5468a8d815bc75d
POST_REPAIR_ALL_OPTIMAL=YES
POST_REPAIR_ALL_VALID=YES

FIXED434_PLAN_DIGEST=sha256:7dd3f236964f2f31561668553010078e1c443b3a8c41e572f226e10a9fc5aa1d
FIXED434_STABLE=YES

HARD_CONSTRAINTS_CHANGED=NO
DR001_CHANGED=NO
RES71_REFERENCES_CHANGED=NO
MATERIALIZATION_RUN=NO
HUMAN_REVIEW_RUN=NO
PROTECTED_MEMBERSHIP_PERSISTED=NO
PROTECTED_STORES_TOUCHED=NO
P4A.3M_STARTED=NO

QA=FULL_CI_PASS (1166 tests, 881.82s; Ruff, format, mypy, repository policy, tracked mutation)
COMMIT=REPORTED_IN_TASK_COMPLETION_MESSAGE
NEXT=P4A.3m (not started)
```

## Entry and runtime provenance

The checkout and its matching remote branch were clean at entry head
`8443ca9e502637a9fde7d580028847d6e4b769e8`. All runs used the synthetic
abstract fixtures from `tests/test_res369_selection.py`; no candidate prose,
canonical rows, or protected membership was materialized or persisted.

Runtime was Python 3.12.13 on Linux x86_64 / WSL2 with OR-Tools CP-SAT
9.15.6755. The oversupply input remained byte-order stable across runs:

```text
candidate_count=436
candidate_order_digest=sha256:3dfc10136da499608add95a3dc0ccd489bbb2fb856bcbc48572deb1c19676e66
approved_pool_digest=sha256:bde9abd144ce11eaecaaa87e94b4e02a581044614d7e7aa04c1b0de8be102014
authority_digest=sha256:0e4a80b7147fdd8a3f0df0f16c4478419d21d009f476c81513c6da512f96d2da
constraint_inventory_digest=sha256:dc9d25f9e0f2850a794380693a4ad878eb70b788a3e08fc6a8f07e50425230aa
validated_warm_start_plan_digest=sha256:657543a3fe2ca381ad66aaf8ca7dac81de875bad0bd0214876501c9b5131e5a4
```

`FinalSelectionProblem` sorts candidate IDs by UTF-8 bytes;
`SelectionConstraintSet` requires byte-sorted unique constraint IDs; allocation
clusters and relation members are sorted before model construction. Balance
cells are sorted after set construction, and mutation lineages are sorted
before variables are created. The candidate-order digest and all four problem
authority digests above matched in every process. No unordered collection
determines canonical ordering.

## Pre-repair reproduction and controlled ablations

All 12 controlled pre-repair solves returned `OPTIMAL/VALID`. Every run had
balance objective `561148`, hash-preference objective `208`, split counts
`260/87/87`, 28 selected mutation lineages, and selected origin counts:

```text
DETERMINISTIC_SYNTHETIC=15
DETERMINISTIC_ENGINE_DERIVED=35
EXPERT_AUTHORED_SEMANTIC=231
SOURCE_BACKED_EVIDENCE_EXTRACTION=42
ADVERSARIAL_MUTATION=111
```

| Ablation | Runs | Result |
| --- | ---: | --- |
| Sealed v1 profile; same process | 2 | Two digests: `5508e450…` and `7fad1ac2…` |
| Sealed v1 profile; fresh processes | 2 | Two digests: `27d5e5d8…` and `c968ce08…` |
| Canonicalization workers 1; all other v1 settings unchanged | 2, same process | Two digests: `7fad1ac2…` and `89639a7d…`; workers alone did not repair it |
| Chunk size 15; workers 8 and warm start retained | 2, same process | Same digest `7fad1ac2…`; all 30 chunk objective values and bounds matched exactly |
| Warm start removed; v1 workers and chunk size retained | 2, same process | Two digests: `c968ce08…` and `5508e450…`; warm start was not causal |
| Sealed v1 repeat with exact lower-bound instrumentation | 2, same process | Two digests: `ebe83ab5…` and `57efac17…`; exposed an OPTIMAL result with an exact integer gap |

The four previously recorded digests were
`44dc18b16ad96940e736b4f9e41319d439e56b3db906d0c4101734dd45c6b97c`,
`2909aaaf31957499e21ebc5ec1d89bc9b6f31663e197c83ddebd1b7e8903e018`,
`34e01e9426072bab43938d20c673a303ba99498c5dc3023f00bdf975de935705`, and
`10905e20f5232c40f2e035a39ddb320a3e8bd8e424c8f0f6fe2a5388b52e1188`.
The seven distinct digests produced across the 12 local controls were:

```text
sha256:5508e450a25297acea0bb903c8992781bf937ac1cfbc34a404ae0fb2e26e8ed5
sha256:7fad1ac2e83005996879b1f8d5ffb03c2536e93f87ebe2aae5468a8d815bc75d
sha256:27d5e5d86b69b4967d7a276bc662a0845013f873c0e39512a37698a6cdea2ec7
sha256:c968ce083a0b11210b87a6852515448c0c4be2542cd732b07b514b9cb6c8d49d
sha256:89639a7d9126e0366d3855ccf9c6a9cd28c1b431d4a109a91c144fc7586e7867
sha256:ebe83ab57aff014964b09b60c639a20a9a8c466b1166dbb2cac0596bbef4f678
sha256:57efac173e27a8408ed0af69c685287131827a493c487209fcf0f2eb65c46c2c
```

### First divergence and exact bound

In the baseline same-process pair (`5508e450…` versus `7fad1ac2…`), the first
different canonical objective was chunk 3, covering
`cell:C09:F12:0` through `cell:C12:F07:2`. The first different assignment was
`cell:C12:F07:0` (`HIDDEN_FINAL` versus `PUBLIC_DEVELOPMENT`). The exact chunk
objectives were `818449412966217462` and `818449412966217438`; both chunks
reported `OPTIMAL` and the same double bound
`8.184494129662175e+17`.

The exact-bound repeat captured the root cause directly. In its first run,
chunk 3 had objective `818449412966217462`, but
`inner_objective_lower_bound=818449412966217438`; the second run had objective
and lower bound `818449412966217438`. Both returned `OPTIMAL`. The objective
and bound fields in the OR-Tools 9.15 response proto are `double`, while its
integer lower-bound field is `int64` ([pinned OR-Tools 9.15 source](https://github.com/google/or-tools/blob/v9.15/ortools/sat/cp_model.proto)).
At this magnitude a binary64 ULP is 128, so costs 24 apart expose the same
objective and bound. The old 30-candidate base-4 maximum was
`4^30 - 1 = 1,152,921,504,606,846,975`: within signed int64, but above the
binary64 exact-integer ceiling `2^53 = 9,007,199,254,740,992`.

For every pair among the seven distinct local pre-repair plans, both plans had
the same primary objective values, selected origin counts, lineage count, and
split counts listed above. The table records each pair's first assignment
difference and its full assignment-difference count. Chunk indices are
zero-based; each row's exact encoded objective is shown for the corresponding
chunk in plan A and plan B. Complete changed-assignment lists and per-run
chunk traces are retained outside Git in `/tmp/res381-pre-pairwise.json`
(SHA-256 `ddf95821416a92014d52632aae1dad70ba6e552e376e50d913ec7b4c518ddbaa`).

| Plan A / plan B (digest prefixes) | First differing candidate and states | Changed assignments | Chunk A / B | Exact chunk objective A / B |
| --- | --- | ---: | ---: | ---: |
| 5508e450 / 7fad1ac2 | `cell:C12:F07:0`: HIDDEN_FINAL → PUBLIC_DEVELOPMENT | 7 | 3 / 3 | 818449412966217462 / 818449412966217438 |
| 5508e450 / 27d5e5d8 | `cell:C06:F13:1`: PUBLIC_DEVELOPMENT → FROZEN_VALIDATION | 9 | 1 / 1 | 495085586111903478 / 495085586111903481 |
| 5508e450 / c968ce08 | `cell:C12:F07:0`: HIDDEN_FINAL → PUBLIC_DEVELOPMENT | 5 | 3 / 3 | 818449412966217462 / 818449412966217438 |
| 5508e450 / 89639a7d | `cell:C12:F07:0`: HIDDEN_FINAL → PUBLIC_DEVELOPMENT | 6 | 3 / 3 | 818449412966217462 / 818449412966217438 |
| 5508e450 / ebe83ab5 | `cell:C14:F11:0`: FROZEN_VALIDATION → HIDDEN_FINAL | 4 | 4 / 4 | 548152411993046445 / 548152411993046457 |
| 5508e450 / 57efac17 | `cell:C12:F07:0`: HIDDEN_FINAL → PUBLIC_DEVELOPMENT | 9 | 3 / 3 | 818449412966217462 / 818449412966217438 |
| 7fad1ac2 / 27d5e5d8 | `cell:C06:F13:1`: PUBLIC_DEVELOPMENT → FROZEN_VALIDATION | 2 | 1 / 1 | 495085586111903478 / 495085586111903481 |
| 7fad1ac2 / c968ce08 | `cell:C18:F07:1`: FROZEN_VALIDATION → HIDDEN_FINAL | 2 | 7 / 7 | 501761817242986203 / 501761817242986206 |
| 7fad1ac2 / 89639a7d | `cell:C14:F11:0`: FROZEN_VALIDATION → HIDDEN_FINAL | 5 | 4 / 4 | 548152411993046445 / 548152411993046457 |
| 7fad1ac2 / ebe83ab5 | `cell:C12:F07:0`: PUBLIC_DEVELOPMENT → HIDDEN_FINAL | 11 | 3 / 3 | 818449412966217438 / 818449412966217462 |
| 7fad1ac2 / 57efac17 | `extra:expert:008`: PUBLIC_DEVELOPMENT → FROZEN_VALIDATION | 2 | 8 / 8 | 549076221055292757 / 549076221055292758 |
| 27d5e5d8 / c968ce08 | `cell:C06:F13:1`: FROZEN_VALIDATION → PUBLIC_DEVELOPMENT | 4 | 1 / 1 | 495085586111903481 / 495085586111903478 |
| 27d5e5d8 / 89639a7d | `cell:C06:F13:1`: FROZEN_VALIDATION → PUBLIC_DEVELOPMENT | 7 | 1 / 1 | 495085586111903481 / 495085586111903478 |
| 27d5e5d8 / ebe83ab5 | `cell:C06:F13:1`: FROZEN_VALIDATION → PUBLIC_DEVELOPMENT | 13 | 1 / 1 | 495085586111903481 / 495085586111903478 |
| 27d5e5d8 / 57efac17 | `cell:C06:F13:1`: FROZEN_VALIDATION → PUBLIC_DEVELOPMENT | 4 | 1 / 1 | 495085586111903481 / 495085586111903478 |
| c968ce08 / 89639a7d | `cell:C14:F11:0`: FROZEN_VALIDATION → HIDDEN_FINAL | 7 | 4 / 4 | 548152411993046445 / 548152411993046457 |
| c968ce08 / ebe83ab5 | `cell:C12:F07:0`: PUBLIC_DEVELOPMENT → HIDDEN_FINAL | 9 | 3 / 3 | 818449412966217438 / 818449412966217462 |
| c968ce08 / 57efac17 | `cell:C18:F07:1`: HIDDEN_FINAL → FROZEN_VALIDATION | 4 | 7 / 7 | 501761817242986206 / 501761817242986203 |
| 89639a7d / ebe83ab5 | `cell:C12:F07:0`: PUBLIC_DEVELOPMENT → HIDDEN_FINAL | 6 | 3 / 3 | 818449412966217438 / 818449412966217462 |
| 89639a7d / 57efac17 | `cell:C14:F11:0`: HIDDEN_FINAL → FROZEN_VALIDATION | 7 | 4 / 4 | 548152411993046457 / 548152411993046445 |
| ebe83ab5 / 57efac17 | `cell:C12:F07:0`: HIDDEN_FINAL → PUBLIC_DEVELOPMENT | 13 | 3 / 3 | 818449412966217462 / 818449412966217438 |

## Repair and post-repair qualification

The solver now accepts a canonical chunk only when its exact `int64`
`inner_objective_lower_bound` equals the decoded integer objective. A mismatch
returns `UNKNOWN` with no plan. This preserves fail-closed behavior even when
a caller uses the old 30-candidate configuration.

Production profile `@2.0.0` uses 15 candidates per base-4 chunk. Its maximum
objective is `4^15 - 1 = 1,073,741,823`, below `2^53`, so every chunk objective
and double-valued bound is exactly representable. The 120-second solver limit
is versioned with v2: a separate 60-second v2 trial hit the hash-preference
limit with incumbent 220 and lower bound 208, correctly returning `UNKNOWN`.
Profile v1 remains unchanged at workers 8, seed 369, timeout 60, chunk size
30, presolve disabled, and search randomization disabled.

The final oversupply qualification used profile v2, identical validated warm
start content, and the unchanged problem digest. Same-process runs share PID
305231; fresh-process PIDs are distinct.

| Process class | Run | PID | Wall seconds | Status / validation | Plan digest |
| --- | ---: | ---: | ---: | --- | --- |
| Same | 1 | 305231 | 194.292 | OPTIMAL / VALID | `sha256:7fad1ac2e83005996879b1f8d5ffb03c2536e93f87ebe2aae5468a8d815bc75d` |
| Same | 2 | 305231 | 152.860 | OPTIMAL / VALID | same |
| Same | 3 | 305231 | 175.199 | OPTIMAL / VALID | same |
| Same | 4 | 305231 | 178.707 | OPTIMAL / VALID | same |
| Same | 5 | 305231 | 160.696 | OPTIMAL / VALID | same |
| Fresh | 1 | 308983 | 162.759 | OPTIMAL / VALID | same |
| Fresh | 2 | 309543 | 145.882 | OPTIMAL / VALID | same |
| Fresh | 3 | 310005 | 142.155 | OPTIMAL / VALID | same |
| Fresh | 4 | 310392 | 164.623 | OPTIMAL / VALID | same |
| Fresh | 5 | 310732 | 181.346 | OPTIMAL / VALID | same |

All ten runs had the same full assignment map and the same:

```text
problem_digest=sha256:cdbacca413757e3295f97af0ae6ff06425d54161d1445f7420210f4410c83986
balance_objective=561148
hash_preference_objective=208
split_counts=260/87/87
selected_origin_counts=synthetic:15, engine-derived:35, expert-authored:231, source-backed:42, mutation:111
selected_mutation_lineages=28
warm_start_plan_digest=sha256:657543a3fe2ca381ad66aaf8ca7dac81de875bad0bd0214876501c9b5131e5a4
```

Each run returned `OPTIMAL` for both primary objectives and all 30 canonical
chunks. The integer lower bound equaled the exact objective for all
`10 × 32 = 320` objective solves. The maximum observed canonical chunk
objective was `920,349,150`. Private run traces, including all prefix
assignment digests, objective values, bounds, timings, and full assignments,
remain outside Git at `/tmp/res381-final-post-same.jsonl` and
`/tmp/res381-final-post-fresh.jsonl` (SHA-256 `d7deab54157b1b7810ef8a834bd029261afdc69548aed28bf80cef35046ce387` and
`77be014cc9003e9e4ce15c98633e871463dde970c0ad6db6c84779e04ad63d1f`).

Fixed-434 was run once with profile v2 and returned `OPTIMAL/VALID`, unchanged
plan digest `sha256:7dd3f236964f2f31561668553010078e1c443b3a8c41e572f226e10a9fc5aa1d`,
and exact integer lower-bound equality for all 29 chunks. Its private trace is
`/tmp/res381-fixed434.jsonl` (SHA-256
`4dcbabadf825f7befba0ab9f6bf9a928b6d0bc7c12c5794815301791aabe0acd`).

## QA and scope

- Focused profile, fail-closed, and five-run toy regression tests: PASS (3).
- Ruff check and formatting check for changed Python files: PASS.
- Full CI: PASS, 1,166 tests in 881.82s; Ruff, formatting, mypy, repository
  policy, and tracked-mutation checks all passed.
- Scientific constraints, objective order, independent validation, RES-71
  reference identities, DR-001, fixtures, and serialization: unchanged.
- Candidate materialization: not run. Human review: not run. Protected final
  membership: not persisted. Protected stores: untouched.
- P4A.3m reserve design: not started.

The next authorized mission is P4A.3m; this receipt does not begin it.
