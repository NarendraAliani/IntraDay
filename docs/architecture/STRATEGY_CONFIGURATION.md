# Strategy Configuration: Persistence, API, Frontend (Checkpoint 26)

See [STRATEGY_ENGINE_ARCHITECTURE.md](STRATEGY_ENGINE_ARCHITECTURE.md)
for the domain/execution design this layers on top of.

## Persistence

`infrastructure.persistence.models.StrategyConfigurationRecord` - one
immutable row per `(strategy_id, specification_version, code_version,
configuration_version)` identity, `parameter_values` a single JSONField
(mirroring `UniverseVersion.members`'s established precedent: a
configuration is read/written as one atomic unit). **Append-only** -
`DjangoStrategyConfigurationRepository.save()` raises
`DuplicateVersionError` (translated to HTTP 409) if the identity already
exists; there is no update path. A materially different configuration
must be saved under a new `configuration_version` label.

This is **layered alongside**, not instead of,
`StrategyVersionRecord`/`ActiveStrategyVersion` (Checkpoint 8/13), which
remain the version-identity/activation-pointer records and are
completely unchanged by this checkpoint. `StrategyVersionService`'s
existing `activate()` (with its `actor`/`actor_user_id`/`request_id`
audit trail) still governs which version identity is "active" for a
`strategy_id`; `StrategyConfigurationService` is a separate concern
(what values a `configuration_version` label actually contains).

## Configuration identity (Part 12)

Identity is the 4-tuple, never the parameter values themselves:

- Same strategy + same parameters + same `configuration_version` ->
  same identity (saving twice raises `DuplicateVersionError`).
- Same strategy + different parameters -> must use a different
  `configuration_version` (values are never silently overwritten).
- Different `code_version` or `specification_version`, same
  `configuration_version` label -> a **different** identity (proven by
  `test_different_code_version_is_a_different_identity`/
  `test_different_specification_version_is_a_different_identity`).

## API surface

Mounted under `/api/v1/config/strategy-engine/`:

| Method | Path | Purpose |
|---|---|---|
| GET | `fields/` | Canonical field registry |
| GET | `strategies/` | Authoritative strategy list (registry-backed) |
| GET | `strategies/<id>/schema/` | That strategy's parameter schema |
| GET | `strategies/<id>/configurations/` | Saved configurations for that strategy |
| GET | `strategies/<id>/configurations/<spec>/<code>/<cfg>/` | One configuration |
| POST | `strategies/<id>/configurations/save/` | Validate + persist (requires `configuration.activate`) |

All read endpoints require authentication only; `save` additionally
requires the existing `configuration-operators` group (RBAC reuse,
Checkpoint 22's own established pattern - no new permission class).
OpenAPI schema (`manage.py spectacular --fail-on-warn`) generates
cleanly and byte-for-byte identically across repeated runs (verified
this checkpoint by diffing two independent generations).

## Frontend: one generic renderer, not per-strategy forms (Part 13/18)

`frontend/src/features/strategy-config/StrategyConfigurationPage.tsx` is
the **only** strategy-configuration component. It renders every control
purely from the API-returned `StrategySchema`/`ParameterDefinition`:

| `parameter_type` | Control |
|---|---|
| `INTEGER` / `DECIMAL` | `<input type="number">` (with min/max from the schema) |
| `ENUM` | `<select>` populated from `allowed_values` |
| `FIELD_REFERENCE` | `<select>` populated from the field-registry endpoint |
| `TIMEFRAME` (and any future closed-set type) | `<input type="text">` |

No `EmaForm.tsx`/`SmaTrendForm.tsx`/`AtrBreakoutForm.tsx` exists - a
repo-wide search for strategy-specific form files returns zero matches
(see the Non-Redundancy Audit in the Checkpoint 26 report).

## Dependent dropdowns (Part 6)

Switching the **Strategy** selector triggers a re-fetch of that
strategy's schema and saved configurations, and **clears every
previously-entered parameter value** - a stale `fast_lookback` value
from EMA Crossover cannot silently survive a switch to SMA Trend Filter
(whose schema does not even define that `parameter_id`). Proven by
`StrategyConfigurationPage.test.tsx`'s dependent-dropdown test, which
asserts the EMA-only control is gone (not merely hidden) after
switching, and that the new strategy's schema was fetched exactly once.

## Activation vs. trading (Part 14, restated for this layer)

Saving/activating a configuration through this UI/API prepares it for
research, diagnostics, or backtesting only. It never authorizes live
order placement or broker execution - those remain governed by
`trading_engine.risk_engine`/`order_management`/the kill switch, none of
which this checkpoint's frontend or API touches. The Strategy
Configuration screen states this explicitly in its own subtitle text.
