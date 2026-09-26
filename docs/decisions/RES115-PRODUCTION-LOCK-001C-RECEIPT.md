# RES-115 production authoring lock receipt

**Mission:** `RES-115-CASE-AUTHORING-001C-PRODUCTION-LOCK-001`

**Status:** `PASS`

**Entry HEAD:** `d1685d2600b1005a1ceb6fa1297096af46897526`

**Phase-A source authority:** `6b2d3bee397d3b7efe1faee908a6ec86ce7540bd`
**Frozen benchmark:** [RES21-DR-001](RES21-DR-001-performance-science-eval-v1.md)

## Production contract

Production is a separate, pending-review candidate lane. Candidate IDs use
`PSE-V1-CANDIDATE:<stable-id>`. Semantic and source-backed proposals identify
`agent-process:codex:RES-115-CASE-AUTHORING-001C`; expert author batches remain
bounded identities distinct from that process. The production store contract
accepts only external paths under `production/`.

The first freeze target is locked at exactly `N=434`:

| Split | Prospective cases |
| --- | ---: |
| `PUBLIC_DEVELOPMENT` | 260 |
| `FROZEN_VALIDATION` | 87 |
| `HIDDEN_FINAL` | 87 |

The production seed parser binds the split, generator ID/version, and seed
block. Pre-review feasibility and final allocation honor that split lock.
Final allocation still uses the reviewed final case hashes and remains the
authority for membership.

The pre-review gate consumes only candidate metadata commitments. Its
synthetic 434-commitment test fixture passes the exact targets, 87 cells per
split, row-level tags and reachable errors, C18 refusal coverage, protected
critical-error eligibility, isolation, and deterministic-synthetic split
eligibility. The receipt contains aggregate counts and a private witness
digest; it stores no candidate-to-split mapping.

## Qualification exclusion

The sealed external 001B manifest and store supplied 101 pending qualification
packets. The exclusion commitment binds their candidate IDs and payload hashes,
exact and normalized question fingerprints, 13-token shingle hashes, blocking
fuzzy match text, generator seed identities, mutation lineage, and exact
evidence-span IDs/digests. Production validation rejects those identities and
the frozen contamination policy rejects prompt clones. Reusing a Phase-A paper
with a different exact evidence span remains eligible.

The private index is external-only:

- Path: `production/exclusions/qualification-001B-private.json`
- Commitment digest: `sha256:5bcc5da6fe959a66b819eb4a6c45326f82b06c4660a114de5f20aa3adf3b6343`
- Unique qualification evidence spans: `23`

The Git training/development exclusion manifest contains 101 IDs, hashes, and
fingerprints, with no question text or seed values:

- [Qualification training exclusions](../../reports/performance_science_eval/qualification_training_exclusions.json)
- Manifest digest: `sha256:45aa4dfdcacbe90b1768800da5eee2695e680f3febdd758fb5885a23bbb2b350`

Both the 001B qualification leak guard and the production private-material
guard pass against Git history, index, and worktree.

## Storage and lifecycle

| Gate | Result |
| --- | --- |
| Production candidates created | `0` |
| Human approvals created | `0` |
| Final cases promoted | `0` |
| Final split allocation | `NO` |
| Protected stores provisioned | `NO` |
| Model inference / training | `NO` / `NO` |
| RES-22+ implemented | `NO` |
| Scientific engine changed | `NO` |

The production candidate directory was not created. Only the private
qualification exclusion index was written under the external production root.

Transient disk storage uses deterministic file-byte checkpoints under
`/mnt/d/Dev/Caches/DynamisLM/PMC`; the lock checkpoints measured `0` bytes
(`TRANSIENT_CACHE_PEAK_MB=0.0`). The hard limit remains `2,000,000,000` bytes.
`PROCESS_PEAK_RSS_MB=63.09375` is reported separately and is not used as a disk
measurement.

## QA and disposition

`./scripts/ci.sh`: `PASS`

`TEST_COUNT=980`

`QA_TRACKED_MUTATION=NONE`

`CURRENT_BLOCKERS=NONE`

`NEXT_AUTHORIZED_ACTION=RES-115-CASE-AUTHORING-001C-MATERIALIZE-001`
