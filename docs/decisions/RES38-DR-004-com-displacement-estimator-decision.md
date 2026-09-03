# RES38-DR-004 — COM-displacement estimator deferral

## DECISION_ID

`RES38-DR-004-com-displacement-estimator-decision`

## STATUS

`DEFERRED`

## QUESTION

Can the sealed RES-37 relative displacement series support a scientifically
clean third COM-displacement jump-height estimator in V1?

## SCOPE

V1 implementation boundary for any estimator that would use integrated
supported-system displacement rather than flight time or takeoff velocity.

## SOURCES

- RES37-DR-004 velocity decision.
- RES37-DR-005 relative displacement reference decision.
- RES46-DR-001 qualified zero-velocity decision.
- RES38-DR-001 and RES38-DR-002.

## APPLICABILITY

Applies to the current `SupportedSystemComRelativeDisplacementResult`, whose
coordinate is relative to the velocity integration start sample.

## OPTIONS_CONSIDERED

1. Treat the maximum relative displacement sample as apex height.
2. Add a minimum-velocity, zero-velocity, apex, drift, or phase authority.
3. Defer the estimator until those authorities are separately registered.

## DECISION

Choose option 3. `COM_DISPLACEMENT_ESTIMATOR=DEFERRED` for RES-38.

## ESTIMAND

No third estimator is registered. The existing relative displacement quantity
remains supported-system relative vertical displacement, not anatomical COM
height or takeoff-to-apex jump height.

## ESTIMATOR

None. No public generic or COM-displacement jump-height operation is exposed.

## EQUATION

None registered.

## INPUTS

No new inputs are authorized.

## EVENT_SEMANTICS

No apex phase, minimum-velocity phase, zero-velocity event, or drift-correction
boundary may be invented by RES-38.

## GRAVITY_SEMANTICS

No new gravity path is created.

## ASSUMPTIONS

The blocker is unresolved authority, not arithmetic: an absolute/anatomical COM
origin, apex selection, and drift policy are absent from the sealed upstream
contracts.

## CLASSIFICATION

No output is emitted; therefore no model-estimate classification is assigned.

## CLAIM_CEILING

The upstream relative displacement can be independently described only under
RES-37 semantics. It cannot be called jump height or apex COM displacement.

## PROVENANCE

No new output provenance is created.

## COMPARABILITY

No COM-displacement estimate can enter estimator-aware comparability.

## REFUSAL

The dedicated deferral refusal uses `COM_DISPLACEMENT_ESTIMATOR_DEFERRED` and
preserves any supplied upstream displacement description.

## LIMITATIONS

Future work must separately authorize apex/phase selection, coordinate origin,
and drift handling before implementation.

## IMPLEMENTATION

Only a refusal constructor is implemented; no displacement estimator exists.

## TESTS

The public CMJ surface exposes no COM-displacement estimator, and the explicit
deferral refusal is granular and deterministic.

## VERSION

`1.0.0`
