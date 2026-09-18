# RES-69 V1 scale-registry audit

This is the deterministic audit required by RES-69. It is a report of the
public scalar metric identities already present in the RES-34..68 registries;
it is not a new scale authority for any of them.

## Registered scale keys

`REGISTERED_SCALE_KEYS = ()`

No family-specific scale entry is imported into the generic RES-69 package.
There is consequently no production scale authorization rationale in V1.
`PRODUCTION_SCALE_KEYS=0`, and every public scale-dependent calculation fails
closed for production observations. A caller-supplied registry is not a
production authority.

## Unregistered public scalar metric keys

Every key below is intentionally unregistered and fails closed for
scale-dependent operations. The entries remain understood by their owning
scientific registries.

```text
dynamislm:metric:30-15-ift-stage-completion@1.0.0
dynamislm:metric:30-15-ift-stage-velocity@1.0.0
dynamislm:metric:30-15-ift-termination@1.0.0
dynamislm:metric:505-asymmetry@1.0.0
dynamislm:metric:505-cod-deficit@1.0.0
dynamislm:metric:acceleration-event-count@1.0.0
dynamislm:metric:bench-press-throw-dynamislm-time-weighted-mean-bar-velocity@1.0.0
dynamislm:metric:bench-press-throw-provider-maximum-velocity@1.0.0
dynamislm:metric:bench-press-throw-provider-mean-power@1.0.0
dynamislm:metric:bench-press-throw-provider-mean-propulsive-velocity@1.0.0
dynamislm:metric:bench-press-throw-provider-mean-velocity@1.0.0
dynamislm:metric:bench-press-throw-provider-peak-power@1.0.0
dynamislm:metric:bench-press-throw-sampled-maximum-bar-velocity@1.0.0
dynamislm:metric:bench-press-throw-source-qualification@1.0.0
dynamislm:metric:bench-press-throw-velocity-series@1.0.0
dynamislm:metric:body-mass@1.0.0
dynamislm:metric:change-of-direction-left-event-count@1.0.0
dynamislm:metric:change-of-direction-right-event-count@1.0.0
dynamislm:metric:cumulative-split-time@1.0.0
dynamislm:metric:deceleration-event-count@1.0.0
dynamislm:metric:delivered-velocity-series@1.0.0
dynamislm:metric:drop-jump-flight-time-jump-height@1.0.0
dynamislm:metric:drop-jump-ground-contact-time@1.0.0
dynamislm:metric:drop-jump-rebound-flight-time@1.0.0
dynamislm:metric:drop-jump-rsi-jh-ct@1.0.0
dynamislm:metric:drop-jump-rsr-ft-ct@1.0.0
dynamislm:metric:drop-jump-source-qualification@1.0.0
dynamislm:metric:drop-jump-source-series@1.0.0
dynamislm:metric:estimated-one-repetition-maximum@1.0.0
dynamislm:metric:explosive-effort-event-count@1.0.0
dynamislm:metric:field-test-source-qualification@1.0.0
dynamislm:metric:imtp-baseline-force-mean@1.0.0
dynamislm:metric:imtp-force-at-100-ms@1.0.0
dynamislm:metric:imtp-force-at-150-ms@1.0.0
dynamislm:metric:imtp-force-at-200-ms@1.0.0
dynamislm:metric:imtp-force-at-50-ms@1.0.0
dynamislm:metric:imtp-force-per-body-mass@1.0.0
dynamislm:metric:imtp-force-time-series@1.0.0
dynamislm:metric:imtp-gross-endpoint-average-rfd@1.0.0
dynamislm:metric:imtp-gross-force-at-registered-time@1.0.0
dynamislm:metric:imtp-gross-force-impulse@1.0.0
dynamislm:metric:imtp-gross-sampled-peak-force@1.0.0
dynamislm:metric:imtp-impulse-0-100-ms@1.0.0
dynamislm:metric:imtp-impulse-0-150-ms@1.0.0
dynamislm:metric:imtp-impulse-0-200-ms@1.0.0
dynamislm:metric:imtp-impulse-0-50-ms@1.0.0
dynamislm:metric:imtp-net-endpoint-average-rfd-above-baseline@1.0.0
dynamislm:metric:imtp-net-force-at-registered-time@1.0.0
dynamislm:metric:imtp-net-force-impulse-above-baseline@1.0.0
dynamislm:metric:imtp-net-sampled-peak-force-above-baseline@1.0.0
dynamislm:metric:imtp-rfd-0-100-ms@1.0.0
dynamislm:metric:imtp-rfd-0-150-ms@1.0.0
dynamislm:metric:imtp-rfd-0-200-ms@1.0.0
dynamislm:metric:imtp-rfd-0-50-ms@1.0.0
dynamislm:metric:imtp-trial-qualification@1.0.0
dynamislm:metric:individual-linear-load-velocity@1.0.0
dynamislm:metric:interval-split-time@1.0.0
dynamislm:metric:jump-event-count@1.0.0
dynamislm:metric:maximum-speed@1.0.0
dynamislm:metric:maximum-sprint-velocity@1.0.0
dynamislm:metric:mean-concentric-velocity@1.0.0
dynamislm:metric:mean-propulsive-velocity@1.0.0
dynamislm:metric:measured-one-repetition-maximum@1.0.0
dynamislm:metric:medicine-ball-instrumented-release-velocity@1.0.0
dynamislm:metric:medicine-ball-throw-distance@1.0.0
dynamislm:metric:medicine-ball-throw-source-qualification@1.0.0
dynamislm:metric:minutes-exposure@1.0.0
dynamislm:metric:peak-velocity@1.0.0
dynamislm:metric:provider-load@1.0.0
dynamislm:metric:relative-distance@1.0.0
dynamislm:metric:repeated-high-intensity-effort@1.0.0
dynamislm:metric:rhie-bout-count@1.0.0
dynamislm:metric:rhie-efforts-per-bout@1.0.0
dynamislm:metric:rhie-recovery-time@1.0.0
dynamislm:metric:rsa-best-time@1.0.0
dynamislm:metric:rsa-mean-time@1.0.0
dynamislm:metric:rsa-percent-decrement@1.0.0
dynamislm:metric:rsa-sprint-time@1.0.0
dynamislm:metric:rsa-total-time@1.0.0
dynamislm:metric:segment-average-velocity@1.0.0
dynamislm:metric:session-duration@1.0.0
dynamislm:metric:sprint-distance@1.0.0
dynamislm:metric:sprint-event-count@1.0.0
dynamislm:metric:sprint-time@1.0.0
dynamislm:metric:sprint-velocity-series@1.0.0
dynamislm:metric:standard-505-time@1.0.0
dynamislm:metric:threshold-distance@1.0.0
dynamislm:metric:threshold-event-count@1.0.0
dynamislm:metric:threshold-time@1.0.0
dynamislm:metric:total-distance@1.0.0
dynamislm:metric:vift@1.0.0
dynamislm:metric:within-set-velocity-loss@1.0.0
```

The generic Python audit reports the same decision by category through
`UNREGISTERED_SCALE_KEYS` and `SCALE_REGISTRY_AUDIT`; this Markdown report
keeps the family-specific stable IDs outside the generic public package, whose
repository policy prohibits test-family coupling.

Synthetic `MeasurementScaleSemantics` entries remain available only as
explicit test fixtures. `SYNTHETIC_TEST` authority is rejected by public
relative change, log-ratio, raw-relative-error, and log-error calculators;
synthetic entries never authorize a production `StatisticalResult`.
