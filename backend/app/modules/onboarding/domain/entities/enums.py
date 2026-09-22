import enum


class CaseState(str, enum.Enum):
    """
    The twelve states of the KYC case lifecycle.

    The full set is declared here because the ``onboarding_case.state`` column needs a
    complete PostgreSQL enum type from the moment the table exists; widening a pg enum
    later is a migration, and narrowing one is not reversible.

    **Declaring the states is not implementing the machine.** The legal-transition
    table, the guard that rejects an illegal transition with ``409``, and the single
    writer that records a ``case_state_transition`` row all land with the state machine.
    Until then a case is created in ``DRAFT`` and nothing moves it.

    Values are ``SCREAMING_SNAKE`` per the repo enum convention
    (``docs/api-conventions.md``); the backlog spells them in lowercase prose.
    """

    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PROVIDER_PENDING = "PROVIDER_PENDING"
    PROVIDER_COMPLETED = "PROVIDER_COMPLETED"
    PROVIDER_FAILED = "PROVIDER_FAILED"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    MORE_INFO_REQUESTED = "MORE_INFO_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVIEW_DUE = "REVIEW_DUE"
    CLOSED = "CLOSED"
    REOPENED_BY_EXCEPTION = "REOPENED_BY_EXCEPTION"


class CaseType(str, enum.Enum):
    """
    What kind of onboarding a case represents.

    The backlog never enumerates this. It names exactly two flows — "``IN``
    individual KYC" and "``IN`` KYB/UBO" (§4.3) — so those are the two members.
    UBO is treated as part of the KYB flow rather than a third case type, because
    the backlog writes them as one flow. Recorded as decision **D13**; adding a
    member later is an additive ``ALTER TYPE`` and therefore reversible enough.
    """

    KYC = "KYC"
    KYB = "KYB"


class TransitionSource(str, enum.Enum):
    """
    What caused a case state transition (four exact values).

    Declared up front so ``case_state_transition.source`` has a complete enum type.
    Nothing writes a transition row until the state machine lands.
    """

    USER_ACTION = "USER_ACTION"
    SYSTEM = "SYSTEM"
    PROVIDER_CALLBACK = "PROVIDER_CALLBACK"
    ADMIN_OVERRIDE = "ADMIN_OVERRIDE"


class OnboardingStatus(str, enum.Enum):
    """
    Verification lifecycle status of an onboarding customer.

    This tracks the *identity-verification* state only — it is deliberately NOT
    a KYB/AML/risk decision. Those business rules live in the compliance module.
    """

    PENDING = "PENDING"          # applicant created, awaiting provider verification
    IN_REVIEW = "IN_REVIEW"      # submitted / provider is reviewing
    APPROVED = "APPROVED"        # provider returned a positive result (e.g. GREEN)
    REJECTED = "REJECTED"        # provider returned a negative result (e.g. RED)


class VerificationStatus(str, enum.Enum):
    """Outcome recorded on a single (immutable) verification record."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
