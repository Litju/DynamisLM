# Contributing to DynamisLM

Contributions should preserve the sealed P0 scientific contracts and keep numerical authority in registered deterministic Python operations.

For a scientific change, record the following when applicable:

- the scientific question;
- the evidence or decision record;
- the stable method and measurement-identity definition;
- the implementation and tests;
- versioning and deterministic-serialization implications;
- provenance and reprocessing implications;
- comparability and refusal implications.

An undocumented metric-definition change is not a refactor. A new protocol, device, estimator, or method normally receives a distinct identity or rule rather than silently changing an existing one.

## Development checks

Use Python 3.12 and uv. Before opening a pull request, run:

```bash
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest
```

Do not add model weights, datasets, corpus shards, credentials, or generated training artifacts to Git. Keep artifact licenses and provenance separate from the AGPL-licensed source tree.
