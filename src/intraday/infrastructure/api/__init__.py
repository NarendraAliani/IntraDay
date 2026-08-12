# File: src/intraday/infrastructure/api/__init__.py
#
# HTTP delivery adapter (Checkpoint 8) — the DRF views/URL layer that
# exposes application services over HTTP. Placed under `infrastructure/`,
# not `application/`, deliberately: an HTTP API is a delivery mechanism
# (a "driving adapter" in ports-and-adapters terms), the same category as
# a broker adapter or persistence adapter — it is allowed to know about
# both `application` (services, contracts) and concrete
# `infrastructure.persistence` implementations to wire them together,
# which `application` itself must never do
# (`.importlinter` contract #6). Analogous to how `infrastructure/persistence`
# already composes `application.repositories` with Django ORM.
#
# Views here MUST NOT: query Django models directly, manipulate
# QuerySets, contain persistence logic, or contain domain business rules
# — they only translate HTTP <-> application service calls (Checkpoint 8
# §2). See docs/api/CONFIGURATION_API.md.
