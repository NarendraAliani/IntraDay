# src/intraday/control_plane/system_readiness/__init__.py
#
# Checkpoint 50 Rule 10: the FIRST authoritative, composed readiness
# state for the platform - answering "is the system ready right now?"
# as ONE evaluated value with named reasons, instead of an operator
# having to separately check market-data health, session status, kill
# switch, and emergency-square-off state and mentally combine them.
#
# Deliberately narrow this checkpoint: composes ONLY the real,
# already-persisted signals this project already produces
# (market-data health - Checkpoint 23, session calendar - Checkpoint
# 39, kill switch - Checkpoint 34, emergency-square-off event state -
# Checkpoint 48/49). It does NOT invent a persistent WebSocket worker,
# Celery worker/Beat heartbeat, or bar-engine health this checkpoint -
# those remain named, undone dependencies (see
# docs/architecture/ACTIVE_PRODUCT_GAP_REGISTER.md), not silently
# assumed healthy.
