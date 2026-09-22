from sqlalchemy import CheckConstraint, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database.models import AnerModel

SCHEMA = "cases"

#: The full case_type / severity vocabularies, reproduced here for the CHECK
#: constraints below. case_type and severity are plain String columns rather
#: than the compliance_case Postgres enums (S1T2's spec calls for String), so
#: a database-level guard against a typo'd value has to be a CHECK against this
#: literal list rather than a shared enum type. Kept in sync with
#: `app.modules.cases.domain.entities.enums.CaseType` / `CaseSeverity` by hand —
#: there is no cross-column-type mechanism here to enforce it automatically,
#: same trade-off customer_review_type_enum vs. review_trigger_definition's
#: plain source_epic/event_type strings already accepts elsewhere in this repo.
_CASE_TYPE_VALUES = (
    "SCREENING_REVIEW", "TRANSACTION_FLAG", "RECONCILIATION_BREAK",
    "RECONCILIATION_TIMEOUT", "ONBOARDING_REVIEW", "TRAVEL_RULE_REVIEW",
    "ON_CHAIN_ESCALATION", "WEBHOOK_DELIVERY_FAILURE", "MANUAL",
)
_SEVERITY_VALUES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")

_CASE_TYPE_IN_LIST = ", ".join(f"'{v}'" for v in _CASE_TYPE_VALUES)
_SEVERITY_IN_LIST = ", ".join(f"'{v}'" for v in _SEVERITY_VALUES)


class CaseSlaConfig(AnerModel):
    """SLA hours and auto-escalation threshold for one (case_type, severity) pair.

    GitOps-managed: rows are replaced wholesale from
    `deployments/gitops/reference-data/compliance/cases/sla-config.yaml` by
    `infrastructure/sla_config_loader.py`, following the same reload-on-boot
    pattern as `compliance.sector_code_registry` — see that loader's module
    docstring for why the reload is safe under concurrent replicas (a Postgres
    advisory lock) and why it is a full DELETE + re-insert rather than an
    upsert (case_type/severity is the only natural key and the config never
    grows a soft-delete column).

    Builds on `AnerModel` (surrogate UUID id, created_at/updated_at): the S1T2
    ticket's field list names only case_type/severity/sla_hours/
    auto_escalate_at_pct, but every other table in this schema — and every
    comparable config table elsewhere in the repo (e.g.
    `compliance.sector_code_registry`) — carries a surrogate id rather than a
    composite natural-key primary key, so this table follows suit rather than
    being the one exception.
    """

    __tablename__ = "case_sla_config"
    __table_args__ = (
        UniqueConstraint("case_type", "severity", name="uq_case_sla_config_type_severity"),
        CheckConstraint(f"case_type IN ({_CASE_TYPE_IN_LIST})", name="ck_case_sla_config_case_type"),
        CheckConstraint(f"severity IN ({_SEVERITY_IN_LIST})", name="ck_case_sla_config_severity"),
        CheckConstraint("sla_hours > 0", name="ck_case_sla_config_sla_hours_positive"),
        CheckConstraint(
            "auto_escalate_at_pct > 0 AND auto_escalate_at_pct <= 100",
            name="ck_case_sla_config_auto_escalate_pct_range",
        ),
        {"schema": SCHEMA},
    )

    case_type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    sla_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    auto_escalate_at_pct: Mapped[int] = mapped_column(Integer, nullable=False)
