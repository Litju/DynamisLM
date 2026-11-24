"""Reconstruct and bind the preregistered exposed D0 sample."""

from __future__ import annotations

import argparse
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

from scripts import a02_v3_contract as v3
from scripts import a02_v3_decision as decision
from scripts.a02_v3_preflight import TOKENIZER_DIR, load_pinned_tokenizer
from scripts.a03_model_core import tokens_sha256 as tokens_sha256

STATIC_SHA256 = "6f7d66fce2d48c6d76bef1d307ee3537b0d182258e7e9261374cd97be40d1cfe"
CHECKPOINT_SHA256 = "20f914e836df3c14a34240769b8dda28360d96ebc8fbedb83685cd5963686ec8"
ARMS = ("N", "C1")


def rank(example: dict[str, Any]) -> str:
    return v3.sha256(f"A03-D0-V1/{decision.example_id(example)}".encode())


def select(examples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    families: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for example in examples:
        families[example["family"]].append(example)
    if len(families) != 14 or any(len(group) < 3 for group in families.values()):
        raise ValueError("D0 requires three examples from each of 14 historical families")
    if len({decision.example_id(example) for example in examples}) != len(examples):
        raise ValueError("duplicate historical example ID")
    return [
        example for family in sorted(families) for example in sorted(families[family], key=rank)[:3]
    ]


def inputs(tokenizer: Any) -> list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]:
    examples = select(decision.heldout_examples(decision.load_protocol()))
    rng = random.Random(741132)
    rows = []
    for example in examples:
        request = example["request"]
        prompt = v3.build_action_prompt(tokenizer, request)
        rows.append(
            (
                {
                    "example_id": decision.example_id(example),
                    "family": example["family"],
                    "rank_sha256": rank(example),
                    "request_sha256": decision.request_sha256(request),
                    "rendered_prompt_sha256": prompt["rendered_prompt_sha256"],
                    "prompt_token_ids_sha256": tokens_sha256(prompt["prompt_token_ids"]),
                    "prompt_tokens": len(prompt["prompt_token_ids"]),
                    "arm_order": rng.sample(ARMS, len(ARMS)),
                },
                example,
                prompt,
            )
        )
    return rows


def seal(tokenizer: Any, static: bytes) -> dict[str, Any]:
    if v3.sha256(static) != STATIC_SHA256:
        raise ValueError("frozen D0 static receipt hash differs")
    receipt = v3.json_object(static.decode())
    if receipt["checkpoint_sha256"] != CHECKPOINT_SHA256:
        raise ValueError("historical aggregate checkpoint identity differs")
    historical = {row["example_id"]: row for row in receipt["rows"]}
    items = []
    for row, _, _ in inputs(tokenizer):
        previous = historical[row["example_id"]]
        if row["family"] != previous["family"] or not previous["tokens_accepted"]:
            raise ValueError("static receipt does not bind the selected example")
        items.append(
            {
                **row,
                "raw_output_sha256": v3.sha256(previous["raw_output"].encode()),
                "generated_token_ids_sha256": previous["recorded_token_digest"],
            }
        )
    return {
        "schema": "DYNAMISLM_A03_D0_SAMPLE_V1",
        "historical_protocol_sha256": decision.protocol_sha256(),
        "historical_checkpoint_sha256": CHECKPOINT_SHA256,
        "historical_static_receipt_sha256": STATIC_SHA256,
        "items": items,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("static", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--tokenizer", type=Path, default=TOKENIZER_DIR)
    args = parser.parse_args()
    data = seal(load_pinned_tokenizer(args.tokenizer), args.static.read_bytes())
    with args.output.open("x", encoding="utf-8") as handle:
        handle.write(v3.canonical(data) + "\n")


if __name__ == "__main__":
    main()
