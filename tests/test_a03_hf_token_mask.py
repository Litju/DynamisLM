from dataclasses import dataclass
from functools import partial

import pytest
from scripts.a03_hf_token_mask import hf_prefix_mask
from scripts.a03_token_decoder import Grammar, TokenMask, Vocabulary

from test_a03_token_decoder import EOS, PARTS, REQUEST


@dataclass
class MockTensor:
    ids: list[int]

    def tolist(self) -> list[int]:
        return self.ids


def test_hf_prefix_mask_preserves_the_native_prefix_and_exposes_only_legal_eos() -> None:
    callable_mask = partial(
        hf_prefix_mask,
        TokenMask(Vocabulary(dict(enumerate(PARTS)), EOS)),
        Grammar(REQUEST),
        [90, 91],
    )
    for i in range(len(PARTS)):
        assert i in callable_mask(0, MockTensor([90, 91, *range(i)]))
    assert callable_mask(0, MockTensor([90, 91, *range(len(PARTS))])) == [EOS]
    for batch, prefix in [(1, [90, 91]), (0, [99, 91]), (0, [90, 91, EOS])]:
        with pytest.raises(ValueError):
            callable_mask(batch, MockTensor(prefix))
