# DynamisLM agent contract

## Mission isolation

- Work only on the active Linear mission.
- One mission uses one branch and one PR.
- Do not mix opportunistic cleanup into a mission PR.

## Deterministic-first

- Everything mechanically derivable must be derived mechanically.
- Never replace deterministic verification with an LLM assertion.
- Do not rewrite expected hashes or counts merely to make QA pass.

## Scientific authority

- Scientific identities, formulas, thresholds, units, sign conventions, population scope, provenance, and comparability are authority-bearing.
- Fail closed when evidence is insufficient.
- Do not silently broaden scientific claims.
- Provider-derived values must not be relabelled as direct measurements.

## Data

- Real empirical source bytes and real canonical rows remain outside Git unless a mission explicitly authorizes otherwise.
- Synthetic fixtures must remain clearly synthetic and repository-policy compliant.

## Serialization

- Serialization V3 and historical hashes must not change unless the mission explicitly authorizes that change.

## Model work

- Dataset ingestion does not imply model-training authorization.
- No GPU or model-training work without an explicit mission or gate.

## QA

- Run deterministic local QA before push.
- Treat tests as falsification attempts, including adversarial and negative tests.
- Hosted CI is independent merge evidence.

## Reviews

- CodeRabbit is an independent reviewer, not scientific truth.
- Resolve or explicitly disposition every blocking review finding.
- A clean AI review does not replace final adversarial or scientific review.
