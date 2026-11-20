import pytest
from scripts import a02_v3_contract as v3
from scripts.a03_token_decoder import Grammar, TokenMask, Vocabulary

REQUEST: dict[str, list[dict[str, str]]] = {"observations": [{}, {}]}
ACTION = {
    "analysis_class": "NONE",
    "observation_ids": ["observation-1", "observation-2"],
    "operation": "NONE",
    "target_claims": {"measurement": [], "relationship": []},
}
# Several tokens span literal, quote, list, and framing boundaries.
PARTS = (
    b'<tool_call>{"name":"submit_scientific_action_v3","arguments":{"analysis_class":"',
    b'NONE","observation_ids":["',
    b'observation-1","',
    b'observation-2"],"operation":"',
    b'NONE","target_claims":{"measurement":[],"relationship":[',
    b"]}}}</tool_call>",
)
EOS = 9
TEXT = b"".join(PARTS).decode()


def test_byte_grammar_is_stricter_than_parser() -> None:
    grammar = Grammar(REQUEST)
    assert grammar.accepts(TEXT.encode())
    for altered in (
        TEXT.replace(',"operation"', ', "operation"'),
        TEXT.replace('"observation-1","observation-2"', '"observation-2","observation-1"'),
    ):
        v3.parse_action(altered, grammar.ids)
        assert not grammar.accepts(altered.encode())
    assert not grammar.accepts(TEXT.replace("observation-2", "observation-3").encode())


@pytest.mark.parametrize("off_grammar_argmax", [False, True])
def test_mock_greedy_preserves_tokens_and_masks_invalid_choices(off_grammar_argmax: bool) -> None:
    pieces = dict(enumerate(PARTS))
    pieces.update({6: b'observation-3","', 7: b"</tool_call>", 8: b"!"})
    mask = TokenMask(Vocabulary(pieces, EOS))
    expected = [*range(len(PARTS)), EOS]

    def logits(prefix: object) -> list[float]:
        assert isinstance(prefix, list)
        step = len(prefix) - 1
        assert prefix == [99, *expected[:step]]
        scores = [-100.0] * 10
        scores[expected[step]] = 1.0
        if off_grammar_argmax and step < len(PARTS):
            scores[EOS if step == 0 else 6] = 2.0
        return scores

    assert v3.parse_action(TEXT, Grammar(REQUEST).ids) == ACTION
    assert mask.decode(Grammar(REQUEST), [99], logits, 7) == (expected, TEXT)


def test_aliases_ties_eos_and_no_unsupported_transition() -> None:
    pieces = {**dict(enumerate(PARTS)), 7: PARTS[0]}
    mask = TokenMask(Vocabulary(pieces, EOS))
    grammar = Grammar(REQUEST)
    assert mask.allowed(grammar, grammar.start) == (0, 7)
    state = grammar.advance(grammar.start, TEXT.encode())
    assert mask.allowed(grammar, state) == (EOS,)
    assert mask.decode(grammar, [], lambda _: [0.0] * 10, 7)[0][0] == 0
    with pytest.raises(ValueError, match="before terminal EOS"):
        mask.decode(grammar, [], lambda _: [0.0] * 10, 6)
    with pytest.raises(ValueError, match="no finite"):
        mask.decode(grammar, [], lambda _: [float("-inf")] * 10, 7)
    with pytest.raises(ValueError, match="no supported token"):
        TokenMask(Vocabulary({0: b"!"}, EOS)).decode(grammar, [], lambda _: [], 7)


def test_d0_replay_fails_at_first_invalid_token_and_requires_terminal_eos() -> None:
    from scripts.a03_d0_static import token_replay

    grammar = Grammar(REQUEST)
    mask = TokenMask(Vocabulary({**dict(enumerate(PARTS)), 6: b'"wrong"]'}, EOS))
    expected = list(range(len(PARTS)))
    assert token_replay(mask, grammar, [*expected, EOS], TEXT) == (True, None)
    accepted, first = token_replay(mask, grammar, [0, 1, 6], TEXT)
    assert not accepted
    assert first == {"position": 2, "token_id": 6, "accepted_prefix": b"".join(PARTS[:2]).decode()}
    assert token_replay(mask, grammar, expected, TEXT) == (
        False,
        {"position": len(expected), "token_id": None, "reason": "recorded EOS absent"},
    )
