"""CPU-only RES-402 development writer/loader; no model weights or training steps."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from dynamislm.serialization import canonical_bytes, canonical_hash, from_canonical_json
from dynamislm.training_data.admission import Purpose, Request, Source, SourceClass
from dynamislm.training_data.processing import (
    TRANSFORM,
    authorize_sft_corpus_bytes,
    process_training_inputs,
    require_external,
    sha256,
)
from dynamislm.training_data.scientific_sft import (
    DevelopmentSet,
    ScientificExample,
    generate_development_set,
    validate_development_set,
    validate_example,
)

MODEL = "HuggingFaceTB/SmolLM3-3B"
MODEL_REVISION = "a07cc9a04f16550a088caea529712d1d335b0ac1"
# Exact offline snapshot inspected for RES-402; no template is synthesized or downloaded.
TOKENIZER_PINS = {
    "tokenizer.json": "7b6a500b662a34eb3f0374db856ba4ad7de4c81040571d78dc0d357238930005",
    "tokenizer_config.json": "59a64b39f05ee0acf7479bbccf99a44d9e481c1a4a494eb03838ae3c35eb29be",
    "chat_template.jinja": "3e0e275a527f249670056e0078e474eadbdd007c134b4fdfae5a7b3089702814",
    "special_tokens_map.json": "12403efb970f069ba62ddf3b66166a27254be4a198166b61ad1ee604bd3a4515",
}


def offline_tokenizer_smoke(dataset: DevelopmentSet, directory: Path | None) -> dict[str, Any]:
    if directory is None:
        return {
            "status": "PENDING",
            "model": MODEL,
            "revision": MODEL_REVISION,
            "reason": "optional offline snapshot/runtime not selected",
        }
    directory = require_external(directory)
    if {p.name for p in directory.iterdir()} != set(TOKENIZER_PINS):
        raise ValueError("unrecognized offline tokenizer resource set")
    for name, digest in TOKENIZER_PINS.items():
        if sha256((directory / name).read_bytes()) != "sha256:" + digest:
            raise ValueError("unrecognized offline tokenizer resource")
    try:
        transformers = importlib.import_module("transformers")
    except ImportError as exc:
        raise ValueError("offline tokenizer runtime unavailable; no downloads allowed") from exc
    tokenizer = transformers.AutoTokenizer.from_pretrained(
        str(directory),
        local_files_only=True,
        trust_remote_code=False,
    )
    lengths = []
    token_hashes = []
    for example in dataset.examples:
        messages = json.loads(example.messages_json)
        tokens = tokenizer.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=False, enable_thinking=False
        )
        if not isinstance(tokens, list) or not tokens or any(type(t) is not int for t in tokens):
            raise ValueError("invalid tokenizer response")
        if len(tokens) > 65536:
            raise ValueError("model native context exceeded; truncation forbidden")
        lengths.append(len(tokens))
        token_hashes.append(canonical_hash(tokens))
    return {
        "status": "OFFLINE_TOKENIZER_ONLY",
        "model": MODEL,
        "revision": MODEL_REVISION,
        "files": TOKENIZER_PINS,
        "token_lengths": lengths,
        "token_ids_sha256": canonical_hash(token_hashes),
        "model_weights_loaded": False,
    }


def load_development_bytes(raw: bytes) -> DevelopmentSet:
    """Inspection of this closed original catalogue confers no source or corpus rights."""
    if len(raw) > 16_000_000:
        raise ValueError("development artifact exceeds bounded catalogue size")
    dataset = from_canonical_json(raw.decode("utf-8"), DevelopmentSet)
    validate_development_set(dataset)
    if raw != canonical_bytes(dataset):
        raise ValueError("noncanonical development bytes")
    return dataset


def cpu_batches(dataset: DevelopmentSet, batch_size: int = 4) -> tuple[tuple[str, ...], ...]:
    validate_development_set(dataset)
    if type(batch_size) is not int or not 1 <= batch_size <= 39:
        raise ValueError("bounded CPU batch size required")
    return tuple(
        tuple(e.messages_json for e in dataset.examples[i : i + batch_size])
        for i in range(0, len(dataset.examples), batch_size)
    )


def write_development_artifacts(
    dataset: DevelopmentSet, output_root: Path, *, tokenizer_directory: Path | None = None
) -> dict[str, Any]:
    root = require_external(output_root)
    raw = canonical_bytes(dataset)
    loaded = load_development_bytes(raw)
    batches = cpu_batches(loaded)
    tokenization = offline_tokenizer_smoke(loaded, tokenizer_directory)
    receipt = {
        "schema": "RES402-CPU-RECEIPT-1",
        "scope": "DEVELOPMENT_ONLY",
        "qualification_scope": "BATCH_LOCAL_ONLY",
        "training_authorized": False,
        "corpus_qualified": False,
        "seed": dataset.seed,
        "examples": len(dataset.examples),
        "valid_numerical": sum(not e.response.refusal_codes for e in dataset.examples),
        "refusals": sum(bool(e.response.refusal_codes) for e in dataset.examples),
        "tool_use": sum(e.call is not None for e in dataset.examples),
        "cpu_batches": len(batches),
        "batch_format_sha256": canonical_hash(batches),
        "examples_sha256": sha256(raw),
        "tokenizer": tokenization,
        "scientific_replay": "PASS",
        "provenance": "SYNTHETIC_ORIGINAL_ONLY",
        "registry_sha256": dataset.examples[0].registry_sha256,
        "implementation_sha256": dataset.examples[0].implementation_sha256,
    }
    destination = root / canonical_hash(receipt).removeprefix("sha256:")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    staging = Path(tempfile.mkdtemp(prefix=".res402-", dir=root))
    try:
        (staging / "examples.json").write_bytes(raw)
        (staging / "receipt.json").write_bytes(canonical_bytes(receipt))
        if destination.exists():
            if destination.is_symlink() or {p.name for p in destination.iterdir()} != {
                "examples.json",
                "receipt.json",
            }:
                raise ValueError("existing development artifact changed")
            for path in staging.iterdir():
                saved = destination / path.name
                if saved.is_symlink() or saved.read_bytes() != path.read_bytes():
                    raise ValueError("existing development artifact changed")
        else:
            os.rename(staging, destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return {**receipt, "receipt_sha256": canonical_hash(receipt)}


def training_request(example: ScientificExample) -> tuple[Request, bytes]:
    validate_example(example)
    raw = canonical_bytes(example)
    source = Source(
        "synthetic-res402-" + example.example_sha256.removeprefix("sha256:"),
        "1",
        sha256(raw),
        SourceClass.INSTRUCTION,
    )
    return Request(source, Purpose.SFT, (TRANSFORM,)), raw


def process_training_example(
    example: ScientificExample, grant: bytes, *, exclusion_bundle: bytes | None, output_root: Path
) -> dict[str, Any]:
    """Candidate submission crosses RES-416/417; it confers no corpus approval."""
    request, raw = training_request(example)
    return process_training_inputs(
        ((request, raw, grant),), exclusion_bundle=exclusion_bundle, output_root=output_root
    )


def load_training_corpus(receipt: object, shard: bytes) -> bytes:
    return authorize_sft_corpus_bytes(receipt, shard)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=402)
    parser.add_argument("--input", type=Path, help="External original catalogue to replay")
    parser.add_argument(
        "--tokenizer-directory", type=Path, help="Exact pinned offline snapshot only"
    )
    args = parser.parse_args()
    try:
        dataset = (
            load_development_bytes(require_external(args.input).read_bytes())
            if args.input
            else generate_development_set(args.seed)
        )
        if dataset.seed != args.seed:
            raise ValueError("requested seed and input lineage disagree")
        summary = write_development_artifacts(
            dataset, args.output_root, tokenizer_directory=args.tokenizer_directory
        )
    except (ValueError, OSError, TypeError) as exc:
        parser.exit(2, f"CPU development validation failed: {type(exc).__name__}\n")
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
