"""Three-path numerical forensics of V3 option scoring on real SmolLM3 code (RES-541).

Every model here is an actual ``SmolLM3ForCausalLM`` (tiny, randomly initialized) with the pinned
architecture pattern: NoPE on every fourth layer, grouped-query attention, rope_theta 5e6 and tied
embeddings. Nothing is mocked. FP32 runs establish structural correctness (token alignment,
cache cropping, rollback, positions, masks) independently of precision; negative controls show
that the diagnostic detects each known class of cache defect; FP16 runs reproduce the class of
failure seen in sessions 003 and 004 without any GPU. Requires the decoder-check overlay.
"""

from __future__ import annotations

import json
import random
from collections.abc import Iterator
from copy import deepcopy
from typing import Any

import pytest

torch = pytest.importorskip("torch")
transformers = pytest.importorskip("transformers")

from scripts import a02_v3_numerics as numerics  # noqa: E402

TOLERANCE = numerics.QUALIFICATION_TOLERANCE_NATS


@pytest.fixture(autouse=True, scope="module")
def _bounded_threads() -> Iterator[None]:
    # Oversubscribed CPU threads make tiny forwards 20x slower without changing results.
    previous = torch.get_num_threads()
    torch.set_num_threads(min(4, previous))
    yield
    torch.set_num_threads(previous)


def _model(hidden: int, *, vocab: int = 2048, layers: int = 8, seed: int = 541) -> Any:
    torch.manual_seed(seed)
    config = transformers.SmolLM3Config(
        vocab_size=vocab,
        hidden_size=hidden,
        intermediate_size=2 * hidden,
        num_hidden_layers=layers,
        num_attention_heads=8,
        num_key_value_heads=2,
        max_position_embeddings=65536,
        rope_theta=5e6,
        tie_word_embeddings=True,
        pad_token_id=0,
        bos_token_id=None,
        eos_token_id=None,
    )
    assert config.no_rope_layers == [1, 1, 1, 0] * (layers // 4)
    lm = transformers.SmolLM3ForCausalLM(config).to(torch.float32)
    lm.eval()
    return lm


def _realistic_logits(lm: Any, scale: float) -> Any:
    """Scale the tied projection so logits reach the magnitudes of a trained 3B model."""
    with torch.no_grad():
        lm.lm_head.weight.mul_(scale)
    return lm


def _schedule(vocab: int, prompt: int, seed: int) -> list[tuple[list[int], int]]:
    """A constrained-walk-shaped call schedule: a long prompt, a growing action prefix, several
    options per choice, shared-prefix back-off into cached tokens, and divergent rollbacks."""
    rng = random.Random(seed)
    prefix = [rng.randrange(1, vocab) for _ in range(prompt)]
    calls = []
    for _ in range(6):
        options = [[rng.randrange(1, vocab) for _ in range(rng.randint(1, 7))] for _ in range(4)]
        backoff = rng.randint(0, 2)
        start = len(prefix) - backoff
        for option in options:
            calls.append((prefix + option, start))
        prefix = prefix + options[rng.randrange(len(options))] + [rng.randrange(1, vocab)]
    # A divergent candidate that shares only a short prefix, then a return to the long one.
    calls.append((prefix[:40] + [rng.randrange(1, vocab) for _ in range(30)], 50))
    calls.append(([*prefix, 7, 8, 9], len(prefix)))
    return calls


@pytest.fixture(scope="module")
def fp32_model() -> Any:
    return _model(64)


# --------------------------------------------------------------------------- structural (FP32)


@pytest.mark.parametrize("prompt", [24, 600, 1500])
def test_fp32_three_paths_agree_across_prefix_lengths_and_rollbacks(
    fp32_model: Any, prompt: int
) -> None:
    report = numerics.replay(fp32_model, _schedule(2048, prompt, seed=prompt))
    for pair in ("A_vs_B", "B_vs_C", "A_vs_C"):
        assert report["summary"][pair]["max_abs_score_difference"] < 5e-5, pair
        assert report["summary"][pair]["candidates_above_tolerance"] == 0
    calls = [c["c_call"] for c in report["candidates"]]
    for candidate, call in zip(report["candidates"], calls, strict=True):
        start, end = candidate["scored_suffix"]
        assert call["positions_contiguous_from_keep"]
        assert call["cache_position_first_last"] == [call["keep"], end - 2]
        assert call["cache_length_after"] == end - 1 == call["keep"] + call["fed_tokens"]
        assert call["scored_tokens"] == end - start == len(candidate["target_token_ids"])
        assert call["keep"] < start
        if call["keep"] and call["fed_tokens"] > 1:
            # Cached multi-token tail: explicit causal mask over every cached key.
            assert call["attention_mask"]["shape"] == [1, 1, call["fed_tokens"], end - 1]
    # The schedule exercises real cache rollback into already-cached tokens and a deep rollback.
    assert any(c["cache_length_before_crop"] > c["keep"] > 0 for c in calls)
    assert min(c["keep"] for c in calls[1:]) <= 40


def test_fp32_long_and_short_scored_suffixes(fp32_model: Any) -> None:
    rng = random.Random(3)
    ids = [rng.randrange(1, 2048) for _ in range(1800)]
    calls = [(ids, 1799), (ids, 1700), (ids[:1500], 1000), (ids, 2)]
    report = numerics.replay(fp32_model, calls)
    assert [len(c["target_token_ids"]) for c in report["candidates"]] == [1, 100, 500, 1798]
    assert report["summary"]["A_vs_C"]["max_abs_score_difference"] < 5e-4
    assert report["summary"]["A_vs_C"]["max_abs_token_difference"] < 5e-5


def test_diagnostic_is_repeatable_bit_for_bit(fp32_model: Any) -> None:
    calls = _schedule(2048, 300, seed=11)
    one = numerics.replay(fp32_model, calls)
    two = numerics.replay(fp32_model, calls)
    assert json.dumps(one, sort_keys=True) == json.dumps(two, sort_keys=True)


def test_fp32_layer_divergence_and_head_are_negligible(fp32_model: Any) -> None:
    rng = random.Random(5)
    ids = [rng.randrange(1, 2048) for _ in range(700)]
    layers = numerics.layer_divergence(fp32_model, ids, 690, 650)
    assert len(layers["layers"]) == 9  # embeddings plus eight decoder layers (last normed)
    assert layers["layers"][0]["max_abs_difference"] == 0.0  # embeddings never differ
    assert max(r["max_abs_difference"] for r in layers["layers"]) < 1e-4
    head = numerics.head_decomposition(fp32_model, ids, 690)
    assert head["logit_dtype"] == "torch.float32"
    assert head["projection_rounding_max_abs_token_logprob"] < 1e-5


# --------------------------------------------------------------------------- negative controls


class _RotatedTargets(numerics.RecordingBackend):
    """Known defect class: scored targets misaligned by one position."""

    def logprobs(self, keep: int, new_ids: Any, targets: Any) -> list[float]:
        return super().logprobs(keep, new_ids, [*targets[1:], targets[0]])


def _faulty_crop(monkeypatch: Any, shift: int | None) -> None:
    """Known defect classes: stale KV (no crop) or an off-by-one rollback (crop one too far)."""
    cache = transformers.DynamicCache
    original = cache.crop

    def crop(self: Any, max_length: int) -> None:
        if self.get_seq_length() <= max_length or shift is None:
            return None
        original(self, max_length - shift)

    monkeypatch.setattr(cache, "crop", crop)


@pytest.mark.parametrize("defect", ["stale_cache", "off_by_one_crop", "misaligned_targets"])
def test_diagnostic_localizes_injected_cache_defects(
    fp32_model: Any, monkeypatch: Any, defect: str
) -> None:
    calls = _schedule(2048, 200, seed=17)
    backend = None
    if defect == "misaligned_targets":
        backend = _RotatedTargets(fp32_model)
    else:
        _faulty_crop(monkeypatch, None if defect == "stale_cache" else 1)
    try:
        report = numerics.replay(fp32_model, calls, backend=backend)
    except RuntimeError as exc:
        # A stale cache can make the tail's key length inconsistent with its mask.
        assert defect == "stale_cache"
        assert "size" in str(exc).lower() and "tensor" in str(exc).lower()
        return
    summary = report["summary"]
    assert summary["A_vs_C"]["max_abs_score_difference"] > 10 * TOLERANCE
    assert summary["B_vs_C"]["max_abs_score_difference"] > 10 * TOLERANCE
    # A and B never reuse a cropped cache, so they stay in agreement: the defect is in C.
    assert summary["A_vs_B"]["max_abs_score_difference"] < 5e-5
    bad = [
        c for c in report["candidates"] if c["B_vs_C"]["first_token_above_tolerance"] is not None
    ]
    assert bad and all(c["A_vs_B"]["first_token_above_tolerance"] is None for c in bad)


# --------------------------------------------------------------------------- precision (FP16)


@pytest.fixture(scope="module")
def realistic_pair() -> tuple[Any, Any]:
    fp32 = _realistic_logits(_model(256, layers=8), 6.0)
    return fp32, deepcopy(fp32).to(torch.float16)


@pytest.fixture(scope="module")
def realistic_reports(realistic_pair: tuple[Any, Any]) -> tuple[Any, Any]:
    calls = _schedule(2048, 1400, seed=5)
    reports = tuple(numerics.replay(model, calls) for model in realistic_pair)
    print(
        json.dumps(
            {
                name: report["summary"]
                for name, report in zip(("FP32", "FP16"), reports, strict=True)
            },
            sort_keys=True,
        )
    )
    return reports


def test_fp16_reproduces_session_failure_class_while_fp32_passes(
    realistic_pair: tuple[Any, Any],
    realistic_reports: tuple[Any, Any],
) -> None:
    """Same weights, same frozen calls: FP32 agrees far inside 1e-3 nat; FP16 does not."""
    fp32, fp16 = realistic_pair
    calls = _schedule(2048, 1400, seed=5)
    wide = realistic_reports[0]["summary"]
    half = realistic_reports[1]
    head = numerics.head_decomposition(fp32, calls[0][0], calls[0][1])
    assert 15 < head["max_abs_logit"] < 60  # trained-model logit magnitude regime
    assert wide["A_vs_C"]["max_abs_score_difference"] < 1e-4
    assert half["summary"]["A_vs_C"]["max_abs_score_difference"] > TOLERANCE
    # The FP16 discrepancy is an execution-shape effect, present with or without cache reuse:
    # path B (fresh cache, no history) already differs from A by the same order.
    assert half["summary"]["A_vs_B"]["max_abs_score_difference"] > TOLERANCE


def test_fp16_first_divergence_is_inside_the_transformer_body(
    realistic_pair: tuple[Any, Any],
    realistic_reports: tuple[Any, Any],
) -> None:
    _, fp16 = realistic_pair
    report = realistic_reports[1]
    worst = max(report["candidates"], key=lambda c: c["A_vs_B"]["abs_sum_difference"])
    assert worst["A_vs_B"]["abs_sum_difference"] > TOLERANCE
    start, _ = worst["scored_suffix"]
    ids = [*report_ids(report, worst)]
    layers = numerics.layer_divergence(fp16, ids, start, worst["c_call"]["keep"])
    assert layers["layers"][0]["max_abs_difference"] == 0.0  # identical embeddings
    first = layers["first_divergent_hidden_state"]
    assert first is not None and first >= 1  # first divergence is inside a decoder layer
    assert layers["layers"][-1]["max_abs_difference"] > 0.0
    head = numerics.head_decomposition(fp16, ids, start)
    assert head["logit_dtype"] == "torch.float16"
    # FP16 logits are quantized before log-softmax: rounding alone moves single tokens.
    assert head["projection_rounding_max_abs_token_logprob"] > 1e-4


def report_ids(report: dict[str, Any], candidate: dict[str, Any]) -> list[int]:
    calls = _schedule(2048, 1400, seed=5)
    ids, start = calls[candidate["index"]]
    assert ids[start:] == candidate["target_token_ids"]
    return list(ids)


# --------------------------------------------------------------------------- argument guards


@pytest.mark.parametrize(("start", "keep"), [(5, 5), (5, 6), (10, 3), (0, 0)])
def test_fresh_cache_path_rejects_invalid_boundaries(
    fp32_model: Any, start: int, keep: int
) -> None:
    with pytest.raises(ValueError, match="fresh-cache"):
        numerics.fresh_cache_token_logprobs(fp32_model, list(range(1, 10)), start, keep)


def test_layer_divergence_requires_a_cached_prefix(fp32_model: Any) -> None:
    with pytest.raises(ValueError, match="layer divergence"):
        numerics.layer_divergence(fp32_model, list(range(1, 10)), 5, 0)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_comparison_fails_closed_on_nonfinite_scores(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        numerics._compare([value], [value], TOLERANCE)
