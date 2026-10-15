"""Legacy ``deal_buyer`` rows, for tests about deals written before buyer companies.

Nothing in the CRM writes a ``deal_buyer`` row any more: a deal names its buyer as a
company, and ``trg_deal_buyer_frozen`` (migration 0058) refuses an ``INSERT``. Deals
written before still have one — it is what the buyer migration maps, what their BUYER
checks are about and what their handover snapshot was taken from — so tests of those
paths stage the row here, in raw SQL, with that one trigger off for the one statement.

All in one transaction: ``ALTER TABLE`` holds its lock until the commit, so no other
session can write the table while the trigger is off, and the trigger is back on before
anyone else sees the row.
"""

from __future__ import annotations

import uuid

import psycopg2

from app.platform.configuration.config import get_settings

FREEZE_TRIGGER = "trg_deal_buyer_frozen"


async def record_legacy_buyer(
    deal_id: uuid.UUID,
    *,
    name: str,
    country: str,
    registration_number: str | None = None,
    tax_id: str | None = None,
    contact_email: str | None = None,
    contact_phone: str | None = None,
) -> uuid.UUID:
    """Give ``deal_id`` a legacy buyer row; returns its id."""
    buyer_id = uuid.uuid4()
    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    conn = psycopg2.connect(url)
    try:
        with conn.cursor() as cur:
            cur.execute(f"ALTER TABLE onboarding.deal_buyer DISABLE TRIGGER {FREEZE_TRIGGER}")
            cur.execute(
                "INSERT INTO onboarding.deal_buyer (id, deal_id, name, country, "
                "registration_number, tax_id, contact_email, contact_phone) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    str(buyer_id),
                    str(deal_id),
                    name,
                    country,
                    registration_number,
                    tax_id,
                    contact_email,
                    contact_phone,
                ),
            )
            cur.execute(f"ALTER TABLE onboarding.deal_buyer ENABLE TRIGGER {FREEZE_TRIGGER}")
        conn.commit()
    finally:
        conn.close()
    return buyer_id


__all__ = ["FREEZE_TRIGGER", "record_legacy_buyer"]
