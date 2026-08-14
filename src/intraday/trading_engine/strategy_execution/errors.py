# File: src/intraday/trading_engine/strategy_execution/errors.py
#
# Checkpoint 26: strategy-configuration/registry/execution error types.
# Kept in this bounded context (not `domain/`), mirroring
# `signal_intelligence.feature_engine.errors`'s own precedent - these
# describe configuration/registration-input violations, not value-object
# construction violations.
from __future__ import annotations


class InvalidParameterValueError(ValueError):
    """Raised when a configuration value fails its parameter definition's
    type/range/allowed-value/required rule."""


class UnknownParameterError(ValueError):
    """Raised when a configuration supplies a parameter_id the strategy's
    schema does not define."""


class MissingRequiredParameterError(ValueError):
    """Raised when a required parameter is absent from a configuration."""


class UnknownFieldReferenceError(ValueError):
    """Raised when a FIELD_REFERENCE parameter value names a field_id not
    present in the canonical field registry."""


class DuplicateStrategyRegistrationError(ValueError):
    """Raised when a strategy_id is registered twice with the registry."""


class UnknownStrategyError(ValueError):
    """Raised when a strategy_id is looked up but not registered."""


class InvalidActivationTransitionError(ValueError):
    """Raised when an activation request violates the existing
    `StrategyMaturityState` lifecycle rules (Checkpoint 5/8)."""


class SampleBarNotPermittedError(RuntimeError):
    """Raised if diagnostic/backtest strategy execution is ever invoked
    against anything other than the fixture/historical bar repository -
    the SAMPLE_BAR/live-trading safety gate (Checkpoint 26 Part 17)."""
