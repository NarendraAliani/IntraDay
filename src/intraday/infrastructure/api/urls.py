# File: src/intraday/infrastructure/api/urls.py
#
# URL routes for the Checkpoint 8 configuration API, mounted at
# /api/v1/config/ by the root URLconf (intraday/urls.py). Versioning
# strategy: a single "/api/v1/" prefix (Checkpoint 8 §14) — no multiple
# API versions introduced.
#
# Route ordering matters: each resource's "active/" literal path is
# declared BEFORE its "<version>/" pattern, so a request for
# ".../active/" is never captured by the more general version pattern.
from __future__ import annotations

from django.urls import path

from intraday.infrastructure.api import (
    backtesting_views,
    historical_backtesting_views,
    kill_switch_views,
    live_paper_readiness_views,
    live_paper_session_views,
    market_data_sync_views,
    market_data_views,
    paper_trading_views,
    reports_views,
    risk_views,
    scanner_configuration_views,
    settings_views,
    signal_views,
    strategy_configuration_views,
    strategy_research_status_views,
    strategy_views,
    system_readiness_view,
    universe_views,
    watchlist_views,
    worker_runtime_status_views,
)

app_name = "config_api"

urlpatterns = [
    # --- Checkpoint 50: composed system readiness --------------------------
    path("system/readiness/", system_readiness_view.system_readiness, name="system-readiness"),
    # --- Checkpoint 62.x: read-only, real, persisted strategy signals -----
    path("signals/", signal_views.list_signals, name="signals-list"),
    path(
        "signals/<str:signal_id>/communication/",
        signal_views.signal_communication_history,
        name="signals-communication-history",
    ),
    # --- Checkpoint 64.10: real report API endpoints (first-ever wiring
    # for any of application/reporting/*.py's builder functions) ------
    path("reports/signals/", reports_views.signal_report, name="reports-signal"),
    path(
        "reports/communication/",
        reports_views.communication_report,
        name="reports-communication",
    ),
    path(
        "reports/daily-session/",
        reports_views.daily_session_report,
        name="reports-daily-session",
    ),
    # --- Checkpoint 23: read-only live market data ------------------------
    path("market-data/session/", market_data_views.session_status, name="market-data-session"),
    path("market-data/health/", market_data_views.health_status, name="market-data-health"),
    path("market-data/quotes/", market_data_views.current_quotes, name="market-data-quotes"),
    path(
        "market-data/instruments/",
        market_data_views.list_instruments,
        name="market-data-instruments",
    ),
    path("market-data/refresh/", market_data_views.refresh, name="market-data-refresh"),
    # --- Checkpoint 24A: read-only canonical bars --------------------------
    path("market-data/bars/", market_data_views.recent_bars, name="market-data-bars"),
    # --- Checkpoint 22: operational provider settings --------------------
    path("settings/dhan/", settings_views.dhan_settings, name="settings-dhan"),
    path("settings/dhan/save/", settings_views.dhan_settings_save, name="settings-dhan-save"),
    path("settings/dhan/test/", settings_views.dhan_test_connection, name="settings-dhan-test"),
    # --- Checkpoint 34: kill switch ---------------------------------------
    path("kill-switch/", kill_switch_views.kill_switch_status, name="kill-switch-status"),
    path("kill-switch/engage/", kill_switch_views.kill_switch_engage, name="kill-switch-engage"),
    path("kill-switch/reset/", kill_switch_views.kill_switch_reset, name="kill-switch-reset"),
    # --- Checkpoint 35: paper trading read APIs + order submission -------
    path("paper-trading/orders/", paper_trading_views.paper_orders, name="paper-orders"),
    path("paper-trading/trades/", paper_trading_views.paper_trades, name="paper-trades"),
    path("paper-trading/positions/", paper_trading_views.paper_positions, name="paper-positions"),
    path("paper-trading/funds/", paper_trading_views.paper_funds, name="paper-funds"),
    path(
        "paper-trading/orders/submit/",
        paper_trading_views.paper_order_submit,
        name="paper-order-submit",
    ),
    path(
        "paper-trading/expire-session/",
        paper_trading_views.paper_expire_session,
        name="paper-expire-session",
    ),
    path("settings/telegram/", settings_views.telegram_settings, name="settings-telegram"),
    path(
        "settings/telegram/save/",
        settings_views.telegram_settings_save,
        name="settings-telegram-save",
    ),
    path(
        "settings/telegram/test/",
        settings_views.telegram_test_connection,
        name="settings-telegram-test",
    ),
    path("settings/discord/", settings_views.discord_settings, name="settings-discord"),
    path(
        "settings/discord/save/",
        settings_views.discord_settings_save,
        name="settings-discord-save",
    ),
    path(
        "settings/discord/test/",
        settings_views.discord_test_connection,
        name="settings-discord-test",
    ),
    path(
        "settings/<str:provider>/status/",
        settings_views.provider_status,
        name="settings-provider-status",
    ),
    # --- Risk configuration ---------------------------------------------
    path("risk/<str:configuration_id>/", risk_views.list_versions, name="risk-list"),
    path("risk/<str:configuration_id>/active/", risk_views.get_active, name="risk-active"),
    path("risk/<str:configuration_id>/<str:version>/", risk_views.get_version, name="risk-version"),
    path(
        "risk/<str:configuration_id>/<str:version>/activate/",
        risk_views.activate,
        name="risk-activate",
    ),
    # --- Universe --------------------------------------------------------
    path("universe/<str:universe_id>/", universe_views.list_versions, name="universe-list"),
    path("universe/<str:universe_id>/active/", universe_views.get_active, name="universe-active"),
    path(
        "universe/<str:universe_id>/<str:version>/",
        universe_views.get_version,
        name="universe-version",
    ),
    path(
        "universe/<str:universe_id>/<str:version>/activate/",
        universe_views.activate,
        name="universe-activate",
    ),
    # --- Strategy version --------------------------------------------------
    path("strategy/<str:strategy_id>/", strategy_views.list_versions, name="strategy-list"),
    path("strategy/<str:strategy_id>/active/", strategy_views.get_active, name="strategy-active"),
    path(
        "strategy/<str:strategy_id>/<str:specification_version>/<str:code_version>/"
        "<str:configuration_version>/",
        strategy_views.get_version,
        name="strategy-version",
    ),
    path(
        "strategy/<str:strategy_id>/<str:specification_version>/<str:code_version>/"
        "<str:configuration_version>/activate/",
        strategy_views.activate,
        name="strategy-activate",
    ),
    # --- Checkpoint 26: strategy engine field registry / registry / config ---
    path(
        "strategy-engine/fields/",
        strategy_configuration_views.field_registry,
        name="strategy-engine-fields",
    ),
    path(
        "strategy-engine/strategies/",
        strategy_configuration_views.list_strategies,
        name="strategy-engine-strategies",
    ),
    path(
        "strategy-engine/strategies/<str:strategy_id>/schema/",
        strategy_configuration_views.strategy_schema,
        name="strategy-engine-schema",
    ),
    path(
        "strategy-engine/strategies/<str:strategy_id>/configurations/",
        strategy_configuration_views.list_configurations,
        name="strategy-engine-configurations-list",
    ),
    path(
        "strategy-engine/strategies/<str:strategy_id>/configurations/save/",
        strategy_configuration_views.save_configuration,
        name="strategy-engine-configurations-save",
    ),
    path(
        "strategy-engine/strategies/<str:strategy_id>/configurations/"
        "<str:specification_version>/<str:code_version>/<str:configuration_version>/",
        strategy_configuration_views.get_configuration,
        name="strategy-engine-configuration-detail",
    ),
    # --- Checkpoint 27: backtesting ---------------------------------------
    path("backtesting/run/", backtesting_views.run_backtest_view, name="backtesting-run"),
    path(
        "backtesting/results/<str:backtest_id>/",
        backtesting_views.get_backtest_result,
        name="backtesting-result-detail",
    ),
    path(
        "backtesting/strategies/<str:strategy_id>/results/",
        backtesting_views.list_backtest_results,
        name="backtesting-results-list",
    ),
    # --- Checkpoint 63.x: DB-first historical backtest runs ---------------
    path(
        "backtesting/historical-runs/",
        historical_backtesting_views.create_historical_backtest_run_view,
        name="backtesting-historical-run-create",
    ),
    path(
        "backtesting/historical-runs/<str:run_id>/progress/",
        historical_backtesting_views.get_historical_backtest_run_progress,
        name="backtesting-historical-run-progress",
    ),
    path(
        "backtesting/coverage-preview/",
        historical_backtesting_views.coverage_preview_view,
        name="backtesting-coverage-preview",
    ),
    # --- Follow-up to Checkpoint 63.x: manual historical market-data sync --
    path(
        "market-data/sync-runs/",
        market_data_sync_views.create_market_data_sync_run_view,
        name="market-data-sync-run-create",
    ),
    path(
        "market-data/sync-runs/<str:run_id>/progress/",
        market_data_sync_views.get_market_data_sync_run_progress,
        name="market-data-sync-run-progress",
    ),
    # --- Checkpoint 64.3: live worker runtime status (operator-facing) ----
    path(
        "market-data/worker-status/",
        worker_runtime_status_views.worker_runtime_status,
        name="worker-runtime-status",
    ),
    # --- Checkpoint 64.12: canonical "can we safely start a Live Paper
    # Session" gate - composes credential/watchdog/kill-switch state ---
    path(
        "market-data/live-paper-readiness/",
        live_paper_readiness_views.live_paper_readiness,
        name="live-paper-readiness",
    ),
    # --- Checkpoint 64.14: the 10-item Pre-Session Readiness Workbench
    # + real session state + effective-session-configuration, all in
    # ONE response - reuses the same signals as the endpoint above ----
    path(
        "market-data/live-paper-workbench/",
        live_paper_readiness_views.live_paper_workbench,
        name="live-paper-workbench",
    ),
    # --- Checkpoint 64.13: explicit, human-triggered START/STOP - the
    # backend re-checks readiness itself, never trusts the frontend ----
    path(
        "market-data/live-paper-session/start/",
        live_paper_session_views.start_live_paper_session_view,
        name="live-paper-session-start",
    ),
    path(
        "market-data/live-paper-session/stop/",
        live_paper_session_views.stop_live_paper_session_view,
        name="live-paper-session-stop",
    ),
    # --- Checkpoint 64.4: live scanner control plane (desired/effective) --
    path(
        "market-data/scanner-config/",
        scanner_configuration_views.get_scanner_configuration,
        name="scanner-config-get",
    ),
    path(
        "market-data/scanner-config/update/",
        scanner_configuration_views.update_scanner_configuration,
        name="scanner-config-update",
    ),
    # --- Checkpoint 27: research watchlists -------------------------------
    path("watchlists/", watchlist_views.list_watchlists, name="watchlists-list"),
    path("watchlists/save/", watchlist_views.save_watchlist, name="watchlists-save"),
    path("watchlists/<str:name>/", watchlist_views.get_watchlist, name="watchlists-detail"),
    path(
        "watchlists/<str:name>/delete/", watchlist_views.delete_watchlist, name="watchlists-delete"
    ),
    # --- Checkpoint 27: strategy research monitor --------------------------
    path(
        "strategy-engine/research-status/",
        strategy_research_status_views.list_research_statuses,
        name="strategy-research-status-list",
    ),
    path(
        "strategy-engine/strategies/<str:strategy_id>/research-status/",
        strategy_research_status_views.get_research_status,
        name="strategy-research-status-get",
    ),
    path(
        "strategy-engine/strategies/<str:strategy_id>/research-status/set/",
        strategy_research_status_views.set_research_status,
        name="strategy-research-status-set",
    ),
]
