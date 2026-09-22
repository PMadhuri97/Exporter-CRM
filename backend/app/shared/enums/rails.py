"""
Rail vocabulary enums.

Pure fixed vocabularies with no behaviour — the platform's authoritative
definitions for rail status/type/finality concepts. They live here, not in
``app.modules.rails.domain.entities.rail_models``, because
``app.shared.contracts.rails`` (the rail adapter port's DTOs) needs to type
fields against them without importing the rails module — and any import of
``app.modules.rails.*`` forces that package's ``__init__.py`` (the module
facade) to run first, which itself imports the port, which imports the DTOs,
which would import the enums: a circular import if the enums stayed on the
module side. Keeping the enums here (shared depends on nothing in ``app/``)
breaks the cycle at its root.

``rail_models.py`` imports these back for its SQLAlchemy ``Enum`` columns —
that's the normal, allowed module-imports-shared direction. This is the
single authoritative definition per enum; nothing else may redefine one.
"""
from __future__ import annotations

import enum


class RailStatus(str, enum.Enum):
    ACTIVE = "active"
    DEGRADED = "degraded"
    SUSPENDED = "suspended"
    DECOMMISSIONED = "decommissioned"


class RailType(str, enum.Enum):
    FIAT = "fiat"
    CRYPTO = "crypto"


class FinalityType(str, enum.Enum):
    REVERSIBLE = "reversible"
    IRREVERSIBLE = "irreversible"


class ConfirmationMechanism(str, enum.Enum):
    SYNCHRONOUS = "synchronous"
    WEBHOOK = "webhook"
    POLLING = "polling"
    ON_CHAIN_EVENT = "on_chain_event"


class SubmissionStatus(str, enum.Enum):
    SUBMITTED = "submitted"
    REJECTED = "rejected"
    PENDING = "pending"
    TIMEOUT = "timeout"


class RailLegStatus(str, enum.Enum):
    SETTLED = "settled"
    FAILED = "failed"
    PROCESSING = "processing"
    RECALLED = "recalled"
