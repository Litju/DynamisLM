# RES45-DR-002

DECISION_ID=RES45-DR-002
STATUS=ADOPTED
QUESTION=What parameter domains are scientifically admissible for the currently registered RES-36 CMJ event detector methods?
PROBLEM=RES-36 preserved threshold values and sigma multipliers explicitly but only required finiteness, allowing structurally constructible values such as negative/zero absolute contact thresholds and non-positive baseline-SD multipliers.
SCOPE=Parameter validity for `CMJ_MOVEMENT_ONSET_BASELINE_SD`, `CMJ_TAKEOFF_ABSOLUTE_FORCE`, and `CMJ_LANDING_ABSOLUTE_FORCE`; no new detector family, universal parameter value, filtering, or mechanics.
SOURCES=
- `docs/decisions/RES36-DR-001-movement-onset.md`
- `docs/decisions/RES36-DR-002-takeoff-contact-loss.md`
- `docs/decisions/RES36-DR-003-landing-contact-regain.md`
- `docs/decisions/RES36-DR-004-event-index-time-and-comparability.md`
- [Comparison of the Reliability of Four Different Movement Thresholds When Evaluating Vertical Jump Performance](https://pmc.ncbi.nlm.nih.gov/articles/PMC9783824/)
- [Comparison of Different Take-off Thresholds When Assessing Vertical Jump Performance](https://pubmed.ncbi.nlm.nih.gov/38863789/)
- [Assessment of Countermovement Jump: What Should We Report?](https://pmc.ncbi.nlm.nih.gov/articles/PMC9865236/)
CANONICAL_AUTHORITY=RES-36 registered method identities, strict sample crossing rules, explicit parameter preservation, and event-order/search prerequisites remain authoritative. This record corrects only admissibility domains.
OPTIONS_CONSIDERED=
- Permit any finite absolute threshold: rejected because a negative or zero value is not a positive absolute contact-force boundary for the registered upward-positive support-force method.
- Permit `threshold_n >= 0`: rejected; zero does not define a positive contact boundary and can make strict contact-loss qualification depend on negative force artifacts.
- Require `threshold_n > 0`: adopted for both absolute-force takeoff and landing methods; this is a domain, not a chosen threshold value.
- Permit `sigma_multiplier >= 0`: rejected; zero collapses baseline-SD deviation to the baseline mean rather than applying a positive noise multiplier.
- Require `sigma_multiplier > 0`: adopted with no project-wide upper bound or default.
- Change dwell/search semantics: rejected; `dwell_samples >= 1` and existing support/order constraints are sufficient and remain unchanged.
DECISION=Every supplied `threshold_n` and `sigma_multiplier` is rejected unless finite. When supplied, `threshold_n` must be strictly positive. This applies to the absolute-force contact-loss and contact-regain methods; the value remains caller/method parameterized. When supplied, `sigma_multiplier` must be strictly positive for the baseline-SD onset method. `dwell_samples >= 1` remains sufficient. Required search starts must remain inside source sample support, onset search must remain after the weighing segment, takeoff search must remain after an optional onset, and landing search remains derived from `takeoff.sample_index + 1`.
RATIONALE=A contact threshold in the registered absolute-force family is a positive boundary in canonical upward-positive force units; rejecting non-positive values prevents an invalid sign/domain interpretation without selecting a project-wide magnitude. A baseline-SD method requires a positive multiplier so the threshold represents a nonzero deviation from baseline noise; zero is a baseline-mean crossing, not a sigma-deviation parameter. Finiteness prevents NaN/Infinity from bypassing deterministic comparisons.
MIGRATION_EFFECT=Existing positive finite parameterized values remain valid. Existing zero/negative thresholds or sigma multipliers now fail at object construction and canonical decode; callers must provide a positive method-specific value. No 5 N, 20 N, 5 SD, 10 SD, or other universal default is added.
SERIALIZATION_EFFECT=The corrected parameter objects serialize their same explicit values under canonical version 3. Prior v2 envelopes are rejected by the strict decoder; no old non-positive value is silently migrated or reinterpreted. Canonical IDs/digests that include detector parameters are consequently version-bound.
ASSUMPTIONS=The registered CMJ force signal is canonical finite upward-positive force in N. “Absolute threshold” describes a positive force boundary, while the method remains operational and does not assert one universal magnitude. A baseline SD itself may be zero; the multiplier domain does not create a noise-adequacy or biological-validity rule.
LIMITATIONS=This record does not select thresholds, impose an upper bound, estimate baseline noise, adjudicate quiet standing, add detector families, or establish biological accuracy. It does not alter dwell, search, event ordering, time attachment, or any downstream mechanics.
IMPLEMENTATION=`src/dynamislm/measurement/cmj/events.py` (`CMJEventDetectorParameters`); RES-36 decision records 001/002/003; `tests/test_cmj.py`.
TESTS=`tests/test_cmj.py` proves negative/zero/positive absolute thresholds, negative/zero/positive sigma multipliers, NaN/Infinity rejection, explicit parameter retention, absence of hidden defaults, and unchanged event detection/dwell/search behavior.
VERSION=RES45-P1D1-1.0.0
