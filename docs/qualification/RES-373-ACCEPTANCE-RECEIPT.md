# RES-373 Acceptance Receipt

```text
MISSION=RES-373
STATUS=PASS
ENTRY_HEAD=182689430d2adfe1227832a015bb4dc66ef39d73
BRANCH=work/res-21-performance-science-eval-v1
SELECTION_PROFILE=PSE-V1-PRODUCTION-SELECTION-SOLVER@1.0.0
ENGINE_REFERENCE_IDENTITY_KIND=RES71_ENGINE_REFERENCE_CASE
REFERENCE_SOURCE_OF_TRUTH=CaseProvenance.engine_reference_case_id
SELECTION_CONSTRAINT_KIND=CONDITIONAL_COLOCATION
FINAL_CASE_ISOLATION_KIND=RES71_ENGINE_REFERENCE_CASE
FINAL_HEAD=RECORDED_IN_LINEAR_CLOSURE_RECEIPT
REMOTE_HEAD=RECORDED_IN_LINEAR_CLOSURE_RECEIPT
```

## Engine-reference isolation

- `ProductionAuthoringPlanItemV1` carries the exact `engine_reference_case_id`
  from validated proposed provenance. Engine-derived commitments require it;
  non-engine commitments cannot carry it.
- RES-369 adapts that value to the typed
  `RES71_ENGINE_REFERENCE_CASE` isolation identity. The generated
  `CONDITIONAL_COLOCATION` constraint now cites
  `RES-71 reference identity; RES-258/RES-369 isolation authority`.
- The same generic conditional-colocation implementation remains in use: any
  member may be `OUT`, while selected related members cannot cross splits.
- Final `BenchmarkCaseV1` isolation uses the same typed identity kind and exact
  provenance field.
- Counterfactual checks use one shared reference ID with different shingles,
  source families, and isolation clusters. Cross-split placement was valid
  without the reference identity and is invalid with it; one member `OUT`
  remains legal.

## RES-71 topology

Counts cover distinct engine-reference IDs, groups by ID, groups with at least
two candidates, emitted conditional-colocation relations, and the largest
group size.

| Fixture | `ENGINE_REFERENCE_IDENTITIES` | `ENGINE_REFERENCE_RELATION_GROUPS` | `ENGINE_REFERENCE_MULTI_CANDIDATE_GROUPS` | `NEW_CONDITIONAL_RELATIONS` | `LARGEST_ENGINE_REFERENCE_GROUP` |
| --- | ---: | ---: | ---: | ---: | ---: |
| Fixed 434 pool | 0 | 0 | 0 | 0 | 0 |
| Oversupply 435 pool | 0 | 0 | 0 | 0 | 0 |
| Adversarial counterfactual pair | 1 | 1 | 1 | 1 | 2 |

The fixed and oversupply production-shape topology is unchanged from RES-369;
neither abstract pool carries a RES-71 reference identity. For the
counterfactual pair, `CROSS_SPLIT_REFERENCE_VIOLATIONS_BEFORE=1` (the crossing
assignment validated before the typed relation) and
`CROSS_SPLIT_REFERENCE_VIOLATIONS_AFTER=0`.

```text
ENGINE_REFERENCE_IDENTITY_TYPED=PASS
SELECTION_ADAPTER_PRESERVES_REFERENCE=PASS
SAME_REFERENCE_CROSS_SPLIT_BLOCKED=PASS
SAME_REFERENCE_ONE_OUT_ALLOWED=PASS
SHINGLE_COUNTERFACTUAL=PASS
FINAL_CASE_ISOLATION=PASS
SEMANTIC_VALIDATION=PASS
```

## Sealed-profile requalification

```text
SOLVER=OR-TOOLS-CP-SAT 9.15.6755
PROFILE_CONFIG=workers:8,random_seed:369,timeout_s:60,canonical_chunk_size:30,cp_model_presolve:false,randomize_search:false
VALIDATED_WARM_START=USED
```

| Qualification | Status / validation | Plan digest | Variables | Constraints | Wall (s) | Objective (s) | Canonicalization (s) | Deterministic (s) | Validation (s) | Process peak RSS (MB) |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Fixed 434 | `OPTIMAL / VALID` | `sha256:7dd3f236964f2f31561668553010078e1c443b3a8c41e572f226e10a9fc5aa1d` | 2,436 | 3,775 | 35.953 | 12.073 | 19.465 | 74.158 | 0.708 | 493.9 |
| Oversupply 435 | `OPTIMAL / VALID` | `sha256:10905e20f5232c40f2e035a39ddb320a3e8bd8e424c8f0f6fe2a5388b52e1188` | 2,456 | 3,386 | 147.689 | 59.519 | 86.802 | 241.260 | 0.616 | 1,078.5 |

| Qualification | Split counts | Selected origin counts | Selected mutation lineages |
| --- | --- | --- | ---: |
| Fixed 434 | `260/87/87` | Synthetic 15; engine-derived 35; expert-authored 230; source-backed 42; adversarial mutation 112 | 28 |
| Oversupply 435 | `260/87/87` | Synthetic 15; engine-derived 35; expert-authored 231; source-backed 42; adversarial mutation 111 | 28 |

### Comparison with RES-369

- Fixed-434 plan digest is unchanged from RES-369.
- The RES-369 oversupply receipt records
  `sha256:44dc18b16ad96940e736b4f9e41319d439e56b3db906d0c4101734dd45c6b97c`;
  this requalification records a different digest. Two runs at the RES-373
  entry head, before this closure change, produced
  `sha256:2909aaaf31957499e21ebc5ec1d89bc9b6f31663e197c83ddebd1b7e8903e018`
  and
  `sha256:34e01e9426072bab43938d20c673a303ba99498c5dc3023f00bdf975de935705`.
- The entry-head reruns and this requalification have the same oversupply
  `problem_digest`:
  `sha256:cdbacca413757e3295f97af0ae6ff06425d54161d1445f7420210f4410c83986`.
  All runs returned `OPTIMAL`; the abstract pool has no engine-reference
  groups. The observed oversupply plan-digest variation is therefore not a
  topology change attributable to RES-373. Solver and canonicalization were
  left unchanged as authorized.
- Fixed-434 feasibility, split counts, and plan digest match the RES-369
  receipt. The oversupply entry-head rerun matched the requalification's split
  counts, selected origin counts, and selected mutation-lineage count. Variable
  and constraint counts match the RES-369 receipt.

## QA

| Check | Result |
| --- | --- |
| Focused `tests/test_res369_selection.py` | `PASS` — 23 tests |
| Full CI (`./scripts/ci.sh`) | `PASS` — 1,164 tests in 854.11 s |

Full CI also passed Ruff, formatting, mypy, repository policy, and the tracked
mutation check.

## Preservation

```text
RES71_REFERENCE_REGISTRY_CHANGED=NO
RES71_REFERENCE_SET_CHANGED=NO
DR001_CHANGED=NO
RESERVE_POLICY_CHANGED=NO
ISOLATION_SEMANTICS_CHANGED_BY_CLOSURE=NO
SOLVER_CHANGED=NO
FIXTURES_CHANGED=NO
CANONICALIZATION_CHANGED=NO
BENCHMARK_CASE_SERIALIZATION_V3_CHANGED=NO
CASE_PAYLOAD_HASH_PROJECTION_CHANGED=NO
PROTECTED_STORES_CHANGED=NO
REAL_CANDIDATE_CONTENT_CHANGED=NO
MATERIALIZATION_RUN=NO
HUMAN_REVIEW_RUN=NO
PROTECTED_MEMBERSHIP_PERSISTED=NO
```

Closure changed only the authority citation, its existing regression
assertion, and this receipt; the production-shape fixtures remain abstract and
synthetic.
