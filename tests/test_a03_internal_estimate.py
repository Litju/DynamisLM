"""The CPU-only compute estimator reads blinded inputs only and authorizes nothing."""

from __future__ import annotations

import inspect
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from scripts import a02_v3_contract as v3
from scripts import a03_internal_config as config
from scripts import a03_internal_estimate as estimator
from scripts import a03_internal_run as runner
from scripts import a03_internal_seal as sealer

from a03_internal_fixtures import valid_packet

ROOT = Path(__file__).resolve().parents[1]


class WordTokenizer:
    """One token per whitespace-separated word of the rendered prompt. Carries no model."""

    def __init__(self, scale: int = 1) -> None:
        self.scale = scale

    def apply_chat_template(self, messages: Any, *, tokenize: bool, **_: Any) -> Any:
        rendered = json.dumps(messages, sort_keys=True)
        return list(range(len(rendered.split()) * self.scale)) if tokenize else rendered

    def encode(self, text: str, *, add_special_tokens: bool) -> list[int]:
        return list(range(len(text.split()) * self.scale))


@pytest.fixture(scope="module")
def blind(tmp_path_factory: pytest.TempPathFactory) -> tuple[bytes, bytes]:
    directory = valid_packet().write(tmp_path_factory.mktemp("packet"))
    exported = sealer.blind_export(directory)
    return exported["blind-requests.jsonl"], exported["blind-scenarios.jsonl"]


def test_estimate_counts_calls_tokens_and_applies_the_frozen_timing_model(
    blind: tuple[bytes, bytes],
) -> None:
    requests, scenarios = blind
    artifact = estimator.estimate(requests, scenarios, WordTokenizer())
    assert artifact["authorizes"] == "NOTHING"
    assert artifact["evidence_class"] == "INTERNAL_OWNER_ADJUDICATED"
    assert artifact["calls"] == {"items": 108, "per_item": 2, "total": 216}
    assert artifact["arms"] == ["N", "C1"]
    assert artifact["tokens"]["max_new_tokens"] == 128
    assert artifact["tokens"]["prompt_total"] == sum(artifact["tokens"]["per_item"].values())
    assert len(artifact["tokens"]["per_item"]) == 108 and artifact["valid"] is True
    # Independent hand calculation from the published planning constants.
    seconds = 216 * 7.65
    assert artifact["expected"] == {
        "generation_seconds": round(seconds, 6),
        "total_seconds": round(seconds + 602, 6),
        "sessions": 1,
        "cu": round((seconds + 602) / 3600 * 1.15 + 0.20, 6),
    }
    worst = 216 * 35.6894
    sessions = math.ceil(worst / (3600 - 602))
    assert artifact["worst_case"] == {
        "generation_seconds": round(worst, 6),
        "total_seconds": round(worst + sessions * 602, 6),
        "sessions": sessions,
        "cu": round((worst + sessions * 602) / 3600 * 1.15 + sessions * 0.20, 6),
    }
    assert sessions == 3 and artifact["timing"]["status"] == "PROVISIONAL_PLANNING_ONLY"
    assert (
        "CPU only" in artifact["device_note"] and "authorizes no compute" in artifact["device_note"]
    )


def test_estimate_is_byte_deterministic_and_independently_verifiable(
    blind: tuple[bytes, bytes],
) -> None:
    requests, scenarios = blind
    data = estimator.render(estimator.estimate(requests, scenarios, WordTokenizer()))
    assert data == estimator.render(estimator.estimate(requests, scenarios, WordTokenizer()))
    parsed = estimator.verify(data, requests, scenarios, WordTokenizer())
    assert parsed["estimate_sha256"] == v3.sha256(
        v3.canonical({k: v for k, v in parsed.items() if k != "estimate_sha256"}).encode()
    )
    forged = json.loads(data) | {"expected": {**parsed["expected"], "sessions": 0}}
    with pytest.raises(ValueError, match="does not reproduce"):
        estimator.verify(
            (v3.canonical(forged) + "\n").encode(), requests, scenarios, WordTokenizer()
        )
    with pytest.raises(ValueError, match="does not reproduce"):
        estimator.verify(data, requests, scenarios, WordTokenizer(scale=2))
    with pytest.raises(ValueError, match="does not reproduce"):
        estimator.verify(
            data, requests[: requests.rfind(b"\n", 0, -1) + 1], scenarios, WordTokenizer()
        )


def test_measured_timing_evidence_replaces_planning_values_and_is_digest_bound(
    blind: tuple[bytes, bytes],
) -> None:
    requests, scenarios = blind
    evidence = {
        "schema": estimator.TIMING_SCHEMA,
        "source": "fixture receipt",
        "expected_seconds_per_call": 8.8,
        "conservative_seconds_per_call": 20.0,
        "setup_teardown_seconds": 300,
        "calls": 6,
    }
    raw = (v3.canonical(evidence) + "\n").encode()
    artifact = estimator.estimate(requests, scenarios, WordTokenizer(), raw)
    assert artifact["timing"]["status"] == "MEASURED_FROM_BOUND_EVIDENCE"
    assert artifact["timing"]["evidence_sha256"] == v3.sha256(raw)
    assert artifact["expected"]["generation_seconds"] == pytest.approx(216 * 8.8)
    for bad in (
        evidence | {"expected_seconds_per_call": -1},
        evidence | {"schema": "x"},
        evidence | {"conservative_seconds_per_call": 1.0},
        evidence | {"extra": 1},
        evidence | {"setup_teardown_seconds": float("nan")},
    ):
        with pytest.raises(ValueError):
            estimator.timing_model(json.dumps(bad).encode())


def test_prompts_over_the_registered_bound_make_the_estimate_invalid(
    blind: tuple[bytes, bytes],
) -> None:
    requests, scenarios = blind
    artifact = estimator.estimate(requests, scenarios, WordTokenizer(scale=500))
    assert artifact["valid"] is False and artifact["tokens"]["items_over_prompt_bound"]


def test_estimator_never_reads_gold_or_the_sealed_packet(tmp_path: Path) -> None:
    packet = valid_packet().write(tmp_path / "packet")
    with pytest.raises(ValueError, match="gold visible to the runner"):
        runner.read_blind(packet)
    assert not [p for p in inspect.signature(estimator.estimate).parameters if "gold" in p]
    requests = sealer.blind_export(packet)["blind-requests.jsonl"].decode().splitlines()
    leaked = json.loads(requests[0]) | {"judgment": {}}
    scenarios = sealer.blind_export(packet)["blind-scenarios.jsonl"]
    with pytest.raises(ValueError, match="expected fields"):
        estimator.estimate(
            ("\n".join([v3.canonical(leaked), *requests[1:]]) + "\n").encode(),
            scenarios,
            WordTokenizer(),
        )


def test_estimator_imports_no_model_or_accelerator_stack() -> None:
    code = (
        "import sys; import scripts.a03_internal_estimate; "
        "bad = [m for m in ('torch', 'transformers', 'peft') if m in sys.modules]; "
        "assert not bad, bad"
    )
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, check=True)
    assert config.load_config()["compute"]["status"] == "PROVISIONAL_PLANNING_ONLY"
