# RES34-DR-003

DECISION_ID=RES34-DR-003
STATUS=ADOPTED
QUESTION=What acquisition-level comparability and refusal outcome is authorized when CMJ identities differ or material metadata are unresolved?
SCOPE=Claim-relative comparison of CMJ acquisition identities and protection of downstream computation authority.
SOURCES=
- `docs/architecture/MEASUREMENT_DATA_PROVENANCE_V1.md`
- `docs/architecture/REASONING_CLAIMS_EVALUATION_V1.md`
- `docs/architecture/P1_EXECUTION_CONTRACT.md`
- [VIM 2.46 metrological comparability](https://jcgm.bipm.org/vim/en/2.46.html)
- [VIM 2.47 metrological compatibility](https://jcgm.bipm.org/vim/en/2.47.html)
- [VIM 2.41 metrological traceability](https://jcgm.bipm.org/vim/en/2.41.html)
APPLICABILITY=Acquisition identity claims in P1B; VIM defines general comparability/traceability concepts, while the project authority defines the six allowed outcome states and claim-specific refusal architecture.
DECISION=Use a typed claim-bearing `CMJComparabilityRequest` and one deterministic P1B rule. Missing protocol/device/measuring-system/channel/axis/frame/unit/sign/timebase/software or unresolved processing/calibration/zeroing state yields `INSUFFICIENT_INFORMATION`. Known material differences yield `BRIDGE_VALIDATION_REQUIRED` with explicit dimension reasons; no cross-device, protocol, arrangement, unit, sign, frame or processing equivalence is inferred. Identical resolved acquisition identity yields `COMPARABLE`; an explicitly requested transformation remains a request and is never executed or treated as a verdict. Map acquisition failures to existing refusal classes and preserve independent observation descriptions. Requests for body/system mass, movement onset, impulse and jump height always return `COMPUTATION_NOT_REGISTERED`.
ALTERNATIVES_CONSIDERED=
- Different identity means automatically not comparable: rejected because a validated bridge may establish claim-relative comparability later.
- Unit conversion implies method harmonization: rejected because conversion is not a device/method bridge.
- Refuse the observations themselves: rejected because refusal blocks the claim, not independently valid source observations.
- Implement a downstream calculation opportunistically: rejected because Python authority requires an explicit registered operation and this unit registers none.
ASSUMPTIONS=The absence of a registered bridge is a resolvable scientific state, not proof of physical non-equivalence. P1B comparison is acquisition-level and does not assess biological jump quality.
LIMITATIONS=No device bridge, protocol bridge, unit-conversion operation, measurement-error model, event detector, or mechanics operation is registered.
REGISTRY_OBJECTS_AFFECTED=`CMJComparabilityRequest`; `CMJ_ACQUISITION_COMPARABILITY_RULE`; acquisition comparability reason codes; CMJ refusal mapping; `CMJComputation` guard.
IMPLEMENTATION=`src/dynamislm/comparability/models.py`; `src/dynamislm/refusal/models.py`; `src/dynamislm/measurement/cmj/comparability.py`; `src/dynamislm/measurement/cmj/refusal.py`; `src/dynamislm/measurement/cmj/registry.py`.
TESTS=`tests/test_cmj.py`: separate-vs-precombined identity, axis/frame/sign mismatch, no-rule device bridge, blocked comparison with safe descriptions, four downstream computation refusals.
VERSION=RES34-P1B-1.0.0
