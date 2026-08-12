# tests/unit/infrastructure/api/__init__.py
#
# Package marker (Checkpoint 8) — see tests/__init__.py. Every test here
# is gated by tests.postgres_utils.requires_postgres, since these
# exercise the real Django-ORM-backed repositories via composition.
