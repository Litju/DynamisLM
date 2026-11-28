"""A1 CPU rehearsal: exercise the whole pipeline with a deterministic stub model (RES-832).

This is the local falsification harness. It proves that the frozen cases, renderers, manifest,
runner, checkpoint chain, scorer, bootstrap and report all execute and that the contracts fail
closed. It uses a stub backend that emits a fixed, deterministic string per arm; the point is
engineering and contract verification, never scientific evidence.

The rehearsal is explicitly excluded from the science: its outputs are written under a rehearsal
root and are never read by the report generator as campaign evidence.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Any

from scripts import a02_v3_contract as v3
from scripts import a1_cases, a1_manifest, a1_run
from scripts import a1_representation as rep
from scripts.a03_model_runtime import Generation

ROOT = Path(__file__).resolve().parents[1]
REHEARSAL = ROOT / "experiments/a1/.rehearsal"


class StubBackend:
    """Deterministic, model-free generator used only for rehearsal and contract tests."""

    def __init__(self, behaviour: str = "gold") -> None:
        self.behaviour = behaviour
        self.tokenizer = None
        self.prompts: list[list[int]] = []

    def generate(
        self, arm: str, request: dict[str, Any], prompt: list[int], deadline: float
    ) -> Generation:
        self.prompts.append(prompt)
        if self.behaviour == "invalid":
            return Generation([1], "no tool call here", "MODEL_EOS")
        target = _match_case(request)
        text = v3.format_action(target) if target else v3.format_action(_no_action())
        return Generation(list(range(1, 6)), text, "MODEL_EOS")


def _no_action() -> dict[str, Any]:
    return {
        "analysis_class": v3.NONE,
        "observation_ids": [],
        "operation": v3.NONE,
        "target_claims": {"measurement": [], "relationship": []},
    }


def _match_case(request: dict[str, Any]) -> dict[str, Any] | None:
    """Rehearsal-only oracle: the gold of the case whose request round-trips exactly."""
    manifest = a1_cases.load_manifest()
    for case in manifest["cases"]:
        if rep.request_sha256(rep.request_for("R-op", case)) == rep.request_sha256(request):
            return a1_cases.gold_action(case)
        if rep.request_sha256(rep.request_for("R-hist", case)) == rep.request_sha256(request):
            return a1_cases.gold_action(case)
    return None


def _stub_prompt_ids(backend: Any, messages: list[dict[str, str]]) -> tuple[list[int], str]:
    digest = v3.sha256(v3.canonical(messages).encode())
    ids = [int(digest[index : index + 2], 16) for index in range(0, 60, 2)]
    return ids, "stub-rendered-prompt"


def use_stub_prompts() -> Any:
    """Swap the tokenizer-level prompt builder for the deterministic stub. Test hook only."""
    original = a1_run.prompt_ids
    a1_run.prompt_ids = _stub_prompt_ids

    def restore() -> None:
        a1_run.prompt_ids = original

    return restore


def rehearsal(root: Path | None = None, *, full: bool = False) -> dict[str, Any]:
    base = root if root is not None else REHEARSAL
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True)
    manifest = a1_manifest.load_manifest()
    conditions = [
        condition
        for condition in manifest["conditions"]
        if condition["role"] in {"PRINCIPAL_FACTORIAL", "DIAGNOSTIC"}
    ]
    original = a1_run.prompt_ids
    a1_run.prompt_ids = _stub_prompt_ids
    receipts = []
    try:
        backend = StubBackend()
        for condition in conditions if full else conditions[:2]:
            receipts.append(
                a1_run.run_arm(
                    backend,
                    condition,
                    identity={"stub": True},
                    root=base,
                    deadline_seconds=60.0,
                )
            )
    finally:
        a1_run.prompt_ids = original
    return {
        "arms": [receipt["arm"] for receipt in receipts],
        "committed": sum(receipt["committed"] for receipt in receipts),
        "complete": all(receipt["complete"] for receipt in receipts),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true", help="rehearse every principal condition")
    args = parser.parse_args()
    print(rehearsal(full=args.full))


if __name__ == "__main__":
    main()
