"""Abstract ports for idempotency platform capability."""

import uuid
from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable

from app.platform.idempotency.models import RegistrationResult
from app.shared.contracts.idempotency import ViolationPage


@runtime_checkable
class ReferenceKeyResolver(Protocol):
    """Resolves a domain reference to the idempotency keys that guarded it.

    The audit interface has to answer "which key guarded this ledger
    transaction" without importing the ledger module — ADR 0001 rule 1 forbids
    the foundation depending on a module, and CI rejects it. Each owning module
    supplies a resolver instead, and the interface composes them.

    Declared as a Protocol rather than an ABC, per ADR 0001 rule 2: a nominal
    base class has to be imported to be subclassed, which would put the import
    back where the rule removed it. Structural typing means an adapter satisfies
    this by shape and depends on nothing here.

    The return is deliberately a list of plain strings. A resolver that returned
    a richer type would need that type to live somewhere both sides can reach,
    and there is nothing to say about a key beyond its value.
    """

    async def idempotency_keys_for(self, reference_id: uuid.UUID) -> list[str]:
        """Keys recorded against this reference, or an empty list if it has none.

        An unknown reference is not an error. An investigation asking "what
        guarded this transaction" about a transaction that never existed wants
        an empty answer, not an exception to handle.
        """
        ...


@runtime_checkable
class ReferenceScopeResolver(Protocol):
    """Expands a domain reference into every registry scope its records sit under.

    ``scope_id`` is not one identifier per settlement, and it is not a settlement
    id at all. Three writers populate it and they use three different
    taxonomies: rail references are scoped ``rail:{rail_id}:leg:{leg_id}``,
    internal derived keys carry a fixed registry constant, and customer keys
    carry the HTTP route template. "Every record for this settlement" is
    therefore a resolution problem, and only the module owning the settlement
    can perform it — it is the one that knows the legs and their rails.

    Customer-key records are deliberately out of scope here: their scope carries
    no settlement linkage whatsoever, so they are reachable only through
    ``ReferenceKeyResolver`` and the key-based lookup. Scope history is the
    union of both, which is the caller's job to assemble.
    """

    async def scope_ids_for(self, reference_id: uuid.UUID) -> list[str]:
        """Every scope this reference's records may live under, unordered."""
        ...


@runtime_checkable
class ViolationSource(Protocol):
    """Reads recorded idempotency violations, newest first.

    Violations are written to ``audit.audit_events`` by the violation detector.
    That table belongs to the audit module, which the platform may not import
    (ADR 0001 rule 1), so the audit module supplies the adapter and the audit
    query interface depends only on this shape.

    A violation is an idempotency *failure* — an operation that executed more than
    once despite the controls. It is never a duplicate that was detected and
    short-circuited; those are read from ``ledger.duplicate_detection`` by a
    different repository, and nothing behind this port touches them.
    """

    async def list_violations(self, *, limit: int, offset: int) -> ViolationPage:
        """One page of violation records, most recent first."""
        ...


@runtime_checkable
class ScopedReferenceResolver(ReferenceKeyResolver, ReferenceScopeResolver, Protocol):
    """A reference whose records are reachable both by scope and by key.

    A settlement is the case: its rail references and internal derived keys are
    found by scope, its customer key only by key. Combining the two into one
    protocol keeps them one object, so a caller cannot resolve the scopes,
    forget the keys, and get an answer that looks complete.
    """


class IdempotencyRegistrationPort(ABC):
    """Abstract port defining operations for idempotency key registration and completion."""

    @abstractmethod
    async def register_key(
        self,
        key_value: str,
        key_type: str,
        scope_id: str,
        operation_type: str,
        correlation_id: str | None = None,
        created_by: str | None = None,
        metadata: dict | None = None,
    ) -> RegistrationResult:
        """Register an idempotency key before operation execution."""

    @abstractmethod
    async def complete_key(
        self,
        key_value: str,
        scope_id: str,
        terminal_status: str,
        response_payload: dict | None = None,
    ) -> Any:
        """Mark an active idempotency key as completed or failed with cached response."""

