# config/universe

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

Tradable universe configuration (NSE; Rule 2 as restated at Checkpoint 64.77 — NSE stock options are the primary tradable instrument, NSE cash equities are supported as underlying/reference instruments; the option universe is resolved from the instrument master, not from this file). **Implemented at Checkpoint 6:** `example.yaml` is an illustrative instance loaded/validated via `application/config_schema/universe.py` — see [CONFIGURATION_MANAGEMENT.md](../../docs/architecture/CONFIGURATION_MANAGEMENT.md). Not an authoritative or production universe definition.

## Depends On

domain/universe

## Must Not Depend On

Derivatives/other-asset universes

