# RES-71 provenance and serialization qualification

## Identity and lineage invariants

The qualification accepts an output only when the owning family contract keeps
the following separable:

```text
ObservationContext + MeasurementIdentity + MeasurementResult + Provenance
```

Derived results must preserve source observation/artifact IDs, acquisition and
processing lineage, method/registry/software version, calculation-changing
parameters, units, value origin, quality/uncertainty status and evidence or
decision references. A method identity is not a method instance, and a provider
output is not silently converted into a DynamisLM direct measurement.

Reprocessing follows the sealed invariant:

```text
raw R + method v1 → D1
raw R + method v2 → D2
D2 does not overwrite D1
```

The RES-71 inventory requires provenance contracts for all 100 operations. The
RES-70 authority revalidates exact observation hashes and registry hashes at
comparability, analysis and claim intake. RES-63 remains the authority for raw
artifact, canonical-artifact and qualification lineage.

## Serialization

- Serialization V3 remains unchanged.
- Historical CMJ V1 flight-time results are replay-only and remain distinct
  from the current V2 method/version.
- Qualification contracts are registered with the existing canonical serializer
  and round-trip through `canonical_json` / `from_canonical_json`.
- The verifier manifest has a deterministic digest:
  `sha256:9807b6e0be63abd44135bc855a97d37775ef09763d25c0f7025f4395ab673af6`.
- Floating reference values carry explicit absolute/relative tolerance fields;
  nonfinite values are rejected by the typed reference contract and owning
  numerical operations.

## Evidence

The RES-71 tests cover serialization round-trip, canonical digest stability,
independent numerical gold values, finite/domain refusal, source/method
identity collision, historical/current method separation and safe refusal
states. Full repository QA is required again at the exact final head.
