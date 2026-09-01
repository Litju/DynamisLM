# RES34-DR-001

DECISION_ID=RES34-DR-001
STATUS=ADOPTED
QUESTION=What minimum identity must be preserved before a force-platform record is a scientifically explicit CMJ observation?
SCOPE=CMJ family/protocol identity and acquisition identity only; no CMJ mechanics or performance judgment.
SOURCES=
- `docs/architecture/SCIENTIFIC_CONSTITUTION_V1.md`
- `docs/architecture/MEASUREMENT_DATA_PROVENANCE_V1.md`
- `docs/architecture/P1_EXECUTION_CONTRACT.md`
- [VIM 2.3 measurand](https://jcgm.bipm.org/vim/en/2.3.html)
- [VIM 3.2 measuring system](https://jcgm.bipm.org/vim/en/3.2.html)
- [VIM 2.9 measurement result](https://jcgm.bipm.org/vim/en/2.9.html)
APPLICABILITY=The project target population and P1B acquisition layer; VIM supplies general metrology definitions rather than a CMJ protocol or device-equivalence claim.
DECISION=Register one stable `CMJ_TEST_FAMILY` reference and keep `CMJProtocolIdentity` separate and optionally unresolved. Preserve arm-use, external-loading, movement-instruction, start-posture and additional supplied attributes without assigning absent values. Specialize the sealed MeasurementIdentity acquisition block with measuring-system/device, arrangement, channel roles, axis, frame, unit, sign, timebase, software, calibration/zeroing and processing-state fields; the inherited protocol/device/artifact slots are nullable so unresolved CMJ states remain representable without defaults. Athlete/session/test/trial context remains ObservationContext.
ALTERNATIVES_CONSIDERED=
- One universal CMJ protocol: rejected because the authority explicitly permits materially different protocol identities.
- Display label as identity: rejected because the same label can name different acquisition identities.
- Athlete/session/trial fields inside MeasurementIdentity: rejected because those belong to ObservationContext.
ASSUMPTIONS=An explicit registry reference is sufficient to identify a protocol or device definition; absence is represented as `None` and is never replaced with a default protocol value.
LIMITATIONS=This record does not establish validity, reliability, measurement uncertainty, event definitions, or equivalence between devices/protocols.
REGISTRY_OBJECTS_AFFECTED=`CMJ_TEST_FAMILY`; `CMJProtocolIdentity`; `CMJAcquisitionIdentity`; `CMJMeasurementIdentity`; `CMJ_REGISTRY_VERSION=1.0.0`.
IMPLEMENTATION=`src/dynamislm/measurement/identity.py` (nullable unresolved slots); `src/dynamislm/measurement/cmj/identity.py`; `src/dynamislm/measurement/cmj/acquisition.py`.
TESTS=`tests/test_cmj.py`: same-label identity separation, context immutability, missing protocol/device/channel/frame/unit detection, canonical round-trip.
VERSION=RES34-P1B-1.0.0
