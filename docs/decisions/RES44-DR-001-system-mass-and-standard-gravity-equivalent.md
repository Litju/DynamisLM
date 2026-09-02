# RES44-DR-001

DECISION_ID=RES44-DR-001
STATUS=ADOPTED
QUESTION=What scientifically distinct quantities may be derived from a valid CMJ SYSTEM_WEIGHT, and when may a result be called physical system mass?
PROBLEM=RES-35 used one SYSTEM_MASS identity for local support force divided by either supplied local gravity or conventional standard gravity. BIPM, VIM, and NIST distinguish mass, weight/force, local acceleration of free fall, and the conventional standard acceleration g_n. Equal numerical kg units therefore do not establish one measurand.
SOURCES=
- `docs/architecture/SCIENTIFIC_CONSTITUTION_V1.md`
- `docs/architecture/MEASUREMENT_DATA_PROVENANCE_V1.md`
- `docs/architecture/REASONING_CLAIMS_EVALUATION_V1.md`
- `docs/architecture/P1_EXECUTION_CONTRACT.md`
- [BIPM SI Brochure, 9th edition and Declaration on weight](https://www.bipm.org/en/publications/si-brochure/)
- [JCGM/VIM 2.12, conventional quantity value](https://jcgm.bipm.org/vim/en/2.12.html)
- [JCGM/VIM 1.7, quantities of the same kind](https://jcgm.bipm.org/vim/en/1.7.html)
- [NIST SI Units — Mass](https://www.nist.gov/pml/owm/si-units-mass)
- [NIST SP 811, Appendix A — weight](https://nvlpubs.nist.gov/nistpubs/Legacy/SP/nistspecialpublication811e1995.pdf)
- [NIST Technical Note 491 — standard gravity](https://nvlpubs.nist.gov/nistpubs/Legacy/TN/nbstechnicalnote491.pdf)
APPLICABILITY=The decision applies to a RES-35-authorized quiet weighing segment whose SYSTEM_WEIGHT is the local supported-system force in N. The supported system remains the athlete plus supported external load and any other supported mass. It does not authorize local-gravity estimation, calibration correction, buoyancy correction, body-mass inference, or CMJ mechanics.
OPTIONS_CONSIDERED=
- Continue calling both W/g_n and W/g_local SYSTEM_MASS: rejected because the identities differ even when the numerical unit is kg.
- Silently substitute g_n when local gravity is absent: rejected because conventional standard gravity is not automatically the local gravitational acceleration.
- Delete W/g_n: rejected because the conventional/reference quotient can be useful when its identity is explicit.
- Register separate physical-local and standard-gravity-equivalent operations: adopted.
DECISION=Keep SYSTEM_WEIGHT as the supported-system force. Register `CMJ_PHYSICAL_SYSTEM_MASS_FROM_WEIGHT` and `CMJ_STANDARD_GRAVITY_MASS_EQUIVALENT_FROM_WEIGHT` as separate operations with separate measurands and metrics. PHYSICAL_SYSTEM_MASS is W divided by an explicitly supplied applicable `LOCAL_GRAVITATIONAL_ACCELERATION`. STANDARD_GRAVITY_MASS_EQUIVALENT is W divided by the registered exact conventional `STANDARD_GRAVITY`, `g_n = 9.80665 m/s^2`; it is a reference/conventional quotient and must not masquerade as physical mass. Neither result is BODY_MASS.
RATIONALE=BIPM defines weight as a force associated with mass and acceleration due to gravity, while standard weight uses conventional standard acceleration. VIM identifies g_n as a conventional value, and NIST defines scientific/technical weight using the local acceleration of free fall while defining mass as an inertial property. Thus a local support-force observation requires applicable local gravity for the physical-mass interpretation; W/g_n remains a distinct conventional/reference quantity.
MEASURANDS=`SYSTEM_WEIGHT` is a force measurand in N. `PHYSICAL_SYSTEM_MASS` and `STANDARD_GRAVITY_MASS_EQUIVALENT` may both serialize numerically in kg, but they are different measurands and identities. No output automatically represents athlete-only body mass.
GRAVITY_SEMANTICS=`STANDARD_GRAVITY` is the registered conventional exact/reference acceleration and is never treated as `LOCAL_GRAVITATIONAL_ACCELERATION`. Physical mass without an applicable local reference returns `LOCAL_GRAVITY_REQUIRED`; no geographic or geodetic estimate is performed. The standard path requires an explicit registered `STANDARD_GRAVITY` input and has no hidden default.
IDENTITY_EFFECT=Replace the misleading generic system-mass operation, measurand, metric, and result wrapper with distinct RES-44 identities. The operation, output measurand, gravity type/value/unit/source, and source SYSTEM_WEIGHT observation ID are part of the derived identity/procedure record. Both classifications remain `ValueOrigin.DERIVED_MECHANICAL_QUANTITY` with `scientific_roles=()`.
MIGRATION_EFFECT=The pre-RES-44 `CMJ_SYSTEM_MASS_FROM_WEIGHT`, `CMJ_SYSTEM_MASS_MEASURAND`, `CMJ_SYSTEM_MASS_METRIC`, and `SystemMassResult` meanings are not retained as public aliases because they can silently mislabel W/g_n. Existing valid SYSTEM_WEIGHT objects and RES-35 force operations are unchanged. Old mass payloads are not decoded as either new measurand.
SERIALIZATION_EFFECT=Keep serialization version 2. New result wrappers have distinct qualified type markers and distinct registry identities. Strict v2 decoding rejects a payload carrying an old removed mass type marker instead of silently changing its scientific meaning; no wire field is relabeled in place.
PROVENANCE_EFFECT=Each derived result retains the exact source SYSTEM_WEIGHT observation ID, source artifact/acquisition lineage, exact gravity value/unit/type/source, registered operation ID/version, RES-44 software version, and this decision as evidence/support. Standard and local paths therefore remain distinguishable after canonical serialization.
COMPARABILITY_EFFECT=Different physical-mass and standard-gravity-equivalent measurands are `NOT_COMPARABLE` with `MASS_MEASURAND_MISMATCH` (and gravity mismatch when present), not interchangeable because both use kg. Different applicable local-gravity references remain claim-relative and require a registered bridge; no device bridge is introduced.
REFUSAL_EFFECT=Missing local gravity returns `GRAVITY_REFERENCE_MISSING` plus `LOCAL_GRAVITY_REQUIRED` for physical mass. A reference of the wrong type returns `GRAVITY_REFERENCE_MISMATCH`; differing mass measurands map to `MASS_MEASURAND_MISMATCH`. `BODY_MASS_CLAIM_UNSUPPORTED` and `COMPUTATION_NOT_REGISTERED` remain the body-mass boundary. A refusal preserves a valid SYSTEM_WEIGHT and does not invalidate a valid standard-gravity equivalent.
ASSUMPTIONS=The RES-35 SYSTEM_WEIGHT result is already valid under its sealed force/provenance contract. A supplied local gravity is explicitly applicable to the supported system and protocol. The arithmetic is a deterministic quotient only; force/gravity uncertainty propagation is not registered.
LIMITATIONS=No local-gravity estimation, latitude/altitude correction, geodesy, location API, buoyancy correction, body-mass inference, external-load subtraction, net force, impulse, acceleration, COM, jump height, phases, power, RFD, or reliability/error model is authorized.
IMPLEMENTATION=`src/dynamislm/measurement/cmj/registry.py`; `src/dynamislm/measurement/cmj/weighing.py`; `src/dynamislm/measurement/cmj/refusal.py`; `src/dynamislm/refusal/models.py`; `src/dynamislm/comparability/models.py`; `src/dynamislm/measurement/cmj/__init__.py`.
TESTS=`tests/test_cmj.py`: preserved SYSTEM_WEIGHT and RES-35/36 regressions; explicit standard/local semantics; distinct kg identities; local-gravity refusal; independent standard quotient; canonical serialization; exact provenance; claim-relative comparability; BODY_MASS refusal; and no mechanics implementation.
VERSION=RES44-P1C1-1.0.0
