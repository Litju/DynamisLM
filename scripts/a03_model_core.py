"""Frozen D0 artifact pins and single-sequence FP32 generation."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

from scripts import a02_v3_contract as v3

EOS = 128012
MAX_NEW = 128
MIN_FREE_VRAM = 14 * 1024**3
MODEL_FILES = {
    "config.json": "c72b1031274ff4626e434d0019e88e95a767460135db9ee492eb80652b786af1",
    "generation_config.json": "3458d62b3f9654f4bbe285223b0f4e5a1e67cae61c92bb6aeaadf04468bf9e01",
    "model.safetensors.index.json": (
        "e3a7254c086c4a78f95ad5864f435d165ffed1ed8998326ce5107b4423c15b76"
    ),
    "model-00001-of-00002.safetensors": (
        "e5eed4113a925264c33e3cdf76cd9f547c06a207ef2270914a7274a2bf685ffd"
    ),
    "model-00002-of-00002.safetensors": (
        "6c3ad90646457295723e4da5ee8afac47006e20407b122df5174693dd8d68a43"
    ),
}
ADAPTER_FILES = {
    "adapter_config.json": "fd308f182471b62d50032f774b41c56895d3979b5ac522eb5fa7228d8bc57f6e",
    "adapter_model.safetensors": "7bda8c60c2e27206d60a41f7f454ecce721e46704e731b4f6c268d042572a6e7",
    "evaluation-binding.json": "da277638987032acad53243a65762787ddd3caf6804986a949a25048ccd25176",
    "metadata.json": "1f3bcf6abe549d855ad89d32d54b9040af4be66ee81f3115f9c308852d1d11a4",
}
RUNTIME = {
    "torch": "2.14.1+cu130",
    "transformers": "4.53.0",
    "peft": "0.16.0",
    "tokenizers": "0.21.1",
}


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_files(path: Path, files: dict[str, str]) -> None:
    for name, expected in files.items():
        if digest(path / name) != expected:
            raise ValueError(f"D0 artifact drift: {name}")


def tokens_sha256(ids: list[int]) -> str:
    return v3.sha256(v3.canonical(ids).encode())


def generate(
    model: Any,
    tokenizer: Any,
    prompt: list[int],
    callback: Any,
    deadline: float,
) -> tuple[dict[str, Any], Any]:
    import torch  # type: ignore[import-not-found]
    from torch.nn.attention import SDPBackend, sdpa_kernel  # type: ignore[import-not-found]

    if not prompt or len(prompt) > 1536 or model.generation_config.eos_token_id != EOS:
        raise ValueError("D0 generation prompt or EOS differs")
    tensor = torch.tensor([prompt], device=model.device)

    def audit(_module: Any, _inputs: Any, logits: Any) -> None:
        if logits.dtype != torch.float32 or not torch.isfinite(logits).all().item():
            raise ValueError("D0 model logits must be finite stock FP32")
        if time.monotonic() >= deadline:
            raise TimeoutError("D0 call deadline exceeded")

    hook = model.lm_head.register_forward_hook(audit)
    started = time.monotonic()
    try:
        extra = {} if callback is None else {"prefix_allowed_tokens_fn": callback}
        with torch.inference_mode(), sdpa_kernel(SDPBackend.MATH):
            result = model.generate(
                tensor,
                attention_mask=torch.ones_like(tensor),
                max_new_tokens=MAX_NEW,
                do_sample=False,
                num_beams=1,
                pad_token_id=tokenizer.pad_token_id,
                use_cache=True,
                return_dict_in_generate=True,
                output_logits=True,
                **extra,
            )
    finally:
        hook.remove()
    full_ids = result.sequences[0].tolist()
    if tuple(result.sequences.shape[:1]) != (1,) or full_ids[: len(prompt)] != prompt:
        raise ValueError("D0 generation changed the bound input")
    ids = full_ids[len(prompt) :]
    raw = tokenizer.decode(ids, skip_special_tokens=True)
    return {
        "token_ids": ids,
        "generated_token_ids_sha256": tokens_sha256(ids),
        "raw_output": raw,
        "raw_output_sha256": v3.sha256(raw.encode()),
        "eos": bool(ids and ids[-1] == EOS),
        "seconds": time.monotonic() - started,
    }, result.logits
