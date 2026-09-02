# RES35-DR-001

DECISION_ID=RES35-DR-001
STATUS=ADOPTED
QUESTION=What scientific quantity and deterministic estimator should a CMJ weighing segment produce, and how should the segment be identified without importing event detection?
SCOPE=CMJ supported-force weighing only; no movement onset, takeoff, landing, impulse, COM kinematics, jump height, filtering, or performance interpretation.
SOURCES=
- `docs/architecture/SCIENTIFIC_CONSTITUTION_V1.md`
- `docs/architecture/MEASUREMENT_DATA_PROVENANCE_V1.md`
- `docs/architecture/P1_EXECUTION_CONTRACT.md`
- [Owen et al. 2014, Development of a Criterion Method to Determine Peak Mechanical Power Output in a Countermovement Jump](https://doi.org/10.1519/JSC.0000000000000311)
- [Heishman et al. 2020, Force-Time Waveform Shape Reveals Countermovement Jump Strategies of Collegiate Athletes](https://pmc.ncbi.nlm.nih.gov/articles/PMC7761544/)
- [Merrigan et al. 2023, Assessment of Countermovement Jump: What Should We Report?](https://pmc.ncbi.nlm.nih.gov/articles/PMC9865236/)
APPLICABILITY=The cited CMJ force-platform methods use quiet-standing/weighing intervals and mean vertical force, but differ in interval duration and protocol. They support the estimator family and the need to preserve the interval identity; they do not establish a universal duration, quietness threshold, or biological acceptance rule for all DynamisLM acquisitions.
OPTIONS_CONSIDERED=
- Automatic quiet-standing detection: deferred because published procedures use materially different windows/thresholds and an event-independent P1C detector has not been registered; movement onset belongs to RES-36.
- Explicit time interval with implementation-defined endpoint interpolation: rejected because the current source contract does not authorize interpolation or an exclusive timestamp endpoint.
- Explicit sample-index interval with `[start_index, end_index)` semantics: adopted because it is deterministic, preserves exact source samples, and keeps selection separate from estimation.
- Mean, median, or trimmed mean force: arithmetic mean adopted because the cited force-platform methods define baseline/body-weight estimates as mean vertical force over a stated weighing interval. No trimming or smoothing is applied.
DECISION=Register `CMJ_EXPLICIT_WEIGHING_SEGMENT` version `1.0.0` as an explicitly supplied sample-index interval. `WeighingSegment` stores source signal/artifact/identity references, non-negative `start_index`, `end_index`, and selection parameters with `start_index < end_index`; the selected samples are exactly `signal.samples[start_index:end_index]`. The first estimator is `CMJ_SYSTEM_WEIGHT_MEAN_FORCE` version `1.0.0`, which returns the arithmetic mean of the selected canonical vertical-force samples as `SYSTEM_WEIGHT` in newtons. The operation requires at least two finite samples so its sample standard deviation is defined; this is computational adequacy, not a universal quiet-standing or biological-validity threshold. The supported system is the physical system represented by the acquisition/protocol, including supported external load where present.
QC=Calculate deterministic descriptive metadata only: sample count, sample-supported duration, mean force, sample standard deviation, and range. For a regular timebase, duration is `sample_count / sample_rate_hz`; for an explicit timebase, duration is the last selected timestamp minus the first. Set quality flags to `QC_DESCRIBED` and `QC_ACCEPTABILITY_NOT_ADJUDICATED`; no universal pass/fail threshold is registered.
RATIONALE=The force platform records supported force. During an explicitly identified interval selected for weighing, its mean vertical force is an estimate of the supported system's static-support force under the supplied protocol and acquisition assumptions. Naming the output `SYSTEM_WEIGHT` keeps force and mass distinct and avoids relabeling a loaded or otherwise supported system as body weight.
ASSUMPTIONS=The supplied interval is intended to be a weighing interval by the caller/protocol; source samples and their timebase are already represented by the sealed RES-34 contract; the input force is canonical, finite, and explicitly upward-positive; no filtering, baseline trimming, or event-derived boundary is hidden in the estimator.
LIMITATIONS=No automated quiet-standing detector, duration threshold, variability threshold, uncertainty model, calibration correction, biological validity claim, or body-mass equivalence is established. A descriptive QC value does not adjudicate acceptability.
REGISTRY_OBJECTS_AFFECTED=`CMJ_EXPLICIT_WEIGHING_SEGMENT`; `CMJ_SYSTEM_WEIGHT_MEAN_FORCE`; `CMJ_SYSTEM_WEIGHT_OPERATION`; `SYSTEM_WEIGHT` measurand/metric; `WeighingSegment`; `WeighingBaselineQC`.
IMPLEMENTATION=`src/dynamislm/measurement/cmj/weighing.py`; `src/dynamislm/measurement/cmj/registry.py`.
TESTS=`tests/test_cmj.py`: half-open boundary selection, segment/estimator separation, deterministic mean/QC, source immutability, no event dependency, and v2 round-trip.
VERSION=RES35-P1C-1.0.0
