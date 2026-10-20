"""Compare pinned model tokenizers without loading model weights."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import cast
from urllib.request import Request, urlopen

from tokenizers import Tokenizer  # type: ignore[import-not-found]
from tokenizers import __version__ as tokenizers_version

MODEL_PINS = {
    "Qwen/Qwen3-4B": (
        "1cfa9a7208912126459214e8b04321603b3df60c",
        "aeb13307a71acd8fe81861d94ad54ab689df773318809eed3cbe794b4492dae4",
    ),
    "HuggingFaceTB/SmolLM3-3B": (
        "a07cc9a04f16550a088caea529712d1d335b0ac1",
        "7b6a500b662a34eb3f0374db856ba4ad7de4c81040571d78dc0d357238930005",
    ),
    "Qwen/Qwen3.5-4B": (
        "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a",
        "5f9e4d4901a92b997e463c1f46055088b6cca5ca61a6522d1b9f64c4bb81cb42",
    ),
    "ibm-granite/granite-4.0-h-tiny": (
        "791e0d3d28c86e106c9b6e0b4cecdee0375b6124",
        "e2bad66439538cb4d5a7580680932432ed9ece9d3b8577e675512bdf11599253",
    ),
}

# Synthetic only: this tokenizes a schema string and does not define a live tool.
TOOL_SCHEMA = json.dumps(
    {
        "type": "function",
        "function": {
            "name": "request_analysis",
            "description": "Synthetic analysis-tool schema for tokenization only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "record_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                    },
                    "metric_label": {"type": "string"},
                    "requested_unit": {
                        "type": "string",
                        "enum": ["m·s⁻¹", "N·m", "W·kg⁻¹"],
                    },
                    "include_provenance": {"type": "boolean"},
                },
                "required": ["record_ids", "metric_label"],
                "additionalProperties": False,
            },
        },
    },
    ensure_ascii=False,
    separators=(",", ":"),
    sort_keys=True,
)

REFUSAL_SCHEMA = json.dumps(
    {
        "type": "object",
        "properties": {
            "decision": {"type": "string", "enum": ["REFUSE", "ALLOW_WITH_LIMITS"]},
            "reason_code": {
                "type": "string",
                "enum": [
                    "INSUFFICIENT_INFORMATION",
                    "COMPUTATION_NOT_REGISTERED",
                    "MEASUREMENT_NOT_COMPARABLE",
                    "UNSUPPORTED_CAUSAL_CLAIM",
                ],
            },
            "missing_evidence": {"type": "array", "items": {"type": "string"}},
            "allowed_interpretation": {"type": ["string", "null"]},
        },
        "required": ["decision", "reason_code", "missing_evidence"],
        "additionalProperties": False,
    },
    ensure_ascii=False,
    separators=(",", ":"),
    sort_keys=True,
)

PROBES = {
    "football_performance_terminology": (
        "high-speed running; sprint distance; acceleration; deceleration; repeated-sprint ability "
        "(RSA); player load; CMJ; 505 change-of-direction test; 30–15 Intermittent Fitness Test "  # noqa: RUF001
        "(IFT)."
    ),
    "biomechanics": (
        "countermovement jump (CMJ); eccentric braking impulse; concentric phase; rate of force "
        "development (RFD); relative peak power; force–time curve; RSI-modified; hip, knee and "  # noqa: RUF001
        "ankle joint moment."
    ),
    "si_units": "m; s; kg; N; N·m; W; W·kg⁻¹; m·s⁻¹; m·s⁻²; ms; mmol·L⁻¹; °C.",
    "scientific_notation": "9.81 m·s⁻²; 3.4×10⁻³; 1.25e+06; 6.02E23; −0.5; 0.0; 1e-12.",  # noqa: RUF001
    "football_microcycle_context": (
        "Elite senior first-team football microcycle: MD-4 strength/power, MD-3 high-speed "
        "running, MD-2 tactical exposure, MD-1 taper, MD match, MD+1 recovery. "
        "Specify session dates, athlete availability, source and match minutes."
    ),
    "measurement_uncertainty": (
        "Within-athlete CMJ change: standard error of measurement (SEM), typical error (TE), "
        "coefficient of variation (CV), 95% confidence interval, minimum detectable change "
        "(MDC), smallest worthwhile change (SWC); distinguish measurement noise from "
        "a causal treatment effect."
    ),
    "scientific_refusal": (
        "INSUFFICIENT_INFORMATION; COMPUTATION_NOT_REGISTERED; "
        "MEASUREMENT_NOT_COMPARABLE; UNSUPPORTED_CAUSAL_CLAIM. "
        "Refuse an unregistered calculation; do not infer force from jump height "
        "or compare unmatched protocols; explain missing evidence."
    ),
    "refusal_output_schema": REFUSAL_SCHEMA,
    "analysis_tool_schema": TOOL_SCHEMA,
}

MAX_TOKENIZER_BYTES = 20_000_000


def _check_probe_definition() -> None:
    assert len(MODEL_PINS) == 4
    assert all(
        len(revision) == 40 and len(digest) == 64 for revision, digest in MODEL_PINS.values()
    )
    assert set(PROBES) == {
        "football_performance_terminology",
        "biomechanics",
        "si_units",
        "scientific_notation",
        "analysis_tool_schema",
        "football_microcycle_context",
        "measurement_uncertainty",
        "scientific_refusal",
        "refusal_output_schema",
    }
    assert json.loads(TOOL_SCHEMA)["type"] == "function"
    assert json.loads(REFUSAL_SCHEMA)["properties"]["decision"]["type"] == "string"


def _fetch_tokenizer(repository: str, revision: str, expected_sha256: str) -> bytes:
    url = f"https://huggingface.co/{repository}/resolve/{revision}/tokenizer.json"
    request = Request(url, headers={"User-Agent": "DynamisLM-RES419-tokenizer-probe/1.0"})
    with urlopen(request, timeout=60) as response:
        payload = cast(bytes, response.read(MAX_TOKENIZER_BYTES + 1))
    if len(payload) > MAX_TOKENIZER_BYTES:
        raise ValueError(f"tokenizer.json exceeds {MAX_TOKENIZER_BYTES} bytes: {repository}")
    actual_sha256 = hashlib.sha256(payload).hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValueError(f"pinned tokenizer checksum mismatch: {repository} {actual_sha256}")
    return payload


def _probe_model(repository: str, revision: str, expected_sha256: str) -> dict[str, object]:
    payload = _fetch_tokenizer(repository, revision, expected_sha256)
    tokenizer = Tokenizer.from_str(payload.decode("utf-8"))
    if tokenizer.get_vocab_size(with_added_tokens=True) == 0:
        raise ValueError(f"empty vocabulary: {repository}")

    probes: dict[str, dict[str, object]] = {}
    total_token_count = 0
    for probe_id, text in PROBES.items():
        encoding = tokenizer.encode(text, add_special_tokens=False)
        if not encoding.ids or len(encoding.ids) != len(encoding.tokens):
            raise ValueError(f"invalid tokenization: {repository} {probe_id}")
        total_token_count += len(encoding.ids)
        token_ids = json.dumps(encoding.ids, separators=(",", ":")).encode("ascii")
        probes[probe_id] = {
            "input_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "token_count": len(encoding.ids),
            "token_ids_sha256": hashlib.sha256(token_ids).hexdigest(),
        }

    return {
        "repository": repository,
        "revision": revision,
        "tokenizer_file": "tokenizer.json",
        "tokenizer_bytes": len(payload),
        "tokenizer_sha256": expected_sha256,
        "vocabulary_size": tokenizer.get_vocab_size(with_added_tokens=True),
        "total_token_count": total_token_count,
        "probes": probes,
    }


def main() -> int:
    _check_probe_definition()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="write JSON to this path instead of stdout")
    args = parser.parse_args()

    report = {
        "schema_version": "RES419-TOKENIZER-PROBE@1.0.0",
        "tokenizers_version": tokenizers_version,
        "scope": {
            "cpu_only": True,
            "tokenization_only": True,
            "model_weights_downloaded": False,
            "model_loaded": False,
            "inference_run": False,
            "chat_template_applied": False,
        },
        "models": [
            _probe_model(repository, revision, digest)
            for repository, (revision, digest) in MODEL_PINS.items()
        ],
    }
    output = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
