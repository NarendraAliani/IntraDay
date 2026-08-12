# src/intraday/infrastructure/__init__.py
#
# Package boundary for the Infrastructure layer (Checkpoint 4 scaffolding
# only). Will hold concrete technology adapters (brokers, market-data
# providers, persistence) implementing domain interfaces (Checkpoint 1 Rule
# 5.3). Must never be imported by domain or any bounded context —
# mechanically enforced by .importlinter contract #2. No adapter code
# exists yet.
