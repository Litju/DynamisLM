"""CPU-only execution/provenance falsification; no Colab, CUDA or model weights."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from io import BytesIO, StringIO
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from scripts import a0_colab, a0_colab_entry, a0_colab_inference
from scripts import a0_engine as engine
from scripts import a01_colab_entry as entry
from scripts import a01_execution as execution
from scripts import a01_experiment as experiment
from scripts import a01_inference as inference
from scripts import a01_protocol as protocol
from scripts import a01_runtime as compatibility

from test_res541_runtime_profile import activate, observed

# Official CLI captures: https://github.com/googlecolab/google-colab-cli/blob/main/docs/demos.md
NO_SESSIONS = "[colab] No active sessions found on server.\n"
PRUNED_SESSION = "[colab] Pruned 1 stale local session(s).\n"
ACTIVE_SESSION = "[gpu-eval] m-s-kkb-usc1c0-3cickkby8ivx5 | Hardware: CPU | Variant: DEFAULT\n"
USAGE = "Current balance: 257.80 compute units\nActive assignments: 0\n"


@pytest.fixture(autouse=True)
def synthetic_runtime_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    activate(monkeypatch)
    monkeypatch.setattr(compatibility, "inventory", observed)


@pytest.fixture
def poisoned_colab_parent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    poison = tmp_path / "tokenizer-site-packages"
    poison.mkdir()
    (poison / "filelock.py").write_text('__version__ = "3.18.0"\n')
    (poison / "json.py").write_text('raise AssertionError("tokenizer PYTHONPATH leaked")\n')
    monkeypatch.setenv("PYTHONPATH", str(poison))
    monkeypatch.setenv("PYTHONHOME", str(tmp_path / "invalid-python-home"))
    for name, path in {
        "TMPDIR": "tmp",
        "UV_CACHE_DIR": "cache/uv",
        "PIP_CACHE_DIR": "cache/pip",
        "XDG_CACHE_HOME": "cache/xdg",
        "HF_HOME": "cache/huggingface",
        "TORCH_HOME": "cache/torch",
        "PYTHONPYCACHEPREFIX": "cache/pycache",
    }.items():
        monkeypatch.setenv(name, f"/mnt/e/DynamisLM-A0/{path}")


def test_colab_environment_isolates_real_child_without_changing_parent(
    poisoned_colab_parent: None,
) -> None:
    parent = dict(os.environ)
    env = execution.colab_environment()
    assert env == {
        key: value for key, value in parent.items() if key not in {"PYTHONPATH", "PYTHONHOME"}
    }
    child = subprocess.run(
        [sys.executable, "-c", "import json, os; print(json.dumps(dict(os.environ)))"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(child.stdout) == env
    assert dict(os.environ) == parent


@pytest.mark.parametrize("failure", [None, "visible", "captured", "unknown", "zero", "active"])
def test_isolated_quota_preserves_oauth_and_fail_closed_parsing(
    monkeypatch: pytest.MonkeyPatch, poisoned_colab_parent: None, failure: str | None
) -> None:
    parent = dict(os.environ)
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    calls = []
    output = {
        "unknown": "unknown quota response\n",
        "zero": USAGE.replace("257.80", "0.00"),
        "active": USAGE.replace("assignments: 0", "assignments: 1"),
    }.get(failure or "", USAGE)

    def visible(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert command == ["colab", "--auth=oauth2", "usage"]
        assert kwargs == {
            "cwd": protocol.ROOT,
            "check": False,
            "env": execution.colab_environment(),
        }
        calls.append("visible")
        return subprocess.CompletedProcess(command, 1 if failure == "visible" else 0)

    def captured(command: list[str], **kwargs: Any) -> Any:
        assert command == ["colab", "--auth=oauth2", "usage"]
        assert kwargs == {
            "cwd": protocol.ROOT,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "bufsize": 1,
            "env": execution.colab_environment(),
        }
        calls.append("captured")
        return SimpleNamespace(
            stdout=StringIO(output), wait=lambda: 1 if failure == "captured" else 0
        )

    monkeypatch.setattr(
        execution, "subprocess", SimpleNamespace(run=visible, Popen=captured, PIPE=-1, STDOUT=-2)
    )
    if failure:
        with pytest.raises(a0_colab.RunError):
            execution.usage()
    else:
        assert execution.usage() == ("257.80", USAGE)
    assert calls == (["visible"] if failure == "visible" else ["visible", "captured"])
    assert dict(os.environ) == parent


@pytest.mark.parametrize("non_tty", ["stdin", "stdout"])
def test_isolated_quota_requires_interactive_terminal(
    monkeypatch: pytest.MonkeyPatch, non_tty: str
) -> None:
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: non_tty != "stdin"))
    monkeypatch.setattr(sys.stdout, "isatty", lambda: non_tty != "stdout")

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("OAuth must remain interactive")

    monkeypatch.setattr(execution, "subprocess", SimpleNamespace(run=forbidden, Popen=forbidden))
    with pytest.raises(a0_colab.RunError, match="interactive"):
        execution.usage()


@pytest.mark.parametrize(
    "text",
    [
        NO_SESSIONS,
        PRUNED_SESSION + NO_SESSIONS,
        PRUNED_SESSION.replace("1", "12") + NO_SESSIONS,
        (PRUNED_SESSION + NO_SESSIONS).replace("\n", "\r\n"),
        "\x1b[32m" + NO_SESSIONS.rstrip() + "\x1b[0m\n",
    ],
)
def test_zero_sessions_accepts_official_cli_output(text: str) -> None:
    assert execution.zero_sessions(text)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "No active sessions found on server",
        NO_SESSIONS.removeprefix("[colab] "),
        NO_SESSIONS.replace("server.", "server"),
        NO_SESSIONS.replace("server.", "server.."),
        "[colab] Unknown response.\n",
        ACTIVE_SESSION,
        PRUNED_SESSION,
        PRUNED_SESSION + ACTIVE_SESSION,
        ACTIVE_SESSION + NO_SESSIONS,
        NO_SESSIONS + ACTIVE_SESSION,
        "[colab] Unknown response.\n" + NO_SESSIONS,
        NO_SESSIONS + "[colab] Unknown response.\n",
        NO_SESSIONS + PRUNED_SESSION,
        PRUNED_SESSION * 2 + NO_SESSIONS,
        NO_SESSIONS * 2,
        PRUNED_SESSION + "\n" + NO_SESSIONS,
        PRUNED_SESSION.replace("1", "0") + NO_SESSIONS,
        PRUNED_SESSION.replace("1", "-1") + NO_SESSIONS,
        PRUNED_SESSION.replace("1", "01") + NO_SESSIONS,
        PRUNED_SESSION.replace("1", "\u0661") + NO_SESSIONS,
        PRUNED_SESSION.replace("1", "many") + NO_SESSIONS,
        PRUNED_SESSION.replace("local ", "") + NO_SESSIONS,
    ],
)
def test_zero_sessions_rejects_unknown_or_active_output(text: str) -> None:
    assert not execution.zero_sessions(text)


def packet(suite: str = "a01_controls", actual: Any = None) -> dict[str, Any]:
    count = protocol.SUITES[suite][1]
    prepared = execution.prepare(suite, count)
    binding = protocol.plan(suite, count)
    cases = engine.load_cases(protocol.ROOT / protocol.SUITES[suite][0])
    when = datetime.now(UTC)
    evidence = {"bootstrap": observed(), "inference": observed()}
    rows = []
    for case, message in zip(cases, prepared["cases"], strict=True):
        raw = experiment.compact(
            engine._model_intent_wire(engine.oracle_intent(engine._build_context(case)))
        )
        ids = [1, 2]
        generated = [7, protocol.EOS]
        if actual is not None:
            ids = actual.apply_chat_template(
                [
                    {"role": "system", "content": protocol.prompt()},
                    {"role": "user", "content": message["user_message"]},
                ],
                tokenize=True,
                add_generation_prompt=True,
                enable_thinking=False,
                strftime_now=when.strftime,
            )
            generated = [*actual.encode(raw, add_special_tokens=False), protocol.EOS]
        row = dict(
            runtime_evidence_sha256=compatibility.digest(evidence),
            case_id=case.case_id,
            raw_text=raw,
            prompt_token_ids=ids,
            prompt_tokens=len(ids),
            generated_token_ids=generated,
            generated_tokens=len(generated),
            prompt_sha256=protocol.digest(protocol.compact(ids).encode()),
            prompt_utc=when.isoformat(),
            chat_template_date=when.strftime("%d %B %Y"),
            user_message_sha256=protocol.digest(message["user_message"].encode()),
            failure_category=None,
        )
        row["binding_sha256"] = protocol.bind_row(row, binding)
        rows.append(row)
    return {
        **binding,
        "schema": "RES541_A0_MODEL_OUTPUTS_V1",
        "status": "COMPLETE",
        "cases": rows,
        "runtime_evidence": evidence,
        "runtime": {
            **observed(),
            "decoding": dict(protocol.DECODING),
            "weight_dtype": "float16",
            "gpu_name": "Tesla T4",
            "compute_capability": [7, 5],
            "total_vram_bytes": 15 * 1024**3,
            "model_weight_bytes_from_revision_metadata": 6 * 1024**3,
        },
    }


@pytest.mark.parametrize(("suite", "count"), [("a0_diagnostic", 16), ("a01_controls", 12)])
def test_exact_suite_routing_and_layered_score(suite: str, count: int) -> None:
    data = packet(suite)
    report = execution.score(data, suite, count)
    assert report["status"] == "PASS"
    assert report["tokenizer_replay"] == "HOST_REPLAY_REQUIRED"
    assert report["model_outputs"] == data
    assert report["layered_score"]["summary"]["semantic_intent_exact_match"] == count
    assert report["system_prompt_sha256"] == protocol.PROMPT_SHA256
    assert protocol.prompt() != a0_colab_inference.SYSTEM_PROMPT


@pytest.mark.parametrize(
    ("suite", "count"),
    [
        ("both", 28),
        ("a0_diagnostic", 28),
        ("a01_controls", 16),
        ("a0_diagnostic", 12),
        ("a01_controls", True),
    ],
)
def test_no_silent_budget_increase(suite: str, count: int) -> None:
    with pytest.raises(ValueError, match="suite"):
        protocol.plan(suite, count)


@pytest.mark.parametrize(
    "field",
    [
        "runtime_profile_id",
        "runtime_profile_sha256",
        "execution_version",
        "source_revision",
        "source_tree",
        "suite",
        "model_revision",
        "tokenizer_revision",
        "prompt_version",
        "system_prompt_sha256",
        "case_manifest_sha256",
        "decoding",
        "limits",
        "case_count",
    ],
)
def test_reject_foreign_source_prompt_suite_and_limits(field: str) -> None:
    data = packet()
    data[field] = "foreign"
    with pytest.raises(ValueError, match="provenance"):
        execution.score(data, "a01_controls", 12)


@pytest.mark.parametrize(
    "mutation",
    [
        "case_id",
        "prompt_sha256",
        "prompt_utc",
        "date",
        "binding",
        "raw",
        "cap",
        "missing_eos",
        "failure",
        "ids",
        "dtype",
    ],
)
def test_reject_per_case_evidence_mismatch(mutation: str) -> None:
    data = packet()
    row = data["cases"][0]
    if mutation == "case_id":
        row["case_id"] = "foreign"
    elif mutation == "prompt_sha256":
        row["prompt_sha256"] = "0" * 64
    elif mutation == "prompt_utc":
        row["prompt_utc"] = "2020-01-01T00:00:00+00:00"
    elif mutation == "date":
        row["chat_template_date"] = "01 January 2020"
    elif mutation == "binding":
        row["binding_sha256"] = "0" * 64
    elif mutation == "raw":
        row["raw_text"] = "REPAIRED"
    elif mutation == "cap":
        row["generated_token_ids"] = [7] * 63 + [protocol.EOS]
        row["generated_tokens"] = 64
    elif mutation == "missing_eos":
        row["generated_token_ids"][-1] = 7
    elif mutation == "failure":
        row["failure_category"] = "CUDA_OUT_OF_MEMORY"
    elif mutation == "ids":
        row["prompt_token_ids"] = [True]
    elif mutation == "dtype":
        data["runtime"]["weight_dtype"] = "bfloat16"
    with pytest.raises(ValueError):
        execution.score(data, "a01_controls", 12)


def test_invalid_intent_stays_raw_and_separate_from_model_refusal() -> None:
    data = packet()
    binding = protocol.plan("a01_controls", 12)
    for row, raw in zip(
        data["cases"], ["{", '{"v":1,"d":"REFUSE","x":"MISSING_EVIDENCE"}'], strict=False
    ):
        row["raw_text"] = raw
        row["binding_sha256"] = protocol.bind_row(row, binding)
    report = execution.score(data, "a01_controls", 12)
    assert report["status"] == "NO_GO"
    assert report["model_outputs"]["cases"][0]["raw_text"] == "{"
    assert report["layered_score"]["summary"]["parser_fallback"] == 1
    assert report["layered_score"]["summary"]["explicit_model_refusal"] == 1
    assert report["layered_score"]["summary"]["final_safety"] == 12


def test_remote_bootstrap_routes_only_the_three_a01_steps(tmp_path: Path) -> None:
    module = protocol.isolated_a0("a0_colab_entry")
    original = a0_colab_entry._run
    calls = []

    def fake(command: list[str], **kwargs: Any) -> str:
        calls.append(command)
        if "prepare" in command:
            Path(command[command.index("--output") + 1]).write_text("{}")
        return "OK"

    module.__dict__["_run"] = fake
    entry.adapt(module, "a01_controls", 12)
    for script, tail in [
        ("a0_engine.py", ["prepare", "--output", str(tmp_path / "p.json")]),
        ("a0_colab_inference.py", ["--prepared-cases", "p", "--output", str(tmp_path / "m.json")]),
        ("a0_engine.py", ["score", "--model-outputs", "m"]),
    ]:
        module._run(["python", "/source/scripts/" + script, *tail])
    assert calls[0][1:4] == ["-m", "scripts.a01_execution", "prepare"]
    assert calls[1][1:3] == ["-m", "scripts.a01_inference"]
    assert calls[2][1:4] == ["-m", "scripts.a01_execution", "score"]
    assert all("--suite" in call and "12" in call for call in (calls[0], calls[2]))
    assert a0_colab_entry._run is original


def test_remote_python_mismatch_retains_observed_runtime_without_relaxing_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = protocol.isolated_a0("a0_colab_entry")
    original = a0_colab_entry._preflight
    monkeypatch.setattr(compatibility, "inventory", lambda: {**observed(), "python": "3.14.0"})
    torch = ModuleType("torch")
    torch.__dict__["__version__"] = "2.11.0+cu130"
    monkeypatch.setitem(sys.modules, "torch", torch)

    def forbidden(*args: Any, **kwargs: Any) -> str:
        raise AssertionError("runtime mismatch must stop before source or model download")

    module.__dict__["_run"] = forbidden
    report_path = tmp_path / "failure.json"
    assert entry.adapt(module, "a0_diagnostic", 16).run("a" * 40, "test", report_path) == 1
    report = json.loads(report_path.read_text())
    assert report["failure_stage"] == "GPU_PREFLIGHT"
    assert report["failure_category"] == "RUNTIME_INCOMPATIBLE"
    assert report["runtime_preflight"] == {**observed(), "python": "3.14.0"}
    assert report["model_weights_downloaded"] is False
    assert report["inference_run"] is False and report["cases"] == []
    assert report["suite"] == "a0_diagnostic" and report["approved_case_count"] == 16
    before = report_path.read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        module.run("a" * 40, "test", report_path)
    assert report_path.read_bytes() == before
    assert a0_colab_entry._preflight is original


def test_inference_private_module_cannot_fall_back_to_a0() -> None:
    prepared = execution.prepare("a01_controls", 12)
    module, records, streamers = inference.runtime(prepared)
    assert module.SYSTEM_PROMPT == protocol.prompt()
    assert a0_colab_inference.SYSTEM_PROMPT != module.SYSTEM_PROMPT
    assert module.MODEL_REVISION == prepared["model_revision"]
    assert (module.MAX_PROMPT_TOKENS, module.MAX_NEW_TOKENS) == (1024, 64)
    with pytest.raises(ValueError, match="original A0"):
        module._apply_chat_template(
            None, [{"role": "system", "content": a0_colab_inference.SYSTEM_PROMPT}]
        )
    assert not records and not streamers


def test_bootstrap_source_is_pinned_before_execution(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(entry, "_RUNTIME", None)
    source = (protocol.ROOT / "scripts/a0_colab_entry.py").read_bytes()
    assert protocol.digest(source) == entry.A0_ENTRY_SHA256
    calls = []
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "entry",
            "--source-revision",
            "a" * 40,
            "--run-id",
            "test",
            "--report-path",
            str(tmp_path / "r.json"),
            "--suite",
            "a01_controls",
            "--cases",
            "12",
        ],
    )
    monkeypatch.setattr(
        entry,
        "urlopen",
        lambda url, **k: BytesIO(
            (protocol.ROOT / "scripts/a01_runtime.py").read_bytes()
            if url.endswith("a01_runtime.py")
            else source
        ),
    )

    def adapted(module: ModuleType, suite: str, count: int) -> Any:
        def run(*args: Any) -> int:
            calls.append((suite, count, args))
            return 0

        return SimpleNamespace(run=run)

    monkeypatch.setattr(entry, "adapt", adapted)
    assert entry.main() == 0
    assert calls[0][0:2] == ("a01_controls", 12)
    monkeypatch.setattr(entry, "urlopen", lambda *a, **k: BytesIO(b"foreign bootstrap"))
    with pytest.raises(ValueError, match="SHA-256"):
        entry.main()
    assert len(calls) == 1


def test_remote_failure_retains_generations_after_temporary_directory_disappears(
    tmp_path: Path,
) -> None:
    module = protocol.isolated_a0("a0_colab_entry")
    model = tmp_path / "model.json"
    report = tmp_path / "report.json"

    def fail(*args: Any, **kwargs: Any) -> str:
        model.write_text(json.dumps({"cases": [{"raw_text": " {partial"}]}))
        raise RuntimeError("mock inference failure")

    def run(*args: Any) -> int:
        with pytest.raises(RuntimeError):
            module._run(["python", "/source/scripts/a0_colab_inference.py", "--output", str(model)])
        model.unlink()
        report.write_text(json.dumps({"status": "NO_GO"}))
        return 1

    module.__dict__.update(_run=fail, run=run, _preflight=lambda: None)
    assert entry.adapt(module, "a01_controls", 12).run("a" * 40, "test", report) == 1
    assert json.loads(report.read_text())["model_outputs"]["cases"][0]["raw_text"] == " {partial"


def test_partial_stream_is_preserved_if_inference_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    prepared = execution.prepare("a01_controls", 12)
    path, output = tmp_path / "prepared.json", tmp_path / "outputs.json"
    prepared["bootstrap_inventory"] = observed()
    path.write_text(json.dumps(prepared))
    stream = SimpleNamespace(
        case_id=prepared["cases"][0]["case_id"],
        ids=[7],
        record={"tokenizer": SimpleNamespace(decode=lambda *a, **k: " {partial")},
    )

    def fail(*args: Any) -> None:
        raise RuntimeError("mock fatal failure after a token")

    monkeypatch.setattr(
        inference, "runtime", lambda _: (SimpleNamespace(run_inference=fail), [], [stream])
    )
    monkeypatch.setattr(inference, "verify_tokenizer_assets", lambda: None)
    with pytest.raises(RuntimeError):
        inference.run(path, output)
    data = json.loads(output.read_text())
    assert data["status"] == "NO_GO"
    assert data["captured_generations"][0]["raw_text"] == " {partial"


@pytest.mark.parametrize("approval", ["wrong", "not_tty"])
def test_no_gpu_without_exact_interactive_owner_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, approval: str
) -> None:
    monkeypatch.setattr(a0_colab, "_prepare_host_storage", lambda _: tmp_path)
    monkeypatch.setattr(
        execution, "tokenizer", lambda _: SimpleNamespace(apply_chat_template=lambda *a, **k: [1])
    )
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: approval != "not_tty"))
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(execution, "verified_revision", lambda: protocol.git("rev-parse", "HEAD"))
    monkeypatch.setattr(execution, "usage", lambda: ("100", ""))
    monkeypatch.setattr("builtins.input", lambda _: "RUN RES-541 A0")

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Colab must never be called before approval")

    # protocol Git reads remain real; only the execution transport is isolated.
    monkeypatch.setattr(execution, "subprocess", SimpleNamespace(run=forbidden))
    with pytest.raises(a0_colab.RunError, match="approval"):
        execution.run("a0_diagnostic", 16, tmp_path, tmp_path)


@pytest.mark.parametrize("notice", ["", PRUNED_SESSION])
@pytest.mark.parametrize(
    "failure",
    [
        None,
        "download",
        "run",
        "stop",
        "sessions",
        "stop_nonzero",
        "sessions_nonzero",
        "other_active",
        "unknown",
        "mixed_active",
        "remote_preflight",
        "foreign_failure",
        "malformed_failure",
        "unbound_success",
    ],
)
def test_owner_gated_transport_always_stops_and_verifies_zero_sessions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str | None,
    notice: str,
    poisoned_colab_parent: None,
) -> None:
    parent = dict(os.environ)
    suite, count = "a0_diagnostic", 16
    binding = protocol.plan(suite, count)
    remote_report = execution.score(packet(suite), suite, count)
    monkeypatch.setattr(a0_colab, "_prepare_host_storage", lambda _: tmp_path)
    monkeypatch.setattr(
        execution, "tokenizer", lambda _: SimpleNamespace(apply_chat_template=lambda *a, **k: [1])
    )
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(execution, "verified_revision", lambda: binding["source_revision"])
    monkeypatch.setattr("builtins.input", lambda _: execution.confirmation(binding, "257.80"))
    calls: list[tuple[str, int | None]] = []
    run_id = ""

    def transport(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        nonlocal run_id
        operation = command[2]
        assert kwargs["env"] == {
            key: value for key, value in parent.items() if key not in {"PYTHONPATH", "PYTHONHOME"}
        }
        calls.append((operation, kwargs.get("timeout")))
        if operation == "run":
            assert "a01_colab_entry.py" in command[10]
            assert command[-4:] == ["--suite", suite, "--cases", "16"]
            run_id = command[6]
        if operation == failure:
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        if operation == "download":
            report = dict(
                remote_report,
                run_id=run_id,
                approved_case_count=count,
                runtime_inventory=observed(),
            )
            if failure in {"remote_preflight", "foreign_failure", "malformed_failure"}:
                report = {
                    **compatibility.binding(),
                    "schema": execution.REPORT_SCHEMA,
                    "execution_version": protocol.VERSION,
                    "source_revision": binding["source_revision"],
                    "run_id": run_id,
                    "suite": suite,
                    "approved_case_count": count,
                    "status": "NO_GO",
                    "failure_stage": "GPU_PREFLIGHT",
                    "failure_category": "PYTHON_VERSION_MISMATCH",
                    "cases": [],
                    "inference_run": failure == "malformed_failure",
                }
                if failure == "foreign_failure":
                    report["source_revision"] = "0" * 40
            elif failure == "unbound_success":
                del report["case_manifest_sha256"]
            Path(command[-1]).write_text(json.dumps(report))
        text = NO_SESSIONS
        if failure == "other_active":
            text = ACTIVE_SESSION
        elif failure == "unknown":
            text = "[colab] Unknown response.\n"
        elif failure == "mixed_active":
            text += ACTIVE_SESSION
        returncode = 1 if failure == f"{operation}_nonzero" else 0
        if operation == "run" and failure in {
            "remote_preflight",
            "foreign_failure",
            "malformed_failure",
        }:
            returncode = 1
        return subprocess.CompletedProcess(command, returncode, notice + text, "")

    def captured(command: list[str], **kwargs: Any) -> Any:
        assert command == ["colab", "--auth=oauth2", "usage"]
        assert kwargs["env"] == execution.colab_environment()
        calls.append(("captured_usage", None))
        return SimpleNamespace(stdout=StringIO(USAGE), wait=lambda: 0)

    monkeypatch.setattr(
        execution, "subprocess", SimpleNamespace(run=transport, Popen=captured, PIPE=-1, STDOUT=-2)
    )
    monkeypatch.setattr(execution, "score", lambda *a, **k: copy.deepcopy(remote_report))
    teardown_failures = {
        "stop",
        "sessions",
        "stop_nonzero",
        "sessions_nonzero",
        "other_active",
        "unknown",
        "mixed_active",
    }
    if failure == "remote_preflight":
        with pytest.raises(a0_colab.RunError, match="GPU_PREFLIGHT: PYTHON_VERSION_MISMATCH"):
            execution.run(suite, count, tmp_path, tmp_path)
    elif failure in {"foreign_failure", "malformed_failure", "unbound_success"}:
        with pytest.raises(a0_colab.RunError, match="provenance mismatch|malformed"):
            execution.run(suite, count, tmp_path, tmp_path)
    elif failure == "download" or failure in teardown_failures:
        with pytest.raises(a0_colab.RunError):
            execution.run(suite, count, tmp_path, tmp_path)
    else:
        assert execution.run(suite, count, tmp_path, tmp_path) == (1 if failure == "run" else 0)
    assert calls == [
        ("usage", None),
        ("captured_usage", None),
        ("run", 900),
        ("download", 120),
        ("stop", 30),
        ("sessions", 30),
    ]
    state = json.loads(next(tmp_path.glob("*-control.json")).read_text())
    assert state["binding"] == binding
    assert state["session_absent_after_stop"] == (failure not in teardown_failures)
    assert dict(os.environ) == parent


def test_historical_fixture_path_is_protected(monkeypatch: pytest.MonkeyPatch) -> None:
    original = experiment.git

    def changed(*args: str) -> str:
        if args[0] == "diff" and "tests/fixtures/a0" in args:
            return "a historical fixture was modified"
        return original(*args)

    monkeypatch.setattr(experiment, "git", changed)
    with pytest.raises(ValueError, match="original A0 baseline changed"):
        experiment.verify_freeze()


@pytest.mark.skipif(
    not os.environ.get("RES541_A01_TOKENIZER_DIR"), reason="requires owner E: tokenizer"
)
@pytest.mark.parametrize("suite", list(protocol.SUITES))
def test_actual_tokenizer_replay_and_rebound_token_tampering(
    suite: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    actual = execution.tokenizer(Path(os.environ["RES541_A01_TOKENIZER_DIR"]))
    prepared = execution.prepare(suite, protocol.SUITES[suite][1])
    path, output = tmp_path / "prepared.json", tmp_path / "outputs.json"
    prepared["bootstrap_inventory"] = observed()
    path.write_text(json.dumps(prepared))

    class Array:
        def __init__(self, values: Any) -> None:
            self.values = values

        def __getitem__(self, index: int) -> Array:
            return Array(self.values[index])

        def reshape(self, *args: Any) -> Array:
            return self

        def tolist(self) -> Any:
            return self.values

    class CPUOnlyTokenizer:
        chat_template = actual.chat_template

        def apply_chat_template(self, messages: Any, **kwargs: Any) -> Any:
            tensors = kwargs.pop("return_tensors", None)
            result = actual.apply_chat_template(messages, **kwargs)
            if tensors:
                assert tensors == "pt" and kwargs["enable_thinking"] is False
                return {k: Array([v]) for k, v in result.items()}
            return result

        def encode(self, *args: Any, **kwargs: Any) -> Any:
            return actual.encode(*args, **kwargs)

        def decode(self, *args: Any, **kwargs: Any) -> Any:
            return actual.decode(*args, **kwargs)

    original_factory = inference.runtime

    def factory(document: dict[str, Any]) -> Any:
        module, records, streamers = original_factory(document)

        def fake_model(prepared_path: Path, output_path: Path) -> dict[str, Any]:
            data = packet(suite, actual)
            for row, case in zip(data["cases"], document["cases"], strict=True):
                encoded = module._apply_chat_template(
                    CPUOnlyTokenizer(),
                    [
                        {"role": "system", "content": module.SYSTEM_PROMPT},
                        {"role": "user", "content": case["user_message"]},
                    ],
                )
                streamer = module.TimingStreamer()
                streamer.put(encoded["input_ids"])
                # Whitespace is genuine raw generation, preserved by A0.1.
                raw = " \n" + row["raw_text"] + "\n"
                ids = [*actual.encode(raw, add_special_tokens=False), protocol.EOS]
                for token in ids:
                    streamer.put(Array([token]))
                row.update(raw_text=raw.strip(), generated_tokens=len(ids))
            output_path.write_text(json.dumps(data))
            return data

        module.__dict__["run_inference"] = fake_model
        return module, records, streamers

    monkeypatch.setattr(inference, "runtime", factory)
    monkeypatch.setattr(inference, "verify_tokenizer_assets", lambda: None)
    inference.run(path, output)
    data = json.loads(output.read_text())
    assert data["cases"][0]["raw_text"].startswith(" \n")
    count = protocol.SUITES[suite][1]
    report = execution.score(data, suite, count, actual)
    assert report["status"] == "PASS" and report["tokenizer_replay"] == "VERIFIED"
    row = data["cases"][0]
    row["prompt_token_ids"][0] += 1
    row["prompt_sha256"] = protocol.digest(protocol.compact(row["prompt_token_ids"]).encode())
    row["binding_sha256"] = protocol.bind_row(row, protocol.plan(suite, count))
    with pytest.raises(ValueError, match="actual tokenizer replay"):
        execution.score(data, suite, count, actual)


@pytest.mark.parametrize("mutation", ["profile", "bootstrap", "inference", "runtime", "digest"])
def test_runtime_provenance_cannot_be_relabelled(mutation: str) -> None:
    data = packet()
    if mutation == "profile":
        data["runtime_profile_sha256"] = "0" * 64
    elif mutation in {"bootstrap", "inference"}:
        data["runtime_evidence"][mutation]["python_build"] = ["foreign", "foreign"]
    elif mutation == "runtime":
        data["runtime"]["torch_cuda_runtime"] = "12.0"
    else:
        data["cases"][0]["runtime_evidence_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        execution.score(data, "a01_controls", 12)


def test_inference_mismatch_precedes_all_downloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = execution.prepare("a0_diagnostic", 16)
    prepared["bootstrap_inventory"] = {**observed(), "python": "3.14.0"}
    path, output = tmp_path / "prepared.json", tmp_path / "outputs.json"
    path.write_text(json.dumps(prepared))

    def forbidden() -> None:
        raise AssertionError("runtime mismatch must precede tokenizer downloads")

    monkeypatch.setattr(inference, "verify_tokenizer_assets", forbidden)
    with pytest.raises(ValueError, match="INCOMPATIBLE"):
        inference.run(path, output)
    failure = json.loads(output.read_text())
    assert failure["status"] == "NO_GO"
    assert failure["runtime_evidence"]["bootstrap"]["python"] == "3.14.0"
    assert failure["runtime_evidence"]["inference"] == observed()

@pytest.mark.parametrize("canonical_sha", ["match", "foreign", "absent"])
def test_canonical_source_check_fails_closed_before_gpu(
    monkeypatch: pytest.MonkeyPatch, canonical_sha: str
) -> None:
    revision = "a" * 40
    branch_ref = f"refs/heads/{a0_colab.BRANCH}"
    monkeypatch.setattr(a0_colab, "_check_clean_pushed_revision", lambda: revision)

    def fake(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert command == [
            "git",
            "ls-remote",
            "--exit-code",
            f"https://github.com/{a0_colab.REPOSITORY}.git",
            branch_ref,
        ]
        assert kwargs["timeout"] == 30
        assert kwargs["cwd"] == protocol.ROOT
        if canonical_sha == "absent":
            return subprocess.CompletedProcess(command, 2, "", "")
        remote_sha = revision if canonical_sha == "match" else "b" * 40
        return subprocess.CompletedProcess(command, 0, f"{remote_sha}\t{branch_ref}\n", "")

    monkeypatch.setattr(execution, "subprocess", SimpleNamespace(run=fake))
    if canonical_sha == "match":
        assert execution.verified_revision() == revision
    else:
        with pytest.raises(a0_colab.RunError, match="canonical repository"):
            execution.verified_revision()
