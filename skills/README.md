# DynamisLM project skills

These nine `SKILL.md` files are the version-controlled source of the project's operational guardrails. They are intentionally concise interfaces to the canonical architecture, not replacement architecture documents.

The bootstrap host exposes static skills through user-global roots (`$HOME/.codex/skills` and `$HOME/.agents/skills`); no repository-local automatic skill discovery mechanism was present in the preflight. The installed copies on the bootstrap host are mirrored from these files under `$HOME/.codex/skills/dynamislm-*`. Future Luna/Codex sessions should load a skill by its exact name or explicit path and verify that the loaded copy matches this directory. A repository checkout alone must not be described as automatic discovery.

The nine initial skills are:

- `dynamislm-scientific-constitution`
- `dynamislm-measurement-model`
- `dynamislm-authority-boundary`
- `dynamislm-provenance`
- `dynamislm-comparability`
- `dynamislm-refusal-claims`
- `dynamislm-evidence-decision`
- `dynamislm-eval`
- `dynamislm-seal`
