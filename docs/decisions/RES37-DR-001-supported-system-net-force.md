# RES37-DR-001

DECISION_ID=RES37-DR-001
STATUS=ADOPTED
QUESTION=What force quantity is authoritative for the first CMJ mechanics layer, and what external-force model does it represent?
SCOPE=RES-37 net vertical force and all mechanics results that consume it.

SOURCES=
- `docs/architecture/SCIENTIFIC_CONSTITUTION_V1.md`
- `docs/architecture/MEASUREMENT_DATA_PROVENANCE_V1.md`
- `docs/architecture/P1_EXECUTION_CONTRACT.md`
- `docs/decisions/RES35-DR-001-weighing-segment-and-system-weight.md`
- `docs/decisions/RES35-DR-002-total-supported-force-construction.md`
- `docs/decisions/RES44-DR-001-system-mass-and-standard-gravity-equivalent.md`
- `docs/decisions/RES45-DR-003-processing-output-entity-contract.md`
- [McMahon, Lake & Comfort, 2022, force-platform CMJ processing](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0265999)
- [Guess et al., 2020, CMJ force-time processing](https://pmc.ncbi.nlm.nih.gov/articles/PMC7761544/)

APPLICABILITY=Only a valid RES-35 total supported vertical-force observation in canonical N, with an exact compatible RES-35 SYSTEM_WEIGHT observation and an explicit RES-37 mechanics system contract.

OPTIONS_CONSIDERED=
- subtract a default athlete body weight: rejected because RES-35 SYSTEM_WEIGHT is a supported-system force and no body-mass alias is authorized;
- subtract a numerically similar weight from another trial: rejected because source identity and system compatibility are material;
- treat contact loss as the end of net force: rejected because Fz approximately zero and F_net,z approximately -W remain meaningful under the registered model;
- authorize a force-platform-plus-gravity model only when its system boundary and force completeness are explicit: adopted.

DECISION=The mechanics object is the SUPPORTED PHYSICAL SYSTEM. `Fz(t)` is the qualified total supported vertical force. The registered net-force operation computes `F_net,z(t) = Fz(t) - W_system` sample by sample. `W_system` is the exact compatible RES-35 SYSTEM_WEIGHT force in N. The external-force model is limited to force-platform vertical support plus gravity acting on the supported system, with no other material unmodeled vertical external force and stable system composition. A loaded supported system therefore produces combined supported-system mechanics, never an implicit athlete-only COM result.

EQUATIONS=
- `F_net,z(t_i) = Fz(t_i) - W_system`;
- `Fz` and `W_system` are both upward-positive vertical forces in N;
- no mass is required for this force subtraction.

INPUTS=Qualified `TotalSupportedForceResult`; exact `SystemWeightResult`; `CMJMechanicalSystemContract`; validated source provenance, protocol, system identity, timebase, unit, axis, frame, and sign.

ASSUMPTIONS=The total-force construction already passed RES-35 bilateral or single/precombined validation. The supplied weight is representative of the same supported system and compatible protocol. A free-form external-loading attribute does not establish force completeness by itself; the explicit mechanics contract is required.

INITIAL_CONDITIONS=None for net force.

BOUNDARY_SEMANTICS=The net-force series retains the complete qualified source sample support, including samples after contact loss. No contact-loss truncation is implicit.

NUMERICAL_METHOD=Elementwise finite subtraction; no filtering, resampling, interpolation, unit conversion, or source mutation.

UNITS=Input and output force N; no performance role; `ValueOrigin.DERIVED_MECHANICAL_QUANTITY` with `scientific_roles=()`.

FRAME_SIGN=Registered source vertical axis and reference frame; positive direction is upward.

LIMITATIONS=No athlete-COM equivalence, body-mass inference, jump height, phase impulse, power, RFD, local-gravity estimation, filtering, or drift correction.

REGISTRY_OBJECTS_AFFECTED=`CMJ_NET_VERTICAL_FORCE_OPERATION`, `CMJ_NET_VERTICAL_FORCE_SCHEMA`, `CMJ_NET_VERTICAL_FORCE_MEASURAND`, `CMJ_NET_VERTICAL_FORCE_METRIC`, `CMJ_MECHANICS_SYSTEM_CONTRACT`, `CMJ_FORCE_PLATFORM_PLUS_GRAVITY_EXTERNAL_FORCE_MODEL`.

IMPLEMENTATION=`src/dynamislm/measurement/cmj/mechanics.py`; full DAG uses `ProcessingRun.output_entity_id` and an immutable derived mechanics artifact.

TESTS=Compatible and mismatched weight/source tests; exact subtraction; source immutability; no-mass net-force path; bilateral non-double-sum; post-contact-loss force; loaded-system and unresolved-external-force refusal; provenance and v3 roundtrip.

VERSION=RES37-P1E-1.0.0
