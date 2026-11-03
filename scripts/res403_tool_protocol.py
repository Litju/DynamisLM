"""Closed RES-403 development protocol; no model runtime or production authority."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import Any

from dynamislm.training_data.scientific_sft import ScientificExample, ToolResponse, validate_example
from scripts import res401_supervision as projection

SCHEMA = "RES403-SCIENTIFIC-ACTION-1"
SYSTEM = (
    "/system_override /no_think Propose one scientific action using visible references. "
    "Only the trusted executor authorizes and computes; do not invent numbers or evidence. "
    "A request is <tool_call> JSON </tool_call> with name registered_science and arguments. "
    "A refusal is a direct JSON action, without a tool call. The action has exactly schema "
    "RES403-SCIENTIFIC-ACTION-1, kind request_analysis or refuse, objective, analysis_class "
    "(requested class or null), operation (candidate registered operation or null), "
    "observations (list of reference and unit), and refusal_reasons (list). "
    "A request has no refusal reasons and names an operation or analysis class. "
    "A refusal has no operation and gives supported refusal reasons. "
    "Operation candidates have prefix dynamislm:registered-operation: and suffix "
    "unit-normalization@1.0.0, duration-normalized-distance@1.0.0, "
    "longitudinal-absolute-change-v1@1.0.0, or "
    "longitudinal-within-athlete-sample-sd-v1@1.0.0."
)
MAX_BYTES = 8192
MAX_OBSERVATIONS = 16
_OPEN = "<tool_call>"
_CLOSE = "</tool_call>"
_TEXT = re.compile(r"^[A-Za-z0-9 _.,;:@/()\-]+$")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _text(value: object, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not 0 < len(value) <= 512 or not _TEXT.fullmatch(value):
        raise ValueError("invalid action text")
    return value


def parse_action(content: str) -> projection.ScientificAction:
    """Parse one XML-wrapped request or one direct JSON refusal, never execute it."""
    if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_BYTES:
        raise ValueError("action size or type invalid")
    wrapped = content.startswith(_OPEN) and content.endswith(_CLOSE)
    raw = content[len(_OPEN) : -len(_CLOSE)] if wrapped else content
    if "<" in raw or ">" in raw:
        raise ValueError("delimiter or executable content")
    try:
        obj = json.loads(
            raw,
            object_pairs_hook=_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")),
        )
    except (ValueError, RecursionError) as exc:
        raise ValueError("invalid action JSON") from exc
    if wrapped:
        if (
            not isinstance(obj, dict)
            or set(obj) != {"name", "arguments"}
            or obj["name"] != "registered_science"
        ):
            raise ValueError("invalid tool envelope")
        obj = obj["arguments"]
    fields = {
        "schema",
        "kind",
        "objective",
        "analysis_class",
        "operation",
        "observations",
        "refusal_reasons",
    }
    if not isinstance(obj, dict) or set(obj) != fields or obj["schema"] != SCHEMA:
        raise ValueError("invalid action schema")
    if obj["kind"] not in ("request_analysis", "refuse") or wrapped != (
        obj["kind"] == "request_analysis"
    ):
        raise ValueError("invalid action representation")
    objective = _text(obj["objective"])
    analysis = _text(obj["analysis_class"], nullable=True)
    operation = _text(obj["operation"], nullable=True)
    observations = obj["observations"]
    reasons = obj["refusal_reasons"]
    if (
        not isinstance(observations, list)
        or len(observations) > MAX_OBSERVATIONS
        or not isinstance(reasons, list)
        or len(reasons) > 16
    ):
        raise ValueError("invalid action lists")
    selections = []
    for item in observations:
        if not isinstance(item, dict) or set(item) != {"reference", "unit"}:
            raise ValueError("invalid observation")
        reference = _text(item["reference"])
        unit = _text(item["unit"])
        if not re.fullmatch(r"observation-[1-9][0-9]*", reference or ""):
            raise ValueError("invalid observation reference")
        selections.append(projection.ObservationSelection(reference or "", unit or ""))
    if len({x.reference for x in selections}) != len(selections):
        raise ValueError("duplicate observation reference")
    parsed_reasons = tuple(_text(reason) or "" for reason in reasons)
    if obj["kind"] == "request_analysis" and (
        parsed_reasons or (operation is None and analysis is None)
    ):
        raise ValueError("invalid request")
    if obj["kind"] == "refuse" and (operation is not None or not parsed_reasons):
        raise ValueError("invalid refusal")
    return projection.ScientificAction(
        SCHEMA, obj["kind"], objective or "", analysis, operation, tuple(selections), parsed_reasons
    )


def action_content(example: ScientificExample) -> str:
    action = asdict(projection.action_target(example))
    action["schema"] = SCHEMA
    if example.call:
        return (
            _OPEN
            + json.dumps(
                {"name": "registered_science", "arguments": action},
                sort_keys=True,
                separators=(",", ":"),
            )
            + _CLOSE
        )
    return json.dumps(action, sort_keys=True, separators=(",", ":"))


class Interaction:
    """One closed trusted request, one action, and at most one executor event."""

    def __init__(self, example: ScientificExample, visible_request: str):
        validate_example(example)
        row = projection.project(example)
        if visible_request != row["messages"][1]["content"]:
            raise ValueError("request does not bind to trusted observations")
        self._example = example
        self._request = visible_request
        self._state = "await_action"
        self._event: ToolResponse | None = None

    def submit_action(self, content: str) -> ToolResponse | None:
        if self._state != "await_action":
            raise ValueError("action out of order")
        action = parse_action(content)
        expected = projection.action_target(self._example)
        # The closed catalogue is the authority for the objective and observation bindings.
        if asdict(action) != {**asdict(expected), "schema": SCHEMA}:
            raise ValueError("proposal does not match authorized task")
        if action.kind == "refuse":
            self._state = "refused"
            return None
        self._event = projection.execute_proposal(self._example, self._request, expected)
        self._state = "executed"
        return self._event

    def final_answer(self, event: object) -> str:
        if self._state != "executed" or event is not self._event:
            raise ValueError("unauthenticated or out-of-order executor event")
        self._state = "finished"
        answer = json.loads(self._example.messages_json)[-1]["content"]
        if not isinstance(answer, str):
            raise ValueError("invalid trusted answer")
        return answer


def qualification(tokenizer: Any) -> dict[str, Any]:
    """Construct replayable synthetic evidence using the pinned real template."""
    from dynamislm.serialization import canonical_hash
    from dynamislm.training_data.scientific_sft import generate_development_set

    dataset = generate_development_set()
    rows = []
    for example in dataset.examples:
        messages = [dict(message) for message in projection.project(example)["messages"]]
        messages[0]["content"] = SYSTEM
        messages[2]["content"] = action_content(example)
        interaction = Interaction(example, messages[1]["content"])
        event = interaction.submit_action(messages[2]["content"])
        if event is not None:
            interaction.final_answer(event)
        first = projection.token_labels(tokenizer, messages)
        if first != projection.token_labels(tokenizer, messages):
            raise ValueError("non-deterministic tokenization")
        rows.append(
            {"example_sha256": example.example_sha256, "messages": messages, "tokens": first}
        )
    return {
        "schema": "RES403-DEVELOPMENT-QUALIFICATION-1",
        "scope": "CLOSED_SYNTHETIC_CATALOGUE_ONLY",
        "training_authorized": False,
        "production_authorized": False,
        "v2_sha256": canonical_hash(dataset),
        "rows": rows,
    }


def main() -> None:
    import argparse
    from pathlib import Path

    from dynamislm.serialization import canonical_bytes
    from dynamislm.training_data.processing import require_external, sha256

    parser = argparse.ArgumentParser()
    parser.add_argument("--tokenizer-directory", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    artifact = qualification(projection.load_tokenizer(args.tokenizer_directory))
    artifact["implementation_sha256"] = sha256(Path(__file__).read_bytes())
    raw = canonical_bytes(artifact)
    root = require_external(args.output_root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = root / (sha256(raw).removeprefix("sha256:") + ".json")
    if path.exists():
        if path.is_symlink() or path.read_bytes() != raw:
            raise ValueError("artifact collision")
    else:
        with path.open("xb") as stream:
            stream.write(raw)
        path.chmod(0o600)
    print(path)


if __name__ == "__main__":
    main()
