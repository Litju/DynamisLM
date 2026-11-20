"""Grammar-constrained V3 action decoding: the syntax-control condition (RES-541).

The decoder walks the closed V3 grammar in a fixed field order (analysis_class,
observation_ids, operation, target_claims). Scaffolding is forced; at each choice point the
model only ranks the allowed continuations by summed token log-probability (greedy, no length
normalization, ties broken by canonical option order). Output is schema-valid by
construction, so this condition removes syntax failure and isolates choice quality. It earns
no model-understanding credit by itself: it is compared with the same model's unconstrained
native generation and scored on the same axes.

Scoring uses natural joint tokenization. At a choice point every option's text is encoded
together with the action prefix; all options are scored from the same position, the longest
token prefix their encodings share, so each score is the log-probability of the same prefix
text followed by that option under identical conditioning. Emitted ids are the joint encoding
of the final text. (Piecewise per-segment encoding was rejected after the preflight showed it
differs from joint tokenization on every gold path.)
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from scripts import a02_v3_contract as v3

# sequence_logprob(ids, start) -> sum over i >= start of log p(ids[i] | ids[:i])
SequenceLogprob = Callable[[Sequence[int], int], float]
Encode = Callable[[str], list[int]]
CLOSE_LIST = "]"


class _Walk:
    def __init__(self, encode: Encode, prompt_ids: Sequence[int]):
        self.encode = encode
        self.prompt_ids = list(prompt_ids)
        self.text = ""
        self.pieces: list[str] = []
        self.choices: list[dict[str, Any]] = []
        self.calls = 0
        self.max_rescored_prefix_tokens = 0

    def force(self, piece: str) -> None:
        self.text += piece
        self.pieces.append(piece)


# chooser(walk, field, options) -> (chosen option, per-option scores)
Chooser = Callable[[_Walk, str, list[str]], tuple[str, list[float]]]


def _choose(walk: _Walk, field: str, options: list[str], chooser: Chooser) -> str:
    if not options:
        raise ValueError("constrained grammar reached a choice point without options")
    chosen, scores = (options[0], [0.0]) if len(options) == 1 else chooser(walk, field, options)
    if chosen not in options:
        raise ValueError("chooser selected an option outside the grammar")
    walk.choices.append({"field": field, "options": options, "scores": scores, "chosen": chosen})
    walk.force(chosen)
    return chosen


def _enum(walk: _Walk, field: str, values: Sequence[str], chooser: Chooser) -> str:
    value = json.loads(_choose(walk, field, [json.dumps(v) for v in values], chooser))
    if not isinstance(value, str):
        raise ValueError("constrained enum produced a non-string value")
    return value


def _subsequence(walk: _Walk, field: str, items: Sequence[str], chooser: Chooser) -> list[str]:
    """Strictly increasing subsequence of ``items``: one element or the list close per step."""
    chosen: list[str] = []
    remaining = list(items)
    while True:
        prefix = "," if chosen else ""
        options = [f"{prefix}{json.dumps(item)}" for item in remaining] + [CLOSE_LIST]
        pick = _choose(walk, field, options, chooser)
        if pick == CLOSE_LIST:
            return chosen
        item = json.loads(pick.removeprefix(","))
        chosen.append(item)
        remaining = remaining[remaining.index(item) + 1 :]


def _walk_grammar(walk: _Walk, request: dict[str, Any], chooser: Chooser) -> dict[str, Any]:
    ids = v3.observation_ids(request)
    walk.force(f'{v3.OPEN}{{"name":{json.dumps(v3.TOOL_NAME)},"arguments":{{"analysis_class":')
    analysis = _enum(walk, "analysis_class", (*v3.ANALYSIS_CLASSES, v3.NONE), chooser)
    walk.force(',"observation_ids":[')
    refs = _subsequence(walk, "observation_ids", ids, chooser)
    walk.force(',"operation":')
    operation = _enum(walk, "operation", (*v3.EXPOSED_OPERATIONS, v3.NONE), chooser)
    walk.force(',"target_claims":{"measurement":[')
    measurement = _subsequence(walk, "target_claims.measurement", v3.MEASUREMENT_LEVELS, chooser)
    walk.force(',"relationship":[')
    relationship = _subsequence(walk, "target_claims.relationship", v3.RELATIONSHIP_LEVELS, chooser)
    walk.force("}}}" + v3.CLOSE)
    action = {
        "analysis_class": analysis,
        "observation_ids": refs,
        "operation": operation,
        "target_claims": {"measurement": measurement, "relationship": relationship},
    }
    if v3.parse_action(walk.text, ids) != action:
        raise ValueError("constrained output does not parse to the decoded action")
    return action


def model_chooser(score: SequenceLogprob) -> Chooser:
    def choose(walk: _Walk, field: str, options: list[str]) -> tuple[str, list[float]]:
        prefix = walk.encode(walk.text)
        encoded = [walk.encode(walk.text + option) for option in options]
        start = len(prefix)
        for ids in encoded:
            shared = 0
            while shared < min(len(ids), len(prefix)) and ids[shared] == prefix[shared]:
                shared += 1
            start = min(start, shared)
        walk.max_rescored_prefix_tokens = max(walk.max_rescored_prefix_tokens, len(prefix) - start)
        offset = len(walk.prompt_ids)
        values = []
        for ids in encoded:
            if len(ids) <= start:
                raise ValueError("constrained option has no tokens after the shared prefix")
            value = float(score([*walk.prompt_ids, *ids], offset + start))
            walk.calls += 1
            if not math.isfinite(value):
                raise ValueError("constrained scorer returned a non-finite log-probability")
            values.append(value)
        best = max(range(len(options)), key=lambda i: (values[i], -i))
        return options[best], values

    return choose


def target_chooser(action: dict[str, Any]) -> Chooser:
    """Steer to a known action; used for preflight token accounting and tests."""
    target = v3.normalize_action(action)

    def choose(walk: _Walk, field: str, options: list[str]) -> tuple[str, list[float]]:
        if field in ("analysis_class", "operation"):
            return json.dumps(target[field]), []
        wanted = (
            target["observation_ids"]
            if field == "observation_ids"
            else target["target_claims"][field.split(".", 1)[1]]
        )
        for option in options:
            if option != CLOSE_LIST and json.loads(option.removeprefix(",")) in wanted:
                return option, []
        return CLOSE_LIST, []

    return choose


def decode(
    *,
    request: dict[str, Any],
    prompt_ids: Sequence[int],
    encode: Encode,
    chooser: Chooser,
) -> dict[str, Any]:
    walk = _Walk(encode, prompt_ids)
    action = _walk_grammar(walk, request, chooser)
    return {
        "text": walk.text,
        "action": action,
        "token_ids": encode(walk.text),
        "pieces": walk.pieces,
        "scorer_calls": walk.calls,
        "max_rescored_prefix_tokens": walk.max_rescored_prefix_tokens,
        "choices": walk.choices,
    }


def max_scorer_calls(request: dict[str, Any]) -> int:
    """Upper bound on scorer calls for one request: every multi-option choice is scored."""

    def subsequence_bound(k: int) -> int:
        # Step j offers (k - j) remaining items plus the close; the worst case picks all items.
        return sum(k - j + 1 for j in range(k + 1) if k - j + 1 > 1)

    return (
        len(v3.ANALYSIS_CLASSES)
        + 1
        + subsequence_bound(len(v3.observation_ids(request)))
        + len(v3.EXPOSED_OPERATIONS)
        + 1
        + sum(subsequence_bound(len(levels)) for levels in v3.CLAIM_AXES.values())
    )


class IncrementalBackend(Protocol):
    def logprobs(self, keep: int, new_ids: Sequence[int], targets: Sequence[int]) -> list[float]:
        """Crop the cache to ``keep`` tokens, feed ``new_ids``, and return log p(targets[j])
        at the final ``len(targets)`` fed positions. Cache all ``keep + len(new_ids)`` tokens."""
        ...


class CachedSequenceLogprob:
    """KV-cache-reusing SequenceLogprob with identical values to full re-scoring.

    Consecutive calls share the prompt and action prefix, so only the tokens after the
    longest cached common prefix are fed. ``fed_tokens`` counts the backend's work.
    """

    def __init__(self, backend: IncrementalBackend):
        self.backend = backend
        self.cached: list[int] = []
        self.fed_tokens = 0

    def __call__(self, ids: Sequence[int], start: int) -> float:
        ids = list(ids)
        if not 0 < start < len(ids):
            raise ValueError("scored span must be non-empty and follow at least one token")
        common = 0
        limit = min(len(self.cached), start - 1)
        while common < limit and self.cached[common] == ids[common]:
            common += 1
        feed, targets = ids[common:-1], ids[start:]
        values = self.backend.logprobs(common, feed, targets)
        if len(values) != len(targets):
            raise ValueError("backend returned a misaligned log-probability vector")
        self.fed_tokens += len(feed)
        self.cached = ids[:-1]
        return float(sum(values))


class HFIncrementalBackend:
    """transformers DynamicCache backend; requires torch.

    CPU-qualified against full re-scoring with a tiny real SmolLM3ForCausalLM (RoPE and NoPE
    layers) in tests/test_res541_a02_v3_real_decoder.py; the pinned model is re-checked in-run.
    """

    def __init__(self, model: Any):
        self.model = model
        self.cache: Any = None

    def logprobs(self, keep: int, new_ids: Sequence[int], targets: Sequence[int]) -> list[float]:
        import torch  # type: ignore[import-not-found]
        from torch.nn.attention import SDPBackend, sdpa_kernel  # type: ignore[import-not-found]

        if not 0 < len(targets) <= len(new_ids):
            raise ValueError("scored targets must be a non-empty suffix of the fed positions")
        if keep == 0:
            self.cache = None
        elif self.cache is not None:
            self.cache.crop(keep)
        tensor = torch.tensor([list(new_ids)], device=self.model.device)
        # FP16 fused attention takes different numerical paths for prefill and cached tails.
        with torch.inference_mode(), sdpa_kernel(SDPBackend.MATH):
            out = self.model(
                tensor, past_key_values=self.cache, use_cache=True, logits_to_keep=len(targets)
            )
        self.cache = out.past_key_values
        logp = torch.log_softmax(out.logits[0], dim=-1, dtype=torch.float32)
        index = torch.tensor(list(targets), device=logp.device).unsqueeze(1)
        return [float(v) for v in logp.gather(1, index).squeeze(1).tolist()]


def hf_token_logprobs(model: Any, ids: Sequence[int], start: int) -> list[float]:
    """Uncached full-context per-token log p(ids[i] | ids[:i]) for every i >= start."""
    import torch
    from torch.nn.attention import SDPBackend, sdpa_kernel

    if not 0 < start < len(ids):
        raise ValueError("scored span must be non-empty and follow at least one token")
    tensor = torch.tensor([list(ids[:-1])], device=model.device)
    with torch.inference_mode(), sdpa_kernel(SDPBackend.MATH):
        logits = model(tensor, use_cache=False, logits_to_keep=len(ids) - start).logits[0]
    targets = torch.tensor(list(ids[start:]), device=model.device).unsqueeze(1)
    picked = torch.log_softmax(logits, dim=-1, dtype=torch.float32).gather(1, targets)
    return [float(v) for v in picked.squeeze(1).tolist()]


def hf_sequence_logprob(model: Any) -> SequenceLogprob:
    """Uncached reference binding: full re-scoring per option. Used in-run only to verify
    the cached binding on a sample before any arm result counts."""

    def score(ids: Sequence[int], start: int) -> float:
        return float(sum(hf_token_logprobs(model, ids, start)))

    return score
