"""Real Transformers CPU qualification of the V3 constrained decoder (RES-541).

Uses an actual SmolLM3ForCausalLM (tiny, randomly initialized, mixing RoPE and NoPE layers like
the pinned model) and an in-test byte-level BPE tokenizer whose merges cross the action
prefix/option boundary. No language model is mocked. Requires the ``decoder-check`` group.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from copy import deepcopy
from typing import Any

import pytest

torch = pytest.importorskip("torch")
transformers = pytest.importorskip("transformers")
tokenizers = pytest.importorskip("tokenizers")

from scripts import a02_v3_constrained as constrained  # noqa: E402
from scripts import a02_v3_contract as v3  # noqa: E402
from scripts import a02_v3_gold as gold  # noqa: E402
from scripts import a02_v3_score as score  # noqa: E402
from scripts import a02_v3_synthetic as synthetic  # noqa: E402

CASES = score._cases()


def _corpus() -> list[str]:
    texts = []
    for case in CASES.values():
        texts.append(v3.user_message(case["request"]))
        texts.append(v3.format_action(gold.derive_gold(case["request"])["action"]))
    for example in synthetic.generate("TRAIN", 7, 56):
        texts.append(v3.user_message(example["request"]))
        texts.append(example["target_text"])
    return texts


@pytest.fixture(scope="module")
def tokenizer() -> Any:
    model = tokenizers.models.BPE()
    tok = tokenizers.Tokenizer(model)
    tok.pre_tokenizer = tokenizers.pre_tokenizers.ByteLevel(add_prefix_space=False)
    tok.decoder = tokenizers.decoders.ByteLevel()
    trainer = tokenizers.trainers.BpeTrainer(
        vocab_size=640,
        initial_alphabet=tokenizers.pre_tokenizers.ByteLevel.alphabet(),
        show_progress=False,
    )
    tok.train_from_iterator(_corpus(), trainer=trainer)
    return tok


@pytest.fixture(scope="module")
def model(tokenizer: Any) -> Any:
    torch.manual_seed(541)
    config = transformers.SmolLM3Config(
        vocab_size=tokenizer.get_vocab_size(),
        hidden_size=48,
        intermediate_size=96,
        num_hidden_layers=4,
        num_attention_heads=4,
        num_key_value_heads=2,
        max_position_embeddings=8192,
        pad_token_id=0,
        bos_token_id=None,
        eos_token_id=None,
    )
    assert config.no_rope_layers == [1, 1, 1, 0]  # RoPE and NoPE layers both present
    lm = transformers.SmolLM3ForCausalLM(config).to(torch.float32)
    lm.eval()
    return lm


def _encode(tokenizer: Any) -> Any:
    def encode(text: str) -> list[int]:
        ids: list[int] = tokenizer.encode(text).ids
        return ids

    return encode


def _decode(tokenizer: Any, model: Any, case_id: str, scorer: Any) -> dict[str, Any]:
    request = CASES[case_id]["request"]
    encode = _encode(tokenizer)
    return constrained.decode(
        request=request,
        prompt_ids=encode("<system>" + v3.user_message(request) + "<assistant>"),
        encode=encode,
        chooser=constrained.model_chooser(scorer),
    )


@pytest.mark.parametrize("case_id", ["a02-unsupported-causality", "a02-missing-evidence"])
def test_cached_and_uncached_real_model_scores_and_choices_agree(
    tokenizer: Any, model: Any, case_id: str
) -> None:
    uncached = _decode(tokenizer, model, case_id, constrained.hf_sequence_logprob(model))
    scorer = constrained.CachedSequenceLogprob(constrained.HFIncrementalBackend(model))
    cached = _decode(tokenizer, model, case_id, scorer)
    assert cached["action"] == uncached["action"]
    assert cached["text"] == uncached["text"]
    flat_cached = [v for c in cached["choices"] for v in c["scores"]]
    flat_uncached = [v for c in uncached["choices"] for v in c["scores"]]
    assert flat_cached == pytest.approx(flat_uncached, abs=2e-4)
    # The real tokenizer merges across the prefix/option boundary, so the shared start
    # backs off into already-cached tokens and the cache must be rolled back.
    assert cached["max_rescored_prefix_tokens"] >= 1
    prompt = len(_encode(tokenizer)("<system>" + v3.user_message(CASES[case_id]["request"])))
    assert scorer.fed_tokens < cached["scorer_calls"] * prompt
    assert v3.parse_action(cached["text"], v3.observation_ids(CASES[case_id]["request"]))


def _full_logprobs(model: Any, ids: Sequence[int]) -> list[float]:
    with torch.inference_mode():
        logits = model(torch.tensor([list(ids)])).logits[0, :-1].float()
    logp = torch.log_softmax(logits, dim=-1)
    return [float(v) for v in logp.gather(1, torch.tensor(ids[1:]).unsqueeze(1)).squeeze(1)]


def test_backend_cache_positions_match_full_forward_after_crop_and_refeed(
    tokenizer: Any, model: Any
) -> None:
    ids = _encode(tokenizer)(v3.user_message(CASES["a02-valid-numerical"]["request"]))[:120]
    full = _full_logprobs(model, ids)
    backend = constrained.HFIncrementalBackend(model)
    # Feed in three chunks, cropping back into the cache between them.
    first = backend.logprobs(0, ids[:60], ids[1:61])
    assert first == pytest.approx(full[:60], abs=2e-4)
    backend.logprobs(60, ids[60:100], ids[61:101])
    rolled = backend.logprobs(40, ids[40:119], ids[41:120])
    assert rolled == pytest.approx(full[40:119], abs=2e-4)


def test_cached_scorer_survives_divergent_prefix_on_real_model(tokenizer: Any, model: Any) -> None:
    encode = _encode(tokenizer)
    a = encode(v3.user_message(CASES["a02-valid-numerical"]["request"]))[:90]
    b = a[:30] + encode("divergent tail with other tokens")[:25]
    scorer = constrained.CachedSequenceLogprob(constrained.HFIncrementalBackend(model))
    reference = constrained.hf_sequence_logprob(model)
    for ids, start in ((a, 70), (b, 40), (a, 50), (a, 85)):
        assert scorer(ids, start) == pytest.approx(reference(ids, start), abs=5e-4)


def test_half_precision_scores_use_math_attention_and_only_scored_logits(model: Any) -> None:
    from torch.nn.attention import SDPBackend, sdpa_kernel  # type: ignore[import-not-found]

    lm = deepcopy(model).to(torch.float16)
    ids = [i % lm.config.vocab_size for i in range(120)]
    calls = []

    def observe(module: Any, args: Any, kwargs: Any, output: Any) -> None:
        calls.append(
            {
                "input_tokens": args[0].shape[1],
                "logit_tokens": output.logits.shape[1],
                "use_cache": kwargs["use_cache"],
                "math": torch.backends.cuda.math_sdp_enabled(),
                "flash": torch.backends.cuda.flash_sdp_enabled(),
                "efficient": torch.backends.cuda.mem_efficient_sdp_enabled(),
            }
        )

    hook = lm.register_forward_hook(observe, with_kwargs=True)
    try:
        reference = constrained.hf_sequence_logprob(lm)(ids, 100)
        cached = constrained.CachedSequenceLogprob(constrained.HFIncrementalBackend(lm))
        assert cached(ids, 100) == pytest.approx(reference, abs=1e-3)
        changed = [*ids[:-3], 3, 2, 1]
        assert cached(changed, 100) == pytest.approx(
            constrained.hf_sequence_logprob(lm)(changed, 100), abs=1e-3
        )
    finally:
        hook.remove()
    assert all(c["logit_tokens"] == 20 for c in calls)
    assert all(c["math"] and not c["flash"] and not c["efficient"] for c in calls)
    assert calls[0]["input_tokens"] == 119 and calls[0]["use_cache"] is False
    assert calls[1]["input_tokens"] == 119 and calls[1]["use_cache"] is True
    assert calls[2]["input_tokens"] < 119 and calls[2]["use_cache"] is True
    # Independently score the complete context and vocabulary to check suffix indexing.
    with torch.inference_mode(), sdpa_kernel(SDPBackend.MATH):
        logits = lm(torch.tensor([ids]), use_cache=False).logits[0, :-1].float()
    full = torch.log_softmax(logits, dim=-1).gather(1, torch.tensor(ids[1:]).unsqueeze(1))
    assert reference == pytest.approx(float(full[99:].sum(dtype=torch.float64)), abs=1e-3)


@pytest.mark.parametrize("start", [-1, 0, 3])
def test_reference_rejects_unconditioned_or_empty_spans(model: Any, start: int) -> None:
    with pytest.raises(ValueError, match="scored span"):
        constrained.hf_sequence_logprob(model)([1, 2, 3], start)


@pytest.mark.parametrize("targets", [[], [1, 2, 3]])
def test_incremental_backend_rejects_targets_outside_fed_suffix(model: Any, targets: Any) -> None:
    with pytest.raises(ValueError, match="scored targets"):
        constrained.HFIncrementalBackend(model).logprobs(0, [1, 2], targets)


def test_explicit_attention_mask_and_cache_position_do_not_change_scores(
    tokenizer: Any, model: Any
) -> None:
    """The backend relies on Transformers inferring positions for an unpadded batch of one."""
    ids = _encode(tokenizer)(v3.user_message(CASES["a02-cross-source"]["request"]))[:80]
    implicit = constrained.HFIncrementalBackend(model)
    implicit.logprobs(0, ids[:50], ids[1:51])
    tail = implicit.logprobs(50, ids[50:79], ids[51:80])
    with torch.inference_mode():
        head = model(
            torch.tensor([ids[:50]]),
            attention_mask=torch.ones(1, 50, dtype=torch.long),
            cache_position=torch.arange(50),
            use_cache=True,
        )
        out = model(
            torch.tensor([ids[50:79]]),
            past_key_values=head.past_key_values,
            attention_mask=torch.ones(1, 79, dtype=torch.long),
            cache_position=torch.arange(50, 79),
            use_cache=True,
        )
    logp = torch.log_softmax(out.logits[0].float(), dim=-1)
    explicit = [float(v) for v in logp.gather(1, torch.tensor(ids[51:80]).unsqueeze(1)).squeeze(1)]
    assert tail == pytest.approx(explicit, abs=2e-4)


def test_decoded_choices_are_reproducible_and_disclose_short_option_bias(
    tokenizer: Any, model: Any
) -> None:
    case_id = "a02-valid-numerical"
    one = _decode(tokenizer, model, case_id, constrained.hf_sequence_logprob(model))
    two = _decode(tokenizer, model, case_id, constrained.hf_sequence_logprob(model))
    assert json.dumps(one["choices"]) == json.dumps(two["choices"])
    # Summed log-probabilities penalize longer options: on a random model the list close
    # usually beats any item. This is why constrained errors are decoder-and-model choices.
    closes = [c for c in one["choices"] if c["options"][-1] == "]" and len(c["options"]) > 1]
    assert closes


CHAT_TEMPLATE = (
    "{% for m in messages %}<|{{ m.role }}|>{{ m.content }}{% endfor %}"
    "{% if xml_tools %}<|tools|>{{ xml_tools | tojson }}{% endif %}<|assistant|>"
)


@pytest.fixture(scope="module")
def chat_tokenizer() -> Any:
    from scripts import a02_v3_decision as decision

    protocol = decision.load_protocol()
    corpus = _corpus()
    corpus.append(v3.ACTION_PROMPT_PATH.read_text(encoding="utf-8"))
    corpus.append(json.dumps(v3.tool_schema()))
    for example in decision.heldout_examples(protocol)[:28]:
        corpus.append(v3.user_message(example["request"]))
        corpus.append(example["target_text"])
    model = tokenizers.models.BPE()
    tok = tokenizers.Tokenizer(model)
    tok.pre_tokenizer = tokenizers.pre_tokenizers.ByteLevel(add_prefix_space=False)
    tok.decoder = tokenizers.decoders.ByteLevel()
    trainer = tokenizers.trainers.BpeTrainer(
        vocab_size=6000,
        initial_alphabet=tokenizers.pre_tokenizers.ByteLevel.alphabet(),
        show_progress=False,
    )
    tok.train_from_iterator(corpus * 3, trainer=trainer)
    fast = transformers.PreTrainedTokenizerFast(tokenizer_object=tok)
    fast.chat_template = CHAT_TEMPLATE
    return fast


def test_hf_worker_backend_runs_resumable_worker_end_to_end(
    chat_tokenizer: Any, tmp_path: Any
) -> None:
    from scripts import a02_v3_decision as decision
    from scripts import a02_v3_worker as worker

    torch.manual_seed(7)
    config = transformers.SmolLM3Config(
        vocab_size=len(chat_tokenizer),
        hidden_size=32,
        intermediate_size=64,
        num_hidden_layers=4,
        num_attention_heads=4,
        num_key_value_heads=2,
        max_position_embeddings=8192,
        pad_token_id=0,
        bos_token_id=None,
        eos_token_id=None,
    )
    lm = transformers.SmolLM3ForCausalLM(config).to(torch.float32)
    lm.eval()
    protocol = decision.load_protocol()
    backend = worker.HFWorkerBackend(lm, chat_tokenizer, protocol["candidate_model"])
    items = worker.work_items(protocol)[:5]  # qualification + two examples, both arms
    path = tmp_path / "checkpoint.jsonl"
    costs = {"QUALIFICATION": 1.0, "ZERO_SHOT_UNCONSTRAINED": 1.0, "ZERO_SHOT_CONSTRAINED": 1.0}
    first = worker.run_worker(
        protocol=protocol,
        items=items,
        checkpoint=path,
        backend=backend,
        deadline=float("inf"),
        item_cost_bounds=costs,
        stop_after=2,
    )
    assert first["status"] == "STOPPED" and first["committed"] == 2
    done = worker.run_worker(
        protocol=protocol,
        items=items,
        checkpoint=path,
        backend=backend,
        deadline=float("inf"),
        item_cost_bounds=costs,
    )
    assert done["status"] == "COMPLETE"
    entries = worker.read_checkpoint(path, items)["entries"]
    qualification = entries[0]["record"]
    assert qualification["passed"] is True
    assert all(r["options_scored"] > 0 for r in qualification["examples"])
    native = entries[1]["record"]
    assert native["decoder"] == "native" and native["truncated"] is True  # random LM, no EOS
    constrained_record = entries[2]["record"]
    example = decision.heldout_examples(protocol)[0]
    assert v3.parse_action(constrained_record["raw_output"], v3.observation_ids(example["request"]))
