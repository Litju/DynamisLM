DECISION_ID: RES36-DR-003
STATUS: ADOPTED
CORRECTION: RES45-DR-002 makes the absolute contact threshold domain explicit as finite and strictly positive. The landing/contact-regain decision and parameterized method family remain adopted.

QUESTION

Which deterministic force-based event method is registered for LANDING /
CONTACT_REGAIN?

SCOPE

LANDING_CONTACT_REGAIN only. This event marks contact regain after a valid
takeoff; it does not mark landing-phase end, stabilization, absorption, or a
zero-velocity phase boundary.

SOURCES

- [Assessment of Countermovement Jump: What Should We Report?](https://pmc.ncbi.nlm.nih.gov/articles/PMC9865236/)
- [Comparison of Different Take-off Thresholds When Assessing Vertical Jump Performance](https://pubmed.ncbi.nlm.nih.gov/38863789/)

APPLICABILITY

The reporting study gives a concrete force-based contact-regain convention
(force exceeding a declared low-force threshold) while separately describing
landing phase constructs. The threshold-comparison evidence supports keeping
contact thresholds as explicit method identities. These sources do not justify
inferring post-contact phases in this foundation.

OPTIONS_CONSIDERED

- reuse the takeoff detector as an unlabeled generic crossing;
- define landing as the first force rise above an explicit absolute threshold;
- use a flight-noise/residual threshold;
- detect stabilization or landing-phase end.

DECISION

Register a distinct `CMJ_LANDING_ABSOLUTE_FORCE@1.0.0` method under the
distinct `LANDING_CONTACT_REGAIN` event definition. A valid takeoff occurrence
is required. Search begins at `takeoff.sample_index + 1`, without a caller-
supplied alternate search origin. The event is the first sample of the
earliest contiguous run of `dwell_samples` samples strictly above the explicit
threshold.

RATIONALE

Contact regain has a different event meaning and search precondition from
contact loss even when both use absolute force arithmetic. Separate definition
and method identities prevent same-label or same-threshold conflation and make
the no-landing outcome explicit.

PARAMETERS

- `threshold_n` is required, finite, and strictly positive; zero and negative values are outside the absolute contact-threshold method domain;
- `direction = ABOVE_THRESHOLD`;
- `dwell_samples` is required and sample-count based;
- search origin is derived only from the validated takeoff occurrence;
- equality does not qualify;
- earliest qualifying run is the registered tie-break, with a structural QC
  flag for additional qualifying runs;
- no qualifying run returns `LANDING_NOT_FOUND` plus the underlying crossing or
  dwell reason.

ASSUMPTIONS

Takeoff belongs to the same qualified source force observation and has a valid
sample-attached index. No circular flight-region bootstrap is used.

LIMITATIONS

Landing is not landing-phase end. No stabilization, absorption, phase,
kinematic, impulse, or jump-height object is emitted. Residual/noise-based
alternatives remain deferred and must receive distinct identities if adopted.

REGISTRY_OBJECTS_AFFECTED

- `CMJ_LANDING_CONTACT_REGAIN_EVENT_DEFINITION@1.0.0`;
- `CMJ_LANDING_ABSOLUTE_FORCE_METHOD@1.0.0`;
- `CMJ_EVENT_COMPARABILITY_RULE@1.0.0`.

IMPLEMENTATION

`detect_landing()` in `src/dynamislm/measurement/cmj/events.py` validates the
takeoff/source link, starts after takeoff, applies the explicit upward crossing
and dwell rule, and never repairs ordering or manufactures a landing.

TESTS

Synthetic traces cover valid landing, no landing while preserving onset/
takeoff, transient contact spikes, multiple candidates, explicit timestamps,
invalid takeoff order, provenance, comparability, and canonical round-trip.

MIGRATION_EFFECT

Existing callers that supplied zero or negative `threshold_n` must choose a
method-valid positive value; no universal threshold value is introduced.

SERIALIZATION_EFFECT

The detector parameter domain is enforced on construction and canonical decode.
The RES45 global serialization migration to version 3 rejects prior v2
envelopes; no threshold value is silently reinterpreted.

VERSION

1.0.0
