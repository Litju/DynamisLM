# PSE V1 post-audit execution baseline receipt

```text
MISSION=PSE-V1-POST-AUDIT-EXECUTION-BASELINE-001
STATUS=PASS
REQUIRED_ENTRY_HEAD=b13932c23d8d5c2071dcdbb3260083650fd0002a
RECOVERY_ANCHOR=c689d5d057da0d5281d718cb25a7b33d26d2530b
RECOVERY_ANCHOR_TREE=57fe054655b96ec69f751027eba5183ff5173d8b
WORK_BRANCH=work/pse-post-audit-execution-baseline
PRIOR_IMPLEMENTATION_HEAD=1584353825a4888d2ab0fb8b395b7e141feb10d9
SUPPLY_AND_QUALIFICATION_COMMIT=7d09956
ROADMAP_COMMIT=bc28306
HARDENING_RECEIPT_COMMIT=THIS_COMMIT
REMOTE_PUSH_AT_BASELINE_SEAL=NO
INVALID_LOCAL_RES397_HEAD=e2d7f9bd616cb7f01e9c834ff8442e2cb8cb9288 (preserved unmodified as forensic evidence)

POST_AUDIT_AUTHORITY=RES258/369/373/381/383
FIXED_PRE_REVIEW_N=NO
POOL_N=NOT_DERIVED
HISTORICAL_ORIGIN_EQUALITY_ACTIVE=NO
HISTORICAL_37X3_ACTIVE=NO
HISTORICAL_434_TOPOLOGY_AUTHORITY=NO
HISTORICAL_ORIGIN_VECTOR_AUTHORITY=NO
HISTORICAL_37X3_AUTHORITY=NO
RES223_TOPOLOGY_ACTIVE=NO
RES128_FIXED_DIGEST_GATE_ACTIVE=NO
LEGACY_EXACT_ORACLE_NEW_POOL_GATE=NO

ACTIVE_SUPPLY_SCHEMA=PSE-V1-AUTHORITY-SUPPLY-INVENTORY@1.3.0
HISTORICAL_RECIPE_INVENTORY=INVENTORY_ONLY
EXISTING_AUTHORIZED_RECIPE_COUNT=INVENTORY_ONLY
ADDITIONAL_AUTHORABLE_CAPACITY=SEPARATE_TYPED_VALUE
CAPACITY_STATUS=PER_LANE_TYPED
FINAL_SELECTION_BOUND=434_FINAL_SELECTION_ONLY
STRUCTURAL_POOL_FLOOR=NOT_DERIVED
STRUCTURAL_BACKFILL_REQUESTS=NONE
RES383_V1_2_INVENTORY=HISTORICAL_PRESERVED
RES383_V1_2_POOL_FLOOR_436=SUPERSEDED
RES383_V1_2_SOURCE_PLUS_SYNTHETIC_BACKFILL=SUPERSEDED
RES383_V1_2_MANDATORY_BACKFILL=SUPERSEDED
EXISTING_RECIPE_COUNT_IS_NOT_POOL_TARGET=YES
EXISTING_RECIPE_COUNT_IS_NOT_CAPACITY_CAP=YES
FINAL_SELECTION_BOUNDS_APPLY_ONLY_TO_FINAL_SELECTION=YES
BASE_INFEASIBLE_REMOVAL_SWEEP=FORBIDDEN
BASE_UNKNOWN_REMOVAL_SWEEP=FORBIDDEN
BACKFILL_WITHOUT_TYPED_DEFICIT=FORBIDDEN
BACKFILL_WITHOUT_FEASIBILITY_EVIDENCE=FORBIDDEN
RES126_EXECUTION_SCOPE=SUPERSEDED
PROPOSED_NEW_LINEAR_ROOT=RES-115

VARIABLE_POOL_AUTHORING_PATH=PASS
INDIVIDUAL_RECIPE_REUSE=SUPPORTED
COLLECTIVE_434_TOPOLOGY_AUTHORITY=NO

SOURCE_AUTHORITY=PASS
RES71_AUTHORITY=PASS
SYNTHETIC_AUTHORITY=PASS
CONTAMINATION_VALIDATION=PASS
ISOLATION_VALIDATION=PASS

RES369_CONSTRAINT_VOCABULARY=UNCHANGED
RES373_ENGINE_REFERENCE_ISOLATION=UNCHANGED
RES381_CANONICAL_CORRECTNESS=UNCHANGED
RES383_SUPPLY_SEMANTICS=CORRECTED

NO_CANDIDATE_HUMAN_APPROVALS_CREATED=YES
NO_PROTECTED_MEMBERSHIP_PERSISTED=YES
NO_BENCHMARK_FREEZE=YES
HUMAN_REVIEW_RUN=NO
PROTECTED_MEMBERSHIP_PERSISTED=NO
BENCHMARK_FROZEN=NO
CANDIDATE_POOL_PERSISTED=NO
EXTERNAL_STORE_WRITES=NONE
SOLVER_RUNS=UNIT_TEST_FIXTURES_ONLY
PRODUCTION_POOL_MATERIALIZATION=NOT_RUN
PRODUCTION_POOL_QUALIFICATION=NOT_RUN
PRODUCTION_ALL_REMOVAL_QUALIFICATION=NOT_RUN
DR001_CHANGED=NO
RES71_REFERENCES_CHANGED=NO
SERIALIZATION_V3_CHANGED=NO
HISTORICAL_HASHES_CHANGED=NO

RUFF=PASS
FORMAT=PASS
MYPY_STRICT=PASS (218 source files)
REPOSITORY_POLICY=PASS
FULL_CI=PASS (./scripts/ci.sh; 1232 passed in 1296.35s)
PYTEST=PASS (1232 passed)
TEST_COUNT=1232
QA_TRACKED_MUTATION=NONE

PSE_V1_COMPLETE=NO
BASELINE_READY_FOR_PR=YES
NEXT=VARIABLE_PRE_REVIEW_POOL_CONSTRUCTION
```

## Authority

This baseline implements, and does not amend:

- [RES21-DR-001](../decisions/RES21-DR-001-performance-science-eval-v1.md), the scientific and scoring constitution;
- [RES258-DR-001](../decisions/RES258-DR-001-pse-v1-pool-first-selection-authority.md) and the [supersession map](../decisions/RES258-SUPERSESSION-MAP.md);
- the [pool-first lifecycle](../architecture/PERFORMANCE_SCIENCE_EVAL_PRE_REVIEW_V1.md);
- the RES-369, RES-373, RES-381 and RES-383 receipts in this directory.

The RES-397 branch `work/res-397-materialized-pool-attrition` reactivated the
superseded RES-126/128/222/223 execution path. That branch was not rewritten,
merged, or cherry-picked. Its valid concerns were reimplemented here from the
recovery anchor, one concern per commit.

## Commits

| Concern | Commit |
| --- | --- |
| Variable production-pool validation without a fixed 434 | `397022e` |
| Exact 13-token question-shingle projection | `e68cf37` |
| RES-383 repair-trial parent-provenance fix (from `a3d041a`) | `7c03d8f` |
| Variable pool authoring contracts | `9423cff` |
| Pool-first materialization boundary | `789ad08` |
| RES-383 supply decoupled from historical planned slots | `2fe22ec` |
| Static call-path proof | `1584353` |
| Prior lifecycle documentation and baseline receipt | `b13932c` |
| Supply semantics and base-feasibility hardening | `7d09956` |
| Post-audit execution roadmap | `bc28306` |
| Final baseline receipt hardening | this receipt commit |

## Modern execution boundary

```text
ProductionCandidateRecipeV1        one individually authorized recipe
    -> VariablePoolAuthoringPlanV1 explicit variable recipe set (no N, origin, or lineage target)
    -> materialize_variable_pool   existing per-recipe production builders + current gates
    -> ProductionAuthoringCandidatePoolV1 (pending review, bound to the plan digest)
    -> project_variable_pool_selection_candidates -> unchanged RES-369 vocabulary
    -> validate_variable_pre_review_pool (candidate gates; final-selection bound 434)
```

A recipe's basis is `HISTORICAL_INDIVIDUAL_RECIPE` or `GOVERNED_SUPPLY_LANE`.
`historical_recipes_from_authoring_inputs` turns the historical production input
into individual recipes. Expert recipes carry their batch, template and cluster
*identity*, but not historical batch membership. Mutation recipes carry an
explicit parent, lineage, operator and stage. Slot totals, the origin vector,
lineage geometry, RES-223 plans and legacy receipts are discarded.

The pre-review pool is variable. It must be large enough to permit the exact
final selection, whose bound is 434; the supply inventory does not set the pool
target or derive `POOL_N`.

## Removed from the active path

The modern entrypoints are:

- `historical_recipes_from_authoring_inputs`
- `VariablePoolAuthoringPlanV1`
- `materialize_variable_pool`
- `production_source_selection_universe`
- `project_variable_pool_selection_candidates`
- `validate_variable_pre_review_pool`
- `build_live_authority_supply_inventory`
- `assess_authority_supply_inventory`
- `plan_variable_pool`

`tests/test_variable_pool_reachability.py` proves that none of these can reach
the following symbols. The analysis is conservative and AST-based across
modules, it includes a positive control, and it was falsified by injection.

- `build_production_authoring_draft`;
- the fixed 434 skeleton: `_authoring_input_skeleton`, `_semantic_slot_specs`,
  `_engine_slot_specs`, `_synthetic_slot_specs` and `_expert_batch_records`;
- 37x3 or 111 mutation geometry: `_mutation_lineage_specs` and `_author_mutation_packets`;
- the fixed 40-source selection: `_choose_supported_sources`;
- RES-223 plan application, either through `_new_or_resume_private_inputs` or
  anywhere in the `res223_topology` module;
- the RES-128 fixed digest gate: `_validate_res128_feasibility_baseline` and the
  `_RES128_*` constants;
- the RES-225 hooks and the `res225_repair` module, plus the `res249_redesign` module;
- the legacy exact-feasibility and fixed-plan gates:
  `validate_production_exact_feasibility`, `validate_production_exact_feasibility_receipt`,
  `validate_production_hard_feasibility`, `validate_production_candidate_set`
  and `bind_production_authoring_plan`.

`tests/test_variable_pool_materialization.py` replaces each of these with a
failing stub and still materializes a pool.

## RES-383 supply correction

`build_live_authority_supply_inventory` emits
`PSE-V1-AUTHORITY-SUPPLY-INVENTORY@1.3.0`. The serialized inventory remains
hash-compatible; typed properties separate `HISTORICAL_RECIPE_INVENTORY`,
`EXISTING_AUTHORIZED_RECIPE_COUNT`, `ADDITIONAL_AUTHORABLE_CAPACITY`, and
`CAPACITY_STATUS`. Existing recipe counts do not set the pool target or cap
future authoring. When extra authority is unproven, its capacity is
`GOVERNED_UNRESOLVED`, `UNKNOWN`, or rule-governed rather than a fabricated
number. The inventory carries no planned origin or lineage geometry.

Its lanes are built as follows:

- **Source:** one lane per accepted document. A document that already carries a
  historical recipe is limited to that recipe's cell. Every other document uses
  its eligible cells.
- **Engine:** one lane per RES-71 reference and cell.
- **Expert:** one lane per batch identity.
- **Mutation:** one lane per lineage.

Historical recipe inventory is reported separately from additional authorable
capacity. Engine, expert, and mutation recipe counts are inventory counts; their
additional capacity remains governed-unresolved until separately authorized.
Source lanes with an existing recipe do not count as additional authorable lanes.
Synthetic generators are rule-governed. The supply assessment reports these
semantics only and derives no structural pool floor or backfill request.

Historical v1.2 inventories remain readable, and their digests are byte-identical
to the `c689d5d` implementation; that digest is pinned in a test.

The live builder was then run read-only against the external store:

```text
SUPPLY_SCHEMA=PSE-V1-AUTHORITY-SUPPLY-INVENTORY@1.3.0
SUPPLY_INVENTORY_DIGEST=sha256:4b7ee2d0f9b3f1b56a638b0b27aa01a5ba153e226f34c37bb995dd113292c616
PLANNED_ORIGIN_COUNTS=NONE
PLANNED_MUTATION_LINEAGES=0
SOURCE_EXISTING_RECIPE_LANES=40
SOURCE_ADDITIONAL_AUTHORABLE_LANES=15
SOURCE_EXHAUSTED_LANES=49
ENGINE_LANES=23
ENGINE_EXISTING_AUTHORIZED_RECIPE_COUNT=31
ENGINE_ADDITIONAL_AUTHORABLE_CAPACITY=GOVERNED_UNRESOLVED
EXPERT_LANES=146
EXPERT_EXISTING_AUTHORIZED_RECIPE_COUNT=240
EXPERT_ADDITIONAL_AUTHORABLE_CAPACITY=GOVERNED_UNRESOLVED
MUTATION_LANES=37
MUTATION_EXISTING_AUTHORIZED_RECIPE_COUNT=111
MUTATION_ADDITIONAL_AUTHORABLE_CAPACITY=GOVERNED_UNRESOLVED
SYNTHETIC_LANES=3 RULE_GOVERNED
EXISTING_RECIPE_COUNT_IS_NOT_POOL_TARGET=YES
EXISTING_RECIPE_COUNT_IS_NOT_CAPACITY_CAP=YES
FINAL_SELECTION_BOUND=434 (FINAL_SELECTION_ONLY)
STRUCTURAL_POOL_FLOOR=NOT_DERIVED
STRUCTURAL_BACKFILL_REQUESTS=NONE
ASSESSMENT=METADATA_REQUIRED
POOL_N=NOT_DERIVED
```

The historical RES-383 v1.2 receipt is preserved unchanged. Its `>=436` floor
and mandatory one-source-plus-one-synthetic request were derived by applying
the final-selection origin bounds and one-removal tolerance to the old
434-slot planned origin vector. That calculation treated existing historical
planned-slot geometry as current variable-pool authority. In v1.3, recipes are
individual authoring inputs, while final-selection bounds apply only to the
eventual final selection; inventory counts do not encode a collective pool
topology. Therefore both v1.2 conclusions are superseded, and v1.2 inventory
cannot be assessed as current execution authority.

## Individual-recipe reuse evidence

In a read-only, in-memory run, all 434 historical recipes were decomposed and
materialized through `materialize_variable_pool`. Nothing was persisted and no
solver was run. All 434 payload hashes matched the historical builder's packets
in the RES-397 stored pool
`production/candidate-pools/RES-397/a46d93c5…ca86.json`, with 0 mismatches.
This shows that each recipe is reproduced exactly through the current gates. It
says nothing about the collective topology, which remains unqualified and
non-authoritative.

## Retained historical code

The following remain in the repository as historical evidence. They are
unreachable from the modern path:

- `production_authoring.build_production_authoring_draft` and its fixed-434 helpers;
- `res223_topology.py`, `res225_repair.py` and `res249_redesign.py`;
- `scripts/res223_topology.py`, `res224_probes.py`, `res225_repair.py` and `res249_benchmark.py`;
- the RES-222/224 exact-feasibility oracle;
- v1.2 supply semantics.

`selection_pool.plan_variable_pool` now solves the base first. `INFEASIBLE`
returns a typed base deficit and stops with no removal sweep, candidate repair
trial, or backfill request. `UNKNOWN` also stops fail-closed. Only a `FEASIBLE`
base proceeds to single-removal qualification. The solver supplies no IIS, so
the typed diagnosis binds pool, problem, and constraint digests and reports no
constraint IDs as causal findings. Existing recipe counts are not used as
additional-capacity ceilings.

## Not carried forward from RES-397

- the `scripts/res397_materialized_pool.py` runner;
- the `read_repair_plan` dependency;
- the legacy UNKNOWN bypass;
- RES-223 receipt namespacing;
- the immutable 434 baseline;
- witness-free structural additions;
- the runner's Cartesian trial search;
- the removal sweep on an infeasible base;
- the `/tmp` checkpoint runner;
- the RES-397 acceptance receipt.

The RES-397 private artifacts in the external store were left untouched.

## Tests

New or extended tests:

- `test_variable_pool.py`: contracts;
- `test_variable_pool_materialization.py`: per-recipe equivalence, subset plans,
  fail-closed lanes, and runtime non-reachability;
- `test_variable_pool_reachability.py`: static proof;
- `test_res383_pool_plan.py`: v1.3 supply semantics, v1.2 historical-only
  assessment, base feasibility hard stops, and parent-provenance regression;
- `test_res369_selection.py`: shingle projection and tamper rejection;
- `test_res115_production.py`: the variable pool gate.

## Proposed Linear governance (documentation only)

Proposed disposition: RES-126 = `CANCEL_SUPERSEDED`. Preserve RES-126
historically with a supersession note: its operative scope was fixed-434
materialization. The new PSE execution hierarchy starts at RES-115 under a new
umbrella whose title does not inherit fixed-434 semantics. No Linear issues
were changed for this receipt.

```text
RES-115
└── Post-Audit PSE V1 Execution & Freeze
    ├── A0 Post-audit execution baseline integration
    ├── A1 Variable pre-review pool construction
    ├── A2 Candidate-level pool qualification
    ├── A2b Conditional governed backfill
    ├── A3 Human-review trust boundary
    ├── A4 Human review
    ├── A5 Final approved-pool selection
    ├── A6 Protected-store provisioning
    └── A7 Final contamination adjudication & freeze
        └── Integrate completed PSE V1 into the main/default release line
```

A2b is created or activated only when A2 emits an actual typed deficit with
feasibility evidence. It is conditional, not a default phase. A2 stops without
removal checks or backfill when base feasibility is `INFEASIBLE` or `UNKNOWN`.

PSE V1 is not complete. No human review, protected membership, or freeze has
occurred.
