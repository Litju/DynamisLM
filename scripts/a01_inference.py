"""Explicit A0.1 inference adapter; invoked only on the owner-approved remote VM."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

from scripts import a01_protocol as protocol


def verify_tokenizer_assets() -> None:
    from huggingface_hub import snapshot_download  # type: ignore[import-not-found]

    freeze = protocol.frozen()
    directory = Path(
        snapshot_download(
            "HuggingFaceTB/SmolLM3-3B",
            revision=freeze["model_revision"],
            allow_patterns=list(freeze["tokenizer_files"]),
            token=False,
        )
    )
    for name, expected in freeze["tokenizer_files"].items():
        if protocol.digest((directory / name).read_bytes()) != expected:
            raise ValueError("remote tokenizer asset SHA-256 mismatch")


def runtime(prepared: dict[str, Any]) -> tuple[ModuleType, list[dict[str, Any]], list[Any]]:
    binding = protocol.plan(prepared["suite"], prepared["case_count"])
    if any(
        protocol.compact(prepared.get(key)) != protocol.compact(value)
        for key, value in binding.items()
    ):
        raise ValueError("prepared A0.1 provenance mismatch")
    manifest = json.loads((protocol.ROOT / protocol.SUITES[prepared["suite"]][0]).read_text())
    if (
        prepared.get("schema") != "RES541_A0_PREPARED_CASES_V1"
        or prepared.get("population") != "SYNTHETIC_DEVELOPMENT_ONLY"
        or [c["case_id"] for c in prepared["cases"]] != [c["case_id"] for c in manifest["cases"]]
    ):
        raise ValueError("prepared A0.1 suite case IDs/count mismatch")
    module = protocol.isolated_a0("a0_colab_inference")
    module.__dict__["SYSTEM_PROMPT"] = protocol.prompt()
    records: list[dict[str, Any]] = []
    streamers: list[Any] = []
    apply_template = module._apply_chat_template
    base_streamer = module.TimingStreamer

    class Streamer(base_streamer):  # type: ignore[misc,valid-type]
        def __init__(self) -> None:
            super().__init__()
            self.ids: list[int] = []
            self.record = records[-1]
            self.case_id = prepared["cases"][len(records) - 1]["case_id"]
            streamers.append(self)

        def put(self, value: Any) -> None:
            if self._prompt_seen:
                self.ids.extend(value.reshape(-1).tolist())
            super().put(value)

    def apply(tokenizer: Any, messages: list[dict[str, str]]) -> Any:
        index = len(records)
        case = prepared["cases"][index]
        if messages != [
            {"role": "system", "content": protocol.prompt()},
            {"role": "user", "content": case["user_message"]},
        ]:
            raise ValueError("inference attempted an original A0 or unexpected prompt")
        when = datetime.now(UTC).isoformat()
        encoded = apply_template(tokenizer, messages)
        rendered = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True, enable_thinking=False
        )
        date = re.search(r"^Today Date: (.+)$", rendered, re.MULTILINE)
        if date is None:
            raise ValueError("official template omitted the run date")
        ids = encoded["input_ids"][0].tolist()
        if tokenizer.encode(rendered, add_special_tokens=False) != ids:
            raise ValueError("actual template/date changed during tokenization")
        records.append(
            {
                "prompt_utc": when,
                "chat_template_date": date.group(1),
                "prompt_token_ids": ids,
                "prompt_sha256": protocol.digest(protocol.compact(ids).encode()),
                "user_message_sha256": protocol.digest(case["user_message"].encode()),
                "tokenizer": tokenizer,
            }
        )
        return encoded

    module.__dict__["TimingStreamer"] = Streamer
    module.__dict__["_apply_chat_template"] = apply
    return module, records, streamers


def run(prepared_path: Path, output: Path) -> None:
    prepared = json.loads(prepared_path.read_text())
    binding = protocol.plan(prepared["suite"], prepared["case_count"])
    module, records, streamers = runtime(prepared)
    os.environ["TZ"] = "UTC"
    time.tzset()
    # The inherited loader keeps checkpoint, hardware/dtype, dependencies and decoding fixed.
    document: dict[str, Any] = {**binding, "schema": "RES541_A0_MODEL_OUTPUTS_V1", "cases": []}
    try:
        verify_tokenizer_assets()
        document = module.run_inference(prepared_path, output)
        document.update(binding)
        if len(records) != binding["case_count"] or len(streamers) != len(records):
            raise ValueError("incomplete actual-token evidence")
        for row, record, streamer in zip(document["cases"], records, streamers, strict=True):
            tokenizer = record["tokenizer"]
            raw = tokenizer.decode(streamer.ids, skip_special_tokens=True)
            if raw.strip() != row["raw_text"] or len(streamer.ids) != row["generated_tokens"]:
                raise ValueError("streamed raw generation differs from the inference result")
            row.update(
                {k: v for k, v in record.items() if k != "tokenizer"},
                raw_text=raw,
                generated_token_ids=streamer.ids,
            )
            row["binding_sha256"] = protocol.bind_row(row, binding)
        protocol.validate_outputs(document, binding, prepared["cases"], tokenizer)
    except Exception as exc:
        document["status"] = "NO_GO"
        document["failure_category"] = type(exc).__name__
        raise
    finally:
        # Preserve even rejected raw generations; never substitute a repaired intent.
        if document.get("status") != "COMPLETE":
            document["captured_generations"] = [
                {
                    "case_id": streamer.case_id,
                    "generated_token_ids": streamer.ids,
                    "raw_text": streamer.record["tokenizer"].decode(
                        streamer.ids, skip_special_tokens=True
                    ),
                }
                for streamer in streamers
            ]
        output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared-cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get("RES541_A01_REMOTE") != "1":
        parser.error("A0.1 model inference is remote-only; use the owner-gated execution adapter")
    run(args.prepared_cases, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
