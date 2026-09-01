<!-- Curated from the sealed Linear document: https://linear.app/alignerr-cmj/document/dynamislm-p1-vertical-slice-execution-contract-a8a5ae922d79 -->

## Status

`P1=AUTHORIZED`

P1 builds the actual measurement ontology and scientific registries iteratively. It does not attempt to solve the entire twelve-family ontology upfront.

## P1 objective

Create the machine-readable scientific primitives and registries required to represent, compute, compare, interpret and refuse claims about DynamisLM measurements without violating the sealed P0 contracts.

## What P1 may define

For each vertical scientific unit, P1 may introduce:

```text
TestEntity
Protocol
Device / MeasuringSystem
RawSignal / Artifact
Event
Phase
Measurand
Estimator
Metric
Equation / RegisteredOperation
Unit
Normalization
ProcessingMethod
ComparabilityRule
EvidenceReference
ProvenanceRule
AnalysisOperation
RefusalCondition
```

P1 may also define generic schema/runtime primitives needed to support these entities.

## What P1 must not reopen routinely

```text
PROJECT_THESIS
TARGET_POPULATION
FIXED_12_TEST_FAMILIES
THREE_SCOPE_MODEL
LLM_AUTHORITY_BOUNDARY
PYTHON_AUTHORITY_BOUNDARY
PROVENANCE_REQUIREMENT
WITHIN_VS_BETWEEN_PRINCIPLE
CAUSAL_DISCIPLINE
PULL_BASED_RESEARCH_MODEL
```

A new metric definition, device variant or protocol disagreement normally becomes a new scientific identity, method, evidence rule or comparability rule. It does not reopen P0.

## Vertical-slice lifecycle

```text
ONE CONCRETE SCIENTIFIC UNIT
        ↓
SCIENTIFIC QUESTION
        ↓
DO WE ALREADY HAVE SUFFICIENT AUTHORITY?
   ├── YES → define/register
   └── NO  → targeted evidence search
                  ↓
             explicit decision record
                  ↓
IDENTITY DEFINED
        ↓
METHOD / OPERATION REGISTERED
        ↓
DETERMINISTIC IMPLEMENTATION
        ↓
VALIDATION + TESTS
        ↓
EVAL / ADVERSARIAL CASES
        ↓
PROVENANCE PRESERVED
        ↓
COMPARABILITY / REFUSAL EXPLICIT
        ↓
SEAL UNIT
        ↓
NEXT UNIT
```

## Evidence decision record

Every scientific implementation decision should record at minimum:

* exact scientific question;
* sources inspected;
* population/method applicability;
* decision adopted;
* materially relevant alternatives;
* assumptions;
* evidence limitations;
* method/registry version;
* deterministic implementation/tests that realize the decision.

Research is pull-based. Do not perform unrelated literature searches because a family may need them eventually.

## Meta-analysis policy

A quantitative synthesis is started only when a concrete implementation/claim decision requires it and:

* study-level data are reproducibly extractable;
* estimands are compatible;
* methods/populations/outcomes can be interpreted together;
* dependent effects are handled correctly.

Workflow:

```text
LITERATURE SEARCH
→ STRUCTURED EXTRACTION
→ AUDIT
→ DETERMINISTIC PYTHON META-ANALYSIS
→ DECISION RECORD
→ IMPLEMENTATION
```

The LM may assist discovery/extraction. It does not invent pooled estimates.

## P1 generic foundation gate

Before a test-specific family can scale, establish minimal reusable primitives for:

* immutable scientific identifiers;
* versioned registry objects;
* units and normalization representation;
* method/algorithm versioning;
* evidence references/decision records;
* observation/result separation;
* provenance/lineage edges;
* comparability states;
* refusal classes/reason codes;
* deterministic serialization/hash behavior;
* validation/error types.

Do not build a giant speculative superclass hierarchy. Add only primitives required by the first vertical slice and clearly reusable across the sealed architecture.

## First executable unit

The immediate implementation unit is **repository + scientific-kernel bootstrap**, not a twelve-family ontology dump.

Required outcome:

* Ubuntu/Linux-native repository initialized;
* Python package and dependency/QA foundation;
* sealed P0 architecture docs represented in-repo;
* generic scientific identity/result/provenance primitives sufficient to support the first measurement slice;
* comparability/refusal enums/contracts represented without test-specific assumptions;
* tests prove serialization, version identity, immutability/lineage invariants and authority separation;
* no model training, corpus ingestion, GPU rental or UI.

## First measurement-family slice

After the kernel bootstrap is sealed, the recommended first scientific slice is **CMJ**, because it exercises raw force signals, event/phase identity, deterministic integration, derived quantities, multiple estimators, method provenance and comparability. The project owner may change the first family without reopening P0.

## P1 acceptance philosophy

P1 is complete only when the scientific representation works across the required domain without collapsing same-label/different-definition measurements and without moving numerical authority into the LM.

Completion of one family is not required before useful generic primitives are sealed, but completed scientific units must be independently testable and evidence-backed before they become authority for downstream data/evaluation work.
