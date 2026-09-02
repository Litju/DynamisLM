# RES45-DR-003

DECISION_ID=RES45-DR-003
STATUS=ADOPTED
QUESTION=What generic provenance field truthfully identifies the output of a processing run when the output may be either a measurement observation or a CMJ event occurrence?
PROBLEM=`ProcessingRun.output_observation_id` labels every processing output as a ScientificMeasurementObservation, but RES-36 produces `CMJEventOccurrence` instances. Storing an event-occurrence identifier in an observation-named field is a false generic contract and makes lineage validation semantically ambiguous.
SCOPE=The generic ProcessingRun output edge and all existing RES-35, RES-36, and RES-44 producers and validators. No generic entity graph, ORM, plugin registry, or new scientific entity hierarchy is introduced.
SOURCES=
- `docs/architecture/MEASUREMENT_DATA_PROVENANCE_V1.md`
- `docs/architecture/P1_EXECUTION_CONTRACT.md`
- `docs/decisions/RES36-DR-004-event-index-time-and-comparability.md`
- `docs/decisions/RES35-DR-001-weighing-segment-and-system-weight.md`
- `docs/decisions/RES44-DR-001-system-mass-and-standard-gravity-equivalent.md`
CANONICAL_AUTHORITY=`InstanceIdentifier.instance_type` is the existing canonical type discriminator for instance IDs; each processing run must point to one declared output entity through exactly one `PRODUCED` lineage edge.
OPTIONS_CONSIDERED=
- Keep `output_observation_id` and overload its value with event-occurrence IDs: rejected because the field name asserts the wrong entity type.
- Add a separate event-only output field or ProcessingRun subtype: rejected as unnecessary duplication and a larger type surface.
- Add a generic graph/entity framework: rejected as outside this bounded correction.
- Rename the field to `output_entity_id: InstanceIdentifier` and validate the exact output edge: adopted.
DECISION=Rename `ProcessingRun.output_observation_id` to `output_entity_id`. The existing `InstanceIdentifier.instance_type` is sufficient type metadata: measurement outputs use `instance_type=observation`, while CMJ event outputs use `instance_type=event-occurrence`. `Provenance` requires exactly one `PRODUCED` edge from each processing run to its declared output entity. Observation and event constructors additionally enforce their respective identifier types and exact processing-run linkage.
RATIONALE=The renamed field states only the generic fact shared by all current processing outputs. The identifier already carries the concrete instance type, so a second output-kind field would duplicate authority and create disagreement risk. Requiring the declared output edge preserves lineage strength and rejects forged or stale output linkage.
MIGRATION_EFFECT=All runtime consumers, constructors, validators, tests, and public helper keyword arguments use `output_entity_id`. No stale semantic alias is retained. Existing in-memory ProcessingRun construction must be updated. Existing canonical payloads containing the old field are not silently reinterpreted.
SERIALIZATION_EFFECT=The current canonical serialization version is 3. The v2 wire contract is not accepted under the strict version gate; no migration reader or backwards-compatibility claim is provided. The output-field rename and the RES45 weighing-field correction therefore require deliberate re-materialization of affected canonical JSON, canonical object hashes, canonical signal digests, hash-derived identifiers, and refusal identifiers. The v3 payload uses `output_entity_id`.
ASSUMPTIONS=Every current processing run has one intended concrete output entity and its producer constructs the corresponding `PRODUCED` edge. `InstanceIdentifier.instance_type` remains the authoritative discriminator for the currently registered observation and event-occurrence entities.
LIMITATIONS=This decision does not define a general entity ontology, graph traversal API, output registry, storage schema, or future event families. It does not authorize mechanics or alter RES-36 event scientific conclusions.
IMPLEMENTATION=`src/dynamislm/provenance/models.py`; `src/dynamislm/measurement/observation.py`; `src/dynamislm/measurement/cmj/events.py`; `src/dynamislm/measurement/cmj/weighing.py`.
TESTS=`tests/test_kernel.py`: typed observation output, v3 public wire field, prior-v2 rejection, and forged output-linkage rejection. `tests/test_cmj.py`: event-occurrence output type, event provenance roundtrip, mass/weight provenance, and alternate-event lineage preservation.
VERSION=RES45-P1D1-1.0.0
