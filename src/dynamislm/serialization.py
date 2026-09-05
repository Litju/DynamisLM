"""Versioned canonical JSON serialization for immutable scientific contracts."""

from __future__ import annotations

import dataclasses
import datetime as datetime_module
import enum
import hashlib
import json
import math
import types
from collections.abc import Mapping, Sequence
from typing import Any, TypeAliasType, Union, cast, get_args, get_origin, get_type_hints

SERIALIZATION_VERSION = 3
SerializableType = type[Any]


class SerializationError(ValueError):
    """Raised when a contract cannot be encoded or decoded deterministically."""


_TYPE_REGISTRY: dict[str, SerializableType] = {}


def type_identifier(cls: SerializableType) -> str:
    """Return the stable package-qualified type name used in wire envelopes."""

    return f"{cls.__module__}.{cls.__qualname__}"


def register_serializable_type[T](cls: type[T]) -> type[T]:
    """Register a public dataclass so polymorphic values can be restored."""

    identifier = type_identifier(cls)
    existing = _TYPE_REGISTRY.get(identifier)
    if existing is not None and existing is not cls:
        raise SerializationError(f"duplicate serialization type identifier: {identifier}")
    _TYPE_REGISTRY[identifier] = cls
    return cls


def _finite_float(value: float) -> float:
    if not math.isfinite(value):
        raise SerializationError("NaN and Infinity are forbidden in canonical scientific data")
    return value


def canonical_data(value: object) -> object:
    """Convert supported values to JSON-compatible canonical data."""

    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return _finite_float(value)
    if isinstance(value, enum.Enum):
        return canonical_data(value.value)
    if isinstance(value, datetime_module.datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise SerializationError("datetimes must include an explicit timezone")
        utc_value = value.astimezone(datetime_module.UTC)
        return utc_value.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        fields = {
            field.name: canonical_data(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
        fields["__type__"] = type_identifier(type(value))
        return fields
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise SerializationError("canonical mappings require string keys")
            result[key] = canonical_data(item)
        return result
    if isinstance(value, tuple | list):
        return [canonical_data(item) for item in value]
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray | str):
        return [canonical_data(item) for item in value]
    raise SerializationError(f"unsupported value for canonical serialization: {type(value)!r}")


def canonical_json(value: object) -> str:
    """Serialize a core contract using a versioned, sorted-key JSON envelope."""

    payload = canonical_data(value)
    envelope = {
        "payload": payload,
        "serialization_version": SERIALIZATION_VERSION,
        "type": type_identifier(type(value)),
    }
    try:
        return json.dumps(
            envelope,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise SerializationError("value is not canonically serializable") from exc


def canonical_bytes(value: object) -> bytes:
    """Return the exact UTF-8 bytes used for hashing."""

    return canonical_json(value).encode("utf-8")


def canonical_hash(value: object) -> str:
    """Return the explicit SHA-256 digest of canonical UTF-8 JSON bytes."""

    digest = hashlib.sha256(canonical_bytes(value)).hexdigest()
    return f"sha256:{digest}"


def _decode_datetime(value: object) -> datetime_module.datetime:
    if not isinstance(value, str):
        raise SerializationError("datetime wire value must be a string")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime_module.datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise SerializationError(f"invalid datetime: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SerializationError("decoded datetime must include an explicit timezone")
    return parsed


def _decode_dynamic(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _decode_dynamic(item) for key, item in value.items() if key != "__type__"}
    if isinstance(value, list):
        return [_decode_dynamic(item) for item in value]
    return value


def _is_none_type(annotation: object) -> bool:
    return annotation is type(None)


def _decode_union(value: object, annotations: tuple[object, ...]) -> object:
    if value is None and any(_is_none_type(annotation) for annotation in annotations):
        return None
    if isinstance(value, dict):
        marker = value.get("__type__")
        if isinstance(marker, str):
            actual = _TYPE_REGISTRY.get(marker)
            if actual is not None:
                for annotation in annotations:
                    if isinstance(annotation, type) and actual is annotation:
                        return _decode_dataclass(value, actual)
    for annotation in annotations:
        if isinstance(annotation, type) and type(value) is annotation:
            return _decode_value(value, annotation)
    errors: list[Exception] = []
    for annotation in annotations:
        if _is_none_type(annotation):
            continue
        try:
            return _decode_value(value, annotation)
        except (SerializationError, TypeError, ValueError) as exc:
            errors.append(exc)
    detail = "; ".join(str(error) for error in errors)
    raise SerializationError(f"could not decode union value ({detail})")


def _decode_dataclass(value: object, cls: SerializableType) -> object:
    if not isinstance(value, dict):
        raise SerializationError(f"{type_identifier(cls)} must decode from an object")
    marker = value.get("__type__")
    target_cls = cls
    if marker is not None and marker != type_identifier(cls):
        if not isinstance(marker, str):
            raise SerializationError("dataclass type marker must be a string")
        registered = _TYPE_REGISTRY.get(marker)
        if registered is None or not issubclass(registered, cls):
            raise SerializationError(
                f"type marker {marker!r} does not match {type_identifier(cls)}"
            )
        target_cls = registered
    fields = {field.name: field for field in dataclasses.fields(target_cls)}
    unexpected = set(value) - set(fields) - {"__type__"}
    if unexpected:
        raise SerializationError(
            f"unexpected fields for {type_identifier(target_cls)}: {sorted(unexpected)}"
        )
    hints = get_type_hints(target_cls)
    kwargs = {
        field.name: _decode_value(value[field.name], hints[field.name])
        for field in fields.values()
        if field.name in value
    }
    legacy_decoder = getattr(target_cls, "__decode_legacy_wire__", None)
    if legacy_decoder is not None:
        decoded_kwargs = legacy_decoder(value, kwargs)
        if not isinstance(decoded_kwargs, dict):
            raise SerializationError(
                f"legacy decoder for {type_identifier(target_cls)} must return a mapping"
            )
        kwargs = decoded_kwargs
    unexpected_decoded = set(kwargs) - set(fields)
    if unexpected_decoded:
        raise SerializationError(
            f"unexpected fields for {type_identifier(target_cls)}: {sorted(unexpected_decoded)}"
        )
    missing = sorted(set(fields) - set(kwargs))
    if missing:
        raise SerializationError(f"missing fields for {type_identifier(target_cls)}: {missing}")
    try:
        return target_cls(**kwargs)
    except (TypeError, ValueError) as exc:
        raise SerializationError(f"invalid {type_identifier(target_cls)} payload") from exc


def _decode_value(value: object, annotation: object) -> object:
    if isinstance(annotation, TypeAliasType):
        annotation = annotation.__value__
    if annotation is Any or annotation is object:
        return _decode_dynamic(value)
    origin = get_origin(annotation)
    if origin in (types.UnionType, Union):
        return _decode_union(value, get_args(annotation))
    if value is None:
        if annotation is type(None):
            return None
        raise SerializationError(f"null is not valid for {annotation!r}")
    if annotation is datetime_module.datetime:
        return _decode_datetime(value)
    if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        try:
            return annotation(value)
        except ValueError as exc:
            raise SerializationError(f"invalid {annotation.__name__} value: {value!r}") from exc
    if isinstance(annotation, type) and dataclasses.is_dataclass(annotation):
        return _decode_dataclass(value, annotation)
    if origin is tuple:
        args = get_args(annotation)
        if not isinstance(value, list):
            raise SerializationError("tuple wire value must be an array")
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(_decode_value(item, args[0]) for item in value)
        if len(args) != len(value):
            raise SerializationError("fixed-length tuple has the wrong number of values")
        return tuple(
            _decode_value(item, item_type) for item, item_type in zip(value, args, strict=True)
        )
    if origin is list:
        args = get_args(annotation)
        if not isinstance(value, list) or len(args) != 1:
            raise SerializationError("list wire value does not match its annotation")
        return [_decode_value(item, args[0]) for item in value]
    if origin in (dict, Mapping):
        args = get_args(annotation)
        if len(args) != 2 or not isinstance(value, dict):
            raise SerializationError("mapping wire value does not match its annotation")
        return {
            _decode_value(key, args[0]): _decode_value(item, args[1]) for key, item in value.items()
        }
    if annotation is bool:
        if not isinstance(value, bool):
            raise SerializationError("boolean wire value required")
        return value
    if annotation is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise SerializationError("integer wire value required")
        return value
    if annotation is float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise SerializationError("numeric wire value required")
        return _finite_float(float(value))
    if annotation is str:
        if not isinstance(value, str):
            raise SerializationError("string wire value required")
        return value
    raise SerializationError(f"unsupported decode annotation: {annotation!r}")


def from_canonical_json[T](serialized: str, cls: type[T]) -> T:
    """Restore a registered core dataclass from its canonical JSON envelope."""

    try:
        envelope = json.loads(serialized)
    except json.JSONDecodeError as exc:
        raise SerializationError("invalid canonical JSON") from exc
    if not isinstance(envelope, dict):
        raise SerializationError("canonical JSON envelope must be an object")
    if envelope.get("serialization_version") != SERIALIZATION_VERSION:
        raise SerializationError("unsupported serialization version")
    expected_type = type_identifier(cls)
    envelope_type = envelope.get("type")
    if envelope_type != expected_type:
        if not isinstance(envelope_type, str):
            raise SerializationError(
                f"canonical type {envelope_type!r} does not match {expected_type!r}"
            )
        registered = _TYPE_REGISTRY.get(envelope_type)
        if registered is None or not issubclass(registered, cls):
            raise SerializationError(
                f"canonical type {envelope_type!r} does not match {expected_type!r}"
            )
    if "payload" not in envelope:
        raise SerializationError("canonical JSON envelope has no payload")
    decoded = _decode_dataclass(envelope["payload"], cls)
    return cast(T, decoded)
