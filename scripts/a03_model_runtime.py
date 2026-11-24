"""Shared pinned A0.3 model loading and native/C1 generation."""

from __future__ import annotations

import resource
import site
import sys
import time
from dataclasses import dataclass
from functools import partial
from importlib.metadata import version
from pathlib import Path
from typing import Any

from scripts import a02_dev_runtime
from scripts import a03_model_core as d0
from scripts.a02_v3_precision import PrecisionAudit, load_model
from scripts.a03_hf_token_mask import hf_prefix_mask
from scripts.a03_token_decoder import Grammar, TokenMask, Vocabulary

MAX_PROMPT = 1536


@dataclass(frozen=True)
class Generation:
    ids: list[int]
    raw: str
    termination: str


def require_file_inventory(directory: Path, allowed: dict[str, str]) -> None:
    extra = sorted(
        path.name
        for path in directory.iterdir()
        if path.name not in allowed and not (path.name == ".cache" and path.is_dir())
    )
    if extra:
        raise ValueError(f"unbound files in inference directory: {extra}")


class PinnedModel:
    """Local frozen D0 loader with explicit FP32 CPU or T4 placement."""

    def __init__(
        self,
        snapshot: Path,
        adapter: Path,
        *,
        identity: dict[str, Any],
        cpu_qualification: bool,
    ) -> None:
        import torch  # type: ignore[import-not-found]
        from peft import PeftModel  # type: ignore[import-not-found]

        started = time.monotonic()
        self.identity = identity
        device = identity["device"]
        packages = self.identity["runtime_packages"]
        if {name: version(name) for name in packages} != packages:
            raise ValueError("pinned runtime packages differ")
        self.runtime: dict[str, Any] = {
            "python": sys.version,
            "device": device,
            "torch_threads": torch.get_num_threads(),
            "torch_interop_threads": torch.get_num_interop_threads(),
        }
        if device == "cpu" and cpu_qualification:
            if sys.version_info[:2] != (3, 13) or torch.version.cuda is not None:
                raise ValueError("CPU qualification requires CPython 3.13 and the CPU torch build")
            self.runtime["cpu_model"] = next(
                line.split(":", 1)[1].strip()
                for line in Path("/proc/cpuinfo").read_text().splitlines()
                if line.startswith("model name")
            )
        if device == "cuda":
            inventory = a02_dev_runtime.inventory(torch, Path(site.getsitepackages()[0]))
            qualified = a02_dev_runtime.qualify(
                inventory, a02_dev_runtime.cuda_smoke(torch, inventory)
            )
            if (
                not qualified["qualified"]
                or torch.version.cuda != "13.0"
                or torch.cuda.mem_get_info(0)[0] < d0.MIN_FREE_VRAM
            ):
                raise ValueError(f"D0 T4 qualification failed: {qualified}")
            self.runtime["cuda"] = {
                "provenance": {
                    name: value
                    for name, value in qualified["provenance_only"].items()
                    if name != "driver_inventory"
                },
                "requirements": {row["name"]: row["passed"] for row in qualified["requirements"]},
                "name": inventory["cuda"]["name"],
                "driver_version": ",".join(inventory["driver_inventory"].split(",")[:2])
                if inventory["driver_inventory"]
                else None,
                "compute_capability": inventory["cuda"]["compute_capability"],
                "total_vram_bytes": inventory["cuda"]["total_vram_bytes"],
            }
        # Transformers can prefer a single safetensors file over the verified shards.
        snapshot_files = d0.MODEL_FILES | self.identity["tokenizer"]["files"]
        require_file_inventory(snapshot, snapshot_files)
        require_file_inventory(adapter, identity["adapter_files"])
        d0.verify_files(snapshot, snapshot_files)
        d0.verify_files(adapter, identity["adapter_files"])
        from transformers import AutoTokenizer  # type: ignore[import-not-found]

        self.tokenizer = AutoTokenizer.from_pretrained(str(snapshot), local_files_only=True)
        self.mask = TokenMask(Vocabulary.from_tokenizer(self.tokenizer))
        # PEFT otherwise redispatches a CPU-resident base with its automatic offload map.
        self.model = PeftModel.from_pretrained(
            load_model(snapshot, "float32", device=device),
            adapter,
            is_trainable=False,
            device_map={"": device},
            local_files_only=True,
        ).eval()
        self.model.generation_config = type(self.model.generation_config).from_model_config(
            self.model.config
        )
        self.audit = PrecisionAudit(self.model, "float32")
        if (
            self.mask.eos != d0.EOS
            or self.model.generation_config.eos_token_id != d0.EOS
            or self.model.config._attn_implementation != "sdpa"
            or any(p.requires_grad or p.device.type != device for p in self.model.parameters())
        ):
            raise ValueError("pinned inference conditions differ")
        self.runtime["parameters"] = self.audit.identity
        self.setup_seconds = time.monotonic() - started

    def measurements(self) -> dict[str, Any]:
        import torch

        return {
            "setup_seconds": self.setup_seconds,
            "peak_host_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            "peak_cuda_reserved_bytes": (
                torch.cuda.max_memory_reserved() if self.identity["device"] == "cuda" else None
            ),
            "precision": self.audit.report() if self.audit.logit_dtypes else self.audit.identity,
        }

    def generate(
        self, arm: str, request: dict[str, Any], prompt: list[int], deadline: float
    ) -> Generation:
        callback = (
            partial(hf_prefix_mask, self.mask, Grammar(request), prompt) if arm == "C1" else None
        )
        result, _ = d0.generate(self.model, self.tokenizer, prompt, callback, deadline)
        ids = result["token_ids"]
        termination = (
            "MODEL_EOS"
            if result["eos"]
            else ("TOKEN_LIMIT" if len(ids) == d0.MAX_NEW else "EARLY_STOP")
        )
        return Generation(ids, result["raw_output"], termination)
