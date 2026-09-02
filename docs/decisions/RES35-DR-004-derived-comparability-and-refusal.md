# RES35-DR-004

DECISION_ID=RES35-DR-004
STATUS=ADOPTED
QUESTION=When may RES-35 system-weight and system-mass observations be compared, and how should an unsupported comparison or body-mass interpretation be refused?
SCOPE=Claim-relative comparability of RES-35 derived observations and the boundary between supported-system quantities and BODY_MASS; no device bridge, biological reliability claim, or event-dependent comparison.
SOURCES=
- `docs/architecture/SCIENTIFIC_CONSTITUTION_V1.md`
- `docs/architecture/MEASUREMENT_DATA_PROVENANCE_V1.md`
- `docs/architecture/REASONING_CLAIMS_EVALUATION_V1.md`
- `docs/architecture/P1_EXECUTION_CONTRACT.md`
- `docs/decisions/RES35-DR-001-weighing-segment-and-system-weight.md`
- `docs/decisions/RES35-DR-002-total-supported-force-construction.md`
- `docs/decisions/RES35-DR-003-gravity-and-system-mass.md`
APPLICABILITY=The rule applies only after each candidate has a complete registered derived identity. It is a deterministic identity rule, not evidence that two devices, populations, protocols, or loading states are biologically interchangeable.
OPTIONS_CONSIDERED=
- Compare equal numeric values and units: rejected because the provenance architecture states that equal labels, units, and numbers do not establish equal scientific identity.
- Compare only the final registered operation: rejected because weighing selection, total-force construction, system definition, and gravity reference remain material.
- Treat all standard and local gravity references as equivalent: rejected because the reference contract is part of SYSTEM_MASS identity.
- Apply a claim-relative identity rule and return bridge/insufficient-information states: adopted.
DECISION=Register `CMJ_DERIVED_COMPARABILITY_RULE` version `1.0.0`. Compare protocol and supported-system construct, source acquisition/measuring-system semantics, acquisition arrangement and combination lineage, axis/frame/sign/unit, registered operation and estimator, method parameters excluding source-instance identifiers, processing version, and (for SYSTEM_MASS) the complete gravity parameters. A different weighing interval, estimator, total-force construction path, system definition/loading state, processing version, or gravity reference is not silently collapsed. Equal complete identities are `COMPARABLE`; known differences are `BRIDGE_VALIDATION_REQUIRED`; missing identity is `INSUFFICIENT_INFORMATION`; an explicitly requested transformation is `REQUIRES_TRANSFORMATION`.
REFUSAL=Map unresolved comparisons to `COMPARABILITY_UNESTABLISHED` while preserving independent observations. A BODY_MASS request is always refused in RES-35 with `BODY_MASS_CLAIM_UNSUPPORTED` / `COMPUTATION_NOT_REGISTERED`; no external-load metadata is subtracted and no body-mass value is emitted.
RATIONALE=Comparability belongs to the claim and the measurement history. A system mass derived with a conventional standard gravity and one derived with a supplied local value may be numerically close while retaining different reference identities. Likewise, a vendor-combined series and a DynamisLM bilateral sum are different processing histories.
ASSUMPTIONS=The candidate observations expose their registered identities and provenance; a future bridge may be introduced only as a separately registered method with evidence and applicability.
LIMITATIONS=No cross-device bridge, reliability threshold, uncertainty-based equivalence rule, or biological body-mass equivalence is adopted. `BRIDGE_VALIDATION_REQUIRED` is not a claim that a bridge exists.
REGISTRY_OBJECTS_AFFECTED=`CMJ_DERIVED_COMPARABILITY_RULE`; RES-35 comparability reason codes; `refusal_for_cmj_derived_comparability`; `BODY_MASS_CLAIM_UNSUPPORTED`.
IMPLEMENTATION=`src/dynamislm/measurement/cmj/weighing.py`; `src/dynamislm/comparability/models.py`; `src/dynamislm/refusal/models.py`.
TESTS=`tests/test_cmj.py`: equal-identity system-weight comparability, gravity-reference difference, segment identity difference, body-mass refusal, and provenance preservation.
VERSION=RES35-P1C-1.0.0
