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
    market_data_views,
    risk_views,
    settings_views,
    strategy_configuration_views,
    strategy_research_status_views,
    strategy_views,
    universe_views,
    watchlist_views,
)

app_name = "config_api"

urlpatterns = [
    # --- Checkpoint 23: read-only live market data ------------------------
    path("market-data/session/", market_data_views.session_status, name="market-data-session"),
    path("market-data/health/", market_data_views.health_status, name="market-data-health"),
    path("market-data/quotes/", market_data_views.current_quotes, name="market-data-quotes"),
    path("market-data/refresh/", market_data_views.refresh, name="market-data-refresh"),
    # --- Checkpoint 24A: read-only canonical bars --------------------------
    path("market-data/bars/", market_data_views.recent_bars, name="market-data-bars"),
    # --- Checkpoint 22: operational provider settings --------------------
    path("settings/dhan/", settings_views.dhan_settings, name="settings-dhan"),
    path("settings/dhan/save/", settings_views.dhan_settings_save, name="settings-dhan-save"),
    path("settings/dhan/test/", settings_views.dhan_test_connection, name="settings-dhan-test"),
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
