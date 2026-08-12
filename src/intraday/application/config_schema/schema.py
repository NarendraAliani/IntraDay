# File: src/intraday/application/config_schema/schema.py
#
# Generic config-schema derivation machinery (Checkpoint 6).
#
# Core rule (Checkpoint 2 §8 / Rule 13): a config schema must DERIVE its
# field definitions from the corresponding domain contract via
# introspection — never redefine a parameter's type/range independently.
# This module provides that introspection machinery exactly once, so every
# concrete schema (risk.py, universe.py, strategy.py) reuses it instead of
# hand-listing field names/types that could silently drift from the
# domain contract they describe.
#
# This is metadata only — it does NOT perform or replace domain
# validation. Actual invariant enforcement always happens inside the
# domain contract's own `__post_init__` when a loader (risk.py etc.)
# constructs the real dataclass; ConfigSchema exists so a future frontend
# form generator (Checkpoint 3 §9 pipeline) has something to introspect
# without duplicating field definitions by hand.
from __future__ import annotations

import dataclasses
import decimal
import enum
from dataclasses import dataclass
from types import UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints


@dataclass(frozen=True, slots=True)
class ConfigFieldSchema:
    """Describes one configurable field, DERIVED from a domain dataclass
    field — never hand-written independently of the domain contract."""

    name: str
    python_type: type[Any]
    required: bool
    is_decimal: bool
    enum_choices: tuple[str, ...] | None


@dataclass(frozen=True, slots=True)
class ConfigSchema:
    """The full set of configurable fields for one domain contract,
    identified by the contract's own class name — traceable back to
    exactly one domain type, never a schema invented independently of
    one."""

    contract_name: str
    fields: tuple[ConfigFieldSchema, ...]

    def field_names(self) -> tuple[str, ...]:
        return tuple(field.name for field in self.fields)

    def required_field_names(self) -> tuple[str, ...]:
        return tuple(field.name for field in self.fields if field.required)


def _unwrap_optional(annotation: Any) -> tuple[Any, bool]:
    """If `annotation` is `X | None` (or `Optional[X]`), return `(X, True)`;
    otherwise return `(annotation, False)` unchanged. Only a single-member
    union with `None` is unwrapped — anything more exotic is left as-is
    rather than guessed at."""
    origin = get_origin(annotation)
    if origin is UnionType or origin is Union:
        args = [arg for arg in get_args(annotation) if arg is not type(None)]
        if len(args) == 1:
            return args[0], True
    return annotation, False


def build_schema_for(domain_type: type[Any]) -> ConfigSchema:
    """Derive a `ConfigSchema` by introspecting `domain_type`'s dataclass
    fields. This is the ONLY mechanism config schemas are built with in
    this codebase — no module in this package hand-lists a field
    name/type that isn't sourced from here."""
    if not dataclasses.is_dataclass(domain_type):
        raise TypeError(
            f"{domain_type!r} is not a dataclass — cannot derive a config schema from it"
        )

    hints = get_type_hints(domain_type)
    fields: list[ConfigFieldSchema] = []
    for f in dataclasses.fields(domain_type):
        annotation: Any = hints.get(f.name, f.type)
        has_default = f.default is not dataclasses.MISSING or (
            f.default_factory is not dataclasses.MISSING
        )
        resolved_type, is_optional = _unwrap_optional(annotation)
        is_decimal = resolved_type is decimal.Decimal
        enum_choices: tuple[str, ...] | None = None
        if isinstance(resolved_type, type) and issubclass(resolved_type, enum.Enum):
            enum_choices = tuple(member.name for member in resolved_type)
        fields.append(
            ConfigFieldSchema(
                name=f.name,
                python_type=resolved_type if isinstance(resolved_type, type) else object,
                required=not has_default and not is_optional,
                is_decimal=is_decimal,
                enum_choices=enum_choices,
            )
        )
    return ConfigSchema(contract_name=domain_type.__name__, fields=tuple(fields))
