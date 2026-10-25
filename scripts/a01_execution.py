"""Owner-gated, one-suite A0.1 Colab adapter and deterministic report replay."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts import a0_colab as control
from scripts import a0_engine as engine
from scripts import a01_experiment as experiment
from scripts import a01_protocol as protocol

REPORT_SCHEMA = "RES541_A01_REPORT_V1"


def colab_environment() -> dict[str, str]:
    return {
        key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME"}
    }


def usage() -> tuple[str, str]:
    command = ["colab", "--auth=oauth2", "usage"]
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise control.RunError("quota and OAuth checks must run in an interactive WSL terminal")
    print("Interactive OAuth2 quota check:")
    visible = subprocess.run(command, cwd=protocol.ROOT, check=False, env=colab_environment())
    if visible.returncode != 0:
        raise control.RunError("Colab usage could not be read; no session was started")
    process = subprocess.Popen(
        command,
        cwd=protocol.ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=colab_environment(),
    )
    assert process.stdout is not None
    lines: list[str] = []
    control._forward_lines(process.stdout, lines)
    if process.wait() != 0:
        raise control.RunError("Colab quota verification failed after the interactive check")
    output = "".join(lines)
    return control._parse_usage_output(output), output


def prepare(suite: str, count: int) -> dict[str, Any]:
    experiment.verify_freeze()
    binding = protocol.plan(suite, count)
    cases = engine.load_cases(protocol.ROOT / protocol.SUITES[suite][0])
    messages = experiment.prepared(cases)
    return {
        **binding,
        "schema": "RES541_A0_PREPARED_CASES_V1",
        "population": "SYNTHETIC_DEVELOPMENT_ONLY",
        "cases": messages,
    }


def tokenizer(path: Path) -> Any:
    from transformers import AutoTokenizer  # type: ignore[import-not-found]

    path = experiment.e_path(path)
    for name, expected in protocol.frozen()["tokenizer_files"].items():
        if protocol.digest((path / name).read_bytes()) != expected:
            raise ValueError("host pinned tokenizer asset mismatch")
    return AutoTokenizer.from_pretrained(
        path, local_files_only=True, trust_remote_code=False, use_fast=True
    )


def score(
    outputs: dict[str, Any], suite: str, count: int, actual_tokenizer: Any = None
) -> dict[str, Any]:
    prepared = prepare(suite, count)
    binding = protocol.plan(suite, count)
    protocol.validate_outputs(outputs, binding, prepared["cases"], actual_tokenizer)
    layered = experiment.score_model_outputs(outputs, suite)
    summary = layered["summary"]
    success = (
        summary["semantic_intent_exact_match"] == count
        and summary["final_safety"] == count
        and summary["expected_numeric_cases_passed"]["numerator"]
        == summary["expected_numeric_cases_passed"]["denominator"]
        and summary["expected_canonical_refusals_passed"]["numerator"]
        == summary["expected_canonical_refusals_passed"]["denominator"]
    )
    return {
        **binding,
        "schema": REPORT_SCHEMA,
        "status": "PASS" if success else "NO_GO",
        "model_outputs": outputs,
        "layered_score": layered,
        "tokenizer_replay": "VERIFIED" if actual_tokenizer is not None else "HOST_REPLAY_REQUIRED",
    }


def confirmation(binding: dict[str, Any], balance: str) -> str:
    return (
        f"RUN RES-541 {protocol.VERSION} | suite={binding['suite']} | cases={binding['case_count']}"
        f" | source={binding['source_revision']} | prompt={protocol.PROMPT_SHA256}"
        f" | manifest={binding['case_manifest_sha256']} | quota={balance} CU"
        " | gpu=T4 | run<=900s | download<=120s | stop<=30s | verify<=30s"
        " | input=1024 | output=64 | weights<=8GiB | one session; no retry"
    )


def zero_sessions(text: str) -> bool:
    plain = re.sub(r"\x1b\[[0-9;]*m", "", text).strip()
    return (
        re.fullmatch(
            r"(?:\[colab\] Pruned [1-9][0-9]* stale local session\(s\)\.\r?\n)?"
            r"\[colab\] No active sessions found on server\.",
            plain,
        )
        is not None
    )


def run(suite: str, count: int, output_dir: Path, tokenizer_dir: Path) -> int:
    output_dir = control._prepare_host_storage(output_dir)
    prepared = prepare(suite, count)
    binding = protocol.plan(suite, count)
    actual_tokenizer = tokenizer(tokenizer_dir)
    # Recheck actual complete prompts before spending quota; no model is loaded here.
    for message in prepared["cases"]:
        ids = actual_tokenizer.apply_chat_template(
            [
                {"role": "system", "content": protocol.prompt()},
                {"role": "user", "content": message["user_message"]},
            ],
            tokenize=True,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        if len(ids) > 1024:
            raise control.RunError("A0.1 complete prompt exceeds the unchanged input limit")
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise control.RunError("A0.1 requires interactive owner approval; no session was started")
    revision = control._check_clean_pushed_revision()
    if revision != binding["source_revision"]:
        raise control.RunError("source changed during A0.1 preparation")
    balance, _ = usage()
    expected = confirmation(binding, balance)
    if input(f"Type exactly `{expected}` to authorize this one A0.1 run: ") != expected:
        raise control.RunError("owner A0.1 approval did not match; no session was started")
    # Approval cannot survive a source change while the owner was reading the prompt.
    if prepare(suite, count) != prepared or control._check_clean_pushed_revision() != revision:
        raise control.RunError("approved A0.1 source or suite changed")
    run_id = f"res541-a01-{suite.replace('_', '-')}-{datetime.now(UTC):%Y%m%d-%H%M%S%f}"
    remote = f"/content/{run_id}-report.json"
    artifact = output_dir / f"{run_id}-remote.json"
    receipt = output_dir / f"{run_id}-control.json"
    state: dict[str, Any] = {
        "binding": binding,
        "run_id": run_id,
        "owner_approved": True,
        "session_absent_after_stop": False,
    }
    command = [
        "colab",
        "--auth=oauth2",
        "run",
        "--gpu",
        "T4",
        "--session",
        run_id,
        "--keep",
        "--timeout",
        "900",
        str(protocol.ROOT / "scripts/a01_colab_entry.py"),
        "--source-revision",
        revision,
        "--run-id",
        run_id,
        "--report-path",
        remote,
        "--suite",
        suite,
        "--cases",
        str(count),
    ]

    def call(
        args: list[str], timeout: int, capture: bool = False
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            args,
            cwd=protocol.ROOT,
            check=False,
            timeout=timeout,
            text=True,
            capture_output=capture,
            env=colab_environment(),
        )

    try:
        state["runner_exit_code"] = call(command, 900).returncode
    except Exception as exc:
        state["runner_error"] = type(exc).__name__
    finally:
        try:
            state["download_exit_code"] = call(
                ["colab", "--auth=oauth2", "download", "--session", run_id, remote, str(artifact)],
                control.REPORT_DOWNLOAD_TIMEOUT_SECONDS,
            ).returncode
        except Exception as exc:
            state["download_error"] = type(exc).__name__
        finally:
            try:
                state["stop_exit_code"] = call(
                    ["colab", "--auth=oauth2", "stop", "--session", run_id],
                    control.SESSION_STOP_TIMEOUT_SECONDS,
                ).returncode
            except Exception as exc:
                state["stop_error"] = type(exc).__name__
            finally:
                try:
                    sessions = call(
                        ["colab", "--auth=oauth2", "sessions"],
                        control.SESSION_LIST_TIMEOUT_SECONDS,
                        True,
                    )
                    state["session_absent_after_stop"] = (
                        state.get("stop_exit_code") == 0
                        and sessions.returncode == 0
                        and zero_sessions(sessions.stdout)
                    )
                except Exception as exc:
                    state["sessions_error"] = type(exc).__name__
                receipt.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    if not state["session_absent_after_stop"]:
        raise control.RunError(
            f"A0.1 teardown unverified; colab --auth=oauth2 stop --session {run_id}; "
            f"verify zero active sessions; receipt: {receipt}"
        )
    if state.get("download_exit_code") != 0 or not artifact.exists():
        raise control.RunError(f"A0.1 artifact unavailable; control receipt: {receipt}")
    if artifact.stat().st_size > 2 * 1024**2:
        raise control.RunError("A0.1 remote artifact exceeds 2 MiB")
    report = json.loads(artifact.read_text())
    if (
        report.get("schema") != REPORT_SCHEMA
        or report.get("source_revision") != revision
        or report.get("run_id") != run_id
        or report.get("suite") != suite
        or type(report.get("approved_case_count")) is not int
        or report.get("approved_case_count") != count
        or any(
            protocol.compact(report.get(key)) != protocol.compact(value)
            for key, value in binding.items()
        )
    ):
        raise control.RunError("retrieved A0.1 report provenance mismatch")
    replay = score(report["model_outputs"], suite, count, actual_tokenizer)
    if (
        report.get("layered_score") != experiment.normalized(replay["layered_score"])
        or report.get("status") != replay["status"]
    ):
        raise control.RunError(
            "retrieved A0.1 scientific score differs from independent CPU replay"
        )
    replay["control_plane"] = state
    with (output_dir / f"{run_id}-verified.json").open("x") as stream:
        stream.write(json.dumps(replay, indent=2, sort_keys=True) + "\n")
    return 0 if state.get("runner_exit_code") == 0 and replay["status"] == "PASS" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "score", "run"))
    parser.add_argument("--suite", choices=tuple(protocol.SUITES), required=True)
    parser.add_argument("--cases", type=int, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--model-outputs", type=Path)
    parser.add_argument("--source-revision")
    parser.add_argument("--output-dir", type=Path, default=control.DEFAULT_REPORT_DIR / "a01")
    parser.add_argument(
        "--tokenizer-dir", type=Path, default=Path("/mnt/e/DynamisLM-A0/a01/tokenizer")
    )
    args = parser.parse_args()
    if args.command == "run":
        return run(args.suite, args.cases, args.output_dir, args.tokenizer_dir)
    if args.output is None:
        parser.error("prepare and score require --output")
    if os.environ.get("RES541_A01_REMOTE") != "1":
        experiment.e_path(args.output)
        if args.model_outputs is not None:
            experiment.e_path(args.model_outputs)
    if args.command == "prepare":
        result = prepare(args.suite, args.cases)
    else:
        if args.model_outputs is None or args.source_revision != protocol.git("rev-parse", "HEAD"):
            parser.error("score requires model outputs and the exact source revision")
        result = score(json.loads(args.model_outputs.read_text()), args.suite, args.cases)
    with args.output.open("x") as stream:
        stream.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
