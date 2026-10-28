# RES-541 CPU request-contract boundary

`scripts.request_guard.evaluate` is an opt-in experimental CPU adapter around
the existing frozen A0 scientific execution path. It does not modify or protect
the historical A0/A0.1 entry points. No model or GPU call is made.

## Trusted origin

An operator-controlled issuer independently records and confirms the request's
structured meaning, including every objective. It issues a `Requirements` record
with version `RES541_REQUEST_REQUIREMENTS_V1` and HMAC-SHA256 over UTF-8 JSON from
`dataclasses.asdict(requirements)`, sorted keys, compact separators, no NaN.
The detached signature is lowercase hexadecimal. Issuance is deliberately absent
from the adapter: never sign a model proposal automatically.

The issuer identifier and a secret verification key of at least 32 bytes must
come from trusted application configuration, outside the proposal payload and
outside Git. An attacker must not control these arguments. This is a shared-key
operator attestation, not a user signature, proof of human confirmation, or proof
of language understanding. The issuer owns the meaning and completeness
attestation; a confirmation reference alone grants no trust. An unconfigured
issuer/key, missing confirmation, unresolved requirements or expired contract
must stop execution. There is no real operator key or issuance integration in
this repository; test keys and confirmations are explicitly synthetic.

## Bounded ontology and binding

Only synthetic development requests at ATHLETE_WITHIN / WITHIN_ATHLETE scope
are supported. Each objective has a unique ID and an explicit `ModelIntent`:
registered analysis class, baseline/follow-up roles, measurement claim axis,
relationship claim axis, and EXECUTE (submission for scientific authorization).
Null means that the issuer deliberately excludes that axis; an unknown axis,
ambiguous objective, prediction, unsupported target or unresolved objective
inventory must be represented by nonempty `unknowns`, not silently mapped to
null. `complete=True` attests the entire objective inventory, not just the subset
the model proposed. These are issuer obligations, not text-derived assertions.

The context digest binds exact request text and ID, current Git revision,
adapter source bytes, canonical support hash and the separately stored role to
entry-ID mapping. Changing any bound input requires a newly issued contract.
The context must reproduce from the existing deterministic synthetic case
constructor; arbitrary externally supplied scientific support is rejected.
This does not prove that an operator's input values originated synthetically.
Frozen scientific source is checked before execution. Requirements have explicit
issue/expiry times, evaluated against the trusted host clock; they may be reused
within that interval only with exactly matching bindings. This is not a one-time
authorization or an anti-replay service.

## Dispatch and results

Supply the context, signed requirements and a tuple of `(objective_id, raw_json)`
proposals to `evaluate`, with the configured issuer/key as keyword arguments.
The entire batch is checked for missing, duplicate or extra objectives and exact
typed agreement before any analysis authorization or calculation. A typed model
REFUSE is a contract rejection, never a canonical scientific refusal.

Accepted proposals use the original `_evaluate` implementation with only its
evaluation-only oracle replaced by a fixed non-execution sentinel in a private
function namespace. The scoring field is removed. Fixture expectations never
enter runtime authorization; canonical RES-69/70 calls remain unchanged.

Every objective retains its own scientific outcome. Eligible descriptive
computation may precede refusal of a faithfully preserved higher-level claim.
If separately requested numerical and causal objectives produce mixed outcomes,
the aggregate is PARTIALLY_REFUSED, never RESULT. The existing execution path
withholds numbers for the individual objective whose higher claim is refused.

Rejected batches return `RES541_REQUEST_CONTRACT_REJECTED`, the failure stage
(AUTHORITY, CONTEXT or PROPOSALS), and no objective
results; this orchestration refusal has no RES-70 authority. Accepted batches
return requirement/context digests, issuer/confirmation provenance, objective IDs,
raw proposal digests and the original scientific results and authority hashes.
The caller must retain the signed contract alongside this receipt. Evaluate
semantic consistency, analysis eligibility, computation, claim disposition and
response safety separately. A VERIFIED guard is not scientific success.

No unrestricted natural-language semantics are established. Without an actual
trusted issuer independently confirming all requirements, the adapter remains
unqualified for live use and must fail closed. Arbitrary Python execution or a
compromised issuer/host is outside this boundary; HMAC is not process isolation.
