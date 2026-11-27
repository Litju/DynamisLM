"""A1 model backend: one loaded base, PEFT adapter toggling, native and C1 decoding (RES-832).

This module owns model identity and the two decoding arms. It never builds a prompt and never
scores. ``M0`` is the identical loaded base with the LoRA adapter disabled by PEFT's own
adapter context, so the two adaptation arms share weights, tokenizer, precision, attention
implementation and generation settings; only the adapter delta differs.

Numerical conditions match the historical A0.3 evaluation: FP32 parameters, SDPA with the MATH
backend, greedy decoding, EOS 128012, and no autocast or TF32. Those are properties of
``a03_model_runtime.PinnedModel`` and are re-asserted in the recorded identity.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from scripts import a02_v3_contract as v3
from scripts import a03_model_core as core
from scripts import alpha_adapter_bundle as bundle

# The precision audit lives with the pinned runtime; import it through its defining module so the
# type checker resolves the real class rather than a re-export.
from scripts.a02_v3_precision import PrecisionAudit
from scripts.a03_hf_token_mask import hf_prefix_mask
from scripts.a03_model_runtime import Generation
from scripts.a03_token_decoder import Grammar, TokenMask, Vocabulary

EVIDENCE_ROOT = Path.home() / ".local/share/dynamislm-evidence"
BUNDLE_CANDIDATES = (
    EVIDENCE_ROOT / "RES-772-adapter-bundle/first.tar",
    EVIDENCE_ROOT / "RES-772-adapter-bundle/second.tar",
)
BASE_CANDIDATES = (
    Path("/mnt/e/DynamisLM-A0/cache/huggingface/hub"),
    Path.home() / ".cache/huggingface/hub",
)
SNAPSHOT_DIR = "models--HuggingFaceTB--SmolLM3-3B/snapshots"
REVISION = "a07cc9a04f16550a088caea529712d1d335b0ac1"
TOKENIZER_DIR = Path("/mnt/e/DynamisLM-A0/a01/tokenizer")


class BackendError(RuntimeError):
    pass


def base_snapshot() -> Path:
    for root in BASE_CANDIDATES:
        candidate = root / SNAPSHOT_DIR / REVISION
        if candidate.is_dir():
            return candidate
    raise BackendError("pinned base snapshot is not present in any known cache")


def adapter_bundle() -> Path:
    for candidate in BUNDLE_CANDIDATES:
        if candidate.is_file():
            return candidate
    raise BackendError("the verified adapter bundle archive is not present")


def tokenizer_dir() -> Path:
    if not TOKENIZER_DIR.is_dir():
        raise BackendError("pinned tokenizer directory is not present")
    return TOKENIZER_DIR


def identity(device: str) -> dict[str, Any]:
    base = bundle.base_reference()
    return {
        "device": device,
        "model": {"id": base["id"], "revision": base["revision"], "files": base["files"]},
        "adapter": {"step": 510, "files": core.ADAPTER_FILES, "bundle": str(adapter_bundle())},
        "tokenizer": {
            "revision": base["revision"],
            "files": {name: base["files"][name] for name in base["tokenizer_files"]},
        },
        "runtime_packages": dict(core.RUNTIME),
        "precision": "float32",
        "attention": "sdpa:MATH",
        "greedy": True,
        "autocast": False,
        "tf32": False,
        "max_new_tokens": core.MAX_NEW,
        "eos_token_id": core.EOS,
    }


class A1Backend:
    """FP32 CUDA/CPU runtime with explicit adapter enable/disable."""

    def __init__(self, device: str, workdir: Path) -> None:
        import torch  # type: ignore[import-not-found]
        from peft import PeftModel  # type: ignore[import-not-found]
        from transformers import AutoTokenizer  # type: ignore[import-not-found]

        from scripts.a02_v3_precision import load_model

        if device not in {"cpu", "cuda"}:
            raise BackendError("unsupported A1 device")
        if device == "cuda":
            free, _total = torch.cuda.mem_get_info(0)
            if free < core.MIN_FREE_VRAM:
                raise BackendError("A1 requires the qualified free VRAM margin")
        base = base_snapshot()
        self.base_dir = base
        self.workdir = workdir
        self.device = device
        core.verify_files(base, identity(device)["model"]["files"])
        payload, report = bundle.verified_payload(adapter_bundle())
        staging = workdir / "adapter"
        staging.mkdir(parents=True, exist_ok=True)
        for name, member in (
            ("adapter_config.json", bundle.CONFIG),
            ("adapter_model.safetensors", bundle.WEIGHTS),
        ):
            (staging / name).write_bytes(payload[member])
        self.bundle_report = report
        self.tokenizer = AutoTokenizer.from_pretrained(str(base), local_files_only=True)
        self.mask = TokenMask(Vocabulary.from_tokenizer(self.tokenizer))
        self.model = PeftModel.from_pretrained(
            load_model(base, "float32", device=device),
            staging,
            is_trainable=False,
            device_map={"": device},
            local_files_only=True,
        ).eval()
        self.model.generation_config = type(self.model.generation_config).from_model_config(
            self.model.config
        )
        self.audit = PrecisionAudit(self.model, "float32")
        self.setup_seconds = 0.0
        self.calls = 0
        self.seconds = 0.0

    @contextmanager
    def adapted(self, model: str) -> Any:
        if model == "M1":
            with self.model.enable_adapter_layers():
                yield
        elif model == "M0":
            with self.model.disable_adapter_layers():
                yield
        else:
            raise BackendError(f"unknown A1 model arm: {model}")

    def generate(
        self, arm: str, request: dict[str, Any], prompt: list[int], deadline: float
    ) -> Generation:
        from functools import partial

        callback = (
            partial(hf_prefix_mask, self.mask, Grammar(request), prompt) if arm == "C1" else None
        )
        started = time.monotonic()
        result, _ = core.generate(self.model, self.tokenizer, prompt, callback, deadline)
        self.calls += 1
        self.seconds += time.monotonic() - started
        ids = result["token_ids"]
        termination = (
            "MODEL_EOS"
            if result["eos"]
            else ("TOKEN_LIMIT" if len(ids) == core.MAX_NEW else "EARLY_STOP")
        )
        return Generation(ids, result["raw_output"], termination)

    def measurements(self) -> dict[str, Any]:
        import resource

        import torch

        return {
            "setup_seconds": self.setup_seconds,
            "peak_host_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            "peak_cuda_reserved_bytes": (
                torch.cuda.max_memory_reserved() if self.device == "cuda" else None
            ),
            "precision": self.audit.identity,
            "calls": self.calls,
            "generation_seconds": round(self.seconds, 3),
            "mean_seconds_per_call": round(self.seconds / self.calls, 4) if self.calls else None,
        }


def request_prompt(
    tokenizer: Any, request: dict[str, Any], system_text: str, fewshot: str = "0"
) -> dict[str, Any]:
    """Prompt builder that takes explicit system-prompt bytes (the A1 ablation surface)."""
    from scripts import a1_representation as rep

    messages = rep.render_messages(request, system_text, fewshot)
    kwargs = {
        "enable_thinking": False,
        "strftime_now": v3.ACTION_TEMPLATE_DATE.strftime,
        "xml_tools": [v3.tool_schema()],
    }
    ids = tokenizer.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=True, **kwargs
    )
    rendered = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True, **kwargs
    )
    if tokenizer.encode(rendered, add_special_tokens=False) != ids:
        raise BackendError("A1 prompt does not reproduce tokenizer ids")
    return {
        "messages": messages,
        "rendered_prompt": rendered,
        "rendered_prompt_sha256": v3.sha256(rendered.encode()),
        "prompt_token_ids": ids,
        "prompt_tokens": len(ids),
    }
