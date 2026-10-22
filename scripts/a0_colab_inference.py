"""Pinned, deterministic SmolLM3 intent inference on the confirmed Colab runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import resource as process_resource
import shutil
import sys
import time
from pathlib import Path
from typing import Any, cast

MODEL_ID = "HuggingFaceTB/SmolLM3-3B"
MODEL_REVISION = "a07cc9a04f16550a088caea529712d1d335b0ac1"
INTENT_SCHEMA = "RES541_A0_INTENT_V1"
PREPARED_SCHEMA = "RES541_A0_PREPARED_CASES_V1"
OUTPUT_SCHEMA = "RES541_A0_MODEL_OUTPUTS_V1"
MAX_CASES = 16
MAX_PROMPT_TOKENS = 1024
MAX_NEW_TOKENS = 64
MAX_MODEL_WEIGHT_BYTES = 8 * 1024**3
SEED = 541
EXECUTE_SHAPE = json.dumps(
    {
        "v": 1,
        "d": "EXECUTE",
        "a": "AnalysisClass enum value",
        "b": "BASELINE|FOLLOWUP|null",
        "f": "BASELINE|FOLLOWUP|null",
        "m": "MeasurementClaimLevel enum value|null",
        "r": "RelationshipClaimLevel enum value|null",
    },
    separators=(",", ":"),
)
REFUSE_SHAPE = json.dumps(
    {"v": 1, "d": "REFUSE", "x": "MISSING_EVIDENCE|UNSUPPORTED_ANALYSIS|CLAIM_EXCEEDS_EVIDENCE"},
    separators=(",", ":"),
)
SYSTEM_PROMPT = (
    "You are a typed scientific request parser. Do not calculate or answer the request.\n"
    "Return compact JSON only; do not add Markdown, spaces, or extra fields.\n"
    f"Version 1 execute shape: {EXECUTE_SHAPE}\n"
    f"Version 1 refuse shape: {REFUSE_SHAPE}\n"
    "Keys: a=analysis class, b=baseline role, f=follow-up role, m=measurement claim, "
    "r=relationship claim, x=refusal reason.\n"
    "For a computation, select the BASELINE and FOLLOWUP roles from the evidence. "
    "Use SCALAR_ABSOLUTE_CHANGE and NUMERICAL_CHANGE only for follow-up minus baseline. "
    "Use SCALAR_RELATIVE_CHANGE for percentages, WITHIN_ATHLETE_ASSOCIATION for association, "
    "CAUSAL_EVIDENCE for causality, and PRACTICAL_OR_DECISION_MEANINGFULNESS for practical "
    "decisions. Leave the unrelated claim axis null. Use REFUSE only when the request cannot "
    "be represented. Never return a computed number, advice, or explanation."
)


class TimingStreamer:
    """Small generate() streamer that times the first emitted token without printing it."""

    def __init__(self) -> None:
        self._prompt_seen = False
        self.first_token_at: float | None = None

    def put(self, value: Any) -> None:
        if not self._prompt_seen:
            self._prompt_seen = True
        elif self.first_token_at is None:
            self.first_token_at = time.perf_counter()

    def end(self) -> None:
        return


def _apply_chat_template(tokenizer: Any, messages: list[dict[str, str]]) -> Any:
    return tokenizer.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        return_dict=True,
        return_tensors="pt",
        enable_thinking=False,
    )


def _load_prepared(path: Path) -> list[dict[str, Any]]:
    document: object = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(document, dict)
        or document.get("schema") != PREPARED_SCHEMA
        or document.get("population") != "SYNTHETIC_DEVELOPMENT_ONLY"
        or not isinstance(document.get("cases"), list)
    ):
        raise ValueError("prepared A0 case file has an invalid schema or population scope")
    cases = document["cases"]
    if not 12 <= len(cases) <= MAX_CASES:
        raise ValueError("A0 inference case count is outside its fixed bound")
    if any(
        not isinstance(case, dict) or not isinstance(case.get("user_message"), str)
        for case in cases
    ):
        raise ValueError("prepared A0 cases contain an invalid user message")
    return cast(list[dict[str, Any]], cases)


def _package_versions() -> dict[str, str]:
    from importlib.metadata import version

    packages = (
        "accelerate",
        "certifi",
        "charset-normalizer",
        "filelock",
        "fsspec",
        "huggingface-hub",
        "idna",
        "Jinja2",
        "MarkupSafe",
        "numpy",
        "packaging",
        "psutil",
        "PyYAML",
        "regex",
        "requests",
        "tokenizers",
        "safetensors",
        "transformers",
        "tqdm",
        "typing_extensions",
        "urllib3",
    )
    return {name: version(name) for name in packages}


def run_inference(prepared_path: Path, output_path: Path) -> dict[str, object]:
    import torch  # type: ignore[import-not-found]
    from huggingface_hub import HfApi  # type: ignore[import-not-found]
    from transformers import AutoModelForCausalLM, AutoTokenizer  # type: ignore[import-not-found]

    cases = _load_prepared(prepared_path)
    packages = _package_versions()
    expected_packages = {
        "accelerate": "1.8.1",
        "certifi": "2025.6.15",
        "charset-normalizer": "3.4.2",
        "filelock": "3.18.0",
        "fsspec": "2025.5.1",
        "huggingface-hub": "0.33.4",
        "idna": "3.10",
        "Jinja2": "3.1.6",
        "MarkupSafe": "3.0.2",
        "numpy": "2.2.6",
        "packaging": "25.0",
        "psutil": "7.0.0",
        "PyYAML": "6.0.2",
        "regex": "2024.11.6",
        "requests": "2.32.4",
        "tokenizers": "0.21.1",
        "safetensors": "0.5.3",
        "transformers": "4.53.0",
        "tqdm": "4.67.1",
        "typing_extensions": "4.14.1",
        "urllib3": "2.5.0",
    }
    if packages != expected_packages:
        raise RuntimeError("pinned inference dependency versions do not match")
    if platform.python_version() != "3.13.15":
        raise RuntimeError("Colab Python version differs from the confirmed preflight")
    if str(torch.__version__) != "2.11.0+cu130":
        raise RuntimeError("Colab PyTorch version differs from the confirmed preflight")
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise RuntimeError("exactly one CUDA device is required")
    properties = torch.cuda.get_device_properties(0)
    capability = torch.cuda.get_device_capability(0)
    total_bytes = int(properties.total_memory)
    if "T4" not in properties.name or capability != (7, 5) or total_bytes < 12 * 1024**3:
        raise RuntimeError("GPU identity, compute capability, or VRAM differs from the T4 gate")
    free_bytes, _ = torch.cuda.mem_get_info(0)
    if free_bytes < 8 * 1024**3:
        raise RuntimeError("less than 8 GiB of free T4 memory is available before weight load")

    weight_info = HfApi().model_info(
        MODEL_ID,
        revision=MODEL_REVISION,
        files_metadata=True,
        token=False,
    )
    weight_files = tuple(
        sibling for sibling in weight_info.siblings if sibling.rfilename.endswith(".safetensors")
    )
    if not weight_files or any(sibling.size is None for sibling in weight_files):
        raise RuntimeError("pinned Safetensors sizes are unavailable before download")
    weight_bytes = sum(int(sibling.size) for sibling in weight_files if sibling.size is not None)
    if weight_bytes > MAX_MODEL_WEIGHT_BYTES:
        raise RuntimeError("pinned model weights exceed the 8 GiB download bound")
    cache_path = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    cache_path.mkdir(parents=True, exist_ok=True)
    free_disk_before_bytes = int(shutil.disk_usage(cache_path).free)
    if free_disk_before_bytes < weight_bytes + 2 * 1024**3:
        raise RuntimeError("free Colab disk is below the model download bound")

    tokenizer_started = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(
        MODEL_ID,
        revision=MODEL_REVISION,
        trust_remote_code=False,
        use_fast=True,
    )
    if tokenizer.eos_token_id is None:
        raise RuntimeError("pinned tokenizer has no EOS token")
    tokenizer_load_seconds = time.perf_counter() - tokenizer_started

    torch.manual_seed(SEED)
    torch.cuda.manual_seed_all(SEED)
    torch.cuda.reset_peak_memory_stats(0)
    model_started = time.perf_counter()
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID,
        revision=MODEL_REVISION,
        trust_remote_code=False,
        use_safetensors=True,
        torch_dtype=torch.float16,
        low_cpu_mem_usage=True,
        device_map={"": 0},
    )
    model.eval()
    if any(
        parameter.is_floating_point() and parameter.dtype is not torch.float16
        for parameter in model.parameters()
    ):
        raise RuntimeError("loaded model contains non-FP16 floating parameters")
    load_seconds = time.perf_counter() - model_started
    config = model.config
    model_config = {
        key: getattr(config, key, None)
        for key in (
            "model_type",
            "architectures",
            "max_position_embeddings",
            "num_hidden_layers",
            "hidden_size",
            "num_attention_heads",
            "num_key_value_heads",
            "vocab_size",
            "torch_dtype",
        )
    }
    if model_config["torch_dtype"] is not None:
        model_config["torch_dtype"] = str(model_config["torch_dtype"])

    generated: list[dict[str, object]] = []
    inference_started = time.perf_counter()
    stopped_after_gpu_failure = False
    for case in cases:
        case_id = case.get("case_id")
        message = case["user_message"]
        started = time.perf_counter()
        if stopped_after_gpu_failure:
            generated.append(
                {
                    "case_id": case_id,
                    "raw_text": "",
                    "prompt_sha256": None,
                    "prompt_tokens": 0,
                    "generated_tokens": 0,
                    "latency_ms": 0.0,
                    "first_token_latency_ms": None,
                    "failure_category": "SKIPPED_AFTER_GPU_FAILURE",
                }
            )
            continue
        try:
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": message},
            ]
            encoded = _apply_chat_template(tokenizer, messages)
            prompt_tokens = int(encoded["input_ids"].shape[-1])
            if prompt_tokens > MAX_PROMPT_TOKENS:
                raise ValueError("prompt exceeds the fixed token bound")
            prompt_token_ids = encoded["input_ids"][0].tolist()
            prompt_hash = hashlib.sha256(
                json.dumps(prompt_token_ids, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            input_ids = encoded["input_ids"].to("cuda:0")
            attention_mask = encoded["attention_mask"].to("cuda:0")
            streamer = TimingStreamer()
            with torch.inference_mode():
                sequences = model.generate(
                    input_ids=input_ids,
                    attention_mask=attention_mask,
                    do_sample=False,
                    num_beams=1,
                    num_return_sequences=1,
                    max_new_tokens=MAX_NEW_TOKENS,
                    use_cache=True,
                    pad_token_id=tokenizer.eos_token_id,
                    eos_token_id=tokenizer.eos_token_id,
                    streamer=streamer,
                )
            continuation = sequences[0, input_ids.shape[-1] :]
            raw_text = tokenizer.decode(continuation, skip_special_tokens=True).strip()
            generated_tokens = int(continuation.shape[-1])
            first_latency = (
                (streamer.first_token_at - started) * 1000
                if streamer.first_token_at is not None
                else None
            )
            generated.append(
                {
                    "case_id": case_id,
                    "raw_text": raw_text,
                    "prompt_sha256": prompt_hash,
                    "prompt_tokens": prompt_tokens,
                    "generated_tokens": generated_tokens,
                    "latency_ms": (time.perf_counter() - started) * 1000,
                    "first_token_latency_ms": first_latency,
                    "failure_category": None,
                }
            )
        except Exception as exc:
            is_cuda_oom = isinstance(exc, torch.cuda.OutOfMemoryError)
            generated.append(
                {
                    "case_id": case_id,
                    "raw_text": "",
                    "prompt_sha256": None,
                    "prompt_tokens": 0,
                    "generated_tokens": 0,
                    "latency_ms": (time.perf_counter() - started) * 1000,
                    "first_token_latency_ms": None,
                    "failure_category": "CUDA_OUT_OF_MEMORY" if is_cuda_oom else type(exc).__name__,
                }
            )
            if is_cuda_oom:
                stopped_after_gpu_failure = True
                torch.cuda.empty_cache()

    inference_seconds = time.perf_counter() - inference_started
    torch.cuda.synchronize(0)
    free_after_bytes, _ = torch.cuda.mem_get_info(0)
    document: dict[str, object] = {
        "schema": OUTPUT_SCHEMA,
        "status": "COMPLETE",
        "intent_schema": "RES541_A0_INTENT_V1",
        "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "packages": packages,
        "cases": generated,
        "runtime": {
            "python": platform.python_version(),
            "torch": str(torch.__version__),
            "torch_cuda_runtime": torch.version.cuda,
            "gpu_name": properties.name,
            "compute_capability": list(capability),
            "total_vram_bytes": total_bytes,
            "free_vram_before_model_bytes": int(free_bytes),
            "free_vram_after_inference_bytes": int(free_after_bytes),
            "model_weight_file_count": len(weight_files),
            "model_weight_bytes_from_revision_metadata": weight_bytes,
            "model_weight_files": [sibling.rfilename for sibling in weight_files],
            "model_config": model_config,
            "free_disk_before_weight_load_bytes": free_disk_before_bytes,
            "free_disk_after_inference_bytes": int(shutil.disk_usage(cache_path).free),
            "model_cache_bytes_delta": max(
                0,
                free_disk_before_bytes - int(shutil.disk_usage(cache_path).free),
            ),
            "peak_allocated_vram_bytes": int(torch.cuda.max_memory_allocated(0)),
            "peak_reserved_vram_bytes": int(torch.cuda.max_memory_reserved(0)),
            "model_load_seconds": load_seconds,
            "tokenizer_load_seconds": tokenizer_load_seconds,
            "generation_seconds": inference_seconds,
            "inference_process_peak_rss_bytes": int(
                process_resource.getrusage(process_resource.RUSAGE_SELF).ru_maxrss * 1024
            ),
            "weight_dtype": "float16",
            "decoding": {
                "do_sample": False,
                "num_beams": 1,
                "max_new_tokens": MAX_NEW_TOKENS,
                "max_prompt_tokens": MAX_PROMPT_TOKENS,
                "seed": SEED,
            },
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(output_path)
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared-cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        run_inference(args.prepared_cases, args.output)
    except Exception as exc:
        category = (
            "CUDA_OUT_OF_MEMORY" if type(exc).__name__ == "OutOfMemoryError" else type(exc).__name__
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(
                {
                    "schema": OUTPUT_SCHEMA,
                    "status": "NO_GO",
                    "intent_schema": "RES541_A0_INTENT_V1",
                    "model_id": MODEL_ID,
                    "model_revision": MODEL_REVISION,
                    "failure_category": category,
                    "cases": [],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"RES-541 A0 inference stopped: {category}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
