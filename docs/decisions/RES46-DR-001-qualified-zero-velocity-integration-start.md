# RES46-DR-001

DECISION_ID=RES46-DR-001
STATUS=ADOPTED
QUESTION=What minimum scientific evidence and identity are required to assert `v_z(t_start)=0 m/s` for authoritative force-platform CMJ forward integration?
PROBLEM=RES-37 accepted `InitialVelocityCondition.zero_at_sample(...)` at any compatible sample. A caller-supplied index and a numeric zero do not establish that the supported physical system was stationary there. A threshold-defined movement-onset occurrence is also an operational detector sample, not automatically the exact physical zero-velocity instant.

SOURCES=
- `docs/decisions/RES35-DR-001-weighing-segment-and-system-weight.md`
- `docs/decisions/RES36-DR-001-movement-onset.md`
- `docs/decisions/RES36-DR-004-event-index-time-and-comparability.md`
- `docs/decisions/RES37-DR-002-impulse-and-integration-semantics.md`
- `docs/decisions/RES37-DR-004-velocity-initial-condition.md`
- [Linthorne, 2001, Standing vertical jump](https://bura.brunel.ac.uk/handle/2438/1392)
- [Guess et al., 2020, force-platform CMJ COM processing](https://pmc.ncbi.nlm.nih.gov/articles/PMC7761544/)
- [McMahon, Lake & Comfort, 2022, position-specific CMJ processing](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0265999)
- [Meylan, Nosaka, Green & Cronin, 2011, The effect of three different start thresholds on the kinematics and kinetics of a countermovement jump](https://pubmed.ncbi.nlm.nih.gov/20664368/)

APPLICABILITY=Authoritative supported-system COM vertical velocity derived from a valid RES-37 supported-system acceleration series and a registered inclusive integration interval. This decision does not authorize takeoff velocity, jump height, or any downstream flight calculation.

OPTIONS_CONSIDERED=
- A. Use an exact RES-35 `SystemWeightResult` weighing segment as a protocol-defined pre-movement reference: adopted only with the explicit RES-35 `WeighingBaselineQC.acceptability_adjudicated=True` marker. The estimator's default descriptive, non-adjudicated QC is insufficient.
- B. Derive a pre-movement reference from the RES-36 movement-onset event minus a fixed duration: not adopted in V1. Published methods demonstrate that a pre-onset reset can be used, but the duration, detector, timebase mapping, and sample-selection rule are method identity; RES-36 V1 registers no such backshift.
- C. Introduce another quiet-standing or sensor-derived reference: deferred because it would require a separate registered evidence and linkage contract.
- D. Continue to accept an arbitrary caller-supplied zero: rejected for the authoritative physical operation. The legacy `InitialVelocityCondition` type remains only as an explicit non-authoritative wire-compatible record; it cannot authorize physical velocity.

DECISION=V1 authoritative velocity requires `QualifiedZeroVelocityReference`. The reference is created from the exact RES-35 `SystemWeightResult` and carries its source signal, source artifact, source measurement identity, exact half-open weighing segment, exact SYSTEM_WEIGHT observation identity, the exact descriptive `WeighingBaselineQC`, registered method, evidence decision, sample index, and `0 m/s`. The linked QC must carry an explicit acceptability adjudication and the source observation's QC flags must agree with it. The default RES-35 estimator output is deliberately non-adjudicated; a bare segment, a descriptive QC record, or an arbitrary index cannot authorize physical zero. The reference sample must lie inside the weighing segment `[start_index, end_index)` and the velocity integration interval must start at that same sample. No free-form assumption text can satisfy or upgrade this contract.

AUTHORITY_MODEL=Zero velocity is a typed prerequisite, not a caller assertion. The physical operation verifies that the reference is explicitly adjudicated, that its QC and QC flags are exactly linked to the source SYSTEM_WEIGHT path, that the reference's exact source IDs and SYSTEM_WEIGHT observation are present in the acceleration provenance, and that the reference source signal and sample match the integration interval. The matching SYSTEM_WEIGHT observation supplies the trial/context/system linkage; a reference from another trial, signal, artifact, measurement identity, or system is refused.

ZERO_VELOCITY_REFERENCE=The adopted reference is a protocol-defined pre-movement reference anchored in the exact RES-35 weighing segment and an explicit acceptability adjudication. The segment and QC establish the registered protocol identity and source evidence; the adjudication is not a universal physiological-stillness threshold and does not overclaim biological stillness. A segment produced by RES-35's default non-adjudicated estimator, including one that contains movement, cannot authorize zero velocity. A later integration start is not authorized merely because an earlier qualified reference was zero; a later sample requires its own qualified reference.

EVENT_RELATION=RES-36 movement onset remains an operational threshold-defined occurrence used to locate movement, preserve event identity, and support event-bounded operations. It is not treated as exact physical `v=0`, and V1 does not use an event-linked zero-velocity reference. The previous RES-37 claim of an optional event-linked initial-condition path is removed rather than left unsupported.

BACKSHIFT_SEMANTICS=No pre-onset backshift is registered in V1. There is no implicit 30 ms, 200 ms, or 250 ms offset; no regular-timebase duration-to-sample mapping; no irregular-timebase nominal-frequency shortcut; and no interpolation. A future backshift must be a separately registered method identity with explicit duration or sample offset, rounding/sample-selection policy, actual-timestamp behavior, and refusal for unrepresentable requests.

INITIAL_CONDITION=The authoritative value is exactly `0.0 m/s` at the qualified reference sample. `InitialVelocityCondition.zero_at_sample(...)` is not accepted by the physical velocity operation, even when its sample is compatible or paired with an event. No conditional numerical path is added in RES-46.

CLAIM_CEILING=The result is supported-system COM vertical velocity under the registered physical system, physical mass, force, timebase, integration interval, and qualified zero-velocity reference. It does not establish athlete-COM velocity, absolute COM position, physiological stillness beyond the protocol-defined reference identity, drift correction, or any jump-height claim.

MIGRATION_EFFECT=Existing RES-37 velocity call sites must construct a qualified reference from the exact compatible `SystemWeightResult`. Arbitrary initial-condition call sites now receive structured refusal. Displacement remains downstream of `SupportedSystemComVelocityResult`, so it inherits the corrected authority without a bypass.

SERIALIZATION_EFFECT=`SERIALIZATION_VERSION` remains 3. `QualifiedZeroVelocityReference` is a distinct registered serializable type. The old `InitialVelocityCondition` wire shape is not reinterpreted, but a legacy RES-37 velocity payload containing that nested type is rejected by the strict decoder rather than accepted as physical velocity. No old physical-velocity hash is silently re-materialized.

PROVENANCE_EFFECT=Velocity processing parameters canonically preserve the qualified reference, including method, evidence decision, source segment, source SYSTEM_WEIGHT observation, exact baseline QC/adjudication, sample index, value, and units. Source observation, artifact, signal, and measurement-identity linkage remains in the provenance DAG; RES-46 decision support is recorded for the velocity operation. Displacement carries the same qualified reference in its series and therefore cannot be manually relabeled as authoritative without upstream velocity authority.

COMPARABILITY_EFFECT=The qualified zero-reference method and exact weighing-segment selection are material velocity identity. Comparability distinguishes different reference methods or segment selections even when the resulting start sample happens to be the same. Trial-instance IDs remain provenance linkage rather than a blanket cross-trial comparability veto.

REFUSAL_EFFECT=The physical velocity operation returns the existing structured refusal architecture with granular `ZERO_VELOCITY_REFERENCE_REQUIRED`, `ZERO_VELOCITY_REFERENCE_UNQUALIFIED`, `ZERO_VELOCITY_SOURCE_MISMATCH`, and `ZERO_VELOCITY_REFERENCE_MISMATCH` reasons, retaining `INITIAL_CONDITION_UNRESOLVED` as the legacy-compatible companion where applicable. Displacement still refuses without a valid upstream velocity, its qualified zero-reference lineage, or its exact relative origin.

ASSUMPTIONS=An explicit protocol-level adjudication marks the exact RES-35 weighing segment as acceptable for the V1 pre-movement reference contract. This is a typed prerequisite and source-linked assertion, not a universal threshold or biological-stillness proof. Existing RES-37 force, impulse, mass, acceleration, trapezoidal integration, timebase, and displacement semantics remain applicable.

LIMITATIONS=V1 does not register movement-onset backshift, event-linked zero velocity, interpolation, zero-velocity updating, endpoint correction, filtering, drift correction, uncertainty propagation, or any jump-height estimator. Explicit timestamps are supported by existing integration arithmetic but not by a new duration-backshift rule.

IMPLEMENTATION=`src/dynamislm/measurement/cmj/mechanics.py`, `src/dynamislm/measurement/cmj/registry.py`, `src/dynamislm/refusal/models.py`, and `src/dynamislm/comparability/models.py`. The legacy type remains registered only so strict v3 decoding can reject its use as an authoritative physical reference.

TESTS=Qualified reference construction and v3 roundtrip; missing and arbitrary initial-condition refusals; post-movement arbitrary zero refusal; non-adjudicated movement-containing segment refusal; wrong signal, artifact, measurement identity, SYSTEM_WEIGHT observation, trial/context, and system refusals; exact segment membership and start linkage; provenance support; displacement rejection when qualified velocity lineage is removed; distinct start-method comparability; unchanged trapezoidal velocity/displacement oracle; unchanged force, impulse, acceleration, physical-mass, loaded-system, and standard-gravity rejection regressions. No event-linked velocity path is tested as authoritative because this decision explicitly does not adopt one; RES37-DR-004 is updated to remove that unsupported claim.

VERSION=RES46-P1E1-1.0.0
