from __future__ import annotations

from typing import Any

import pytest
from scripts import a02_v3_contract as v3
from scripts import a02_v3_preflight as preflight


class _CharTokenizer:
    def apply_chat_template(self, messages: Any, *, tokenize: bool, **_: Any) -> Any:
        text = "".join(f"<{m['role']}>{m['content']}" for m in messages)
        return self.encode(text, add_special_tokens=False) if tokenize else text

    def encode(self, text: str, add_special_tokens: bool) -> list[int]:
        return [ord(char) for char in text]


def test_preflight_report_is_complete_and_allocates_nothing() -> None:
    report = preflight.build_preflight(_CharTokenizer())
    assert report["gold_derivable"] == {"numerator": 10, "denominator": 10}
    assert report["oracle_exact"] == {"numerator": 10, "denominator": 10}
    assert report["gpu_allocated"] is False and report["weights_loaded"] is False
    assert len(report["cases"]) == 10
    assert all(row["constrained_emitted_ids_are_joint_encoding"] for row in report["cases"])
    assert report["max_constrained_scorer_calls"] == 69
    for row in report["cases"]:
        assert 0 < row["gold_path_cached_fed_tokens"] < row["gold_path_uncached_scored_tokens"]
        assert row["gold_path_cached_fed_tokens"] >= row["prompt_tokens"]


def test_profile_token_caps_follow_their_stated_derivation_rule() -> None:
    decoding = v3.load_profile()["decoding"]
    gold_max = 84  # pinned-tokenizer value recorded in the derivation text
    assert f"({gold_max} tokens" in decoding["derivation"]
    cap = decoding["action_max_new_tokens"]
    assert cap >= 1.5 * gold_max and cap & (cap - 1) == 0 and cap // 2 < 1.5 * gold_max


@pytest.mark.skipif(
    not (preflight.TOKENIZER_DIR / "tokenizer.json").exists(),
    reason="pinned tokenizer is held outside Git on E:",
)
def test_pinned_tokenizer_preflight_fits_profile_bounds() -> None:  # pragma: no cover
    pytest.importorskip("transformers")
    report = preflight.build_preflight(preflight.load_pinned_tokenizer())
    decoding = v3.load_profile()["decoding"]
    assert report["max_prompt_tokens"] <= decoding["action_max_prompt_tokens"]
    assert report["max_gold_native_action_tokens"] == 84
    assert report["max_gold_native_action_tokens"] * 1.5 <= decoding["action_max_new_tokens"]
