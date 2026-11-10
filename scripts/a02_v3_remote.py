"""Colab-side bootstrap for one authorized V3 zero-shot session (RES-541).

Executed by ``colab exec --file`` with ``A02_V3_REMOTE_STAGE`` set to ``prepare`` or ``work``.
Every session is a fresh VM, so each one prepares again; the plan budgets that.

* prepare: verify the uploaded source archive against the binding, extract it fresh, build the
  pinned inference environment with the reviewed V2 helper, then in a bounded child process run
  the reviewed V2 runtime qualification (field-level inventory and FP16 CUDA smoke) before any
  weights, and download and hash-verify the pinned weights and tokenizer.
* work: refuse unless prepare reported READY for this binding; in a bounded child, re-verify
  weights and tokenizer, load the pinned model, and advance the resumable checkpoint with the
  V3 worker until it completes or the stage deadline.

All provider-independent logic lives in ``a02_v3_worker``; this file only composes reviewed
primitives from ``a02_remote``, ``a02_dev_remote`` and ``a02_dev_runtime``.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

WORK = Path("/content/a02")
SOURCE_ARCHIVE = Path("/content/a02-v3-source.tar")
BINDING_PATH = Path("/content/a02-v3-binding.json")
CHECKPOINT = Path("/content/a02-v3-checkpoint.jsonl")
STATUS_PATH = Path("/content/a02-v3-status.json")
SOURCE_DIR = WORK / "v3-source"
BINDING_SCHEMA = "RES541_A02_V3_REMOTE_BINDING_V1"
CHILD_MARGIN_SECONDS = 30
_BINDING_KEYS = {
    "schema",
    "source_archive_sha256",
    "source_revision",
    "source_identity",
    "plan_sha256",
    "protocol_sha256",
    "session_index",
    "item_cost_bounds",
}


def load_binding(path: Path | None = None) -> dict[str, Any]:
    binding = json.loads((BINDING_PATH if path is None else path).read_bytes())
    if not isinstance(binding, dict) or set(binding) != _BINDING_KEYS:
        raise ValueError("V3 remote binding fields differ")
    if binding["schema"] != BINDING_SCHEMA:
        raise ValueError("V3 remote binding schema differs")
    costs = binding["item_cost_bounds"]
    if set(costs) != {"QUALIFICATION", "ZERO_SHOT_UNCONSTRAINED", "ZERO_SHOT_CONSTRAINED"} or any(
        not isinstance(v, int | float) or v <= 0 for v in costs.values()
    ):
        raise ValueError("V3 remote binding cost bounds are invalid")
    return binding


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_status(value: dict[str, Any]) -> None:
    temporary = STATUS_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
    os.replace(temporary, STATUS_PATH)


def _child_env(source: Path, stage: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}}
    env.update(
        PYTHONNOUSERSITE="1",
        PYTHONPATH=f"{source}:{source / 'src'}",
        A02_V3_CHILD_STAGE=stage,
        HF_HOME=str(WORK / "hf-cache"),
        HF_HUB_CACHE=str(WORK / "hf-cache/hub"),
        HF_HUB_DISABLE_TELEMETRY="1",
    )
    return env


def outer(stage: str, timeout: int, helpers: Any = None) -> int:
    """System-Python entry: environment setup, then a bounded pinned-Python child."""
    binding = load_binding()
    if _sha256_file(SOURCE_ARCHIVE) != binding["source_archive_sha256"]:
        raise ValueError("uploaded V3 source archive hash differs from the binding")
    if helpers is None:  # pragma: no cover - reviewed remote primitives
        if stage == "prepare":
            if SOURCE_DIR.exists():
                raise ValueError("V3 source directory already exists in this VM")
            SOURCE_DIR.mkdir(parents=True)
            sys.path[:0] = [str(Path(__file__).resolve().parent.parent)]
            from scripts import a02_dev_remote

            a02_dev_remote._safe_extract(SOURCE_ARCHIVE, SOURCE_DIR)
        sys.path[:0] = [str(SOURCE_DIR), str(SOURCE_DIR / "src")]
        from scripts import a02_dev_remote, a02_remote

        helpers = type(
            "Helpers",
            (),
            {
                "setup": staticmethod(
                    lambda: a02_remote._setup_inference(a02_remote._install_uv(), SOURCE_DIR)
                ),
                "child": staticmethod(a02_dev_remote._run_bounded_child),
            },
        )
    if stage == "prepare":
        _write_status({"status": "PREPARING", "plan_sha256": binding["plan_sha256"]})
        helpers.setup()
    else:
        status = json.loads(STATUS_PATH.read_bytes()) if STATUS_PATH.exists() else {}
        if status.get("status") != "READY" or status.get("plan_sha256") != binding["plan_sha256"]:
            raise ValueError("V3 work stage requires a READY prepare stage for this binding")
    result = helpers.child(
        [str(WORK / "inference-venv/bin/python"), str(SOURCE_DIR / "scripts/a02_v3_remote.py")],
        cwd=SOURCE_DIR,
        env=_child_env(SOURCE_DIR, stage),
        timeout=max(10, timeout - CHILD_MARGIN_SECONDS),
    )
    status = json.loads(STATUS_PATH.read_bytes()) if STATUS_PATH.exists() else {}
    status.setdefault("stages", []).append(
        {
            "stage": stage,
            "returncode": result.get("returncode"),
            "timed_out": result.get("timed_out"),
            "stderr_tail": result.get("stderr_tail"),
        }
    )
    _write_status(status)
    return 0 if result.get("returncode") == 0 and not result.get("timed_out") else 1


def child(stage: str, timeout: int) -> int:  # pragma: no cover - pinned GPU process
    """Pinned-Python entry: runtime qualification, weights and the resumable worker."""
    import time

    deadline = time.monotonic() + max(10, timeout - 2 * CHILD_MARGIN_SECONDS)
    from scripts import a02_dev_runtime, a02_remote
    from scripts import a02_v3_contract as v3
    from scripts import a02_v3_decision as decision
    from scripts import a02_v3_worker as worker

    binding = load_binding()
    protocol = decision.load_protocol()
    if decision.protocol_sha256() != binding["protocol_sha256"]:
        raise ValueError("extracted V3 protocol differs from the binding")
    profile = v3.load_profile()
    freeze = profile["tokenizer"]["files"]
    model = protocol["candidate_model"]
    import site

    import torch  # type: ignore[import-not-found]

    if stage == "prepare":
        inventory = a02_dev_runtime.inventory(torch, Path(site.getsitepackages()[0]))
        smoke = a02_dev_runtime.cuda_smoke(torch, inventory)
        qualification = a02_dev_runtime.qualify(inventory, smoke)
        if not qualification["qualified"]:
            _write_status({"status": "RUNTIME_INCOMPATIBLE", "qualification": qualification})
            return 2
        path, weights = a02_remote._weights(model["id"], model["revision"], torch, freeze)
        _write_status(
            {
                "status": "READY",
                "plan_sha256": binding["plan_sha256"],
                "snapshot_path": str(path),
                "weights": weights,
                "runtime_qualification": qualification,
            }
        )
        return 0
    status = json.loads(STATUS_PATH.read_bytes())
    snapshot = Path(status["snapshot_path"])
    for item in [*status["weights"]["weight_files"], *status["weights"]["support_files"].values()]:
        if _sha256_file(snapshot / item["name"]) != item["sha256"]:
            raise ValueError(f"V3 model asset changed: {item['name']}")
    for name, digest in freeze.items():
        if _sha256_file(snapshot / name) != digest:
            raise ValueError(f"V3 tokenizer file differs: {name}")
    from transformers import AutoModelForCausalLM, AutoTokenizer  # type: ignore[import-not-found]

    tokenizer = AutoTokenizer.from_pretrained(str(snapshot), local_files_only=True)
    lm = AutoModelForCausalLM.from_pretrained(
        str(snapshot), local_files_only=True, torch_dtype=torch.float16
    ).to("cuda")
    lm.eval()
    result = worker.run_worker(
        protocol=protocol,
        items=worker.work_items(protocol),
        checkpoint=CHECKPOINT,
        backend=worker.HFWorkerBackend(lm, tokenizer, model),
        deadline=deadline,
        item_cost_bounds=binding["item_cost_bounds"],
    )
    status.setdefault("work_results", []).append(result)
    _write_status(status)
    return 0 if result["status"] in {"COMPLETE", "PAUSED_AT_DEADLINE"} else 3


def main() -> int:  # pragma: no cover - remote entry point
    child_stage = os.environ.get("A02_V3_CHILD_STAGE")
    stage = child_stage or os.environ.get("A02_V3_REMOTE_STAGE", "")
    if stage not in {"prepare", "work"}:
        raise ValueError("A02_V3_REMOTE_STAGE must be prepare or work")
    timeout = int(os.environ.get("A02_V3_REMOTE_STAGE_TIMEOUT", "0"))
    if timeout < 60:
        raise ValueError("V3 remote stage timeout is missing or too small")
    return child(stage, timeout) if child_stage else outer(stage, timeout)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
