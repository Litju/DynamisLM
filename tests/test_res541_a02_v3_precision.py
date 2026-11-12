"""Selected arithmetic applies to one model shared by both scoring arms (RES-541)."""

from __future__ import annotations

from collections.abc import Iterator
from copy import deepcopy
from typing import Any

import pytest
from scripts import a02_v3_precision as precision


@pytest.fixture(autouse=True, scope="module")
def bounded_threads() -> Iterator[None]:
    torch = pytest.importorskip("torch")
    previous = torch.get_num_threads()
    torch.set_num_threads(min(previous, 4))
    yield
    torch.set_num_threads(previous)


def test_unknown_precision_fails_before_model_loading() -> None:
    with pytest.raises(ValueError, match="precision"):
        precision.configure("bfloat16")


def test_fp32_disables_tf32_and_rejects_autocast() -> None:
    torch = pytest.importorskip("torch")
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True
    assert precision.configure("float32") == torch.float32
    assert not torch.backends.cuda.matmul.allow_tf32
    assert not torch.backends.cudnn.allow_tf32
    assert torch.get_float32_matmul_precision() == "highest"
    with torch.autocast("cpu"):
        with pytest.raises(ValueError, match="autocast"):
            precision.configure("float32")


@pytest.mark.parametrize("selected", ["float16", "float32"])
def test_loaded_precision_and_both_scorers(tmp_path: Any, selected: str) -> None:
    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")
    from scripts import a02_v3_constrained as constrained

    config = transformers.SmolLM3Config(
        vocab_size=128,
        hidden_size=32,
        intermediate_size=64,
        num_hidden_layers=4,
        num_attention_heads=4,
        num_key_value_heads=2,
        pad_token_id=0,
        bos_token_id=None,
        eos_token_id=None,
    )
    torch.manual_seed(541)
    lm = transformers.SmolLM3ForCausalLM(config).eval()
    lm.save_pretrained(tmp_path)
    # CPU device_map loading needs the same pinned accelerate present in the remote environment.
    if selected == "float32":
        pytest.importorskip("accelerate")
    model = precision.load_model(tmp_path, selected, device="cpu")
    assert precision.verify_parameters(model, selected)["parameter_dtypes"] == [f"torch.{selected}"]
    audit = precision.PrecisionAudit(model, selected)
    observed = []
    hook = model.lm_head.register_forward_hook(lambda m, a, out: observed.append(str(out.dtype)))
    try:
        ids = [1, 2, 3, 4, 5]
        cached = constrained.CachedSequenceLogprob(constrained.HFIncrementalBackend(model))
        assert abs(cached(ids, 3) - constrained.hf_sequence_logprob(model)(ids, 3)) < 0.001
        assert observed and set(observed) == {f"torch.{selected}"}
        assert audit.report()["logit_dtypes"] == [f"torch.{selected}"]
        if selected == "float32":
            torch.backends.cuda.matmul.allow_tf32 = True
            with pytest.raises(ValueError, match="settings changed"):
                model(torch.tensor([[1, 2]]))
            precision.configure("float32")
            with pytest.raises(ValueError, match="intermediate"):
                audit._observe(model, (), torch.ones(1, dtype=torch.float16))
        audit.close()
        mixed = deepcopy(model)
        mixed.lm_head.to(torch.float64)
        with pytest.raises(ValueError, match="parameter precision"):
            precision.verify_parameters(mixed, selected)
    finally:
        audit.close()
        hook.remove()
