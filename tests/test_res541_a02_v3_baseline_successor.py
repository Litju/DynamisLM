"""Synthetic CPU controls; never substitute these fixtures for sealed model evidence."""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from scripts import a02_v3_baseline_successor as successor
from scripts import a02_v3_contract as v3
from scripts import a02_v3_decision as decision
from scripts import a02_v3_execution as execution
from scripts import a02_v3_worker as worker

PROTOCOL = decision.load_protocol()


def synthetic_model_metadata() -> dict[str, Any]:
    return {
        "synthetic": True,
        "model_id": PROTOCOL["candidate_model"]["id"],
        "model_revision": PROTOCOL["candidate_model"]["revision"],
        "contract_profile_sha256": PROTOCOL["contract_profile_sha256"],
        "protocol_sha256": decision.protocol_sha256(),
    }


def extend_synthetic_checkpoint(path: Path, items: list[worker.WorkItem], stop: int) -> None:
    # Inject fixtures in one write; real worker persistence is tested separately and unchanged.
    state = worker.read_checkpoint(path, items)
    start, head = len(state["entries"]), state["head"]
    lines: list[bytes] = []
    for seq, item in enumerate(items[start:stop], start):
        entry = {
            "schema": worker.CHECKPOINT_SCHEMA,
            "seq": seq,
            "prev_sha256": head,
            "item": item.id,
            "record": synthetic_model_metadata(),
        }
        head = worker._line_hash(entry)
        lines.append((v3.canonical({**entry, "line_sha256": head}) + "\n").encode())
    with path.open("ab") as stream:
        stream.write(b"".join(lines))


class ReadonlyClient:
    def snapshot(self) -> dict[str, Any]:
        return {"balance": 100.0, "usage_rate_cu_per_hour": 0.0, "active_sessions": []}

    def sessions(self) -> list[str]:
        return []

    def new(self, *args: Any) -> None:
        raise AssertionError("CPU proposal/negative controls cannot allocate")


def test_sealed_manifest_detects_changed_bytes_and_unsafe_paths(tmp_path: Path) -> None:
    item = tmp_path / "synthetic.json"
    item.write_text('{"synthetic":true}')
    manifest = tmp_path / "execution-evidence-manifest-20261112.json"
    manifest.write_text(json.dumps({"files": {item.name: successor.digest(item)}}))
    bound = successor.digest(manifest)
    assert successor.verify_manifest(tmp_path, bound) == {item.name: successor.digest(item)}
    item.write_text('{"synthetic":"edited"}')
    with pytest.raises(ValueError, match="evidence changed"):
        successor.verify_manifest(tmp_path, bound)
    manifest.write_text(json.dumps({"files": {"../outside": "0" * 64}}))
    with pytest.raises(ValueError, match="unsafe"):
        successor.verify_manifest(tmp_path, successor.digest(manifest))
    with pytest.raises(ValueError, match="manifest changed"):
        successor.verify_manifest(tmp_path, bound)


@pytest.fixture
def prepared(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, dict[str, Any]]:
    # Dataset/gold qualification has its own full regression; do it once for these CPU controls.
    monkeypatch.setattr(decision, "load_protocol", lambda: PROTOCOL)
    parent = tmp_path / "synthetic-predecessor"
    parent.mkdir()
    (parent / "baseline").mkdir()
    bounds = execution.RuntimeBounds(
        session_seconds=3600,
        exec_seconds=3300,
        cleanup_reserve_seconds=300,
        inference_overhead_seconds=215,
        worker_margin_seconds=60,
        cost_buffer_cu=0.2,
    )

    def write(name: str, data: Any) -> None:
        (parent / name).write_text(json.dumps(data))

    write(
        "baseline-plan-native-cache.json",
        {
            "bounds": asdict(bounds),
            "item_cost_bounds_seconds": {"QUALIFICATION": 100},
            "scorer_call_bound": {"used_for_pricing": 73},
        },
    )
    write(
        "baseline/session-001-status.json",
        {
            "prepare_seconds": 98.16,
            "native_cache_measurements": [{"seconds": 16.67, "tokens": 123}],
        },
    )
    write("baseline/session-002-status.json", {"prepare_seconds": 155.097149113})
    write(
        "baseline/ledger.json",
        {
            "sessions": [
                {
                    "index": 1,
                    "name": "old-001",
                    "compute_units_spent": 0.75,
                    "cost_status": "KNOWN",
                    "committed_items": 307,
                },
                {
                    "index": 2,
                    "name": "old-002",
                    "compute_units_spent": 0.05,
                    "cost_status": "KNOWN",
                    "committed_items": 307,
                },
            ]
        },
    )
    write(
        "budget-ledger.json",
        {
            "sessions": [
                {"kind": "DIAGNOSTIC", "conservative_cu": 0.3564},
                {"kind": "BASELINE", "conservative_cu": 1.0039, "charge_sha256": "1" * 64},
                {"kind": "BASELINE", "conservative_cu": 0.0685, "charge_sha256": "2" * 64},
            ]
        },
    )
    protocol = decision.load_protocol()
    items = worker.work_items(protocol)
    # Synthetic chain for worker boundary tests; fixed production hashes reject these bytes.
    records = []
    lines: list[bytes] = []
    head = worker.GENESIS
    checkpoint = parent / "baseline/checkpoint.jsonl"
    for index, item in enumerate(items[:307]):
        record = {
            "synthetic": True,
            "schema": worker.QUALIFICATION_SCHEMA if index == 0 else "synthetic-arm",
            "passed": True,
            "model_id": protocol["candidate_model"]["id"],
            "model_revision": protocol["candidate_model"]["revision"],
            "contract_profile_sha256": protocol["contract_profile_sha256"],
            "protocol_sha256": decision.protocol_sha256(),
            "arm": item.arm,
            "seconds": 10.0,
            "scorer_calls": 33,
        }
        entry = {
            "schema": worker.CHECKPOINT_SCHEMA,
            "seq": index,
            "prev_sha256": head,
            "item": item.id,
            "record": record,
        }
        head = worker._line_hash(entry)
        lines.append((v3.canonical({**entry, "line_sha256": head}) + "\n").encode())
        records.append(record)
    checkpoint.write_bytes(b"".join(lines))
    predecessor = {
        "synthetic": True,
        "source_identity": {"commit": successor.PREDECESSOR_HEAD, "tree": "b" * 40},
        "new_campaign_spent_cu": 1.4288,
        "unspent_original_ceiling_cu": 48.5712,
        "remaining_worklist": [x.id for x in items[307:]],
        "last_observed_t4_cu_per_hour": 1.15,
    }
    monkeypatch.setattr(successor, "PREDECESSOR", parent)
    monkeypatch.setattr(successor, "verify_predecessor", lambda: predecessor)
    monkeypatch.setattr(successor, "scientific_compatibility", lambda: {"synthetic": "unchanged"})
    monkeypatch.setattr(
        execution, "source_identity", lambda: {"commit": "a" * 40, "tree": "c" * 40}
    )

    def archive(path: Path) -> tuple[Path, str]:
        path.write_bytes(b"synthetic source archive")
        return path, successor.digest(path)

    monkeypatch.setattr(execution, "source_archive", archive)
    monkeypatch.setattr(
        successor, "head_archive_sha256", lambda: v3.sha256(b"synthetic source archive")
    )
    directory = tmp_path / "successor"
    proposal = successor.prepare(directory, ReadonlyClient())
    return directory, proposal


def test_proposal_prices_only_remaining_work_and_preserves_original_ceiling(prepared: Any) -> None:
    directory, proposal = prepared
    assert successor.validate(directory) == proposal
    plan = proposal["plan"]
    assert plan["starting_item"] == 307 and plan["scheduled_work_items"] == 274
    assert plan["sessions"][0]["first_item"] == 307 and plan["sessions"][-1]["end_item"] == 581
    assert plan["preparation_derivation"]["result_seconds"] == 660
    assert plan["qualification"] == "INHERITED_PASSED_DO_NOT_REPEAT"
    assert plan["compute_units"]["maximum_additional_cu"] <= 48.5712
    assert proposal["original_maximum_new_cu"] == 50 and proposal["training_authorized"] is False
    assert proposal["status"] == "PROPOSED_NOT_AUTHORIZED"
    assert plan["compute_units"]["expected_sessions"] >= 1
    expected = (
        plan["compute_units"]["expected_sessions"] * (660 + 215 + 300)
        + plan["compute_units"]["expected_scoring_seconds"]
    )
    assert plan["compute_units"]["expected_at_observed_rate_cu"] == pytest.approx(
        expected * 1.15 / 3600
    )
    ledger = successor.inherited_ledger(proposal)
    assert [x["index"] for x in ledger["sessions"]] == [1, 2]
    assert all(
        x["source_identity"]["commit"] == successor.PREDECESSOR_HEAD for x in ledger["sessions"]
    )
    assert [x["compute_units_spent"] for x in ledger["sessions"]] == [1.0039, 0.0685]


def test_copying_proposal_cannot_reset_execution_marker(prepared: Any, tmp_path: Path) -> None:
    directory, proposal = prepared
    copied = tmp_path / "replay"
    shutil.copytree(directory, copied)
    with pytest.raises(ValueError, match="source/archive differs"):
        successor.validate(copied)
    (directory / "source.tar").write_bytes(b"changed")
    with pytest.raises(ValueError, match="source/archive differs"):
        successor.validate(directory)


def test_rehashed_archive_still_has_to_be_the_exact_head_archive(prepared: Any) -> None:
    directory, proposal = prepared
    (directory / "source.tar").write_bytes(b"changed archive")
    proposal["source_archive_sha256"] = successor.digest(directory / "source.tar")
    proposal["proposal_sha256"] = v3.sha256(
        v3.canonical({k: v for k, v in proposal.items() if k != "proposal_sha256"}).encode()
    )
    (directory / "proposal.json").write_text(json.dumps(proposal))
    with pytest.raises(ValueError, match="source/archive differs"):
        successor.validate(directory)


@pytest.mark.parametrize("fault", ["rate", "scope", "watchdog", "index", "expiry", "plan"])
def test_rehashed_proposal_cannot_change_derived_authority(prepared: Any, fault: str) -> None:
    directory, proposal = prepared
    if fault == "rate":
        proposal["last_observed_t4_cu_per_hour"] = 2.0
    elif fault == "scope":
        proposal["training_authorized"] = True
    elif fault == "watchdog":
        proposal["independent_watchdog_seconds"] = 7200
    elif fault == "index":
        proposal["first_new_session_index"] = 2
    elif fault == "expiry":
        proposal["valid_until_utc"] = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    else:
        proposal["plan"]["item_cost_bounds_seconds"]["ZERO_SHOT_CONSTRAINED"] = 0.01
    proposal["proposal_sha256"] = v3.sha256(
        v3.canonical({k: v for k, v in proposal.items() if k != "proposal_sha256"}).encode()
    )
    (directory / "proposal.json").write_text(json.dumps(proposal))
    with pytest.raises(ValueError):
        successor.validate(directory)


def test_expiry_must_cover_full_session_and_teardown(prepared: Any) -> None:
    directory, proposal = prepared
    proposal["valid_until_utc"] = (datetime.now(UTC) + timedelta(seconds=100)).isoformat()
    with pytest.raises(ValueError, match="bounded session"):
        successor.validate_window(proposal, 3690)
    proposal["valid_until_utc"] = "2030-01-01T00:00:00"
    with pytest.raises(ValueError):
        successor.validate_window(proposal)


def approval(proposal: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "RES541_BASELINE_SUCCESSOR_OWNER_APPROVAL_V1",
        "proposal_sha256": proposal["proposal_sha256"],
        "approved": True,
        "owner_statement": "SYNTHETIC CPU TEST APPROVAL ONLY",
        "recorded_utc": datetime.now(UTC).isoformat(),
    }


def test_explicit_new_owner_receipt_required_before_any_allocation(prepared: Any) -> None:
    directory, proposal = prepared
    for receipt in (
        {},
        dict(approval(proposal), proposal_sha256="0" * 64),
        dict(approval(proposal), approved=False),
    ):
        path = directory / "bad-owner.json"
        path.write_text(json.dumps(receipt))
        with pytest.raises(ValueError, match="owner approval"):
            successor.run(directory, path, ReadonlyClient())
        assert not (directory / "execution-used.json").exists()


def test_inherited_qualification_is_not_repeated(prepared: Any) -> None:
    from test_res541_a02_v3_worker import COSTS, _Backend

    directory, proposal = prepared
    checkpoint = successor.PREDECESSOR / "baseline/checkpoint.jsonl"
    target = directory / "worker-boundary.jsonl"
    target.write_bytes(checkpoint.read_bytes())

    class Backend(_Backend):
        def reference_scorer(self) -> Any:
            raise AssertionError("inherited qualification must not run again")

    result = worker.run_worker(
        protocol=decision.load_protocol(),
        items=worker.work_items(decision.load_protocol()),
        checkpoint=target,
        backend=Backend(),
        deadline=float("inf"),
        item_cost_bounds=COSTS,
        stop_after=2,
    )
    assert result["committed"] == 309
    assert target.read_bytes().startswith(checkpoint.read_bytes())
    rows = worker.read_checkpoint(target, worker.work_items(decision.load_protocol()))["entries"]
    assert rows[307]["item"] == "HELDOUT:5410:153|ZERO_SHOT_UNCONSTRAINED"


@pytest.mark.parametrize("failed", [False, True])
def test_successor_preserves_prefix_starts_session3_and_cannot_retry(
    prepared: Any, monkeypatch: Any, failed: bool
) -> None:
    directory, proposal = prepared
    path = directory / "synthetic-owner.json"
    path.write_text(json.dumps(approval(proposal)))
    original = (successor.PREDECESSOR / "baseline/checkpoint.jsonl").read_bytes()
    called = []

    def session(**kwargs: Any) -> dict[str, Any]:
        index = kwargs["session_index"]
        called.append(index)
        assert index == 3
        checkpoint = kwargs["run_dir"] / "checkpoint.jsonl"
        assert checkpoint.read_bytes() == original
        if not failed:
            items = worker.work_items(decision.load_protocol())
            extend_synthetic_checkpoint(checkpoint, items, len(items))
        state = {
            "quota_before": {"balance": 100},
            "quota_after": {"balance": 99.9},
            "rate_after_allocation": 1.15,
            "target_absent_after_stop": True,
            "stopped": True,
            "sessions_before": [],
            "unrelated_sessions_after": [],
            "work": {"returncode": 0, "timed_out": False},
            "merge": {"torn_tail_discarded": False},
        }
        if failed:
            state["failure"] = "synthetic nested timeout"
        (kwargs["run_dir"] / f"session-{index:03d}-control.json").write_text(json.dumps(state))
        return state

    monkeypatch.setattr(execution, "run_session", session)
    monkeypatch.setattr(worker, "score_checkpoint", lambda *args: {"synthetic": True})
    result = successor.run(directory, path, ReadonlyClient())
    assert result["complete"] is (not failed)
    assert called == [3]
    assert (successor.PREDECESSOR / "baseline/checkpoint.jsonl").read_bytes() == original
    assert result["new_task_evaluations"] == (0 if failed else 274)
    with pytest.raises(ValueError, match="consumed"):
        successor.run(directory, path, ReadonlyClient())
    assert called == [3]


@pytest.mark.parametrize(
    ("finish", "edit_proposal", "corrupt_prefix", "expire_after_stop", "final_slot"),
    [
        (True, False, False, False, False),
        (False, False, False, False, False),
        (False, True, False, False, False),
        (True, False, True, False, False),
        (True, False, False, True, False),
        (True, False, True, False, True),
    ],
    ids=[
        "complete_near_expiry",
        "incomplete_near_expiry",
        "changed_approval",
        "changed_prefix",
        "completed_then_expired",
        "final_slot_changed_prefix",
    ],
)
def test_completion_and_approved_window_at_admission_boundary(
    prepared: Any,
    monkeypatch: Any,
    finish: bool,
    edit_proposal: bool,
    corrupt_prefix: bool,
    expire_after_stop: bool,
    final_slot: bool,
) -> None:
    from types import SimpleNamespace

    directory, proposal = prepared
    end = datetime.fromisoformat(proposal["valid_until_utc"])
    slot_count = proposal["maximum_new_sessions"] if final_slot else 1
    clock = [end - timedelta(seconds=3700 * slot_count)]
    seconds = [0.0]
    monkeypatch.setattr(
        successor,
        "datetime",
        SimpleNamespace(now=lambda tz: clock[0], fromisoformat=datetime.fromisoformat),
    )
    monkeypatch.setattr(successor, "time", SimpleNamespace(monotonic=lambda: seconds[0]))
    owner = directory / "synthetic-owner.json"
    owner.write_text(json.dumps(approval(proposal)))
    called = []
    scored = []

    def session(**kwargs: Any) -> dict[str, Any]:
        index = kwargs["session_index"]
        called.append(index)
        assert index == 3 or final_slot, "another session must not be admitted at this boundary"
        target = directory / "checkpoint.jsonl"
        items = worker.work_items(PROTOCOL)
        start = len(worker.read_checkpoint(target, items)["entries"])
        finished_slot = finish and (not final_slot or index == proposal["plan"]["session_count"])
        stop = len(items) if finished_slot else start + 1
        extend_synthetic_checkpoint(target, items, stop)
        if corrupt_prefix and finished_slot:
            rows = worker.read_checkpoint(target, items)["entries"]
            rows[0]["record"]["synthetic"] = "replaced inherited bytes"
            head = worker.GENESIS
            lines: list[bytes] = []
            for row in rows:
                row["prev_sha256"] = head
                head = worker._line_hash(row)
                lines.append((v3.canonical({**row, "line_sha256": head}) + "\n").encode())
            target.write_bytes(b"".join(lines))
        clock[0] += timedelta(seconds=3600)
        seconds[0] += 3600
        if edit_proposal:
            changed = json.loads((directory / "proposal.json").read_text())
            for key in ("valid_from_utc", "valid_until_utc"):
                changed[key] = (
                    datetime.fromisoformat(changed[key]) + timedelta(seconds=3600)
                ).isoformat()
            changed["proposal_sha256"] = v3.sha256(
                v3.canonical({k: v for k, v in changed.items() if k != "proposal_sha256"}).encode()
            )
            (directory / "proposal.json").write_text(json.dumps(changed))
        state = {
            "quota_before": {"balance": 100.0},
            "quota_after": {"balance": 98.85},
            "rate_after_allocation": 1.15,
            "target_absent_after_stop": True,
            "stopped": True,
            "sessions_before": [],
            "unrelated_sessions_after": [],
            "work": {"returncode": 0, "timed_out": False},
            "merge": {"torn_tail_discarded": False},
        }
        (directory / f"session-{index:03d}-control.json").write_text(json.dumps(state))
        return state

    def score(*args: Any) -> dict[str, Any]:
        scored.append(True)
        return {"synthetic": True}

    monkeypatch.setattr(execution, "run_session", session)
    original_anomaly = execution.session_anomaly

    def anomaly(*args: Any) -> Any:
        result = original_anomaly(*args)
        if expire_after_stop:
            clock[0] += timedelta(seconds=150)
        return result

    monkeypatch.setattr(execution, "session_anomaly", anomaly)
    monkeypatch.setattr(worker, "score_checkpoint", score)
    result = successor.run(directory, owner, ReadonlyClient())
    assert called == (list(range(3, proposal["plan"]["session_count"] + 1)) if final_slot else [3])
    expected_complete = finish and not corrupt_prefix
    assert result["complete"] is expected_complete
    assert len(scored) == (1 if expected_complete else 0)
    assert (directory / "terminal-anomaly.json").exists() is (not expected_complete)
    if edit_proposal:
        assert "approved proposal" in result["error"]
    if corrupt_prefix:
        assert "replaced inherited checkpoint" in result["error"]
