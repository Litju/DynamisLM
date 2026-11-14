# A0.2 V2 development loop

V2 is prospective, synthetic-only development. It uses the existing ten new-case fixtures, does not rerun the paired historical cases, and does not alter V1 reports or prompts.

V2 records analysis class separately from every requested measurement and relationship claim. The causal and practical cases preserve their requested claim level for Python's canonical RES-70 decision; the composite case preserves both relationship levels for the application guard. This lets scoring measure model intent without granting the proposal scientific authority.

Run the CPU preflight at any time. It reads the pinned tokenizer from E:, loads no weights, and allocates no GPU:

```bash
.venv/bin/python -m scripts.a02_dev_preflight
```

The proposed campaign cap is 2.00 CU total, at most two T4 sessions, and 900 seconds per session. It is not authorized by this file. After the owner gives one interactive approval, record it once with:

```bash
.venv/bin/python -m scripts.a02_dev_execution authorize
```

Each later session uses the same cap automatically and does not ask for another phrase:

```bash
.venv/bin/python -m scripts.a02_dev_execution run
```

The controller binds the clean source, V2 profile, CPU preflight, quota snapshot, and one-time authorization. It consumes a session marker before allocation, monitors account usage against the campaign cap, and stops only the exact V2 session. This ten-case profile is single-use; no session is retried after model output or an external failure. A later experiment needs a new source-bound profile. The CPU scorer replays the downloaded report and records model intent, authority results, raw model finals, and deterministic rendered answers separately.

No model training, paid upgrade, retry, model-weight download to WSL, or change to the V1 scientific authority is part of this profile.

## Scope and session-004 outcome

The ten-case gate is a development harness. `execute_development_v2` admits only the frozen case IDs and requires byte-equality with the frozen expected intent before any execution. It is a test-oracle firewall, not a general scientific-request authorization system or a safety guarantee for arbitrary inputs. Guard refusals show containment, not model competence.

Session 004 completed eight of ten cases. The retained actions show that this profile's gold intents cannot be reached: no request exposes the required `observation-N` references. Six of the eight actions also contain scientific semantic errors. This profile is not to be rerun. A successor needs a repaired, gold-derivable contract. See `docs/decisions/RES541-DR-001-session-004-diagnosis-and-architecture.md` and `python -m scripts.a02_dev_forensics`.
