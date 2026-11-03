"""One bounded Colab GPU process for the frozen RES-541 A0.2 experiment."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import resource
import subprocess
import sys
import tarfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

MODEL_ID = "HuggingFaceTB/SmolLM3-3B"
MODEL_REVISION = "a07cc9a04f16550a088caea529712d1d335b0ac1"
ENGINE_PYTHON = "3.12.13"
UV_VERSION = "0.12.2"
SOURCE_ARCHIVE = Path("/content/a02-source.tar")
BINDING_PATH = Path("/content/a02-binding.json")
REMOTE_REPORT = Path("/content/a02-report.json")
WORK = Path("/content/a02")
HISTORICAL_DATE = datetime(2026, 10, 28, tzinfo=UTC)
A02_DATE = datetime(2026, 11, 3, tzinfo=UTC)
MAX_PROMPT_TOKENS = 1024
ACTION_TOKENS = 128
FINAL_TOKENS = 64
HISTORICAL_TOKENS = 64
WEIGHT_LIMIT = 8 * 1024**3
ENGINE_TIMEOUT = 20


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(
        value, allow_nan=False, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )


def _write_report(report: dict[str, Any]) -> None:
    REMOTE_REPORT.parent.mkdir(parents=True, exist_ok=True)
    temp = REMOTE_REPORT.with_suffix(".tmp")
    temp.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    temp.replace(REMOTE_REPORT)


def _run(command: list[str], *, cwd: Path | None = None, timeout: int = 120) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=os.environ.copy(),
    )
    if result.returncode:
        raise RuntimeError(
            f"command failed ({result.returncode}): {Path(command[0]).name}; "
            f"stderr={result.stderr[-1500:]}"
        )
    return result.stdout


def _safe_extract(archive: Path, destination: Path) -> None:
    with tarfile.open(archive, "r:") as source:
        members = source.getmembers()
        if not members or any(
            Path(member.name).is_absolute() or ".." in Path(member.name).parts for member in members
        ):
            raise ValueError("source archive contains an unsafe path")
        source.extractall(destination, members=members, filter="data")


def _install_uv() -> Path:
    uv_env = WORK / "uv-venv"
    if not (uv_env / "bin/python").exists():
        _run([sys.executable, "-m", "venv", str(uv_env)], timeout=45)
        _run(
            [
                str(uv_env / "bin/python"),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                f"uv=={UV_VERSION}",
            ],
            timeout=90,
        )
    uv = uv_env / "bin/uv"
    version = _run([str(uv), "--version"], timeout=10).strip().split()
    if len(version) < 2 or version[:2] != ["uv", UV_VERSION]:
        raise ValueError("remote uv version differs from the frozen runner")
    return uv


def _setup_engine(source: Path, uv: Path) -> Path:
    env = os.environ.copy()
    env.update(
        UV_CACHE_DIR=str(WORK / "uv-cache"),
        UV_PYTHON_INSTALL_DIR=str(WORK / "uv-python"),
        TMPDIR=str(WORK / "tmp"),
        PYTHONDONTWRITEBYTECODE="1",
    )
    Path(env["UV_CACHE_DIR"]).mkdir(parents=True, exist_ok=True)
    Path(env["UV_PYTHON_INSTALL_DIR"]).mkdir(parents=True, exist_ok=True)
    Path(env["TMPDIR"]).mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [str(uv), "python", "install", ENGINE_PYTHON], cwd=source, env=env, check=True, timeout=120
    )
    subprocess.run(
        [str(uv), "sync", "--frozen", "--all-groups", "--python", ENGINE_PYTHON],
        cwd=source,
        env=env,
        check=True,
        timeout=240,
    )
    engine_python = source / ".venv/bin/python"
    actual = _run(
        [str(engine_python), "-c", "import platform; print(platform.python_version())"],
        cwd=source,
        timeout=10,
    ).strip()
    if actual != ENGINE_PYTHON:
        raise ValueError(
            f"scientific engine Python changed: expected {ENGINE_PYTHON}, got {actual}"
        )
    return engine_python


def _setup_inference(uv: Path, source: Path) -> Path:
    inference_env = WORK / "inference-venv"
    if not inference_env.exists():
        subprocess.run(
            [
                str(uv),
                "venv",
                "--system-site-packages",
                "--python",
                sys.executable,
                str(inference_env),
            ],
            cwd=source,
            check=True,
            timeout=60,
        )
    inference_python = inference_env / "bin/python"
    requirements = source / "experiments/a0/requirements-colab.txt"
    subprocess.run(
        [
            str(uv),
            "pip",
            "install",
            "--python",
            str(inference_python),
            "--no-deps",
            "-r",
            str(requirements),
        ],
        cwd=source,
        check=True,
        timeout=180,
    )
    site = _run(
        [str(inference_python), "-c", "import site; print(site.getsitepackages()[0])"],
        cwd=source,
        timeout=10,
    ).strip()
    if site not in sys.path:
        sys.path.insert(0, site)
    if "transformers" in sys.modules:
        raise ValueError("Transformers loaded before the pinned inference environment")
    return inference_python


def _package_versions() -> dict[str, str]:
    names = [
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
    ]
    return {name: importlib.metadata.version(name) for name in names}


def _runtime_gate() -> tuple[Any, dict[str, Any]]:
    import torch  # type: ignore[import-not-found]

    from scripts import a01_runtime

    observed = a01_runtime.inventory()
    a01_runtime.qualify(observed)
    if str(torch.__version__) != "2.11.0+cu130" or torch.version.cuda != "13.0":
        raise ValueError("Colab PyTorch/CUDA differs from the reviewed A0.1 runtime profile")
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise ValueError("exactly one Colab CUDA GPU is required")
    properties = torch.cuda.get_device_properties(0)
    free_bytes, _ = torch.cuda.mem_get_info(0)
    if (
        "T4" not in properties.name
        or int(properties.total_memory) < 12 * 1024**3
        or free_bytes < 8 * 1024**3
    ):
        raise ValueError("T4 VRAM gate failed before model weight download")
    return torch, observed


def _weights(repo_id: str, revision: str, torch: Any) -> tuple[Path, dict[str, Any]]:
    from huggingface_hub import HfApi, snapshot_download  # type: ignore[import-not-found]

    model_info = HfApi().model_info(repo_id, revision=revision, files_metadata=True, token=False)
    if model_info.sha != revision:
        raise ValueError("Hugging Face resolved a different model revision")
    siblings = [item for item in model_info.siblings if item.rfilename.endswith(".safetensors")]
    total = sum(int(getattr(item, "size", 0) or 0) for item in siblings)
    if not siblings or total <= 0 or total > WEIGHT_LIMIT:
        raise ValueError("pinned model weight metadata exceeds the frozen 8 GiB bound")
    snapshot = Path(
        snapshot_download(
            repo_id,
            revision=revision,
            cache_dir=str(WORK / "hf-cache"),
            token=False,
            trust_remote_code=False,
        )
    )
    files = []
    for item in siblings:
        path = snapshot / item.rfilename
        if not path.is_file():
            raise ValueError(f"pinned model weight missing: {item.rfilename}")
        size = path.stat().st_size
        if getattr(item, "size", None) is not None and size != item.size:
            raise ValueError(f"pinned weight size mismatch: {item.rfilename}")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(8 * 1024**2), b""):
                digest.update(chunk)
        expected_lfs = getattr(getattr(item, "lfs", None), "sha256", None)
        actual = digest.hexdigest()
        if expected_lfs and actual != expected_lfs:
            raise ValueError(f"pinned weight content hash mismatch: {item.rfilename}")
        files.append(
            {
                "name": item.rfilename,
                "bytes": size,
                "sha256": actual,
                "hub_lfs_sha256": expected_lfs,
            }
        )
    if sum(row["bytes"] for row in files) > WEIGHT_LIMIT:
        raise ValueError("downloaded model weights exceed the frozen 8 GiB bound")
    memory = {
        "allocated_before_model_bytes": int(torch.cuda.memory_allocated(0)),
        "reserved_before_model_bytes": int(torch.cuda.memory_reserved(0)),
    }
    return snapshot, {
        "model_revision": model_info.sha,
        "weight_bytes": sum(x["bytes"] for x in files),
        "weight_files": files,
        **memory,
    }


class _Streamer:
    def __init__(self) -> None:
        self.prompt_seen = False
        self.first_token_s: float | None = None
        self.tokens: list[int] = []

    def put(self, value: Any) -> None:
        if not self.prompt_seen:
            self.prompt_seen = True
            return
        token_ids = value.reshape(-1).tolist()
        if token_ids:
            if self.first_token_s is None:
                self.first_token_s = time.perf_counter()
            self.tokens.extend(int(item) for item in token_ids)

    def end(self) -> None:
        return


def _message_envelope(origin: str, payload: str) -> str:
    value = (
        json.dumps(
            {"origin": origin, "payload": payload, "schema": "RES403-MODEL-TRANSCRIPT-1"},
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
    if len(value.encode("utf-8")) > 65536:
        raise ValueError("transcript message exceeds the frozen protocol bound")
    return value


def _final_request_text(request: dict[str, Any]) -> str:
    context = request.get("football_context", {})
    reduced = {
        key: request[key]
        for key in (
            "question",
            "objective",
            "measurement",
            "protocol",
            "observations",
            "source_documentation",
            "comparability_evidence",
            "missing_evidence",
            "user_provided_quoted_text",
        )
        if key in request
    }
    if isinstance(context, dict) and "population" in context:
        reduced["population"] = context["population"]
    return _canonical(reduced)


def _verify_event(
    event: dict[str, Any], case_id: str, interaction_id: str, action_sha: str
) -> None:
    value = dict(event)
    digest = value.pop("event_sha256", None)
    if (
        event.get("schema") != "RES541_A02_EXECUTOR_EVENT_V1"
        or event.get("case_id") != case_id
        or event.get("interaction_id") != interaction_id
        or event.get("action_sha256") != action_sha
        or digest != hashlib.sha256(_canonical(value).encode()).hexdigest()
    ):
        raise ValueError("CPU authority executor event binding failed on Colab")


def _generate(
    model: Any,
    tokenizer: Any,
    torch: Any,
    messages: list[dict[str, str]],
    *,
    cap: int,
    template_date: datetime,
) -> dict[str, Any]:
    kwargs = {"enable_thinking": False, "strftime_now": template_date.strftime}
    encoded = tokenizer.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        return_dict=True,
        return_tensors="pt",
        **kwargs,
    )
    ids = encoded["input_ids"][0].tolist()
    rendered = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True, **kwargs
    )
    if tokenizer.encode(rendered, add_special_tokens=False) != ids:
        raise ValueError("actual rendered chat prompt differs from its recorded token IDs")
    if len(ids) > MAX_PROMPT_TOKENS:
        raise ValueError("rendered chat prompt exceeds 1024 tokens")
    input_ids = encoded["input_ids"].to(model.device)
    attention_mask = encoded.get("attention_mask")
    if attention_mask is not None:
        attention_mask = attention_mask.to(model.device)
    streamer = _Streamer()
    start = time.perf_counter()
    torch.manual_seed(541)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(541)
    kwargs = {
        "input_ids": input_ids,
        "max_new_tokens": cap,
        "do_sample": False,
        "num_beams": 1,
        "pad_token_id": tokenizer.eos_token_id,
        "eos_token_id": tokenizer.eos_token_id,
        "streamer": streamer,
        "use_cache": True,
    }
    if attention_mask is not None:
        kwargs["attention_mask"] = attention_mask
    with torch.inference_mode():
        model.generate(**kwargs)
    elapsed = time.perf_counter() - start
    raw_text = tokenizer.decode(streamer.tokens, skip_special_tokens=True)
    rendered_raw = tokenizer.decode(streamer.tokens, skip_special_tokens=False)
    return {
        "seed": 541,
        "do_sample": False,
        "num_beams": 1,
        "max_new_tokens": cap,
        "prompt_text": rendered,
        "prompt_sha256": hashlib.sha256(rendered.encode()).hexdigest(),
        "prompt_token_ids": ids,
        "prompt_token_ids_sha256": hashlib.sha256(_canonical(ids).encode()).hexdigest(),
        "prompt_tokens": len(ids),
        "raw_text": raw_text,
        "raw_with_special_tokens": rendered_raw,
        "generated_token_ids": streamer.tokens,
        "generated_token_ids_sha256": hashlib.sha256(
            _canonical(streamer.tokens).encode()
        ).hexdigest(),
        "generated_tokens": len(streamer.tokens),
        "eos_seen": bool(streamer.tokens and streamer.tokens[-1] == tokenizer.eos_token_id),
        "truncated": not bool(streamer.tokens and streamer.tokens[-1] == tokenizer.eos_token_id),
        "first_token_latency_s": streamer.first_token_s - start if streamer.first_token_s else None,
        "generation_latency_s": elapsed,
        "template_date": template_date.strftime("%d %B %Y"),
    }


def _engine_call(process: subprocess.Popen[str], request: dict[str, Any]) -> dict[str, Any]:
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(_canonical(request) + "\n")
    process.stdin.flush()
    line = process.stdout.readline()
    if not line:
        raise RuntimeError("CPU authority executor exited without a response")
    response: object = json.loads(line)
    if not isinstance(response, dict):
        raise RuntimeError("CPU authority executor returned a non-object response")
    response = cast(dict[str, Any], response)
    if "executor_error" in response:
        raise RuntimeError(
            "CPU authority executor failed: "
            f"{response['executor_error']}: {response.get('error_message')}"
        )
    return response


def run() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "schema": "RES541_A02_REMOTE_REPORT_V1",
        "status": "RUNNING",
        "cases": [],
        "source": {},
    }
    engine_process: subprocess.Popen[str] | None = None
    stage = "BINDING"
    try:
        if REMOTE_REPORT.exists():
            raise ValueError("remote A02 report path already exists")
        binding = json.loads(BINDING_PATH.read_text(encoding="utf-8"))
        archive_bytes = SOURCE_ARCHIVE.read_bytes()
        if _sha(archive_bytes) != binding["source_archive_sha256"]:
            raise ValueError("uploaded source archive hash mismatch")
        source = WORK / "source"
        source.mkdir(parents=True, exist_ok=False)
        _safe_extract(SOURCE_ARCHIVE, source)
        if str(source) not in sys.path:
            sys.path.insert(0, str(source))
        report["source"] = {
            "run_id": binding["run_id"],
            "revision": binding["source_revision"],
            "tree": binding["source_tree"],
            "archive_sha256": binding["source_archive_sha256"],
            "protocol_sha256": binding["protocol_sha256"],
            "preflight_sha256": binding["preflight_sha256"],
        }
        protocol_bytes = (source / "experiments/a02/protocol-v1.json").read_bytes()
        if _sha(protocol_bytes) != binding["protocol_sha256"]:
            raise ValueError("uploaded A02 protocol hash differs from the owner-confirmed binding")
        protocol = json.loads(protocol_bytes)
        if (
            protocol["schema"] != "RES541_A02_PROTOCOL_V1"
            or protocol["status"] != "FROZEN_PRE_INFERENCE"
        ):
            raise ValueError("A02 protocol is not frozen")
        for name, expected in protocol["experiment_files"].items():
            if hashlib.sha256((source / name).read_bytes()).hexdigest() != expected:
                raise ValueError(f"frozen A02 source hash mismatch: {name}")
        science_files = {
            name: hashlib.sha256((source / name).read_bytes()).hexdigest()
            for name in protocol["scientific_source_files"]
        }
        if (
            science_files != protocol["scientific_source_files"]
            or hashlib.sha256(_canonical(science_files).encode()).hexdigest()
            != protocol["scientific_source_sha256"]
        ):
            raise ValueError("scientific source inventory differs from the frozen protocol")

        stage = "RUNTIME_SETUP"
        torch, inventory = _runtime_gate()
        uv = _install_uv()
        engine_python = _setup_engine(source, uv)
        inference_python = _setup_inference(uv, source)
        inference_site = _run(
            [str(inference_python), "-c", "import site; print(site.getsitepackages()[0])"],
            cwd=source,
        ).strip()
        if inference_site not in sys.path:
            sys.path.insert(0, inference_site)
        packages = _package_versions()
        expected_packages = {
            line.split("==", 1)[0]: line.split("==", 1)[1]
            for line in (source / "experiments/a0/requirements-colab.txt").read_text().splitlines()
            if line and not line.startswith("#")
        }
        if packages != expected_packages:
            raise ValueError("pinned inference package inventory differs")
        report["runtime"] = {
            "model_python": sys.version,
            "model_python_version": platform.python_version(),
            "scientific_engine_python": _run(
                [str(engine_python), "-c", "import platform; print(platform.python_version())"],
                cwd=source,
            ).strip(),
            "torch": str(torch.__version__),
            "torch_cuda_runtime": torch.version.cuda,
            "packages": packages,
            "gpu_name": torch.cuda.get_device_name(0),
            "compute_capability": list(torch.cuda.get_device_capability(0)),
            "total_vram_bytes": int(torch.cuda.get_device_properties(0).total_memory),
            "free_vram_before_weights_bytes": int(torch.cuda.mem_get_info(0)[0]),
            "runtime_inventory": inventory,
            "weight_dtype": "float16",
            "historical_action_decoding": {
                "do_sample": False,
                "num_beams": 1,
                "seed": 541,
                "max_prompt_tokens": MAX_PROMPT_TOKENS,
                "max_new_tokens": HISTORICAL_TOKENS,
                "enable_thinking": False,
                "template_date": HISTORICAL_DATE.strftime("%d %B %Y"),
            },
            "new_action_decoding": {
                "do_sample": False,
                "num_beams": 1,
                "seed": 541,
                "max_prompt_tokens": MAX_PROMPT_TOKENS,
                "max_new_tokens": ACTION_TOKENS,
                "enable_thinking": False,
                "template_date": A02_DATE.strftime("%d %B %Y"),
            },
            "final_decoding": {
                "do_sample": False,
                "num_beams": 1,
                "seed": 541,
                "max_prompt_tokens": MAX_PROMPT_TOKENS,
                "max_new_tokens": FINAL_TOKENS,
                "enable_thinking": False,
                "template_date": A02_DATE.strftime("%d %B %Y"),
            },
        }

        stage = "TOKENIZER_AND_MODEL_DOWNLOAD"
        os.environ["HF_HOME"] = str(WORK / "hf-cache")
        os.environ["HF_HUB_CACHE"] = str(WORK / "hf-cache/hub")
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "0"
        from transformers import (  # type: ignore[import-not-found]
            AutoModelForCausalLM,
            AutoTokenizer,
        )

        weights_path, weight_inventory = _weights(MODEL_ID, MODEL_REVISION, torch)
        tokenizer = AutoTokenizer.from_pretrained(
            weights_path,
            revision=MODEL_REVISION,
            local_files_only=True,
            trust_remote_code=False,
            use_fast=True,
        )
        tokenizer_manifest = json.loads(
            (source / "experiments/a02/tokenizer-files-v1.json").read_text()
        )
        if (
            tokenizer_manifest.get("model_revision") != MODEL_REVISION
            or tokenizer_manifest.get("model_id") != MODEL_ID
        ):
            raise ValueError("tokenizer manifest model identity differs")
        freeze_files = tokenizer_manifest["files"]
        tokenizer_files = {
            name: hashlib.sha256((weights_path / name).read_bytes()).hexdigest()
            for name in freeze_files
        }
        if tokenizer_files != freeze_files:
            raise ValueError("remote pinned tokenizer file hashes differ")
        if tokenizer.chat_template != (weights_path / "chat_template.jinja").read_text():
            raise ValueError("loaded tokenizer template differs from pinned Jinja bytes")
        torch.cuda.reset_peak_memory_stats(0)
        model_load_start = time.perf_counter()
        model = AutoModelForCausalLM.from_pretrained(
            weights_path,
            local_files_only=True,
            trust_remote_code=False,
            torch_dtype=torch.float16,
            device_map=0,
            low_cpu_mem_usage=True,
        )
        model.eval()
        report["model"] = {
            "id": MODEL_ID,
            "revision": MODEL_REVISION,
            "tokenizer_revision": MODEL_REVISION,
            "tokenizer_files": tokenizer_files,
            "chat_template_sha256": hashlib.sha256(tokenizer.chat_template.encode()).hexdigest(),
            "load_seconds": time.perf_counter() - model_load_start,
            **weight_inventory,
        }

        stage = "INFERENCE"
        engine_env = os.environ.copy()
        engine_env.pop("PYTHONHOME", None)
        engine_env["PYTHONPATH"] = f"{source}:{source / 'src'}"
        engine_env["PYTHONDONTWRITEBYTECODE"] = "1"
        engine_process = subprocess.Popen(
            [str(engine_python), str(source / "scripts/a02_engine.py"), "--serve"],
            cwd=source,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=open(WORK / "engine-stderr.log", "w"),
            text=True,
            bufsize=1,
            env=engine_env,
        )
        historical = json.loads((source / "experiments/a02/historical-inputs-v1.json").read_text())[
            "cases"
        ]
        new_cases = json.loads((source / "experiments/a02/cases-v1.json").read_text())["cases"]
        old_system = (source / "experiments/a01/system-prompt-v1.txt").read_text().rstrip("\n")
        new_system = (source / "experiments/a02/system-action-v1.txt").read_text().rstrip("\n")
        final_system = (source / "experiments/a02/system-final-v1.txt").read_text().rstrip("\n")
        prompt_started = time.perf_counter()

        def process_case(
            case_id: str,
            kind: str,
            user_text: str,
            final_text: str,
            user_message: str,
            system_prompt: str,
            date: datetime,
            action_cap: int,
            request_sha: str,
        ) -> None:
            interaction_id = f"{binding['run_id']}:{case_id}"
            action_messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ]
            action_generated = _generate(
                model, tokenizer, torch, action_messages, cap=action_cap, template_date=date
            )
            action_raw = action_generated["raw_text"]
            case_report: dict[str, Any] = {
                "case_id": case_id,
                "protocol": kind,
                "request_sha256": request_sha,
                "final_user_text": final_text,
                "final_user_text_sha256": hashlib.sha256(final_text.encode()).hexdigest(),
                "interaction_id": interaction_id,
                "user_message": user_text,
                "action_generation": action_generated,
                "case_status": "ACTION_GENERATED",
            }
            report["cases"].append(case_report)
            report["partial_case_count"] = len(report["cases"])
            _write_report(report)
            executor_start = time.perf_counter()
            engine_response = _engine_call(
                engine_process,
                {
                    "kind": kind,
                    "case_id": case_id,
                    "raw_action": action_raw,
                    "interaction_id": interaction_id,
                    "truncated": action_generated["truncated"],
                },
            )
            executor_ms = (time.perf_counter() - executor_start) * 1000
            case_report["engine_response"] = engine_response
            case_report["engine_roundtrip_ms"] = executor_ms
            case_report["case_status"] = "EXECUTOR_RECORDED"
            _write_report(report)
            if engine_response.get("request_sha256") != request_sha:
                raise ValueError(f"executor request binding mismatch: {case_id}")
            event = engine_response.get("event")
            if event:
                _verify_event(event, case_id, interaction_id, engine_response["action_sha256"])
            summary = {
                "origin": event["origin"] if event else "application_guard_refusal",
                "outcome": event.get("outcome") if event else "REFUSED",
                "reason_codes": event.get("reason_codes", [])
                if event
                else ["A02_EXECUTOR_EVENT_MISSING"],
                "value": event.get("value") if event else None,
                "unit": event.get("unit") if event else None,
                "claim_scope": "NUMERICAL_CHANGE_ONLY"
                if event and event.get("outcome") == "RESULT"
                else "NO_RESULT_AUTHORIZED",
            }
            action_envelope = _message_envelope("model_action_proposal", action_raw)
            final_messages = [
                {"role": "system", "content": final_system},
                {"role": "user", "content": _message_envelope("untrusted_user_input", final_text)},
                {"role": "assistant", "content": action_envelope},
                {"role": "tool", "content": _canonical(summary)},
            ]
            final_generated = _generate(
                model, tokenizer, torch, final_messages, cap=FINAL_TOKENS, template_date=A02_DATE
            )
            case_report.update(final_generation=final_generated, case_status="COMPLETE")
            report["partial_case_count"] = len(report["cases"])
            report["peak_allocated_vram_bytes"] = int(torch.cuda.max_memory_allocated(0))
            report["peak_reserved_vram_bytes"] = int(torch.cuda.max_memory_reserved(0))
            _write_report(report)

        for row in historical:
            process_case(
                row["case_id"],
                "historical",
                row["user_message"],
                row["user_message"],
                row["user_message"],
                old_system,
                HISTORICAL_DATE,
                HISTORICAL_TOKENS,
                row["user_message_sha256"],
            )
        for row in new_cases:
            request_text = _canonical(row["request"])
            user_message = _message_envelope("untrusted_user_input", request_text)
            final_text = _final_request_text(row["request"])
            process_case(
                row["case_id"],
                "new",
                request_text,
                final_text,
                user_message,
                new_system,
                A02_DATE,
                ACTION_TOKENS,
                row["request_sha256"],
            )

        report["status"] = "COMPLETE"
        report["runtime_seconds"] = time.perf_counter() - prompt_started
        report["total_prompt_tokens"] = sum(
            row["action_generation"]["prompt_tokens"] + row["final_generation"]["prompt_tokens"]
            for row in report["cases"]
        )
        report["total_generated_tokens"] = sum(
            row["action_generation"]["generated_tokens"]
            + row["final_generation"]["generated_tokens"]
            for row in report["cases"]
        )
        report["peak_allocated_vram_bytes"] = int(torch.cuda.max_memory_allocated(0))
        report["peak_reserved_vram_bytes"] = int(torch.cuda.max_memory_reserved(0))
        report["process_max_rss"] = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        _write_report(report)
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "case_count": len(report["cases"]),
                    "weights_on_remote": True,
                }
            )
        )
        return 0
    except Exception as exc:
        report.update(
            status="NO_GO",
            failure_stage=stage,
            failure_category=type(exc).__name__,
            failure_message=str(exc)[:2000],
            partial_case_count=len(report["cases"]),
        )
        _write_report(report)
        print(
            json.dumps({"status": "NO_GO", "stage": stage, "failure": type(exc).__name__}),
            file=sys.stderr,
        )
        return 1
    finally:
        if engine_process is not None:
            try:
                if engine_process.stdin:
                    engine_process.stdin.close()
                engine_process.wait(timeout=ENGINE_TIMEOUT)
            except Exception:
                engine_process.kill()
                engine_process.wait(timeout=5)


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
