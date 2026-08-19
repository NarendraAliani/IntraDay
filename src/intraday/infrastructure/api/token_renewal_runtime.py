# File: src/intraday/infrastructure/api/token_renewal_runtime.py
#
# Checkpoint 64.1: the composition-root adapter satisfying
# `application.services.token_lifecycle.TokenRenewer` with the real
# Dhan `/v2/RenewToken` client - the ONE place a Dhan-specific
# exception is translated into the application layer's generic
# `TokenRenewalError` (mirrors this project's existing dependency-
# inversion pattern - e.g. `infrastructure.api.tasks.
# build_historical_backtest_orchestrator` injecting a concrete
# provider into an application-layer Protocol).
from __future__ import annotations

from intraday.application.services.token_lifecycle import TokenRenewalError, TokenRenewalResult
from intraday.infrastructure.market_data_providers.dhan.token_renewal_client import (
    DhanTokenRenewalError,
    renew_dhan_token,
)


def renew_dhan_token_adapter(*, client_id: str, current_access_token: str) -> TokenRenewalResult:
    try:
        result = renew_dhan_token(client_id=client_id, current_access_token=current_access_token)
    except DhanTokenRenewalError as exc:
        raise TokenRenewalError(str(exc)) from exc
    return TokenRenewalResult(new_access_token=result.new_access_token)


__all__ = ["renew_dhan_token_adapter"]
