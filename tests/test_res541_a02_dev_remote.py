from __future__ import annotations

from typing import Any

import pytest
from scripts import a02_dev_protocol, a02_dev_remote


def test_remote_generator_passes_native_tool_schema_and_enforces_profile_prompt_limit() -> None:
    class TensorRow:
        def tolist(self) -> list[int]:
            return [101, 102]

    class TensorBatch:
        def __getitem__(self, _index: int) -> TensorRow:
            return TensorRow()

    class RuntimeTokenizer:
        def __init__(self) -> None:
            self.tool_schemas: list[Any] = []

        def apply_chat_template(self, _messages: Any, *, tokenize: bool, **kwargs: Any) -> Any:
            self.tool_schemas.append(kwargs.get("xml_tools"))
            if not tokenize:
                return "<rendered>"
            return {"input_ids": TensorBatch()}

        def encode(self, _rendered: str, *, add_special_tokens: bool) -> list[int]:
            assert add_special_tokens is False
            return [101, 102]

    class RuntimeModel:
        def generate(self, **_kwargs: Any) -> None:
            raise AssertionError("generation must stop when the V2 prompt is over its bound")

    tokenizer = RuntimeTokenizer()
    schema = a02_dev_protocol.tool_schema()
    with pytest.raises(ValueError, match="exceeds its 1-token bound"):
        a02_dev_remote._generate(
            RuntimeModel(),
            tokenizer,
            object(),
            [{"role": "system", "content": "synthetic"}],
            cap=256,
            template_date=a02_dev_protocol.ACTION_TEMPLATE_DATE,
            prompt_limit=1,
            xml_tools=[schema],
        )
    assert tokenizer.tool_schemas == [[schema], [schema]]
