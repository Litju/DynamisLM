"""CPU tokenizer preflight for the prospective RES-541 A0.2 V2 development profile."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from scripts import a02_dev_engine, a02_dev_protocol, a02_experiment

ROOT = Path(__file__).resolve().parents[1]
E_ROOT = Path("/mnt/e/DynamisLM-A0").resolve()
TOKENIZER_DIR = E_ROOT / "a01/tokenizer"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_preflight(
    tokenizer: Any,
    *,
    source_revision: str = "CPU_PREFLIGHT_ONLY",
    source_tree: str = "CPU_PREFLIGHT_ONLY",
    working_tree_clean: bool = False,
) -> dict[str, Any]:
    profile = a02_dev_protocol.load_profile()
    cases = json.loads(a02_experiment.CASES_PATH.read_bytes())["cases"]
    case_map = {row["case_id"]: row for row in cases}
    decoding = profile["decoding"]
    rows = []
    for case_id in profile["case_ids"]:
        case = case_map[case_id]
        prompt = a02_dev_protocol.build_action_prompt(tokenizer, case["request"])
        if prompt["prompt_tokens"] > decoding["action_max_prompt_tokens"]:
            raise ValueError(f"V2 action prompt exceeds its bound: {case_id}")
        intent = a02_dev_protocol.expected_intent(case_id)
        action_text = a02_dev_protocol.format_intent(intent)
        output_tokens = len(tokenizer.encode(action_text, add_special_tokens=False)) + 1
        if output_tokens > decoding["action_max_new_tokens"]:
            raise ValueError(f"V2 expected action exceeds its output bound: {case_id}")
        replay = a02_dev_engine.execute_development_v2(
            case_id,
            action_text,
            f"a02-v2-preflight:{case_id}",
        )
        final_messages = a02_dev_protocol.build_final_messages(
            request_text=a02_experiment.final_request_text(case["request"]),
            action_text=action_text,
            event=replay["event"],
        )
        kwargs = {
            "enable_thinking": False,
            "strftime_now": a02_dev_protocol.ACTION_TEMPLATE_DATE.strftime,
        }
        final_ids = tokenizer.apply_chat_template(
            final_messages, tokenize=True, add_generation_prompt=True, **kwargs
        )
        final_rendered = tokenizer.apply_chat_template(
            final_messages, tokenize=False, add_generation_prompt=True, **kwargs
        )
        if tokenizer.encode(final_rendered, add_special_tokens=False) != final_ids:
            raise ValueError(f"V2 final prompt token IDs do not replay: {case_id}")
        if len(final_ids) > decoding["final_max_prompt_tokens"]:
            raise ValueError(f"V2 final prompt exceeds its bound: {case_id}")
        answer = a02_dev_protocol.render_validated_executor_event(replay["event"])
        rows.append(
            {
                "case_id": case_id,
                "request_sha256": case["request_sha256"],
                **prompt,
                "expected_action_output_tokens_including_eos": output_tokens,
                "action_output_token_limit": decoding["action_max_new_tokens"],
                "final_prompt": final_rendered,
                "final_prompt_sha256": sha256(final_rendered.encode()),
                "final_prompt_token_ids": final_ids,
                "final_prompt_token_ids_sha256": sha256(
                    a02_dev_protocol.canonical(final_ids).encode()
                ),
                "final_prompt_tokens": len(final_ids),
                "final_output_token_limit": decoding["final_max_new_tokens"],
                "deterministic_answer_sha256": sha256(answer.encode()),
            }
        )
    return {
        "schema": "RES541_A02_DEVELOPMENT_PREFLIGHT_V2",
        "status": "CPU_PREFLIGHT_COMPLETE_GPU_AUTHORIZATION_PENDING",
        "development_profile_sha256": sha256(a02_dev_protocol.PROFILE_PATH.read_bytes()),
        "case_manifest_sha256": sha256(a02_experiment.CASES_PATH.read_bytes()),
        "tokenizer_revision": profile["tokenizer"]["revision"],
        "tokenizer_files": profile["tokenizer"]["files"],
        "chat_template_sha256": sha256(tokenizer.chat_template.encode()),
        "source_revision": source_revision,
        "source_tree": source_tree,
        "working_tree_clean": working_tree_clean,
        "action_case_count": len(rows),
        "model_weights_loaded": False,
        "gpu_allocated": False,
        "cases": rows,
    }


def run(tokenizer_dir: Path = TOKENIZER_DIR, output: Path | None = None) -> dict[str, Any]:
    mount = subprocess.check_output(
        ["findmnt", "-n", "-o", "SOURCE", "--target", "/mnt/e"], text=True
    ).strip()
    if mount != "E:\\" or not Path("/mnt/e").is_mount():
        raise ValueError("Windows E: must be mounted at /mnt/e before V2 CPU preflight")
    tokenizer_dir = tokenizer_dir.resolve()
    if not tokenizer_dir.is_relative_to(E_ROOT) or not tokenizer_dir.is_dir():
        raise ValueError("pinned tokenizer must be read from /mnt/e/DynamisLM-A0")
    profile = a02_dev_protocol.load_profile()
    if any(not (tokenizer_dir / name).is_file() for name in profile["tokenizer"]["files"]):
        raise ValueError("pinned tokenizer snapshot is incomplete")
    assets = {
        name: sha256((tokenizer_dir / name).read_bytes()) for name in profile["tokenizer"]["files"]
    }
    if assets != profile["tokenizer"]["files"]:
        raise ValueError("pinned tokenizer assets differ from the V2 development profile")
    from transformers import AutoTokenizer  # type: ignore[import-not-found]

    tokenizer = AutoTokenizer.from_pretrained(
        tokenizer_dir, local_files_only=True, trust_remote_code=False, use_fast=True
    )
    if (
        sha256(tokenizer.chat_template.encode())
        != profile["tokenizer"]["files"]["chat_template.jinja"]
    ):
        raise ValueError("loaded SmolLM3 template differs from its profile pin")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True).strip()
    clean = not subprocess.check_output(
        ["git", "status", "--porcelain=v1"], cwd=ROOT, text=True
    ).strip()
    document = build_preflight(
        tokenizer,
        source_revision=revision,
        source_tree=tree,
        working_tree_clean=clean,
    )
    if output is None:
        output = E_ROOT / "a02" / f"development-preflight-v2-{revision}.json"
    output = output.resolve()
    if not output.is_relative_to(E_ROOT):
        raise ValueError("development preflight artifacts must remain under E:")
    output.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if output.exists():
        if output.read_text(encoding="utf-8") != content:
            raise ValueError("existing V2 preflight differs; refusing to overwrite it")
    else:
        output.write_text(content, encoding="utf-8")
    return {
        "path": str(output),
        "sha256": sha256(output.read_bytes()),
        "cases": len(document["cases"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tokenizer-dir", type=Path, default=TOKENIZER_DIR)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.tokenizer_dir, args.output), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
