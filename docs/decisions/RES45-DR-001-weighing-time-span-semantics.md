# RES45-DR-001

DECISION_ID=RES45-DR-001
STATUS=ADOPTED
QUESTION=Which temporal quantity should RES-35 weighing QC expose for the selected sample support?
PROBLEM=The previous `duration_s` field used `N / fs` for regular samples but `t_last - t_first` for explicit timestamps. Those formulas describe nominal sample-window coverage and elapsed sample span respectively, so equivalent regular and explicit representations of the same sample instants could produce different values under one ambiguous name.
SCOPE=The descriptive temporal metadata attached to an explicit RES-35 weighing segment; no interpolation, resampling, event detection, or CMJ mechanics.
SOURCES=
- `docs/architecture/SCIENTIFIC_CONSTITUTION_V1.md`
- `docs/architecture/MEASUREMENT_DATA_PROVENANCE_V1.md`
- `docs/architecture/P1_EXECUTION_CONTRACT.md`
- `docs/decisions/RES35-DR-001-weighing-segment-and-system-weight.md`
- `src/dynamislm/measurement/cmj/signal.py` regular and explicit timebase contracts
CANONICAL_AUTHORITY=The selected segment is the exact half-open sample interval `[start_index, end_index)` from RES35-DR-001. A sample-attached elapsed span is the timestamp of the last selected sample minus the timestamp of the first selected sample.
OPTIONS_CONSIDERED=
- Keep `duration_s` with mixed formulas: rejected because one field would retain two temporal meanings.
- Report nominal sample-window coverage `N / fs`: rejected as the adopted common meaning because it differs from elapsed span and has no automatic definition for irregular explicit timestamps.
- Report elapsed sample span with a renamed field: adopted.
- Report both span and nominal coverage: rejected as unnecessary for this gate; no nominal interval-support model is registered.
DECISION=Replace `WeighingBaselineQC.duration_s` with `elapsed_sample_span_s`. For a segment containing `N >= 2` selected samples, regular timebase span is `(N - 1) / sample_rate_hz`, independent of `start_time_s`; explicit timebase span is `times_s[end_index - 1] - times_s[start_index]`. The arithmetic mean, sample standard deviation, range, and `[start_index, end_index)` selection remain unchanged.
RATIONALE=Both representations then measure the same observable quantity: the elapsed time between the first and last recorded samples in the selected support. Regular and explicit regular-equivalent timestamps therefore agree, while irregular explicit timestamps preserve their actual recorded endpoint span. The field name states the measurand and prevents a nominal coverage interpretation.
MIGRATION_EFFECT=All runtime and test consumers use `elapsed_sample_span_s`; no `duration_s` compatibility alias is retained because it would preserve the ambiguous contract.
SERIALIZATION_EFFECT=The nested QC wire field changes from `duration_s` to `elapsed_sample_span_s`, requiring canonical serialization version 3. The strict decoder rejects v2 envelopes. Since the canonical envelope version is hashed, canonical signal/artifact digests and hash-derived result/refusal IDs change when objects are re-materialized under v3; no old hash is silently reused.
ASSUMPTIONS=RES-34 validation guarantees finite, ordered explicit timestamps and a valid regular sample rate before the estimator runs. The selected segment has at least two samples. No interpolation is needed or performed.
LIMITATIONS=This does not report acquisition recording duration, endpoint-inclusive coverage, or nominal `N / fs` window coverage. An irregular sampling interval-support model remains unregistered.
IMPLEMENTATION=`src/dynamislm/measurement/cmj/weighing.py` (`WeighingBaselineQC`, `_elapsed_sample_span`, `estimate_system_weight`); `src/dynamislm/serialization.py`; `docs/decisions/RES35-DR-001-weighing-segment-and-system-weight.md`.
TESTS=`tests/test_cmj.py` proves N=2, N>2, regular/explicit regular-equivalent agreement, non-zero regular start-time invariance, irregular explicit endpoint span, field-name alignment, and unchanged mean-force arithmetic.
VERSION=RES45-P1D1-1.0.0
