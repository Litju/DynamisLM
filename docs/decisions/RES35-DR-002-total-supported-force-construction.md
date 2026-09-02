# RES35-DR-002

DECISION_ID=RES35-DR-002
STATUS=ADOPTED
QUESTION=How may DynamisLM construct total supported vertical force from CMJ force-platform acquisitions without silently changing units, sign/frame semantics, timebase, or provenance?
SCOPE=Supported vertical-force input construction for RES-35 weighing; no event/mechanics computation and no device-equivalence bridge.
SOURCES=
- `docs/architecture/MEASUREMENT_DATA_PROVENANCE_V1.md`
- `docs/architecture/SCIENTIFIC_CONSTITUTION_V1.md`
- `docs/architecture/P1_EXECUTION_CONTRACT.md`
- [NIST Guide to the SI, Chapter 4](https://www.nist.gov/pml/special-publication-811/nist-guide-si-chapter-4-two-classes-si-units-and-si-prefixes)
- [NIST Guide to the SI, Appendix B.9 conversion factors](https://www.nist.gov/pml/special-publication-811/nist-guide-si-appendix-b-conversion-factors/nist-guide-si-appendix-b9)
- [Heishman et al. 2020, Force-Time Waveform Shape Reveals Countermovement Jump Strategies of Collegiate Athletes](https://pmc.ncbi.nlm.nih.gov/articles/PMC7761544/)
- [A Dual-Channel Strain Gauge Force Plate System with Hardware-Triggered Synchronization for Countermovement Jump Analysis](https://pubmed.ncbi.nlm.nih.gov/42451280/)
APPLICABILITY=The force-platform studies demonstrate separate bilateral vertical-force channels and total-force construction in CMJ workflows. NIST supports the distinction between force and mass and the SI force-unit context. These sources do not authorize DynamisLM to repair unknown synchronization, infer axis orientation, or harmonize devices.
OPTIONS_CONSIDERED=
- Sum the values of any two channels by matching array positions: rejected because equal array length does not establish shared timebase, axis/frame, sign, units, or intended trial context.
- Normalize/resample/shift/flip/convert implicitly: rejected because each is a distinct processing operation requiring its own registered method and provenance.
- Accept only canonical newtons for the first operation: adopted as the smallest complete policy; existing non-N force units remain representable but require an explicit registered transformation before weighing.
- Treat a vendor/precombined signal as a DynamisLM bilateral sum: rejected because acquisition histories and combination lineage are materially different.
DECISION=Register `CMJ_BILATERAL_TOTAL_VERTICAL_FORCE_SUM` version `1.0.0`. For `BILATERAL_SEPARATE`, require exactly one explicitly identified left channel and one right channel, matching intended athlete/session/test/trial context, compatible registered vertical axis and reference frame, the same explicit upward-positive sign convention, exact canonical `N` unit on both signals, compatible regular/explicit timebase with matching clock reference and acquisition timestamps, identical sample support and timestamps, known non-unknown processing state, and immutable source artifacts/acquisition lineage. Produce each output sample as `left[i] + right[i]` with no resampling, interpolation, filtering, time shifting, sign flip, unit conversion, or sample dropping. The result is a new `SYSTEM_PROCESSED` signal and observation with source lineage to both inputs and a registered processing run.
PATHS=`SINGLE_PLATFORM` passes through the source signal/observation when its acquisition identity establishes supported total vertical force; `BILATERAL_PRECOMBINED` passes through the original vendor/device/direct combination lineage when its existing combination contract is valid; `BILATERAL_SEPARATE` uses the registered DynamisLM sum only after all prerequisites pass. A left/right-only path is never treated as total system force.
UNIT_POLICY=The operation accepts only `NEWTON` by stable unit identity. `kN`, `lbf`, and `kgf` are not silently converted; they return `FORCE_UNIT_TRANSFORMATION_REQUIRED`. No conversion operation is registered in RES-35. `kgf` remains a force unit and is never used as the mass unit.
SIGN_FRAME_POLICY=The operation requires an explicit registered axis/reference-frame identity and an explicit upward-positive sign convention. It does not infer orientation from sample values or flip a signal. Missing, downward-positive, or incompatible semantics return `SIGN_OR_FRAME_UNRESOLVED`.
RATIONALE=Vertical force contributions from concurrently supported bilateral platforms are additive only when they are components of the same physical axis/frame and sample support. New processed identity and two-source lineage make the operation auditable and keep `BILATERAL_SUM` distinct from `RAW_ACQUIRED`.
ASSUMPTIONS=The caller supplies channel identities and test context; the source contract's acquisition metadata is authoritative; exact timestamp equality is sufficient for this deterministic operation and no synchronization repair is attempted.
LIMITATIONS=No cross-device bridge, calibration correction, unit conversion, resampling, filtering, or uncertainty propagation is implemented. Synthetic exact sums validate arithmetic and contracts only, not biological or device performance.
REGISTRY_OBJECTS_AFFECTED=`CMJ_BILATERAL_TOTAL_VERTICAL_FORCE_SUM`; `CMJ_TOTAL_SUPPORTED_VERTICAL_FORCE` schema/measurand/metric; `ProcessedVerticalForceSignal`; `BILATERAL_PRECOMBINED` DynamisLM combination lineage.
IMPLEMENTATION=`src/dynamislm/measurement/cmj/weighing.py`; `src/dynamislm/measurement/cmj/registry.py`; `src/dynamislm/refusal/models.py`.
TESTS=`tests/test_cmj.py`: exact synchronized sum, raw immutability, SYSTEM_PROCESSED classification, two-source provenance, incompatible axis/frame/sign/unit/timebase/sample support, and pass-through path preservation.
VERSION=RES35-P1C-1.0.0
