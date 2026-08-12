# File: src/intraday/infrastructure/persistence/__init__.py
#
# Django app package for infrastructure/persistence (Checkpoint 7). The
# ONLY place in this codebase where domain/application concepts are
# translated into Django ORM rows and back — models.py defines the
# tables, repositories.py implements the Protocol interfaces declared in
# intraday.application.repositories. Registered in INSTALLED_APPS as
# "intraday.infrastructure.persistence" (see settings/base.py). See
# docs/architecture/PERSISTENCE_ARCHITECTURE.md for the full design.
