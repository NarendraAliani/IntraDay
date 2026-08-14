# src/intraday/infrastructure/market_data_providers/dhan/__init__.py
#
# Checkpoint 23: Dhan-specific live market-data adapter. Dhan-specific
# concepts (security IDs, exchange-segment strings, the Market Quote
# REST shape) are confined to this package - domain/application never
# see them (Checkpoint 23 §4's "never leak Dhan-specific concepts into
# domain/").
