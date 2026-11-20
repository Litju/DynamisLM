"""Bind the A0.3 token mask to pinned Transformers single-sequence greedy generation."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from scripts.a03_token_decoder import Grammar, TokenMask


class TokenTensor(Protocol):
    def tolist(self) -> list[int]: ...


def hf_prefix_mask(
    mask: TokenMask,
    grammar: Grammar,
    prompt_ids: Sequence[int],
    batch_id: int,
    full_ids: TokenTensor,
) -> list[int]:
    """Use as prefix_allowed_tokens_fn with batch size one, one beam and no sampling."""
    ids = full_ids.tolist()
    if batch_id != 0 or ids[: len(prompt_ids)] != list(prompt_ids):
        raise ValueError("A0.3 generation left the bound single-prompt batch")
    state = grammar.start
    for token in ids[len(prompt_ids) :]:
        state = mask.advance(grammar, state, token)
        if not state:
            raise ValueError("A0.3 generation prefix is outside the token grammar")
    allowed = mask.allowed(grammar, state)
    if not allowed:
        raise ValueError("A0.3 generation has no supported token transition")
    return list(allowed)
