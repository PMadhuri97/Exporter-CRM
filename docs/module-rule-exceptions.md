# Module-rule exceptions

The architecture (§2.5, *The module rule, and its one exception*) says all
connecting code lives in the `onboarding` module, and that **no file in the
`kyb`, `cases`, `customers` or `compliance` modules is edited**. Those modules
were delivered against tickets that stay valid only while untouched, and
keeping all coupling in one place means it can be removed in one place.

Every departure from that rule gets its own entry below, with the reason and
the date. An exception that is not written down here is not an exception — it
is a rule violation. Adding one requires the same written record, and the
architecture permits no exception at all without it.

---

## EX-001 — Role gates on two compliance read routes

| | |
|---|---|
| **Date** | 2026-09-25 |
| **Module** | `compliance` |
| **File** | `backend/app/modules/compliance/api/router.py` |
| **Decision reference** | Architecture decision 11 (§6.1), implemented as Dev1 task L1-08 |
| **Scope** | Authorization only. No business logic, schema, service or response shape was touched. |

### Routes

| Route | Before | After |
|---|---|---|
| `GET /api/v1/compliance/approvals/{transaction_id}` | `Depends(get_current_active_user)` — any authenticated account | `require_role(COMPLIANCE, ADMIN)` |
| `GET /api/v1/compliance/screenings/{transaction_id}` | `Depends(get_current_active_user)` — any authenticated account | `require_role(COMPLIANCE, ADMIN)` |

### Reason

Both routes checked only that the caller held a valid token, not what role it
held. `POST /api/v1/auth/register` is unauthenticated and grants `API_USER`,
so anyone able to reach the sign-up route could then read a transaction's
sanctions-screening outcome and its maker-checker approval state.

Decision 11 settles the trade-off explicitly: an open route is worse than
bending the module rule once, on the record. The change is two dependency
swaps and two OpenAPI `403` entries, which is the smallest edit that closes
the gap.

### What was changed

- Added a module-level `_COMPLIANCE_OR_ADMIN = require_role(UserRole.COMPLIANCE, UserRole.ADMIN)`,
  mirroring the pattern the same file already uses for its two `POST` routes.
- Swapped the two read routes' `get_current_active_user` dependency for it.
- Documented `403` in each route's `responses` block, per the working rule that
  every route declares its roles and documents its refusal (§7.5).
- Removed the now-unused `get_current_active_user` import.

### What was *not* changed

`ComplianceService`, the compliance schemas, the domain entities, the
migrations and the two `POST` routes' existing `require_role(COMPLIANCE)`
gates are untouched. The two routes' behaviour for a `COMPLIANCE` or `ADMIN`
caller is identical to before.

### Reversal

Delete `_COMPLIANCE_OR_ADMIN`, restore the `get_current_active_user`
dependency and import, and drop the two `403` entries. Nothing else depends on
this change.

---

*No further exceptions have been granted. The `kyb`, `cases` and `customers`
modules remain unedited.*
