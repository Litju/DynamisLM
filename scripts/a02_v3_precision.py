"""Explicit prospective A1 precision selection; grants no scientific or GPU authority (RES-541)."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def configure(precision: str) -> Any:
    if precision not in {"float16", "float32"}:
        raise ValueError("precision must explicitly name float16 or float32")
    import torch  # type: ignore[import-not-found]

    if precision == "float32":
        if torch.is_autocast_enabled("cuda") or torch.is_autocast_enabled("cpu"):
            raise ValueError("A1 requires autocast disabled")
        torch.set_float32_matmul_precision("highest")
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
    return getattr(torch, precision)


def load_model(snapshot: Path, precision: str = "float16", *, device: str = "cuda") -> Any:
    """FP16 retains the historical loader; FP32 streams directly to the selected device."""
    from transformers import AutoModelForCausalLM  # type: ignore[import-not-found]

    dtype = configure(precision)
    options: dict[str, Any] = {}
    if precision == "float32":
        options.update(device_map={"": device}, low_cpu_mem_usage=True)
    model = AutoModelForCausalLM.from_pretrained(
        str(snapshot), local_files_only=True, torch_dtype=dtype, **options
    )
    if precision == "float16":
        model = model.to(device)
    model.eval()
    verify_parameters(model, precision)
    return model


def verify_parameters(model: Any, precision: str) -> dict[str, Any]:
    expected = f"torch.{precision}"
    observed = {str(p.dtype) for p in model.parameters()}
    if precision not in {"float16", "float32"} or observed != {expected}:
        raise ValueError(f"loaded parameter precision differs: {sorted(observed)}")
    return {
        "selected_precision": precision,
        "parameter_dtypes": sorted(observed),
        "parameter_count": sum(p.numel() for p in model.parameters()),
        "parameter_bytes": sum(p.numel() * p.element_size() for p in model.parameters()),
    }


class PrecisionAudit:
    """Observe actual floating intermediates and logits; refuse mixed FP32 execution."""

    def __init__(self, model: Any, selected: str):
        self.identity = verify_parameters(model, selected)
        self.selected = selected
        self.dtypes: set[str] = set()
        self.logit_dtypes: set[str] = set()
        self.hooks: list[Any] = []
        self.hooks.append(model.register_forward_pre_hook(self._before))
        for _name, module in model.named_modules():
            if not list(module.children()):
                self.hooks.append(module.register_forward_hook(self._observe))
        self.hooks.append(model.lm_head.register_forward_hook(self._logits))

    def _before(self, module: Any, args: Any) -> None:
        import torch

        if self.selected == "float32" and (
            torch.is_autocast_enabled("cuda")
            or torch.is_autocast_enabled("cpu")
            or torch.backends.cuda.matmul.allow_tf32
            or torch.backends.cudnn.allow_tf32
            or torch.get_float32_matmul_precision() != "highest"
        ):
            raise ValueError("FP32 runtime precision settings changed")

    def _observe(self, module: Any, args: Any, output: Any) -> None:
        if isinstance(output, dict):
            for value in output.values():
                self._observe(module, args, value)
        elif isinstance(output, tuple | list):
            for value in output:
                self._observe(module, args, value)
        elif hasattr(output, "is_floating_point") and output.is_floating_point():
            dtype = str(output.dtype)
            self.dtypes.add(dtype)
            if self.selected == "float32" and dtype != "torch.float32":
                raise ValueError(f"FP32 intermediate has dtype {dtype}")

    def _logits(self, module: Any, args: Any, output: Any) -> None:
        self.logit_dtypes.add(str(output.dtype))
        if str(output.dtype) != f"torch.{self.selected}":
            raise ValueError("final logits differ from selected precision")

    def report(self) -> dict[str, Any]:
        if not self.dtypes or not self.logit_dtypes:
            raise ValueError("precision audit has no executed forwards")
        return {
            **self.identity,
            "intermediate_dtypes": sorted(self.dtypes),
            "logit_dtypes": sorted(self.logit_dtypes),
        }

    def close(self) -> None:
        for hook in self.hooks:
            hook.remove()
