# RES35-DR-003

DECISION_ID=RES35-DR-003
STATUS=PARTIALLY_SUPERSEDED
CORRECTION=RES44-DR-001 supersedes only the RES-35 mass identity/derivation branch. The SYSTEM_WEIGHT force, explicit weighing-segment, supported-system, provenance, and BODY_MASS boundary remain adopted. The historical generic SYSTEM_MASS text below is retained for decision history and is not a current implementation contract.
QUESTION=What explicit gravity contract is required to derive system mass from system weight, and how must the result remain distinct from body mass?
SCOPE=System-mass derivation from an authorized `SYSTEM_WEIGHT`; no body-mass estimator or external-load subtraction.
SOURCES=
- `docs/architecture/SCIENTIFIC_CONSTITUTION_V1.md`
- `docs/architecture/MEASUREMENT_DATA_PROVENANCE_V1.md`
- `docs/architecture/REASONING_CLAIMS_EVALUATION_V1.md`
- `docs/architecture/P1_EXECUTION_CONTRACT.md`
- [BIPM SI Brochure, 9th edition](https://www.bipm.org/documents/d/guest/si-brochure-9-pdf)
- [NIST Guide to the SI, Chapter 8](https://www.nist.gov/pml/special-publication-811/nist-guide-si-chapter-8)
- [NIST Guide to the SI, Appendix B.9](https://www.nist.gov/pml/special-publication-811/nist-guide-si-appendix-b-conversion-factors/nist-guide-si-appendix-b9)
- [NIST, SI Units — Mass](https://www.nist.gov/pml/owm/si-units-mass)
APPLICABILITY=BIPM and NIST establish kilogram as mass, newton as force, and the conventional standard acceleration `g_n = 9.80665 m/s^2`, while distinguishing local gravitational acceleration from the conventional reference. The CMJ result is a supported-system quantity under the supplied protocol, not automatically an athlete-only body quantity.
OPTIONS_CONSIDERED=
- Hard-code `9.81` or silently use `9.80665`: rejected because a mass result must retain the gravity reference/value and standard versus local semantics.
- Always require a supplied local gravity value: rejected as unnecessarily restrictive for a documented standard-reference derivation.
- Always use standard gravity: rejected because local gravity is a valid explicit reference and can differ by location.
- Explicit `GravityReference` with either conventional standard gravity or a supplied local gravitational acceleration: adopted.
DECISION=Register `CMJ_SYSTEM_MASS_FROM_WEIGHT` version `1.0.0`. `GravityReference` stores a finite positive value in `m/s^2`, `reference_type` (`STANDARD_GRAVITY` or `LOCAL_GRAVITATIONAL_ACCELERATION`), a source/reference, and explicit uncertainty/status metadata. The registered standard object is explicitly `g_n = 9.80665 m/s^2`; it is not a function default. A caller may instead supply a local value with its source and status. Derive `SYSTEM_MASS` only from a valid registered `SYSTEM_WEIGHT` in `N` using `m_system = W_system / g_reference`, and report in the registered kilogram mass unit. If gravity is absent or invalid, return a structured refusal while preserving the valid system-weight observation.
IDENTITY=System mass is a separate measurement identity with its own registered operation, kilogram unit, gravity parameters, source system-weight lineage, and `ValueOrigin.DERIVED_MECHANICAL_QUANTITY` with `scientific_roles=()`. Standard and local gravity references remain distinct in serialized parameters and claim-relative comparability.
BODY_MASS_BOUNDARY=Do not emit `BODY_MASS`. A loaded CMJ or any trial with supported external load can include athlete plus load and other supported mass. Even an unloaded protocol requires a separately authorized body-mass equivalence method and prerequisites. No external-load value is subtracted in RES-35. A body-mass request returns `BODY_MASS_CLAIM_UNSUPPORTED` / `COMPUTATION_NOT_REGISTERED` while the system mass remains safely describable.
RATIONALE=The force platform observes support force, and division by an explicit gravitational acceleration produces a mass estimate for the supported system under the registered reference. Recording the gravity contract prevents a conventional reference from masquerading as a local measurement and prevents force/mass/body-mass collapse.
ASSUMPTIONS=The system-weight operation's force identity and provenance are valid; gravitational acceleration is treated as a supplied/reference input; no uncertainty propagation or buoyancy correction is registered in P1C.
LIMITATIONS=The initial result carries uncertainty status but does not propagate force or gravity uncertainty. Local-gravity estimation, calibration, buoyancy, body-mass equivalence, loaded/unloaded adjudication, and performance interpretation are deferred.
REGISTRY_OBJECTS_AFFECTED=`CMJ_SYSTEM_MASS_FROM_WEIGHT`; `GravityReference`; `STANDARD_GRAVITY`; `LOCAL_GRAVITATIONAL_ACCELERATION`; `KILOGRAM`; `SYSTEM_MASS` measurand/metric; gravity comparability dimensions; body-mass refusal reason.
IMPLEMENTATION=`src/dynamislm/measurement/cmj/weighing.py`; `src/dynamislm/measurement/cmj/registry.py`; `src/dynamislm/refusal/models.py`.
TESTS=`tests/test_cmj.py`: missing-gravity refusal with preserved weight, explicit standard/local distinction, `W/g` oracle, gravity serialization, no `9.81` default, derived classification/roles, loaded-protocol body-mass refusal, and comparability differences.
VERSION=RES35-P1C-1.0.0
