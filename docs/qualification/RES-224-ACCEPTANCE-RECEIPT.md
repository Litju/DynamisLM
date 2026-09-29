# RES-224 acceptance receipt

```text
MISSION=RES-224-UNKNOWN-RESOLUTION-001
STATUS=PASS
ENTRY_HEAD=7cfbb7a73a91090c86d728d68c0614224f60cf9e
IMPLEMENTATION_HEAD=3c3c8807e3488c213c689649b3f51c44f9c4eee6
FINAL_HEAD=3c3c8807e3488c213c689649b3f51c44f9c4eee6
RECEIPT_BINDING_HEAD=97812c430a80b606600fb2bac4caac486f1bfb72

RES223_IMPLEMENTATION_HEAD=79904ed1da9c0f5f351330b878b4570d035c8a48
RES223_RECEIPT_BINDING_HEAD=7cfbb7a73a91090c86d728d68c0614224f60cf9e
RES223_RECEIPT_PROVENANCE=RECONCILED

PRODUCTION_CANDIDATES=434
TARGET_COUNTS=260/87/87
ORIGIN_COUNTS_CHANGED=NO
SCIENTIFIC_ISOLATION_CHANGED=NO
RES71_AUTHORITY_CHANGED=NO
RES223_AUTHOR_BATCH_TOPOLOGY_CHANGED=NO
CANDIDATE_QUESTIONS_CHANGED=NO
EXPECTED_ANSWERS_CHANGED=NO
SOURCE_EVIDENCE_CHANGED=NO
CONTAMINATION_THRESHOLDS_CHANGED=NO

BASE_FINAL_STATUS=INFEASIBLE
COLOCATION_FINAL_STATUS=INFEASIBLE
INDEPENDENT_SOLVER_USED=YES
INDEPENDENT_RESULT=BASE_UNSAT_PROOF_CHECKED;COLOCATION_UNSAT_PROOF_CHECKED
VALIDATED_WITNESS=NO
CANONICAL_SELF_REDUCTION=NOT_RUN
CANONICAL_WITNESS_DIGEST=NONE
FEASIBILITY_MEMBERSHIP_PERSISTED=NO

CANDIDATE_CONTENT_CHANGED=NO
SCIENTIFIC_TOPOLOGY_CHANGED=NO
PRODUCTION_STORE_PROMOTED=NO
FINAL_SPLIT_ALLOCATION_PERFORMED=NO
MODEL_TRAINING_RUN=NO

QA=PASS
TEST_COUNT=1055
QA_TRACKED_MUTATION=NONE
NEXT=candidate-design repair
CANDIDATE_DESIGN_REPAIR_AUTHORIZED=YES
CANDIDATE_DESIGN_REPAIR_EXECUTED=NO
PR_CREATED=NO
MERGE_PERFORMED=NO
```

`IMPLEMENTATION_HEAD` and `FINAL_HEAD` identify the code and probe commit.
`RECEIPT_BINDING_HEAD` identifies the commit that first recorded this receipt;
this later documentation-only commit makes that provenance explicit. No
implementation changes follow `IMPLEMENTATION_HEAD`.

## Reconstructed models

```text
COMMITMENTS_DIGEST=sha256:b009d1bebbd026821f7dc136efb8719bb4c5dc7007a8a05f248b468dc3a4743a
COLOCATION_EDGE_DIGEST=sha256:922c19b9243f7a6cd56c22463db826607c1980edea9bb9b394feab0c5fcd02a4
BASE_COMPONENTS=218
COLOCATION_COMPONENTS=194
BASE_MODEL_DIGEST=sha256:691e5163da6854cc0697e89ff320a1f3f185b0a086fb10748be21a2e81c9eafc
COLOCATION_MODEL_DIGEST=sha256:02db17410d7aa1991b521eac8fac5f75a59fce30fde0c798e7a094d59d1df09d
BASE_CONSTRAINT_SET_DIGEST=sha256:0e8a6ffdb62906dd75294f5e8daf79ece4bc4fb1853ed574140a489ecc341433
COLOCATION_CONSTRAINT_SET_DIGEST=sha256:3db0a851e574436f644bdfc890705a07ef230e3886b57a912b808d1eb0a62a2f
SOLVER_CONFIG_DIGEST=sha256:cff15b97f72c4a72fb7f09af3baef401021dd69303585258a4902daace4fd189
ORTOOLS_VERSION=9.15.6755
```

Canonical Boolean model protos were exported outside Git:

| Model | SHA-256 | Bytes |
|---|---|---:|
| BASE | `sha256:cd5de2106bf2f6efc65b20c361f92ac3cf582af234f4b497e636d5e67254a407` | 42,927 |
| COLOCATION | `sha256:6e84514d0c022b9a8ec2bf8334b9d6e3473a4ff1f43344228a6042ec752138ef` | 39,833 |

## Progressive submodels

The telemetry columns report wall seconds, deterministic time, branches,
conflicts, and binary/integer propagations. The private artifact also stores
user time, Boolean count, restarts, LP iterations, presolved counts,
`solution_info`, solver configuration, and presolve/search/complete-log digests.

| Probe | Status | Wall s | Deterministic time | Branches | Conflicts | Binary / integer propagations |
|---|---|---:|---:|---:|---:|---:|
| BASE_CELLS_ONLY | FEASIBLE | 0.143 | 0.001856 | 1,733 | 3 | 1,945 / 0 |
| COLOCATION_CELLS_ONLY | FEASIBLE | 0.075 | 0.001653 | 1,527 | 3 | 1,761 / 0 |
| COLOCATION_COUNT_CELL_LOCKS | UNKNOWN | 300.013 | 141.429 | 872,912 | 118,271 | 7,786,349 / 2,195,953 |
| COLOCATION_COUNT_LOCKS | FEASIBLE | 0.063 | 0.015060 | 1,319 | 0 | 1,546 / 2,865 |
| COLOCATION_NONCRITICAL | UNKNOWN | 300.004 | 184.819 | 1,416,764 | 181,229 | 11,942,717 / 3,553,577 |
| BASE_FULL | UNKNOWN | 60.001 | 48.793 | 795,562 | 77,837 | 5,614,672 / 2,013,216 |
| COLOCATION_FULL | UNKNOWN | 60.007 | 37.560 | 705,096 | 65,131 | 4,929,388 / 1,709,205 |

## Constraint ladder

| Rung | Status | Deterministic time | Model-proto digest | Constraint-set digest |
|---|---|---:|---|---|
| L0 CELL | FEASIBLE | 0.002768 | `sha256:5a8f053d5667314a3d0e3fba2f3d91c2ce7639e1ec5e3982ccb4964665bf9eac` | `sha256:9f5cbba39ac28459d3ffa78ea180a532312131b466239abcb37ae906ec403d7d` |
| L1 CELL + COUNT | UNKNOWN | 44.471 | `sha256:5b22c4c979ff2dafbe94afd1286eb8eaafac40005167e40e5bf8bf77bfe3ebc1` | `sha256:b10b5ca50ff0b4671b11f29b521dcf72ffdc7fa3b66ac07b9bda0e568c36fc78` |
| L2 + SYNTHETIC_LOCK | UNKNOWN | 51.434 | `sha256:9f7e5163015371bb1d2c15a381e6430825950c10340516520da54fde44afb2dc` | `sha256:2a5e0b4e508a1e4d6fea5d4d5f804a0755900412426032235acee62065d8ad10` |
| L3 + C18_REFUSAL | UNKNOWN | 40.483 | `sha256:771d1052a0591afff89a057063e80a349fde78e9051d5fd1a5d3ea333ef7f6f8` | `sha256:a8d4b7934fc8e6e98b050b11491e2bf9ad4ec14858733b43faad70f35507c311` |
| L4 + ROW_TAG | UNKNOWN | 48.087 | `sha256:d1b587c1998d3df5bf5e6dca688ee240e83f0b9011b90de4273e93c699409030` | `sha256:be2df8a55febe2fc0c35f60716fbafb47e8792828df3b5b1cb493ad458922ea3` |
| L5 + ROW_ERROR | UNKNOWN | 44.295 | `sha256:7a1c1e6ebb9c34fcee4af08d42df9c618636d7a55b32d3cb389083eecb6d6dae` | `sha256:13f7044dcfa60e699fa577f2df6578a68354a68d5060605d67f54b6ab232608c` |
| L6 + CRITICAL | UNKNOWN | 40.949 | `sha256:57cb854d7ce51dfd06f81bc030add2d575c53cbb4deb83bc25e81165b8b0019f` | `sha256:50429e43275845b4ad298c63502ba811c9cf2e1337264db37efa3330b0e85d81` |
| L7 BASE_FULL | UNKNOWN | 43.098 | `sha256:cd5de2106bf2f6efc65b20c361f92ac3cf582af234f4b497e636d5e67254a407` | `sha256:0e8a6ffdb62906dd75294f5e8daf79ece4bc4fb1853ed574140a489ecc341433` |
| L8 COLOCATION_FULL | UNKNOWN | 49.798 | `sha256:6e84514d0c022b9a8ec2bf8334b9d6e3473a4ff1f43344228a6042ec752138ef` | `sha256:3db0a851e574436f644bdfc890705a07ef230e3886b57a912b808d1eb0a62a2f` |

FIRST_FEASIBLE_TO_UNKNOWN_BOUNDARY=L1_CELL_COUNT

## Single-worker time probes

All runs used one worker, seed 0, presolve enabled, randomized search disabled,
and no hint. Each row uses the same full-model proto digest for its model.

| Model | Limit | Status | Wall s | Deterministic time | Branches | Conflicts | Binary / integer propagations |
|---|---:|---|---:|---:|---:|---:|---:|
| BASE | 60 | UNKNOWN | 60.003 | 30.042 | 539,464 | 40,348 | 2,776,186 / 1,230,472 |
| BASE | 300 | UNKNOWN | 300.005 | 168.599 | 1,190,661 | 127,726 | 6,857,629 / 2,869,261 |
| BASE | 900 | UNKNOWN | 900.001 | 554.151 | 3,611,567 | 292,813 | 19,980,246 / 8,120,281 |
| BASE | 3600 | UNKNOWN | 3600.032 | 1,591.161 | 8,636,644 | 769,128 | 48,672,040 / 19,943,966 |
| COLOCATION | 60 | UNKNOWN | 60.002 | 73.102 | 495,883 | 126,985 | 7,122,034 / 1,664,618 |
| COLOCATION | 300 | UNKNOWN | 300.002 | 219.734 | 1,862,780 | 192,450 | 12,426,725 / 4,710,775 |
| COLOCATION | 900 | UNKNOWN | 900.004 | 605.000 | 4,551,579 | 365,097 | 23,611,680 / 10,811,174 |
| COLOCATION | 3600 | UNKNOWN | 3600.000 | 2,480.481 | 13,164,295 | 1,268,717 | 78,989,068 / 32,455,878 |

## Hint ablation

The hard-constraint digests remained unchanged within each model across hint
modes. `NOT_AVAILABLE` means the source progressive submodel returned UNKNOWN
or could not be projected onto the target component topology.

| Hint | BASE | COLOCATION |
|---|---|---|
| NO_HINT | UNKNOWN | UNKNOWN |
| COMPONENT_PREFERRED_RANK_HINT | UNKNOWN | UNKNOWN |
| BASE_CELL_FEASIBLE_HINT | UNKNOWN | NOT_AVAILABLE |
| COLOCATION_CELL_FEASIBLE_HINT | UNKNOWN | UNKNOWN |
| COUNT_CELL_LOCK_HINT | NOT_AVAILABLE | NOT_AVAILABLE |
| NONCRITICAL_HINT | NOT_AVAILABLE | NOT_AVAILABLE |

## Multi-worker probes

Default portfolio search was used with only worker count, 900-second diagnostic
budget, and private logging configured.

| Model | Workers | Status | Wall s | Deterministic time |
|---|---:|---|---:|---:|
| BASE | 8 | INFEASIBLE | 0.046 | 0.009260 |
| BASE | 16 | INFEASIBLE | 0.225 | 0.178499 |
| COLOCATION | 8 | INFEASIBLE | 0.059 | 0.014388 |
| COLOCATION | 16 | INFEASIBLE | 0.057 | 0.022010 |

All four multi-worker UNSAT results were independently cross-checked by the PB
proof path below.

## Symmetry and exactly-three strengthening

```text
EXCHANGEABILITY_CLASSES=138
EXCHANGEABILITY_CLASS_SIZE_DISTRIBUTION=1:122;2:6;3:5;4:2;6:1;15:1;16:1
LARGEST_EXCHANGEABILITY_CLASS=16
COMPONENTS_IN_NONTRIVIAL_CLASSES=72
SYMMETRY_BREAKING_APPLIED=YES
SYMMETRY_BREAKING_PROOF_DIGEST=sha256:50a2390cd69bdaa67846732475185f7a94abfd12a2b32f5b546de6a417a91b3e
```

The signature partition included component size, split locks, eligible cells,
row tags/errors, C18 obligations, critical-error eligibility, retained
co-location graph structure, and each component's contribution to every hard
constraint. Component-order symmetry breaking was applied only to these proven
permutation-invariant classes. No global split-color symmetry was assumed.

| Co-location full model | Status | Deterministic time | Branches | Conflicts | CP-SAT symmetry telemetry |
|---|---|---:|---:|---:|---|
| Without breaker | UNKNOWN | 73.102 | 495,883 | 126,985 | 84 generators; 105 orbits / 530 variables; orbitope 9×2 |
| With breaker | UNKNOWN | 56.797 | 897,470 | 65,037 | 30 generators; 72 orbits / 273 variables; orbitope 9×2 |

The exhaustive exactly-three truth-table check covered all 27 assignments and
passed before either strengthened solve.

| Model | Exactly-three cells | Baseline 300 s | Strengthened 300 s |
|---|---:|---|---|
| BASE | 67 | UNKNOWN | INFEASIBLE |
| COLOCATION | 67 | UNKNOWN | INFEASIBLE |

```text
EXACTLY_THREE_CELL_STRENGTHENING=PASS
EXHAUSTIVE_ASSIGNMENTS_CHECKED=27
MODEL_SOLUTION_SET_CHANGED=NO
EQUIVALENCE_DIGEST=sha256:2a02f0798573aa7bee28387abbe724a0630ce7a2fc0bc6c2ceee8f29ba4482d3
BASE_STRENGTHENED_GROUP_DIGEST=sha256:12be8e05d4b220a578d7438854a1a2b17ec5d6eace69e61d843f73b29741370b
COLOCATION_STRENGTHENED_GROUP_DIGEST=sha256:12be8e05d4b220a578d7438854a1a2b17ec5d6eace69e61d843f73b29741370b
```

## Independent SAT/PB proofs

The canonical full Boolean/PB models were encoded as CNF with PyPBLib BDD
encoding and solved by Glucose 4 through PySAT. DRUP certificates were checked
with DRAT-trim commit `2e3b2dc0ecf938addbd779d42877b6ed69d9a985`.

| Model | CNF variables / clauses | CNF digest | Result digest | DRUP certificate digest | Checker |
|---|---:|---|---|---|---|
| BASE | 51,220 / 151,230 | `sha256:c9f420c2dc04b8f032ddfcc80a6b38ce0340b4847637657176b2df3844cb691b` | `sha256:713181e52ae12b4406cf024c5d6e51b965c1ecb3e37727e78f462d67da3c6741` | `sha256:1b52df4167c7f0d2cee266a2cbd7ad719de7180d7eca0f13e371f65db505dfe4` | PASS |
| COLOCATION | 43,564 / 128,808 | `sha256:6691fd2c3fff42f61248275deaa0f3edece6e883326e7e7acbb35940b810b920` | `sha256:a6acc4bc4fa513a2405826168f464bd075e383b80325c8e9c5d2a5c444e9b3a7` | `sha256:838282d399dc5cfd6e03e71c93a5866a77c494d03e85d41e10c8c56c386e8309` | PASS |

```text
INDEPENDENT_SOLVER=Glucose 4 / PySAT 1.9.dev15 / PyPBLib 0.0.4
PB_ENCODING=BDD
BASE_RESULT=UNSAT
COLOCATION_RESULT=UNSAT
BASE_RESULT_ARTIFACT_DIGEST=sha256:cf8b3ba168376db70f476466cd38a92a0df11dffe662c1a6f74e6c12a4b7200d
COLOCATION_RESULT_ARTIFACT_DIGEST=sha256:3b9ea27e8671c5777f7d8939c03659a9471ea2d2f49d7507ac78109d6b6e967c
BASE_PROOF_CHECK=PASS
COLOCATION_PROOF_CHECK=PASS
```

## Private artifacts and preservation

```text
PRIVATE_ARTIFACT_ROOT=/mnt/e/Data/Datasets/DynamisLM/PerformanceScienceEval/production/diagnostics/RES-224
PRIVATE_PROBE_FILE_DIGEST=sha256:13987596b688e46ab71ba021fac3c1294460f59978c30a91bcfe95e1ac9a6428
PRIVATE_PROBE_PAYLOAD_DIGEST=sha256:399f3b97d6ac7ea2588af710a618eb335b461e650631dba44a25522ce0e1799e
PRIVATE_SOLVER_LOG_COUNT=36
PRIVATE_LOG_MANIFEST_DIGEST=sha256:e1ecf422fa3d5409750243c2805e4066df42fd1fb01cb5c47b11de5754dcd553
BASE_DRUP_PATH=production/diagnostics/RES-224/RES224_BASE_GLUCOSE4.drup
COLOCATION_DRUP_PATH=production/diagnostics/RES-224/RES224_COLOCATION_GLUCOSE4.drup
FEASIBILITY_MEMBERSHIP_PERSISTED=NO
RES223_PRIVATE_INPUTS_AND_REPAIR_PLAN_HASHES=UNCHANGED
```

All protos, CNFs, solver logs, result JSON, and proof certificates remain under
the external private diagnostics root. The checked-in receipt contains hashes
and aggregate telemetry only.

`STATUS=PASS` records that both UNSAT results have independently checked
certificates. Candidate-design repair is authorized for a subsequent mission;
RES-224 itself changed no candidate content, topology, allocation, or store.
