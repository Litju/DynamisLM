"""Real tiny SmolLM3 + PEFT optimizer checks; never evidence of 3B task accuracy (RES-541)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

torch = pytest.importorskip("torch")
transformers = pytest.importorskip("transformers")
pytest.importorskip("peft")

from scripts import a02_v3_training as training  # noqa: E402


@pytest.fixture(autouse=True, scope="module")
def bounded_threads() -> Iterator[None]:
    previous = torch.get_num_threads()
    torch.set_num_threads(min(previous, 2))
    yield
    torch.set_num_threads(previous)


@pytest.fixture
def setup_training() -> tuple[Any, Any, Any]:
    torch.manual_seed(11)
    config = transformers.SmolLM3Config(
        vocab_size=128,
        hidden_size=32,
        intermediate_size=64,
        num_hidden_layers=4,
        num_attention_heads=4,
        num_key_value_heads=2,
        pad_token_id=0,
        bos_token_id=None,
        eos_token_id=2,
    )
    base = transformers.SmolLM3ForCausalLM(config).float()
    spec = deepcopy(training.specification())
    # Clearly synthetic optimizer fixture: run three small updates, no production profile mutation.
    spec["adaptation"]["optimizer"].update(
        epochs=1, batch_tokens=16, learning_rate=0.02, warmup_ratio=0
    )
    spec["checkpoint_interval_steps"] = 1
    data = [
        training.TokenExample([1, 3, 5, 7, 9, 11, 13, 15, 17, 19, 2], 8, f"SYNTHETIC:{i}")
        for i in range(3)
    ]
    return base, spec, data


def test_target_only_loss_matches_full_next_token_reference(setup_training: Any) -> None:
    base, spec, data = setup_training
    model = training.attach(base, spec).eval()
    example = data[0]
    actual = training.target_loss(model, example)
    logits = model(torch.tensor([example.ids[:-1]]), use_cache=False).logits[:, example.start - 1 :]
    expected = torch.nn.functional.cross_entropy(
        logits.reshape(-1, 128), torch.tensor(example.ids[example.start :]), reduction="sum"
    )
    assert float(actual.detach()) == pytest.approx(float(expected.detach()), abs=1e-5)
    for boundary in (0, len(example.ids)):
        with pytest.raises(ValueError, match="boundary"):
            training.target_loss(model, training.TokenExample(example.ids, boundary, example.id))


def test_training_changes_real_adapter_weights_and_preserves_base(
    setup_training: Any, tmp_path: Path
) -> None:
    base, spec, data = setup_training
    original_base = deepcopy(base)
    model = training.attach(base, spec)
    frozen = {n: p.detach().clone() for n, p in model.named_parameters() if not p.requires_grad}
    before = training.adapter_fingerprint(model)
    events: list[dict[str, Any]] = []
    report = training.fit(
        model,
        data,
        spec,
        tmp_path,
        {"synthetic_source": "one"},
        deadline=float("inf"),
        emit=events.append,
    )
    assert report["completed"] and report["next_step"] == report["total_steps"] == 3
    assert report["adapter_fingerprint"] != before
    assert report["target_tokens"] == 9
    assert len(events) == 3 and all(e["loss_per_target_token"] > 0 for e in events)
    params = dict(model.named_parameters())
    assert all(
        torch.equal(params[n], original) and params[n].grad is None
        for n, original in frozen.items()
    )
    recovered = tmp_path / "recovered"
    training.unpack(tmp_path / "checkpoint.tar", recovered)
    loaded = training.attach(original_base, spec, recovered)
    assert training.adapter_fingerprint(loaded) == report["adapter_fingerprint"]


def test_optimizer_rng_resume_matches_uninterrupted_training(
    setup_training: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base, spec, data = setup_training
    torch.manual_seed(88)
    full = training.attach(deepcopy(base), spec)
    completed = training.fit(
        full,
        data,
        spec,
        tmp_path / "full",
        {"synthetic_source": "resume"},
        deadline=float("inf"),
        emit=lambda value: None,
    )
    torch.manual_seed(88)
    partial = training.attach(deepcopy(base), spec)
    clock = [0.0]
    monkeypatch.setattr(training, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    def elapsed(value: dict[str, Any]) -> None:
        clock[0] += 100

    paused = training.fit(
        partial,
        data,
        spec,
        tmp_path / "partial",
        {"synthetic_source": "resume"},
        deadline=300,
        emit=elapsed,
    )
    assert not paused["completed"] and paused["next_step"] == 2
    recovered = tmp_path / "restore"
    training.unpack(tmp_path / "partial/checkpoint.tar", recovered)
    resumed = training.attach(deepcopy(base), spec, recovered)
    result = training.fit(
        resumed,
        data,
        spec,
        tmp_path / "resumed",
        {"synthetic_source": "resume"},
        deadline=float("inf"),
        emit=lambda value: None,
        resumed=recovered,
    )
    assert result["completed"]
    assert result["adapter_fingerprint"] == completed["adapter_fingerprint"]
    assert result["loss_sum"] == completed["loss_sum"]
    meta_path = recovered / "metadata.json"
    meta = json.loads(meta_path.read_bytes())
    meta["identity"] = {"synthetic_source": "forged"}
    meta_path.write_text(json.dumps(meta))
    with pytest.raises(ValueError, match="identity differs"):
        training.fit(
            resumed,
            data,
            spec,
            tmp_path / "invalid",
            {"synthetic_source": "resume"},
            deadline=float("inf"),
            emit=lambda value: None,
            resumed=recovered,
        )


def test_batches_preserve_examples_and_reject_oversized_input(setup_training: Any) -> None:
    _, spec, data = setup_training
    groups = training.batches(data, spec)
    assert sorted(i for group in groups for i in group) == list(range(len(data)))
    assert all(sum(len(data[i].ids) - 1 for i in group) <= 16 for group in groups)
    with pytest.raises(ValueError, match="oversized"):
        training.batches([training.TokenExample(list(range(40)), 20, "SYNTHETIC")], spec)
