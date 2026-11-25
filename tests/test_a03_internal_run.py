"""Track A: the gold-free runner over the real RES-430 `ask` pipeline with a scripted model."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from scripts import a02_v3_contract as v3
from scripts import a02_v3_worker as checkpoint
from scripts import a03_internal_config as config
from scripts import a03_internal_replay as replay
from scripts import a03_internal_run as runner
from scripts import a03_prospective_run as prospective_run
from scripts import research_ask as research

from a03_internal_fixtures import (
    BUNDLE_SHA,
    IDENTITY,
    Packet,
    Scripted,
    install_memoization,
    pack_and_run,
    prepare_run,
    scripted_outputs,
    valid_packet,
)


@pytest.fixture(autouse=True)
def fast(monkeypatch: pytest.MonkeyPatch) -> None:
    install_memoization(monkeypatch)


def rows(output: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (output / "outputs.jsonl").read_text().splitlines()]


def test_full_run_commits_every_row_through_the_deployed_ask_pipeline(tmp_path: Path) -> None:
    packet = valid_packet()
    backend = Scripted(scripted_outputs(packet))
    run = pack_and_run(tmp_path, packet, backend)
    assert run["result"]["status"] == "COMMITTED" and run["result"]["entries"] == 216
    items = runner.load_blind(run["requests"], run["scenarios"])
    work = runner.work_items(items)
    entries = rows(run["output"])
    assert [(e["record"]["item_id"], e["record"]["arm"]) for e in entries] == [
        (w.key, w.arm) for w in work
    ]
    assert [arm for _, arm in backend.calls] == [w.arm for w in work]
    assert {w.arm for w in work} == {"N", "C1"}
    per_item = [{w.arm for w in work if w.key == i.item_id} for i in items]
    assert all(arms == {"N", "C1"} for arms in per_item)
    for entry in entries:
        receipt = entry["record"]["receipt"]
        assert receipt["schema"] == research.SCHEMA  # the shipped ask receipt
        assert receipt["proposal"]["decoding"] == entry["record"]["arm"]
        assert "identity" not in receipt
        assert receipt["scenario"]["origin"] == "SYNTHETIC_DETERMINISTIC"
    runtime = json.loads((run["output"] / "runtime.json").read_text())
    assert runtime["identity"] == IDENTITY
    commit = json.loads((run["output"] / "output-commit.json").read_text())
    assert commit["status"] == "COMMITTED" and commit["head"] == entries[-1]["line_sha256"]


def test_the_model_receives_only_question_and_scenario_evidence(tmp_path: Path) -> None:
    packet = valid_packet()
    seen: list[dict[str, Any]] = []

    class Spy(Scripted):
        def generate(
            self, arm: str, request: dict[str, Any], prompt: list[int], deadline: float
        ) -> Any:
            seen.append(request)
            return super().generate(arm, request, prompt, deadline)

    pack_and_run(tmp_path, packet, Spy(scripted_outputs(packet)))
    assert len(seen) == 216
    for request in seen:
        assert set(request) == {"question", "observations", "requested_claims"}
        blob = json.dumps(request)
        for forbidden in (
            "gold",
            "stratum",
            "cluster",
            "CAUSAL_OVERREACH",
            "acceptable",
            "judgment",
        ):
            assert forbidden not in blob


def test_run_is_resumable_only_from_the_exact_prefix_and_commitment_is_immutable(
    tmp_path: Path,
) -> None:
    packet = valid_packet()
    backend = Scripted(scripted_outputs(packet))
    prepared = prepare_run(tmp_path, packet, backend)
    args = (prepared["manifest"], prepared["requests"], prepared["scenarios"], prepared["output"])
    partial = runner.run(*args, prepared["runtime"], seconds=1e-9, verify_source=False)
    assert partial == {
        "status": "INCOMPLETE",
        "entries": 0,
        "prefix_sha256": partial["prefix_sha256"],
    }
    assert not (prepared["output"] / "output-commit.json").exists()
    with pytest.raises(ValueError, match="prefix digest"):
        runner.run(*args, prepared["runtime"], seconds=60, verify_source=False)
    done = runner.run(
        *args,
        prepared["runtime"],
        seconds=3600,
        resume_sha256=partial["prefix_sha256"],
        verify_source=False,
    )
    assert done["status"] == "COMMITTED"
    with pytest.raises(ValueError, match="immutable"):
        runner.run(*args, prepared["runtime"], seconds=60, verify_source=False)
    with pytest.raises(ValueError, match="complete run is committed|cannot claim"):
        runner.commit_partial(
            prepared["output"],
            prepared["manifest"],
            runner.work_items(runner.load_blind(prepared["requests"], prepared["scenarios"])),
            "EXHAUSTED",
        )


def test_gold_visible_to_the_runner_is_refused(tmp_path: Path) -> None:
    packet = valid_packet()
    prepared = prepare_run(tmp_path, packet, Scripted(scripted_outputs(packet)))
    # The sealed packet directory is not a blinded input.
    with pytest.raises(ValueError, match="gold visible to the runner"):
        runner.read_blind(prepared["protected"])
    (prepared["blind"] / "gold.jsonl").write_text("{}\n")
    with pytest.raises(ValueError, match="gold visible to the runner"):
        runner.read_blind(prepared["blind"])
    (prepared["blind"] / "gold.jsonl").unlink()
    runner.read_blind(prepared["blind"])
    (prepared["output"] / "gold.jsonl").write_text("{}\n")
    with pytest.raises(ValueError, match="gold visible to the runner"):
        runner.run(
            prepared["manifest"],
            prepared["requests"],
            prepared["scenarios"],
            prepared["output"],
            prepared["runtime"],
            seconds=60,
            verify_source=False,
        )
    assert not prepared["runtime"].backend.calls


@pytest.mark.parametrize("field", ["judgment", "stratum", "cluster_id", "critical_families"])
def test_blinded_requests_reject_gold_or_sampling_fields(tmp_path: Path, field: str) -> None:
    packet = valid_packet()
    prepared = prepare_run(tmp_path, packet, Scripted({}))
    lines = prepared["requests"].decode().splitlines()
    leaked = json.loads(lines[0]) | {field: "x"}
    tampered = ("\n".join([v3.canonical(leaked), *lines[1:]]) + "\n").encode()
    with pytest.raises(ValueError, match="expected fields"):
        runner.load_blind(tampered, prepared["scenarios"])


def test_missing_unused_or_mismatched_scenario_bindings_are_refused(tmp_path: Path) -> None:
    prepared = prepare_run(tmp_path, valid_packet(), Scripted({}))
    requests = prepared["requests"].decode().splitlines()
    scenarios = prepared["scenarios"].decode().splitlines()
    with pytest.raises(ValueError, match="missing scenario binding"):
        runner.load_blind(prepared["requests"], ("\n".join(scenarios[1:]) + "\n").encode())
    target = json.loads(requests[0])["scenario_id"]
    without = [line for line in requests if json.loads(line)["scenario_id"] != target]
    with pytest.raises(ValueError, match="unsorted or has unused"):
        runner.load_blind(("\n".join(without) + "\n").encode(), prepared["scenarios"])
    with pytest.raises(ValueError, match="unsorted"):
        runner.load_blind(("\n".join(reversed(requests)) + "\n").encode(), prepared["scenarios"])
    swapped = json.loads(scenarios[0]) | {"scenario_id": "eval-" + "9" * 12}
    with pytest.raises(ValueError, match="mismatched blinded scenario identity"):
        runner.load_blind(
            prepared["requests"],
            ("\n".join([v3.canonical(swapped), *scenarios[1:]]) + "\n").encode(),
        )
    with pytest.raises(ValueError, match="validator"):
        runner.load_blind(
            prepared["requests"],
            (
                "\n".join(
                    [v3.canonical(json.loads(scenarios[0]) | {"scenario": "{}"}), *scenarios[1:]]
                )
                + "\n"
            ).encode(),
        )


def test_wrong_bundle_digest_or_tampered_manifest_fails_before_inference(tmp_path: Path) -> None:
    packet = valid_packet()
    backend = Scripted(scripted_outputs(packet))
    prepared = prepare_run(tmp_path, packet, backend)
    args = (prepared["requests"], prepared["scenarios"], prepared["output"])
    other = research.ResearchRuntime(
        backend, {**IDENTITY, "bundle": {**IDENTITY["bundle"], "archive_sha256": "00" * 32}}
    )
    with pytest.raises(ValueError, match="bundle archive digest differs"):
        runner.run(prepared["manifest"], *args, other, seconds=60, verify_source=False)
    for key, value in (
        ("order_seed", 741132),
        ("protocol_sha256", "0" * 64),
        ("config_sha256", "0" * 64),
        ("bundle_archive_sha256", "00" * 32),
        ("mode", "PROSPECTIVE"),
        ("independence", "PARTIAL"),
    ):
        with pytest.raises(ValueError, match="differ"):
            runner.run(
                prepared["manifest"] | {key: value},
                *args,
                prepared["runtime"],
                seconds=60,
                verify_source=False,
            )
    with pytest.raises(ValueError, match="differ"):
        runner.verify_manifest(
            prepared["manifest"],
            prepared["requests"],
            prepared["scenarios"],
            bundle_archive_sha256="ee" * 32,
            verify_source=False,
        )
    assert not backend.calls
    assert prepared["manifest"]["evidence_class"] == "INTERNAL_OWNER_ADJUDICATED"
    assert prepared["manifest"]["order_seed"] == config.load_config()["statistics"]["order_seed"]
    assert BUNDLE_SHA == prepared["manifest"]["bundle_archive_sha256"]


def test_model_errors_timeouts_and_truncations_become_failure_rows_not_exclusions(
    tmp_path: Path,
) -> None:
    packet = valid_packet()
    outputs = scripted_outputs(packet)
    first, second, third = packet.requests[0], packet.requests[1], packet.requests[2]
    outputs[first["question"], "C1"] = RuntimeError("model failed")
    outputs[second["question"], "N"] = TimeoutError("late")
    outputs[third["question"], "C1"] = "<not-a-tool-call>"
    run = pack_and_run(tmp_path, packet, Scripted(outputs))
    assert run["result"]["status"] == "COMMITTED" and run["result"]["entries"] == 216
    by_key = {
        (e["record"]["item_id"], e["record"]["arm"]): e["record"] for e in rows(run["output"])
    }
    errored = by_key[first["item_id"], "C1"]
    assert errored["receipt"] is None and errored["error"] == "UnsupportedRuntimeError"
    timeout = by_key[second["item_id"], "N"]
    assert timeout["receipt"]["admission"]["parse_status"] == "INCOMPLETE"
    assert timeout["receipt"]["proposal"]["termination"] == "MODEL_TIMEOUT"
    garbage = by_key[third["item_id"], "C1"]["receipt"]
    assert garbage["admission"]["parse_status"] in ("REJECTED", "INCOMPLETE")
    assert not garbage["admission"]["operation_executed"]


def test_gold_free_live_stop_rules_stop_and_seal_a_partial_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    packet = valid_packet()
    prepared = prepare_run(tmp_path, packet, Scripted(scripted_outputs(packet)))
    real = research.ask
    calls = [0]

    def forged(scenario: Any, question: str, runtime: Any) -> Any:
        receipt, code = real(scenario, question, runtime)
        if calls[0] == 3:
            receipt["result"] = {"operation": "other:operation", "registered_output_hash": "x"}
        calls[0] += 1
        return receipt, code

    monkeypatch.setattr(research, "ask", forged)
    stopped = runner.run(
        prepared["manifest"],
        prepared["requests"],
        prepared["scenarios"],
        prepared["output"],
        prepared["runtime"],
        seconds=3600,
        verify_source=False,
    )
    assert stopped["status"] == "STOPPED_LIVE_RULE"
    assert stopped["rule"] == "DISPATCH_OTHER_THAN_RES69_ABSOLUTE_CHANGE"
    assert stopped["entries"] == 4
    work = runner.work_items(runner.load_blind(prepared["requests"], prepared["scenarios"]))
    commit = runner.commit_partial(prepared["output"], prepared["manifest"], work, "STOPPED")
    assert commit["status"] == "STOPPED" and commit["entries"] == 4
    with pytest.raises(ValueError, match="immutable"):
        runner.run(
            prepared["manifest"],
            prepared["requests"],
            prepared["scenarios"],
            prepared["output"],
            prepared["runtime"],
            seconds=3600,
            resume_sha256=stopped["prefix_sha256"],
            verify_source=False,
        )


def test_live_violation_rules() -> None:
    ok = {"result": {"operation": replay.RES69, "registered_output_hash": "h"}}
    assert runner.live_violation(ok) is None
    assert runner.live_violation({"result": None}) is None
    assert (
        runner.live_violation({"result": {"operation": replay.RES69, "registered_output_hash": ""}})
        == "NUMERIC_RESULT_WITHOUT_RECEIPT"
    )
    assert (
        runner.live_violation({"result": {"operation": "x", "registered_output_hash": "h"}})
        == "DISPATCH_OTHER_THAN_RES69_ABSOLUTE_CHANGE"
    )


def test_altered_or_reordered_outputs_after_commitment_are_detected(tmp_path: Path) -> None:
    packet = valid_packet()
    run = pack_and_run(tmp_path, packet, Scripted(scripted_outputs(packet)))
    work = runner.work_items(runner.load_blind(run["requests"], run["scenarios"]))
    path = run["output"] / "outputs.jsonl"
    original = path.read_bytes()
    runner.verify_rows(path, run["manifest"], work)
    lines = original.splitlines(keepends=True)
    path.write_bytes(original.replace(b"MODEL_EOS", b"TOKEN_LIMIT", 1))
    with pytest.raises(checkpoint.CheckpointError):
        runner.verify_rows(path, run["manifest"], work)
    path.write_bytes(b"".join([lines[1], lines[0], *lines[2:]]))
    with pytest.raises(checkpoint.CheckpointError):
        runner.verify_rows(path, run["manifest"], work)
    path.write_bytes(original)
    other = run["manifest"] | {"order_seed": 1}
    with pytest.raises(ValueError, match="binding differs"):
        runner.verify_rows(path, other, work)


def test_a_packet_can_not_masquerade_as_a_prospective_runner_input(tmp_path: Path) -> None:
    from scripts import a03_prospective_run as prospective

    packet = valid_packet()
    prepared = prepare_run(tmp_path, packet, Scripted({}))
    with pytest.raises((ValueError, KeyError)):
        prospective.load_items(prepared["requests"], prepared["scenarios"])
    assert runner.SCHEMA != prospective.SCHEMA
    assert prepared["manifest"]["schema"] == runner.SCHEMA
    assert (
        "mode" in prepared["manifest"] and prepared["manifest"]["mode"] != prospective.PROSPECTIVE
    )
    assert isinstance(packet, Packet)


def test_manifest_step_writes_run_json_beside_the_blinded_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from a03_internal_fixtures import FIXTURE_SOURCE

    prepared = prepare_run(tmp_path, valid_packet(), Scripted({}))
    monkeypatch.setattr(runner, "source_identity", lambda: FIXTURE_SOURCE)
    written = runner.write_manifest(
        prepared["blind"],
        packet_sha256=prospective_run.object_hash(prepared["packet_manifest"]),
        bundle_archive_sha256=BUNDLE_SHA,
    )
    assert written == prepared["manifest"]
    on_disk = (prepared["blind"] / "run.json").read_bytes()
    assert on_disk == (v3.canonical(written) + "\n").encode()
    assert runner.read_blind(prepared["blind"]) == (prepared["requests"], prepared["scenarios"])
    with pytest.raises(FileExistsError):
        runner.write_manifest(
            prepared["blind"],
            packet_sha256=prospective_run.object_hash(prepared["packet_manifest"]),
            bundle_archive_sha256=BUNDLE_SHA,
        )


def test_real_runs_require_an_exact_clean_source_checkout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prospective_run, "_git", lambda *args: " M scripts/a03_internal_run.py")
    with pytest.raises(ValueError, match="exact clean source checkout"):
        runner.source_identity()
