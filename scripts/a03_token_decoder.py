"""Token-level greedy decoding for the fixed-order V3 action language."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts import a02_v3_contract as v3

State = frozenset[int]


@dataclass(frozen=True)
class Vocabulary:
    pieces: Mapping[int, bytes]
    eos: int

    @classmethod
    def from_pinned(cls, path: Path) -> Vocabulary:
        from scripts.a02_v3_preflight import load_pinned_tokenizer

        tokenizer = load_pinned_tokenizer(path)
        spec = json.loads(tokenizer.backend_tokenizer.to_str())
        if spec["model"]["type"] != "BPE" or spec["decoder"]["type"] != "ByteLevel":
            raise ValueError("unsupported V3 tokenizer decoder")
        # Every V3 grammar literal uses printable ASCII without spaces. ByteLevel maps
        # these bytes to themselves, including when a token spans two grammar literals.
        pieces = {
            index: spelling.encode("ascii")
            for spelling, index in spec["model"]["vocab"].items()
            if spelling and all("!" <= char <= "~" for char in spelling)
        }
        for added in spec["added_tokens"]:
            index, spelling = added["id"], added["content"]
            pieces.pop(index, None)
            if not added["special"] and spelling in (v3.OPEN, v3.CLOSE):
                if tokenizer.decode([index], skip_special_tokens=True) != spelling:
                    raise ValueError("V3 tokenizer framing is ambiguous")
                pieces[index] = spelling.encode("ascii")
        return cls(pieces, int(tokenizer.eos_token_id))


class Grammar:
    """A byte NFA with shared suffixes for the V3 subsequence lists."""

    def __init__(self, request: dict[str, Any]):
        self.ids = v3.observation_ids(request)
        self.edges: list[dict[int, set[int]]] = [{}]
        end = self._literal("}}}" + v3.CLOSE, 0)
        end = self._list(v3.RELATIONSHIP_LEVELS, end)
        end = self._literal(',"relationship":[', end)
        end = self._list(v3.MEASUREMENT_LEVELS, end)
        end = self._literal(',"target_claims":{"measurement":[', end)
        end = self._options((*v3.EXPOSED_OPERATIONS, v3.NONE), end)
        end = self._literal(',"operation":', end)
        end = self._list(self.ids, end)
        end = self._literal(',"observation_ids":[', end)
        end = self._options((*v3.ANALYSIS_CLASSES, v3.NONE), end)
        self.start = frozenset(
            [
                self._literal(
                    f'{v3.OPEN}{{"name":{json.dumps(v3.TOOL_NAME)},"arguments":{{"analysis_class":',
                    end,
                )
            ]
        )

    def _node(self, edges: dict[int, set[int]]) -> int:
        self.edges.append(edges)
        return len(self.edges) - 1

    def _literal(self, literal: str, end: int) -> int:
        for byte in reversed(literal.encode("ascii")):
            end = self._node({byte: {end}})
        return end

    def _union(self, starts: Sequence[int]) -> int:
        edges: dict[int, set[int]] = {}
        for start in starts:
            for byte, targets in self.edges[start].items():
                edges.setdefault(byte, set()).update(targets)
        return self._node(edges)

    def _options(self, items: Sequence[str], end: int) -> int:
        return self._union([self._literal(json.dumps(item), end) for item in items])

    def _list(self, items: Sequence[str], end: int) -> int:
        close = self._literal("]", end)
        first_items: list[int] = [close]
        next_items: list[int] = [close]
        for item in reversed(items):
            first = self._literal(json.dumps(item), self._union(next_items))
            first_items.append(first)
            next_items.append(self._literal(",", first))
        return self._union(first_items)

    def advance(self, state: State, piece: bytes) -> State:
        for byte in piece:
            state = frozenset(target for node in state for target in self.edges[node].get(byte, ()))
            if not state:
                break
        return state

    def accepts(self, output: bytes) -> bool:
        return 0 in self.advance(self.start, output)


class TokenMask:
    """Build an immutable vocabulary index once and reuse it across requests."""

    def __init__(self, vocabulary: Vocabulary):
        self.eos = vocabulary.eos
        self.pieces = dict(vocabulary.pieces)
        self.tokens: dict[bytes, list[int]] = {}
        self.prefixes: set[bytes] = set()
        for index, piece in self.pieces.items():
            if not piece or index == self.eos:
                raise ValueError("empty or ambiguous V3 vocabulary token")
            self.tokens.setdefault(piece, []).append(index)
            self.prefixes.update(piece[:size] for size in range(1, len(piece)))

    def advance(self, grammar: Grammar, state: State, token: int) -> State:
        piece = self.pieces.get(token)
        return grammar.advance(state, piece) if piece else frozenset()

    def allowed(self, grammar: Grammar, state: State) -> tuple[int, ...]:
        # Visit only prefixes shared by the vocabulary and the current grammar state.
        allowed = [self.eos] if 0 in state else []
        todo = [(b"", state)]
        while todo:
            prefix, position = todo.pop()
            for byte in {byte for node in position for byte in grammar.edges[node]}:
                piece = prefix + bytes([byte])
                allowed.extend(self.tokens.get(piece, ()))
                if piece in self.prefixes:
                    todo.append((piece, grammar.advance(position, bytes([byte]))))
        return tuple(sorted(allowed))

    def decode(
        self,
        grammar: Grammar,
        prompt_ids: Sequence[int],
        logits: Callable[[Sequence[int]], Sequence[float]],
        max_new_tokens: int,
    ) -> tuple[list[int], str]:
        """Use next-token logits and the lowest token ID for exact greedy ties."""
        state = grammar.start
        generated: list[int] = []
        output = bytearray()
        for _ in range(max_new_tokens):
            allowed = self.allowed(grammar, state)
            if not allowed:
                raise ValueError("V3 grammar has no supported token transition")
            scores = logits([*prompt_ids, *generated])
            if allowed[-1] >= len(scores) or any(math.isnan(scores[token]) for token in allowed):
                raise ValueError("invalid V3 next-token logits")
            chosen = max(allowed, key=lambda token: scores[token])
            if not math.isfinite(scores[chosen]):
                raise ValueError("no finite V3 token score")
            generated.append(chosen)
            if chosen == self.eos:
                text = output.decode("ascii")
                v3.parse_action(text, grammar.ids)
                return generated, text
            state = self.advance(grammar, state, chosen)
            output.extend(self.pieces[chosen])
        raise ValueError("V3 generation ended before terminal EOS")
