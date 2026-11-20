"""Execute or independently score the source-bound D0 diagnostic."""

from __future__ import annotations

import argparse
import hashlib
import math
import site
import time
from functools import partial
from importlib.metadata import version
from pathlib import Path
from typing import Any

from scripts import a02_dev_runtime
from scripts import a02_v3_contract as v3
from scripts import a02_v3_decision as decision
from scripts import a02_v3_precision as precision
from scripts import a02_v3_worker as worker
from scripts import a03_d0_sample as sample
from scripts.a02_v3_preflight import TOKENIZER_DIR, load_pinned_tokenizer
from scripts.a03_d0_static import common, token_replay
from scripts.a03_hf_token_mask import hf_prefix_mask
from scripts.a03_token_decoder import Grammar, TokenMask, Vocabulary

EOS = 128012
MAX_NEW = 128
CALL_SECONDS = 35.689416472975644
MAX_SESSION_SECONDS = 3600
CLEANUP_SECONDS = 120
MAX_RATE = 1.15
RESERVE_CU = 0.20
CAP_CU = 1.35
MIN_FREE_VRAM = 14 * 1024**3
MODEL_FILES = {
    "config.json": "c72b1031274ff4626e434d0019e88e95a767460135db9ee492eb80652b786af1",
    "generation_config.json": "3458d62b3f9654f4bbe285223b0f4e5a1e67cae61c92bb6aeaadf04468bf9e01",
    "model.safetensors.index.json": (
        "e3a7254c086c4a78f95ad5864f435d165ffed1ed8998326ce5107b4423c15b76"
    ),
    "model-00001-of-00002.safetensors": (
        "e5eed4113a925264c33e3cdf76cd9f547c06a207ef2270914a7274a2bf685ffd"
    ),
    "model-00002-of-00002.safetensors": (
        "6c3ad90646457295723e4da5ee8afac47006e20407b122df5174693dd8d68a43"
    ),
}
ADAPTER_FILES = {
    "adapter_config.json": "fd308f182471b62d50032f774b41c56895d3979b5ac522eb5fa7228d8bc57f6e",
    "adapter_model.safetensors": "7bda8c60c2e27206d60a41f7f454ecce721e46704e731b4f6c268d042572a6e7",
    "evaluation-binding.json": "da277638987032acad53243a65762787ddd3caf6804986a949a25048ccd25176",
    "metadata.json": "1f3bcf6abe549d855ad89d32d54b9040af4be66ee81f3115f9c308852d1d11a4",
}
RUNTIME = {
    "torch": "2.14.1+cu130",
    "transformers": "4.53.0",
    "peft": "0.16.0",
    "tokenizers": "0.21.1",
}


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_files(path: Path, files: dict[str, str]) -> None:
    for name, expected in files.items():
        if digest(path / name) != expected:
            raise ValueError(f"D0 artifact drift: {name}")


def write(path: Path, value: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as stream:
        stream.write(v3.canonical(value) + "\n")


def bound_inputs(tokenizer: Any, manifest: Path, expected: str) -> Any:
    data = manifest.read_bytes()
    if v3.sha256(data) != expected:
        raise ValueError("D0 sample digest differs")
    actual = v3.json_object(data.decode())
    rows = sample.inputs(tokenizer)
    if (
        actual["schema"] != "DYNAMISLM_A03_D0_SAMPLE_V1"
        or actual["historical_checkpoint_sha256"] != sample.CHECKPOINT_SHA256
        or actual["historical_static_receipt_sha256"] != sample.STATIC_SHA256
        or actual["historical_protocol_sha256"] != decision.protocol_sha256()
        or any(
            not expected_row.items() <= row.items()
            for row, (expected_row, _, _) in zip(actual["items"], rows, strict=True)
        )
    ):
        raise ValueError("D0 sample content differs")
    return [(row, ex, prompt) for row, (_, ex, prompt) in zip(actual["items"], rows, strict=True)]


def work_items(rows: Any) -> list[worker.WorkItem]:
    return [
        worker.WorkItem(row["example_id"], arm) for row, _, _ in rows for arm in row["arm_order"]
    ]


def generate(
    model: Any,
    tokenizer: Any,
    prompt: list[int],
    callback: Any,
    deadline: float,
) -> tuple[dict[str, Any], Any]:
    import torch  # type: ignore[import-not-found]
    from torch.nn.attention import SDPBackend, sdpa_kernel  # type: ignore[import-not-found]

    if not prompt or len(prompt) > 1536 or model.generation_config.eos_token_id != EOS:
        raise ValueError("D0 generation prompt or EOS differs")
    tensor = torch.tensor([prompt], device=model.device)

    def audit(_module: Any, _inputs: Any, logits: Any) -> None:
        if logits.dtype != torch.float32 or not torch.isfinite(logits).all().item():
            raise ValueError("D0 model logits must be finite stock FP32")
        if time.monotonic() >= deadline:
            raise TimeoutError("D0 call deadline exceeded")

    hook = model.lm_head.register_forward_hook(audit)
    started = time.monotonic()
    try:
        extra = {} if callback is None else {"prefix_allowed_tokens_fn": callback}
        with torch.inference_mode(), sdpa_kernel(SDPBackend.MATH):
            result = model.generate(
                tensor,
                attention_mask=torch.ones_like(tensor),
                max_new_tokens=MAX_NEW,
                do_sample=False,
                num_beams=1,
                pad_token_id=tokenizer.pad_token_id,
                use_cache=True,
                return_dict_in_generate=True,
                output_logits=True,
                **extra,
            )
    finally:
        hook.remove()
    full_ids = result.sequences[0].tolist()
    if tuple(result.sequences.shape[:1]) != (1,) or full_ids[: len(prompt)] != prompt:
        raise ValueError("D0 generation changed the bound input")
    ids = full_ids[len(prompt) :]
    raw = tokenizer.decode(ids, skip_special_tokens=True)
    return {
        "token_ids": ids,
        "generated_token_ids_sha256": sample.tokens_sha256(ids),
        "raw_output": raw,
        "raw_output_sha256": v3.sha256(raw.encode()),
        "eos": bool(ids and ids[-1] == EOS),
        "seconds": time.monotonic() - started,
    }, result.logits


def divergence(mask: TokenMask, grammar: Grammar, pair: dict[str, Any]) -> dict[str, Any] | None:
    native, masked = (pair[arm][0]["token_ids"] for arm in sample.ARMS)
    if native == masked:
        return None
    position = common(native, masked)
    state = grammar.start
    for token in native[:position]:
        state = mask.advance(grammar, state, token)
    return {
        "position": position,
        "prefix_token_ids": native[:position],
        "allowed_token_ids": list(mask.allowed(grammar, state)),
        "arms": {
            arm: {
                "chosen_token_id": ids[position],
                "raw_logits_fp32_by_token_id": pair[arm][1][position][0].cpu().tolist(),
            }
            for arm, ids in zip(sample.ARMS, (native, masked), strict=True)
        },
    }


def evaluate(
    model: Any,
    tokenizer: Any,
    mask: TokenMask,
    rows: Any,
    directory: Path,
    proposal_sha256: str,
    deadline: float,
) -> None:
    path = directory / "checkpoint.jsonl"
    path.touch(exist_ok=False)
    if time.monotonic() + len(work_items(rows)) * CALL_SECONDS >= deadline:
        raise TimeoutError("D0 startup left insufficient time for the registered workload")
    items = iter(work_items(rows))
    head = worker.GENESIS
    seq = 0
    for row, example, prompt in rows:
        grammar = Grammar(example["request"])
        ids = prompt["prompt_token_ids"]
        if time.monotonic() + 2 * CALL_SECONDS >= deadline:
            raise TimeoutError("D0 pair has insufficient generation time")
        pair = {}
        for arm in row["arm_order"]:
            item = next(items)
            callback = partial(hf_prefix_mask, mask, grammar, ids) if arm == "C1" else None
            record, logits = generate(
                model, tokenizer, ids, callback, min(deadline, time.monotonic() + CALL_SECONDS)
            )
            pair[arm] = (record, logits)
            head = worker._append(
                path,
                {
                    "schema": worker.CHECKPOINT_SCHEMA,
                    "seq": seq,
                    "prev_sha256": head,
                    "item": item.id,
                    "record": {
                        **record,
                        "proposal_sha256": proposal_sha256,
                        "prompt_token_ids_sha256": row["prompt_token_ids_sha256"],
                    },
                },
            )
            seq += 1
            if not record["eos"] or record["seconds"] > CALL_SECONDS:
                raise ValueError(f"D0 stopped on EOS or timing failure: {item.id}")
        n = pair["N"][0]
        native_ok, intervention = token_replay(mask, grammar, n["token_ids"], n["raw_output"])
        difference = divergence(mask, grammar, pair)
        if difference is not None:
            write(
                directory / f"divergence-{seq // 2}.json",
                {
                    "example_id": row["example_id"],
                    "native_grammar_compatible": native_ok,
                    "native_first_masked_token": intervention,
                    **difference,
                },
            )
        if (difference is not None and native_ok) or (seq == 2 and (difference or not native_ok)):
            raise ValueError(f"D0 stopped on divergence or failed smoke: {row['example_id']}")
        c1 = pair["C1"][0]
        if not token_replay(mask, grammar, c1["token_ids"], c1["raw_output"])[0]:
            raise ValueError("D0 C1 exact token replay failed")
        v3.parse_action(c1["raw_output"], grammar.ids)


def score(tokenizer: Any, mask: TokenMask, rows: Any, path: Path, proposal_sha256: str) -> Any:
    state = worker.read_checkpoint(path, work_items(rows))
    if state["torn_tail_discarded"]:
        raise ValueError("D0 checkpoint has a torn tail")
    results: dict[str, Any] = {}
    for entry in state["entries"]:
        index, arm_index = divmod(entry["seq"], 2)
        row, example, _ = rows[index]
        arm = row["arm_order"][arm_index]
        rec = entry["record"]
        ids = rec["token_ids"]
        raw = tokenizer.decode(ids, skip_special_tokens=True)
        eos = bool(ids and ids[-1] == EOS)
        if (
            rec["proposal_sha256"] != proposal_sha256
            or rec["prompt_token_ids_sha256"] != row["prompt_token_ids_sha256"]
            or not 0 < len(ids) <= MAX_NEW
            or EOS in ids[:-1]
            or rec["eos"] is not eos
            or raw != rec["raw_output"]
            or v3.sha256(raw.encode()) != rec["raw_output_sha256"]
            or sample.tokens_sha256(ids) != rec["generated_token_ids_sha256"]
            or not math.isfinite(rec["seconds"])
            or rec["seconds"] < 0
        ):
            raise ValueError(f"D0 output evidence differs: {entry['item']}")
        grammar = Grammar(example["request"])
        accepted, intervention = token_replay(mask, grammar, ids, raw)
        try:
            action = v3.parse_action(raw, grammar.ids)
        except ValueError:
            action = None
        scored = results.setdefault(row["example_id"], {"family": row["family"]})
        scored[arm] = {
            **rec,
            "parse_valid": action is not None,
            "syntax_valid": eos and action is not None,
            "exact_intent": eos
            and action is not None
            and v3.normalize_action(action) == example["gold_action"],
            "grammar_accepted": accepted,
            "first_masked_token": intervention,
            "historical_bytes_equal": rec["raw_output_sha256"] == row["raw_output_sha256"],
            "historical_tokens_equal": rec["generated_token_ids_sha256"]
            == row["generated_token_ids_sha256"],
        }
        if all(a in scored for a in sample.ARMS):
            scored["bytes_equal"] = scored["N"]["raw_output"] == scored["C1"]["raw_output"]
            scored["tokens_equal"] = scored["N"]["token_ids"] == scored["C1"]["token_ids"]
    return {"checkpoint_sha256": digest(path), "checkpoint_head": state["head"], "pairs": results}


def run(directory: Path, proposal_sha256: str, seconds: float) -> None:
    import torch
    from huggingface_hub import snapshot_download
    from peft import PeftModel  # type: ignore[import-not-found]

    if not 0 < seconds <= MAX_SESSION_SECONDS - CLEANUP_SECONDS:
        raise ValueError("D0 remote deadline differs")
    deadline = time.monotonic() + seconds
    proposal_path = directory / "proposal.json"
    if digest(proposal_path) != proposal_sha256:
        raise ValueError("D0 proposal digest differs")
    proposal = v3.json_object(proposal_path.read_text())
    model_id = decision.load_protocol()["candidate_model"]
    if (
        proposal["model"] != model_id
        or proposal["model_files"] != MODEL_FILES
        or proposal["adapter_files"] != ADAPTER_FILES
    ):
        raise ValueError("D0 proposal model identity differs")
    versions = {name: version(name) for name in RUNTIME}
    if versions != RUNTIME:
        raise ValueError(f"D0 runtime versions differ: {versions}")
    inventory = a02_dev_runtime.inventory(torch, Path(site.getsitepackages()[0]))
    qualification = a02_dev_runtime.qualify(inventory, a02_dev_runtime.cuda_smoke(torch, inventory))
    if not qualification["qualified"] or torch.cuda.mem_get_info()[0] < MIN_FREE_VRAM:
        raise ValueError(f"D0 T4 qualification failed: {qualification}")
    adapter = directory / "adapter"
    verify_files(adapter, ADAPTER_FILES)
    tokenizer_files = v3.load_profile()["tokenizer"]["files"]
    snapshot = Path(
        snapshot_download(
            model_id["id"],
            revision=model_id["revision"],
            allow_patterns=[*MODEL_FILES, *tokenizer_files],
        )
    )
    verify_files(snapshot, MODEL_FILES)
    tokenizer = load_pinned_tokenizer(snapshot)
    mask = TokenMask(Vocabulary.from_pinned(snapshot))
    if mask.eos != EOS:
        raise ValueError("D0 pinned tokenizer EOS differs")
    rows = bound_inputs(tokenizer, directory / "sample.json", proposal["sample_sha256"])
    model = PeftModel.from_pretrained(
        precision.load_model(snapshot, "float32"), adapter, is_trainable=False
    ).eval()
    # The historical snapshot derived generation defaults from config.json.
    model.generation_config = type(model.generation_config).from_model_config(model.config)
    if any(p.requires_grad or p.device.type != "cuda" for p in model.parameters()):
        raise ValueError("D0 model must be frozen and resident on CUDA")
    if model.config._attn_implementation != "sdpa":
        raise ValueError("D0 runtime did not select SDPA")
    audit = precision.PrecisionAudit(model, "float32")
    write(
        directory / "runtime.json",
        {
            "proposal_sha256": proposal_sha256,
            "versions": versions,
            "qualification": qualification,
            "parameters": audit.identity,
            "attention_implementation": model.config._attn_implementation,
            "generation_config": model.generation_config.to_dict(),
            "model_files": MODEL_FILES,
            "adapter_files": ADAPTER_FILES,
            "tokenizer_files": tokenizer_files,
        },
    )
    completed = False
    try:
        evaluate(model, tokenizer, mask, rows, directory, proposal_sha256, deadline)
        completed = True
    finally:
        write(
            directory / "terminal.json",
            {
                "completed": completed,
                "proposal_sha256": proposal_sha256,
                "checkpoint_sha256": digest(directory / "checkpoint.jsonl"),
                "precision": audit.report() if audit.logit_dtypes else audit.identity,
                "peak_cuda_bytes": torch.cuda.max_memory_reserved(),
                "diagnostics": {p.name: digest(p) for p in directory.glob("divergence-*.json")},
            },
        )
        audit.close()


def score_directory(directory: Path, proposal_sha256: str) -> None:
    proposal_path = directory / "proposal.json"
    if digest(proposal_path) != proposal_sha256:
        raise ValueError("D0 scorer proposal digest differs")
    proposal = v3.json_object(proposal_path.read_text())
    rows = bound_inputs(
        load_pinned_tokenizer(), directory / "sample.json", proposal["sample_sha256"]
    )
    scored = score(
        load_pinned_tokenizer(),
        TokenMask(Vocabulary.from_pinned(TOKENIZER_DIR)),
        rows,
        directory / "checkpoint.jsonl",
        proposal_sha256,
    )

    runtime = v3.json_object((directory / "runtime.json").read_text())
    if (
        runtime["proposal_sha256"] != proposal_sha256
        or runtime["model_files"] != MODEL_FILES
        or runtime["adapter_files"] != ADAPTER_FILES
        or runtime["tokenizer_files"] != v3.load_profile()["tokenizer"]["files"]
        or runtime["versions"] != RUNTIME
        or not runtime["qualification"]["qualified"]
    ):
        raise ValueError("D0 runtime evidence differs")
    complete = False
    terminal_path = directory / "terminal.json"
    if terminal_path.exists():
        terminal = v3.json_object(terminal_path.read_text())
        if (
            terminal["proposal_sha256"] != proposal_sha256
            or terminal["checkpoint_sha256"] != scored["checkpoint_sha256"]
            or terminal["diagnostics"]
            != {p.name: digest(p) for p in directory.glob("divergence-*.json")}
        ):
            raise ValueError("D0 terminal digest differs")
        complete = terminal["completed"] is True
    pairs = list(scored["pairs"].values())
    counts = {}
    for arm in sample.ARMS:
        records = [pair[arm] for pair in pairs if arm in pair]
        counts[arm] = {
            "outputs": len(records),
            **{
                key: sum(record[key] for record in records)
                for key in (
                    "syntax_valid",
                    "exact_intent",
                    "historical_bytes_equal",
                    "historical_tokens_equal",
                )
            },
            "seconds": sum(record["seconds"] for record in records),
        }
    complete = complete and all(counts[arm]["outputs"] == len(rows) for arm in sample.ARMS)
    complete = complete and all(
        "C1" in pair
        and pair["C1"]["grammar_accepted"]
        and pair["C1"]["syntax_valid"]
        and pair["N"]["eos"]
        and (pair["tokens_equal"] or not pair["N"]["grammar_accepted"])
        for pair in pairs
    )
    write(
        directory / "scores.json",
        {
            **scored,
            "complete": complete,
            "counts": counts,
            "paired_bytes_equal": sum(pair.get("bytes_equal", False) for pair in pairs),
            "paired_tokens_equal": sum(pair.get("tokens_equal", False) for pair in pairs),
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("proposal_sha256")
    parser.add_argument("--score", action="store_true")
    parser.add_argument("--seconds", type=float)
    args = parser.parse_args()
    if args.score:
        score_directory(args.directory, args.proposal_sha256)
    elif args.seconds is not None:
        run(args.directory, args.proposal_sha256, args.seconds)
    else:
        parser.error("specify --seconds or --score")


if __name__ == "__main__":
    main()
