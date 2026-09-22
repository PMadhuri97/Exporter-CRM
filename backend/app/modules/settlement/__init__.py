"""settlement — schema-only stub (epic4-reference).

This module is OUT OF SCOPE for the Epic 4 reference checkout (it belongs to
a different epic). Its business logic (application/, api/, infrastructure/,
domain/policies, etc.) is deliberately NOT present here.

What IS present:
  - migrations/   so `alembic upgrade head` reproduces the same schema as
    the real platform (this codebase uses a single, interlinked Alembic
    chain across all modules; splitting it cleanly is not possible without
    surgery on migration history — see RUNNING.md).
  - domain/entities/  ONLY where another in-scope module's SQLAlchemy
    relationships resolve against one of this module's ORM classes, or
    where migrations/env.py imports it for Base.metadata population. These
    are schema definitions only (columns, types, relationships) — no
    services, no ports, no use cases.

The real module's public facade (this file, in the source repo) eagerly
imports its application/api/infrastructure layers. That facade is NOT
reproduced here on purpose: importing it would pull in the exact business
logic this reference checkout excludes. Do not "restore" this __init__.py
from the source repo without re-checking that reasoning.
"""
