"""Tiny JSON <-> dataclass (de)serialization.

Stdlib-only. The JSON files in the memory bank are the source of truth; these
dataclasses are just typed, validated convenience wrappers over them. `from_dict`
is deliberately forgiving — unknown keys are ignored and missing keys fall back to
each field's default — so hand-edited or LLM-authored files still load.
"""
from __future__ import annotations

import dataclasses
import typing


def _is_dataclass_type(t) -> bool:
    return isinstance(t, type) and dataclasses.is_dataclass(t)


def to_dict(obj):
    """Dataclass (possibly nested) -> plain dict/list JSON tree."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    return obj


def from_dict(cls, data):
    """Build a dataclass instance from a plain dict, recursively.

    Ignores keys the dataclass doesn't declare; leaves declared-but-absent keys
    to their field defaults.
    """
    if data is None:
        return None
    hints = typing.get_type_hints(cls)
    kwargs = {}
    for f in dataclasses.fields(cls):
        if f.name not in data:
            continue  # use the field's default / default_factory
        kwargs[f.name] = _convert(hints.get(f.name), data[f.name])
    return cls(**kwargs)


def _convert(typ, raw):
    origin = typing.get_origin(typ)
    args = typing.get_args(typ)

    # Optional[X] / Union[...]
    if origin is typing.Union:
        non_none = [a for a in args if a is not type(None)]
        if raw is None:
            return None
        if len(non_none) == 1:
            return _convert(non_none[0], raw)
        return raw

    if origin in (list, typing.List):
        inner = args[0] if args else None
        if inner and _is_dataclass_type(inner):
            return [from_dict(inner, x) for x in raw]
        return list(raw)

    if origin in (dict, typing.Dict):
        return dict(raw)

    if _is_dataclass_type(typ):
        return from_dict(typ, raw)

    return raw
