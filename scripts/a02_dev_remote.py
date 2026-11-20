"""Remote inference worker for the prospective RES-541 A0.2 V2 development profile."""

from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

WORK = Path("/content/a02")
SOURCE_ARCHIVE = Path("/content/a02-source.tar")
BINDING_PATH = Path("/content/a02-binding.json")
REMOTE_REPORT = Path("/content/a02-report.json")
DEVELOPMENT_PREFLIGHT_PATH = Path("/content/a02-development-preflight-v2.json")
MODEL_ID = "HuggingFaceTB/SmolLM3-3B"
MODEL_REVISION = "a07cc9a04f16550a088caea529712d1d335b0ac1"
ENGINE_PYTHON = "3.12.13"
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_SECRET = re.compile(
    r"(?i)(authorization\s*:\s*bearer\s+|(?:token|secret|password|api[_-]?key)\s*[:=]\s*)\S+"
)
_GITHUB_SECRET = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{40,})\b")
_AWS_SECRET = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
MAX_PROMPT_TOKENS = 1024


def _generate(
    model: Any,
    tokenizer: Any,
    torch: Any,
    messages: list[dict[str, str]],
    *,
    cap: int,
    template_date: datetime,
    prompt_limit: int,
    xml_tools: list[dict[str, Any]] | None = None,
    frozen_prompt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from scripts import a02_remote

    kwargs: dict[str, Any] = {
        "enable_thinking": False,
        "strftime_now": template_date.strftime,
    }
    if xml_tools is not None:
        kwargs["xml_tools"] = xml_tools
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
        raise ValueError("V2 prompt rendering differs from its token IDs")
    if frozen_prompt is not None:
        from scripts import a02_prompt

        prompt_token_ids_sha256 = a02_prompt.prompt_token_ids_sha256(ids)
    else:
        prompt_token_ids_sha256 = hashlib.sha256(a02_remote._canonical(ids).encode()).hexdigest()
    if frozen_prompt is not None:
        from scripts import a02_prompt

        a02_prompt.verify_frozen_prompt(rendered, ids, frozen_prompt, frozen_prompt["case_id"])
        prompt_token_ids_sha256 = frozen_prompt["prompt_token_ids_sha256"]
    if len(ids) > prompt_limit:
        raise ValueError(f"V2 prompt exceeds its {prompt_limit}-token bound")
    input_ids = encoded["input_ids"].to(model.device)
    attention_mask = encoded.get("attention_mask")
    if attention_mask is not None:
        attention_mask = attention_mask.to(model.device)
    streamer = a02_remote._Streamer()
    start = time.perf_counter()
    torch.manual_seed(541)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(541)
    generation_kwargs = {
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
        generation_kwargs["attention_mask"] = attention_mask
    with torch.inference_mode():
        model.generate(**generation_kwargs)
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
        "prompt_token_ids_sha256": prompt_token_ids_sha256,
        "prompt_tokens": len(ids),
        "raw_text": raw_text,
        "raw_with_special_tokens": rendered_raw,
        "generated_token_ids": streamer.tokens,
        "generated_token_ids_sha256": hashlib.sha256(
            a02_remote._canonical(streamer.tokens).encode()
        ).hexdigest(),
        "generated_tokens": len(streamer.tokens),
        "eos_seen": bool(streamer.tokens and streamer.tokens[-1] == tokenizer.eos_token_id),
        "truncated": not bool(streamer.tokens and streamer.tokens[-1] == tokenizer.eos_token_id),
        "first_token_latency_s": (
            streamer.first_token_s - start if streamer.first_token_s is not None else None
        ),
        "generation_latency_s": elapsed,
        "template_date": template_date.strftime("%d %B %Y"),
    }


def _initial_report(binding: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "RES541_A02_DEVELOPMENT_REPORT_V2",
        "status": "RUNNING",
        "cases": [],
        "stage_history": [],
        "current_stage": "REMOTE_ENTRYPOINT",
        "last_completed_stage": None,
        "partial_case_count": 0,
        "source": {
            "run_id": binding["run_id"],
            "revision": binding["source_revision"],
            "tree": binding["source_tree"],
            "archive_sha256": binding["source_archive_sha256"],
            "protocol_sha256": binding["protocol_sha256"],
            "preflight_sha256": binding["development_preflight_sha256"],
            "development_profile_sha256": binding["development_profile_sha256"],
            "development_preflight_sha256": binding["development_preflight_sha256"],
            "runtime_policy_id": binding["runtime_policy_id"],
            "runtime_policy_sha256": binding["runtime_policy_sha256"],
            "baseline_remote_report_sha256": binding["baseline_remote_report_sha256"],
        },
    }


def _write_report(report: dict[str, Any]) -> None:
    REMOTE_REPORT.parent.mkdir(parents=True, exist_ok=True)
    temporary = REMOTE_REPORT.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, REMOTE_REPORT)
    directory_fd = os.open(REMOTE_REPORT.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _mark_stage(report: dict[str, Any], stage: str, status: str, **fields: Any) -> None:
    report["current_stage"] = stage
    report.setdefault("stage_history", []).append(
        {"stage": stage, "status": status, "recorded_at_utc": datetime.now(UTC).isoformat()}
    )
    if status == "COMPLETE":
        report["last_completed_stage"] = stage
    report.update(fields)
    _write_report(report)


def _safe_excerpt(value: str | bytes | None, limit: int = 4000) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    value = _ANSI.sub("", value).replace("\x00", "")
    value = _SECRET.sub(r"\1[REDACTED]", value)
    value = _GITHUB_SECRET.sub("[REDACTED_GITHUB_TOKEN]", value)
    value = _AWS_SECRET.sub("[REDACTED_AWS_KEY]", value)
    return value[-limit:]


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024**2), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_extract(archive: Path, destination: Path) -> None:
    with tarfile.open(archive, "r:") as source:
        members = source.getmembers()
        if not members or any(
            Path(member.name).is_absolute() or ".." in Path(member.name).parts for member in members
        ):
            raise ValueError("V2 source archive contains an unsafe path")
        source.extractall(destination, members=members, filter="data")


def _run_bounded_child(
    command: list[str], *, cwd: Path, env: dict[str, str], timeout: int
) -> dict[str, Any]:
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )
        timed_out = False
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()

        def tail(stream: Any) -> str:
            stream.seek(0, os.SEEK_END)
            stream.seek(max(0, stream.tell() - 16_384))
            return _safe_excerpt(stream.read())

        return {
            "returncode": process.returncode,
            "timed_out": timed_out,
            "stdout_tail": tail(stdout),
            "stderr_tail": tail(stderr),
        }


def _record_failure(report: dict[str, Any], stage: str, exc: BaseException) -> None:
    report.update(
        status="EXTERNAL_BLOCKER",
        failure_stage=stage,
        failure_category=type(exc).__name__,
        failure_message=_safe_excerpt(str(exc), 1000),
        partial_case_count=len(report.get("cases", [])),
    )
    evidence = getattr(exc, "evidence", None)
    if isinstance(evidence, dict):
        report["command_failure"] = evidence
    timeout = exc if isinstance(exc, subprocess.TimeoutExpired) else exc.__cause__
    if isinstance(timeout, subprocess.TimeoutExpired):
        report["command_output"] = {
            "stdout_tail": _safe_excerpt(timeout.output),
            "stderr_tail": _safe_excerpt(timeout.stderr),
        }
    _mark_stage(report, stage, "FAILED")


def _stage_timeout(binding: dict[str, Any], stage: str) -> int:
    ceiling = binding.get("remote_stage_timeouts_seconds", {}).get(stage)
    if type(ceiling) is not int or not 30 <= ceiling <= 720:
        raise ValueError("V2 remote stage timeout is invalid")
    requested = os.environ.get("A02_DEV_REMOTE_STAGE_TIMEOUT")
    if requested is None:
        return ceiling
    try:
        timeout = int(requested)
    except ValueError as exc:
        raise ValueError("V2 requested remote stage timeout is invalid") from exc
    if not 30 <= timeout <= ceiling:
        raise ValueError("V2 requested remote stage timeout exceeds its bound")
    return timeout


def _run_isolated_inference(stage: str) -> int:
    binding = json.loads(BINDING_PATH.read_bytes())
    if not isinstance(binding, dict) or binding.get("execution_mode") != "development_v2":
        raise ValueError("A0.2 V2 run binding is invalid")
    if stage not in {"prepare", "infer"}:
        raise ValueError("V2 remote stage must be prepare or infer")
    if stage == "prepare":
        if REMOTE_REPORT.exists():
            raise ValueError("remote V2 report already exists; refusing to overwrite it")
        report = _initial_report(binding)
        _mark_stage(report, "REMOTE_PREPARE_ENTRY", "STARTED")
    else:
        if not REMOTE_REPORT.exists():
            report = _initial_report(binding)
            _record_failure(
                report,
                "INFERENCE_PREPARE_VALIDATION",
                ValueError("V2 inference stage has no completed prepare report"),
            )
            return 1
        report = json.loads(REMOTE_REPORT.read_bytes())
        if not isinstance(report, dict) or not isinstance(report.get("source"), dict):
            raise ValueError("V2 inference prepare report is invalid")
        if report["source"].get("run_id") != binding.get("run_id"):
            raise ValueError("V2 inference prepare report does not match the run binding")
        if report.get("status") != "READY_FOR_INFERENCE":
            if report.get("status") not in {"EXTERNAL_BLOCKER", "COMPLETE"}:
                _record_failure(
                    report,
                    "INFERENCE_PREPARE_VALIDATION",
                    ValueError("V2 inference stage is not bound to a completed prepare stage"),
                )
            return 1
        report["status"] = "RUNNING"
        _mark_stage(report, "REMOTE_INFERENCE_ENTRY", "STARTED")
    try:
        stage_timeout = _stage_timeout(binding, stage)
        WORK.mkdir(parents=True, exist_ok=True)
        _mark_stage(report, "SOURCE_ARCHIVE_VERIFY", "STARTED")
        archive_bytes = SOURCE_ARCHIVE.read_bytes()
        if hashlib.sha256(archive_bytes).hexdigest() != binding["source_archive_sha256"]:
            raise ValueError("uploaded V2 source archive hash mismatch")
        _mark_stage(report, "SOURCE_ARCHIVE_VERIFY", "COMPLETE")
        source = WORK / f"development-source-{binding['run_id']}"
        if stage == "prepare":
            _mark_stage(report, "SOURCE_EXTRACTION", "STARTED")
            source.mkdir(exist_ok=False)
            _safe_extract(SOURCE_ARCHIVE, source)
            _mark_stage(report, "SOURCE_EXTRACTION", "COMPLETE")
        elif not source.is_dir():
            raise ValueError("V2 prepared source directory is missing")
        for path in (source, source / "src"):
            if str(path) not in sys.path:
                sys.path.insert(0, str(path))
        from scripts import a02_remote

        if stage == "prepare":
            _mark_stage(report, "UV_SETUP", "STARTED")
            uv = a02_remote._install_uv()
            _mark_stage(report, "UV_SETUP", "COMPLETE")
            _mark_stage(report, "SCIENTIFIC_ENGINE_DEPENDENCIES", "STARTED")
            a02_remote._setup_engine(source, uv)
            _mark_stage(report, "SCIENTIFIC_ENGINE_DEPENDENCIES", "COMPLETE")
            _mark_stage(report, "INFERENCE_DEPENDENCIES", "STARTED")
            a02_remote._setup_inference(uv, source)
            _mark_stage(report, "INFERENCE_DEPENDENCIES", "COMPLETE")
        else:
            for required in (
                WORK / "uv-venv/bin/uv",
                source / ".venv/bin/python",
                WORK / "inference-venv/bin/python",
            ):
                if not required.is_file():
                    raise ValueError("V2 prepare artifact or pinned environment is missing")
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHONHOME", None)
        environment["PYTHONNOUSERSITE"] = "1"
        environment["PYTHONPATH"] = f"{source}:{source / 'src'}"
        environment["A02_DEV_V2_PINNED_PROCESS"] = "1"
        environment["A02_DEV_WORKER_STAGE"] = stage
        _mark_stage(report, f"WORKER_{stage.upper()}", "STARTED")
        child = _run_bounded_child(
            [
                str(WORK / "inference-venv/bin/python"),
                str(source / "scripts/a02_dev_remote.py"),
            ],
            cwd=source,
            env=environment,
            timeout=max(10, stage_timeout - 30),
        )
        latest = json.loads(REMOTE_REPORT.read_bytes()) if REMOTE_REPORT.is_file() else report
        latest.setdefault("remote_stage_commands", []).append(
            {
                "stage": stage,
                "returncode": child["returncode"],
                "timed_out": child["timed_out"],
                "stdout_tail": child["stdout_tail"],
                "stderr_tail": child["stderr_tail"],
                "timeout_seconds": stage_timeout - 30,
            }
        )
        if child["timed_out"] or child["returncode"] != 0:
            worker_failure_category = latest.get("failure_category")
            worker_failure_message = latest.get("failure_message")
            controller_failure_category = (
                "TimeoutExpired" if child["timed_out"] else "RemoteWorkerExit"
            )
            latest["controller_failure_category"] = controller_failure_category
            latest["controller_failure_message"] = (
                f"V2 {stage} worker did not complete its bounded stage."
            )
            if isinstance(worker_failure_category, str):
                latest["worker_failure_category"] = worker_failure_category
            if isinstance(worker_failure_message, str):
                latest["worker_failure_message"] = worker_failure_message
            latest["status"] = "EXTERNAL_BLOCKER"
            latest["failure_category"] = controller_failure_category
            latest["failure_message"] = latest["controller_failure_message"]
            _mark_stage(
                latest,
                latest.get("current_stage", f"WORKER_{stage.upper()}"),
                "TIMEOUT" if child["timed_out"] else "FAILED",
                failure_stage=latest.get("current_stage", f"WORKER_{stage.upper()}"),
                worker_stdout_tail=child["stdout_tail"],
                worker_stderr_tail=child["stderr_tail"],
            )
            return 1
        expected = "READY_FOR_INFERENCE" if stage == "prepare" else "COMPLETE"
        if latest.get("status") != expected:
            failure_stage = latest.get("current_stage", f"WORKER_{stage.upper()}")
            _record_failure(
                latest, failure_stage, RuntimeError(f"worker returned without {expected}")
            )
            return 1
        report = latest
        _mark_stage(report, f"REMOTE_{stage.upper()}", "COMPLETE")
        return 0
    except Exception as exc:
        if REMOTE_REPORT.is_file():
            try:
                latest = json.loads(REMOTE_REPORT.read_bytes())
                if latest.get("source", {}).get("run_id") == binding.get("run_id"):
                    report = latest
            except (OSError, json.JSONDecodeError):
                pass
        _record_failure(report, report.get("current_stage", stage.upper()), exc)
        return 1


def _run_inference_process(stage: str) -> int:
    binding = json.loads(BINDING_PATH.read_bytes())
    if stage not in {"prepare", "infer"}:
        raise ValueError("V2 worker stage must be prepare or infer")
    report = json.loads(REMOTE_REPORT.read_bytes())
    if report.get("source", {}).get("run_id") != binding.get("run_id"):
        raise ValueError("V2 progress report does not match the run binding")
    if stage == "infer" and report.get("status") != "RUNNING":
        raise ValueError("V2 inference worker did not receive an active stage report")
    if stage == "prepare" and report.get("status") != "RUNNING":
        raise ValueError("V2 prepare worker did not receive an active stage report")
    engine_process: subprocess.Popen[str] | None = None
    current_stage = "SOURCE_AND_PREFLIGHT_VALIDATION"
    try:
        _mark_stage(report, current_stage, "STARTED")
        archive_bytes = SOURCE_ARCHIVE.read_bytes()
        if hashlib.sha256(archive_bytes).hexdigest() != binding["source_archive_sha256"]:
            raise ValueError("uploaded V2 source archive hash mismatch")
        source = WORK / f"development-source-{binding['run_id']}"
        if not source.is_dir():
            raise ValueError("V2 source extraction is missing")
        for path in (source, source / "src"):
            if str(path) not in sys.path:
                sys.path.insert(0, str(path))
        from scripts import a02_dev_protocol, a02_dev_runtime, a02_experiment, a02_remote

        a02_dev_runtime.validate_binding(binding)

        profile_bytes = (source / "experiments/a02/development-profile-v2.json").read_bytes()
        if hashlib.sha256(profile_bytes).hexdigest() != binding["development_profile_sha256"]:
            raise ValueError("V2 profile hash differs from its run binding")
        profile = a02_dev_protocol.load_profile()
        preflight_bytes = DEVELOPMENT_PREFLIGHT_PATH.read_bytes()
        if hashlib.sha256(preflight_bytes).hexdigest() != binding["development_preflight_sha256"]:
            raise ValueError("V2 CPU preflight hash differs from its run binding")
        preflight = json.loads(preflight_bytes)
        if (
            preflight.get("schema") != "RES541_A02_DEVELOPMENT_PREFLIGHT_V2"
            or preflight.get("development_profile_sha256") != binding["development_profile_sha256"]
            or preflight.get("source_revision") != binding["source_revision"]
            or preflight.get("working_tree_clean") is not True
            or preflight.get("case_manifest_sha256") != profile["inputs"]["case_manifest_sha256"]
        ):
            raise ValueError("V2 preflight does not bind the owner-approved source and profile")
        protocol_bytes = (source / "experiments/a02/protocol-v1.json").read_bytes()
        if hashlib.sha256(protocol_bytes).hexdigest() != binding["protocol_sha256"]:
            raise ValueError("frozen A02 authority protocol hash differs")
        protocol = json.loads(protocol_bytes)
        for name, expected in protocol["experiment_files"].items():
            if hashlib.sha256((source / name).read_bytes()).hexdigest() != expected:
                raise ValueError(f"frozen A02 file changed: {name}")
        science_files = {
            name: hashlib.sha256((source / name).read_bytes()).hexdigest()
            for name in protocol["scientific_source_files"]
        }
        if (
            science_files != protocol["scientific_source_files"]
            or hashlib.sha256(a02_remote._canonical(science_files).encode()).hexdigest()
            != protocol["scientific_source_sha256"]
        ):
            raise ValueError("RES-70/RES-71 scientific source inventory differs")
        case_rows = json.loads(a02_experiment.CASES_PATH.read_bytes())["cases"]
        case_map = {row["case_id"]: row for row in case_rows}
        frozen = {row["case_id"]: row for row in preflight["cases"]}
        if set(case_map) != set(profile["case_ids"]) or set(frozen) != set(profile["case_ids"]):
            raise ValueError("V2 cases or preflight do not match the frozen ten-case profile")
        if preflight.get("action_case_count") != len(case_map):
            raise ValueError("V2 preflight case count differs")
        _mark_stage(report, current_stage, "COMPLETE")
        engine_python = source / ".venv/bin/python"
        inference_python = Path(sys.executable)
        if inference_python.parent.parent.resolve() != (WORK / "inference-venv").resolve():
            raise ValueError("V2 worker is not using the pinned inference environment")
        if not engine_python.is_file():
            raise ValueError("V2 scientific engine environment is missing")
        current_stage = "INFERENCE_RUNTIME_DEPENDENCY_CHECK"
        _mark_stage(report, current_stage, "STARTED")
        inference_site = a02_remote._run(
            [str(inference_python), "-c", "import site; print(site.getsitepackages()[0])"],
            cwd=source,
        ).strip()
        if inference_site not in sys.path:
            sys.path.insert(0, inference_site)
        expected_packages = {
            line.split("==", 1)[0]: line.split("==", 1)[1]
            for line in (source / "experiments/a0/requirements-colab.txt").read_text().splitlines()
            if line and not line.startswith("#")
        }
        packages = a02_remote._package_versions(expected_packages, Path(inference_site))
        scientific_engine_python = a02_remote._run(
            [str(engine_python), "-c", "import platform; print(platform.python_version())"],
            cwd=source,
        ).strip()
        _mark_stage(report, current_stage, "COMPLETE")
        current_stage = "GPU_RUNTIME_VALIDATION"
        _mark_stage(report, current_stage, "STARTED")
        torch_import_error: str | None = None
        try:
            import torch  # type: ignore[import-not-found]
        except Exception as exc:
            torch = None
            torch_import_error = f"{type(exc).__name__}: {str(exc)[:500]}"
        inventory = a02_dev_runtime.inventory(torch, Path(inference_site))
        if torch_import_error is not None:
            inventory["inventory_errors"]["torch_import"] = torch_import_error
        smoke = a02_dev_runtime.cuda_smoke(torch, inventory)
        qualification = a02_dev_runtime.qualify(inventory, smoke)
        torch_record = inventory["torch"]
        cuda_record = inventory["cuda"]
        report["runtime"] = {
            "model_python": sys.version,
            "model_python_version": inventory["python"]["version"],
            "scientific_engine_python": scientific_engine_python,
            "torch": torch_record["version"],
            "torch_module": {
                "version": torch_record["version"],
                "distribution_version": torch_record["distribution_version"],
                "origin": torch_record["module_origin"],
                "distribution_origin": torch_record["distribution_origin"],
            },
            "torch_cuda_runtime": torch_record["cuda_runtime"],
            "packages": packages,
            "gpu_name": cuda_record["name"],
            "compute_capability": cuda_record["compute_capability"],
            "total_vram_bytes": cuda_record["total_vram_bytes"],
            "free_vram_before_weights_bytes": cuda_record["free_vram_bytes"],
            "runtime_inventory": inventory,
            "runtime_qualification": qualification,
            "development_action_decoding": profile["decoding"],
        }
        _write_report(report)
        if not qualification["qualified"]:
            raise a02_dev_runtime.RuntimeQualificationError(qualification)
        _mark_stage(report, current_stage, "COMPLETE")

        os.environ["HF_HOME"] = str(WORK / "hf-cache")
        os.environ["HF_HUB_CACHE"] = str(WORK / "hf-cache/hub")
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "0"
        from transformers import (  # type: ignore[import-not-found]
            AutoModelForCausalLM,
            AutoTokenizer,
        )

        tokenizer_manifest = json.loads(
            (source / "experiments/a02/tokenizer-files-v1.json").read_text()
        )
        freeze_files = tokenizer_manifest["files"]
        if freeze_files != profile["tokenizer"]["files"]:
            raise ValueError("V2 tokenizer identity differs from the frozen V1 tokenizer")
        if stage == "prepare":
            current_stage = "MODEL_ASSET_DOWNLOAD"
            _mark_stage(report, current_stage, "STARTED")
            weights_path, weights = a02_remote._weights(
                MODEL_ID, MODEL_REVISION, torch, freeze_files
            )
            _mark_stage(report, current_stage, "COMPLETE")
        else:
            current_stage = "MODEL_ASSET_REUSE"
            _mark_stage(report, current_stage, "STARTED")
            assets = report.get("model_assets")
            if not isinstance(assets, dict) or assets.get("model_revision") != MODEL_REVISION:
                raise ValueError("V2 prepared model assets are missing or have the wrong revision")
            weights_path = Path(assets["snapshot_path"])
            weights = assets["weights"]
            for item in [*weights["weight_files"], *weights["support_files"].values()]:
                path = weights_path / item["name"]
                if (
                    not path.is_file()
                    or path.stat().st_size != item["bytes"]
                    or _file_sha256(path) != item["sha256"]
                ):
                    raise ValueError(f"V2 prepared model asset changed: {item['name']}")
            _mark_stage(report, current_stage, "COMPLETE")
        current_stage = "TOKENIZER_VERIFICATION"
        _mark_stage(report, current_stage, "STARTED")
        tokenizer = AutoTokenizer.from_pretrained(
            weights_path,
            revision=MODEL_REVISION,
            local_files_only=True,
            trust_remote_code=False,
            use_fast=True,
        )
        tokenizer_files = {
            name: hashlib.sha256((weights_path / name).read_bytes()).hexdigest()
            for name in freeze_files
        }
        if tokenizer_files != freeze_files:
            raise ValueError("remote V2 tokenizer assets differ from their frozen hashes")
        if tokenizer.chat_template != (weights_path / "chat_template.jinja").read_text():
            raise ValueError("loaded SmolLM3 template differs from its frozen bytes")
        _mark_stage(report, current_stage, "COMPLETE")
        tokenizer_record = {
            "tokenizer_files": tokenizer_files,
            "chat_template_sha256": hashlib.sha256(tokenizer.chat_template.encode()).hexdigest(),
        }
        if stage == "prepare":
            report["model_assets"] = {
                "model_revision": MODEL_REVISION,
                "snapshot_path": str(weights_path),
                "weights": weights,
                **tokenizer_record,
                "model_loaded": False,
            }
            report["status"] = "READY_FOR_INFERENCE"
            _mark_stage(report, "MODEL_ASSETS_VERIFIED", "COMPLETE", model_loaded=False)
            print(json.dumps({"status": "READY_FOR_INFERENCE", "weights_verified": True}))
            return 0
        _mark_stage(report, current_stage, "COMPLETE")
        action_inputs = {}
        for case_id in profile["case_ids"]:
            case = case_map[case_id]
            frozen_prompt = frozen[case_id]
            if case["request_sha256"] != frozen_prompt["request_sha256"]:
                raise ValueError(f"V2 preflight request differs: {case_id}")
            prompt = a02_dev_protocol.build_action_prompt(tokenizer, case["request"])
            a02_prompt = __import__("scripts.a02_prompt", fromlist=["verify_frozen_prompt"])
            a02_prompt.verify_frozen_prompt(
                prompt["rendered_prompt"], prompt["prompt_token_ids"], frozen_prompt, case_id
            )
            action_inputs[case_id] = (prompt["messages"], frozen_prompt)

        current_stage = "MODEL_LOADING"
        _mark_stage(report, current_stage, "STARTED", model_loaded=False)
        torch.cuda.reset_peak_memory_stats(0)
        model_start = time.perf_counter()
        model = AutoModelForCausalLM.from_pretrained(
            weights_path,
            local_files_only=True,
            trust_remote_code=False,
            torch_dtype=torch.float16,
            device_map=0,
            low_cpu_mem_usage=True,
        )
        model.eval()
        dtypes = a02_remote._floating_parameter_dtypes(model)
        if dtypes != ["float16"]:
            raise ValueError("V2 model weight dtype differs from the fixed FP16 profile")
        report["model"] = {
            "id": MODEL_ID,
            "revision": MODEL_REVISION,
            "tokenizer_revision": MODEL_REVISION,
            "tokenizer_files": tokenizer_files,
            "chat_template_sha256": hashlib.sha256(tokenizer.chat_template.encode()).hexdigest(),
            "load_seconds": time.perf_counter() - model_start,
            **weights,
        }
        report["runtime"]["weight_dtype"] = ",".join(dtypes)
        report["model_loaded"] = True
        _mark_stage(report, current_stage, "COMPLETE", model_loaded=True)

        current_stage = "ENGINE_PROCESS_START"
        _mark_stage(report, current_stage, "STARTED")
        engine_env = os.environ.copy()
        engine_env.pop("PYTHONHOME", None)
        engine_env["PYTHONPATH"] = f"{source}:{source / 'src'}"
        engine_env["PYTHONDONTWRITEBYTECODE"] = "1"
        engine_process = subprocess.Popen(
            [str(engine_python), str(source / "scripts/a02_dev_engine.py"), "--serve"],
            cwd=source,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=open(WORK / "development-engine-stderr.log", "w"),
            text=True,
            bufsize=1,
            env=engine_env,
        )
        current_stage = "MODEL_INFERENCE"
        _mark_stage(report, current_stage, "STARTED")
        start = time.perf_counter()
        tool = a02_dev_protocol.tool_schema()
        for case_id in profile["case_ids"]:
            current_stage = f"GENERATION:{case_id}"
            _mark_stage(report, current_stage, "STARTED", current_case_id=case_id)
            case = case_map[case_id]
            interaction_id = f"{binding['run_id']}:{case_id}"
            request_text = a02_remote._canonical(case["request"])
            final_text = a02_experiment.final_request_text(case["request"])
            action_messages, frozen_prompt = action_inputs[case_id]
            action_generation = _generate(
                model,
                tokenizer,
                torch,
                action_messages,
                cap=profile["decoding"]["action_max_new_tokens"],
                template_date=a02_dev_protocol.ACTION_TEMPLATE_DATE,
                prompt_limit=profile["decoding"]["action_max_prompt_tokens"],
                xml_tools=[tool],
                frozen_prompt=frozen_prompt,
            )
            row: dict[str, Any] = {
                "case_id": case_id,
                "protocol": "development_v2",
                "request_sha256": case["request_sha256"],
                "interaction_id": interaction_id,
                "user_message": a02_remote._message_envelope("untrusted_user_input", request_text),
                "final_user_text": final_text,
                "final_user_text_sha256": hashlib.sha256(final_text.encode()).hexdigest(),
                "action_generation": action_generation,
                "case_status": "ACTION_GENERATED",
            }
            report["cases"].append(row)
            report["partial_case_count"] = len(report["cases"])
            _write_report(report)
            engine_response = a02_remote._engine_call(
                engine_process,
                {
                    "kind": "development_v2",
                    "case_id": case_id,
                    "raw_action": action_generation["raw_text"],
                    "interaction_id": interaction_id,
                    "truncated": action_generation["truncated"],
                },
            )
            row["engine_response"] = engine_response
            row["case_status"] = "EXECUTOR_RECORDED"
            if engine_response.get("request_sha256") != case["request_sha256"]:
                raise ValueError(f"V2 executor request binding mismatch: {case_id}")
            event = engine_response.get("event")
            if not isinstance(event, dict):
                raise ValueError(f"V2 executor event is missing: {case_id}")
            a02_remote._verify_event(
                event, case_id, interaction_id, engine_response["action_sha256"]
            )
            final_messages = a02_dev_protocol.build_final_messages(
                request_text=final_text,
                action_text=action_generation["raw_text"],
                event=event,
            )
            row["deterministic_answer"] = a02_dev_protocol.render_validated_executor_event(event)
            row["deterministic_answer_sha256"] = hashlib.sha256(
                row["deterministic_answer"].encode()
            ).hexdigest()
            row["final_generation"] = _generate(
                model,
                tokenizer,
                torch,
                final_messages,
                cap=profile["decoding"]["final_max_new_tokens"],
                template_date=a02_dev_protocol.ACTION_TEMPLATE_DATE,
                prompt_limit=profile["decoding"]["final_max_prompt_tokens"],
            )
            row["case_status"] = "COMPLETE"
            report["partial_case_count"] = len(report["cases"])
            _mark_stage(report, current_stage, "COMPLETE", current_case_id=None)

        report.update(
            status="COMPLETE",
            current_case_id=None,
            runtime_seconds=time.perf_counter() - start,
            total_prompt_tokens=sum(
                row["action_generation"]["prompt_tokens"] + row["final_generation"]["prompt_tokens"]
                for row in report["cases"]
            ),
            total_generated_tokens=sum(
                row["action_generation"]["generated_tokens"]
                + row["final_generation"]["generated_tokens"]
                for row in report["cases"]
            ),
            peak_allocated_vram_bytes=int(torch.cuda.max_memory_allocated(0)),
            peak_reserved_vram_bytes=int(torch.cuda.max_memory_reserved(0)),
        )
        _mark_stage(report, "DEVELOPMENT_RUN_COMPLETE", "COMPLETE")
        print(json.dumps({"status": "COMPLETE", "case_count": len(report["cases"])}))
        return 0
    except Exception as exc:
        report.update(
            status="EXTERNAL_BLOCKER",
            failure_stage=current_stage,
            failure_category=type(exc).__name__,
            failure_message=_safe_excerpt(a02_remote._sanitize(str(exc)), 1000),
            partial_case_count=len(report.get("cases", [])),
        )
        _mark_stage(report, current_stage, "FAILED")
        print(
            json.dumps(
                {
                    "status": "EXTERNAL_BLOCKER",
                    "stage": current_stage,
                    "failure": type(exc).__name__,
                }
            ),
            file=sys.stderr,
        )
        return 1
    finally:
        if engine_process is not None:
            try:
                if engine_process.stdin is not None:
                    engine_process.stdin.close()
                if engine_process.wait(timeout=5) != 0:
                    engine_process.kill()
            except Exception:
                engine_process.kill()


def run() -> int:
    stage = os.environ.get("A02_DEV_WORKER_STAGE")
    if os.environ.get("A02_DEV_V2_PINNED_PROCESS") == "1":
        if stage not in {"prepare", "infer"}:
            raise ValueError("V2 worker stage is missing")
        return _run_inference_process(stage)
    return _run_isolated_inference(os.environ.get("A02_DEV_REMOTE_STAGE", ""))


if __name__ == "__main__":
    raise SystemExit(run())
