"""L2-04 — the ten-status lifecycle is retired; the journey is LEAD ->
PROSPECT -> CUSTOMER, with qualification and the marker beside it.

The old model is gone from the live record (migration 0020), and nothing it
ever recorded is lost: its moves stay in the history log as they were written.
"""

from __future__ import annotations

import pathlib
import uuid

import psycopg2
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.domain.entities import exporter_enums
from app.modules.onboarding.domain.entities.exporter_enums import (
    ExporterJourney,
    ExporterMarker,
)
from app.modules.onboarding.domain.entities.qualification_enums import QualificationState
from app.modules.onboarding.tests.fixtures.companies import insert_company
from app.platform.configuration.config import get_settings
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio

BACKEND = pathlib.Path(__file__).resolve().parents[5]
REVISION = "onboarding_0020_retire_lifecycle"


def _connect():
    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    return psycopg2.connect(url)


def _scalar(query: str, params: tuple = ()):
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchone()[0]
    finally:
        conn.close()


async def test_0020_follows_0017_in_one_chain():
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    script = ScriptDirectory.from_config(cfg)
    [head] = script.get_heads()
    assert script.get_revision(REVISION).down_revision == "onboarding_0017_qualification"
    assert REVISION in {rev.revision for rev in script.walk_revisions("base", head)}
    assert len(REVISION) <= 32


async def test_the_old_column_and_its_type_are_gone():
    assert _scalar(
        "SELECT count(*) FROM information_schema.columns "
        "WHERE table_schema = 'onboarding' AND table_name = 'exporter_profile' "
        "AND column_name = 'lifecycle_status'"
    ) == 0
    assert _scalar(
        "SELECT count(*) FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace "
        "WHERE n.nspname = 'onboarding' AND t.typname = 'exporter_lifecycle_status_enum'"
    ) == 0


async def test_the_old_enum_is_gone_from_the_code():
    assert not hasattr(exporter_enums, "ExporterLifecycleStatus")


async def test_the_journey_has_exactly_three_values_and_holds_no_other_gauge():
    assert [j.value for j in ExporterJourney] == ["LEAD", "PROSPECT", "CUSTOMER"]
    others = {m.value for m in ExporterMarker} | {q.value for q in QualificationState}
    assert not others & {j.value for j in ExporterJourney}
    conn = _connect()
    try:
        with conn.cursor() as cur:
            company_id = insert_company(cur)
            with pytest.raises(psycopg2.errors.InvalidTextRepresentation):
                cur.execute(
                    "UPDATE onboarding.exporter_profile SET journey = 'ONBOARDED' "
                    "WHERE customer_id = %s",
                    (str(company_id),),
                )
    finally:
        conn.rollback()
        conn.close()


async def test_old_statuses_stay_readable_as_history():
    """History stores values as strings, so a row written by the old model —
    `COMPLIANCE_REVIEW` -> `ONBOARDED` — reads back exactly as written."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            company_id = insert_company(cur)
            cur.execute(
                "INSERT INTO onboarding.exporter_lifecycle_history "
                "(id, customer_id, dimension, event_type, from_status, to_status, event_metadata) "
                "VALUES (%s, %s, 'journey', 'lifecycle_transition', 'COMPLIANCE_REVIEW', "
                "'ONBOARDED', '{\"terminal\": true}')",
                (str(uuid.uuid4()), str(company_id)),
            )
        conn.commit()
    finally:
        conn.close()

    async with db_services.AsyncSessionLocal() as db:
        rows, _ = await HistoryService(db).list_for_company(company_id, dimension="journey")
    [row] = rows
    assert (row.from_status, row.to_status) == ("COMPLIANCE_REVIEW", "ONBOARDED")
    assert row.event_metadata["terminal"] is True
