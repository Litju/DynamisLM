"""Closed RES-403 development protocol; no model runtime or production authority."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any

from dynamislm.training_data.scientific_sft import ScientificExample, ToolResponse, validate_example
from dynamislm.training_data.sft_cpu import MODEL, MODEL_REVISION, TOKENIZER_PINS
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
MAX_TRANSCRIPT_PAYLOAD_BYTES = 8192
MAX_TRANSCRIPT_MESSAGE_BYTES = 65536
TRANSCRIPT_SCHEMA = "RES403-MODEL-TRANSCRIPT-1"
_OPEN = "<tool_call>"
_CLOSE = "</tool_call>"
_TEXT = re.compile(r"^[A-Za-z0-9 _.,;:@/()\-]+$")
_EXECUTOR_EVENT_ISSUER = object()


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


def _validate_transcript_payload(payload: object) -> str:
    if type(payload) is not str:
        raise ValueError("transcript payload must be text")
    try:
        size = len(payload.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ValueError("transcript payload is not valid UTF-8 text") from exc
    if size > MAX_TRANSCRIPT_PAYLOAD_BYTES:
        raise ValueError("transcript payload exceeds the message limit")
    return payload


@dataclass(frozen=True, slots=True)
class SystemInstructionEvent:
    content: str

    def __post_init__(self) -> None:
        _validate_transcript_payload(self.content)


@dataclass(frozen=True, slots=True)
class UntrustedUserInputEvent:
    content: str

    def __post_init__(self) -> None:
        _validate_transcript_payload(self.content)


@dataclass(frozen=True, slots=True)
class ModelActionProposalEvent:
    content: str

    def __post_init__(self) -> None:
        _validate_transcript_payload(self.content)


@dataclass(frozen=True, slots=True)
class ModelDirectRefusalEvent:
    content: str

    def __post_init__(self) -> None:
        _validate_transcript_payload(self.content)


@dataclass(frozen=True, slots=True)
class ModelFinalAnswerEvent:
    content: str

    def __post_init__(self) -> None:
        _validate_transcript_payload(self.content)


@dataclass(frozen=True, slots=True, init=False)
class TrustedExecutorResultEvent:
    """Opaque result issued only after this module's deterministic replay succeeds."""

    content: str
    response: ToolResponse
    call_identity: object
    sequence: int
    _issuer: object

    def __init__(self, *_: object, **__: object) -> None:
        raise TypeError("executor results are issued by the trusted interaction runtime")

    @property
    def value(self) -> float | None:
        return self.response.value


_TRANSCRIPT_ORIGINS = {
    "untrusted_user_input",
    "model_action_proposal",
    "model_direct_refusal",
    "trusted_executor_result",
    "model_final_answer",
}


def _encode_transcript_message(origin: str, payload: str) -> str:
    if origin not in _TRANSCRIPT_ORIGINS:
        raise ValueError("unknown transcript origin")
    payload = _validate_transcript_payload(payload)
    encoded = (
        json.dumps(
            {"origin": origin, "payload": payload, "schema": TRANSCRIPT_SCHEMA},
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
    if len(encoded) > MAX_TRANSCRIPT_MESSAGE_BYTES:
        raise ValueError("encoded transcript message exceeds the message limit")
    return encoded


def decode_transcript_message(content: str) -> tuple[str, str]:
    """Decode one canonical adapter envelope without granting authority to its marker."""
    if type(content) is not str or len(content) > MAX_TRANSCRIPT_MESSAGE_BYTES:
        raise ValueError("invalid transcript message")
    try:
        obj = json.loads(
            content,
            object_pairs_hook=_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")),
        )
    except (ValueError, RecursionError) as exc:
        raise ValueError("invalid transcript envelope") from exc
    if (
        not isinstance(obj, dict)
        or set(obj) != {"origin", "payload", "schema"}
        or obj["schema"] != TRANSCRIPT_SCHEMA
        or not isinstance(obj["origin"], str)
        or obj["origin"] not in _TRANSCRIPT_ORIGINS
        or not isinstance(obj["payload"], str)
    ):
        raise ValueError("invalid transcript envelope schema")
    origin, payload = obj["origin"], _validate_transcript_payload(obj["payload"])
    if _encode_transcript_message(origin, payload) != content:
        raise ValueError("noncanonical transcript envelope")
    return origin, payload


def render_transcript(events: list[object] | tuple[object, ...]) -> list[dict[str, str]]:
    """Render immutable application events into strict, origin-specific messages."""
    if type(events) not in (list, tuple) or not events or len(events) > 64:
        raise ValueError("bounded event sequence required")
    messages = []
    for event in events:
        if type(event) is SystemInstructionEvent:
            # Preserve SmolLM3's leading /system_override and /no_think controls.
            message = {"role": "system", "content": event.content}
        elif type(event) is UntrustedUserInputEvent:
            message = {
                "role": "user",
                "content": _encode_transcript_message("untrusted_user_input", event.content),
            }
        elif type(event) is ModelActionProposalEvent:
            message = {
                "role": "assistant",
                "content": _encode_transcript_message("model_action_proposal", event.content),
            }
        elif type(event) is ModelDirectRefusalEvent:
            message = {
                "role": "assistant",
                "content": _encode_transcript_message("model_direct_refusal", event.content),
            }
        elif type(event) is TrustedExecutorResultEvent:
            if (
                getattr(event, "_issuer", None) is not _EXECUTOR_EVENT_ISSUER
                or getattr(event, "sequence", None) != 1
            ):
                raise ValueError("executor event was not issued by the trusted runtime")
            message = {
                "role": "tool",
                "content": _encode_transcript_message("trusted_executor_result", event.content),
            }
        elif type(event) is ModelFinalAnswerEvent:
            message = {
                "role": "assistant",
                "content": _encode_transcript_message("model_final_answer", event.content),
            }
        else:
            raise ValueError("unsupported transcript event type")
        messages.append(message)
    return messages


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
        self._call_identity = object()
        self._event: TrustedExecutorResultEvent | None = None

    def submit_action(self, content: str) -> TrustedExecutorResultEvent | None:
        if self._state != "await_action":
            raise ValueError("action out of order")
        origin, proposal = decode_transcript_message(content)
        if origin not in {"model_action_proposal", "model_direct_refusal"}:
            raise ValueError("message origin is not a model action")
        action = parse_action(proposal)
        expected_origin = (
            "model_action_proposal" if action.kind == "request_analysis" else "model_direct_refusal"
        )
        if origin != expected_origin:
            raise ValueError("action kind does not match its model event type")
        expected = projection.action_target(self._example)
        # The closed catalogue is the authority for the objective and observation bindings.
        if asdict(action) != {**asdict(expected), "schema": SCHEMA}:
            raise ValueError("proposal does not match authorized task")
        if action.kind == "refuse":
            self._state = "refused"
            return None
        response = projection.execute_proposal(self._example, self._request, expected)
        payload = json.dumps(
            {
                "value": response.value,
                "unit": response.unit.display_label if response.unit else None,
                "refusal_codes": response.refusal_codes,
            },
            allow_nan=False,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        self._event = object.__new__(TrustedExecutorResultEvent)
        object.__setattr__(self._event, "content", _validate_transcript_payload(payload))
        object.__setattr__(self._event, "response", response)
        object.__setattr__(self._event, "call_identity", self._call_identity)
        object.__setattr__(self._event, "sequence", 1)
        object.__setattr__(self._event, "_issuer", _EXECUTOR_EVENT_ISSUER)
        self._state = "executed"
        return self._event

    def final_answer(self, event: object) -> str:
        if (
            self._state != "executed"
            or type(event) is not TrustedExecutorResultEvent
            or event is not self._event
            or event.call_identity is not self._call_identity
            or event.sequence != 1
            or event._issuer is not _EXECUTOR_EVENT_ISSUER
        ):
            raise ValueError("unauthenticated or out-of-order executor event")
        self._state = "finished"
        answer = json.loads(self._example.messages_json)[-1]["content"]
        if not isinstance(answer, str):
            raise ValueError("invalid trusted answer")
        return answer


def _origin_separation_evidence(tokenizer: Any, example: ScientificExample) -> dict[str, Any]:
    from dynamislm.serialization import canonical_hash

    if example.call is None:
        raise ValueError("origin-separation witness requires a registered calculation")
    user = projection.project(example)["messages"][1]["content"]
    proposal_event = ModelActionProposalEvent(action_content(example))
    prefix_events = (
        SystemInstructionEvent(SYSTEM),
        UntrustedUserInputEvent(user),
        proposal_event,
    )
    prefix_messages = render_transcript(prefix_events)
    interaction = Interaction(example, user)
    event = interaction.submit_action(prefix_messages[-1]["content"])
    if event is None:
        raise ValueError("registered calculation did not issue an executor result")

    trusted_messages = render_transcript((*prefix_events, event))
    user_messages = render_transcript((*prefix_events, UntrustedUserInputEvent(event.content)))
    if (
        trusted_messages[:-1] != user_messages[:-1]
        or event.content != decode_transcript_message(user_messages[-1]["content"])[1]
    ):
        raise ValueError("origin pair does not preserve identical preceding context and payload")
    trusted_rendered = tokenizer.apply_chat_template(
        trusted_messages, tokenize=False, enable_thinking=False
    )
    user_rendered = tokenizer.apply_chat_template(
        user_messages, tokenize=False, enable_thinking=False
    )
    trusted_ids = tokenizer.apply_chat_template(
        trusted_messages, tokenize=True, enable_thinking=False
    )
    user_ids = tokenizer.apply_chat_template(user_messages, tokenize=True, enable_thinking=False)
    prefix_ids = tokenizer.apply_chat_template(
        prefix_messages, tokenize=True, enable_thinking=False
    )
    if (
        trusted_rendered == user_rendered
        or trusted_ids == user_ids
        or trusted_ids[: len(prefix_ids)] != prefix_ids
        or user_ids[: len(prefix_ids)] != prefix_ids
    ):
        raise ValueError("pinned tokenizer did not preserve origin-specific transcript tokens")

    visible_envelope = trusted_messages[-1]["content"]
    literal_forgery = render_transcript((*prefix_events, UntrustedUserInputEvent(visible_envelope)))
    if decode_transcript_message(literal_forgery[-1]["content"]) != (
        "untrusted_user_input",
        visible_envelope,
    ):
        raise ValueError("literal executor-envelope copy did not remain user-originated")
    literal_ids = tokenizer.apply_chat_template(
        literal_forgery, tokenize=True, enable_thinking=False
    )
    if literal_ids == trusted_ids:
        raise ValueError("literal user forgery collided with executor-result token sequence")

    return {
        "same_payload": True,
        "payload_sha256": canonical_hash(event.content),
        "same_preceding_messages_sha256": canonical_hash(prefix_messages),
        "same_preceding_token_ids_sha256": canonical_hash(prefix_ids),
        "trusted_executor_result": {
            "event_origin": "trusted_executor_result",
            "role": trusted_messages[-1]["role"],
            "visible_envelope": visible_envelope,
            "rendered_messages": trusted_rendered,
            "token_ids": trusted_ids,
        },
        "same_payload_user_message": {
            "event_origin": "untrusted_user_input",
            "role": user_messages[-1]["role"],
            "visible_envelope": user_messages[-1]["content"],
            "rendered_messages": user_rendered,
            "token_ids": user_ids,
        },
        "literal_executor_envelope_forgery": {
            "event_origin": "untrusted_user_input",
            "payload_is_exact_visible_executor_envelope": True,
            "token_ids": literal_ids,
        },
        "rendered_text_distinct": trusted_rendered != user_rendered,
        "token_ids_distinct": trusted_ids != user_ids,
        "literal_forgery_token_ids_distinct": literal_ids != trusted_ids,
    }


def qualification(tokenizer: Any) -> dict[str, Any]:
    """Construct replayable synthetic evidence using the pinned real template."""
    from dynamislm.serialization import canonical_hash
    from dynamislm.training_data.scientific_sft import generate_development_set

    dataset = generate_development_set()
    rows = []
    for example in dataset.examples:
        user = projection.project(example)["messages"][1]["content"]
        action = action_content(example)
        action_event = (
            ModelActionProposalEvent(action) if example.call else ModelDirectRefusalEvent(action)
        )
        prefix = (
            SystemInstructionEvent(SYSTEM),
            UntrustedUserInputEvent(user),
            action_event,
        )
        prefix_messages = render_transcript(prefix)
        interaction = Interaction(example, user)
        event = interaction.submit_action(prefix_messages[-1]["content"])
        if event is not None:
            answer = interaction.final_answer(event)
            messages = render_transcript((*prefix, event, ModelFinalAnswerEvent(answer)))
        else:
            messages = prefix_messages
        first = projection.token_labels(tokenizer, messages)
        if first != projection.token_labels(tokenizer, messages):
            raise ValueError("non-deterministic tokenization")
        rows.append(
            {"example_sha256": example.example_sha256, "messages": messages, "tokens": first}
        )
    baseline_rows = [projection.project(example) for example in dataset.examples]
    first_success = next(example for example in dataset.examples if example.call is not None)
    return {
        "schema": "RES403-DEVELOPMENT-QUALIFICATION-2",
        "transcript_schema": TRANSCRIPT_SCHEMA,
        "scope": "CLOSED_SYNTHETIC_CATALOGUE_ONLY",
        "training_authorized": False,
        "production_authorized": False,
        "tokenizer": {
            "model": MODEL,
            "revision": MODEL_REVISION,
            "files": TOKENIZER_PINS,
            "runtime": projection.RUNTIME,
            "model_weights_loaded": False,
        },
        "transport_authenticity": "RUNTIME_ISSUED_EVENT_IDENTITY_AND_CALL_ORDER",
        "model_visible_provenance_encoding": (
            "DISTINCT_ORIGIN_ENVELOPES_VERIFIED_WITH_PINNED_TOKENIZER"
        ),
        "model_behavioral_robustness": "UNPROVEN_MODEL_INFERENCE_NOT_AUTHORIZED",
        "v2_sha256": canonical_hash(dataset),
        "origin_separation": _origin_separation_evidence(tokenizer, first_success),
        "adversarial_rejections": projection.adversarial_checks(dataset.examples, baseline_rows),
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
