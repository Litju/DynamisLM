# RES48-DR-001 — Flight-time V2 and registered loading authority

## DECISION_ID

`RES48-DR-001-flight-time-v2-and-registered-loading-authority`

## STATUS

`ADOPTED`

## QUESTION

How should the RES-47 flight-time applicability correction receive a distinct
scientific method identity, and how should loading applicability enter the
deterministic estimator without lexical interpretation of protocol text?

## PROBLEM

RES-47 added stable supported-system, mechanical-contract, and loading-
applicability prerequisites to the RES-38 flight-time method while retaining
the RES-38 estimator and operation identifiers. Its implementation also used
substring parsing of free-form `external_loading` metadata as scientific
authority. Both changes are material method changes and require explicit
versioned, registered authority.

## SOURCES

- RES-37 supported-system mechanics and `CMJMechanicalSystemContract`.
- RES-38 flight-time, comparability, and COM-displacement decisions.
- RES-46 qualified zero-velocity decision; unchanged and out of scope here.
- RES-47 flight-time ballistic system applicability decision.
- Linthorne (2001), *Analysis of standing vertical jumps using a force
  platform*, https://bura.brunel.ac.uk/handle/2438/1392.
- Xu, Turner, Comfort & Harry (2023), *A Systematic Review of the Different
  Calculation Methods for Measuring Jump Height During the Countermovement and
  Drop Jump Tests*, https://pmc.ncbi.nlm.nih.gov/articles/PMC10115716/.
- McMahon, Lake & Comfort (2022), *Identifying and reporting position-specific
  countermovement jump outcome and phase characteristics within rugby league*,
  https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0265999.

## HISTORICAL_V1

The exact pre-RES-47 RES-38 method is retained. Its equation, prerequisites,
assumptions, claim ceiling, and serialized parameter shape are not changed.

### V1_ESTIMATOR_ID

`dynamislm:estimator:cmj-flight-time-ballistic-jump-height-v1@1.0.0`

### V1_OPERATION_ID

`dynamislm:registered-operation:cmj-flight-time-ballistic-jump-height-v1@1.0.0`

### V1_ASSUMPTIONS

- `CMJ_BALLISTIC_VERTICAL_MOTION`
- `CMJ_TAKEOFF_LANDING_HEIGHT_EQUIVALENCE`
- `CMJ_NEGLIGIBLE_AIR_RESISTANCE`
- `CMJ_LOCAL_GRAVITY_APPLICABLE`

### V1_CLAIM_CEILING

Estimator-qualified supported-trial flight-time ballistic height; not
automatically anatomical athlete COM jump height. V1 is historical and is not
emitted by new authoritative computation.

## QUALIFIED_V2

V2 has distinct estimator and operation references with an actual
`ScientificIdentifier.version` of `2.0.0`. The arithmetic is unchanged:

```text
flight_time_s = landing.event_time_s - takeoff.event_time_s
height_m = gravity.value_m_per_s2 * flight_time_s**2 / 8
```

### V2_ESTIMATOR_ID

`dynamislm:estimator:cmj-flight-time-ballistic-jump-height-v2@2.0.0`

### V2_OPERATION_ID

`dynamislm:registered-operation:cmj-flight-time-ballistic-jump-height-v2@2.0.0`

### V2_ASSUMPTIONS

V2 carries the four historical assumptions plus:

- `CMJ_SUPPORTED_SYSTEM_STABLE`
- registered `CMJMechanicalSystemContract`
- registered closed flight-loading applicability

It still requires same-source RES-36 takeoff and landing, exact recorded
event-time subtraction, and explicit applicable local gravity.

### V2_CLAIM_CEILING

Estimator-qualified supported-trial ballistic flight-time height. A loaded
result describes the combined supported system and is never automatically an
athlete-only COM-height claim.

## LOADING_STATE_VOCABULARY

The closed registered vocabulary is:

- `UNLOADED`
- `STABLE_ATTACHED_SUPPORTED_LOAD`
- `NON_BALLISTIC_EXTERNAL_FORCE`
- `UNRESOLVED`

Unknown values fail typed construction/decoding. No unknown state defaults to
`UNLOADED`.

## SEMANTIC_RESOLUTION_BOUNDARY

```text
raw protocol metadata
    -> upstream semantic resolution/adjudication
    -> closed FlightLoadingState
    -> FlightBallisticApplicability
    -> deterministic V2 estimator
```

`CMJProtocolIdentity.external_loading.value` remains descriptive and
auditable. `FREE_TEXT_AUTHORITY=NONE`: no substring, keyword, regex, or text
classifier can authorize the estimate.

## APPLICABILITY_OBJECT

`FlightBallisticApplicability` is the narrow serializable prerequisite. It
preserves the closed loading state, exact source observation/signal/artifact/
acquisition and measurement-identity IDs, the complete source
`CMJProtocolIdentity`, exact `CMJMechanicalSystemContract`, registered
applicability decision, and a deterministic source binding digest.

## SOURCE_LINKAGE

V2 requires exact equality of the applicability object’s source IDs and
protocol identity with the takeoff, landing, and supplied source observation.
The applicability contract is the sole contract authority; independently
supplied mismatched contracts are refused. Matching labels or numeric values do
not establish linkage.

`UNLOADED` requires an authorized contract with
`includes_supported_external_load=False`. `STABLE_ATTACHED_SUPPORTED_LOAD`
requires an authorized stable contract with that field `True`. Both require
the gravity-only external-force model and stable composition. The two
non-authorizing states refuse V2 with the existing ballistic/unresolved
refusal taxonomy.

## SERIALIZATION_DECISION

`SERIALIZATION_VERSION=3` is retained. V2 uses a registered subclass of the
historical estimator-parameters type, so the wire marker distinguishes the
typed V2 payload while the historical base payload remains decodable.

### HISTORICAL_V1_PAYLOAD_POLICY

Accept only the exact pre-RES-47 V1 method and parameter semantics. It remains
V1 and is never upgraded. A V1 payload carrying V2 assumptions, a system
contract, or RES-47 applicability metadata is rejected.

### TRANSITIONAL_RES47_PAYLOAD_POLICY

Reject explicitly. A payload with the old V1 estimator/operation identity and
RES-47 stable-system/applicability semantics cannot be interpreted as either
canonical V1 or V2.

### V2_PAYLOAD_POLICY

New authoritative V2 payloads roundtrip with the actual V2 estimator/operation
identities, typed applicability object, loading state, contract, source
linkage, provenance, and exact arithmetic parameters. Canonical JSON and
hashes are deterministic.

### HASH_MIGRATION

None for historical V1 payloads. New V2 hashes intentionally differ because
the method identity and typed applicability are material serialized content.

## PROVENANCE_EFFECT

V2 provenance carries the V2 estimator and operation, RES-38/RES-47/RES-48
evidence chain, exact takeoff and landing events, source observation, local
gravity, mechanical contract, loading state, typed applicability, assumptions,
and processing-run parameters. The raw protocol text remains in source
identity metadata only.

## COMPARABILITY_EFFECT

V1 and V2 share the broad intended estimand but are not interchangeable;
comparison returns `BRIDGE_VALIDATION_REQUIRED`. Identical V2 material
dimensions may be `COMPARABLE`. Loading state, contract, protocol, event
methods, gravity, assumptions, and method version are material dimensions.

## REFUSAL_EFFECT

Missing typed applicability, unresolved/non-ballistic loading, state/contract
mismatch, and wrong source linkage block only the V2 flight-time claim. Valid
events and their descriptive recorded time difference, plus independent
takeoff-velocity results, remain describable. COM-displacement remains
`DEFERRED`.

## LIMITATIONS

The contract and loading state do not measure takeoff/landing height
equivalence, aerodynamic effects, or anatomical COM location. No event,
gravity, mechanics, takeoff-velocity, phase, or COM-displacement science is
redefined here.

## IMPLEMENTATION

Registry identities and closed loading references are in
`src/dynamislm/measurement/cmj/registry.py`. The typed applicability and V1/V2
flight-time path are in `src/dynamislm/measurement/cmj/jump_height.py`.

## TESTS

Tests cover historical V1 identity and assumptions, distinct V2 identifier
versions, V2-only emission, closed-state authorization/refusal, adversarial raw
text, exact source linkage, provenance, comparability, historical and
transitional v3 payloads, deterministic roundtrips/hashes, unchanged
flight-time arithmetic/local gravity/events, takeoff-velocity regression,
exact Xu metadata, COM-displacement deferral, and RES-39 non-implementation.

## VERSION

`RES48-P1F2-1.0.0`
