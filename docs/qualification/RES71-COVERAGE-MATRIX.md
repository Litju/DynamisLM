# RES-71 V2 coverage matrix

`build_coverage_matrix()` returns the machine-readable version. Every row has
authoritative surfaces, registered operations (where applicable), unresolved
capabilities, provenance boundary, comparability boundary, claim boundary,
authority references and test paths. Validation keys supplied and canonical
rows by `domain` and requires exact frozen-dataclass equality before preserving
the existing domain and test-path checks.

| V2 domain | Status | Explicit boundary / unresolved surface |
|---|---|---|
| Population/source authority | QUALIFIED | Ambiguous/noncanonical populations quarantine; indirect evidence cannot mint target priors. |
| Football world/context | QUALIFIED | Match-day relation requires an identified target match; no nearest-match inference. |
| Ingestion/qualification | QUALIFIED | Raw bytes, license, schema, mapping, canonical artifact and replay lineage remain bound. |
| External load / GNSS / optical | QUALIFIED_WITH_EXPLICIT_DEFERRED | Hidden vendor algorithms and unresolved threshold/sampling semantics are observations/refusals, not reconstructed equations. |
| CMJ | QUALIFIED_WITH_EXPLICIT_DEFERRED | CMJ RFD and COM-displacement jump height remain deferred; estimator/event/phase identities remain distinct. |
| Strength / IMTP / VBT | QUALIFIED_WITH_EXPLICIT_DEFERRED | VBT MPV and terminal-velocity estimated 1RM are represented/refused; velocity loss is not fatigue. |
| Sprint / max velocity / COD / RSA / 30–15 IFT | QUALIFIED_WITH_EXPLICIT_DEFERRED | Acceleration, sustained maximum, 505 asymmetry and VIFT relabelling remain refused/deferred. |
| DJ / bench throw / medicine-ball throw | QUALIFIED_WITH_EXPLICIT_DEFERRED | DJ JH/CT differs from FT/CT; generic BPT/MBT power and norms are refused. |
| Longitudinal statistics / reliability / error | QUALIFIED_WITH_EXPLICIT_DEFERRED | Deferred ICC/SEM/MDC/CI/BA/repeated-measures methods are explicit; no generic meaningful-change authority. |
| Cross-source comparability | QUALIFIED_WITH_EXPLICIT_DEFERRED | Exact identities, context and registry hashes are required; no transitive or caller-minted bridge. |
| Analysis capability | QUALIFIED_WITH_EXPLICIT_DEFERRED | Missing prerequisites, wrong level, pseudoreplication and deferred between/cross-test models refuse. |
| Claim authority | QUALIFIED_WITH_EXPLICIT_DEFERRED | Ladder/causal level is enforced; practical, readiness, fatigue, injury and causal escalation refuse. |

“Qualified with explicit deferred” means the domain is covered by an
authoritative implementation/refusal contract; it does not claim that every
published method is implemented.

## Required upstream relationships

```text
population/source → football context → canonical record/lineage
       ↓                    ↓                    ↓
measurement identity → deterministic operation → statistical analysis
       ↓                    ↓                    ↓
comparability/evidence → claim authority → bounded result or refusal
```

No arrow permits a label, unit, correlation, provider output or LM proposal to
skip identity, provenance, comparability, analysis or claim prerequisites.
