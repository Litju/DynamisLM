"""Three-path numerical diagnostic for V3 constrained option scoring (RES-541).

ENGINEERING EVIDENCE ONLY. Nothing here is a scientific result, a qualification verdict or an
arm record; it exists to locate the first numerical divergence between scoring strategies that
are mathematically identical:

    log P(x[start:] | x[:start]) = sum_{t >= start} log P(x[t] | x[:t])

* Path A, full context: one uncached forward over ``ids[:-1]`` (the worker's reference binding).
* Path B, fresh cache: a new KV cache per candidate, prefilled with ``ids[:keep]`` in one chunk,
  then the tail ``ids[keep:-1]`` fed against it. ``keep`` is the prefix that path C reused for
  the same call, so B reproduces C's final execution shape without inheriting C's cache history.
* Path C, reused cache: the production ``CachedSequenceLogprob`` over ``HFIncrementalBackend``,
  which crops and reuses one DynamicCache across candidates.

Interpretation: B versus C isolates cache reuse and cropping (same final chunk boundary, different
history); A versus B isolates execution shape (one chunk versus prefix plus tail); A versus C is
what the in-run qualification measures. ``layer_divergence`` then compares A and B hidden states
layer by layer at the scored positions, and ``head_decomposition`` separates the transformer body
from the final projection: it re-projects the same hidden state in the model dtype and in FP32.
"""

from __future__ import annotations

import math
import platform
from collections.abc import Sequence
from typing import Any

from scripts import a02_v3_constrained as constrained

SCHEMA = "RES541_A02_V3_NUMERICAL_DIAGNOSTIC_V1"
EVIDENCE_CLASS = "ENGINEERING_EVIDENCE_NOT_SCIENTIFIC_RESULT"
QUALIFICATION_TOLERANCE_NATS = 1e-3


class RecordingBackend(constrained.HFIncrementalBackend):
    """Production incremental backend plus per-call cache, position and mask instrumentation."""

    def __init__(self, model: Any):
        super().__init__(model)
        self.calls: list[dict[str, Any]] = []
        self._observed: dict[str, Any] = {}
        self._hooks: list[Any] = []

    def _install(self) -> None:
        def rotary(module: Any, args: Any, kwargs: Any) -> None:
            positions = kwargs.get("position_ids", args[1] if len(args) > 1 else None)
            self._observed["position_ids"] = [int(p) for p in positions[0].tolist()]

        def attention(module: Any, args: Any, kwargs: Any) -> None:
            mask = kwargs.get("attention_mask")
            self._observed["attention_mask"] = (
                None if mask is None else {"shape": list(mask.shape), "dtype": str(mask.dtype)}
            )
            self._observed["cache_position"] = [int(p) for p in kwargs["cache_position"].tolist()]

        base = self.model.model
        self._hooks = [
            base.rotary_emb.register_forward_pre_hook(rotary, with_kwargs=True),
            base.layers[0].self_attn.register_forward_pre_hook(attention, with_kwargs=True),
        ]

    def logprobs(self, keep: int, new_ids: Sequence[int], targets: Sequence[int]) -> list[float]:
        before = 0 if self.cache is None else int(self.cache.get_seq_length())
        self._observed = {}
        self._install()
        try:
            values = super().logprobs(keep, new_ids, targets)
        finally:
            for hook in self._hooks:
                hook.remove()
        layer0 = self.cache.layers[0] if hasattr(self.cache, "layers") else None
        key = layer0.keys if layer0 is not None else self.cache.key_cache[0]
        self.calls.append(
            {
                "keep": keep,
                "cache_length_before_crop": before,
                "cache_length_after": int(self.cache.get_seq_length()),
                "fed_tokens": len(new_ids),
                "scored_tokens": len(targets),
                "position_ids_first_last": _ends(self._observed.get("position_ids", [])),
                "cache_position_first_last": _ends(self._observed.get("cache_position", [])),
                "positions_contiguous_from_keep": self._observed.get("position_ids")
                == list(range(keep, keep + len(new_ids)))
                == self._observed.get("cache_position"),
                "attention_mask": self._observed.get("attention_mask"),
                "kv_layer0_shape": list(key.shape),
                "kv_dtype": str(key.dtype),
                "token_logprobs": values,
            }
        )
        return values


def _ends(values: Sequence[int]) -> list[int]:
    return [values[0], values[-1]] if values else []


def fresh_cache_token_logprobs(
    model: Any, ids: Sequence[int], start: int, keep: int
) -> list[float]:
    """Path B: new cache, prefill ``ids[:keep]`` in one chunk, then score from the tail."""
    if not 0 <= keep < start < len(ids):
        raise ValueError("fresh-cache path needs 0 <= keep < start < len(ids)")
    backend = constrained.HFIncrementalBackend(model)
    if keep:
        backend.logprobs(0, ids[:keep], ids[keep : keep + 1])
    return backend.logprobs(keep, ids[keep:-1], ids[start:])


class _CallRecorder:
    """SequenceLogprob wrapper that records each production scorer call in order."""

    def __init__(self, scorer: constrained.CachedSequenceLogprob):
        self.scorer = scorer
        self.calls: list[tuple[list[int], int]] = []

    def __call__(self, ids: Sequence[int], start: int) -> float:
        self.calls.append((list(ids), start))
        return self.scorer(ids, start)


def _compare(a: Sequence[float], b: Sequence[float], tolerance: float) -> dict[str, Any]:
    if not a or any(not math.isfinite(v) for v in (*a, *b)):
        raise ValueError("numerical comparison requires finite non-empty scores")
    diffs = [x - y for x, y in zip(a, b, strict=True)]
    absolute = [abs(d) for d in diffs]
    exact = next((i for i, d in enumerate(diffs) if d != 0.0), None)
    material = next((i for i, d in enumerate(absolute) if d > tolerance), None)
    return {
        "first_bitwise_divergent_token": exact,
        "first_token_above_tolerance": material,
        "max_abs_token_difference": max(absolute, default=0.0),
        "mean_abs_token_difference": sum(absolute) / len(absolute) if absolute else 0.0,
        "signed_sum_difference": math.fsum(diffs),
        "abs_sum_difference": abs(math.fsum(diffs)),
    }


def _margins(choices: list[dict[str, Any]], scores: Sequence[float]) -> list[dict[str, Any]]:
    out, cursor = [], 0
    for choice in choices:
        if len(choice["options"]) < 2:
            continue
        values = list(scores[cursor : cursor + len(choice["options"])])
        cursor += len(choice["options"])
        order = sorted(range(len(values)), key=lambda i: (-values[i], i))
        out.append(
            {
                "field": choice["field"],
                "winner": order[0],
                "runner_up": order[1],
                "margin_nats": values[order[0]] - values[order[1]],
            }
        )
    return out


def runtime_identity(model: Any) -> dict[str, Any]:
    import torch  # type: ignore[import-not-found]
    import transformers

    device = model.device
    identity: dict[str, Any] = {
        "python": platform.python_version(),
        "torch": torch.__version__,
        "transformers": transformers.__version__,
        "device": str(device),
        "dtype": str(model.dtype),
        "attn_implementation": model.config._attn_implementation,
        "sdpa_backend_in_scorer": "MATH",
        "training_mode": bool(model.training),
        "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
    }
    if device.type == "cuda":
        identity.update(
            gpu=torch.cuda.get_device_name(device),
            capability=list(torch.cuda.get_device_capability(device)),
            cuda_runtime=torch.version.cuda,
            allow_fp16_reduced_precision_reduction=(
                torch.backends.cuda.matmul.allow_fp16_reduced_precision_reduction
            ),
            allow_tf32=torch.backends.cuda.matmul.allow_tf32,
        )
    return identity


def _rescore(
    model: Any,
    calls: Sequence[tuple[list[int], int]],
    recorded: Sequence[dict[str, Any]],
    *,
    tolerance: float,
    max_candidates: int | None,
) -> tuple[list[dict[str, Any]], dict[str, list[float]]]:
    """Re-score every recorded path-C call with paths A and B and compare per token."""
    if len(calls) != len(recorded):
        raise ValueError("recorded scorer calls and backend calls differ")
    candidates = []
    totals: dict[str, list[float]] = {"A": [], "B": [], "C": []}
    for index, ((ids, start), call) in enumerate(zip(calls, recorded, strict=True)):
        if max_candidates is not None and index >= max_candidates:
            break
        c = call["token_logprobs"]
        a = constrained.hf_token_logprobs(model, ids, start)
        b = fresh_cache_token_logprobs(model, ids, start, call["keep"])
        for name, values in (("A", a), ("B", b), ("C", c)):
            totals[name].append(math.fsum(values))
        candidates.append(
            {
                "index": index,
                "input_tokens": len(ids),
                "scored_suffix": [start, len(ids)],
                "target_token_ids": ids[start:],
                "c_call": {k: v for k, v in call.items() if k != "token_logprobs"},
                "token_logprobs": {"A": a, "B": b, "C": c},
                "A_vs_B": _compare(a, b, tolerance),
                "B_vs_C": _compare(b, c, tolerance),
                "A_vs_C": _compare(a, c, tolerance),
            }
        )
    return candidates, totals


def summarize(candidates: Sequence[dict[str, Any]], tolerance: float) -> dict[str, Any]:
    return {
        pair: {
            "max_abs_score_difference": max(
                (c[pair]["abs_sum_difference"] for c in candidates), default=0.0
            ),
            "max_abs_token_difference": max(
                (c[pair]["max_abs_token_difference"] for c in candidates), default=0.0
            ),
            "candidates_above_tolerance": sum(
                c[pair]["abs_sum_difference"] > tolerance for c in candidates
            ),
        }
        for pair in ("A_vs_B", "B_vs_C", "A_vs_C")
    }


def replay(
    model: Any,
    calls: Sequence[tuple[Sequence[int], int]],
    *,
    backend: RecordingBackend | None = None,
    tolerance: float = QUALIFICATION_TOLERANCE_NATS,
) -> dict[str, Any]:
    """Three-path comparison of an explicit ordered call schedule (no grammar walk)."""
    backend = RecordingBackend(model) if backend is None else backend
    scorer = constrained.CachedSequenceLogprob(backend)
    schedule = [(list(ids), start) for ids, start in calls]
    for ids, start in schedule:
        scorer(ids, start)
    backend.cache = None
    candidates, _ = _rescore(
        model, schedule, backend.calls, tolerance=tolerance, max_candidates=None
    )
    return {"summary": summarize(candidates, tolerance), "candidates": candidates}


def three_path(
    *,
    model: Any,
    request: dict[str, Any],
    prompt_ids: Sequence[int],
    encode: constrained.Encode,
    tolerance: float = QUALIFICATION_TOLERANCE_NATS,
    max_candidates: int | None = None,
) -> dict[str, Any]:
    """Run the production cached walk, then re-score every call with paths A and B."""
    backend = RecordingBackend(model)
    recorder = _CallRecorder(constrained.CachedSequenceLogprob(backend))
    walk = constrained.decode(
        request=request,
        prompt_ids=prompt_ids,
        encode=encode,
        chooser=constrained.model_chooser(recorder),
    )
    backend.cache = None
    candidates, totals = _rescore(
        model, recorder.calls, backend.calls, tolerance=tolerance, max_candidates=max_candidates
    )
    complete = len(candidates) == len(recorder.calls)
    summary = summarize(candidates, tolerance)
    margins = (
        {name: _margins(walk["choices"], values) for name, values in totals.items()}
        if complete
        else None
    )
    return {
        "schema": SCHEMA,
        "evidence_class": EVIDENCE_CLASS,
        "tolerance_nats": tolerance,
        "runtime": runtime_identity(model),
        "prompt_tokens": len(prompt_ids),
        "scorer_calls": len(recorder.calls),
        "candidates_examined": len(candidates),
        "complete": complete,
        "cached_action": walk["action"],
        "summary": summary,
        "winner_margins": margins,
        "winners_agree": None
        if margins is None
        else len({tuple(m["winner"] for m in v) for v in margins.values()}) == 1,
        "min_winner_margin_nats": None
        if margins is None
        else min((m["margin_nats"] for m in margins["C"]), default=None),
        "candidates": candidates,
    }


def _hidden_states(model: Any, chunks: Sequence[Sequence[int]], positions: int) -> list[Any]:
    """Per-layer hidden states at the last ``positions`` fed tokens, fed chunk by chunk."""
    import torch
    from torch.nn.attention import SDPBackend, sdpa_kernel  # type: ignore[import-not-found]

    cache = None
    out = None
    with torch.inference_mode(), sdpa_kernel(SDPBackend.MATH):
        for chunk in chunks:
            out = model.model(
                torch.tensor([list(chunk)], device=model.device),
                past_key_values=cache,
                use_cache=True,
                output_hidden_states=True,
            )
            cache = out.past_key_values
    if out is None:
        raise ValueError("no chunks were fed")
    return [
        h[0, -positions:].to(device="cpu", dtype=torch.float32, copy=True)
        for h in out.hidden_states
    ]


def layer_divergence(model: Any, ids: Sequence[int], start: int, keep: int) -> dict[str, Any]:
    """Compare A (one chunk) and B (prefix + tail) hidden states at the scored positions."""
    if not 0 < keep < start < len(ids):
        raise ValueError("layer divergence needs 0 < keep < start < len(ids)")
    positions = len(ids) - start
    full = _hidden_states(model, [ids[:-1]], positions)
    split = _hidden_states(model, [ids[:keep], ids[keep:-1]], positions)
    layers: list[dict[str, Any]] = []
    for index, (x, y) in enumerate(zip(full, split, strict=True)):
        layers.append(
            {
                "hidden_state_index": index,
                "max_abs_difference": float((x - y).abs().max()),
                "first_divergent_target_token": next(
                    (
                        start + i
                        for i, differs in enumerate((x != y).any(dim=-1).tolist())
                        if differs
                    ),
                    None,
                ),
                "max_abs_value": float(x.abs().max()),
            }
        )
    first = next((r["hidden_state_index"] for r in layers if r["max_abs_difference"] > 0), None)
    return {
        "note": "index 0 is the embedding output; the last index is after the final norm",
        "first_divergent_hidden_state": first,
        "layers": layers,
    }


def head_decomposition(model: Any, ids: Sequence[int], start: int) -> dict[str, Any]:
    """Body versus projection: the same hidden state projected in the model dtype and in FP32."""
    import torch
    from torch.nn.attention import SDPBackend, sdpa_kernel

    positions = len(ids) - start
    targets = torch.tensor(list(ids[start:]), device=model.device).unsqueeze(1)
    with torch.inference_mode(), sdpa_kernel(SDPBackend.MATH):
        hidden = model.model(
            torch.tensor([list(ids[:-1])], device=model.device), use_cache=False
        ).last_hidden_state[0, -positions:]
        native = model.lm_head(hidden)
        wide = torch.nn.functional.linear(hidden.float(), model.lm_head.weight.float())
    native_lp = torch.log_softmax(native, dim=-1, dtype=torch.float32).gather(1, targets)
    wide_lp = torch.log_softmax(wide, dim=-1).gather(1, targets)
    gap = (native_lp - wide_lp).abs().squeeze(1)
    return {
        "logit_dtype": str(native.dtype),
        "max_abs_logit": float(wide.abs().max()),
        "max_abs_target_logit": float(wide.gather(1, targets).abs().max()),
        "projection_rounding_max_abs_token_logprob": float(gap.max()),
        "projection_rounding_abs_sum": float(gap.sum()),
    }
