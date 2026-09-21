# RES-71 registered-operation inventory

The authoritative inventory is the immutable tuple returned by
`dynamislm.qualification.build_registered_operation_inventory()`.
`validate_registered_operation_inventory()` discovers every
`RegistryReference` whose object type is `registered-operation` and requires an
exact set match. A newly exposed operation therefore fails qualification until
its contract is reviewed.

Each row contains:

```text
operation_id
label
method_version
scientific_family
disposition
implementation
input_contract
output_contract
provenance_contract
refusal_path
test_coverage
authority_references
tolerance_contract
```

## Inventory totals

| Family | Registered identities | Implemented | Historical replay | Represented only | Deferred | Rejected |
|---|---:|---:|---:|---:|---:|---:|
| Population/source | 2 | 2 | 0 | 0 | 0 | 0 |
| Football context | 1 | 1 | 0 | 0 | 0 | 0 |
| Ingestion/record | 3 | 3 | 0 | 0 | 0 | 0 |
| External load | 3 | 3 | 0 | 0 | 0 | 0 |
| CMJ | 25 | 24 | 1 | 0 | 0 | 0 |
| Strength/IMTP/VBT | 14 | 12 | 0 | 1 | 1 | 0 |
| Field testing | 14 | 12 | 0 | 1 | 1 | 0 |
| DJ/BPT/MBT | 10 | 9 | 0 | 1 | 0 | 0 |
| Longitudinal statistics | 27 | 14 | 0 | 4 | 6 | 3 |
| Cross-source bridge | 1 | 1 | 0 | 0 | 0 | 0 |
| **Total** | **100** | **81** | **1** | **7** | **8** | **3** |

The count is a qualification assertion, not a replacement for the exact set
comparison. The machine-readable entries carry the implementation symbol,
input/output/provenance contract, refusal route, authority documents and test
paths for each identity.

## Authority mapping by family

| Family | Primary implementation surface | Authority | Test evidence |
|---|---|---|---|
| Population/source | `dynamislm.population`, `dynamislm.ingestion` | RES-59/60/63 | `test_population.py`, `test_ingestion.py`, `test_res63_operational_authority.py` |
| Football context | `dynamislm.football`, `dynamislm.longitudinal` | RES-61/62 | `test_football.py`, `test_longitudinal.py` |
| External load | `dynamislm.external_load` | RES-64 | `test_external_load.py` |
| CMJ | `dynamislm.measurement.cmj` | RES-34–50/65 | CMJ test family and RES-71 gold/refusal cases |
| Strength | `dynamislm.measurement.strength` | RES-66 | `test_strength.py` |
| Field testing | `dynamislm.measurement.field_testing` | RES-67 | `test_field_testing.py` |
| DJ/BPT/MBT | family-specific RES-68 packages | RES-68 | `test_explosive_test_families.py` |
| Longitudinal statistics | `dynamislm.longitudinal.statistics` | RES-69 | `test_longitudinal_statistics.py` |
| Comparability | `dynamislm.comparability` | RES-70 | RES-70 comparability/bridge/adversarial tests |

## Completeness rule

Implemented entries must resolve to an importable implementation symbol and
have test paths in the repository. Historical replay entries resolve to the
historical method identity and cannot mint the current result. Every other
disposition has an explicit refusal/representation path. Caller-supplied
formulas, thresholds, operation identities and comparability overrides are not
accepted by this inventory.
