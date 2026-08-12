# File: src/intraday/application/config_schema/universe.py
#
# Config schema and loader for domain.universe.Universe (Checkpoint 6).
# Instrument identity is derived via make_instrument_id (Checkpoint 5) —
# a config author supplies only a plain symbol string, never a raw
# instrument_id, keeping the derivation logic single-sourced.
from __future__ import annotations

from typing import Any

from intraday.application.config_schema.errors import ConfigValidationError
from intraday.application.config_schema.schema import ConfigSchema, build_schema_for
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.shared_kernel.contracts import Exchange, Version
from intraday.domain.universe.contracts import Universe, UniverseMember, UniverseMembershipStatus

UNIVERSE_SCHEMA: ConfigSchema = build_schema_for(Universe)


def load_universe(raw: dict[str, Any], *, source: str = "<config>") -> Universe:
    """Parse a raw config dict into a validated `Universe` instance.

    Expected shape:
        universe_id: str
        version: str
        exchange: "NSE" | "BSE"
        members: [{symbol: str, status?: "INCLUDED" | "EXCLUDED"}, ...]
    """
    try:
        exchange = Exchange(raw["exchange"])
        members = tuple(
            UniverseMember(
                instrument_id=make_instrument_id(exchange, member["symbol"]),
                status=UniverseMembershipStatus(member.get("status", "INCLUDED")),
            )
            for member in raw.get("members", [])
        )
        return Universe(
            universe_id=raw["universe_id"],
            version=Version(value=raw["version"]),
            exchange=exchange,
            members=members,
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise ConfigValidationError(source=source, original=exc) from exc
