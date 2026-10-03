"""Enums for the company record (EXP-1): ``ExporterProfile`` — **owner:
Developer 2** (architecture §8.1, §9.2).

The activity-log enum (``ExporterActivityType``) used to live here too; L2-01
moved it to ``engagement_enums.py``, which Developer 3 owns.

Kept in their own file rather than added to ``orchestration_enums.py`` or the
legacy ``enums.py``: none of these concepts belong to a single verification
journey (``OnboardingRequestStatus``'s domain) or to the pre-Epic-4.1 case/KYC
design (``enums.py``'s domain) — they describe the enduring exporter
relationship those journeys attach to.

The old ten-status ``ExporterLifecycleStatus`` was retired in L2-04 (migration
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
    #: Created by the buyer migration, or by an RM recording a deal's buyer (IQ-6,
    #: allocation F3). Says the relationship began as somebody else's counterparty
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
    replaces was retired in L2-04 (migration 0020)."""

    LEAD = "LEAD"
    PROSPECT = "PROSPECT"
    CUSTOMER = "CUSTOMER"


class CompanyIdentityType(str, enum.Enum):
    """Which kind of registration identifies this company — **owner: Developer 3**
    (allocation F3, plan P4-1).

    An Indian company is identified by its PAN; a foreign one by whatever its own
    jurisdiction issues, which ``registration_number`` carries. The distinction has to
    be a column rather than "has a PAN?", because a buyer company created by the
    migration may have neither yet (IQ-7 excuses migrated buyers from the requirement)
    and "we do not know which" must not read as "foreign".

    Nullable on ``exporter_profile``: every company created before F3 predates the
    question. Migration 0032 sets ``IN_PAN`` wherever a PAN is already stored, which is
    the only case it can infer safely.
    """

    IN_PAN = "IN_PAN"
    FOREIGN_REG = "FOREIGN_REG"


class CompanyPipelineStatus(str, enum.Enum):
    """Whether this company is in the sales pipeline at all — **owner: Developer 3**
    (allocation F3, plan P4-1, P4-2).

    A company that exists only because it was somebody's buyer is not a lead, and must
    not appear in pipeline counts or be chased by sales (plan §8: buyers become leads
    only when someone onboards them). It is still a full company record: it can be
    screened, cleared and have checks recorded against it (Developer 1's P4-11).

    ``NOT_IN_PIPELINE`` implies the journey has not started — `LEAD`, with
    qualification `NOT_YET_REVIEWED` and conversation `NOT_CONTACTED` — and migration
    0032 enforces that with a check constraint. `POST /exporters/{id}/pipeline`
    (task 3.11) is the one way out, and it starts the journey properly.
    """

    IN_PIPELINE = "IN_PIPELINE"
    NOT_IN_PIPELINE = "NOT_IN_PIPELINE"


class GstRegistrationStatus(str, enum.Enum):
    """What the GST portal says about a registration — **owner: Developer 3**
    (allocation task 3.12, plan P6-1).

    `UNVERIFIED` is the default and means exactly that: somebody recorded the GSTIN
    and nobody has checked it against the portal. It is deliberately **not** called
    `ACTIVE`, which would be a claim the CRM has no basis for — the whole point of
    the column is to tell "we believe this is live" apart from "nobody has looked".

    `CANCELLED` and `SUSPENDED` come from the portal. Neither deactivates the row by
    itself (`active` is a separate, local decision, task 3.12): a cancelled
    registration is still part of the company's record, and the two questions — "is
    this registration live at the GST portal?" and "do we still use it?" — have
    different answers and different owners.
    """

    UNVERIFIED = "UNVERIFIED"
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    SUSPENDED = "SUSPENDED"


class GstRegistrationFlag(str, enum.Enum):
    """Whether compliance has flagged this branch — **owner: Developer 3**
    (allocation task 3.14, plan P6-5).

    One branch, not the company: a company trading through five states may have a
    problem in one of them, and flagging the company would stop the other four
    (decision BQ-6). A flagged branch blocks a handover only for deals invoiced
    *through that branch* (task 2.9).

    `FLAGGED` always carries a reason — `ck_exporter_gstin_flag_reason` requires it —
    because the reason is what the person reading the block needs, and a flag whose
    reason nobody recorded cannot be acted on or lifted with confidence.
    """

    NONE = "NONE"
    FLAGGED = "FLAGGED"
