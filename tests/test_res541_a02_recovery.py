"""Synthetic, CPU-only falsification of the attempt-3 recovery boundary."""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

import pytest
from scripts import a02_experiment, a02_recover, a02_score

TARGET = "synthetic-a02-target"
ENDPOINT = "gpu-t4-s-synthetic-target"
UNRELATED = (
    "[synthetic-unrelated] gpu-a100-s-other | Hardware: A100 | Shape: Standard | Variant: GPU"
)


def provider_evidence(text: str, endpoints: list[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    return (
        {
            "command": ["colab", "--auth=oauth2", "sessions"],
            "exit_code": 0,
            "stdout": text,
            "stderr": "",
        },
        {
            "exit_code": 0,
            "stderr": "",
            "stdout": json.dumps(
                {
                    "endpoint": "https://colab.research.google.com/tun/m/assignments",
                    "assignments": [{"endpoint": endpoint} for endpoint in endpoints],
                }
            ),
        },
    )


def test_unrelated_active_session_does_not_invalidate_stopped_target() -> None:
    cli, provider = provider_evidence(UNRELATED, ["gpu-a100-s-other"])
    assert a02_recover._target_absent(cli, TARGET, ENDPOINT, provider)


@pytest.mark.parametrize("name", [TARGET, "renamed-target"])
def test_active_target_is_rejected_by_name_or_endpoint(name: str) -> None:
    text = f"[{name}] {ENDPOINT} | Hardware: T4 | Shape: Standard | Variant: GPU"
    cli, provider = provider_evidence(text, [ENDPOINT])
    assert not a02_recover._target_absent(cli, TARGET, ENDPOINT, provider)


@pytest.mark.parametrize("failure", ["cli-error", "auth", "missing", "malformed", "different"])
def test_unverified_target_fails_closed(failure: str) -> None:
    cli, provider = provider_evidence(UNRELATED, ["gpu-a100-s-other"])
    if failure == "cli-error":
        cli["exit_code"] = 1
    elif failure == "auth":
        provider["stderr"] = "Authentication failed"
    elif failure == "missing":
        cli["stdout"] = ""
    elif failure == "malformed":
        cli["stdout"] = "[colab] Session not found"
    else:
        _, provider = provider_evidence(UNRELATED, [ENDPOINT])
    with pytest.raises(ValueError, match="UNKNOWN"):
        a02_recover._target_absent(cli, TARGET, ENDPOINT, provider)


def test_forged_teardown_cannot_self_authorize(tmp_path: Path) -> None:
    path = tmp_path / "teardown.json"
    path.write_text(json.dumps({"target_absent": True, "decision": "SUCCESS"}))
    with pytest.raises(ValueError, match="digest mismatch"):
        a02_recover.verify_teardown(path, tmp_path)


@pytest.mark.parametrize("payload", ["{", "[]", "null"])
def test_malformed_evidence_is_rejected(tmp_path: Path, payload: str) -> None:
    path = tmp_path / "receipt.json"
    path.write_text(payload)
    with pytest.raises(ValueError):
        a02_recover._pinned_json(path, a02_recover._hash(path.read_bytes()))


def population() -> tuple[dict[str, Any], dict[str, Any]]:
    preflight = {
        "historical_cases": [{"case_id": f"synthetic-history-{i}"} for i in range(16)],
        "new_action_cases": [{"case_id": f"synthetic-new-{i}"} for i in range(10)],
    }
    remote = {
        "cases": [
            {**row, "protocol": kind, "case_status": "COMPLETE"}
            for kind, rows in (
                ("historical", preflight["historical_cases"]),
                ("new", preflight["new_action_cases"]),
            )
            for row in rows
        ]
    }
    return remote, preflight


@pytest.mark.parametrize("failure", ["missing", "duplicate", "partial", "wrong-kind"])
def test_population_is_exact_and_complete(failure: str) -> None:
    remote, preflight = population()
    a02_recover.verify_population(remote, preflight)
    if failure == "missing":
        remote["cases"].pop()
    elif failure == "duplicate":
        remote["cases"][-1] = remote["cases"][0]
    elif failure == "partial":
        remote["cases"][0]["case_status"] = "PARTIAL"
    else:
        remote["cases"][0]["protocol"] = "new"
    with pytest.raises(ValueError, match="population"):
        a02_recover.verify_population(remote, preflight)


@pytest.mark.parametrize(
    "name",
    ["authorization.json", "attempt-003-used.json", "binding.json", "remote-report.json"],
)
def test_tampered_original_cannot_be_admitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    # The trusted manifest is the external anchor; a replacement receipt cannot bless itself.
    path = tmp_path / name
    path.write_text('{"synthetic":true}')
    manifest = {
        "files": [
            {
                "name": name,
                "local_path": str(path),
                "bytes": path.stat().st_size,
                "sha256": a02_recover._hash(path.read_bytes()),
            }
        ]
    }
    manifest_path = tmp_path / "artifact-hashes.json"
    manifest_path.write_text(json.dumps(manifest))
    monkeypatch.setattr(
        a02_recover, "MANIFEST_SHA256", a02_recover._hash(manifest_path.read_bytes())
    )
    path.write_text('{"synthetic":"forged model, marker, binding or owner authority"}')
    with pytest.raises(ValueError, match="original artifact changed"):
        a02_recover.verify_originals(tmp_path)
    manifest["files"][0]["sha256"] = a02_recover._hash(path.read_bytes())
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="evidence digest mismatch"):
        a02_recover.verify_originals(tmp_path)


def test_date_metadata_normalization_does_not_relax_decoding() -> None:
    expected = {"template_date": "3 November 2026", "max_new_tokens": 128, "do_sample": False}
    actual = {**expected, "template_date": "03 November 2026"}
    assert a02_recover._decoding_equal(actual, expected)
    for key, value in [
        ("max_new_tokens", 129),
        ("do_sample", True),
        ("template_date", "04 November 2026"),
    ]:
        assert not a02_recover._decoding_equal({**actual, key: value}, expected)


def test_historical_attempt3_adapter_rejects_the_later_attempt4_scorer() -> None:
    original = inspect.getsource(a02_score.verify_run)
    assert "if attempt not in (1, 2, 4):" in original
    with pytest.raises(ValueError, match="incompatible with the retained attempt-3 adapter"):
        a02_recover.adapted_scorer()


def test_prompt_validation_failure_never_becomes_qualified_score(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "original"
    run_dir.mkdir()
    (run_dir / "control.json").write_text("{}")
    teardown = tmp_path / "teardown.json"
    teardown.write_text("{}")
    output = tmp_path / "recovery"
    monkeypatch.setattr(a02_score, "_under_e", lambda path: path)
    monkeypatch.setattr(
        a02_recover,
        "verify_originals",
        lambda path: {"session_absent_after_stop": False, "watchdog_phase": "TRIGGERED"},
    )
    monkeypatch.setattr(
        a02_recover, "verify_teardown", lambda *args: {"decision": "TARGET_STOPPED"}
    )

    def reject(*args: Any) -> None:
        raise ValueError("action prompt differs from CPU preflight: synthetic-case")

    monkeypatch.setattr(a02_recover, "adapted_scorer", lambda: (reject, "synthetic scorer"))
    monkeypatch.setattr(
        a02_recover, "inspect_cases", lambda path: {"scientific_qualification": False}
    )
    receipt = a02_recover.recover(run_dir, teardown, output)
    assert receipt["disposition"] == "A02_ATTEMPT3_EVIDENCE_VALIDATION_FAILED"
    assert receipt["scientific_decision"] is None
    assert receipt["verified_report_sha256"] is None
    assert not (output / "verified.json").exists()
    assert (output / "unqualified-observed-diagnostics.json").exists()


def test_diagnostics_also_reject_changed_frozen_scientific_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def reject(protocol: Any) -> None:
        raise ValueError("scientific source file identity changed")

    monkeypatch.setattr(a02_recover, "adapted_scorer", lambda: None)
    monkeypatch.setattr(a02_experiment, "verify_protocol_source_bindings", reject)
    with pytest.raises(ValueError, match="scientific source file identity changed"):
        a02_recover.inspect_cases(tmp_path)
