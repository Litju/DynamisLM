# RES-383 Acceptance Receipt

```text
MISSION=RES-383
STATUS=BACKFILL_REQUIRED
EXACT_POOL_QUALIFICATION=METADATA_REQUIRED
ENTRY_HEAD=86b16f9a395416b7319c20499fef626d747283db
ENTRY_TREE=CLEAN
ENTRY_REMOTE_REF=origin/work/res-21-performance-science-eval-v1
ENTRY_REMOTE_HEAD=86b16f9a395416b7319c20499fef626d747283db
WORK_BRANCH=work/res-383-variable-pool-feasibility
POOL_N_POLICY=STRUCTURALLY_DERIVED_NO_FIXED_TARGET
KNOWN_STRUCTURAL_POOL_FLOOR=436
DERIVED_POOL_N=NOT_CLAIMED
BACKFILL_REQUESTS=1_SOURCE_PLUS_1_SYNTHETIC
INDEPENDENT_CRITICAL_RESERVE=NOT_QUALIFIED
CURRENT_AUTHORING_INPUT_SLOTS=434
MATERIALIZED_FINAL_SELECTION_CANDIDATES=0
USABLE_RESERVE_CAPACITY=0
FINAL_CANONICAL_CONFIRMATION=NOT_RUN
PRODUCTION_SOLVER_PROFILE_V2_SOLVE=NOT_RUN
PROFILE_V2_RESERVED_FOR_FINAL_CANONICAL=YES
CANDIDATE_TEXT_MATERIALIZED=NO
HUMAN_REVIEW_PERFORMED=NO
PROTECTED_MEMBERSHIP_PERSISTED=NO
DR001_CHANGED=NO
RES71_REFERENCES_CHANGED=NO
```

## Authority supply inventory

The inventory was derived read-only from sealed RES-71 references and registered
operations, the Phase-A accepted-source/family/support manifests, the registered
production generator, and current private production authoring inputs. It does
not read or create production candidate packets. Sensitive identities and rows
remain in the external qualification store; the repository records only this
count summary and the inventory/file digests.

```text
SUPPLY_SCHEMA=PSE-V1-AUTHORITY-SUPPLY-INVENTORY@1.1.0
SUPPLY_INVENTORY_DIGEST=sha256:e6f0c601171822278898450e622fa953427733065c1c7e51c5ada807f67d80c1
SUPPLY_EXTERNAL_FILE=qualification/RES-383/authority-supply-inventory.v1.1.json (external)
SUPPLY_EXTERNAL_FILE_DIGEST=sha256:ac0df6382262a31f916b926da96a0634d27a8fe7adee8338db5fce78d4a7d719
SUPPLY_ASSESSMENT_DIGEST=sha256:cadedbd36a0c01cb8242f8cb0573857ab2377d3b0987221ea1f0a8708d5d7106
SUPPLY_ATOMS=890
GOVERNED_RESERVE_LANES=273
```

| Authority | Actual inventory |
| --- | --- |
| RES-71 | 12 sealed references: 5 `VALUE`, 4 `REFUSAL`, 1 `COMPARABILITY`, 2 `CLAIM_AUTHORITY`; 6 operation identities are referenced by those cases. The live operation inventory has 100 entries. Sealed reference digest: `sha256:d29d84699b7cf70c2d409d370c5ffd6c7ad7cd704375b14b541527a95fa385e5`. |
| Phase-A source authority | 104 accepted documents across 94 source families; 104 source-tag support rows. Forty documents are selected. Sixty-four remain unselected raw source authority; 62 have retained applicability lanes, not qualified candidate slots. |
| Engine lanes | 23 exact capability/family/reference lanes cover 31 planned engine slots. No extra engine reference or slot is inferred. |
| Synthetic authority | 3 registered split-family lanes under one generator identity. The 12 current seed blocks are planned. Additional unique blocks remain governed by the registered generator and split-lock rules; capacity is not given a fabricated numeric ceiling. |
| Expert-semantic authority | 146 bounded batch/template/isolation lanes cover 240 planned slots. No extra slot is recorded. |
| Mutation authority | 37 existing parent/operator lineages and 111 child seed blocks. Additional child capacity remains unresolved until parent/cell candidate metadata exists. |
| Candidate/review stores | 0 materialized production candidates. Qualification exclusion boundary: 101 candidates excluded from production reuse. No human approval exists for this mission. |

The current private authoring input content digest is
`sha256:b1549e62d61de905939a1a8139ff55c4f2ce9ac0fd0d25412026eb5f34fccea9`;
its external file digest is
`sha256:b64146e9eb6f4b917a4f199f589a72cba2d4312e2be3a3719cba54bb8016b044`.
It contains 271 scenario seeds (240 semantic and 31 engine), 12 synthetic seed
blocks, 40 source selections, and 111 mutation seed blocks: 434 prospective
authoring slots, not materialized `FinalSelectionCandidate` metadata.

Phase-A manifest digests:

```text
accepted.jsonl=sha256:5f32fd5fda9e9072c90afd49f8e3080ed9fd8a9c160e962eccdfc7a97b3f8335
source_families_001.jsonl=sha256:4d3420fcd5a1e0b3bad24db73e8a6ed68308cdc5a1f19dab9f2fcf3e289156b7
source_tag_support_evidence_001.jsonl=sha256:7dd8bcf756ffa5de4cf26db3f5fcd3227c153d7295b3e46dacd0bf9ef20e9bac
synthetic_generator_registry=sha256:1e75e89e95b3705f9adc0d58cf06d92fd1a335b5da68863be4a5a2be98069a64
qualification_exclusion_digest=sha256:5bcc5da6fe959a66b819eb4a6c45326f82b06c4660a114de5f20aa3adf3b6343
```

## Structural reserve result

The final target remains 434 with splits `260 / 87 / 87`. Each single removal
must leave a jointly feasible 434-candidate assignment under the RES-369 hard
constraints. Necessary count lower bounds from the current planned slots are:

| Constraint | Planned slots | Needed for one-removal tolerance | Deficit |
| --- | ---: | ---: | ---: |
| Final selected count | 434 | pool at least 435 | 1 overall |
| Source-backed minimum | 40 | at least 41 | 1 source |
| Engine-derived minimum | 31 | at least 31 | 0 |
| Synthetic minimum | 12 | at least 13 | 1 synthetic |
| Mutation minimum | 111 | at least 61 | 0 |
| Distinct mutation lineages | 37 | at least 21 | 0 |
| Expert-semantic maximum | 240 | at most 240 selected | no reserve implied |

The source and synthetic deficits require distinct origins, so the evidence
supports `KNOWN_STRUCTURAL_POOL_FLOOR >= 436`. It does not derive a complete
pool size. The typed inventory returns one source request with 62 retained
applicability lanes and one synthetic request under the three registered
split-family lanes. The requests are authoring/sourcing capacity only; no
candidate prose or metadata was created.

There are 5 critical error classes across 2 protected splits. Removal tolerance
requires 20 candidate-feature incidences. The candidate store is empty, so
neither these incidences nor the exact isolation/colocation/split-lock/mutation
interactions can yet be checked. The typed result is therefore
`BACKFILL_REQUIRED` with exact qualification `METADATA_REQUIRED/UNRESOLVED`,
not `AUTHORITY_EXPANSION_REQUIRED`.

## Implementation and verification

- Added immutable, versioned `AuthoritySupplyInventoryV1`, per-atom and
  per-lane digests, payload-free `ReserveCandidateLaneV1` and typed
  `BackfillRequestV1`/`ReserveDeficitV1`. Schema 1.1.0 records exact authorized
  capability-family cells. Materialized candidates bind those cells and their
  source document/family, RES-71 reference, generator/split, expert batch/template,
  or mutation parent/lineage identities. The external inventory round-tripped
  with the recorded digest; the prior schema 1.0.0 file remains unchanged.
- Kept actual `FinalSelectionCandidate` metadata in a separate
  materialized-backfill type. Simple count needs create lane-bound requests;
  exact baseline/removal failures create scenario-bound deficits and retry from
  materialized candidates on governed lanes. If lane candidates or exact-cause
  metadata are missing, status remains `METADATA_REQUIRED`; expansion requires
  a complete inventory proving no lane can satisfy the deficit.
- Pool feasibility uses the named
  `PSE-V1-POOL-FEASIBILITY-SOLVER@1.0.0` profile: 8 workers, seed 369,
  120-second timeout, chunk size 30, presolve disabled, and randomized search
  disabled. Qualification ran on the existing RES-369 abstract production-shape
  hard-constraint model with 435 candidates: base FEASIBLE in 2.956514 s; five
  representative removals FEASIBLE in 2.120099 s (expert), 2.268977 s (source),
  1.536938 s (engine), 1.681378 s (synthetic), and 1.910188 s (mutation).
  `UNKNOWN_COUNT=0` across these six scenarios. Full real-pool removal
  qualification remains pending candidate metadata. Production canonical profile
  v2 remains reserved for final confirmation.
- Receipts distinguish total planned candidates, eligible candidates, and
  usable reserve count. Rejected and qualification-excluded candidates are
  excluded from reserve counts.
- The exact feasibility-only path continues to use RES-369 hard constraints
  and independent witness validation. Optimization and canonicalization are
  not run for scenario enumeration. Exact-interaction repair tests every
  available materialized candidate against the failed scenario and only retries
  candidates with a FEASIBLE witness, ordered by review cost then lane/candidate ID.
- No candidate prose, human review, protected membership, DR-001 change, or
  RES-71 reference change occurred. P4A.3n was not started. The PR remains draft.
- Focused RES-383 tests: 20 passed.
- Full `./scripts/ci.sh`: Ruff, formatting, strict mypy, repository policy, and
  tracked-mutation checks passed; pytest passed all 1,187 tests in 859.52 s.
