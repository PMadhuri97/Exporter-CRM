# compliance

Business domain. Public facade is `__init__.py` — the only import surface for other modules (ARCHITECTURE.md §6).

## Effective-dated registries

Every registry this module reads — purpose codes, their corridor mappings, sector
classifications, external code mappings, and the compliance rules themselves — is
**effective-dated**. A row is not a fact; it is a fact *for a period*. Resolution is
therefore always against the caller's `as_of_date` (or `transaction_date`), **never
against today**: re-running an assessment must not change what a payment was obliged
to do when the money moved, and a payment backdated to before a regulator renumbered
its codes must still carry the code that was in force then.

The single rule is `domain/policies/effectivity.py::is_effective_at`, a half-open
window `[effective_from, effective_to)`. `effective_to = NULL` means open-ended.
Anything comparing dates against a registry row goes through it rather than
hand-rolling the comparison — the Postgres exclusion constraints are built on
`daterange(..., '[)')` to match, so a divergence here silently disagrees with what
the database will accept.

**Repositories return every row; the application layer picks.** Ports such as
`PurposeCodeRepository.get_canonical_history` and `SectorRiskRepository` deliberately
return lists without filtering by date. Which row is in force is a domain decision,
not a query decision, and a query that quietly dropped a second row would hide the
seed-data error the exclusion constraints exist to surface.

The consequence worth knowing before you write a lookup: **a code has no single
"current" row.** A code retired and later reinstated is two rows with a gap between
them, which is why `get_canonical_history` replaced an earlier single-row
`get_canonical`. Where a constraint guarantees at most one row can be in force —
`ex_purpose_code_canonical_validity` does — take the first match and stop
(`application/validation.py`, `application/settlement_assessment.py`):

```python
history = await repository.get_canonical_history(canonical_code)
row = next(
    (r for r in history if is_effective_at(r.effective_from, r.effective_to, as_of_date)),
    None,
)
```

`None` is a real answer — no version in force on that date — and is distinct from an
unknown code, which returns an empty history.

Where a constraint does *not* rule out two rows in force at once, collect the matches
and treat more than one as an error rather than picking. Corridor mappings are the
live case: `ex_purpose_code_mapping_validity` includes `external_standard_version` in
its key, so it only forbids overlap *within* one revision, and two revisions may still
claim the same corridor on the same date — guessing would put an arbitrary regulatory
code on a payment. `application/sector_risk_service.py` keeps the same shape even
though its exclusion constraint makes the ambiguous case unreachable, so that a broken
constraint surfaces instead of being silently absorbed.

Either way, do not add a third resolution strategy; if the existing one is wrong, fix
it in one place.

## Reference data

The registries are seeded from `deployments/gitops/reference-data/compliance/`, not
from application code. Adding a corridor or a purpose code is a YAML change and
nothing else. Loaders replace the tables wholesale on boot behind a Postgres advisory
lock (BUILD.md #6), so seed files are the source of truth and edits made directly in
the database are lost on the next start.

When a regulator publishes a new revision of a code set, **close the existing row with
an `effective_to` and add a new one** — never edit a row in place, or payments already
filed under the old revision stop being explicable.
