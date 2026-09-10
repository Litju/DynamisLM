# RES63-DR-001 — Canonical dataset ingestion and qualification

## Control

`DECISION_ID=RES63-DR-001`

`SPEC_VERSION=1.0.0`

`STATUS=ADOPTED_FOR_REVIEW`

`SERIALIZATION_VERSION=3`

This record realizes **DynamisLM — Canonical Dataset Ingestion &
Qualification Specification V1** for RES-63. It establishes data, identity,
qualification, byte integrity, and raw-to-canonical lineage authority. It does
not authorize the next scientific-engine unit.

## Scientific question

How can real public football-performance datasets be acquired, identified,
qualified, quarantined, and replayed deterministically for the exact V2 target
population while keeping raw bytes and full canonical tables outside Git and
keeping source-reported values distinct from DynamisLM computational
derivations?

## Scope and constitutional boundary

The canonical target population is fixed and conjunctive:

```text
SEX = MALE
AGE_CLASS = SENIOR
SPORT = ASSOCIATION_FOOTBALL
PROFESSIONAL_STATUS = PROFESSIONAL
SQUAD_LEVEL = FIRST_TEAM
COMPETITION_LEVEL = TOP_DOMESTIC_DIVISION
```

Rows must also be actual measured or observed athlete data relevant to
performance science. Women, youth/U23, academy, university, amateur,
semi-professional, lower-division, other-sport, and inseparable mixed rows
are not broadened into the target population.

The existing RES-60 `qualify_canonical_population` and
`qualify_canonical_source` functions remain the only population/source
qualification authority. RES-63 adds row-level integrity and mapping around
those decisions; it does not implement a second population engine.

The three constitutional scopes remain distinct:

```text
KNOWLEDGE_SCOPE != COMPUTATIONAL_AUTHORITY_SCOPE != CLAIM_AUTHORITY_SCOPE
```

Source-reported values are external observations. Provider-derived outputs are
not direct physical measurements, and neither is an accepted RES-64
DynamisLM computational derivation.

## Evidence roles

RES-63 reuses the RES-60/V2 roles:

```text
CANONICAL_EMPIRICAL_TARGET
DIRECT_TARGET_POPULATION_EVIDENCE
INDIRECT_MEASUREMENT_EVIDENCE
NONCANONICAL_CONTEXT_ONLY
REJECTED_OR_UNRESOLVED
```

An evidence role is claim-relative. A source may be useful for a method claim
without becoming a canonical empirical target. Synthetic fixtures are
explicitly `origin=synthetic_deterministic` and never establish observed
empirical evidence.

## Repository and storage decision

The repository root is represented operationally as `~/projects/DynamisLM`.
The current native-WSL empirical-data root is represented as
`~/data/dynamislm`, or by the explicit `$DYNAMISLM_DATA_ROOT` override.

The resolver expands the configured path, resolves symlinks, obtains the Git
root mechanically through `git rev-parse --show-toplevel`, and rejects a data
root equal to or beneath the repository. The guard therefore rejects
`repo/data`, `repo/.data`, `repo/datasets`, and symlinks that point into the
repository. It does not rely on `.gitignore`.

The invariant is:

```text
REPOSITORY_ROOT ∩ EMPIRICAL_DATA_ROOT = ∅
DATA_INSIDE_WSL=YES
DATA_ROOT_INSIDE_REPO=NO
```

The external tree is:

```text
objects/sha256/<first-two-hex>/<full-sha256>
metadata/
receipts/
canonical/
quarantine/
tmp/acquisition/
```

No shell startup file is modified automatically. Committed registries and
reports use relative content-addressed paths and never resolve the operator's
home directory.

## Runtime-integrity decision

The pre-ingestion seal closes the direct-construction/V3-decode asymmetry for
the generic leaf boundary. Narrow constructor checks now validate nested
instances, immutable tuples, enum values, scalar result variants, explicit
timezone values, provenance nodes, and lineage types. No dataclass fields,
wire shape, serialization version, or historical valid hash is changed.

The promotion boundary requires runtime integrity before any record can be
promoted. No pydantic, typeguard, beartype, or generic runtime type system is
introduced.

## Identity and version decision

`DatasetSourceIdentity` records source ID, provider, title, landing page, and
persistent identifier. `DatasetVersionIdentity` records repository version,
version-specific identifier when available, and publication date when known.

The following are separate facts:

```text
SAME_DOI_OR_HANDLE != SAME_BYTES
SAME_LANDING_PAGE != SAME_VERSION
SAME_VERSION_LABEL + CHANGED_BYTES = SOURCE_VERSION_CONFLICT
```

A source revision is never overwritten in place. A changed provider artifact
requires a new explicit registry revision or a first-class conflict receipt.

## License and training-use decision

`DatasetLicenseIdentity` is a deliberately small machine-readable contract.
The current implementation supports `CC-BY-4.0` and `CC-BY-NC-4.0`, with the
canonical URI, assertion URI, attribution flag, noncommercial flag, and notes.
Unsupported expressions and inconsistent restriction flags fail closed.

License qualification is independent of population qualification, source
qualification, and training authorization. The global RES-63 lock is:

```text
MODEL_TRAINING_USE=NOT_AUTHORIZED_BY_RES63
```

No permissive or noncommercial license captured by RES-63 authorizes DAPT,
SFT, RL, RLVR, training-text construction, commercial model training, or
noncommercial model training. A later training-data mission must independently
qualify legal and project authorization.

## Byte-integrity and provider-hash decision

DynamisLM SHA-256 over the exact downloaded bytes is the raw-artifact
authority. Acquisition streams HTTPS response bytes into a temporary file in
`tmp/acquisition`, updates SHA-256 and byte count during the stream, flushes
and fsyncs the file, verifies expected digest/size, and atomically stores the
object under the sharded content-addressed path.

```text
SHA256(EXACT_BYTES) = DYNAMISLM_RAW_ARTIFACT_IDENTITY
ORIGINAL_FILENAME != BYTE_IDENTITY
PROVIDER_HASH != DYNAMISLM_SHA256
ETAG != CRYPTOGRAPHIC_AUTHORITY
```

Dataverse UNF/checksum, Mendeley SHA-256 metadata, and Zenodo MD5 are retained
as supplementary provider provenance. An existing object with the same
digest is size- and digest-verified and reused; it is never replaced by a
duplicate temporary file. A registered expected digest mismatch emits a
`SourceVersionConflict` receipt and fails closed.

## Metadata and schema decision

Provider-native structured metadata are captured where available. The
canonical metadata snapshot digest is distinct from the raw file digest.
`SourceMetadataClaim` retains each official/provider claim. Conflicting claims
are represented by `SourceMetadataConflict`; a verified row, key, or byte fact
is stored separately as `VERIFIED_FILE_FACT`.

Tabular schema inspection preserves exact headers and computes row count,
column count, distinct source athlete IDs, distinct date values, missingness,
duplicate raw rows, candidate natural-key duplicates, and structural observed
types. XLSX inspection uses the bounded `openpyxl>=3.1,<4` dependency because
the provider files are real OOXML workbooks; pandas is not added.

`MISSING != ZERO` and no imputation is authorized.

## Source-variable decision

Every source column receives a `SourceVariableIdentity` with:

```text
original_column_name
source_label
source_role
source_reported_unit
source_provider
source_method_family
source_threshold_or_band
source_aggregation_context
source_device_or_sampling_note
source_definition_reference
resolution_status
missing_information
```

The allowed roles are `CONTEXT`, `DIRECT_REPORTED`, `PROVIDER_DERIVED`, and
`UNRESOLVED`. Thresholds and bands are identity-bearing:

```text
DISTANCE_GT_20_KMH != DISTANCE_GT_25_KMH
METRIC_LABEL != SCIENTIFIC_MEASUREMENT_IDENTITY
```

PlayerLoad, IMA, RHIE, thresholded distances, and similar provider outputs are
kept under exact source/provider/method identity. Proprietary equations are
not reconstructed. Public sampling/device descriptions are retained as
metadata only; a public derived player-match table is not claimed to contain
raw GNSS or IMU waveforms.

Date of birth is source-only by default. Source-local pseudonymous athlete IDs
are retained; no real-world name resolution is performed.

## Football-world mapping decision

RES-61 identity/context concepts are reused where source evidence supports
them. The ingestion intermediate can represent an athlete, source-local
session/date, competition, season when explicit, and position. It does not
invent opponent, fixture ID, round, stadium, home/away, training day,
microcycle, match-day-relative label, software, firmware, device model, or
provider algorithm parameters.

The intermediate is not forced into a final RES-64
`ScientificMeasurementObservation`. Football context remains separate from
measurement identity.

## Raw-row and lineage decision

Each row identity contains:

```text
source_id
source_version
raw_artifact_sha256
source_row_number
natural_source_key (when present)
```

`AthleteID + Gamedate` is recorded as a candidate natural key but is not
assumed unique. The source row number remains authoritative when the candidate
key repeats.

Each adapter has an explicit mapping version. For example:

```text
unifesp-serie-a-mapping@1.0.0
```

The canonical path is:

```text
DatasetSourceIdentity
  -> DatasetVersionIdentity
  -> VerifiedRawArtifact SHA-256
  -> ArtifactAcquisitionReceipt
  -> SourceSchema
  -> source row
  -> mapping version
  -> CanonicalEmpiricalRecord
```

The mapping depends only on verified raw bytes, registered metadata, and the
mapping version. Wall clock, network access at transform time, filesystem
enumeration order, and Python hash ordering are not transform inputs.

## Qualification, quarantine, and promotion decision

`QuarantineReceipt` is first-class and records source/version, artifact digest
when available, failed stage, exact reason codes, missing information,
evidence, affected rows/variables, and requalification requirements.

There is exactly one promotion authority. A record/source can promote only
when every mandatory term is true:

```text
RUNTIME_INTEGRITY_PASS
AND SOURCE_QUALIFIED
AND POPULATION_QUALIFIED
AND RAW_BYTES_VERIFIED
AND SOURCE_VERSION_VERIFIED
AND LICENSE_CAPTURED
AND VARIABLE_IDENTITY_RESOLVED
AND FOOTBALL_WORLD_MAPPING_RESOLVED
AND LINEAGE_COMPLETE
```

There is no `force`, `manual_override`, or owner override. A qualified source
does not automatically qualify every variable. Unresolved variable semantics
remain quarantined and do not enter canonical JSONL.

## Canonical artifact and replay decision

Full canonical empirical output is deterministic JSONL under
`canonical/` in the external root. UTF-8, stable key ordering, explicit `\n`
newline behavior, stable raw-row/variable ordering, and a content SHA-256 are
fixed. Acquisition timestamps are not semantic canonical content.

The JSONL payload is privacy-minimized and references full source/population
decisions by stable IDs; full decision trees remain in external qualification
receipts. No row, DOB list, raw byte, or full canonical table is committed to
Git.

## Initial source decisions

### Source A — UNIFESP/Domus Dados Brazilian Serie A

`unifesp-brazil-serie-a-v1` is qualified and promoted. Its persistent ID is
`hdl:20.500.12682/rdp/GMXME8`, version `1.0`, and official license
`CC-BY-NC-4.0`. The verified published tab artifact is retained at its
content-addressed SHA and has 5,202 rows and 28 columns, 98 distinct source
athlete IDs, 361 distinct date values, zero duplicate raw rows, and zero
candidate natural-key duplicates.

Official/provider participant, match, case, file-size, and provider-MD5 claims
are retained as five explicit conflict receipts. The current exact downloaded
bytes are authoritative under SHA-256; the provider MD5/size are supplementary
claims and are not silently substituted.

The source-variable registry preserves the exact threshold labels, provider
methods, Catapult VECTOR7 metadata, and provider-derived status. Date of birth
is excluded from canonical output. The canonical artifact has 140,454
row-variable records under `unifesp-serie-a-mapping@1.0.0` and is replay-stable.

### Source B — Mendeley Russian Premier League

`mendeley-rpl-v1` is acquired and schema-inspected, but quarantined with
`UNRESOLVED_SEX_EVIDENCE`, `UNRESOLVED_FIRST_TEAM_STATUS`, and
`POPULATION_SCOPE_UNRESOLVED`. The workbook has
115 rows, 16 columns, 24 distinct player identifiers, and 14 distinct match
identifiers on the inspected data sheet. The captured source evidence does not
explicitly establish the male-sex or first-team clauses for the exact cohort,
so no canonical records are promoted.

### Source C — Mendeley Turkish Super League/InStat

`mendeley-turkish-super-league-instat-v1` is acquired and quarantined after
granularity audit. The data sheet exposes team/match aggregates and no player
identifier; the verified classification is `TEAM`. Reasons are
`UNRESOLVED_RECORD_GRANULARITY`,
`TEAM_AGGREGATE_NOT_CANONICAL_ATHLETE_RECORD`,
`UNRESOLVED_SEX_EVIDENCE`, and `UNRESOLVED_FIRST_TEAM_STATUS`.

### Source D — Zenodo Ekstraklasa training adaptation

`zenodo-ekstraklasa-training-adaptation` is acquired as a verified ZIP. The
provider MD5 is retained separately from the local SHA-256. It remains
quarantined under `UNRESOLVED_PUBLICATION_PROVENANCE` and
`UNRESOLVED_FIRST_TEAM_STATUS` until package-to-manuscript linkage,
raw-versus-derived field provenance, and exact cohort evidence are resolved.

## Real-data Git firewall

RES-75 policy is extended narrowly so `.tab` is a controlled tabular fixture
extension. A `.tab` file is permitted in Git only under
`tests/fixtures/synthetic/`, on the explicit allowlist, and within the 1 MiB
fixture limit. The committed fixture is deterministic synthetic data and has
no real athlete rows or exact DOB records.

Before review, real raw and canonical SHA-256 digests are compared with every
tracked Git file. The required result is:

```text
RAW_SOURCE_BYTES_IN_GIT=NO
REAL_CANONICAL_ROWS_IN_GIT=NO
```

## Alternatives rejected

- Broadening the population to obtain more rows — rejected by the sealed V2
  target population.
- Treating provider prose as file truth — rejected; claims and verified file
  facts remain separate.
- Treating provider MD5, UNF, or ETag as the local byte authority — rejected;
  SHA-256 over exact bytes is authoritative.
- Treating a DOI, landing page, or version label as byte identity — rejected.
- Treating team aggregates as canonical athlete records — rejected.
- Reconstructing proprietary PlayerLoad/IMA/RHIE algorithms — rejected and
  deferred to later scientific authority where admissible.
- Propagating exact DOB or resolving player names — rejected by minimization.
- Adding DVC, RO-Crate, BagIt, cloud warehouses, or a generic data lake —
  rejected because narrow native contracts meet this boundary.
- Changing CI workflow, main ruleset, or RES-75 hook architecture — rejected;
  the existing hosted/local gate is sufficient.

## Non-goals and next boundary

RES-63 does not implement total distance, relative distance, HSR, sprint,
acceleration, deceleration, metabolic power, PlayerLoad, IMA, RHIE, GNSS,
optical-tracking equations, final measurement identities, LM training-data
construction, DAPT, SFT, RL/RLVR, inference, GPU work, or generic data-lake
infrastructure.

`RES64_FORMULAS_IMPLEMENTED=NO` and `SCIENTIFIC_NUMERICAL_AUTHORITY_CHANGED=NO`.
CMJ numerical science and all historical V3 hashes remain unchanged.
