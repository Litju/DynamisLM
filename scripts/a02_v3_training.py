"""Bounded owner-requested LoRA training on frozen synthetic TRAIN data (RES-541).

Learned adapters stay outside Git. This never trains on held-out/exposed examples and never
labels training loss as scientific task accuracy. Evaluation arithmetic remains the A1 FP32 path.
"""

from __future__ import annotations

import gc
import hashlib
import importlib.metadata
import json
import math
import os
import random
import shutil
import tarfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts import a02_execution
from scripts import a02_v3_contract as v3
from scripts import a02_v3_decision as decision
from scripts import a02_v3_precision as precision
from scripts import a02_v3_synthetic as synthetic

SCHEMA = "RES541_LORA_TRAINING_CHECKPOINT_V1"


def specification() -> dict[str, Any]:
    protocol = decision.load_protocol()
    return {
        "schema": "RES541_OWNER_REQUESTED_LORA_V1",
        "base_model": protocol["candidate_model"],
        "protocol_sha256": decision.protocol_sha256(),
        "training": protocol["data"]["training"],
        "adaptation": protocol["adaptation"],
        "peft_version": "0.16.0",
        "base_precision": "float16",
        "adapter_precision": "float32",
        "evaluation_precision": "float32",
        "attention_backend": "MATH",
        "loss": "mean next-token cross-entropy over target_text plus tokenizer EOS only",
        "batching": "microbatch1; full-input token budget; target-token-weighted gradients",
        "optimizer": {"betas": [0.9, 0.999], "eps": 1e-8, "weight_decay": 0.01},
        "schedule": "ceil warmup fraction; linear decay; epoch shuffle seed+epoch",
        "max_grad_norm": 1.0,
        "gradient_checkpointing": True,
        "deterministic_algorithms": True,
        "cublas_workspace_config": ":4096:8",
        "loss_scaler_initial_scale": 128.0,
        "numerical_failure": "stop on nonfinite loss/gradient/adapter; no skipped updates",
        "checkpoint_interval_steps": 10,
        "first_step_bound_seconds": 120.0,
        "scientific_accuracy_claim": False,
    }


def validate_specification(value: dict[str, Any]) -> None:
    if value != specification():
        raise ValueError("training specification differs from exact frozen source")


@dataclass(frozen=True)
class TokenExample:
    ids: list[int]
    start: int
    id: str


def examples(tokenizer: Any, spec: dict[str, Any]) -> list[TokenExample]:
    validate_specification(spec)
    data = spec["training"]
    if data["split"] != "TRAIN":
        raise ValueError("training accepts only the frozen TRAIN split")
    rows = synthetic.generate(data["split"], data["seed"], data["count"])
    if synthetic.manifest_sha256(rows) != data["manifest_sha256"]:
        raise ValueError("training examples differ from frozen manifest")
    profile = v3.load_profile()
    out = []
    eos = tokenizer.eos_token_id
    if not isinstance(eos, int):
        raise ValueError("training needs the pinned tokenizer EOS")
    for row in rows:
        if row["split"] != "TRAIN":
            raise ValueError("non-TRAIN example reached training")
        prompt = v3.build_action_prompt(tokenizer, row["request"])
        prefix = prompt["prompt_token_ids"]
        joint = list(
            tokenizer.encode(
                prompt["rendered_prompt"] + row["target_text"], add_special_tokens=False
            )
        )
        if joint[: len(prefix)] != prefix or len(joint) <= len(prefix):
            raise ValueError("training prompt/target boundary is not token aligned")
        joint.append(eos)
        if (
            len(prefix) > profile["decoding"]["action_max_prompt_tokens"]
            or len(joint) - len(prefix) > profile["decoding"]["action_max_new_tokens"]
        ):
            raise ValueError("training exceeds frozen token limits; no truncation")
        out.append(TokenExample(joint, len(prefix), decision.example_id(row)))
    return out


def batches(data: Sequence[TokenExample], spec: dict[str, Any]) -> list[list[int]]:
    optimizer = spec["adaptation"]["optimizer"]
    limit = optimizer["batch_tokens"]
    out = []
    if not data or limit <= 0:
        raise ValueError("training data and token budget must be nonempty")
    for epoch in range(optimizer["epochs"]):
        order = list(range(len(data)))
        random.Random(optimizer["seed"] + epoch).shuffle(order)
        batch: list[int] = []
        used = 0
        for index in order:
            cost = len(data[index].ids) - 1
            if not 0 < data[index].start < len(data[index].ids) or cost > limit:
                raise ValueError("invalid training boundaries or oversized example")
            if batch and used + cost > limit:
                out.append(batch)
                batch, used = [], 0
            batch.append(index)
            used += cost
        if batch:
            out.append(batch)
    return out


def attach(base: Any, spec: dict[str, Any], checkpoint: Path | None = None) -> Any:
    from peft import (  # type: ignore[import-not-found]
        LoraConfig,
        PeftModel,
        TaskType,
        get_peft_model,
    )

    if checkpoint is None:
        config = spec["adaptation"]["lora"]
        model = get_peft_model(
            base,
            LoraConfig(
                task_type=TaskType.CAUSAL_LM,
                r=config["rank"],
                lora_alpha=config["alpha"],
                lora_dropout=config["dropout"],
                target_modules=config["target_modules"],
                bias="none",
            ),
        )
    else:
        model = PeftModel.from_pretrained(base, checkpoint, is_trainable=True)
    trainable = [(n, p) for n, p in model.named_parameters() if p.requires_grad]
    if not trainable or any(
        "lora_" not in n or str(p.dtype) != "torch.float32" for n, p in trainable
    ):
        raise ValueError("only FP32 LoRA parameters may be trainable")
    model.config.use_cache = False
    if spec["gradient_checkpointing"]:
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
        model.enable_input_require_grads()
    model.train()
    return model


def target_loss(model: Any, example: TokenExample) -> Any:
    import torch  # type: ignore[import-not-found]
    from torch.nn.attention import SDPBackend, sdpa_kernel  # type: ignore[import-not-found]

    if not 0 < example.start < len(example.ids):
        raise ValueError("invalid target-only loss boundary")
    device = next(model.parameters()).device
    ids = torch.tensor([example.ids[:-1]], device=device)
    targets = torch.tensor([example.ids[example.start :]], device=device)
    with (
        sdpa_kernel(SDPBackend.MATH),
        torch.autocast(device_type=device.type, dtype=torch.float16, enabled=device.type == "cuda"),
    ):
        logits = model(ids, use_cache=False, logits_to_keep=targets.shape[1]).logits
    return torch.nn.functional.cross_entropy(
        logits.float().reshape(-1, logits.shape[-1]), targets.reshape(-1), reduction="sum"
    )


def adapter_fingerprint(model: Any) -> str:
    h = hashlib.sha256()
    for name, parameter in sorted(model.named_parameters()):
        if parameter.requires_grad:
            h.update(name.encode())
            h.update(parameter.detach().float().cpu().contiguous().numpy().tobytes())
    return h.hexdigest()


def unpack(archive: Path, destination: Path) -> None:
    if destination.exists():
        raise ValueError("training recovery directory already exists")
    destination.mkdir(parents=True)
    with tarfile.open(archive, "r:") as handle:
        members = handle.getmembers()
        allowed = {
            "adapter_config.json",
            "adapter_model.safetensors",
            "optimizer.pt",
            "metadata.json",
        }
        if (
            len(members) != len(allowed)
            or {m.name for m in members} != allowed
            or any(not m.isfile() for m in members)
        ):
            raise ValueError("unsafe or incomplete training checkpoint archive")
        handle.extractall(destination, filter="data")


def save(
    model: Any,
    optimizer: Any,
    scheduler: Any,
    scaler: Any,
    root: Path,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    import torch

    stage = root / "writing-checkpoint"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    model.save_pretrained(stage, safe_serialization=True)
    # PEFT also writes a model-card README; only checkpoint authority files enter the tar.
    torch.save(
        {
            "optimizer": optimizer.state_dict(),
            "scheduler": scheduler.state_dict(),
            "scaler": scaler.state_dict(),
            "cpu_rng": torch.get_rng_state(),
            "cuda_rng": torch.cuda.get_rng_state() if next(model.parameters()).is_cuda else None,
        },
        stage / "optimizer.pt",
    )
    metadata = {
        **metadata,
        "adapter_sha256": v3.sha256((stage / "adapter_model.safetensors").read_bytes()),
        "adapter_fingerprint": adapter_fingerprint(model),
    }
    a02_execution._write_json(stage / "metadata.json", metadata)
    tmp = root / "checkpoint.writing.tar"
    with tarfile.open(tmp, "w:") as handle:
        for name in (
            "adapter_config.json",
            "adapter_model.safetensors",
            "optimizer.pt",
            "metadata.json",
        ):
            handle.add(stage / name, arcname=name)
    with tmp.open("rb") as stream:
        os.fsync(stream.fileno())
    os.replace(tmp, root / "checkpoint.tar")
    return metadata


def fit(
    model: Any,
    data: Sequence[TokenExample],
    spec: dict[str, Any],
    root: Path,
    identity: dict[str, Any],
    *,
    deadline: float,
    emit: Callable[[dict[str, Any]], None],
    resumed: Path | None = None,
) -> dict[str, Any]:
    """Train at complete optimizer-step boundaries; serialize optimizer and RNG for exact resume."""
    import torch
    from torch.nn.attention import SDPBackend, sdpa_kernel

    plan = batches(data, spec)
    total = len(plan)
    params = [p for p in model.parameters() if p.requires_grad]
    frozen = [(p, p._version) for p in model.parameters() if not p.requires_grad]
    config = spec["adaptation"]["optimizer"]
    optimizer = torch.optim.AdamW(params, lr=config["learning_rate"], **spec["optimizer"])
    warmup: int = math.ceil(total * config["warmup_ratio"])

    def factor(step: int) -> float:
        return (
            step / max(1, warmup)
            if step < warmup
            else max(0.0, (total - step) / max(1, total - warmup))
        )

    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, factor)
    scaler = torch.amp.GradScaler(
        "cuda",
        enabled=next(model.parameters()).is_cuda,
        init_scale=spec["loss_scaler_initial_scale"],
    )
    meta: dict[str, Any] = {
        "schema": SCHEMA,
        "identity": identity,
        "specification_sha256": v3.sha256(v3.canonical(spec).encode()),
        "data_order_sha256": v3.sha256(
            v3.canonical([[data[i].id for i in b] for b in plan]).encode()
        ),
        "next_step": 0,
        "total_steps": total,
        "loss_sum": 0.0,
        "target_tokens": 0,
        "initial_adapter_fingerprint": adapter_fingerprint(model),
        "runtime": {
            "torch": torch.__version__,
            "cuda": torch.version.cuda,
            "peft": importlib.metadata.version("peft"),
            "device": str(next(model.parameters()).device),
            "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
            "float32_matmul_precision": torch.get_float32_matmul_precision(),
        },
        "completed": False,
        "step_bound_seconds": spec["first_step_bound_seconds"],
    }
    if resumed is not None:
        old = json.loads((resumed / "metadata.json").read_bytes())
        for key in (
            "schema",
            "identity",
            "specification_sha256",
            "data_order_sha256",
            "total_steps",
            "runtime",
        ):
            if old[key] != meta[key]:
                raise ValueError(f"training checkpoint identity differs: {key}")
        if (
            isinstance(old["next_step"], bool)
            or not isinstance(old["next_step"], int)
            or not 0 <= old["next_step"] <= total
            or old["adapter_fingerprint"] != adapter_fingerprint(model)
            or old["adapter_sha256"]
            != v3.sha256((resumed / "adapter_model.safetensors").read_bytes())
        ):
            raise ValueError("training checkpoint weights or cursor differ")
        state = torch.load(resumed / "optimizer.pt", map_location="cpu", weights_only=True)
        optimizer.load_state_dict(state["optimizer"])
        scheduler.load_state_dict(state["scheduler"])
        scaler.load_state_dict(state["scaler"])
        torch.set_rng_state(state["cpu_rng"])
        if state["cuda_rng"] is not None:
            torch.cuda.set_rng_state(state["cuda_rng"])
        meta = old
    else:
        meta = save(model, optimizer, scheduler, scaler, root, meta)
    first_step = meta["next_step"]
    while meta["next_step"] < total:
        if time.monotonic() + meta["step_bound_seconds"] + 30 >= deadline:
            break
        started = time.monotonic()
        batch = plan[meta["next_step"]]
        denominator = sum(len(data[i].ids) - data[i].start for i in batch)
        optimizer.zero_grad(set_to_none=True)
        batch_loss = 0.0
        for index in batch:
            # Checkpoint recomputation must use the forward pass's attention backend.
            with sdpa_kernel(SDPBackend.MATH):
                loss = target_loss(model, data[index])
                if not bool(torch.isfinite(loss).item()):
                    raise FloatingPointError("nonfinite training loss; no retry")
                batch_loss += float(loss.detach())
                scaler.scale(loss / denominator).backward()
        scaler.unscale_(optimizer)
        torch.nn.utils.clip_grad_norm_(params, spec["max_grad_norm"], error_if_nonfinite=True)
        if any(p._version != version or p.requires_grad for p, version in frozen):
            raise ValueError("frozen base weights changed")
        previous_scale = scaler.get_scale()
        scaler.step(optimizer)
        scaler.update()
        if scaler.get_scale() < previous_scale or any(
            not bool(torch.isfinite(p).all()) for p in params
        ):
            raise FloatingPointError(
                "training overflow or nonfinite adapter; no skipped update accepted"
            )
        scheduler.step()
        if next(model.parameters()).is_cuda:
            torch.cuda.synchronize()
        elapsed = time.monotonic() - started
        meta.update(
            next_step=meta["next_step"] + 1,
            loss_sum=meta["loss_sum"] + batch_loss,
            target_tokens=meta["target_tokens"] + denominator,
            step_bound_seconds=max(meta["step_bound_seconds"], elapsed * 2 + 5),
        )
        meta["completed"] = meta["next_step"] == total
        emit(
            {
                "phase": "TRAIN_STEP",
                "step": meta["next_step"],
                "total_steps": total,
                "loss_per_target_token": batch_loss / denominator,
                "seconds": elapsed,
                "learning_rate": optimizer.param_groups[0]["lr"],
            }
        )
        if meta["completed"] or meta["next_step"] % spec["checkpoint_interval_steps"] == 0:
            meta = save(model, optimizer, scheduler, scaler, root, meta)
    meta = save(model, optimizer, scheduler, scaler, root, meta)
    if meta["completed"] and meta["adapter_fingerprint"] == meta["initial_adapter_fingerprint"]:
        raise ValueError("completed training produced no changed adapter weights")
    return {
        **meta,
        "steps_this_session": meta["next_step"] - first_step,
        "checkpoint_sha256": v3.sha256((root / "checkpoint.tar").read_bytes()),
    }


def run(
    snapshot: Path,
    root: Path,
    spec: dict[str, Any],
    identity: dict[str, Any],
    *,
    deadline: float,
    emit: Callable[[dict[str, Any]], None],
    prior: Path | None = None,
) -> dict[str, Any]:
    import peft
    import torch
    from transformers import AutoTokenizer  # type: ignore[import-not-found]

    validate_specification(spec)
    if peft.__version__ != spec["peft_version"]:
        raise ValueError("unpinned PEFT runtime")
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = spec["cublas_workspace_config"]
    torch.use_deterministic_algorithms(spec["deterministic_algorithms"])
    torch.cuda.reset_peak_memory_stats()
    before_free, before_total = torch.cuda.mem_get_info()
    torch.manual_seed(spec["adaptation"]["optimizer"]["seed"])
    torch.cuda.manual_seed_all(spec["adaptation"]["optimizer"]["seed"])
    precision.configure("float32")
    restored = None
    if prior is not None:
        restored = root / "restored-checkpoint"
        unpack(prior, restored)
    tokenizer = AutoTokenizer.from_pretrained(snapshot, local_files_only=True)
    data = examples(tokenizer, spec)
    base = precision.load_model(snapshot, "float16")
    model = attach(base, spec, restored)
    result = fit(model, data, spec, root, identity, deadline=deadline, emit=emit, resumed=restored)
    result.update(
        evidence_class="OWNER_REQUESTED_SYNTHETIC_LORA_TRAINING_NOT_TASK_ACCURACY",
        base_model=spec["base_model"],
        training_manifest_sha256=spec["training"]["manifest_sha256"],
        trainable_parameters=sum(p.numel() for p in model.parameters() if p.requires_grad),
        runtime={
            **result["runtime"],
            "torch": torch.__version__,
            "peft": peft.__version__,
            "training_base_parameter_dtypes": sorted(
                {str(p.dtype) for p in model.parameters() if not p.requires_grad}
            ),
            "adapter_parameter_dtypes": sorted(
                {str(p.dtype) for p in model.parameters() if p.requires_grad}
            ),
        },
        before_load_free_bytes=int(before_free),
        before_load_total_bytes=int(before_total),
        peak_allocated_bytes=int(torch.cuda.max_memory_allocated()),
        peak_reserved_bytes=int(torch.cuda.max_memory_reserved()),
    )
    emit({"phase": "TRAIN_FINAL", **result})
    del model, base
    gc.collect()
    return result
