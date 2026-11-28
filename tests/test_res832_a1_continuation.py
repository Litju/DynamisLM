"""Falsification tests for the RES-832 continuation repairs.

Every test here pins a defect that the first campaign demonstrated or that independent source
inspection found, so a regression fails deterministically instead of consuming another session:

* PEFT 0.16.0 adapter semantics (``disable_adapter()`` is the only context manager);
* explicit remote base/adapter binding and pinned-interpreter enforcement;
* the gold-free payload reconstructing every frozen request without private local files;
* the D6 retrospective export carrying requests but never gold;
* controller accounting at the full 1,332 generations including D6;
* the cumulative session deadline;
* abort-on-defect versus resumable time-slice interruption;
* the disclosed prompt bound that the frozen few-shot arm needs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from scripts import a02_v3_contract as v3
from scripts import (
    a1_backend,
    a1_cases,
    a1_chain,
    a1_colab,
    a1_colab_worker,
    a1_manifest,
    a1_payload,
    a1_rehearsal,
    a1_retrospective,
    a1_run,
    a1_work_order,
)
from scripts import a1_representation as rep

ROOT = Path(__file__).resolve().parents[1]
needs_evidence = pytest.mark.skipif(
    not a1_retrospective.available(),
    reason="private RES-774 evidence lives outside Git; verified locally, not on hosted CI",
)


class FakeTunerLayer:
    """The only PEFT surface the backend relies on: the per-layer disable flag."""

    def __init__(self) -> None:
        self.disable_adapters = False
        self.adapter_layer_names: tuple[str, ...] = ("lora",)
        self.active_adapters = ["default"]


class FakePeftModel:
    """A minimal model whose adapter state is real state, not a mocked call count."""

    def __init__(self, layers: int = 3) -> None:
        self.layers = [FakeTunerLayer() for _ in range(layers)]
        self.enable_adapter_layers_calls = 0
        self.disable_adapter_layers_calls = 0

    def modules(self) -> list[Any]:
        return list(self.layers)

    def disable_adapter(self) -> Any:
        """Mirror PEFT 0.16.0: a real context manager that flips every layer and restores."""
        model = self

        class _Context:
            def __enter__(self) -> None:
                for layer in model.layers:
                    layer.disable_adapters = True

            def __exit__(self, *args: Any) -> None:
                for layer in model.layers:
                    layer.disable_adapters = False

        return _Context()

    # Deliberately unusable as context managers: PEFT 0.16.0 returns None from these.
    def enable_adapter_layers(self) -> None:
        self.enable_adapter_layers_calls += 1

    def disable_adapter_layers(self) -> None:
        self.disable_adapter_layers_calls += 1


def _client() -> Any:
    return object()


def _backend_with(model: Any) -> Any:
    backend = a1_backend.A1Backend.__new__(a1_backend.A1Backend)
    backend.model = model
    backend.tokenizer = None
    backend.mask = None  # type: ignore[assignment]
    backend.calls = 0
    backend.seconds = 0.0
    backend.arm_calls = {"M0": 0, "M1": 0}
    backend.adapter_checks = 0
    backend._expected_adapter = None
    return backend


def test_peft_layer_state_is_read_not_assumed() -> None:
    model = FakePeftModel()
    assert a1_backend.adapter_enabled(model) is True
    for layer in model.layers:
        layer.disable_adapters = True
    assert a1_backend.adapter_enabled(model) is False
    assert a1_backend.adapter_enabled(object()) is None


def test_irregular_adapter_state_fails_closed() -> None:
    model = FakePeftModel()
    model.layers[0].disable_adapters = True
    with pytest.raises(a1_backend.BackendError):
        a1_backend.adapter_enabled(model)


def test_m0_uses_the_real_disable_adapter_context_manager() -> None:
    model = FakePeftModel()
    backend = _backend_with(model)
    with backend.adapted("M0"):
        assert a1_backend.adapter_enabled(model) is False
        assert model.enable_adapter_layers_calls == 0
        assert model.disable_adapter_layers_calls == 0
    assert a1_backend.adapter_enabled(model) is True


def test_m1_leaves_the_adapter_enabled() -> None:
    model = FakePeftModel()
    backend = _backend_with(model)
    with backend.adapted("M1"):
        assert a1_backend.adapter_enabled(model) is True
    assert a1_backend.adapter_enabled(model) is True


def test_m0_generation_inside_the_context_sees_the_disabled_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = FakePeftModel()
    backend = _backend_with(model)
    seen: list[bool] = []

    def fake_generate(*args: Any, **kwargs: Any) -> tuple[dict[str, Any], Any]:
        seen.append(a1_backend.adapter_enabled(model) is False)
        return {"token_ids": [1], "raw_output": "x", "eos": True}, None

    from scripts import a03_model_core

    monkeypatch.setattr(a03_model_core, "generate", fake_generate)
    with backend.adapted("M0"):
        backend.generate("N", {}, [1], deadline=0.0)
    assert seen == [True]
    assert backend.arm_calls == {"M0": 1, "M1": 0}


def test_generation_outside_an_arm_is_refused() -> None:
    model = FakePeftModel()
    backend = _backend_with(model)
    with pytest.raises(a1_backend.BackendError):
        backend.generate("N", {}, [1], deadline=0.0)


def test_unknown_arm_is_refused() -> None:
    backend = _backend_with(FakePeftModel())
    with pytest.raises(a1_backend.BackendError):
        with backend.adapted("M2"):
            pass


def test_explicit_base_binding_is_verified_before_use(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(a1_backend.BASE_DIR_ENV, str(tmp_path))
    calls: list[Path] = []

    def record(path: Path, files: Any) -> None:
        calls.append(path)

    from scripts import a03_model_core

    monkeypatch.setattr(a03_model_core, "verify_files", record)
    assert a1_backend.base_snapshot() == tmp_path
    assert calls == [tmp_path]


def test_explicit_adapter_binding_is_used_before_local_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    archive = tmp_path / "bundle.tar"
    archive.write_bytes(b"bundle")
    monkeypatch.setenv(a1_backend.ADAPTER_ARCHIVE_ENV, str(archive))
    assert a1_backend.adapter_bundle() == archive


def test_missing_binding_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(a1_backend.BASE_DIR_ENV, str(tmp_path / "absent"))
    with pytest.raises(a1_backend.BackendError):
        a1_backend.base_snapshot()
    monkeypatch.setenv(a1_backend.ADAPTER_ARCHIVE_ENV, str(tmp_path / "absent.tar"))
    with pytest.raises(a1_backend.BackendError):
        a1_backend.adapter_bundle()


def test_identity_records_the_interpreter_and_paths() -> None:
    # identity() must be a pure record of the bound paths; it is what the generation commits.
    value = a1_backend.identity("cuda")
    assert value["max_prompt_tokens"] == a1_backend.MAX_PROMPT_TOKENS
    assert value["interpreter"]["pinned_prefix"] == "/content/a02/inference-venv"
    assert value["interpreter"]["is_pinned"] == sys.executable.startswith(
        "/content/a02/inference-venv"
    )
    assert value["model"]["revision"] == a1_backend.REVISION


def test_cuda_execution_requires_the_pinned_interpreter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The guard must fire before any model is loaded."""

    class FakeTorch:
        class cuda:  # noqa: N801
            @staticmethod
            def mem_get_info(index: int) -> tuple[int, int]:
                return 10**12, 10**12

    monkeypatch.setitem(sys.modules, "torch", FakeTorch)
    with pytest.raises(a1_backend.BackendError, match="pinned inference interpreter"):
        a1_backend.A1Backend("cuda", tmp_path)


def test_payload_work_order_reconstructs_every_frozen_call() -> None:
    order = a1_payload.work_order(None)
    assert order["planned_conditions"] == 20
    assert order["planned_generations"] == 1332
    assert order["principal_generations"] == 384
    assert [entry["role"] for entry in order["conditions"]][:8] == ["PRINCIPAL_FACTORIAL"] * 8
    for condition in order["conditions"]:
        for item in condition["items"]:
            assert rep.request_sha256(item["request"]) == item["request_sha256"]
            assert v3.sha256(v3.canonical(item["messages"]).encode()) == item["prompt_sha256"]


def test_payload_carries_the_d6_retrospective_requests() -> None:
    order = a1_payload.work_order(None)
    names = {condition["arm"] for condition in order["conditions"]}
    assert {"D6-M0-N", "D6-M0-C1"} <= names
    retrospective = [
        condition
        for condition in order["conditions"]
        if condition["role"] == "RETROSPECTIVE_NOT_FINAL_EVIDENCE"
    ]
    assert sum(len(condition["items"]) for condition in retrospective) == 192


@needs_evidence
def test_d6_transport_matches_the_sealed_request_digests() -> None:
    order = a1_payload.work_order(None)
    sealed = a1_manifest.load_manifest()
    sealed_items = {
        item["case_id"]: item
        for condition in sealed["retrospective"]["conditions"]
        for item in condition["items"]
    }
    transported = {
        item["case_id"]: item
        for condition in order["conditions"]
        if condition["role"] == "RETROSPECTIVE_NOT_FINAL_EVIDENCE"
        for item in condition["items"]
    }
    assert set(transported) == set(sealed_items)
    for case_id, item in transported.items():
        assert item["request_sha256"] == sealed_items[case_id]["request_sha256"]
        assert item["prompt_sha256"] == sealed_items[case_id]["prompt_sha256"]


def test_payload_exposes_no_gold_or_adjudication_metadata() -> None:
    order = a1_payload.work_order(None)
    text = v3.canonical(order)
    for key in a1_payload.FORBIDDEN_KEYS:
        assert f'"{key}"' not in text
    for case in a1_cases.load_manifest()["cases"]:
        assert v3.canonical(a1_cases.gold_action(case)) not in text
    assert a1_cases.CASES_PATH.name not in text


def test_runner_reuses_one_case_across_representations(tmp_path: Path) -> None:
    """The same case id appears in R-hist and R-op with different requests.

    A work order keyed only by case id silently served the wrong request and failed the digest
    gate. Each transported item must carry its own request and messages.
    """
    order = a1_payload.work_order(None)
    by_arm = {condition["arm"]: condition for condition in order["conditions"]}
    hist = by_arm["P-M1-R-hist-C1"]["items"][0]
    op = by_arm["P-M1-R-op-C1"]["items"][0]
    assert hist["case_id"] == op["case_id"]
    assert hist["request"] != op["request"]
    assert hist["request_sha256"] != op["request_sha256"]
    for item in (hist, op):
        assert v3.sha256(v3.canonical(item["request"]).encode()) == item["request_sha256"]


def test_transported_items_drive_the_runner_without_local_cases(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A transported item must be executable with the local cohort made unreachable."""
    order = a1_payload.work_order(None)
    condition = next(c for c in order["conditions"] if c["arm"] == "P-M1-R-op-C1")
    condition = {**condition, "items": condition["items"][:2]}
    restore = a1_rehearsal.use_stub_prompts()

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a transported run must not build a local case inventory")

    monkeypatch.setattr(a1_run, "_local_cases", forbidden)
    try:
        receipt = a1_run.run_arm(
            a1_rehearsal.StubBackend(), condition, identity={}, root=tmp_path, deadline_seconds=60
        )
    finally:
        restore()
    assert receipt["committed"] == 2
    assert receipt["complete"] is True


def test_local_case_ids_are_rejected_by_the_transport_boundary() -> None:
    """The authored cohort must not be reconstructable from the transported work order."""
    order = a1_payload.work_order(None)
    text = v3.canonical(order)
    for case in a1_cases.load_manifest()["cases"]:
        # Frozen case ids do appear in the principal arms, but the authored fields never do.
        for field in ("question_text", "novel_phrasing", "subset_selection", "stated_measurement"):
            assert f'"{field}"' not in text
        assert f'"contrast":"{case["contrast"]}"' not in text


def test_payload_source_set_cannot_reach_evaluation_material() -> None:
    inventory = a1_payload.source_inventory()
    assert inventory["paths"] == len(a1_payload.SOURCE_PATHS)
    assert set(a1_payload.SOURCE_PATHS) & set(a1_payload.FORBIDDEN_SOURCE_PATHS) == set()
    for path in a1_payload.FORBIDDEN_SOURCE_PATHS:
        assert path not in a1_payload.SOURCE_PATHS
    # The worker's verifier must not import the authored cohort either.
    import ast
    import inspect

    from scripts import a1_work_order

    tree = ast.parse(inspect.getsource(a1_work_order))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert not any("a1_cases" in name or "a1_manifest" in name for name in imported)


def test_worker_imports_only_the_transport_verifier() -> None:
    import ast
    import inspect

    from scripts import a1_colab_worker

    tree = ast.parse(inspect.getsource(a1_colab_worker))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    text = inspect.getsource(a1_colab_worker)
    assert "a1_work_order" in imported or "a1_work_order" in text
    assert "a1_payload" not in imported
    assert "from scripts import a1_payload" not in text


def test_payload_forbidden_key_screen_catches_a_leak() -> None:
    with pytest.raises(a1_work_order.PayloadError):
        a1_work_order.screen({"gold": {}}, "probe")
    with pytest.raises(a1_work_order.PayloadError):
        a1_work_order.screen({"items": [{"acceptable_actions": []}]}, "probe")
    with pytest.raises(a1_work_order.PayloadError):
        a1_work_order.screen({"judgment": {"control": "EXECUTE"}}, "probe")


def test_smoke_input_is_development_only_and_outside_the_cohort() -> None:
    order = a1_payload.work_order(None)
    smoke = order["smoke"]
    assert smoke["purpose"] == "DEVELOPMENT_ONLY_EXECUTION_CHECK"
    assert len(smoke["conditions"]) == 4
    assert [row["model"] for row in smoke["conditions"]] == ["M0", "M0", "M1", "M1"]
    assert [row["decoder"] for row in smoke["conditions"]] == ["N", "C1", "N", "C1"]
    cohort = {
        rep.request_sha256(rep.request_for("R-op", case))
        for case in a1_cases.load_manifest()["cases"]
    }
    assert smoke["request_sha256"] not in cohort
    assert smoke["request_sha256"] == rep.request_sha256(smoke["request"])


def test_work_order_verification_rejects_a_tampered_request() -> None:
    order = a1_payload.work_order(None)
    a1_payload.verify_work_order(order)
    tampered = json.loads(json.dumps(order))
    tampered["conditions"][0]["items"][0]["request"]["question"] = "tampered"
    with pytest.raises(a1_payload.PayloadError):
        a1_payload.verify_work_order(tampered)


def test_work_order_verification_rejects_a_dropped_condition() -> None:
    order = a1_payload.work_order(None)
    tampered = json.loads(json.dumps(order))
    tampered["conditions"] = tampered["conditions"][:-1]
    with pytest.raises(a1_payload.PayloadError):
        a1_payload.verify_work_order(tampered)


def test_frozen_prompt_bound_covers_the_few_shot_arm() -> None:
    """The historical 1,536-token guard is smaller than the frozen D5 prompts."""
    limit = a1_run.MAX_PROMPT
    assert limit == 4096
    assert a1_backend.MAX_PROMPT_TOKENS == limit
    assert limit > 1536


def test_generator_bound_defaults_to_the_historical_limit() -> None:
    import inspect

    signature = inspect.signature(a1_chain_import().generate)
    default = signature.parameters["max_prompt_tokens"].default
    assert default == 1536


def a1_chain_import() -> Any:
    from scripts import a03_model_core

    return a03_model_core


def test_runner_never_resets_a_cumulative_deadline(tmp_path: Path) -> None:
    """A single session deadline must govern every call; no per-call reset is allowed."""
    condition = a1_manifest.load_manifest()["conditions"][0]
    restore = a1_rehearsal.use_stub_prompts()
    deadlines: list[float] = []

    class Recording(a1_rehearsal.StubBackend):
        def generate(
            self, arm: str, request: dict[str, Any], prompt: list[int], deadline: float
        ) -> Any:
            deadlines.append(deadline)
            return super().generate(arm, request, prompt, deadline)

    try:
        receipt = a1_run.run_arm(
            Recording(),
            condition,
            identity={},
            root=tmp_path,
            deadline_seconds=3600.0,
        )
    finally:
        restore()
    assert receipt["complete"] is True
    assert len(set(deadlines)) == 1, "each call received a different deadline"


def test_runner_stops_before_exhausting_the_session_budget(tmp_path: Path) -> None:
    """With no remaining budget the arm must commit nothing rather than overrun."""
    import time as _time

    condition = a1_manifest.load_manifest()["conditions"][0]
    restore = a1_rehearsal.use_stub_prompts()
    try:
        receipt = a1_run.run_arm(
            a1_rehearsal.StubBackend(),
            condition,
            identity={},
            root=tmp_path,
            deadline_seconds=0.0,
            session_deadline=_time.monotonic() + 1.0,
        )
    finally:
        restore()
    assert receipt["generated_now"] == 0
    assert receipt["stopped_early"] is True
    assert receipt["complete"] is False


def test_campaign_allocates_the_full_frozen_count() -> None:
    """The controller must plan all 1,332 generations, including the D6 retrospective calls."""
    receipt = {
        "planned_generations": a1_payload.work_order(None)["planned_generations"],
    }
    assert receipt["planned_generations"] == 1332 == 1140 + 192
    assert a1_manifest.load_manifest()["total_planned_generations"] == 1332


def test_worker_refuses_a_missing_run_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(a1_colab_worker, "WORK", tmp_path)
    monkeypatch.setattr(sys, "argv", ["a1_colab_worker.py", "campaign"])
    monkeypatch.setenv("A1_PHASE", "campaign")
    assert a1_colab_worker.main() == 1
    error = json.loads((tmp_path / "error.json").read_text())
    assert "positive A1_SECONDS budget" in error["message"]


def test_worker_entrypoint_refuses_a_missing_phase() -> None:
    import subprocess

    env = {**__import__("os").environ, "PYTHONPATH": f"{ROOT / 'src'}:{ROOT}"}
    env.pop("A1_PHASE", None)
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/a1_colab_worker.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )
    assert result.returncode != 0
    assert "phase must be given" in result.stderr


def test_harvest_refuses_divergent_chains(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import tarfile

    monkeypatch.setattr(a1_colab, "RUNS", tmp_path / "runs")
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs/arm.jsonl").write_bytes(b'{"line":1}\n')
    archive = tmp_path / "evidence.tar"
    with tarfile.open(archive, "w") as tar:
        path = tmp_path / "arm.jsonl"
        path.write_bytes(b'{"other":2}\n')
        tar.add(path, arcname="runs/arm.jsonl")
    with pytest.raises(a1_colab.ControllerError, match="diverges"):
        a1_colab.harvest(archive)


def test_defect_errors_are_distinct_from_resumable_interruptions() -> None:
    assert issubclass(a1_colab.DefectError, a1_colab.ControllerError)
    session: dict[str, Any] = {"phases": [{"returncode": 1, "stderr": "boom"}]}
    with pytest.raises(a1_colab.DefectError):
        a1_colab._require_phase(session, "bootstrap", "SETUP_COMPLETE", _client())
    assert session["defect"] == "BOOTSTRAP_PHASE_FAILED"


def test_time_slice_without_progress_is_a_defect() -> None:
    session: dict[str, Any] = {}
    with pytest.raises(a1_colab.DefectError, match="without progress"):
        a1_colab._require_progress(
            session, 10, {"phase": {"phase": "RUN_PARTIAL"}, "committed": 10}
        )
    assert session["defect"] == "RUN_PHASE_NO_PROGRESS"


def test_time_slice_with_progress_is_resumable() -> None:
    session: dict[str, Any] = {}
    a1_colab._require_progress(session, 10, {"phase": {"phase": "RUN_PARTIAL"}, "committed": 25})
    assert "defect" not in session
    assert session["progress"] == {"before": 10, "after": 25, "phase": "RUN_PARTIAL"}


def test_completed_run_is_not_a_defect() -> None:
    session: dict[str, Any] = {}
    a1_colab._require_progress(
        session, 1332, {"phase": {"phase": "RUN_COMPLETE"}, "committed": 1332}
    )
    assert "defect" not in session


def test_unrecorded_run_phase_is_a_defect() -> None:
    session: dict[str, Any] = {}
    with pytest.raises(a1_colab.DefectError, match="not a resumable interruption"):
        a1_colab._require_progress(session, 0, {"phase": {}})


def test_chain_reads_refuse_a_wrong_item_order(tmp_path: Path) -> None:
    condition = a1_manifest.load_manifest()["conditions"][0]
    restore = a1_rehearsal.use_stub_prompts()
    try:
        a1_run.run_arm(
            a1_rehearsal.StubBackend(), condition, identity={}, root=tmp_path, deadline_seconds=60
        )
    finally:
        restore()
    path = a1_chain.arm_path(condition["arm"], tmp_path)
    reordered = list(condition["items"])
    reordered[0], reordered[1] = reordered[1], reordered[0]
    with pytest.raises(a1_chain.ChainError):
        a1_chain.read_arm(path, condition["arm"], reordered)


def test_chain_counts_only_committed_lines(tmp_path: Path) -> None:
    condition = a1_manifest.load_manifest()["conditions"][0]
    restore = a1_rehearsal.use_stub_prompts()
    try:
        a1_run.run_arm(
            a1_rehearsal.StubBackend(), condition, identity={}, root=tmp_path, deadline_seconds=60
        )
    finally:
        restore()
    assert a1_chain.count_lines(tmp_path) == {condition["arm"]: 48}


def test_historical_cpu_record_is_preserved() -> None:
    path = ROOT / "reports/a1/cpu-baseline-history-v1.json"
    record = json.loads(path.read_text())
    assert record["schema"] == "DYNAMISLM_A1_CPU_BASELINE_HISTORY_V1"
    assert record["auxiliary_input"]["in_model_visible_request"] is False
    assert record["baselines"]["rule_based"]["exact"]["estimate"] == pytest.approx(
        0.5833333333333334
    )
    for value in record["baselines"]["restricted_input"].values():
        assert value["exact"]["estimate"] == pytest.approx(0.2916666666666667)


def test_allocation_ledger_records_every_performed_allocation() -> None:
    """The control record must carry a mechanical ledger, not a prose summary."""
    path = ROOT / "experiments/a1/.campaign/campaign-2-control.json"
    if not path.is_file():
        pytest.skip("no continuation control record on this machine")
    control = json.loads(path.read_text())
    ledger = control.get("allocation_ledger")
    assert ledger is not None, "the continuation control record has no allocation ledger"
    assert ledger["schema"] == "DYNAMISLM_A1_ALLOCATION_LEDGER_V1"
    rows = ledger["allocations"]
    assert ledger["totals"]["allocations"] == len(rows)
    assert ledger["totals"]["seconds"] == pytest.approx(
        round(sum(row["elapsed_seconds"] for row in rows), 1)
    )
    assert ledger["totals"]["modeled_cu"] == pytest.approx(
        round(sum(row["modeled_cu"] for row in rows), 4)
    )
    assert ledger["totals"]["generations"] == 0
    # The breach is recorded arithmetically against the authorized session count.
    authorized = ledger["authorization"]["additional_sessions"]
    assert ledger["breach"]["sessions_over_authorization"] == len(rows) - authorized
    # Every attempt-3 row must match the session it derives from.
    sessions = {session["index"]: session for session in control["sessions"]}
    for row in rows:
        if row["id"].startswith("attempt-3/"):
            session = sessions[row["session"]]
            assert row["elapsed_seconds"] == session["elapsed_seconds"]
            assert row["modeled_cu"] == (session.get("modeled_cu") or 0.0)
            assert row["endpoint_bound"] == bool(session.get("target_endpoint"))


def test_report_does_not_impute_an_unexecuted_arm() -> None:
    """No arm may carry a fabricated estimate while no generation exists."""
    report = (ROOT / "docs/research/A1-REPORT.md").read_text(encoding="utf-8")
    analysis = json.loads((ROOT / "reports/a1/analysis-v1.json").read_text())
    assert analysis["completed_generations"] == 0
    assert analysis["completed_arms"] == 0
    assert analysis["planned_generations"] == 1332
    for name in ("H1", "H2", "H5"):
        assert analysis["hypotheses"][name]["status"] == "NOT_EVALUABLE"
    assert "not estimable" in report
    assert "NOT_EVALUABLE" in report


def test_report_discloses_the_session_breach() -> None:
    """The overrun must be stated in the published report, not only in the control record."""
    report = (ROOT / "docs/research/A1-REPORT.md").read_text(encoding="utf-8")
    assert "Envelope breach disclosure" in report
    assert "exceeded by 2" in report
