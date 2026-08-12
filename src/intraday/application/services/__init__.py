# File: src/intraday/application/services/__init__.py
#
# Package marker for application/services (Checkpoint 8). Use-case
# services depend only on the Protocol interfaces in
# application/repositories — never on a concrete (Django) implementation.
# Concrete repositories are wired in by the composition root
# (intraday.composition, outside application/ and infrastructure/), never
# constructed here. See docs/api/CONFIGURATION_API.md.
