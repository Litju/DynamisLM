# RES-60-DR-001 — Canonical population and source authority

## Status

`ADOPTED`

`RES-60`

`CONSTITUTION_VERSION=2.0.0`

## Scientific question

What typed, deterministic, provenance-aware contract establishes that a
population and a source qualify as canonical empirical DynamisLM V2 target
data, while preserving the distinction between population matching, source
eligibility, evidence applicability, and license/reuse permission?

## Authority inspected

- `docs/architecture/SCIENTIFIC_CONSTITUTION_V2.md` — sealed V2 target
  population, evidence hierarchy, refusal architecture, and RES-60 sequence.
- `docs/architecture/MEASUREMENT_DATA_PROVENANCE_V1.md` — immutable
  observation/provenance and source-to-result requirements.
- `docs/architecture/P1_EXECUTION_CONTRACT.md` — registered deterministic
  authority and decision-record workflow.
- Existing V3 contracts in `src/dynamislm/measurement/`,
  `src/dynamislm/evidence/`, `src/dynamislm/refusal/`,
  `src/dynamislm/provenance/`, and `src/dynamislm/serialization.py`.
- Existing tests, including the RES-49 historical CMJ serialization hashes.

The sealed V2 Constitution already resolves the six target clauses. No
project-wide literature search or football-norm threshold is required for this
implementation unit.

## Decision

### 1. Population identity

The V2 population identity is an immutable typed dataclass with these six
material dimensions:

```text
SEX = MALE
AGE_CLASS = SENIOR
SPORT = ASSOCIATION_FOOTBALL
PROFESSIONAL_STATUS = PROFESSIONAL
SQUAD_LEVEL = FIRST_TEAM
COMPETITION_TIER = TOP_DOMESTIC_DIVISION
```

`CompetitionIdentity` and `SeasonIdentity` are represented as stable typed
references using existing `ScientificIdentifier` primitives. RES-60 does not
define the RES-61 football-world ontology.

### 2. Evidence-backed resolution

Each material dimension is evaluated through one or more immutable
`PopulationEvidenceBinding` values. A binding records the dimension, the
typed-domain value, an evidence reference, and whether the evidence is
established, missing, unresolved, or conflicting. A typed caller assertion is
not evidence. A canonical population `PASS` requires an established binding
for every clause.

Unknown values and missing bindings remain unresolved. Conflicting bindings
remain unresolved. No language-model or free-text field can upgrade a clause.

### 3. Deterministic population semantics

`qualify_canonical_population` is the registered deterministic authority.
Every clause is returned as `PASS`, `FAIL`, or `UNRESOLVED`.

```text
any FAIL        -> NONCANONICAL
no FAIL + any UNRESOLVED -> UNRESOLVED
all PASS        -> PASS
```

The result retains all clause decisions, failed and unresolved dimensions,
missing information, supporting evidence, reason codes, and the registered
method identity. No boolean-only result is exposed as the authority.

### 4. Population versus source eligibility

Population matching is necessary but insufficient. The distinct
`CanonicalSource`/`qualify_canonical_source` contract also requires:

1. the exact population decision to pass;
2. actual observed/measured data origin;
3. a clean whole target cohort or an explicitly separated target subgroup;
4. adequate stable source identity and revision; and
5. observed athlete/trial-level granularity.

Source status is separate from population status. A source with a population
failure is not silently reclassified as indirect evidence.

### 5. Mixed cohorts and subgroup separability

A whole cohort may qualify only when its scope is explicitly an exact target
cohort. A mixed parent cohort may qualify only when the evaluated subgroup has
its own target population identity, subgroup and parent identities, extraction
evidence, and extraction provenance. A mixed cohort that is not separable is a
canonical eligibility failure. Unknown separability or missing extraction
provenance is unresolved/quarantined.

Row extraction is deferred to RES-63; RES-60 defines only the authority
contract and provenance requirements.

### 6. Actual observed versus synthetic origin

Only `ACTUAL_OBSERVED_MEASURED` data can satisfy the canonical empirical
source requirement. `SYNTHETIC`, `SIMULATED`, and `LITERATURE_ONLY` sources
cannot become canonical observed data even when their typed population fields
match. Unknown origin is unresolved.

### 7. Evidence classes and claim-relative applicability

The V2 hierarchy is represented explicitly as:

```text
CANONICAL_EMPIRICAL_TARGET
DIRECT_TARGET_POPULATION_EVIDENCE
INDIRECT_MEASUREMENT_EVIDENCE
NONCANONICAL_CONTEXT_ONLY
REJECTED_OR_UNRESOLVED
```

`V2EvidenceApplicability` records a claim, explicit applicability decision,
scientific role, and evidence class. It is not derived from a failed canonical
gate. In particular, a non-target source becomes
`INDIRECT_MEASUREMENT_EVIDENCE` only when a separate explicit applicability
record says so for a measurement/method claim.

The existing `EvidenceApplicability.population_scope: str` remains a V1/V3
historical/descriptive wire field. It is not consulted by the V2 canonical
source gate and its serialized shape is unchanged.

### 8. License and reuse

`LicenseReuseMetadata` is stored on the source and copied into the source
decision, but it is not a scientific population/source eligibility clause.
Restrictive, conditional, prohibited, or unknown reuse status can coexist
with scientific canonical eligibility. Training or redistribution permission
must be decided separately.

### 9. Refusal taxonomy

The existing refusal taxonomy is extended additively with
`POPULATION_SCOPE_UNRESOLVED` and `CANONICAL_ELIGIBILITY_FAILED`, plus
dimension-specific, subgroup, evidence, origin, and granularity reason codes.
Historical enum values are unchanged. These reason codes are used by the
typed decision output; independent observations remain describable.

### 10. Serialization and compatibility

All RES-60 dataclasses are registered with the existing strict V3 canonical
serializer. New dataclasses do not change `SERIALIZATION_VERSION`. Tuple
fields remain immutable; constructor validation rejects invalid enum/domain
values and empty required fields; canonical serialization rejects non-finite
values through the existing serializer. New decision IDs are deterministic
hash-derived identifiers.

`ObservationContext.population_context: str` remains historical/descriptive
context. It is not authoritative for V2 canonical eligibility. Existing
observation and evidence dataclass wire shapes are unchanged. The existing
CMJ/V1 historical hash assertions remain the regression authority.

## Alternatives rejected

- Replacing existing free-text observation/evidence fields: rejected because
  it would mutate historical V3 wire shapes without a migration requirement.
- Treating `elite`, `professional`, club affiliation, or caller metadata as
  sufficient: rejected by the V2 unresolved-population policy.
- Marking every failed population source as indirect evidence: rejected because
  indirect applicability is claim-relative and method-specific.
- Blocking canonical science on license status: rejected because scientific
  eligibility and reuse permission are separate axes.
- Implementing team, competition, season, ingestion, or row-extraction
  ontology here: deferred to RES-61 through RES-63.

## Limitations and deferred work

- RES-60 does not implement the full football-world ontology, teams, matches,
  seasons beyond stable references, ingestion, or row-level extraction.
- The gate does not decide whether a source is useful indirect evidence; it
  only provides the typed contract for an explicit claim-relative decision.
- No football norms, thresholds, reliability, longitudinal composition, or
  training authorization is introduced.

## Realization

- Registry: `src/dynamislm/population/registry.py`
- Typed contracts: `src/dynamislm/population/models.py`
- Deterministic authority: `src/dynamislm/population/qualification.py`
- Focused tests: `tests/test_population.py`
