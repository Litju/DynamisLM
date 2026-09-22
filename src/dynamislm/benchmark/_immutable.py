"""Small immutable containers used by the benchmark contracts."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import cast


class FrozenMap(Mapping[str, object]):
    """An insertion-independent, recursively frozen string-keyed mapping."""

    __slots__ = ("_items", "_values")

    def __init__(self, value: Mapping[str, object] | None = None) -> None:
        if value is None:
            value = {}
        if any(not isinstance(key, str) for key in value):
            raise TypeError("benchmark mappings require string keys")
        items = tuple(
            sorted(
                ((key, freeze_data(item)) for key, item in value.items()),
                key=lambda item: item[0].encode("utf-8"),
            )
        )
        self._items = items
        self._values = dict(items)

    def __getitem__(self, key: str) -> object:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return (key for key, _ in self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __repr__(self) -> str:
        return f"FrozenMap({dict(self._items)!r})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, FrozenMap):
            return self._items == other._items
        if isinstance(other, Mapping):
            return dict(self._items) == dict(other)
        return NotImplemented


def freeze_data(value: object) -> object:
    """Recursively freeze mappings and sequences used in case payloads."""

    if isinstance(value, FrozenMap):
        return value
    if isinstance(value, Mapping):
        return FrozenMap(cast(Mapping[str, object], value))
    if isinstance(value, tuple | list):
        return tuple(freeze_data(item) for item in value)
    if isinstance(value, set | frozenset):
        raise TypeError("benchmark contracts require ordered tuples, not sets")
    return value


def freeze_mapping(value: Mapping[str, object], field_name: str) -> FrozenMap:
    """Freeze a required mapping and provide a field-specific error."""

    try:
        return FrozenMap(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a string-keyed mapping") from exc
