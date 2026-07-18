"""anime_studio — a provider-agnostic anime studio engine.

The durable asset is the project state (the memory bank), not any model. Models
are swappable contractors plugged in behind common provider interfaces.

Step 1 (this package so far): the schema, the continuity ledger, project
scaffolding, and load/save helpers. Nothing renders yet — this is the foundation
every stage composes on.
"""
from . import schema, serde, store, ledger, paths  # noqa: F401

__version__ = "0.1.0"
