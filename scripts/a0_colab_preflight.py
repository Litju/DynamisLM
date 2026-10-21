"""GPU-only Colab preflight for RES-541; never imports or downloads model weights."""

from __future__ import annotations

import json
import platform
import shutil
from pathlib import Path

MIN_TOTAL_GPU_GIB = 12
GIB = 1024**3
SMOLLM3_FP16_WEIGHT_FLOOR_BYTES = 6_150_197_248


def main() -> int:
    try:
        import torch  # type: ignore[import-not-found]
    except ImportError:
        print(
            json.dumps(
                {
                    "schema": "RES541_COLAB_PREFLIGHT_V1",
                    "status": "TORCH_UNAVAILABLE",
                    "python": platform.python_version(),
                },
                sort_keys=True,
            )
        )
        return 3

    devices: list[dict[str, object]] = []
    if torch.cuda.is_available():
        for index in range(torch.cuda.device_count()):
            properties = torch.cuda.get_device_properties(index)
            devices.append(
                {
                    "index": index,
                    "name": properties.name,
                    "compute_capability": list(torch.cuda.get_device_capability(index)),
                    "total_memory_gib": round(properties.total_memory / GIB, 3),
                    "fp16_weight_floor_gib": round(SMOLLM3_FP16_WEIGHT_FLOOR_BYTES / GIB, 3),
                }
            )

    enough_device_memory = any(
        isinstance(device["total_memory_gib"], float)
        and device["total_memory_gib"] >= MIN_TOTAL_GPU_GIB
        for device in devices
    )
    report = {
        "schema": "RES541_COLAB_PREFLIGHT_V1",
        "status": (
            "PRELIMINARY_CAPACITY"
            if enough_device_memory
            else ("INSUFFICIENT_VRAM" if devices else "CUDA_UNAVAILABLE")
        ),
        "python": platform.python_version(),
        "torch": str(torch.__version__),
        "pytorch_cuda_runtime": torch.version.cuda,
        "cuda_available": torch.cuda.is_available(),
        "device_count": len(devices),
        "devices": devices,
        "disk_free_gib": round(shutil.disk_usage(Path.cwd()).free / GIB, 3),
        "model_weights_downloaded": False,
        "inference_run": False,
        "training_run": False,
        "memory_note": "Weight bytes are a floor, not peak runtime VRAM.",
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if enough_device_memory else 2


if __name__ == "__main__":
    raise SystemExit(main())
