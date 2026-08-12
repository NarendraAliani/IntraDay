# File: src/intraday/application/contracts/__init__.py
#
# Package marker for application/contracts (Checkpoint 8, first real
# content — was documentation-only through Checkpoint 7). Holds DRF
# serializers representing the wire-facing (transport) shape of each API
# resource. These are transport contracts, NOT domain contracts
# (Checkpoint 8 §4) — they may duplicate a domain field's *name* for
# clarity, but never redefine its type/constraints independently; each
# serializer's docstring cross-references the domain/application dataclass
# it represents. No domain dataclass inherits from or is coupled to a
# serializer class.
