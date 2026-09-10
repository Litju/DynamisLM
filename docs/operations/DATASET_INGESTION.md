# DynamisLM dataset ingestion operations

This runbook describes the RES-63 canonical empirical ingestion boundary. It
is intentionally small: source identity, exact-byte acquisition, schema and
population qualification, source-variable identity, football-context mapping,
quarantine, promotion, and replay.

## Roots

```text
REPOSITORY=~/projects/DynamisLM
REAL_DATA=~/data/dynamislm
```

The resolver honors an explicit override:

```bash
export DYNAMISLM_DATA_ROOT="$HOME/data/dynamislm"
```

The export is optional and is not written to shell startup files by the
project. If absent, the resolver uses `Path.home() / "data" / "dynamislm"`.

Before use, the resolver obtains the Git root mechanically, expands the
configured path, resolves symlinks, and fails if the data root equals the
repository or is beneath it. This guard applies even when a path is ignored by
Git.

## External tree

After the containment check, create the tree with:

```bash
mkdir -p \
  "$DYNAMISLM_DATA_ROOT/objects/sha256" \
  "$DYNAMISLM_DATA_ROOT/metadata" \
  "$DYNAMISLM_DATA_ROOT/receipts" \
  "$DYNAMISLM_DATA_ROOT/canonical" \
  "$DYNAMISLM_DATA_ROOT/quarantine" \
  "$DYNAMISLM_DATA_ROOT/tmp/acquisition"
```

Raw bytes are stored as:

```text
objects/sha256/<first-two-hex>/<full-sha256>
```

The original filename is recorded in the acquisition receipt. It is metadata,
not byte identity.

## Acquisition

`acquire_url` accepts a typed `DatasetSourceIdentity` and
`DatasetVersionIdentity`. It requires HTTPS, an explicit finite timeout, and
streams the response into `tmp/acquisition`. It records:

```text
requested URL
resolved final URL
original filename
media type
exact byte size
SHA-256
timezone-aware UTC retrieval time
ETag when supplied
Last-Modified when supplied
provider checksum/UNF when supplied
metadata snapshot SHA-256 when supplied
```

The SHA-256 is updated during streaming. The temporary file is flushed and
fsynced before verification. A verified object is atomically moved to its
shard. If that digest already exists, the existing object is independently
verified by size and digest and the duplicate temporary file is removed.

If an expected digest differs, acquisition emits a `SourceVersionConflict`
receipt and fails closed. It does not overwrite the registered artifact or
silently change the source version. Provider hashes remain supplementary:

```text
PROVIDER_HASH != DYNAMISLM_SHA256
ETAG != CRYPTOGRAPHIC_AUTHORITY
```

## Metadata snapshots and registries

Provider-native structured metadata are captured under `metadata/` and hashed
separately from data bytes. Committed files under `registries/datasets/` hold
public source/version/file/license metadata, expected SHA-256 and size,
provider checksums, evidence references, qualification state, and reason
codes. They never hold raw athlete rows, DOB tables, canonical rows, tokens,
credentials, or private URLs.

`SourceMetadataClaim` preserves each official claim. When claims disagree,
write a `SourceMetadataConflict` and separately report the fact computed from
verified bytes. A distinct date-value count is not called an official match
count unless the source semantics establish that identity.

## Qualification

Use the existing RES-60 functions:

```python
from dynamislm.population import qualify_canonical_population, qualify_canonical_source
```

Do not create a second population engine. Every canonical source must satisfy
the exact target clauses:

```text
MALE + SENIOR + ASSOCIATION_FOOTBALL + PROFESSIONAL
+ FIRST_TEAM + TOP_DOMESTIC_DIVISION
```

Unknown or ambiguous clauses remain unresolved. `MISSING != ZERO` and no
imputation is performed. A source can be scientifically eligible while a
license or training-use decision remains independent.

## Source variables

Every exact original column receives a `SourceVariableIdentity`. Preserve
source labels, units, thresholds/bands, aggregation context, provider/device
notes, method family, definition references, resolution state, and missing
information. A threshold is part of identity; similar labels are not
normalized.

Use `PROVIDER_DERIVED` for a provider output such as PlayerLoad when the table
reports it but the system does not own a reproducible public equation. Do not
convert it to generic work, power, load, or a final RES-64 metric. Public
sampling descriptions are metadata and do not imply public raw GNSS or IMU
waveforms.

Date of birth is source-only unless a separately registered scientific
operation requires it. Retain source-local pseudonymous athlete IDs and do not
resolve them to names.

## Football context and raw-row identity

Map only source-supported context. The ingestion intermediate can preserve
athlete, source-local session/date, competition, explicit season, and position
when documented. Do not invent opponent, round, stadium, fixture ID,
home/away, microcycle, match-day-relative context, firmware, software,
thresholds, or provider algorithms.

Every row retains:

```text
source_id + source_version + raw_artifact_sha256 + source_row_number
```

An available natural key is additional metadata only. Do not assume
`AthleteID + Gamedate` is unique.

Every adapter names a stable mapping version, for example
`unifesp-serie-a-mapping@1.1.0`. Same raw bytes with a changed mapping version
can produce a different canonical artifact; that is a new explicit output and
never an overwrite of an earlier mapping result.

The committed registry produces a typed `RegisteredDatasetFileIdentity` for
each source file. Its expected SHA-256, byte size, representation, filename,
media type, and provider identifiers are not populated from live metadata.
Live provider metadata is an observation checked against that identity. Source
A uses `ARCHIVAL_TAB`; a Dataverse `SAVED_ORIGINAL` download is a separate,
noncanonical diagnostic representation.

## Quarantine and promotion

`QuarantineReceipt` must identify the source/version, artifact digest when
available, failed stage, exact reason codes, missing information, evidence,
affected rows/variables, and requirements for requalification. Examples:

```text
UNRESOLVED_RECORD_GRANULARITY
UNRESOLVED_FIRST_TEAM_STATUS
UNRESOLVED_SEX_EVIDENCE
UNRESOLVED_PROVIDER_THRESHOLD
UNRESOLVED_METHOD_VERSION
UNRESOLVED_PUBLICATION_PROVENANCE
PUBLIC_ACQUISITION_NOT_REPRODUCIBLE
RAW_BYTES_MISMATCH
SOURCE_VERSION_CONFLICT
FOOTBALL_CONTEXT_UNRESOLVED
```

The sole promotion authority derives all of these gates from a typed
`PromotionEvidence` tree:

```text
runtime integrity
source qualification
population qualification
raw bytes verified
source version verified
license captured
variable identity resolved
football-world mapping resolved
complete lineage
```

There is no public nine-boolean promotion API and no `force=True`,
`manual_override=True`, or owner override. `PromotionDecision` recomputes its
status, reason codes, and content-derived decision ID from nested evidence.
A qualified source does not qualify every variable. Unresolved variable
semantics remain quarantined.

## Canonical replay

Full real canonical output is JSONL under `canonical/` in the data root. It is
UTF-8, uses sorted JSON keys and explicit LF line endings, orders records by
source row and the registered source-variable order, and has a deterministic
SHA-256. The production writer is streaming and fails if its iterator is out of
order; it does not materialize a full record tuple or giant string/bytes value.
Complete source-variable identities are stored once in an external registry
sidecar and rows carry only `source_variable_id`. Acquisition timestamps are
excluded from semantic content. Full qualification decisions are stored once
in external receipts and canonical rows reference their stable IDs.

Replay the same verified bytes with the same registered metadata and mapping
version using the offline entry point:

```bash
uv run python scripts/res63_replay.py \
  --source unifesp-brazil-serie-a-v1 \
  --data-root "$DYNAMISLM_DATA_ROOT" \
  --report-dir /tmp/res63-reports \
  --verify
```

Require identical record count, ordering, canonical SHA-256, variable-registry
SHA, mapping version, population/source decisions, variable identities,
metadata-conflict receipts, and quarantine decisions. Ordinary replay does not
refresh network metadata. A transform never depends on filesystem enumeration
or Python hash ordering.

## Initial sources

Source A (`unifesp-brazil-serie-a-v1`) is qualified and promoted from its
verified official `ARCHIVAL_TAB` bytes. The source claim graph keeps separate
the Dataverse version description, Domus collection description, paper
abstract, paper Methods 2.1, paper main-team/professional-adult context, and
verified file facts. The paper's 98-player abstract claim and 99-player
Methods claim remain distinct from the separate Domus 90-player claim. Source
B (`mendeley-rpl-v1`) is quarantined
because the exact captured evidence does not establish the male-sex or
first-team clauses.
Source C (`mendeley-turkish-super-league-instat-v1`) is quarantined because the
verified workbook is resolved `TEAM`-level aggregate data without player
identifiers; its quarantine reason is
`TEAM_AGGREGATE_NOT_CANONICAL_ATHLETE_RECORD`, not unresolved granularity.
Source D (`zenodo-ekstraklasa-training-adaptation`) is quarantined pending
publication/provenance and first-team-status proof.

## Git firewall and QA

Git may contain typed contracts, adapters, public registries, schema and
qualification reports, conflict/quarantine receipts, hashes/counts, and small
synthetic fixtures only. Real raw files and full canonical tables remain
outside Git.

The `.tab` extension is controlled by the RES-75 repository policy. It is
allowed only for an explicitly allowlisted fixture beneath
`tests/fixtures/synthetic/` and within the existing size limit.

Before review, run from `~/projects/DynamisLM`:

```bash
./scripts/qa-fast.sh
uv run python scripts/repository_policy.py
./scripts/ci.sh
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest
git diff --check
```

Also compare real raw/canonical SHA-256 digests with `git ls-files`. Required:

```text
RAW_SOURCE_BYTES_IN_GIT=NO
REAL_CANONICAL_ROWS_IN_GIT=NO
MODEL_TRAINING_USE=NOT_AUTHORIZED_BY_RES63
SERIALIZATION_VERSION=3
RES64_FORMULAS_IMPLEMENTED=NO
```
