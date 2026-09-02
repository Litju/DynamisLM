# RES37-DR-003

DECISION_ID=RES37-DR-003
STATUS=ADOPTED
QUESTION=When may RES-37 convert net force into physical supported-system COM acceleration?
SCOPE=The primary physical acceleration path only; it does not register a conventional standard-g acceleration path.

SOURCES=
- `docs/decisions/RES44-DR-001-system-mass-and-standard-gravity-equivalent.md`
- `docs/decisions/RES45-DR-004-standard-gravity-exact-reference-status.md`
- [McMahon, Lake & Comfort, 2022, force-platform CMJ processing](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0265999)
- [Linthorne, 2001, force-platform impulse-momentum analysis](https://bura.brunel.ac.uk/handle/2438/1392)

APPLICABILITY=An exact compatible `PhysicalSystemMassResult` from RES-44, whose source SYSTEM_WEIGHT observation is the same observation used by the RES-37 net-force chain, and a resolved mechanics system contract.

OPTIONS_CONSIDERED=
- divide by any kg-valued result: rejected because the standard-gravity equivalent is a distinct conventional measurand;
- divide by standard gravity when local gravity is absent: rejected by RES-44;
- divide net force by exact physical system mass from applicable local gravity: adopted;
- register a separate standard-g normalized acceleration path in RES-37: deferred because the physical-local path is the only V1 authority and no downstream claim needs the conventional path.

DECISION=Register `a_z(t)=F_net,z(t)/m_system` as `SUPPORTED_SYSTEM_COM_VERTICAL_ACCELERATION`. Require `PhysicalSystemMassResult`, kg, exact source SYSTEM_WEIGHT observation linkage, compatible supported-system identity, N net force, upward-positive vertical frame, and explicit timebase. `StandardGravityMassEquivalentResult` is rejected with a structured refusal and can never satisfy this method by numeric equality or unit equality. `STANDARD_GRAVITY_MECHANICS_PATH=DEFERRED`.

EQUATIONS=`a_z(t_i) = F_net,z(t_i) / m_system`.

INPUTS=Valid RES-37 net force; valid RES-44 physical system mass; exact source-weight identity; resolved mechanics system contract.

ASSUMPTIONS=The local gravity reference in RES-44 is applicable to the same supported system and protocol. The mass quotient and force division are deterministic; uncertainty is not propagated.

INITIAL_CONDITIONS=None for acceleration.

BOUNDARY_SEMANTICS=Acceleration retains the complete net-force sample support and does not add or remove event samples.

NUMERICAL_METHOD=Elementwise division only; no hidden gravity conversion, unit conversion, filtering, interpolation, or drift operation.

UNITS=Input N and kg; output m/s².

FRAME_SIGN=Registered source vertical axis and frame; upward positive; supported-system boundary, not automatic athlete COM.

LIMITATIONS=No local-gravity estimation, body-mass inference, athlete-COM relabeling, standard-g acceleration alias, uncertainty propagation, or endpoint correction.

REGISTRY_OBJECTS_AFFECTED=`CMJ_SUPPORTED_SYSTEM_COM_ACCELERATION_OPERATION` and its measurand/metric; `CMJ_MECHANICS_COMPARABILITY_RULE`; RES-44 physical and standard mass identities remain distinct.

IMPLEMENTATION=`src/dynamislm/measurement/cmj/mechanics.py`; mass and net-force provenance are merged without replacing upstream observations.

TESTS=Missing physical mass; standard-gravity-equivalent adversarial input; same-value wrong-source mass; exact compatible mass; exact acceleration; impulse/mass equals velocity change; loaded system; provenance and refusal preservation.

VERSION=RES37-P1E-1.0.0
