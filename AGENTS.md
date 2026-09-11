# DynamisLM agent contract

## Mission isolation

- Work only on the active Linear mission.
- One mission uses one branch and one PR.
- Do not mix unrelated cleanup or feature work into a mission PR.
- Review fixes for the same mission remain on its PR.

## Deterministic-first

- Everything mechanically derivable must be derived mechanically.
- Never replace deterministic verification with an AI assertion.
- Never change expected hashes, counts, outputs, or fixtures merely to obtain PASS.

## Scientific authority

- Scientific identities, formulas, units, thresholds, sign conventions, population scope, provenance, and comparability are authority-bearing.
- Fail closed when evidence is insufficient.
- Never broaden scientific claims silently.
- Provider-derived values must not become direct measurements by relabelling.

## Data

- Real empirical source bytes and real canonical rows remain outside Git unless an explicit mission authorizes otherwise.
- Synthetic fixtures must remain clearly synthetic and policy compliant.

## Serialization

- Serialization V3 and historical hashes remain stable unless a mission explicitly authorizes a change.

## Model work

- Dataset ingestion does not authorize model training.
- No GPU or model-training work without an explicit mission or gate.

## QA

- Run deterministic local QA before push.
- Tests should attempt to falsify contracts, including adversarial negative cases.
- Hosted CI is independent merge evidence.

## Review

- AI review is advisory reasoning, not deterministic authority.
- Verify review findings against the current head before changing code.
- Resolve or explicitly disposition blocking findings.
- Scientific, data, measurement, population, provenance, and comparability missions require final adversarial or scientific review before merge.
