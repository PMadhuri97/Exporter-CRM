"""orchestration — empty placeholder (epic4-reference).

Fully out of scope, and unlike the other excluded modules there is nothing
schema-related to bring over: the real orchestration module has no
migrations/ directory (it owns no tables — it is pure Temporal
workflow/activity glue over onboarding, settlement, rails and payments) and
no domain/entities/ that any in-scope module's relationships resolve
against. bootstrap.py's Base.metadata imports never reference it either.

This empty package exists only so importlinter.ini's architecture contracts
(which name app.modules.orchestration in a few forbidden/source module
lists, since they describe the real platform) can still resolve the dotted
path instead of erroring with "module does not exist". It carries zero code.
"""
