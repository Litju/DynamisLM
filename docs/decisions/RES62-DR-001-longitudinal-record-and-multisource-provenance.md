# RES-62-DR-001 — Longitudinal record and multi-source provenance

## Status

`ADOPTED`

`RES-62`

`CONSTITUTION_VERSION=2.0.0`

`SERIALIZATION_VERSION=3`

## Scientific-data question

How can DynamisLM compose one athlete's immutable observations across many
football sessions, devices, providers, measurement identities, and seasons
while preserving each observation's existing identity, result, football-world
placement, source/acquisition/processing lineage, and RES-60 source
qualification?

This unit establishes longitudinal data and lineage authority only. It does
not establish a statistical estimator, a measurement-error model, or any
longitudinal sports-science claim.

## Authority inspected

- `docs/architecture/SCIENTIFIC_CONSTITUTION_V2.md` — sealed target world,
  population boundary, missingness rule, and deterministic-authority split.
- `docs/architecture/MEASUREMENT_DATA_PROVENANCE_V1.md` — observation,
  provenance, reprocessing, and claim-relative comparability contracts.
- `docs/architecture/P1_EXECUTION_CONTRACT.md` — registered-operation and
  evidence-decision workflow.
- `docs/architecture/REASONING_CLAIMS_EVALUATION_V1.md` — longitudinal claim
  ladder and refusal boundary.
- `docs/decisions/RES60-DR-001-canonical-population-and-source-gate.md` —
  canonical source qualification and synthetic-source exclusion.
- `docs/decisions/RES61-DR-001-football-world-ontology.md` — typed athlete,
  team, season, session, exposure, and observation placement.
- Existing source files and regression tests under
  `src/dynamislm/measurement/`, `src/dynamislm/provenance/`,
  `src/dynamislm/population/`, `src/dynamislm/football/`, and `tests/`.

No broad literature review or external dataset search was required. The sealed
project contracts resolve the architecture question; the only new operation
is structural and non-statistical.

## Existing leaf authorities and the RES-62 composition boundary

The following existing objects remain immutable leaf/source authorities:

1. `ScientificMeasurementObservation` remains the authority for one
   observation's `ObservationContext`, `MeasurementIdentity`,
   `MeasurementResult`, and existing `Provenance`.
2. `ObservationContext`, `MeasurementIdentity`, and `MeasurementResult` remain
   separate authorities for context, what/how was measured, and observed
   output/status.
3. `SourceArtifact`, `AcquisitionRecord`, `ProcessingRun`, `LineageEdge`, and
   `Provenance` remain the authority for one observation's source and
   computational lineage.
4. `FootballWorldContext`, `CompetitionIdentity`, and `SeasonIdentity` remain
   RES-61/RES-60 authorities for typed football placement.
5. `CanonicalPopulationDecision` and `CanonicalSourceDecision` remain RES-60
   authorities for population/source qualification.

RES-62 wraps those authorities in:

- `SourceArtifactQualificationBinding`, which states which existing source
  decision qualified which exact source-artifact IDs without mutating either
  object;
- `LongitudinalObservationEntry`, which composes one unchanged scientific
  observation, one unchanged typed football-world context, and exact artifact
  qualification coverage;
- `LongitudinalAthletePerformanceRecord`, an immutable ordered snapshot of
  entries for one athlete;
- `MultiSourceAnalysisInput`, an immutable self-contained selected-entry
  snapshot with explicit temporal scope;
- `MultiSourceProcessingRun`, a new processing identity for a registered
  multi-source operation;
- `MultiSourceProvenanceGraph`, an additive DAG that unions source lineage and
  the new longitudinal edges; and
- `LongitudinalSourceManifestResult`, a structural result proving the
  end-to-end path without pretending to be a performance metric.

The multi-source provenance layer begins at the composition boundary: the
first RES-62 edge is from an unchanged source observation and its football
context/qualification to a `LongitudinalObservationEntry`. Existing
`Provenance` remains the authority below that boundary and is copied into the
new graph as typed nodes and edges, not flattened into metadata strings.

The following public wire types are deliberately unchanged in fields, module,
class identity, serialization, and hash behavior:

`ScientificMeasurementObservation`, `ObservationContext`,
`MeasurementIdentity`, `MeasurementResult`, `Provenance`, `SourceArtifact`,
`AcquisitionRecord`, `ProcessingRun`, `LineageEdge`, `FootballWorldContext`,
`CompetitionIdentity`, `SeasonIdentity`, `CanonicalPopulationDecision`, and
`CanonicalSourceDecision`.

`src/dynamislm/serialization.py` is not modified. New public RES-62 dataclasses
use the existing `@register_serializable_type` decorator and V3 envelope.

## Decisions

### 1. Longitudinal record identity

`LongitudinalAthletePerformanceRecord` is an immutable snapshot, not an
update-in-place entity. Its record ID is a deterministic
`InstanceIdentifier(instance_type="longitudinal-athlete-record", ...)` derived
from:

```text
record origin
+ athlete identity
+ canonical ordered entry hashes
+ registered RES-62 record method/version
```

Adding, removing, or changing an entry therefore creates a new record ID.
There is no first, primary, or preferred source.

### 2. Contextualized observation semantics

`LongitudinalObservationEntry` stores the complete
`ScientificMeasurementObservation` and the complete `FootballWorldContext`.
It does not copy fields from `MeasurementIdentity` or flatten the context.
Construction invokes RES-61 observation/world validation and additionally
requires matching athlete ID, session ID, and any explicit observation-context
ID. The observation timestamp must be within known session bounds; absent
session bounds remain unknown. Clock correction is not inferred.

### 3. Observed-canonical versus synthetic record semantics

`LongitudinalRecordOrigin` has exactly two explicit states:

- `OBSERVED_CANONICAL` — every bound source decision must be a passing
  `CANONICAL_EMPIRICAL_TARGET` decision;
- `SYNTHETIC_DETERMINISTIC` — fixture data remain explicitly synthetic and
  cannot carry a passing canonical empirical source decision.

No `is_real`, `canonical_empirical`, or equivalent ambiguous boolean is used.
A synthetic fixture may use the ordinary RES-60 qualification function and
retain its explicitly failed synthetic-source decision; it cannot turn that
decision into an empirical claim.

### 4. Source qualification to SourceArtifact binding

`SourceArtifactQualificationBinding` is an additive typed relationship between
one `CanonicalSourceDecision` and one or more source-artifact IDs. An entry
requires exact one-time coverage of every artifact in its unchanged
`observation.provenance.source_artifacts` tuple:

```text
covered artifact IDs == observation provenance artifact IDs
covered artifact IDs are unique
```

An artifact cannot receive conflicting source decisions in the same record.
The binding does not alter `SourceArtifact` or `CanonicalSourceDecision`.

### 5. Deterministic deduplication

Record and analysis-input builders index candidates by the stable qualified
`observation_id`. The only duplicate collapse rule is:

```text
same observation ID + same canonical entry content -> collapse exactly
same observation ID + different canonical entry content -> reject conflict
different observation ID -> preserve, even if every visible value matches
```

Canonical entry content includes the unchanged observation, football context,
and qualification bindings. Labels, dates, values, sessions, devices, or
provider similarity never deduplicate observations.

### 6. Ordering and canonical hashing

Builders sort entries by:

1. `observation.context.observed_at` converted to UTC;
2. qualified `observation_id`; and
3. canonical entry content hash.

The original observation timestamp is never changed. Direct record and input
construction requires this canonical order, so inconsistent wire reordering
fails during construction/decoding. Record, input, processing, manifest, and
graph identities are derived from canonical content and are independent of
input arrival order.

### 7. Multi-session, multi-season, and team semantics

One record may contain many sessions, testing/training/match contexts, devices,
measurement identities, providers, teams, and seasons. Each entry retains its
own `FootballWorldContext`. Same athlete plus same calendar date does not merge
different sessions. Same session does not merge different measurement
identities.

Cross-season record construction is valid. A downstream analysis must declare
whether it is same-session, within-season, or cross-season; record membership
does not silently choose an analysis scope or a lifelong team identity.

### 8. Multi-source analysis input semantics

`MultiSourceAnalysisInput` embeds selected `LongitudinalObservationEntry`
objects, not an unverified ID bag. It requires at least two distinct source
observations, validates one athlete, exact canonical order, exact duplicate
collapse through its builder, and carries each source's independent identity,
world context, qualification, and original provenance.

No field represents `primary_source`, `first_source`, `primary_device`, or
`primary_measurement_identity`.

### 9. Analysis scope

The registered scope enum is:

- `SAME_SESSION` — all selected entries identify exactly one session;
- `WITHIN_SEASON` — all selected entries identify exactly one season, with
  multiple sessions allowed;
- `CROSS_SEASON` — at least two explicit seasons are selected.

Cross-session selection is not globally invalid: it is required by the
within-season and cross-season longitudinal cases. Selection fails only when it
violates the declared scope.

### 10. Complete provenance graph

`MultiSourceProvenanceGraph` is an additive, typed, canonical DAG. It includes
stable node IDs, node kinds, canonical content fingerprints, directed typed
edges, deterministic node/edge ordering, a graph hash, and a graph ID. It is
not a generic persistence or graph framework.

The node vocabulary covers source artifacts, acquisitions, source processing
runs, source observations, football-world contexts, source qualification
bindings, longitudinal entries, analysis input, the new multi-source
processing run, the derived result, and registry references needed by existing
`SUPPORTED_BY` edges.

For every selected observation, the graph unions the actual public
`Provenance` arrays and every recorded source lineage edge. Shared nodes are
deduplicated only by stable node ID plus equal canonical hash. Equal-looking
filenames, vendors, dates, or values do not collapse different IDs.

### 11. Graph validation

Construction and result validation require:

- every endpoint exists and no self-edge exists;
- node IDs and edge triples are unambiguous;
- the graph is acyclic;
- every selected observation, artifact, acquisition, and source processing run
  is represented;
- every listed source dependency reaches its selected observation through the
  recorded source lineage;
- every selected observation reaches the analysis input and the final output;
- the new processing run has exactly one produced output;
- no extra or cross-athlete node is present; and
- node hashes, graph hash/ID, and all expected edge content match recomputation.

Missing source dependencies, endpoint omissions, cycles, hash conflicts,
source-observation omission, or unrelated injected nodes fail closed.

### 12. Processing and reprocessing identity

`MultiSourceProcessingRun` is separate from historical `ProcessingRun`. Its
processing ID is derived from input ID/hash, explicit source observation IDs,
registered operation, immutable parameters, and software version. Its output
entity ID is derived from that processing identity. Changing any material
method component creates a new processing/output identity; an earlier result
is never overwritten.

The only RES-62 implemented operation is
`RES62_MULTI_SOURCE_MANIFEST`, a structural manifest operation. The processing
contract is shaped for future registered operations, but no future operation
is implicitly authorized by this record.

### 13. Structural result and no first-source inheritance

`LongitudinalSourceManifestResult` has its own derived-result identity. It
contains selected observation IDs, selected entry hashes, source count,
manifest hash, the new processing run, and the complete graph. It inherits no
measurement identity, device, artifact, session, unit, or result identity from
any selected source. Reversing `[A, B, C]` to `[C, B, A]` produces the same
input, processing, output, manifest, and graph identities.

The result contains no mean, SD, CV, z-score, trend, slope, EWMA, ACWR,
fatigue, readiness, risk, reliability, uncertainty statistic, or other
performance calculation.

### 14. Missingness

RES-62 has no imputation authority. Absence remains absence. A missing CMJ/test
week does not produce zero, `None`-valued fake observations, carry-forward,
interpolation, or a synthetic replacement. A source-declared missingness marker
may remain part of the source observation metadata, but RES-62 does not invent
one.

### 15. Existing CMJ migration

The migration path is wrapping/composition:

```text
existing ScientificMeasurementObservation
        + new FootballWorldContext
        + explicit SourceArtifactQualificationBinding[]
        ↓
LongitudinalObservationEntry
```

The CMJ observation's `MeasurementIdentity`, `MeasurementResult`, existing
`Provenance`, and canonical hashes are reused as-is. No CMJ result is
recomputed and no CMJ wire type is rewritten.

### 16. V3 serialization

All public RES-62 dataclasses are registered with the existing serializer.
Round-trip tests cover canonical JSON and hashes for bindings, entries,
records, inputs, runs, graph nodes/edges/graphs, and the structural result.
Semantic V3 tamper tests mutate derived IDs, selected content, ordering, scope,
processing metadata, source nodes/edges, graph hash, and manifest fields; all
inconsistent payloads fail during decode/construction.

`SERIALIZATION_VERSION` remains `3`; no serializer modification is required.

### 17. RES-63 and RES-69 boundaries

RES-62 does not download, ingest, map, or qualify a public dataset at row level.
Source adapters, mappings, and dataset qualification remain RES-63.

RES-62 owns immutable longitudinal data composition and complete lineage.
RES-69 owns longitudinal statistical authority and any numerical result envelope
for baselines, change, reliability, error, uncertainty, or other analysis.
Future results may reuse the RES-62 input and graph contracts, but their
operation-specific numerical validity must be implemented and registered by
the downstream deterministic scientific engine.

## Migration diagram

```text
CURRENT:

ScientificMeasurementObservation
    +
Provenance

RES-61:

ScientificMeasurementObservation
    +
FootballWorldContext

RES-62:

LongitudinalObservationEntry[
    ScientificMeasurementObservation,
    FootballWorldContext,
    SourceArtifactQualificationBinding[]
]
    ↓
LongitudinalAthletePerformanceRecord
    ↓
MultiSourceAnalysisInput
    ↓
MultiSourceProcessingRun
    ↓
StructuralDerivedResult
    ↓
MultiSourceProvenanceGraph
```

Existing leaf authorities remain unchanged.

## Synthetic qualification fixture

The focused RES-62 test module contains one deterministic, clearly tagged
`SYNTHETIC RES-62` fixture covering ten weeks for one de-identified synthetic
first-team athlete. It includes repeated training, match, and testing
sessions; multiple devices/providers and measurement identities; multiple
artifacts/acquisitions/source processing runs; a same-session multi-device
case; an intentionally absent expected testing week; and an explicit unknown
exposure state. The fixture is structural test data, not empirical football
evidence, and never receives a passing canonical source decision.

Separate tests cover two seasons, same-date different sessions, distinct
same-session identities, duplicate-looking values, qualification failures,
graph corruption, reprocessing, source-order attacks, missingness, migration,
and historical hash/wire compatibility.

## Realization

- Registered identities: `src/dynamislm/longitudinal/registry.py`
- Immutable contracts: `src/dynamislm/longitudinal/models.py`
- Deterministic builders: `src/dynamislm/longitudinal/record.py`
- Complete lineage union/validation:
  `src/dynamislm/longitudinal/lineage.py`
- Public validators: `src/dynamislm/longitudinal/validation.py`
- Public API: `src/dynamislm/longitudinal/__init__.py` and
  `src/dynamislm/__init__.py`
- Focused qualification: `tests/test_longitudinal.py`

No scientific numerical authority changed.
