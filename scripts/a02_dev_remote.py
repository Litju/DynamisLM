"""Remote inference worker for the prospective RES-541 A0.2 V2 development profile."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

SOURCE_DIR = Path(__file__).resolve().parents[1]
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from scripts import a02_remote  # noqa: E402

WORK = a02_remote.WORK
SOURCE_ARCHIVE = a02_remote.SOURCE_ARCHIVE
BINDING_PATH = a02_remote.BINDING_PATH
REMOTE_REPORT = a02_remote.REMOTE_REPORT
DEVELOPMENT_PREFLIGHT_PATH = Path("/content/a02-development-preflight-v2.json")
MODEL_ID = a02_remote.MODEL_ID
MODEL_REVISION = a02_remote.MODEL_REVISION
ENGINE_PYTHON = a02_remote.ENGINE_PYTHON
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
        "source": {
            "run_id": binding["run_id"],
            "revision": binding["source_revision"],
            "tree": binding["source_tree"],
            "archive_sha256": binding["source_archive_sha256"],
            "protocol_sha256": binding["protocol_sha256"],
            "preflight_sha256": binding["preflight_sha256"],
            "development_profile_sha256": binding["development_profile_sha256"],
            "development_preflight_sha256": binding["development_preflight_sha256"],
            "baseline_remote_report_sha256": binding["baseline_remote_report_sha256"],
        },
    }


def _run_isolated_inference() -> int:
    binding = json.loads(BINDING_PATH.read_bytes())
    if not isinstance(binding, dict) or binding.get("execution_mode") != "development_v2":
        raise ValueError("A0.2 V2 run binding is invalid")
    report = _initial_report(binding)
    stage = "INFERENCE_PROCESS_BOOTSTRAP"
    try:
        WORK.mkdir(parents=True, exist_ok=True)
        if REMOTE_REPORT.exists():
            raise ValueError("remote A0.2 V2 report path already exists")
        archive_bytes = SOURCE_ARCHIVE.read_bytes()
        if hashlib.sha256(archive_bytes).hexdigest() != binding["source_archive_sha256"]:
            raise ValueError("uploaded V2 source archive hash mismatch")
        bootstrap = WORK / "development-bootstrap-source"
        bootstrap.mkdir(exist_ok=False)
        a02_remote._safe_extract(SOURCE_ARCHIVE, bootstrap)
        uv = a02_remote._install_uv()
        inference_python = a02_remote._setup_inference(uv, bootstrap)
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHONHOME", None)
        environment["PYTHONNOUSERSITE"] = "1"
        environment["A02_DEV_V2_PINNED_PROCESS"] = "1"
        result = subprocess.run(
            [str(inference_python), str(bootstrap / "scripts/a02_dev_remote.py")],
            cwd=bootstrap,
            env=environment,
            check=False,
        )
        if not REMOTE_REPORT.exists():
            raise RuntimeError(f"V2 inference process exited {result.returncode} without a report")
        return result.returncode
    except Exception as exc:
        if REMOTE_REPORT.exists():
            return 1
        report.update(
            status="NO_GO",
            failure_stage=stage,
            failure_category=type(exc).__name__,
            failure_message=a02_remote._sanitize(str(exc)),
            partial_case_count=0,
        )
        a02_remote._write_report(report)
        return 1


def _run_inference_process() -> int:
    binding = json.loads(BINDING_PATH.read_bytes())
    report = _initial_report(binding)
    engine_process: subprocess.Popen[str] | None = None
    stage = "BINDING"
    try:
        if REMOTE_REPORT.exists():
            raise ValueError("remote A0.2 V2 report path already exists")
        archive_bytes = SOURCE_ARCHIVE.read_bytes()
        if hashlib.sha256(archive_bytes).hexdigest() != binding["source_archive_sha256"]:
            raise ValueError("uploaded V2 source archive hash mismatch")
        source = WORK / f"development-source-{binding['run_id']}"
        source.mkdir(parents=True, exist_ok=False)
        a02_remote._safe_extract(SOURCE_ARCHIVE, source)
        for path in (source, source / "src"):
            if str(path) not in sys.path:
                sys.path.insert(0, str(path))
        from scripts import a02_dev_protocol, a02_experiment

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

        stage = "ENGINE_SETUP"
        uv = a02_remote._install_uv()
        engine_python = a02_remote._setup_engine(source, uv)
        stage = "INFERENCE_SETUP"
        inference_python = Path(sys.executable)
        if inference_python.parent.parent.resolve() != (WORK / "inference-venv").resolve():
            raise ValueError("V2 worker is not using the pinned inference environment")
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
        stage = "RUNTIME_SETUP"
        torch, inventory = a02_remote._runtime_gate()
        a02_remote._package_versions(expected_packages, Path(inference_site))
        torch_module = a02_remote._torch_module_inventory(torch, Path(inference_site))
        report["runtime"] = {
            "model_python": sys.version,
            "model_python_version": platform.python_version(),
            "scientific_engine_python": a02_remote._run(
                [str(engine_python), "-c", "import platform; print(platform.python_version())"],
                cwd=source,
            ).strip(),
            "torch": str(torch.__version__),
            "torch_module": torch_module,
            "torch_cuda_runtime": torch.version.cuda,
            "packages": packages,
            "gpu_name": torch.cuda.get_device_name(0),
            "compute_capability": list(torch.cuda.get_device_capability(0)),
            "total_vram_bytes": int(torch.cuda.get_device_properties(0).total_memory),
            "free_vram_before_weights_bytes": int(torch.cuda.mem_get_info(0)[0]),
            "runtime_inventory": inventory,
            "development_action_decoding": profile["decoding"],
        }
        a02_remote._write_report(report)

        stage = "TOKENIZER_AND_MODEL_DOWNLOAD"
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
        weights_path, weights = a02_remote._weights(MODEL_ID, MODEL_REVISION, torch, freeze_files)
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
        a02_remote._write_report(report)

        stage = "ENGINE_PROCESS_START"
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
        stage = "INFERENCE"
        start = time.perf_counter()
        tool = a02_dev_protocol.tool_schema()
        for case_id in profile["case_ids"]:
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
            a02_remote._write_report(report)
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
            a02_remote._write_report(report)

        report.update(
            status="COMPLETE",
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
        a02_remote._write_report(report)
        print(json.dumps({"status": "COMPLETE", "case_count": len(report["cases"])}))
        return 0
    except Exception as exc:
        report.update(
            status="NO_GO",
            failure_stage=stage,
            failure_category=type(exc).__name__,
            failure_message=a02_remote._sanitize(str(exc)),
            partial_case_count=len(report["cases"]),
        )
        a02_remote._write_report(report)
        print(
            json.dumps({"status": "NO_GO", "stage": stage, "failure": type(exc).__name__}),
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
    if os.environ.get("A02_DEV_V2_PINNED_PROCESS") != "1":
        return _run_isolated_inference()
    return _run_inference_process()


if __name__ == "__main__":
    raise SystemExit(run())
