"""Original SYNTHETIC development-only SFT tests; no protected cases or athlete records."""

import importlib
import json
from dataclasses import asdict, fields, replace
from pathlib import Path
from typing import Any

import pytest

from dynamislm.analysis import AnalysisClass
from dynamislm.external_load.registry import EXTERNAL_LOAD_MINUTE
from dynamislm.longitudinal.statistics import (
    StatisticalResult,
    StatisticalSupport,
    calculate_absolute_change,
)
from dynamislm.serialization import canonical_bytes, canonical_hash, from_canonical_json
from dynamislm.training_data import scientific_sft as s
from dynamislm.training_data import sft_cpu as cpu
from dynamislm.training_data.processing import TRANSFORM, sha256
from dynamislm.training_data.scientific_sft import Category, construct_example
from test_res416_admission import fixture, install_test_authority
from test_res417_processing import exclusions


@pytest.fixture(scope="module")
def dataset() -> s.DevelopmentSet:
    return s.generate_development_set()


def category(dataset: s.DevelopmentSet, name: Category) -> s.ScientificExample:
    return next(e for e in dataset.examples if e.task.category == name)


def rehash(example: s.ScientificExample) -> s.ScientificExample:
    payload = tuple(getattr(example, f.name) for f in fields(example) if f.name != "example_sha256")
    return replace(example, example_sha256=canonical_hash(payload))


def test_generation_replay_and_roundtrip(dataset: s.DevelopmentSet) -> None:
    assert len(dataset.examples) == 39
    assert len({e.task.category for e in dataset.examples}) == 13
    assert sum(not e.response.refusal_codes for e in dataset.examples) == 15
    assert sum(e.call is not None for e in dataset.examples) == 30
    assert canonical_bytes(dataset) == canonical_bytes(s.generate_development_set())
    loaded = cpu.load_development_bytes(canonical_bytes(dataset))
    assert canonical_bytes(loaded) == canonical_bytes(dataset)
    assert canonical_bytes(dataset) != canonical_bytes(s.generate_development_set(403))
    assert len(cpu.cpu_batches(loaded)) == 10


def test_actual_registered_scientific_response(dataset: s.DevelopmentSet) -> None:
    example = category(dataset, Category.LONGITUDINAL)
    assert example.call is not None and example.call.support is not None
    result = calculate_absolute_change(example.call.support)
    assert isinstance(result, StatisticalResult)
    assert result.estimates[0].value == example.response.value
    assert result.estimates[0].unit == example.response.unit
    assert from_canonical_json(example.response.engine_response, StatisticalResult) == result
    assert example.response.analysis_authorization is not None
    assert example.call.operation_id == result.result_kind.identifier.stable_id


@pytest.mark.parametrize(
    "case",
    [
        "number",
        "unit",
        "operation",
        "missing_operation",
        "version",
        "arguments",
        "tool_output",
        "result_digest",
        "input_digest",
        "registry",
        "implementation",
        "provenance",
        "rights",
        "causal_class",
        "objective",
        "question",
        "partition",
        "context",
        "tool_role",
        "tool_link",
        "causal_answer",
        "missing_final",
        "identity",
    ],
)
def test_rehashed_scientific_forgeries_rejected(dataset: s.DevelopmentSet, case: str) -> None:
    example = category(dataset, Category.LONGITUDINAL)
    assert example.call is not None
    call = example.call
    if case == "number":
        example = replace(example, response=replace(example.response, value=999.0))
    elif case == "unit":
        example = replace(example, response=replace(example.response, unit=EXTERNAL_LOAD_MINUTE))
    elif case in {"operation", "missing_operation", "version"}:
        changes: dict[str, Any] = {"operation_id": "dynamislm:registered-operation:invented@1.0.0"}
        if case == "missing_operation":
            changes = {"operation_id": None}
        if case == "version":
            changes = {"method_version": "99"}
        example = replace(example, call=replace(call, **changes))
    elif case == "arguments":
        example = replace(example, call=replace(call, support=None))
    elif case == "tool_output":
        example = replace(example, response=replace(example.response, engine_response="forged"))
    elif case in {"result_digest", "input_digest", "registry", "implementation"}:
        field = {
            "result_digest": "result_sha256",
            "input_digest": "input_sha256",
            "registry": "registry_sha256",
            "implementation": "implementation_sha256",
        }[case]
        invalid_fields: dict[str, Any] = {field: "sha256:" + "0" * 64}
        example = replace(example, **invalid_fields)
    elif case in {
        "provenance",
        "rights",
        "causal_class",
        "objective",
        "question",
        "partition",
        "context",
        "identity",
    }:
        task_changes: dict[str, dict[str, Any]] = {
            "provenance": {"source_provenance": None},
            "rights": {"rights": "TRAINING_AUTHORIZED"},
            "causal_class": {"requested_analysis_class": AnalysisClass.MIXED_EFFECTS_ANALYSIS},
            "objective": {"objective": "Infer causation"},
            "question": {"question": "Cause injury risk?"},
            "partition": {"partition": "PSE_HIDDEN_FINAL"},
            "context": {"population": "youth women"},
            "identity": {"measurement_identity": "generic jump power"},
        }
        example = replace(example, task=replace(example.task, **task_changes[case]))
    else:
        messages = json.loads(example.messages_json)
        if case == "tool_role":
            messages[2]["role"] = "assistant"
        elif case == "tool_link":
            messages[2]["tool_call_id"] = "different"
        elif case == "causal_answer":
            messages[-1]["content"] = "Training caused improvement; athlete is ready for selection."
        elif case == "missing_final":
            messages.pop()
        example = replace(example, messages_json=json.dumps(messages))
    with pytest.raises(ValueError, match="failed replay"):
        s.validate_example(rehash(example))


@pytest.mark.parametrize(
    "name",
    [
        Category.UNIT_MISMATCH,
        Category.CROSS_SOURCE,
        Category.MISSING_DATA,
        Category.UNKNOWN_PROVENANCE,
        Category.RELIABILITY,
        Category.CAUSAL,
        Category.CONTRADICTORY,
        Category.NO_DOWNGRADE,
    ],
)
def test_refusals_and_supported_descriptive_counterexamples(
    dataset: s.DevelopmentSet, name: Category
) -> None:
    refused = category(dataset, name)
    assert refused.response.refusal_codes and refused.response.value is None
    s.validate_example(refused)
    supported = category(
        dataset,
        Category.DESCRIPTIVE_DISPERSION if name == Category.RELIABILITY else Category.LONGITUDINAL,
    )
    assert not supported.response.refusal_codes
    s.validate_example(supported)
    if name in {Category.CAUSAL, Category.CONTRADICTORY, Category.UNKNOWN_PROVENANCE}:
        assert refused.call is None
    if name == Category.NO_DOWNGRADE:
        assert refused.task.requested_analysis_class == AnalysisClass.WITHIN_ATHLETE_ASSOCIATION
        assert refused.call is not None and refused.call.operation_id is None


def test_duplicate_conflicting_and_unordered_lineage(dataset: s.DevelopmentSet) -> None:
    variants = [
        replace(dataset, examples=(*dataset.examples[:-1], dataset.examples[0])),
        replace(dataset, examples=tuple(reversed(dataset.examples))),
        replace(dataset, seed=403),
        replace(dataset, qualification_scope="CORPUS_QUALIFIED"),
    ]
    for invalid in variants:
        with pytest.raises(ValueError):
            s.validate_development_set(invalid)


def test_external_writer_replay_tamper_and_corpus_gate(
    dataset: s.DevelopmentSet, tmp_path: Path
) -> None:
    first = cpu.write_development_artifacts(dataset, tmp_path)
    assert first == cpu.write_development_artifacts(dataset, tmp_path)
    assert first["examples"] == 39 and first["cpu_batches"] == 10
    assert first["scientific_replay"] == "PASS"
    assert first["tokenizer"]["status"] == "PENDING"
    root = tmp_path / first["receipt_sha256"].removeprefix("sha256:")
    raw = (root / "examples.json").read_bytes()
    receipt = json.loads((root / "receipt.json").read_bytes())["payload"]
    assert sha256(raw) == first["examples_sha256"]
    for candidate in (first, receipt):
        candidate["corpus_qualified"] = True
        candidate["training_authorized"] = True
        candidate["qualification_scope"] = "CORPUS_QUALIFIED"
        candidate["receipt_sha256"] = canonical_hash(candidate)
        with pytest.raises(PermissionError, match="CORPUS_ASSEMBLY_REQUIRED"):
            cpu.load_training_corpus(json.loads(json.dumps(candidate)), raw)
    (root / "examples.json").write_bytes(raw + b" ")
    with pytest.raises(ValueError, match="artifact changed"):
        cpu.write_development_artifacts(dataset, tmp_path)
    with pytest.raises(ValueError):
        cpu.write_development_artifacts(dataset, Path.cwd() / "artifacts")


def provision_example(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    example: s.ScientificExample,
    *,
    revoked: bool = False,
    expired: bool = False,
) -> bytes:
    request, _ = cpu.training_request(example)
    root = tmp_path / "trust"
    root.mkdir()
    changes: dict[str, Any] = {
        "source": asdict(request.source),
        "synthetic": False,
        "transformations": [TRANSFORM],
    }
    if expired:
        changes["expires"] = "2026-01-02T00:00:00+00:00"
    _, grant = fixture(root, changes=changes, revoked=revoked)
    install_test_authority(root, monkeypatch)
    return grant


def test_test_provisioned_admission_processing_and_denied_corpus(
    dataset: s.DevelopmentSet, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    example = category(dataset, Category.UNIT_CONVERSION)
    with pytest.raises(PermissionError):
        cpu.process_training_example(
            example, b"{}", exclusion_bundle=None, output_root=tmp_path / "deny"
        )
    grant = provision_example(tmp_path, monkeypatch, example)
    result = cpu.process_training_example(
        example, grant, exclusion_bundle=exclusions(monkeypatch), output_root=tmp_path / "out"
    )
    assert result["status"] == "CLEAN"
    assert result["qualification_scope"] == "BATCH_LOCAL_ONLY"
    with pytest.raises(PermissionError):
        cpu.load_training_corpus(result, b"synthetic")


@pytest.mark.parametrize(
    "case",
    ["revoked", "expired", "forged", "unrecognized", "changed", "protected", "missing_exclusions"],
)
def test_training_boundary_denials(
    dataset: s.DevelopmentSet, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    example = category(dataset, Category.UNIT_CONVERSION)
    grant = provision_example(
        tmp_path, monkeypatch, example, revoked=case == "revoked", expired=case == "expired"
    )
    if case == "forged":
        grant += b" "
    if case == "unrecognized":
        grant = b"{}"
    bundle: bytes | None = exclusions(
        monkeypatch, cpu.training_request(example)[1] if case == "protected" else None
    )
    if case == "missing_exclusions":
        bundle = None
    if case == "changed":
        example = replace(example, task=replace(example.task, values=(999.0,)))
    if case in {"protected", "missing_exclusions"}:
        result = cpu.process_training_example(
            example, grant, exclusion_bundle=bundle, output_root=tmp_path / "out"
        )
        assert result["status"] == ("CONTAMINATED" if case == "protected" else "UNQUALIFIED")
        assert not list((tmp_path / "out").rglob("shard.json"))
    else:
        with pytest.raises((ValueError, PermissionError)):
            cpu.process_training_example(
                example, grant, exclusion_bundle=bundle, output_root=tmp_path / "out"
            )


def test_offline_tokenizer_no_resource_bypass(
    dataset: s.DevelopmentSet, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ValueError, match="resource set"):
        cpu.offline_tokenizer_smoke(dataset, tmp_path)
    for filename in cpu.TOKENIZER_PINS:
        (tmp_path / filename).write_bytes(b"forged")
    with pytest.raises(ValueError, match="unrecognized"):
        cpu.offline_tokenizer_smoke(dataset, tmp_path)
    for filename in cpu.TOKENIZER_PINS:
        if filename != "tokenizer.json":
            (tmp_path / filename).unlink()
    monkeypatch.setattr(
        cpu, "TOKENIZER_PINS", {"tokenizer.json": sha256(b"forged").removeprefix("sha256:")}
    )

    def unavailable(name: str) -> Any:
        raise ImportError("synthetic unavailable runtime")

    monkeypatch.setattr(importlib, "import_module", unavailable)
    with pytest.raises(ValueError, match="runtime unavailable"):
        cpu.offline_tokenizer_smoke(dataset, tmp_path)


def test_cli_development_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["sft_cpu", "--seed", "402", "--output-root", str(tmp_path)])
    cpu.main()
    result = json.loads(capsys.readouterr().out)
    assert result["examples"] == 39 and not result["training_authorized"]
    input_path = tmp_path / result["receipt_sha256"].removeprefix("sha256:") / "examples.json"
    monkeypatch.setattr(
        "sys.argv",
        ["sft_cpu", "--seed", "402", "--input", str(input_path), "--output-root", str(tmp_path)],
    )
    cpu.main()
    assert json.loads(capsys.readouterr().out) == result


def test_missing_data_uses_engine_refusal() -> None:
    example = construct_example(402, tuple(Category).index(Category.MISSING_DATA))
    assert example.response.refusal_codes
    assert example.response.value is None


def test_operation_qualification_precedes_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    real = calculate_absolute_change

    def counted(support: StatisticalSupport) -> Any:
        nonlocal calls
        calls += 1
        return real(support)

    def denied(key: str, function: object) -> str:
        raise ValueError("unqualified operation adapter")

    monkeypatch.setattr(s, "calculate_absolute_change", counted)
    monkeypatch.setattr(s, "_qualified", denied)
    with pytest.raises(ValueError, match="unqualified"):
        s.construct_example(402, tuple(Category).index(Category.LONGITUDINAL))
    assert calls == 0


def test_offline_template_adapter_with_isolated_fixture(
    dataset: s.DevelopmentSet, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    pins = {"tokenizer.json": sha256(b"SYNTHETIC fixture").removeprefix("sha256:")}
    (tmp_path / "tokenizer.json").write_bytes(b"SYNTHETIC fixture")
    monkeypatch.setattr(cpu, "TOKENIZER_PINS", pins)
    calls = 0

    class FixtureTokenizer:
        def apply_chat_template(self, messages: list[dict[str, Any]], **kwargs: Any) -> list[int]:
            nonlocal calls
            calls += 1
            assert kwargs == {
                "tokenize": True,
                "add_generation_prompt": False,
                "enable_thinking": False,
            }
            assert messages[0]["role"] == "user" and messages[-1]["role"] == "assistant"
            return [1, 2, 3]

    def from_pretrained(path: str, **kwargs: Any) -> FixtureTokenizer:
        assert path == str(tmp_path)
        assert kwargs == {"local_files_only": True, "trust_remote_code": False}
        return FixtureTokenizer()

    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name: SimpleNamespace(
            AutoTokenizer=SimpleNamespace(from_pretrained=from_pretrained)
        ),
    )
    summary = cpu.offline_tokenizer_smoke(dataset, tmp_path)
    assert calls == 39 and summary["status"] == "OFFLINE_TOKENIZER_ONLY"
    assert not summary["model_weights_loaded"]
    (tmp_path / "added_tokens.json").write_text("{}")
    with pytest.raises(ValueError, match="resource set"):
        cpu.offline_tokenizer_smoke(dataset, tmp_path)


def test_runtime_contract_rejects_untyped_enum() -> None:
    example = s.construct_example(402, 0)
    attack: dict[str, Any] = {"category": example.task.category.value}
    forged = replace(example, task=replace(example.task, **attack))
    with pytest.raises(ValueError, match="typed"):
        s.validate_example(forged)


def test_prompt_units_match_each_engine_input() -> None:
    example = s.construct_example(402, tuple(Category).index(Category.UNIT_MISMATCH))
    assert example.call is not None and example.call.support is not None
    units = tuple(entry.observation.result.unit for entry in example.call.support.included_entries)
    assert getattr(example.task, "measurement_units", ()) == units


def test_constructor_does_not_add_kernel_operations() -> None:
    import dynamislm
    from dynamislm.qualification import build_registered_operation_inventory

    inventory = build_registered_operation_inventory()
    assert len(inventory) == 100
    assert not hasattr(dynamislm, "construct_example")
    assert not hasattr(dynamislm, "generate_development_set")
    assert not hasattr(dynamislm, "calculate_metric")
    assert all(not entry.operation_id.startswith("synthetic-res402:") for entry in inventory)
