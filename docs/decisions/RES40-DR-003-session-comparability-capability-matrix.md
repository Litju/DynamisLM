# RES40-DR-003 — CMJ session comparability and capability matrix

DECISION_ID=RES40-DR-003
STATUS=ADOPTED
SCOPE=Comparability/refusal of immutable CMJ session summaries and closure of the first CMJ measurement family.

## SESSION_COMPARABILITY

Two session summaries are directly comparable only when their target measurand,
metric definition, source estimator/method, phase system/definition, acquisition
and processing identity, device/protocol/system/loading contract, selection and
ranking identity including the canonical ranking-method semantic key, tie
policy, aggregation rule/version, candidate and contributing counts,
unit/normalization, filtering, resampling, drift, and processing state agree
under the existing registered authorities.

The following are not direct-comparable by default: selected maximum versus
arithmetic mean; maximum by different ranking metrics; maximize versus
minimize; maximum-of-2 versus maximum-of-3; mean-of-2 versus mean-of-3;
flight-time versus takeoff-velocity jump height; different phase systems;
different devices or protocols; loaded versus unloaded systems; and vendor
selection versus a DynamisLM registered rule. Refusal is claim-relative and
does not invalidate the retained source trials.

Observed values, event/phase coordinates, source IDs, trial IDs, timestamps,
and provenance lineage remain instance records. They do not become method
identity merely because they occur inside a session summary.

## CAPABILITY_MATRIX

| KNOWLEDGE_SCOPE | COMPUTATIONAL_AUTHORITY_SCOPE | CLAIM_AUTHORITY_SCOPE |
| --- | --- | --- |
| CMJ test-family identity, acquisition, protocol, device, timebase, loading, force and mechanics contracts | Registered CMJ raw acquisition, events, mechanics, jump-height estimators, phase system/metrics, trial declaration, eligibility, selection, scalar projection, and arithmetic mean | Estimator-qualified, supported-system trial/session mechanical summaries with retained method and provenance identity |
| Selection and aggregation practice is heterogeneous; Turner 2024, Lake 2018, and Xu 2023 show why rule and estimator identity matter | Explicit ordered candidates; eligible-all and registered extreme selection; maximize/minimize; earliest-declared tie; selected-target separation; scalar-only mean | No universal best trial; no automatic “higher is better”; no metric shopping; no hidden available-case summary |
| Phase method identity is distinct from realized phase coordinates under RES-39/RES-49 | Phase-aware and estimator-aware direct comparability, plus acquisition/device/protocol/system/loading checks | Same methods with different observed event/phase coordinates may compare when all material method identity agrees |
| Session summary identity includes opportunity and contribution counts | Counts are retained and compared; all trial/target omissions are explicit | Mean-of-2 vs mean-of-3 and maximum-of-2 vs maximum-of-3 are not direct-comparable by default |
| Deterministic aggregation is not measurement-error analysis | `NOT_ASSESSED` uncertainty only; no SD, SEM, MDC, TE, CV, ICC, CI, SWC, or responsiveness computation | No reliability, meaningful-change, readiness, fatigue, or causal/physiological claim |
| Deferred scientific definitions | Power; RFD; RSI-mod; asymmetry; normalization families; landing strategy metrics; anatomical COM methods not registered; cross-estimator jump-height bridge; sub-sample phase zero-crossing bridge | No authority for these metrics or cross-method claims |
| Deferred interpretation and external/vendor outputs | Vendor metrics/composites and unregistered selections are not executed or harmonized | No vendor composite, causal, physiological, or unsupported performance claim |

## LIMITATIONS

The matrix describes current repository authority only. Future typed relative
search-origin semantics, estimator bridges, and additional metrics require new
registered decisions and tests; they are not inferred by this record.

## SERIALIZATION

`SERIALIZATION_VERSION=3`. Session objects are additive. No historical phase or
phase-metric serialization/hash is changed by the session comparator.
