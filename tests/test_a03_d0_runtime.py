import time
from functools import partial
from pathlib import Path
from typing import Any

import pytest
from scripts import a02_v3_contract as v3
from scripts import a02_v3_decision as decision
from scripts import a03_d0_runtime as runtime
from scripts.a02_v3_preflight import TOKENIZER_DIR, load_pinned_tokenizer
from scripts.a03_d0_static import token_replay
from scripts.a03_hf_token_mask import hf_prefix_mask
from scripts.a03_token_decoder import Grammar, TokenMask, Vocabulary


def test_artifact_hash_gate_rejects_changed_bytes(tmp_path: Path) -> None:
    asset = tmp_path / "asset"
    asset.write_bytes(b"before")
    expected = {asset.name: runtime.digest(asset)}
    runtime.verify_files(tmp_path, expected)
    asset.write_bytes(b"after")
    with pytest.raises(ValueError, match="artifact drift"):
        runtime.verify_files(tmp_path, expected)


def test_real_transformers_greedy_callback_eos_and_logits() -> None:
    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")
    if not TOKENIZER_DIR.is_dir():
        pytest.skip("pinned tokenizer files are required")
    assert transformers.__version__ == "4.53.0"
    tokenizer = load_pinned_tokenizer()
    mask = TokenMask(Vocabulary.from_pinned(TOKENIZER_DIR))
    example = decision.heldout_examples(decision.load_protocol())[0]
    grammar = Grammar(example["request"])
    target = example["target_text"]
    path = [*tokenizer.encode(target, add_special_tokens=False), runtime.EOS]
    model = transformers.AutoModelForCausalLM.from_config(
        transformers.SmolLM3Config(
            vocab_size=128256,
            hidden_size=16,
            intermediate_size=32,
            num_attention_heads=2,
            num_key_value_heads=1,
            num_hidden_layers=1,
            max_window_layers=1,
            eos_token_id=runtime.EOS,
        )
    ).eval()
    prompt = [10, 11]
    callback = partial(hf_prefix_mask, mask, grammar, prompt)
    step = 0
    preferred = path[0]

    def scripted(_module: Any, _inputs: Any, output: Any) -> Any:
        nonlocal step
        logits = torch.zeros_like(output)
        logits[..., path[step]] = 1
        if step == 0:
            logits[..., preferred] = 2
        step += 1
        return logits

    threads = torch.get_num_threads()
    torch.set_num_threads(1)
    hook = model.lm_head.register_forward_hook(scripted)
    try:
        native = runtime.generate(model, tokenizer, prompt, None, time.monotonic() + 15)
        step = 0
        masked = runtime.generate(model, tokenizer, prompt, callback, time.monotonic() + 15)
        assert native[0]["token_ids"] == masked[0]["token_ids"] == path
        assert native[0]["raw_output"].encode() == target.encode()
        assert token_replay(mask, grammar, path, target)[0]
        assert runtime.divergence(mask, grammar, {"N": native, "C1": masked}) is None
        assert all(torch.equal(n, c) for n, c in zip(native[1], masked[1], strict=True))
        step = 0
        preferred = tokenizer.pad_token_id
        changed = runtime.generate(model, tokenizer, prompt, None, time.monotonic() + 15)
        step = 0
        corrected = runtime.generate(model, tokenizer, prompt, callback, time.monotonic() + 15)
        assert corrected[0]["token_ids"] == path
        assert torch.equal(changed[1][0], corrected[1][0])
        difference = runtime.divergence(mask, grammar, {"N": changed, "C1": corrected})
        assert difference is not None and difference["position"] == 0
        assert preferred not in difference["allowed_token_ids"]
        assert difference["arms"]["N"]["raw_logits_fp32_by_token_id"][preferred] == 2
        assert v3.normalize_action(v3.parse_action(target, grammar.ids)) == example["gold_action"]
    finally:
        hook.remove()
        torch.set_num_threads(threads)
