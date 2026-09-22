"""
Onboarding workflows.

``OnboardingWorkflow`` (``onboarding_workflow.py``) orchestrates one onboarding
request from DRAFT to ACTIVE on Temporal. Its activities live in
``application/activities.py``; it is started by
``application/onboarding_workflow_service.start_onboarding_workflow``.

The legacy identity-provider foundation (registration and the inbound Sumsub
webhook) still runs synchronously and is not part of this workflow.
"""
