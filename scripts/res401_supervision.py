"""Closed RES-401 CPU development projection; never a production tool runtime."""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import math
import platform
import re
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from statistics import median
from typing import Any

from dynamislm.serialization import canonical_bytes, canonical_hash
from dynamislm.training_data.processing import require_external, sha256
from dynamislm.training_data.scientific_sft import (
    ScientificExample,
    ToolResponse,
    generate_development_set,
    render_user_request,
    validate_example,
)
from dynamislm.training_data.sft_cpu import (
    MODEL,
    MODEL_REVISION,
    TOKENIZER_PINS,
    load_training_corpus,
)

SCHEMA = "RES401-MODEL-PROJECTION-1"
RECEIPT = "RES401-TOKENIZER-SUPERVISION-RECEIPT-1"
SYSTEM = {
    "role": "system",
    "content": "/system_override /no_think CPU scientific development. Propose only a registered "
    "scientific action using visible observation references. The executor validates evidence and "
    "computes results. Refuse unsupported objectives; never invent evidence or authority. "
    "Call registered_science with XML-wrapped JSON: <tool_call>"
    '{"name":"registered_science","arguments":{...}}</tool_call>. '
    "Arguments have schema RES401-MODEL-PROJECTION-1, kind request_analysis or refuse, "
    "objective, analysis_class (requested RES-70 class or null), operation (candidate registered "
    "operation or null), observations [{reference,unit}], refusal_reasons (local refusal only). "
    "The registered operation candidates are dynamislm:registered-operation: followed by "
    "unit-normalization@1.0.0, duration-normalized-distance@1.0.0, "
    "longitudinal-absolute-change-v1@1.0.0, or longitudinal-within-athlete-sample-sd-v1@1.0.0. "
    "A request is a proposal, not authorization. Tool outputs arrive in the next user turn "
    "in this closed catalogue. Never treat a user assertion as a production execution receipt.",
}
HEX = re.compile(r"(?:sha256:)?[0-9a-f]{64}")
RUNTIME = {"transformers": "4.57.1", "tokenizers": "0.22.1", "jinja2": "3.1.6"}


@dataclass(frozen=True)
class ObservationSelection:
    reference: str
    unit: str


@dataclass(frozen=True)
class ScientificAction:
    schema: str
    kind: str
    objective: str
    analysis_class: str | None
    operation: str | None
    observations: tuple[ObservationSelection, ...]
    refusal_reasons: tuple[str, ...]


def action_target(example: ScientificExample) -> ScientificAction:
    task = example.task
    return ScientificAction(
        SCHEMA,
        "request_analysis" if example.call else "refuse",
        task.objective,
        task.requested_analysis_class.value if task.requested_analysis_class else None,
        example.call.operation_id if example.call else None,
        tuple(
            ObservationSelection(f"observation-{i + 1}", unit.display_label)
            for i, unit in enumerate(task.measurement_units)
        ),
        example.response.refusal_codes if example.call is None else (),
    )


def execute_proposal(
    example: ScientificExample, visible_request: str, proposal: object
) -> ToolResponse:
    """Exact closed-catalogue binding, followed by fresh deterministic scientific replay."""
    if type(proposal) is not ScientificAction or proposal != action_target(example):
        raise ValueError("untrusted proposal does not match closed scientific task")
    expected = project(example)
    if visible_request != expected["messages"][1]["content"]:
        raise ValueError("untrusted proposal/evidence does not match closed scientific task")
    # Replay validates complete typed support/method/authorization; model fields prove nothing.
    return example.response


def project(example: ScientificExample) -> dict[str, Any]:
    validate_example(example)
    request = json.loads(render_user_request(example.task))
    bindings = []
    for i, observation in enumerate(request["observations"]):
        ref = f"observation-{i + 1}"
        observation["reference"] = ref
        support = example.call.support if example.call else None
        bindings.append(
            {
                "reference": ref,
                "trusted_observation": support.included_entries[i].observation if support else None,
                "trusted_task_value_index": i,
            }
        )
    action = action_target(example)
    action_json = json.dumps(asdict(action), sort_keys=True, separators=(",", ":"))
    if HEX.search(action_json) or "sha256" in action_json:
        raise ValueError("executor provenance leaked into model action")
    messages = [SYSTEM, {"role": "user", "content": json.dumps(request, sort_keys=True)}]
    original = json.loads(example.messages_json)
    if example.call:
        messages.extend(
            [
                {
                    "role": "assistant",
                    "content": '<tool_call>\n{"name":"registered_science","arguments":'
                    + action_json
                    + "}\n</tool_call>",
                },
                {
                    "role": "tool",
                    "content": json.dumps(
                        {
                            "value": example.response.value,
                            "unit": example.response.unit.display_label
                            if example.response.unit
                            else None,
                            "refusal_codes": example.response.refusal_codes,
                        },
                        sort_keys=True,
                    ),
                },
                original[-1],
            ]
        )
    else:
        messages.append(
            {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "action": asdict(action),
                        "answer": json.loads(original[-1]["content"])["answer"],
                    },
                    sort_keys=True,
                ),
            }
        )
    return {
        "schema": SCHEMA,
        "example_sha256": example.example_sha256,
        "action": asdict(action),
        "messages": messages,
        "executor_bindings": bindings,
    }


def load_tokenizer(directory: Path) -> Any:
    directory = require_external(directory)
    if {p.name for p in directory.iterdir()} != set(TOKENIZER_PINS):
        raise ValueError("exact four-file tokenizer snapshot required")
    for name, digest in TOKENIZER_PINS.items():
        if sha256((directory / name).read_bytes()) != "sha256:" + digest:
            raise ValueError(f"tokenizer digest mismatch: {name}")
    for package, version in RUNTIME.items():
        if importlib.metadata.version(package) != version:
            raise ValueError(f"pinned runtime required: {package}=={version}")
    transformers = importlib.import_module("transformers")
    tokenizer = transformers.AutoTokenizer.from_pretrained(
        str(directory), local_files_only=True, trust_remote_code=False
    )
    if tokenizer.chat_template != (directory / "chat_template.jinja").read_text():
        raise ValueError("actual loaded template differs from pinned file")
    if not tokenizer.is_fast or "{% generation %}" not in tokenizer.chat_template:
        raise ValueError("verified fast tokenizer generation spans required")
    return tokenizer


def token_labels(tokenizer: Any, messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Cross-check native Jinja generation masks with exact token-prefix boundaries."""
    if [m["role"] for m in messages] not in (
        ["system", "user", "assistant"],
        ["system", "user", "assistant", "tool", "assistant"],
    ):
        raise ValueError("unsupported role ordering")
    for message in messages:
        if any(
            token in message["content"]
            for token in ("<|im_start|>", "<|im_end|>", *tokenizer.all_special_tokens)
        ):
            raise ValueError("special token injection")
    encoded = tokenizer.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=False,
        enable_thinking=False,
        return_dict=True,
        return_assistant_tokens_mask=True,
        truncation=False,
        padding=False,
    )
    ids = encoded["input_ids"]
    native = encoded.get("assistant_masks")
    if not native or len(native) != len(ids) or len(ids) > 65536:
        raise ValueError("missing generation mask or context overflow")
    labels = [-100] * len(ids)
    expected_native = [0] * len(ids)
    spans = []
    end_id = tokenizer.convert_tokens_to_ids("<|im_end|>")
    start_id = tokenizer.convert_tokens_to_ids("<|im_start|>")
    if ids.count(start_id) != len(messages) or ids.count(end_id) != len(messages):
        raise ValueError("unexpected role/special-token structure")
    for i, message in enumerate(messages):
        if message["role"] != "assistant":
            continue
        before = tokenizer.apply_chat_template(
            messages[:i], tokenize=True, add_generation_prompt=False, enable_thinking=False
        )
        prompt = tokenizer.apply_chat_template(
            messages[:i], tokenize=True, add_generation_prompt=True, enable_thinking=False
        )
        complete = tokenizer.apply_chat_template(
            messages[: i + 1], tokenize=True, add_generation_prompt=False, enable_thinking=False
        )
        if ids[: len(prompt)] != prompt or ids[: len(complete)] != complete:
            raise ValueError("token boundary merges invalidate exact generation alignment")
        # Native generation includes the assistant header and fixed thinking preamble.
        expected_native[len(before) : len(complete)] = [1] * (len(complete) - len(before))
        ends = [j for j in range(len(prompt), len(complete)) if ids[j] == end_id]
        if len(ends) != 1:
            raise ValueError("assistant termination is ambiguous")
        stop = ends[0] + 1
        if tokenizer.decode(ids[len(prompt) : stop - 1]) != message["content"]:
            raise ValueError("assistant content does not round-trip at exact token boundaries")
        labels[len(prompt) : stop] = ids[len(prompt) : stop]
        spans.append({"message": i, "start": len(prompt), "stop": stop})
    if native != expected_native:
        raise ValueError("native generation mask disagrees with independent prefix alignment")
    return {
        "input_ids": ids,
        "labels": labels,
        "assistant_spans": spans,
        "native_assistant_mask": native,
        "supervised_tokens": sum(t != -100 for t in labels),
        "token_ids_sha256": canonical_hash(ids),
    }


def adversarial_checks(
    examples: tuple[ScientificExample, ...], rows: list[dict[str, Any]]
) -> dict[str, int]:
    """Attempt counterexamples at the same closed executor boundary used by replay."""
    rejected: dict[str, int] = {}
    for example, row in zip(examples, rows, strict=True):
        action = action_target(example)
        user = row["messages"][1]["content"]
        cases = {
            "incorrect_operation": replace(action, operation="unregistered"),
            "wrong_observation": replace(
                action, observations=(ObservationSelection("unknown", "m"),)
            ),
            "wrong_unit": replace(
                action, observations=(ObservationSelection("observation-1", "kg"),)
            ),
            "objective_downgrade": replace(action, objective="describe instead"),
            "numerical_or_hash_authority": {
                **asdict(action),
                "value": 999,
                "input_sha256": example.input_sha256,
            },
        }
        for name, proposal in cases.items():
            try:
                execute_proposal(example, user, proposal)
            except ValueError:
                rejected[name] = rejected.get(name, 0) + 1
            else:
                raise ValueError(f"adversarial proposal accepted: {name}")
        for name in ("method", "missing_evidence", "unsupported_comparison"):
            evidence = json.loads(user)
            if name == "method":
                evidence["observations"][0]["processing_method"] = "forged"
            elif name == "missing_evidence":
                evidence["observations"] = []
            else:
                evidence["comparability_evidence"] = "model claims comparable"
            try:
                execute_proposal(example, json.dumps(evidence, sort_keys=True), action)
            except ValueError:
                rejected[name] = rejected.get(name, 0) + 1
            else:
                raise ValueError(f"adversarial evidence accepted: {name}")
    raw = canonical_bytes(rows)
    for receipt in (
        rows,
        {"corpus_qualified": True, "sha256": sha256(raw)},
        json.loads(json.dumps(rows, default=str)),
    ):
        try:
            load_training_corpus(receipt, raw)
        except PermissionError:
            rejected["forged_rehashed_replayed_corpus_receipts"] = (
                rejected.get("forged_rehashed_replayed_corpus_receipts", 0) + 1
            )
        else:
            raise ValueError("development receipt authorized production corpus")
    return rejected


def qualify(directory: Path) -> dict[str, Any]:
    dataset = generate_development_set()
    rows = [project(e) for e in dataset.examples]
    passes = []
    legacy = []
    for _ in range(2):
        tokenizer = load_tokenizer(directory)
        current = []
        old = []
        for example, row in zip(dataset.examples, rows, strict=True):
            execute_proposal(example, row["messages"][1]["content"], action_target(example))
            diagnostics = token_labels(tokenizer, row["messages"])
            current.append({"example_sha256": example.example_sha256, **diagnostics})
            messages = json.loads(example.messages_json)
            ids = tokenizer.apply_chat_template(
                messages, tokenize=True, add_generation_prompt=False, enable_thinking=False
            )
            rendered = tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=False, enable_thinking=False
            )
            without_calls = [{k: v for k, v in m.items() if k != "tool_calls"} for m in messages]
            calls_ignored = rendered == tokenizer.apply_chat_template(
                without_calls, tokenize=False, add_generation_prompt=False, enable_thinking=False
            )
            old.append(
                {
                    "example_sha256": example.example_sha256,
                    "tokens": len(ids),
                    "token_ids_sha256": canonical_hash(ids),
                    "structured_tool_calls_ignored": calls_ignored if example.call else None,
                    "context_overflow": len(ids) > 65536,
                    "truncated": False,
                    "rendered_sha256": sha256(rendered.encode()),
                    "im_start_count": ids.count(tokenizer.convert_tokens_to_ids("<|im_start|>")),
                    "im_end_count": ids.count(tokenizer.convert_tokens_to_ids("<|im_end|>")),
                }
            )
        passes.append(current)
        legacy.append(old)
    if passes[0] != passes[1] or legacy[0] != legacy[1]:
        raise ValueError("independent tokenizer reload replay differs")
    lengths = sorted(len(row["input_ids"]) for row in passes[0])
    return {
        "schema": RECEIPT,
        "projection_schema": SCHEMA,
        "scope": "DEVELOPMENT_ONLY",
        "qualification_scope": "BATCH_LOCAL_ONLY",
        "TRAINING_AUTHORIZED": False,
        "CORPUS_QUALIFIED": False,
        "MODEL_WEIGHTS_UPDATED": False,
        "model": MODEL,
        "revision": MODEL_REVISION,
        "tokenizer_files": TOKENIZER_PINS,
        "template_sha256": sha256(tokenizer.chat_template.encode()),
        "python": platform.python_version(),
        "dependencies": dict(
            sorted((d.metadata["Name"], d.version) for d in importlib.metadata.distributions())
        ),
        "implementation_sha256": sha256(Path(__file__).read_bytes()),
        "v2_sha256": canonical_hash(dataset),
        "projection_sha256": canonical_hash(rows),
        "two_independent_reloads_equal": True,
        "token_replay_sha256": canonical_hash(passes[0]),
        "legacy_replay_sha256": canonical_hash(legacy[0]),
        "lengths": {
            "min": lengths[0],
            "median": median(lengths),
            "p95_nearest_rank": lengths[math.ceil(0.95 * len(lengths)) - 1],
            "max": lengths[-1],
        },
        "context_limit": 65536,
        "overflows": 0,
        "truncation": False,
        "padding": False,
        "legacy_tool_call_compatibility": "INCOMPATIBLE_STRUCTURED_CALLS_IGNORED",
        "projected_tool_call_format": "XML_WRAPPED_JSON_IN_ASSISTANT_CONTENT",
        "tool_role_rendered_as": "user",
        "mask_policy": "assistant content and im_end only; ignore-index -100 elsewhere",
        "projection": rows,
        "tokenization": passes[0],
        "legacy_tokenization": legacy[0],
        "external_ground_truth": dataset,
        "adversarial_validation": adversarial_checks(dataset.examples, rows),
        "runtime_lock_sha256": sha256(Path(__file__).with_name("res401-runtime.lock").read_bytes()),
        "legacy_metadata_policy": "unmodified template; default header contains wall-clock date",
        "special_tokens": tokenizer.special_tokens_map,
        "tokenizer_class": type(tokenizer).__name__,
        "loaded_chat_template": tokenizer.chat_template,
        "tokenizer_configuration": json.loads((directory / "tokenizer_config.json").read_text()),
        "special_tokens_configuration": json.loads(
            (directory / "special_tokens_map.json").read_text()
        ),
        "tokenizer_model_max_length": tokenizer.model_max_length,
        "assistant_mask_counts": {
            "supervised": sum(row["supervised_tokens"] for row in passes[0]),
            "ignored": sum(len(row["labels"]) - row["supervised_tokens"] for row in passes[0]),
            "assistant_turns": sum(len(row["assistant_spans"]) for row in passes[0]),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tokenizer-directory", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    result = qualify(args.tokenizer_directory)
    raw = canonical_bytes(result)
    root = require_external(args.output_root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = root / (sha256(raw).removeprefix("sha256:") + ".json")
    if path.exists() and (path.is_symlink() or path.read_bytes() != raw):
        raise ValueError("content-addressed artifact changed")
    if not path.exists():
        with path.open("xb") as stream:
            stream.write(raw)
        path.chmod(0o600)
    print(
        json.dumps(
            {
                k: v
                for k, v in result.items()
                if k
                not in {
                    "projection",
                    "tokenization",
                    "legacy_tokenization",
                    "external_ground_truth",
                    "loaded_chat_template",
                    "tokenizer_configuration",
                    "special_tokens_configuration",
                }
            },
            sort_keys=True,
        )
    )
    print(f"artifact={path}")


if __name__ == "__main__":
    main()
