"""CPU preflight for the prospective V3 contract on the pinned tokenizer (RES-541).

Loads no weights and allocates no GPU. For every exposed case it records prompt tokens, the
native gold action's token count, the constrained gold path's joint-encoded token count and
the constrained scorer-call bound. It also re-runs
the gold-derivability audit and the oracle scoring ceiling.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from scripts import a02_v3_constrained as constrained
from scripts import a02_v3_contract as v3
from scripts import a02_v3_gold as gold
from scripts import a02_v3_score as score

E_ROOT = Path("/mnt/e/DynamisLM-A0").resolve()
TOKENIZER_DIR = E_ROOT / "a01/tokenizer"
SCHEMA = "RES541_A02_V3_CPU_PREFLIGHT_V1"


def build_preflight(tokenizer: Any) -> dict[str, Any]:
    profile = v3.load_profile()
    cases = score._cases()
    audit = gold.audit_exposed_cases()

    def encode(text: str) -> list[int]:
        ids: list[int] = tokenizer.encode(text, add_special_tokens=False)
        return ids

    rows = []
    for case_id in profile["case_ids"]:
        request = cases[case_id]["request"]
        expected = gold.derive_gold(request)["action"]
        prompt = v3.build_action_prompt(tokenizer, request)
        native = v3.format_action(expected)
        path = constrained.decode(
            request=request,
            prompt_ids=prompt["prompt_token_ids"],
            encode=encode,
            chooser=constrained.target_chooser(expected),
        )
        rows.append(
            {
                "case_id": case_id,
                "prompt_tokens": prompt["prompt_tokens"],
                "rendered_prompt_sha256": prompt["rendered_prompt_sha256"],
                "gold_native_action_tokens": len(encode(native)) + 1,
                "constrained_gold_tokens": len(path["token_ids"]),
                "constrained_emitted_ids_are_joint_encoding": path["token_ids"]
                == encode(path["text"]),
                "constrained_max_scorer_calls": constrained.max_scorer_calls(request),
                "oracle_exact": score.score_case(case_id, native)["intent"]["exact"],
            }
        )
    return {
        "schema": SCHEMA,
        "profile_sha256": v3.sha256(v3.PROFILE_PATH.read_bytes()),
        "tokenizer_files": profile["tokenizer"]["files"],
        "gold_derivable": audit["derivable"],
        "cases": rows,
        "max_prompt_tokens": max(r["prompt_tokens"] for r in rows),
        "max_gold_native_action_tokens": max(r["gold_native_action_tokens"] for r in rows),
        "max_constrained_scorer_calls": max(r["constrained_max_scorer_calls"] for r in rows),
        "max_constrained_gold_tokens": max(r["constrained_gold_tokens"] for r in rows),
        "oracle_exact": {
            "numerator": sum(r["oracle_exact"] for r in rows),
            "denominator": len(rows),
        },
        "gpu_allocated": False,
        "weights_loaded": False,
    }


def load_pinned_tokenizer(path: Path = TOKENIZER_DIR) -> Any:
    for name, digest in v3.load_profile()["tokenizer"]["files"].items():
        if v3.sha256((path / name).read_bytes()) != digest:
            raise ValueError(f"pinned tokenizer file differs: {name}")
    from transformers import AutoTokenizer  # type: ignore[import-not-found]

    return AutoTokenizer.from_pretrained(str(path), local_files_only=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = build_preflight(load_pinned_tokenizer())
    data = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
    if args.output is None:
        print(data.decode(), end="")
        return 0
    if not args.output.resolve().is_relative_to(E_ROOT):
        raise ValueError("V3 preflight receipts are written under E:")
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    print(v3.sha256(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
