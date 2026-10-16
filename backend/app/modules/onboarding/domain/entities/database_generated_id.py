"""``DatabaseGeneratedId`` — a primary key the database can fill in by itself.

The tables created from migration 0018 onward (deals, documents, trade history) give
``id`` a database default, ``gen_random_uuid()``, so a row written with raw SQL — a
data migration, a fixture, an operator's repair — still gets an id. The ORM keeps
supplying its own ``uuid4``; this mixin only makes the model say what the database
already does, so the metadata is a complete description of the schema
(``tests/contract/test_orm_matches_the_onboarding_schema.py``).

List it before the base class: ``class Deal(DatabaseGeneratedId, AnerModel)``.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


class DatabaseGeneratedId:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
