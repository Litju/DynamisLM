# DynamisLM

DynamisLM is a compact specialized reasoning-LM research project for elite men's senior first-team top-division professional association-football performance science, backed by deterministic Python scientific authority.

The project is not an AI coach and does not currently ship a trained DynamisLM checkpoint. Its scientific contract is deliberately split:

- The language-model layer may resolve terminology, protocols, measurement identity, comparability intent, analysis class, evidence scope, interpretation, and refusal.
- Registered deterministic Python software is the authority for equations, arithmetic, units, signal processing, event/phase detection, metric derivation, statistics, uncertainty, thresholds, and registered comparability adjudication.
- If a required numerical operation is not registered, the correct result is `COMPUTATION_NOT_REGISTERED`; the language model must not become an implicit calculator.

## Scientific world

The V2 scientific world has three coupled domains:

- Performance testing;
- external load / exposure;
- longitudinal football context.

### Performance testing

The Performance Testing domain preserves twelve test families:

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

These twelve families are the Performance Testing scope, not the whole DynamisLM scientific world. V2's canonical empirical target population is:

```text
SEX = MALE
AGE_CLASS = SENIOR
SPORT = ASSOCIATION_FOOTBALL
PROFESSIONAL_STATUS = PROFESSIONAL
SQUAD_LEVEL = FIRST_TEAM
COMPETITION_LEVEL = TOP_DOMESTIC_DIVISION
```

Women, academy/youth/U23, university, amateur/semi-professional, lower-division, futsal, rugby, other-sport, generic trained-adult and unseparable mixed cohorts are noncanonical empirical target populations. They may still provide explicitly classified indirect measurement evidence for population-independent mechanics, metrology, signal processing, statistics, device behavior and related methods; they do not establish canonical football priors, norms or thresholds.

### External load / exposure

This domain covers GNSS/GPS, optical tracking, inertial and vendor-derived measures, match/training exposure, total/relative distance, speed-zone metrics, HSR, sprint, acceleration/deceleration and provider/method/threshold identity.

### Longitudinal football context

This domain covers athlete, first-team squad, club/team, competition, season, training, match, testing session, match exposure, training exposure, microcycle, match-day-relative context and multi-device/multi-source longitudinal history.

The fundamental scientific object is:

```text
ScientificMeasurementObservation
    = ObservationContext
    + MeasurementIdentity
    + MeasurementResult
    + Provenance
```

The language-model/Python authority split and the distinction between Knowledge Scope, Computational Authority Scope and Claim Authority Scope remain binding. ScientificMeasurementObservation is the unit of typed scientific meaning, not a naked label/value pair.

## Current engine status

CMJ is no longer merely the next authorized unit. The repository contains substantial CMJ authority through RES-50, including:

- acquisition identity;
- signal validation;
- weighing/system mass;
- events;
- net force / impulse;
- COM mechanics;
- jump-height estimators;
- phase system;
- trial selection;
- session aggregation;
- comparability;
- refusal;
- provenance;
- serialization and ranking authority.

Additional CMJ force, power, RFD, RSI-mod and asymmetry completion work belongs downstream under RES-65. No metric is implied here beyond what the existing registered implementation and tests establish.

RES-75 hosted CI and repository governance is sealed. RES-63 implements the
canonical empirical ingestion boundary; real source bytes and full canonical
tables remain outside Git under `~/data/dynamislm`. Empirical data use for
model training remains blocked by `MODEL_TRAINING_USE=NOT_AUTHORIZED_BY_RES63`.

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

The current V2 and historical architecture documents are curated in [`docs/architecture`](docs/architecture/README.md). Project-specific operational guardrails are versioned in [`skills`](skills/README.md).

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

The current executable program is defined by the canonical Linear sequence:

```text
RES-59 → RES-60 → RES-61 → RES-62 → RES-63 → RES-64...RES-70 → RES-71
```

RES-59 re-seals the V2 scientific constitution; RES-60 through RES-63 establish typed population, football-world, longitudinal-record and canonical-dataset authority; RES-64...RES-70 expand deterministic scientific engine coverage; RES-71 is the Scientific Engine Qualification Gate. Project control remains in Linear; this repository records executable code and curated authority documents.

No operational model, inference, baseline-inference benchmark, paid GPU qualification, CPT/DAPT, SFT/PEFT, RLVR/GRPO or scaling work may begin before RES-71 records `SCIENTIFIC_ENGINE_GATE = PASS`. Candidate-model research notes are downstream planning only; no model is shipped here.

## Current limitations

- No trained checkpoint, model weights, corpus, database, API, frontend, GPU runtime, or deployment is included.
- The other performance-test families, external-load/exposure engine and scientific-engine qualification remain downstream work in the RES-64→RES-71 sequence; RES-63 dataset qualification is limited to its current ingestion boundary.
- The current CMJ implementation is not a complete CMJ science program; additional force, power, RFD, RSI-mod and asymmetry methods remain downstream under RES-65.
- The generic kernel and CMJ vertical slice represent registered contracts and provenance; they are not a complete persistence layer or clinical/return-to-play authority.
- Comparability without a registered deterministic rule remains explicitly unresolved/insufficient.

## License

Copyright 2026 Julio Rodriguez and contributors. Licensed under the [GNU Affero General Public License, version 3 only](LICENSE).
