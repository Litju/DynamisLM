"""Frozen A0.1 execution binding, shared by Python 3.12 science and Colab inference."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VERSION = "RES541_A01_EXECUTION_V1"
PROMPT_VERSION = "A0.1_PROMPT_V1"
PROMPT_SHA256 = "3a427cbddec385a60e2843f921d3b8a3e3d0b80af8167f12a71a4d07a5639362"
FREEZE_SHA256 = "923b39087168dc97431a3de9e00bd4c292b5d3308bc0be0e0660196bc8e5ed0d"
SUITES = {
    "a0_diagnostic": ("experiments/a0/cases.json", 16),
    "a01_controls": ("experiments/a01/controls-v2.json", 12),
}
DECODING = {
    "do_sample": False,
    "num_beams": 1,
    "max_new_tokens": 64,
    "max_prompt_tokens": 1024,
    "seed": 541,
}
LIMITS = {
    "gpu": "T4",
    "runtime_seconds": 900,
    "download_seconds": 120,
    "stop_seconds": 30,
    "session_verification_seconds": 30,
    "model_weight_bytes": 8 * 1024**3,
    "weight_dtype": "float16",
    "enable_thinking": False,
}
EOS = 128012


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def compact(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def frozen() -> dict[str, Any]:
    raw = (ROOT / "experiments/a01/freeze-v1.json").read_bytes()
    if digest(raw) != FREEZE_SHA256:
        raise ValueError("A0.1 freeze manifest changed")
    freeze: dict[str, Any] = json.loads(raw)
    for name, expected in freeze["files"].items():
        if digest((ROOT / name).read_bytes()) != expected:
            raise ValueError(f"frozen A0.1 asset changed: {name}")
    return freeze


def prompt() -> str:
    raw = (ROOT / "experiments/a01/system-prompt-v1.txt").read_bytes()
    if digest(raw) != PROMPT_SHA256:
        raise ValueError("A0.1 prompt SHA-256 mismatch")
    return raw.decode("utf-8")


def plan(suite: str, count: int) -> dict[str, Any]:
    freeze = frozen()
    if suite not in SUITES or type(count) is not int or count != SUITES[suite][1] or count > 16:
        raise ValueError("select exactly one frozen suite and its explicit case count (at most 16)")
    path, _ = SUITES[suite]
    return {
        "execution_version": VERSION,
        "suite": suite,
        "case_count": count,
        "source_revision": git("rev-parse", "HEAD"),
        "source_tree": git("rev-parse", "HEAD^{tree}"),
        "case_manifest_sha256": freeze["files"][path],
        "prompt_version": PROMPT_VERSION,
        "system_prompt_sha256": PROMPT_SHA256,
        "model_id": "HuggingFaceTB/SmolLM3-3B",
        "model_revision": freeze["model_revision"],
        "tokenizer_revision": freeze["model_revision"],
        "intent_schema": freeze["intent_schema"],
        "decoding": dict(DECODING),
        "limits": dict(LIMITS),
    }


def isolated_a0(name: str) -> ModuleType:
    """Adapt a private module instance; the original import and source remain untouched."""
    frozen()
    path = ROOT / "scripts" / (name + ".py")
    spec = importlib.util.spec_from_file_location("_a01_" + name, path)
    if spec is None or spec.loader is None:
        raise ValueError("cannot load the frozen A0 implementation")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bind_row(row: dict[str, Any], binding: dict[str, Any]) -> str:
    return digest(
        compact(
            {
                "binding": binding,
                "case_id": row["case_id"],
                "prompt_sha256": row["prompt_sha256"],
                "chat_template_date": row["chat_template_date"],
                "prompt_utc": row["prompt_utc"],
                "user_message_sha256": row["user_message_sha256"],
                "raw_sha256": digest(row["raw_text"].encode()),
                "generated_token_ids": row["generated_token_ids"],
            }
        ).encode()
    )


def validate_outputs(
    document: dict[str, Any],
    binding: dict[str, Any],
    messages: list[dict[str, str]],
    tokenizer: Any = None,
) -> None:
    if any(compact(document.get(key)) != compact(value) for key, value in binding.items()):
        raise ValueError("A0.1 output provenance mismatch")
    if (
        document.get("schema") != "RES541_A0_MODEL_OUTPUTS_V1"
        or document.get("status") != "COMPLETE"
    ):
        raise ValueError("A0.1 inference did not complete")
    runtime = document.get("runtime", {})
    if (
        compact(runtime.get("decoding")) != compact(DECODING)
        or runtime.get("weight_dtype") != "float16"
    ):
        raise ValueError("inference decoding or FP16 mismatch")
    if (
        "T4" not in str(runtime.get("gpu_name"))
        or runtime.get("compute_capability") != [7, 5]
        or type(runtime.get("total_vram_bytes")) is not int
        or runtime["total_vram_bytes"] < 12 * 1024**3
        or type(runtime.get("model_weight_bytes_from_revision_metadata")) is not int
        or not 0 < runtime["model_weight_bytes_from_revision_metadata"] <= 8 * 1024**3
    ):
        raise ValueError("recorded GPU or weight budget mismatch")
    rows = document.get("cases")
    if (
        not isinstance(rows, list)
        or len(rows) != len(messages)
        or [r.get("case_id") for r in rows] != [m["case_id"] for m in messages]
    ):
        raise ValueError("A0.1 output case IDs/order/count mismatch")
    for row, message in zip(rows, messages, strict=True):
        ids, generated = row.get("prompt_token_ids"), row.get("generated_token_ids")
        if (
            not isinstance(ids, list)
            or not ids
            or len(ids) > 1024
            or not isinstance(generated, list)
            or not 0 < len(generated) < 64
            or any(type(n) is not int or n < 0 for n in ids + generated)
            or generated[-1] != EOS
            or EOS in generated[:-1]
            or type(row.get("prompt_tokens")) is not int
            or row["prompt_tokens"] != len(ids)
            or type(row.get("generated_tokens")) is not int
            or row["generated_tokens"] != len(generated)
            or row.get("failure_category") is not None
        ):
            raise ValueError("A0.1 token evidence missing, failed or truncated")
        when = datetime.fromisoformat(row["prompt_utc"])
        if when.tzinfo != UTC or when.strftime("%d %B %Y") != row["chat_template_date"]:
            raise ValueError("chat-template date mismatch")
        if (
            row["prompt_sha256"] != digest(compact(ids).encode())
            or row["user_message_sha256"] != digest(message["user_message"].encode())
            or row["binding_sha256"] != bind_row(row, binding)
        ):
            raise ValueError("A0.1 per-case token/source binding mismatch")
        if tokenizer is not None:
            if (
                digest(tokenizer.chat_template.encode())
                != frozen()["tokenizer_files"]["chat_template.jinja"]
            ):
                raise ValueError("official chat template mismatch")
            actual = tokenizer.apply_chat_template(
                [
                    {"role": "system", "content": prompt()},
                    {"role": "user", "content": message["user_message"]},
                ],
                tokenize=True,
                add_generation_prompt=True,
                enable_thinking=False,
                strftime_now=when.strftime,
            )
            if (
                actual != ids
                or tokenizer.decode(generated, skip_special_tokens=True) != row["raw_text"]
            ):
                raise ValueError("actual tokenizer replay or raw generation mismatch")
