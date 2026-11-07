"""The frozen Serialization V3 action prompt contract for A0.2 new cases."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from dynamislm.serialization import canonical_json
from scripts import res403_tool_protocol

ACTION_TEMPLATE_DATE = datetime(2026, 11, 3, tzinfo=UTC)


def prompt_token_ids_sha256(token_ids: list[int]) -> str:
    return hashlib.sha256(canonical_json(token_ids).encode("utf-8")).hexdigest()


def build_action_messages(request: object, system_prompt: str) -> list[dict[str, str]]:
    request_text = canonical_json(request)
    user_message = res403_tool_protocol.render_transcript(
        [res403_tool_protocol.UntrustedUserInputEvent(request_text)]
    )[0]
    return [{"role": "system", "content": system_prompt}, user_message]


def build_action_prompt(tokenizer: Any, request: object, system_prompt: str) -> dict[str, Any]:
    messages = build_action_messages(request, system_prompt)
    kwargs = {
        "enable_thinking": False,
        "strftime_now": ACTION_TEMPLATE_DATE.strftime,
    }
    token_ids = tokenizer.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=True, **kwargs
    )
    rendered = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True, **kwargs
    )
    if tokenizer.encode(rendered, add_special_tokens=False) != token_ids:
        raise ValueError("official Jinja rendering does not reproduce tokenizer IDs")
    return {
        "messages": messages,
        "rendered_prompt": rendered,
        "rendered_prompt_sha256": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
        "prompt_token_ids": token_ids,
        "prompt_token_ids_sha256": prompt_token_ids_sha256(token_ids),
        "prompt_tokens": len(token_ids),
    }


def verify_frozen_prompt(
    rendered: str, token_ids: list[int], frozen: dict[str, Any], case_id: str
) -> None:
    actual = {
        "rendered_prompt": rendered,
        "rendered_prompt_sha256": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
        "prompt_token_ids": token_ids,
        "prompt_token_ids_sha256": prompt_token_ids_sha256(token_ids),
        "prompt_tokens": len(token_ids),
    }
    if any(actual[key] != frozen.get(key) for key in actual):
        raise ValueError(f"action prompt differs from frozen input contract: {case_id}")
