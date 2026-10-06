# RES-383 Acceptance Receipt

```text
MISSION=RES-383
STATUS=AUTHORITY_EXPANSION_REQUIRED
ENTRY_HEAD=86b16f9a395416b7319c20499fef626d747283db
ENTRY_TREE=CLEAN
ENTRY_REMOTE_REF=origin/work/res-21-performance-science-eval-v1
ENTRY_REMOTE_HEAD=86b16f9a395416b7319c20499fef626d747283db
WORK_BRANCH=work/res-383-variable-pool-feasibility
POOL_N_POLICY=STRUCTURALLY_DERIVED_NO_FIXED_TARGET
KNOWN_BACKFILL_FLOOR=1_SOURCE_PLUS_1_SYNTHETIC
INDEPENDENT_CRITICAL_RESERVE=NOT_QUALIFIED
CURRENT_AUTHORING_INPUT_SLOTS=434
CANDIDATE_LEVEL_SELECTION_METADATA=0
FINAL_CANONICAL_CONFIRMATION=NOT_RUN
PRODUCTION_SOLVER_PROFILE_V2_SOLVE=NOT_RUN
PROFILE_V2_RESERVED_FOR_FINAL_CANONICAL=YES
CANDIDATE_TEXT_MATERIALIZED=NO
HUMAN_REVIEW_PERFORMED=NO
PROTECTED_MEMBERSHIP_PERSISTED=NO
DR001_CHANGED=NO
RES71_REFERENCES_CHANGED=NO
```

## Authority inventory

The read-only inventory used the sealed RES-71 reference module, the current
typed production authoring inputs, Phase-A accepted-source manifests, and the
external production directory. No candidate packets or candidate prose were
read or produced.

| Authority | Current supply |
| --- | --- |
| Sealed RES-71 references | 12 validated references: 5 `VALUE`, 4 `REFUSAL`, 1 `COMPARABILITY`, 2 `CLAIM_AUTHORITY`; 6 registered operation identities; digest `sha256:d29d84699b7cf70c2d409d370c5ffd6c7ad7cd704375b14b541527a95fa385e5` |
| Phase-A accepted source metadata | 104 accepted documents across 94 source families: 5 direct-target, 95 indirect-measurement, 4 noncanonical-context documents; 104 source-tag support rows |
| Current source selections | 40 selections across 40 documents and 38 source families, covering 5 direct-target documents and all 10 Phase-A search strata |
| Unselected source metadata | 64 accepted documents remain unselected; each has a source-tag support row. This is raw source authority, not 64 qualified candidate slots. |
| Registered synthetic generator | 3 registered split-family entries, 1 generator identity, digest `sha256:1e75e89e95b3705f9adc0d58cf06d92fd1a335b5da68863be4a5a2be98069a64` |
| Current synthetic seed blocks | 12 unique blocks bound in the current private inputs |
| Expert-semantic lane | 146 author-batch, template, and isolation-cluster identities covering 240 planned semantic slots; no additional slot is recorded |
| Mutation lane | 37 parent roots and lineages; 111 child seed blocks; operator counts: identity trap 7, comparability overreach 7, claim-boundary overreach 7, safe-partial refusal trap 8, error-correction trap 8 |
| Current production candidate and review stores | No production candidate or review directory and 0 production candidate files; the existing production-lock report records 0 candidates created and 0 human approvals |
| Qualification exclusion | 101 qualification candidates are excluded from production reuse by the current exclusion boundary |

The current typed `ProductionAuthoringInputsV1` file validates against its
input digest `sha256:b1549e62d61de905939a1a8139ff55c4f2ce9ac0fd0d25412026eb5f34fccea9`
and the registered generator digest. Its external file digest is
`sha256:b64146e9eb6f4b917a4f199f589a72cba2d4312e2be3a3719cba54bb8016b044`.
It contains 271 scenario seeds (240 semantic and 31 engine), 12 synthetic seed
blocks, 40 source selections, and 111 mutation seed blocks: exactly 434
prospective authoring slots. It does not contain production
`FinalSelectionCandidate` metadata.

Phase-A manifest digests:

```text
accepted.jsonl=sha256:5f32fd5fda9e9072c90afd49f8e3080ed9fd8a9c160e962eccdfc7a97b3f8335
source_families_001.jsonl=sha256:4d3420fcd5a1e0b3bad24db73e8a6ed68308cdc5a1f19dab9f2fcf3e289156b7
source_tag_support_evidence_001.jsonl=sha256:7dd8bcf756ffa5de4cf26db3f5fcd3227c153d7295b3e46dacd0bf9ef20e9bac
phase_a_source_authority_head=6b2d3bee397d3b7efe1faee908a6ec86ce7540bd
qualification_exclusion_digest=sha256:5bcc5da6fe959a66b819eb4a6c45326f82b06c4660a114de5f20aa3adf3b6343
production_lock_report=sha256:4f741e3ca4dc8ec66532919f0fd9622b78d3ecd5b2f77b299c41e0a7bc0a7c21
```

## Reserve derivation

The reserve rule is structural: every one-candidate removal must retain an
exact feasible `434 / 260 / 87 / 87` assignment under the RES-369 constraints.
The current planned origin counts imply these necessary lower bounds before
critical-feature and isolation checks:

| Constraint | Current slots | Required to tolerate any one removal | Detected deficit |
| --- | ---: | ---: | ---: |
| Final selected count | 434 total | Pool size at least 435 | At least 1 slot |
| Source-backed minimum | 40 | At least 41 source candidates | 1 source candidate |
| Engine-derived minimum | 30 | At least 31 engine candidates | 0; 31 planned |
| Deterministic-synthetic minimum | 12 | At least 13 synthetic candidates | 1 synthetic candidate |
| Mutation minimum | 60 | At least 61 mutation candidates | 0; 111 planned |
| Mutation lineages | 20 | At least 21 distinct lineages | 0; 37 planned |
| Expert-semantic maximum | At most 240 selected | No pool reserve implied by the maximum | 0 |

The two origin deficits require at least one additional source-backed slot and
one additional synthetic slot. Added to the current 434 slots, the resulting
known lower bound is 436. This is not a selected pool size: coverage,
isolation, candidate metadata, and critical reserve may require more.

There are 5 critical error classes and 2 protected splits. Each existing
critical feature minimum is 1; tolerating removal of any one candidate
therefore requires at least 2 independently assignable candidate identities
for each class/split requirement: 10 requirements and 20 required
candidate-feature incidences. RES-115's aggregate `N434_FEASIBILITY_FIXTURE`
receipt records baseline protected-critical feasibility only. It does not
establish these independent reserve incidences for an actual candidate pool.

## Missing authority

The exact deficits cannot be closed from the current production candidate
metadata because no production candidate packet or per-candidate selection
metadata exists. The current private inputs are seed, source-selection,
expert-batch, and mutation-lineage inputs; they do not bind the features,
isolation relations, source/RES-71 identities, exact-shingle digests, or
mutation-parent payload hashes needed by the exact oracle.

The targeted expansion required before qualification is:

1. One additional governed source selection, binding a distinct eligible
   Phase-A document/family, capability/family, applicability, and exact support
   span. The accepted registry has unused documents, but the current active
   production input has exactly 40 selections.
2. One additional unique synthetic seed block and candidate slot under the
   existing registered generator identity. The current input has 12 of 12
   planned seed blocks bound.
3. Candidate-level metadata for the full proposed pool that proves the 20
   critical feature incidences and exact source, engine-reference, generator,
   expert-batch, mutation-parent, and contamination/isolation identities.
   Backfill beyond the two known deficits must be derived from those metadata
   and the exact removal oracle.

No additional engine reference, mutation root, or mutation operator is
required by the known count bounds. If exact feasibility identifies a specific
critical or isolation deficit, any further supply must name its governed
source, expert, generator, or mutation-root/operator authority.

## Implementation and evidence

- Added a feasibility-only CP-SAT solve path. It encodes the existing
  RES-369 hard-constraint vocabulary, returns only a plan digest, and passes
  any witness to the independent semantic validator. It does not optimize or
  canonicalize. The feasibility path rejects production solver profile v2,
  reserving it for final canonical confirmation.
- Added variable-size pool metadata planning, structural `minimum + 1`
  backfill needs, authority-bound backfill inputs, exact checks after every
  planned candidate removal, and an explicit independent critical-reserve
  status. It adds only supplied backfill candidates that address a detected
  bound. Pending/unapproved candidates are treated as potential capacity only
  inside the ephemeral oracle view; plan metadata retains their original
  review status.
- Focused RES-383 and RES-369 selection tests: 33 passed. Ruff, formatting,
  and mypy passed on the changed Python files.
- The exact live reserve oracle and production-profile-v2 canonical
  confirmation were not run because no candidate-level production metadata
  pool exists and the detected source/synthetic deficits remain unfilled.

The receipt intentionally stops at `AUTHORITY_EXPANSION_REQUIRED`. No
candidate supply, critical reserve, or final pool membership is inferred from
the metadata inventory alone.
