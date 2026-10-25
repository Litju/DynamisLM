"""CPU-only execution/provenance falsification; no Colab, CUDA or model weights."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from io import BytesIO
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

# Official CLI captures: https://github.com/googlecolab/google-colab-cli/blob/main/docs/demos.md
NO_SESSIONS = "[colab] No active sessions found on server.\n"
PRUNED_SESSION = "[colab] Pruned 1 stale local session(s).\n"
ACTIVE_SESSION = "[gpu-eval] m-s-kkb-usc1c0-3cickkby8ivx5 | Hardware: CPU | Variant: DEFAULT\n"


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
        "runtime": {
            "decoding": dict(protocol.DECODING),
            "weight_dtype": "float16",
            "gpu_name": "MOCK T4",
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
    monkeypatch.setattr(entry, "urlopen", lambda *a, **k: BytesIO(source))

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
    module = ModuleType("mock_remote")
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

    module.__dict__.update(_run=fail, run=run)
    assert entry.adapt(module, "a01_controls", 12).run("a" * 40, "test", report) == 1
    assert json.loads(report.read_text())["model_outputs"]["cases"][0]["raw_text"] == " {partial"


def test_partial_stream_is_preserved_if_inference_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    prepared = execution.prepare("a01_controls", 12)
    path, output = tmp_path / "prepared.json", tmp_path / "outputs.json"
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
    monkeypatch.setattr(
        a0_colab, "_check_clean_pushed_revision", lambda: protocol.git("rev-parse", "HEAD")
    )
    monkeypatch.setattr(a0_colab, "_usage", lambda: ("100", ""))
    monkeypatch.setattr("builtins.input", lambda _: "RUN RES-541 A0")

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Colab must never be called before approval")

    # protocol Git reads remain real; only the execution transport is isolated.
    monkeypatch.setattr(execution, "subprocess", SimpleNamespace(run=forbidden))
    with pytest.raises(a0_colab.RunError, match="approval"):
        execution.run("a01_controls", 12, tmp_path, tmp_path)


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
    ],
)
def test_owner_gated_transport_always_stops_and_verifies_zero_sessions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str | None, notice: str
) -> None:
    suite, count = "a01_controls", 12
    binding = protocol.plan(suite, count)
    remote_report = execution.score(packet(), suite, count)
    monkeypatch.setattr(a0_colab, "_prepare_host_storage", lambda _: tmp_path)
    monkeypatch.setattr(
        execution, "tokenizer", lambda _: SimpleNamespace(apply_chat_template=lambda *a, **k: [1])
    )
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(
        a0_colab, "_check_clean_pushed_revision", lambda: binding["source_revision"]
    )
    monkeypatch.setattr(a0_colab, "_usage", lambda: ("100", ""))
    monkeypatch.setattr("builtins.input", lambda _: execution.confirmation(binding, "100"))
    calls: list[tuple[str, int]] = []
    run_id = ""

    def transport(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        nonlocal run_id
        operation = command[2]
        calls.append((operation, kwargs["timeout"]))
        if operation == "run":
            assert "a01_colab_entry.py" in command[10]
            assert command[-4:] == ["--suite", suite, "--cases", "12"]
            run_id = command[6]
        if operation == failure:
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        if operation == "download":
            report = dict(remote_report, run_id=run_id, approved_case_count=count)
            Path(command[-1]).write_text(json.dumps(report))
        text = NO_SESSIONS
        if failure == "other_active":
            text = ACTIVE_SESSION
        elif failure == "unknown":
            text = "[colab] Unknown response.\n"
        elif failure == "mixed_active":
            text += ACTIVE_SESSION
        returncode = 1 if failure == f"{operation}_nonzero" else 0
        return subprocess.CompletedProcess(command, returncode, notice + text, "")

    monkeypatch.setattr(execution, "subprocess", SimpleNamespace(run=transport))
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
    if failure == "download" or failure in teardown_failures:
        with pytest.raises(a0_colab.RunError):
            execution.run(suite, count, tmp_path, tmp_path)
    else:
        assert execution.run(suite, count, tmp_path, tmp_path) == (1 if failure == "run" else 0)
    assert calls == [("run", 900), ("download", 120), ("stop", 30), ("sessions", 30)]
    state = json.loads(next(tmp_path.glob("*-control.json")).read_text())
    assert state["binding"] == binding
    assert state["session_absent_after_stop"] == (failure not in teardown_failures)


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
