from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.compliance.application.compliance_rule_service import (
    evaluate_settlement_compliance,
)
from app.modules.compliance.application.rule_engine import ComplianceActionSet
from app.modules.compliance.application.sector_classification import (
    SectorRegistryClassificationLookup,
)
from app.modules.compliance.application.validation import validate_purpose_code
from app.modules.compliance.domain.policies.effectivity import is_effective_at
from app.modules.compliance.domain.policies.rule_matching import ComplianceFacts
from app.modules.compliance.domain.ports import (
    ComplianceAuditSink,
    IndicativeRateProvider,
    SectorClassificationLookup,
)
from app.modules.compliance.infrastructure.compliance_audit_sink import (
    AuditServiceComplianceAuditSink,
)
from app.modules.compliance.infrastructure.compliance_rule_repository import (
    SQLAlchemyComplianceRuleRepository,
)
from app.modules.compliance.infrastructure.purpose_code_repository import (
    SQLAlchemyPurposeCodeRepository,
)
from app.modules.compliance.infrastructure.sector_risk_repository import (
    SQLAlchemySectorRiskRepository,
)


async def evaluate_compliance_rules(
    session: AsyncSession,
    *,
    sector_code: str,
    purpose_code: str,
    corridor_id: str,
    send_amount: int,
    send_currency: str,
    as_of_date: date,
    country_jurisdiction: str | None = None,
    rate_provider: IndicativeRateProvider | None = None,
    classification_lookup: SectorClassificationLookup | None = None,
    audit_sink: ComplianceAuditSink | None = None,
) -> ComplianceActionSet:
    purpose_repository = SQLAlchemyPurposeCodeRepository(session)
    rule_repository = SQLAlchemyComplianceRuleRepository(session)

    if classification_lookup is None:
        classification_lookup = SectorRegistryClassificationLookup(
            SQLAlchemySectorRiskRepository(session)
        )
    if audit_sink is None:
        audit_sink = AuditServiceComplianceAuditSink(session)

    await validate_purpose_code(purpose_code, corridor_id, as_of_date, purpose_repository)

    # The rules match on the purpose *category* — the vocabulary a rule can be
    # written against — not on the canonical code, of which there is one per
    # purpose. validate_purpose_code has already established that this row
    # exists and is in force on the date.
    #
    # A code retired and later reinstated has more than one row, each with its
    # own window, so the category is read from the row in force on as_of_date —
    # never from today, and never from whichever row the query returned first.
    # This mirrors validate_purpose_code rather than deciding effectivity again:
    # ex_purpose_code_canonical_validity guarantees the windows never overlap,
    # so at most one row can match.
    history = await purpose_repository.get_canonical_history(purpose_code)
    canonical = next(
        (c for c in history if is_effective_at(c.effective_from, c.effective_to, as_of_date)),
        None,
    )
    purpose_category = canonical.category.value if canonical is not None else None

    # Both jurisdiction arguments are handed to S0T2 unchanged. Which rung wins
    # is S0T2's decision and is not second-guessed here: whatever authority it
    # resolves is the one carried into the action set below.
    classification = await classification_lookup.resolve(
        sector_code, corridor_id, country_jurisdiction, as_of_date
    )

    facts = ComplianceFacts(
        send_amount_minor=send_amount,
        send_asset_code=send_currency,
        as_of_date=as_of_date,
        sector_risk_tier=classification.risk_tier,
        classification_label=classification.classification_label,
        purpose_code=purpose_category,
        corridor_id=corridor_id,
    )

    return await evaluate_settlement_compliance(
        facts,
        rule_repository,
        rate_provider,
        resolving_jurisdiction=classification.resolving_jurisdiction,
        audit_sink=audit_sink,
    )
