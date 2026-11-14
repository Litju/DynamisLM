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
import math
import os
import re
import sys
import tarfile
import time
from pathlib import Path
from typing import Any

CONTENT_ROOT = Path(os.environ.get("A02_V3_CONTENT_ROOT", "/content"))
WORK = CONTENT_ROOT / "a02"
SOURCE_ARCHIVE = CONTENT_ROOT / "a02-v3-source.tar"
BINDING_PATH = CONTENT_ROOT / "a02-v3-binding.json"
CHECKPOINT = CONTENT_ROOT / "a02-v3-checkpoint.jsonl"
STATUS_PATH = CONTENT_ROOT / "a02-v3-status.json"
SOURCE_DIR = WORK / "v3-source"
BINDING_SCHEMA = "RES541_A02_V3_REMOTE_BINDING_V1"
FP32_BINDING_SCHEMA = "RES541_A1_FP32_CAMPAIGN_REMOTE_BINDING_V1"
NATIVE_CACHE_BINDING_SCHEMA = "RES541_A1_NATIVE_CACHE_CAMPAIGN_REMOTE_BINDING_V1"
TRAINING_BINDING_SCHEMA = "RES541_OWNER_LORA_REMOTE_BINDING_V1"
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
    diagnostic = isinstance(binding, dict) and binding.get("schema") == (
        "RES541_A1_DIAGNOSTIC_REMOTE_BINDING_V1"
    )
    native_cache = (
        isinstance(binding, dict) and binding.get("schema") == NATIVE_CACHE_BINDING_SCHEMA
    )
    fp32 = isinstance(binding, dict) and binding.get("schema") in {
        FP32_BINDING_SCHEMA,
        NATIVE_CACHE_BINDING_SCHEMA,
    }
    training = isinstance(binding, dict) and binding.get("schema") == TRAINING_BINDING_SCHEMA
    keys = _BINDING_KEYS | {"numerical_diagnostic"} if diagnostic else _BINDING_KEYS
    if fp32:
        keys = keys | {"precision", "numerical_amendment_sha256"}
    if native_cache:
        keys = keys | {"native_cache"}
    if training:
        keys = (_BINDING_KEYS - {"item_cost_bounds"}) | {
            "training_spec",
            "training_checkpoint_sha256",
        }
    if not isinstance(binding, dict) or set(binding) != keys:
        raise ValueError("V3 remote binding fields differ")
    if not diagnostic and not fp32 and not training and binding["schema"] != BINDING_SCHEMA:
        raise ValueError("V3 remote binding schema differs")
    if fp32 and binding["precision"] != "float32":
        raise ValueError("A1 campaign requires explicitly selected FP32")
    if native_cache and binding["native_cache"] is not True:
        raise ValueError("native cache execution must explicitly be selected")
    identity = binding["source_identity"]
    if (
        not isinstance(identity, dict)
        or set(identity) != {"commit", "tree"}
        or any(
            not isinstance(v, str) or re.fullmatch(r"[0-9a-f]{40}", v) is None
            for v in identity.values()
        )
        or binding["source_revision"] != identity["commit"]
    ):
        raise ValueError("V3 source identity differs")
    if not training:
        costs = binding["item_cost_bounds"]
        if set(costs) != {
            "QUALIFICATION",
            "ZERO_SHOT_UNCONSTRAINED",
            "ZERO_SHOT_CONSTRAINED",
        } or any(not isinstance(v, int | float) or v <= 0 for v in costs.values()):
            raise ValueError("V3 remote binding cost bounds are invalid")
    return binding


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_status(value: dict[str, Any]) -> None:
    value = {
        **value,
        "binding": load_binding(),
        "checkpoint_sha256": _sha256_file(CHECKPOINT) if CHECKPOINT.exists() else None,
    }
    if "error_detail" in value:
        value["error_detail"] = re.sub(
            r"(?i)(token|password|secret|authorization)[\s:=]+(?:Bearer\s+)?\S+",
            r"\1=[REDACTED]",
            str(value["error_detail"]),
        )[:2000]
    if "stages" in value:
        for stage in value["stages"]:
            stage["stderr_tail"] = re.sub(
                r"(?i)(token|password|secret|authorization)[\s:=]+(?:Bearer\s+)?\S+",
                r"\1=[REDACTED]",
                str(stage.get("stderr_tail", "")),
            )[:2000]
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
    if os.environ.get("A02_V3_BOOTSTRAP_TEST") == "1":
        env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", CUDA_VISIBLE_DEVICES="")
    return env


def _safe_extract_source(archive: Path, destination: Path) -> None:
    # Colab exec runs this file in a kernel, so there is no __file__-based package root yet.
    with tarfile.open(archive, "r:") as source:
        members = source.getmembers()
        if not members or any(
            Path(member.name).is_absolute() or ".." in Path(member.name).parts for member in members
        ):
            raise ValueError("V3 source archive contains an unsafe path")
        source.extractall(destination, members=members, filter="data")


def outer(stage: str, timeout: int, helpers: Any = None) -> int:
    """System-Python entry: environment setup, then a bounded pinned-Python child."""
    outer_started = time.monotonic()
    binding = load_binding()
    if _sha256_file(SOURCE_ARCHIVE) != binding["source_archive_sha256"]:
        raise ValueError("uploaded V3 source archive hash differs from the binding")
    bootstrap_test = os.environ.get("A02_V3_BOOTSTRAP_TEST") == "1"
    if (
        bootstrap_test
        and binding["plan_sha256"] != hashlib.sha256(b"synthetic CPU bootstrap plan").hexdigest()
    ):
        raise ValueError("CPU rehearsal cannot use a production plan binding")
    if stage == "work":
        status = json.loads(STATUS_PATH.read_bytes()) if STATUS_PATH.exists() else {}
        expected = "BOOTSTRAP_TEST_READY" if bootstrap_test else "READY"
        if (
            status.get("status") != expected
            or status.get("plan_sha256") != binding["plan_sha256"]
            or status.get("binding") != binding
        ):
            raise ValueError("V3 work stage requires a READY prepare stage for this binding")
    if helpers is None:  # pragma: no cover - reviewed remote primitives
        if stage == "prepare":
            if SOURCE_DIR.exists():
                raise ValueError("V3 source directory already exists in this VM")
            SOURCE_DIR.mkdir(parents=True)
            _safe_extract_source(SOURCE_ARCHIVE, SOURCE_DIR)
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
        if not bootstrap_test:
            helpers.setup()
            if "training_spec" in binding:
                from scripts import a02_remote

                # The training overlay must preserve inherited torch.
                a02_remote._run(
                    [
                        str(a02_remote._install_uv()),
                        "pip",
                        "install",
                        "--python",
                        str(WORK / "inference-venv/bin/python"),
                        "--no-deps",
                        "--only-binary=:all:",
                        "-r",
                        str(SOURCE_DIR / "experiments/a02/training-requirements-v1.txt"),
                    ],
                    cwd=SOURCE_DIR,
                    stage="PINNED_PEFT_INSTALL",
                    timeout=120,
                )
    child_seconds = max(
        1, math.floor(timeout - (time.monotonic() - outer_started) - CHILD_MARGIN_SECONDS)
    )
    child_env = _child_env(SOURCE_DIR, stage)
    child_env["A02_V3_REMOTE_STAGE_TIMEOUT"] = str(child_seconds)
    result = helpers.child(
        [str(WORK / "inference-venv/bin/python"), str(SOURCE_DIR / "scripts/a02_v3_remote.py")],
        cwd=SOURCE_DIR,
        env=child_env,
        timeout=child_seconds,
    )
    status = json.loads(STATUS_PATH.read_bytes()) if STATUS_PATH.exists() else {}
    if stage == "prepare":
        status["prepare_seconds"] = time.monotonic() - outer_started
    status.setdefault("stages", []).append(
        {
            "stage": stage,
            "returncode": result.get("returncode"),
            "timed_out": result.get("timed_out"),
            "stderr_tail": result.get("stderr_tail"),
        }
    )
    clean = result.get("returncode") == 0 and result.get("timed_out") is False
    if not clean or (
        stage == "prepare" and status.get("status") not in {"READY", "BOOTSTRAP_TEST_READY"}
    ):
        status.update(
            status="EXECUTION_FAILED",
            failure_stage=stage,
            failure_category="CHILD_TIMEOUT"
            if result.get("timed_out")
            else "CHILD_EXIT_OR_INCOMPLETE_STATUS",
            child_timeout_seconds=child_seconds,
        )
        clean = False
    _write_status(status)
    return 0 if clean else 1


def child(stage: str, timeout: int) -> int:  # pragma: no cover - pinned GPU process
    """Pinned-Python entry: runtime qualification, weights and the resumable worker."""
    import time

    started = time.monotonic()
    deadline = started + max(10, timeout - 2 * CHILD_MARGIN_SECONDS)
    from scripts import a02_dev_runtime, a02_remote
    from scripts import a02_v3_contract as v3
    from scripts import a02_v3_decision as decision
    from scripts import a02_v3_worker as worker

    binding = load_binding()
    protocol = decision.load_protocol()
    if "numerical_diagnostic" in binding:
        from scripts import a02_v3_gpu_diagnostic as diagnostic

        diagnostic.validate_specification(binding["numerical_diagnostic"])
    if binding.get("precision") == "float32":
        from scripts.a02_v3_gpu_diagnostic import AMENDMENT

        if _sha256_file(AMENDMENT) != binding["numerical_amendment_sha256"]:
            raise ValueError("FP32 campaign numerical amendment differs")
    if "training_spec" in binding:
        from scripts import a02_v3_training as training

        training.validate_specification(binding["training_spec"])
    if decision.protocol_sha256() != binding["protocol_sha256"]:
        raise ValueError("extracted V3 protocol differs from the binding")
    if os.environ.get("A02_V3_BOOTSTRAP_TEST") == "1":
        status = json.loads(STATUS_PATH.read_bytes()) if STATUS_PATH.exists() else {}
        from scripts.a02_v3_cpu_rehearsal import rehearse

        tokenizer_path = os.environ.get("A02_V3_CPU_TOKENIZER")
        if not tokenizer_path:
            raise ValueError("CPU rehearsal requires offline pinned tokenizer")
        rehearsal = rehearse(Path(tokenizer_path), CONTENT_ROOT / f"cpu-{stage}-synthetic.jsonl")
        status.update(
            cpu_rehearsal=rehearsal,
            status="BOOTSTRAP_TEST_READY" if stage == "prepare" else "BOOTSTRAP_TEST_COMPLETE",
            plan_sha256=binding["plan_sha256"],
            bootstrap_test={
                "stage": stage,
                "python_executable": sys.executable,
                "cwd": str(Path.cwd()),
                "pythonpath": os.environ.get("PYTHONPATH"),
                "child_stage": os.environ.get("A02_V3_CHILD_STAGE"),
                "source_revision": binding["source_revision"],
                "source_archive_sha256": _sha256_file(SOURCE_ARCHIVE),
                "imports": [
                    name
                    for name in (
                        "scripts.a02_dev_runtime",
                        "scripts.a02_remote",
                        "scripts.a02_v3_contract",
                        "scripts.a02_v3_decision",
                        "scripts.a02_v3_worker",
                    )
                    if name in sys.modules
                ],
                "torch_imported": "torch" in sys.modules,
                "transformers_imported": "transformers" in sys.modules,
            },
        )
        _write_status(status)
        return 0
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
        _write_status(
            {
                "status": "RUNTIME_QUALIFIED",
                "runtime_qualification": qualification,
                "prepare_phase": "PINNED_MODEL_DOWNLOAD_AND_HASH_VERIFY",
            }
        )
        path, weights = a02_remote._weights(model["id"], model["revision"], torch, freeze)
        _write_status(
            {
                "status": "READY",
                "plan_sha256": binding["plan_sha256"],
                "snapshot_path": str(path),
                "weights": weights,
                "runtime_qualification": qualification,
                "prepare_seconds": time.monotonic() - started,
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
    if "training_spec" in binding:
        training_root = CONTENT_ROOT / "a02-training"
        prior = CONTENT_ROOT / "a02-training-prior.tar"
        expected_prior = binding["training_checkpoint_sha256"]
        if expected_prior is None:
            if prior.exists():
                raise ValueError("unbound training checkpoint present")
        elif not prior.is_file() or _sha256_file(prior) != expected_prior:
            raise ValueError("training recovery archive differs")
        report_path = CONTENT_ROOT / "a02-training-report.jsonl"
        if report_path.exists():
            raise ValueError("training work already executed in this session; no retry")

        def training_emit(value: dict[str, Any]) -> None:
            with report_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(value, sort_keys=True, allow_nan=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())

        identity = {
            "source_identity": binding["source_identity"],
            "source_archive_sha256": binding["source_archive_sha256"],
            "plan_sha256": binding["plan_sha256"],
        }
        result = training.run(
            snapshot,
            training_root,
            binding["training_spec"],
            identity,
            deadline=deadline,
            emit=training_emit,
            prior=prior if expected_prior is not None else None,
        )
        status.update(
            status="TRAINING_COMPLETE" if result["completed"] else "TRAINING_PAUSED",
            training_result=result,
            training_report_sha256=_sha256_file(report_path),
            training_checkpoint_sha256=_sha256_file(training_root / "checkpoint.tar"),
        )
        _write_status(status)
        return 0
    if "numerical_diagnostic" in binding:
        report_path = CONTENT_ROOT / "a02-v3-diagnostic.jsonl"
        if report_path.exists():
            raise ValueError("diagnostic evidence already exists; no retry")

        def emit(value: dict[str, Any]) -> None:
            with report_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(value, sort_keys=True) + "\n")
                stream.flush()
                os.fsync(stream.fileno())

        result = diagnostic.run(
            snapshot,
            deadline=deadline,
            emit=emit,
            prepare_seconds=status["prepare_seconds"] + time.monotonic() - started,
            diagnostic_spec=binding["numerical_diagnostic"],
        )
        status.update(
            status="DIAGNOSTIC_COMPLETE" if result["passed"] else "DIAGNOSTIC_FAILED",
            diagnostic_sha256=_sha256_file(report_path),
        )
        _write_status(status)
        return 0 if result["passed"] else 3
    from transformers import AutoModelForCausalLM, AutoTokenizer  # type: ignore[import-not-found]

    tokenizer = AutoTokenizer.from_pretrained(str(snapshot), local_files_only=True)
    audit = None
    if binding.get("precision") == "float32":
        from scripts.a02_v3_precision import PrecisionAudit, load_model

        lm = load_model(snapshot, "float32")
        audit = PrecisionAudit(lm, "float32")
    else:
        lm = AutoModelForCausalLM.from_pretrained(
            str(snapshot), local_files_only=True, torch_dtype=torch.float16
        ).to("cuda")
        lm.eval()
    backend = worker.HFWorkerBackend(
        lm, tokenizer, model, native_cache=True if binding.get("native_cache") is True else None
    )
    if binding.get("native_cache") is True:
        calibration = worker.calibration_examples(protocol)[-1]
        prompt = v3.build_action_prompt(tokenizer, calibration["request"])
        backend.generate_native(
            prompt["prompt_token_ids"], profile["decoding"]["action_max_new_tokens"]
        )
        measured = backend.native_measurements[-1]
        status["native_cache_calibration"] = {
            **measured,
            "example_id": decision.example_id(calibration),
            "prompt_sha256": prompt["rendered_prompt_sha256"],
        }
        _write_status(status)
        if measured["seconds"] > binding["item_cost_bounds"]["ZERO_SHOT_UNCONSTRAINED"]:
            raise ValueError(
                "cached native calibration exceeds projected bound; no held-out evaluation"
            )
    result = worker.run_worker(
        protocol=protocol,
        items=worker.work_items(protocol),
        checkpoint=CHECKPOINT,
        backend=backend,
        deadline=deadline,
        item_cost_bounds=binding["item_cost_bounds"],
    )
    status.setdefault("work_results", []).append(result)
    if backend.native_measurements:
        status["native_cache_measurements"] = backend.native_measurements
    if audit is not None:
        status["precision_audit"] = (
            audit.report() if audit.logit_dtypes else {**audit.identity, "executed_forwards": False}
        )
        audit.close()
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
    try:
        return child(stage, timeout) if child_stage else outer(stage, timeout)
    except Exception as exc:
        status = json.loads(STATUS_PATH.read_bytes()) if STATUS_PATH.exists() else {}
        status.update(
            status="EXECUTION_FAILED",
            failure_stage=stage,
            error_type=type(exc).__name__,
            error_detail=str(exc),
        )
        _write_status(status)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
