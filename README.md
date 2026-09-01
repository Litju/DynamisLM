# DynamisLM

DynamisLM is a research-grade language-model project for scientific reasoning over longitudinal, multi-device athlete-performance measurements in trained or competitive adult non-clinical team-sport athletes.

The project is not an AI coach and does not currently ship a trained DynamisLM checkpoint. Its scientific contract is deliberately split:

- The language-model layer may resolve terminology, protocols, measurement identity, comparability intent, analysis class, evidence scope, interpretation, and refusal.
- Registered deterministic Python software is the authority for equations, arithmetic, units, signal processing, event/phase detection, metric derivation, statistics, uncertainty, thresholds, and registered comparability adjudication.
- If a required numerical operation is not registered, the correct result is `COMPUTATION_NOT_REGISTERED`; the language model must not become an implicit calculator.

## Scope

The fixed knowledge domain contains exactly twelve test families:

1. Countermovement Jump (CMJ)
2. Drop Jump (DJ)
3. Isometric Mid-Thigh Pull (IMTP)
4. Squat / Squat Velocity-Based Testing
5. Bench Press / Bench Press Velocity-Based Testing
6. Bench Press Throw
7. Medicine-Ball Throw Testing
8. Short Linear Sprint / Acceleration Testing
9. Maximum Sprint Velocity / High-Speed Sprint Testing
10. 505 Change-of-Direction Testing
11. 30–15 Intermittent Fitness Test
12. Repeated-Sprint Testing / RSA

The fundamental scientific object is:

```text
ScientificMeasurementObservation
    = ObservationContext
    + MeasurementIdentity
    + MeasurementResult
    + Provenance
```

The current status is **P1 scientific-kernel implementation**: generic contracts and invariants are being established before test-family vertical slices. CMJ is the next authorized unit, but its equations, events, thresholds, and method choices are not implemented here.

## Architecture

```text
Question + measurement context
            ↓
      semantic reasoning
            ↓
  typed analysis/comparison request
            ↓
 deterministic Python authority
            ↓
 structured result + provenance
            ↓
 bounded interpretation or refusal
```

The sealed P0 documents are curated in [`docs/architecture`](docs/architecture/README.md). Project-specific operational guardrails are versioned in [`skills`](skills/README.md).

## Install and test

Python 3.12 and [uv](https://docs.astral.sh/uv/) are required. From a Linux-native checkout:

```bash
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest
```

The runtime kernel uses only the Python standard library. Development tools are locked in `uv.lock`.

## Licensing and artifacts

The source code is `AGPL-3.0-only`. Model weights and adapters are license-deferred until an upstream base-model license is selected and reviewed. Datasets and corpora remain licensed by their individual sources and provenance. Project name, logo, and branding rights are separate from software copyright. See [NOTICE.md](NOTICE.md), [CONTRIBUTING.md](CONTRIBUTING.md), and [SECURITY.md](SECURITY.md).

## Roadmap

The current research sequence is defined by the canonical Linear program: P1 generic ontology/kernel, then independently researched vertical measurement slices, deterministic scientific engine work, evaluation, licensed data, model capability, and usefulness validation. Project control remains in Linear; this repository records executable code and sealed authority documents.

## Current limitations

- No trained checkpoint, model weights, corpus, database, API, frontend, GPU runtime, or deployment is included.
- P1A does not enumerate the twelve-family ontology or implement test-specific equations, signal processing, thresholds, reliability models, or bridges.
- The generic kernel represents contracts and provenance; it is not a complete persistence layer or clinical/return-to-play authority.
- Comparability without a registered deterministic rule remains explicitly unresolved/insufficient.

## License

Copyright 2026 Julio Rodriguez and contributors. Licensed under the [GNU Affero General Public License, version 3 only](LICENSE).
