"""Replay exposed A0.2 action evidence. Tokenizer only, no model or logits."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from scripts import a02_v3_constrained as old
from scripts import a02_v3_contract as v3
from scripts import a02_v3_decision as decision
from scripts import a02_v3_synthetic as synthetic
from scripts import a02_v3_training as training
from scripts import a02_v3_worker as worker
from scripts.a02_v3_preflight import TOKENIZER_DIR, load_pinned_tokenizer
from scripts.a03_token_decoder import Grammar, TokenMask, Vocabulary

REPORT_ROOT = Path("/mnt/e/DynamisLM-A0/reports/A03-DECODER-AUTHORITY-RECOVERY")
NATIVE = "ADAPTED_UNCONSTRAINED"
LEGACY = "ADAPTED_CONSTRAINED"


def common(left: Sequence[int], right: Sequence[int]) -> int:
    return next(
        (i for i, (a, b) in enumerate(zip(left, right, strict=False)) if a != b),
        min(len(left), len(right)),
    )


def completion(grammar: Grammar, prefix: str) -> str:
    state = grammar.advance(grammar.start, prefix.encode("ascii"))
    if not state:
        raise ValueError("historical choice is outside the candidate byte grammar")
    suffix = bytearray()
    while 0 not in state:
        byte = min(byte for node in state for byte in grammar.edges[node])
        suffix.append(byte)
        state = grammar.advance(state, bytes([byte]))
    return prefix + suffix.decode("ascii")


def choice_boundaries(
    grammar: Grammar,
    encode: old.Encode,
    output: str,
    comparison_output: str,
    request: dict[str, Any],
    action: dict[str, Any],
) -> list[dict[str, Any]]:
    traces: list[dict[str, Any]] = []
    target = old.target_chooser(action)

    def choose(walk: old._Walk, field: str, options: list[str]) -> tuple[str, list[float]]:
        selected, _ = target(walk, field, options)
        prefix = walk.text
        partial = [encode(prefix + option) for option in options]
        start = min(common(encode(prefix), ids) for ids in partial)
        tests = []
        for option, ids in zip(options, partial, strict=True):
            head = prefix + option
            full = next(
                (text for text in (output, comparison_output) if text.startswith(head)), None
            )
            if full is None:
                full = completion(grammar, head)
            # A close option can be a complete token sequence even though more bytes follow.
            joint = encode(full)
            shared = common(ids, joint)
            tests.append(
                {
                    "option": option,
                    "scorer_start": start,
                    "scored_ids": ids[start:],
                    "common_token_count": shared,
                    "right_boundary_differs": shared != len(ids),
                    "first_incomplete_token_id": ids[shared] if shared < len(ids) else None,
                    "complete_token_ids_from_difference": joint[shared : shared + 4],
                    "following_bytes": full[len(head) :],
                }
            )
        traces.append({"field": field, "prefix": prefix, "chosen": selected, "tests": tests})
        return selected, []

    emitted = old.decode(request=request, prompt_ids=[], encode=encode, chooser=choose)
    if emitted["text"] != output:
        raise ValueError("historical fixed-order walk does not reproduce recorded bytes")
    return traces


def token_replay(
    mask: TokenMask, grammar: Grammar, ids: list[int], raw: str
) -> tuple[bool, dict[str, Any] | None]:
    state = grammar.start
    output = bytearray()
    for pos, token in enumerate(ids):
        if token not in mask.allowed(grammar, state):
            return False, {"position": pos, "token_id": token, "accepted_prefix": output.decode()}
        if token == mask.eos:
            return pos == len(ids) - 1 and output == raw.encode(), None
        output.extend(mask.pieces[token])
        state = mask.advance(grammar, state, token)
    return False, {"position": len(ids), "token_id": None, "reason": "recorded EOS absent"}


def qualify(checkpoint: Path, tokenizer_path: Path) -> dict[str, Any]:
    protocol = decision.load_protocol()
    items = training.adapted_work_items(protocol)
    checkpoint_state = worker.read_checkpoint(checkpoint, items)
    if checkpoint_state["torn_tail_discarded"] or len(checkpoint_state["entries"]) != len(items):
        raise ValueError("incomplete historical checkpoint")
    worker.check_identity(checkpoint_state["entries"], protocol)
    records: dict[str, list[dict[str, Any]]] = {NATIVE: [], LEGACY: []}
    for item, entry in zip(items, checkpoint_state["entries"], strict=True):
        if item.arm in records and item.key.startswith("HELDOUT:"):
            records[item.arm].append(entry["record"])
    native_scores = decision.bind_arm(protocol, NATIVE, records[NATIVE])
    legacy_scores = decision.bind_arm(protocol, LEGACY, records[LEGACY])
    tokenizer = load_pinned_tokenizer(tokenizer_path)

    def encode(text: str) -> list[int]:
        return list(tokenizer.encode(text, add_special_tokens=False))

    (quote,) = encode('"')
    train_spec = protocol["data"]["training"]
    train = synthetic.generate(train_spec["split"], train_spec["seed"], train_spec["count"])
    if synthetic.manifest_sha256(train) != train_spec["manifest_sha256"]:
        raise ValueError("historical training manifest differs")
    length, quotes = 0, 0
    for example in train:
        ids = encode(example["target_text"])
        length += len(ids)
        quotes += ids.count(quote)

    mask = TokenMask(Vocabulary.from_pinned(tokenizer_path))
    rows = []
    totals: Counter[str] = Counter()
    for native, legacy, ns, ls, example in zip(
        records[NATIVE],
        records[LEGACY],
        native_scores,
        legacy_scores,
        decision.heldout_examples(protocol),
        strict=True,
    ):
        request = example["request"]
        grammar = Grammar(request)
        raw, old_raw = native["raw_output"], legacy["raw_output"]
        prompt = v3.build_action_prompt(tokenizer, request)
        if any(
            record["rendered_prompt_sha256"] != prompt["rendered_prompt_sha256"]
            for record in (native, legacy)
        ):
            raise ValueError("recorded prompt differs from pinned rendering")
        canonical = encode(raw)
        matches = [
            ids
            for ids in (canonical, [*canonical, mask.eos])
            if v3.sha256(v3.canonical(ids).encode()) == native["generated_token_ids_sha256"]
        ]
        token_ok, intervention = (
            token_replay(mask, grammar, matches[0], raw) if len(matches) == 1 else (False, None)
        )
        byte_ok = grammar.accepts(raw.encode())
        native_trace = (
            choice_boundaries(
                grammar, encode, raw, old_raw, request, v3.parse_action(raw, grammar.ids)
            )
            if byte_ok and ns["strict_valid"]
            else []
        )
        legacy_trace = choice_boundaries(
            grammar, encode, old_raw, raw, request, v3.parse_action(old_raw, grammar.ids)
        )
        recorded_choices = [c for c in legacy["choices"] if len(c["options"]) > 1]
        if [(c["field"], c["chosen"], c["options"]) for c in recorded_choices] != [
            (c["field"], c["chosen"], [t["option"] for t in c["tests"]]) for c in legacy_trace
        ]:
            raise ValueError("historical choice trace differs")
        first_difference = None
        for left, right in zip(native_trace, legacy_trace, strict=False):
            if left["chosen"] == right["chosen"]:
                continue
            if (left["field"], left["prefix"]) != (right["field"], right["prefix"]):
                raise ValueError("choice paths diverged before the first decision")
            preserved = next(t for t in left["tests"] if t["option"] == left["chosen"])
            selected = next(t for t in right["tests"] if t["option"] == right["chosen"])
            asymmetry = (
                ns["exact"]
                and not ls["exact"]
                and right["field"] == "target_claims.relationship"
                and selected["option"] == old.CLOSE_LIST
                and not selected["right_boundary_differs"]
                and preserved["right_boundary_differs"]
                and preserved["scored_ids"][-1] == quote
            )
            first_difference = {
                "field": right["field"],
                "native": preserved,
                "legacy": selected,
                "boundary_asymmetry": asymmetry,
            }
            totals["lost_cases_with_boundary_asymmetry"] += asymmetry
            break
        totals.update(
            {
                "strict_parse_valid": int(ns["strict_valid"]),
                "grammar_bytes_accepted": int(byte_ok),
                "token_sequences_digest_verified": int(len(matches) == 1),
                "grammar_tokens_accepted": int(token_ok),
                "known_mask_interventions": int(
                    intervention is not None and intervention["token_id"] is not None
                ),
                "native_exact_historical": int(ns["exact"]),
                "legacy_exact_historical": int(ls["exact"]),
                "native_only_exact_historical": int(ns["exact"] and not ls["exact"]),
                "cases_with_legacy_right_boundary_difference": int(
                    any(t["right_boundary_differs"] for c in legacy_trace for t in c["tests"])
                ),
            }
        )
        for c in legacy_trace:
            for test in c["tests"]:
                totals["legacy_right_boundary_differences"] += test["right_boundary_differs"]
                if test["option"] != old.CLOSE_LIST:
                    totals["legacy_quoted_options"] += 1
                    totals["legacy_quoted_options_ending_in_lone_quote"] += (
                        test["scored_ids"][-1] == quote
                    )
        rows.append(
            {
                "example_id": native["example_id"],
                "family": native["family"],
                "raw_output": raw,
                "strict_parse_valid": ns["strict_valid"],
                "bytes_accepted": byte_ok,
                "tokens_accepted": token_ok,
                "recorded_token_digest": native["generated_token_ids_sha256"],
                "recovered_token_ids": matches[0] if len(matches) == 1 else None,
                "first_mask_intervention": intervention,
                "historical_native_exact": ns["exact"],
                "historical_legacy_exact": ls["exact"],
                "first_choice_difference": first_difference,
                "native_option_boundaries": native_trace,
                "legacy_option_boundaries": legacy_trace,
            }
        )
    return {
        "checkpoint_sha256": v3.sha256(checkpoint.read_bytes()),
        "checkpoint_chain_head": checkpoint_state["head"],
        "protocol_sha256": decision.protocol_sha256(),
        "model": protocol["candidate_model"],
        "tokenizer": v3.load_profile()["tokenizer"],
        "training_targets": len(train),
        "training_token_count": length,
        "quote_token_id": quote,
        "quote_in_training_targets": quotes,
        "counts": dict(totals),
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--tokenizer", type=Path, default=TOKENIZER_DIR)
    args = parser.parse_args()
    if not args.output.resolve().is_relative_to(REPORT_ROOT):
        raise ValueError("D0 receipts belong under the external A0.3 reports root")
    report = qualify(args.checkpoint, args.tokenizer)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=True, separators=(",", ":"))
        handle.write("\n")
    print(json.dumps(report["counts"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
