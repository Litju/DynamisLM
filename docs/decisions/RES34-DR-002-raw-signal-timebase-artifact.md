# RES34-DR-002

DECISION_ID=RES34-DR-002
STATUS=ADOPTED
QUESTION=How should a CMJ vertical-force source be represented so raw content, timebase semantics and acquisition provenance cannot be silently transformed?
SCOPE=Raw vertical-force signal, sampling/timebase, processing state, source artifact and raw-observation composition.
SOURCES=
- `docs/architecture/MEASUREMENT_DATA_PROVENANCE_V1.md`
- `docs/architecture/SCIENTIFIC_CONSTITUTION_V1.md`
- [VIM 2.6 measurement procedure](https://jcgm.bipm.org/vim/en/2.6.html)
- [VIM 2.9 measurement result](https://jcgm.bipm.org/vim/en/2.9.html)
- [VIM 2.39 calibration](https://jcgm.bipm.org/vim/en/2.39.html)
- [VIM 2.41 metrological traceability](https://jcgm.bipm.org/vim/en/2.41.html)
- [NIST Guide to the SI, Chapter 4](https://www.nist.gov/pml/special-publication-811/nist-guide-si-chapter-4-two-classes-si-units-and-si-prefixes)
APPLICABILITY=Force quantities represented in the P1B source contract. NIST supports the force-unit registry, while VIM supports preserving measurement procedure/calibration/traceability context; neither authorizes CMJ event or mechanics algorithms.
DECISION=Represent samples as an immutable tuple in `RawVerticalForceSignal`, paired with either an explicit per-sample time tuple or an explicit regular sample rate. Preserve unit, physical axis, reference frame, sign and processing state on the signal and acquisition identity. Distinguish `RAW_ACQUIRED`, `DEVICE_PROCESSED`, `SYSTEM_PROCESSED` and `UNKNOWN`. Use immutable content-addressed `CMJSourceArtifact` metadata with SHA-256 and an explicit acquisition-instance link; canonical synthetic fixtures can verify the digest, while external byte-level verification remains explicitly unverified unless supplied. The raw-observation constructor accepts only `RAW_ACQUIRED` signals. Do not filter, resample, convert units, flip sign or sum bilateral channels in P1B. Keep raw signal payload outside MeasurementResult, which stores only a structured artifact reference.
ALTERNATIVES_CONSIDERED=
- NumPy array storage: rejected for this unit because core tuples provide finite-value and deterministic serialization semantics without a new dependency.
- Implicit time from a sample-rate number: rejected because explicit time samples and clock/timebase identity must remain distinguishable.
- Treating the first vendor export as raw: rejected because exported data may already be device processed.
- Storing samples in a scalar/derived result: rejected because it destroys source/result separation.
ASSUMPTIONS=SHA-256 is the only artifact hash algorithm registered in P1B; a canonical signal representation is a test-fixture encoding, not a claim about every vendor file byte layout. Numeric time-rate tolerance is used only for deterministic representation consistency, not a biological threshold.
LIMITATIONS=No binary parser, external file-byte verifier, calibration correction, filtering, resampling, bilateral combination, or uncertainty model is implemented.
REGISTRY_OBJECTS_AFFECTED=`CMJSourceArtifact`; `RawVerticalForceSignal`; `RegularTimebase`; `ExplicitTimebase`; `CMJ_RAW_VERTICAL_FORCE_SIGNAL_SCHEMA`; `HashAlgorithm.SHA256`.
IMPLEMENTATION=`src/dynamislm/measurement/cmj/signal.py`; `src/dynamislm/measurement/cmj/acquisition.py`; `src/dynamislm/measurement/cmj/validation.py`; `src/dynamislm/serialization.py` (registered subclass round-trip support).
TESTS=`tests/test_cmj.py`: immutable samples/artifact, stable hash, time ordering/rate checks, unit/frame/sign persistence, raw-vs-processed and unknown-state checks, raw observation provenance.
VERSION=RES34-P1B-1.0.0
