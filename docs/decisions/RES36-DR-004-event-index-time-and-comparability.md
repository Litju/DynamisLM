DECISION_ID: RES36-DR-004
STATUS: ADOPTED

QUESTION

What exact sample/time, refusal, and comparability semantics apply to CMJ event
occurrences?

SCOPE

All RES-36 event occurrences and event-to-event comparison claims.

SOURCES

- [Assessment of Countermovement Jump: What Should We Report?](https://pmc.ncbi.nlm.nih.gov/articles/PMC9865236/)
- [The effect of different movement onset thresholds on countermovement jump performance](https://pmc.ncbi.nlm.nih.gov/articles/PMC9783824/)
- [Comparison of Different Take-off Thresholds When Assessing Vertical Jump Performance](https://pubmed.ncbi.nlm.nih.gov/38863789/)

APPLICABILITY

The sources motivate explicit operational definitions and demonstrate that
method choices change event-dependent outputs. Exact sample/time and refusal
rules below are DynamisLM contract decisions, not claims that synthetic
oracles establish biological accuracy.

OPTIONS_CONSIDERED

- interpolate threshold crossings between samples;
- use hidden rounding/backshift conventions;
- choose a candidate by an undocumented implementation order;
- treat same labels as comparable;
- register deterministic sample-attached events with explicit refusal/QC.

DECISION

An event occurrence is sample-attached. Its index is the first sample of the
first qualifying dwell run under its registered method. For a regular timebase,
time is `start_time_s + sample_index / sample_rate_hz`. For an explicit
timebase, time is exactly `times_s[sample_index]`. No implicit interpolation,
filtering, timestamp repair, resampling, or backshift is performed.

The registered earliest-run tie-break is deterministic; later qualifying runs
are retained as structural QC. A missing crossing or insufficient dwell returns
a claim-specific refusal. Invalid event order is refused, never repaired. A
missing landing does not invalidate already returned onset or takeoff objects.

Comparability requires matching event definition, detector method/version,
all material detector parameters, source force-processing/acquisition identity,
and timebase identity. A method or parameter mismatch is not silently flattened
by matching event labels or event times.

RATIONALE

Sample attachment makes index semantics auditable and preserves exact recorded
timestamps. Explicit refusals prevent ambiguous candidates and inadequate
signals from becoming fabricated events. The comparability rule follows the
sealed provenance architecture: claims are relative to declared identity and
must distinguish methods and transformations.

PARAMETERS

- sample indices satisfy `0 <= index < len(samples)`;
- regular and explicit timebase calculations are exact deterministic formulas;
- dwell is an explicit integer sample count, not an inferred duration;
- no backshift parameter is registered in RES-36;
- structural codes include threshold-not-crossed, insufficient-dwell,
  multiple-candidate QC, boundary QC, ordering conflict, and missing landing.

ASSUMPTIONS

The existing RES-34/RES-35 validation and provenance boundaries are
authoritative. Any future backshift, filtering, or transformation needs its
own registered identity and evidence.

LIMITATIONS

Synthetic traces test arithmetic, identity, provenance, refusal, and
serialization only. They do not validate biological event accuracy or support
confidence percentages.

REGISTRY_OBJECTS_AFFECTED

- `CMJ_EVENT_COMPARABILITY_RULE@1.0.0`;
- RES-36 event definitions, methods, parameter and refusal reason registries.

IMPLEMENTATION

The event module emits immutable `CMJEventDefinition`,
`CMJEventDetectorMethod`, `CMJEventDetectorParameters`, and
`CMJEventOccurrence` objects with canonical provenance. `compare_cmj_events()`
uses the registered event comparability rule.

TESTS

Synthetic regular/explicit timestamp traces, no interpolation, dwell,
ambiguity tie-break, invalid order, missing landing, source immutability,
method mismatch, serialization, and all prior RES-32/34/35/41 tests.

VERSION

1.0.0
