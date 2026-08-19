# src/intraday/control_plane/market_data_watchdog/__init__.py
#
# Checkpoint 64.1: package boundary for control_plane/market_data_watchdog
# - a new, sibling bounded context to `market_data_health` (Checkpoint
# 23), NOT a replacement or duplication of it. `market_data_health`'s
# own evaluator is explicitly scoped to the REST-polling refresh
# pattern (a single last-success/last-failure instant, a 120s manual-
# refresh freshness threshold - see its own module docstring). This
# context answers a genuinely different question a CONTINUOUS
# WebSocket worker needs: distinguishing "the socket is alive" from
# "market data is actually still flowing" at packet/quote/bar
# granularity, plus token and reconnect state - none of which the REST
# health evaluator's vocabulary can express. Supervisory only, per this
# bounded context's own permanent scope (Checkpoint 2 §10) - it
# observes and classifies, it never generates a signal or makes a
# trading decision.
