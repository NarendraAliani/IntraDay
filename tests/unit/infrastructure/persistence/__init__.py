# tests/unit/infrastructure/persistence/__init__.py
#
# Package marker (Checkpoint 7) — see tests/__init__.py. Every test in
# this package is gated by tests.postgres_utils.requires_postgres,
# since all of them exercise real Django ORM/PostgreSQL behavior.
