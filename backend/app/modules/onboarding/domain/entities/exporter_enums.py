"""Enums for the company record: ``ExporterProfile`` (architecture §8.1, §9.2).

The activity-log enum (``ExporterActivityType``) used to live here too; it moved
to ``engagement_enums.py``.

Kept in their own file rather than added to ``orchestration_enums.py`` or the
legacy ``enums.py``: none of these concepts belong to a single verification
journey (``OnboardingRequestStatus``'s domain) or to the pre-Epic-4.1 case/KYC
design (``enums.py``'s domain) — they describe the enduring exporter
relationship those journeys attach to.

The old ten-status ``ExporterLifecycleStatus`` was retired in migration
0020): the journey is ``ExporterJourney``, beside the qualification gauge and
the ``ExporterMarker``. Its values survive as strings in the history log.
"""

import enum


class ExporterSource(str, enum.Enum):
    """How this exporter relationship originated. Immutable once set on
    ``ExporterProfile.source`` (both a service-layer guard and a DB trigger —
    see the migration and ``exceptions.ExporterSourceAlreadySetError``): this
    is an audit-relevant fact about how the relationship began, the same
    reasoning ``ComplianceCase.resolved_by`` is guarded for.
    """

    MANUAL = "MANUAL"
    SALES = "SALES"
    REFERRAL = "REFERRAL"
    RXIL = "RXIL"
    PARTNER = "PARTNER"
    API = "API"
    BROKER = "BROKER"
    EVENT = "EVENT"
    EXISTING_CUSTOMER = "EXISTING_CUSTOMER"
    #: Created by the buyer migration, or by an RM recording a deal's buyer.
    #: Says the relationship began as somebody else's counterparty
    #: rather than as a lead we went looking for.
    DEAL_BUYER = "DEAL_BUYER"


class ExporterMarker(str, enum.Enum):
    """A commercial pause or ending, kept apart from the journey (decision 3,
    ``docs/contracts/company-record.md`` §3.3). Not a lifecycle stage, and not
    a compliance hold: a compliance concern belongs on the background check.
    ``PAUSED`` and ``ENDED`` always carry a reason."""

    NONE = "NONE"
    PAUSED = "PAUSED"
    ENDED = "ENDED"


class ExporterJourney(str, enum.Enum):
    """The company's main journey (architecture §3.2): forward only, and never
    moved by hand — each move follows from a qualification outcome or a
    background-check decision (``docs/contracts/company-record.md`` §3.1).

    Added in migration 0017; the ten-status ``ExporterLifecycleStatus`` it
    replaces was retired in migration 0020."""

    LEAD = "LEAD"
    PROSPECT = "PROSPECT"
    CUSTOMER = "CUSTOMER"


class CompanyIdentityType(str, enum.Enum):
    """Which kind of registration identifies this company.

    An Indian company is identified by its PAN; a foreign one by whatever its own
    jurisdiction issues, which ``registration_number`` carries. The distinction has to
    be a column rather than "has a PAN?", because a buyer company created by the
    migration may have neither yet (migrated buyers are excused from the requirement)
    and "we do not know which" must not read as "foreign".

    Nullable on ``exporter_profile``: every company created before 0032 predates the
    question. Migration 0032 sets ``IN_PAN`` wherever a PAN is already stored, which is
    the only case it can infer safely.
    """

    IN_PAN = "IN_PAN"
    FOREIGN_REG = "FOREIGN_REG"


class CompanyPipelineStatus(str, enum.Enum):
    """Whether this company is in the sales pipeline at all.

    A company that exists only because it was somebody's buyer is not a lead, and must
    not appear in pipeline counts or be chased by sales (buyers become leads
    only when someone onboards them). It is still a full company record: it can be
    screened, cleared and have checks recorded against it (full-depth buyer checks).

    ``NOT_IN_PIPELINE`` implies the journey has not started — `LEAD`, with
    qualification `NOT_YET_REVIEWED` and conversation `NOT_CONTACTED` — and migration
    0032 enforces that with a check constraint. `POST /exporters/{id}/pipeline`
    is the one way out, and it starts the journey properly.
    """

    IN_PIPELINE = "IN_PIPELINE"
    NOT_IN_PIPELINE = "NOT_IN_PIPELINE"


class GstRegistrationStatus(str, enum.Enum):
    """What the GST portal says about a registration.

    `UNVERIFIED` is the default and means exactly that: somebody recorded the GSTIN
    and nobody has checked it against the portal. It is deliberately **not** called
    `ACTIVE`, which would be a claim the CRM has no basis for — the whole point of
    the column is to tell "we believe this is live" apart from "nobody has looked".

    `CANCELLED` and `SUSPENDED` come from the portal. Neither deactivates the row by
    itself (`active` is a separate, local decision): a cancelled
    registration is still part of the company's record, and the two questions — "is
    this registration live at the GST portal?" and "do we still use it?" — have
    different answers and different owners.
    """

    UNVERIFIED = "UNVERIFIED"
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    SUSPENDED = "SUSPENDED"


class GstRegistrationFlag(str, enum.Enum):
    """Whether compliance has flagged this branch.

    One branch, not the company: a company trading through five states may have a
    problem in one of them, and flagging the company would stop the other four
    A flagged branch blocks a handover only for deals invoiced
    *through that branch*.

    `FLAGGED` always carries a reason — `ck_exporter_gstin_flag_reason` requires it —
    because the reason is what the person reading the block needs, and a flag whose
    reason nobody recorded cannot be acted on or lifted with confidence.
    """

    NONE = "NONE"
    FLAGGED = "FLAGGED"


class CompanyTradeRole(str, enum.Enum):
    """Which side of a trade a company has actually been on. **A filter, never a
    column**: no table stores this, and none should.

    The role lives in the relationship, not on the company — a deal names its seller
    (``deal.company_id``) and its buyer (``deal.buyer_company_id``), and a trade
    relationship names both sides. So one company can be **both**, and often is: an
    exporter we sell to that another exporter also buys from.

    This is deliberately not ``source`` or ``pipeline_status``, which are the two
    things it gets mistaken for:

    * ``source=DEAL_BUYER`` is how the record was *created*. A company first met as
      somebody's buyer and later sold to keeps that source for ever, so it answers a
      question about the past, not about what the company is now.
    * ``pipeline_status`` says whether anyone brought the company into the pipeline.
      A buyer-only company is ``NOT_IN_PIPELINE``, but a company that *was* brought in
      and also appears as a buyer elsewhere is ``IN_PIPELINE`` and still a buyer.

    ``BOTH`` therefore means "has been on both sides", not "we are unsure".
    """

    SELLER = "SELLER"
    BUYER = "BUYER"
    BOTH = "BOTH"
