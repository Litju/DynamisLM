# PerformanceScience-Eval V1 source screening protocol

## Scope

This is the RES-115 Phase A metadata and reusable-rights registry. It does not create benchmark cases, evidence spans, model inputs, or protected stores.

The scientific population authority is `SCIENTIFIC_CONSTITUTION_V2.md`: the canonical empirical target is elite men's senior first-team top-division professional association football. A vague `elite`, `professional`, or `soccer` label does not establish that identity. Non-target team-sport or athlete populations can be retained only when the article provides useful measurement, protocol, device, reliability, agreement, uncertainty, statistical, or method evidence; their scope remains explicitly indirect and cannot establish target-population norms or thresholds.

## Discovery and metadata screen

- Searches use only the ten targeted PubMed E-Utilities queries in `registries/performance_science_eval/search_plan.json`.
- Each stratum is relevance-ranked and capped at 150 PMID results for the initial sweep; this is not a PubMed or PMC baseline.
- PubMed metadata and abstracts are screened before any article full-text request. Abstract text is transient and is not copied into the public registry.
- A candidate must support at least one fixed PerformanceScience-Eval capability or family through test/protocol identity, measurement method, device behavior, reliability/error, validity/agreement, external-load definition, longitudinal design, population applicability, evidence extraction, or association/prediction interpretation.
- Training interventions or applied associations are included only where their measured outcomes, design, or claim limits provide a concrete source-backed evaluation use. Injury, clinical, supplement, readiness, or fatigue claims do not expand DynamisLM's scientific scope.
- Candidate tags are proposals mapped to the frozen RES-21 C01-C18 and F01-F14 vocabulary. They do not create benchmark cases or authority.

## Rights and retrieval gate

A candidate's article/version is eligible for retained full text only after all of the following pass from article-specific PMC OAI front matter and the PubMed record:

1. PMID, PMCID, DOI where present, and PMC version identity are consistent.
2. The actual article/version license is explicitly CC0 or CC BY; CC BY-SA, non-commercial, no-derivatives, publisher-only, unclear, or unverified terms are rejected for full-text benchmark use.
3. PubMed publication type and linked correction/retraction/expression-of-concern metadata do not indicate an unresolved integrity notice.
4. The article belongs to the reusable PMC open collection and has no embargo indicated at retrieval.
5. The source passes the scientific relevance and applicability screen.

Only after those checks pass is JATS XML requested from PMC OAI-PMH. The retained artifact is the article XML compressed with deterministic gzip. No PDF, figure/media asset, or supplement is requested. A failed post-retrieval identity, license, article-type, or integrity check deletes the transient response and rejects the source.

## Identity and applicability

- PMID, PMCID, DOI, article/version identity, retained artifact identity, and content hashes are separate recorded fields.
- The initial `source_family_id` is document-scoped. The registry does not infer that distinct papers share an athlete cohort or dataset; any such relationship must be resolved before future case allocation and split isolation.
- `DIRECT_TARGET_POPULATION_EVIDENCE` is used only when the article documents the required target clauses. Otherwise the record identifies a narrower indirect measurement role or remains unresolved.
- A retained source is not a canonical empirical athlete dataset and does not authorize training or any scientific claim by itself.
