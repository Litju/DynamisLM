"""A1 model backend: one loaded base, PEFT adapter toggling, native and C1 decoding (RES-832).

This module owns model identity and the two decoding arms. It never builds a prompt and never
scores. ``M0`` is the identical loaded base with the LoRA adapter disabled by PEFT's own
``disable_adapter()`` context manager, so the two adaptation arms share weights, tokenizer,
precision, attention implementation and generation settings; only the adapter delta differs.

PEFT 0.16.0 exposes ``disable_adapter()`` as the context manager on ``PeftModel``.
``enable_adapter_layers()``/``disable_adapter_layers()`` live on the inner ``BaseTuner`` and
return ``None``; calling them as context managers silently runs both adaptation arms through the
adapter. The explicit per-layer state is therefore asserted on every arm entry, on every
generation and on every arm exit, never assumed.

Numerical conditions match the historical A0.3 evaluation: FP32 parameters, SDPA with the MATH
backend, greedy decoding, EOS 128012, and no autocast or TF32. Those are properties of
``a03_model_runtime.PinnedModel`` and are re-asserted in the recorded identity.

Path binding is explicit. A remote session receives its verified base snapshot and adapter
archive through ``A1_BASE_DIR`` and ``A1_ADAPTER_ARCHIVE``; the local caches are only a fallback
for CPU work. Every bound artifact is digest-verified before it is loaded, and CUDA execution
requires the pinned inference interpreter.
"""

from __future__ import annotations

import os
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Any

from scripts import a02_v3_contract as v3
from scripts import a03_model_core as core
from scripts import alpha_adapter_bundle as bundle

# The precision audit lives with the pinned runtime; import it through its defining module so the
# type checker resolves the real class rather than a re-export.
from scripts.a02_v3_precision import PrecisionAudit
from scripts.a03_hf_token_mask import hf_prefix_mask
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
BASE_DIR_ENV = "A1_BASE_DIR"
ADAPTER_ARCHIVE_ENV = "A1_ADAPTER_ARCHIVE"
PINNED_PYTHON_PREFIX = "/content/a02/inference-venv"
RUNTIME_PACKAGES = ("transformers", "peft", "tokenizers")
# Disclosed A1 prompt bound. The frozen A1 few-shot arm (D5) needs 2,689 tokens; the pinned base
# advertises a 65,536-token context. Every non-few-shot arm stays below the historical A0 bound of
# 1,536, which is verified locally and recorded in the payload digest gate.
MAX_PROMPT_TOKENS = 4096


class BackendError(RuntimeError):
    pass


@dataclass(frozen=True)
class Generation:
    ids: list[int]
    raw: str
    termination: str


def _bound_dir(variable: str) -> Path | None:
    value = os.environ.get(variable)
    if not value:
        return None
    path = Path(value)
    if not path.is_dir():
        raise BackendError(f"{variable} names a directory that does not exist")
    return path


def base_snapshot() -> Path:
    """The verified base snapshot: an explicit binding first, never a search after it."""
    bound = _bound_dir(BASE_DIR_ENV)
    if bound is not None:
        core.verify_files(bound, bundle.base_reference()["files"])
        return bound
    for root in BASE_CANDIDATES:
        candidate = root / SNAPSHOT_DIR / REVISION
        if candidate.is_dir():
            return candidate
    raise BackendError("pinned base snapshot is not present in any known cache")


def adapter_bundle() -> Path:
    """The verified adapter archive: an explicit binding first, then local evidence."""
    bound = os.environ.get(ADAPTER_ARCHIVE_ENV)
    if bound:
        path = Path(bound)
        if not path.is_file():
            raise BackendError(f"{ADAPTER_ARCHIVE_ENV} names a file that does not exist")
        return path
    for candidate in BUNDLE_CANDIDATES:
        if candidate.is_file():
            return candidate
    raise BackendError("the verified adapter bundle archive is not present")


def _record_path(value: str | None, fallback: Path) -> str:
    """Record the path that will be used, without requiring it to exist yet.

    The identity record is written before and after loading; a machine that has not yet downloaded
    the base must still be able to write the intended binding, and the loader itself verifies
    presence and every digest. Recording the candidate is therefore honest, not permissive.
    """
    if value:
        return value
    return str(fallback)


def identity(device: str) -> dict[str, Any]:
    base = bundle.base_reference()
    return {
        "device": device,
        "interpreter": {
            "executable": sys.executable,
            "version": sys.version.split()[0],
            "pinned_prefix": PINNED_PYTHON_PREFIX,
            "is_pinned": sys.executable.startswith(PINNED_PYTHON_PREFIX),
        },
        "model": {
            "id": base["id"],
            "revision": base["revision"],
            "files": base["files"],
            "path": _record_path(
                os.environ.get(BASE_DIR_ENV), BASE_CANDIDATES[0] / SNAPSHOT_DIR / REVISION
            ),
            "path_source": "BINDING" if os.environ.get(BASE_DIR_ENV) else "LOCAL_CACHE",
        },
        "adapter": {
            "step": 510,
            "files": core.ADAPTER_FILES,
            "bundle": _record_path(os.environ.get(ADAPTER_ARCHIVE_ENV), BUNDLE_CANDIDATES[0]),
            "bundle_source": "BINDING" if os.environ.get(ADAPTER_ARCHIVE_ENV) else "LOCAL_EVIDENCE",
        },
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
        "max_prompt_tokens": MAX_PROMPT_TOKENS,
        "eos_token_id": core.EOS,
    }


def tuner_layers(model: Any) -> list[Any]:
    """The live PEFT tuner layers, read from the loaded model rather than assumed.

    Where PEFT is importable the authoritative ``BaseTunerLayer`` class is used. Without PEFT
    (a CPU-only checkout, or a contract test) the same surface is identified structurally. A
    model with no layer at all returns an empty list, which the callers treat as "non-PEFT" and
    refuse for an inference arm.
    """
    base_layer: Any = None
    try:
        from peft.tuners.tuners_utils import (  # type: ignore[import-not-found]
            BaseTunerLayer,
        )

        base_layer = BaseTunerLayer
    except ModuleNotFoundError:
        base_layer = None

    def is_layer(module: Any) -> bool:
        if base_layer is not None:
            return bool(isinstance(module, base_layer))
        return bool(
            hasattr(module, "disable_adapters")
            and hasattr(module, "adapter_layer_names")
            and hasattr(module, "active_adapters")
        )

    if not hasattr(model, "modules"):
        return []
    return [module for module in model.modules() if is_layer(module)]


def adapter_enabled(model: Any) -> bool | None:
    """True/False from the real per-layer flags; None when the model carries no tuner layer.

    An irregular mixture is an execution defect: it would make the arm identity ambiguous.
    """
    layers = tuner_layers(model)
    if not layers:
        return None
    states = {bool(layer.disable_adapters) for layer in layers}
    if len(states) != 1:
        raise BackendError("PEFT adapter state is irregular across layers")
    return not states.pop()


class A1Backend:
    """FP32 CUDA/CPU runtime with verified adapter enable/disable and explicit path binding."""

    def __init__(self, device: str, workdir: Path) -> None:
        # The interpreter guard runs before any inference import: a wrong interpreter must fail
        # immediately rather than after a costly import or a partial load.
        if device not in {"cpu", "cuda"}:
            raise BackendError("unsupported A1 device")
        if device == "cuda" and not sys.executable.startswith(PINNED_PYTHON_PREFIX):
            raise BackendError("A1 CUDA execution requires the pinned inference interpreter")

        import torch  # type: ignore[import-not-found]
        from peft import PeftModel  # type: ignore[import-not-found]
        from transformers import AutoTokenizer  # type: ignore[import-not-found]

        from scripts.a02_v3_precision import load_model

        if device == "cuda":
            free, _total = torch.cuda.mem_get_info(0)
            if free < core.MIN_FREE_VRAM:
                raise BackendError("A1 requires the qualified free VRAM margin")
        self.observed_packages = {
            "torch": str(torch.__version__),
            **{name: version(name) for name in RUNTIME_PACKAGES},
        }
        if self.observed_packages != core.RUNTIME:
            raise BackendError(f"A1 runtime package identity differs: {self.observed_packages}")
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
        if (
            self.mask.eos != core.EOS
            or self.model.generation_config.eos_token_id != core.EOS
            or self.model.config._attn_implementation != "sdpa"
            or any(p.requires_grad or p.device.type != device for p in self.model.parameters())
        ):
            raise BackendError("pinned A1 inference conditions differ")
        if adapter_enabled(self.model) is not True:
            raise BackendError("the loaded adapter is not active at setup")
        self.setup_seconds = 0.0
        self.calls = 0
        self.seconds = 0.0
        self.arm_calls = {"M0": 0, "M1": 0}
        self.adapter_checks = 0
        self._expected_adapter: str | None = None

    def _require_adapter(self, model: str) -> None:
        expected = model == "M1"
        observed = adapter_enabled(self.model)
        if observed is not expected:
            raise BackendError(
                f"A1 adapter state differs during {model}: enabled={observed}, expected={expected}"
            )
        self.adapter_checks += 1

    @contextmanager
    def adapted(self, model: str) -> Any:
        """Enter one adaptation arm, verifying the real PEFT layer state on both edges."""
        if model not in {"M0", "M1"}:
            raise BackendError(f"unknown A1 model arm: {model}")
        if adapter_enabled(self.model) is not True:
            raise BackendError("A1 adapter is not enabled before the arm")
        if model == "M1":
            self._expected_adapter = model
            try:
                self._require_adapter(model)
                yield
                self._require_adapter(model)
            finally:
                self._expected_adapter = None
        else:
            # The only supported adapter-off mechanism in PEFT 0.16.0 is this context manager.
            with self.model.disable_adapter():
                self._expected_adapter = model
                try:
                    self._require_adapter(model)
                    yield
                    self._require_adapter(model)
                finally:
                    self._expected_adapter = None
            if adapter_enabled(self.model) is not True:
                raise BackendError("A1 adapter was not restored after the M0 arm")

    def generate(
        self, arm: str, request: dict[str, Any], prompt: list[int], deadline: float
    ) -> Generation:
        from functools import partial

        if self._expected_adapter is None:
            raise BackendError("A1 generation was requested outside an adaptation arm")
        self._require_adapter(self._expected_adapter)
        if not 0 < len(prompt) <= MAX_PROMPT_TOKENS:
            raise BackendError(f"A1 prompt exceeds the disclosed {MAX_PROMPT_TOKENS}-token bound")
        callback = (
            partial(hf_prefix_mask, self.mask, Grammar(request), prompt) if arm == "C1" else None
        )
        started = time.monotonic()
        result, _ = core.generate(
            self.model,
            self.tokenizer,
            prompt,
            callback,
            deadline,
            max_prompt_tokens=MAX_PROMPT_TOKENS,
        )
        self._require_adapter(self._expected_adapter)
        self.calls += 1
        self.arm_calls[self._expected_adapter] += 1
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
            "precision": self.audit.report() if self.audit.logit_dtypes else self.audit.identity,
            "runtime_packages": self.observed_packages,
            "interpreter": sys.executable,
            "adapter_checks": self.adapter_checks,
            "adapter_state_after": adapter_enabled(self.model),
            "calls": self.calls,
            "calls_by_model": dict(self.arm_calls),
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
