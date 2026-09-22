"""Payments — public facade (epic4-reference).

payments is otherwise out of scope for this checkout (see the module-level
note that would live here if this were the schema-only stub pattern used by
ledger/settlement/fx/reconciliation/rails/reporting). It gets this one
exception because it is identical to the real facade below: unlike those
other excluded modules, the real payments/__init__.py never imports
application/ or api/ at all — only domain entities and a plain
infrastructure/repository.py (generic BaseRepository/AppendOnlyRepository CRUD
wrappers, no business rules). audit/application/services.py (in scope, kept
in full) imports `TransactionRepository` from here directly, so this facade
has to be real rather than stubbed.

domain/entities/ and infrastructure/repository.py are both present; api/ and
application/ (which do not exist in the real module either) are still absent.
"""
from app.modules.payments.domain.entities.payments import (
    Transaction,
    TransactionStatus,
    TransactionStatusHistory,
)
from app.modules.payments.infrastructure.repository import (
    StatusHistoryRepository,
    TransactionRepository,
)

__all__ = [
    "StatusHistoryRepository",
    "Transaction",
    "TransactionRepository",
    "TransactionStatus",
    "TransactionStatusHistory",
]
