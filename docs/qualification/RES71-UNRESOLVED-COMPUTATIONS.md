# RES-71 unresolved-computation inventory

Unsupported methods remain explicit and non-authoritative. The complete
machine-readable set is returned by
`build_unresolved_computation_inventory()` and validated by
`validate_unresolved_computation_inventory()`.

## Registered but not computed

| Operation / capability | Disposition | Refusal boundary |
|---|---|---|
| 505 asymmetry | REPRESENT_BUT_DO_NOT_COMPUTE | No frozen denominator, direction or sign convention. |
| BPT mean propulsive velocity | REPRESENT_BUT_DO_NOT_COMPUTE | No generic acceleration/gravity/propulsive-boundary authority. |
| Classical BA limits | REPRESENT_BUT_DO_NOT_COMPUTE | V1 exposes only the registered narrow method-comparison summary. |
| ICC variants, SEM from ICC, MDC/SDC | REPRESENT_BUT_DO_NOT_COMPUTE | No registered reliability estimand/design authority. |
| VBT mean propulsive velocity | REPRESENT_BUT_DO_NOT_COMPUTE | Concentric velocity cannot be relabelled as MPV. |
| Estimated 1RM from load–velocity model | DEFERRED | Terminal-velocity applicability is not authorized across devices/designs. |
| Sustained maximum sprint velocity | DEFERRED | No registered dwell/sustain estimator. |
| Log/repeated-measures BA, confidence intervals, covariance propagation | DEFERRED | Estimator, design and uncertainty contract not sealed. |
| Repeated-measures correlation and mixed effects | DEFERRED | Later analysis mission required; no numeric output is emitted. |
| Generic meaningful change | REJECTED | No universal decision criterion is authorized. |
| Generic SEM | REJECTED | No registered estimand or design. |
| Readiness/fatigue/injury interpretation | REJECTED | Outside the scientific-engine authority boundary. |

## No registered numeric operation

| Capability | Deterministic refusal |
|---|---|
| CMJ RFD | `refuse_unregistered_cmj_rfd` |
| Generic BPT load × velocity power | `calculate_bpt_load_times_velocity_power` |
| MBT distance-as-power / protocol-independent norm | `calculate_mbt_distance_as_power`, `calculate_mbt_protocol_independent_normative_score` |
| Sprint acceleration from split averages | `refuse_sprint_acceleration` |
| VIFT relabelled as VO2max, MAS or maximum sprint speed | `refuse_vift_as_vo2max`, `refuse_vift_as_mas`, `refuse_vift_as_mss` |

The VIFT relabelling routes are identity refusals, not missing-computation
refusals: their expected class is `IDENTITY_UNRESOLVED` with
`MEASURAND_MISMATCH` and `METRIC_DEFINITION_MISMATCH` reason codes. CMJ RFD
expects the producer reason code `NO_REGISTERED_OPERATION`.

Every refusal preserves the blocked claim, reason code(s), missing information
and safe description where the owning family exposes them. No placeholder
number is returned. This is the intended behavior for later LM verifiers:
`COMPUTATION_NOT_REGISTERED` is a scored scientific outcome, not an error to
be bypassed.
