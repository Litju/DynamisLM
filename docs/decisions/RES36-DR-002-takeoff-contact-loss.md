DECISION_ID: RES36-DR-002
STATUS: ADOPTED

QUESTION

Which deterministic force-based event method is registered for TAKEOFF /
CONTACT_LOSS?

SCOPE

TAKEOFF_CONTACT_LOSS only. This is a contact-loss event and is not the end of
the propulsive phase by default.

SOURCES

- [Comparison of Different Take-off Thresholds When Assessing Vertical Jump Performance](https://pubmed.ncbi.nlm.nih.gov/38863789/)
- [Assessment of Countermovement Jump: What Should We Report?](https://pmc.ncbi.nlm.nih.gov/articles/PMC9865236/)

APPLICABILITY

The comparison study directly demonstrates that 20 N, 10 N, 5 N, 1 N, 5 SD,
and peak-residual-force takeoff rules are distinct operationalizations and can
alter derived CMJ outputs. The reporting study provides a concrete force-based
contact convention. Neither establishes one universal threshold for every
device or population.

OPTIONS_CONSIDERED

- fixed absolute-force threshold;
- unloaded-force residual/noise threshold;
- flight-noise threshold requiring a known flight region;
- a method-specific filtered or interpolated crossing.

DECISION

Register `CMJ_TAKEOFF_ABSOLUTE_FORCE@1.0.0`. The threshold value in N,
crossing direction, dwell count, search start, and sample-index convention are
required detector parameters. The event is the first sample of the earliest
contiguous run of `dwell_samples` samples strictly below the explicit
threshold. A supplied movement-onset occurrence is an optional ordering
precondition; if supplied, takeoff search must begin strictly after it.

RATIONALE

An absolute-force detector is the smallest deterministic contact-loss method
that does not require a circular flight-noise bootstrap. Its numeric threshold
is deliberately not fixed by this project. Preserving the threshold and
crossing rule in the event identity keeps 20 N, 5 N, and other defensible
methods separate for comparability.

PARAMETERS

- `threshold_n` is required and finite;
- `direction = BELOW_THRESHOLD`;
- `dwell_samples` is required and sample-count based;
- `search_start_index` is required;
- event index is the first sample satisfying the full dwell run;
- equality does not qualify;
- earliest qualifying run is the registered tie-break, with a structural QC
  flag for additional qualifying runs.

ASSUMPTIONS

The input is qualified supported vertical force, already total where bilateral
acquisition requires it. No force filtering, resampling, interpolation, sign
flip, or unit conversion occurs in RES-36.

LIMITATIONS

This is an operational force threshold, not a universal scientific truth. A
flight-noise/residual method is deferred until its prerequisites and identity
are independently registered. Takeoff does not create a flight-phase object,
propulsive-phase boundary, or jump-height result.

REGISTRY_OBJECTS_AFFECTED

- `CMJ_TAKEOFF_CONTACT_LOSS_EVENT_DEFINITION@1.0.0`;
- `CMJ_TAKEOFF_ABSOLUTE_FORCE_METHOD@1.0.0`;
- `CMJ_EVENT_COMPARABILITY_RULE@1.0.0`.

IMPLEMENTATION

`detect_takeoff()` in `src/dynamislm/measurement/cmj/events.py` performs strict
sample comparisons and explicit dwell scanning, returning a structured refusal
when the threshold is absent, not crossed, or not persistent.

TESTS

Synthetic traces cover explicit thresholds, no takeoff, insufficient dwell,
transient spikes, multiple runs, ordering after movement onset, exact sample
index/time, provenance, serialization, and source immutability.

VERSION

1.0.0
