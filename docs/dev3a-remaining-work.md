# Dev3a — what is left, and who owns it

**As of 27 September 2026**, after the PR audit of `feature/dev3a-conversation-followups`
(L3-01a, L3-02, L3-03, L3-04, L3-11a), with the review fixes in §1 applied.

**Nothing below is a code defect.** Every defect the audit found is fixed and tested
(§1). What remains is either a **decision**, a **review the plan requires**, or
**another developer's task**. It is grouped by who acts next, and each item says
whether it has to happen **before this PR merges** or can follow it.

| When | Items |
|---|---|
| **Before merge** | §2.1 the PDF in `docs/` · §3 Dev1's review of the shared files · §4 Dev2's review of 0016 and `sample_data.py` |
| **After merge** | Everything else |

Verification with the fixes applied: §8.

---

## 1. Fixed during the audit (for the record, nothing to do)

So a reader does not re-raise them:

| Finding | Fix |
|---|---|
| `next_due_at` without a timezone reached the service and raised `TypeError` — a 500 | `AwareDatetime` on `CompleteFollowUpRequest.next_due_at`; now a 422 |
| Two simultaneous completions of one follow-up: the loser hit `uq_follow_up_completion_activity_id` as a raw `IntegrityError` — a 500 | `FollowUpService._require_follow_up` locks the activity row (`SELECT … FOR UPDATE`); the second waits and gets `FOLLOW_UP_ALREADY_COMPLETED` (409) |
| Follow-ups page fetched 50 rows and had no paging; soonest-due-first order meant Done/All only ever showed their oldest 50 | Previous/Next pager from `follow_ups_total`; resets on tab/filter change; steps back if a completion empties the page |
| Follow-ups seeder matched by `(customer_id, subject)` with no order; the RESCHEDULED seed's replacement shares the subject, so a re-run could reschedule again | `order_by(occurred_at, id).limit(1)` picks the original; uses Dev2's `SAMPLE_DATA_ACTOR` instead of a copy |
| Overdue tab listed every parked company, including ones due next quarter | New `check_backs_due_only` query parameter (on or before today, UTC), used by the Overdue tab |
| Sidebar lit both **Exporters** and **Follow-ups** on `/exporters/follow-ups` | Only the most specific matching row is active (also `aria-current`); `Sidebar.test.tsx` added |
| Moving the gauge did not refresh the Follow-ups list's check-backs | `useSetExporterConversation` invalidates `followUps` |
| Check-back date picker offered past days; a hook comment claimed the company response carries the gauge | `min` set; comment corrected |

Contract notes added in `engagement.md` §5.6 and §7.1. `frontend/openapi.json` and
`src/lib/api/schema.ts` regenerated.

---

## 2. Programme lead — decisions

### 2.1 The architecture PDF is committed to `docs/` — **decide before merge**

The PR adds `docs/Exporter-CRM-Architecture-and-Plan.pdf` (1.8 MB binary). Until now
it was kept out of the repository. **This is the one item whose cost changes at
merge:** deleting it later removes it from the tree but not from history, so every
clone carries it permanently.

- Keep it: the committed prompts (`docs/dev3a-*.md`, `docs/dev3b-*.md`) name that
  path as their source of truth, and they then resolve.
- Drop it: `git rm docs/Exporter-CRM-Architecture-and-Plan.pdf` before committing,
  and accept that the prompts point at a file each developer holds locally.

The five prompt files (`dev3a-prompt-…`, `dev3a-phase1/2-prompt-…`,
`dev3b-prompt-…`) are small text and harmless either way.

### 2.2 The seam commit was not a separate PR — accept, no action

The plan (§5 of the 3A prompt) wanted the shared-file anchors landed alone and
reviewed by Dev1 first. Here they arrived in the same single commit as the feature
work. Splitting them out now means rewriting the branch history, for no change in
the result. Recommendation: accept, and have Dev1 review those files inside this PR
(§3).

### 2.3 Re-dating a `NOT_NOW` check-back — **product decision, after merge**

Today a company at `NOT_NOW` cannot have its check-back date changed without first
moving to another value: a move to the value already held is refused
(`INVALID_CONVERSATION_TRANSITION`, `engagement.md` §1.1). If "they said call back
in March, now they say May" should be one step, the contract has to allow
`NOT_NOW → NOT_NOW` with a new date. **Owner once decided: Dev3a** — a contract
change plus a service/`allowed_moves` change. Cheapest before the §10
acknowledgements are collected.

### 2.4 Retiring `GET /exporters/activities/pending` — after merge

It predates completions and still lists completed follow-ups (documented in
`engagement.md` §5.6). `GET /onboarding/follow-ups` is the correct list now. The
frontend does not call the old route. Decide whether to deprecate it; **owner:
Dev3a**, with Dev2 (whose L2-03 edit is in it).

### 2.5 Environment, not code — **owner: whoever takes U6 (CI)**

- 24 backend tests fail with `password authentication failed for user "audit_ro"`
  / `"ledger_ro"` / `"settlement_ro"` (`platform/idempotency`,
  `audit/test_idempotency_violations.py`). They fail identically on `main`: the
  local database's read-only role passwords no longer match the test settings. The
  quality-gate baseline has moved from 22F/5E to **29F/22E** until this is fixed.
- Dev3a's note (phase 1 §2.7) says the database they used was stamped at
  `onboarding_0013_risk_check`, a revision from an abandoned branch. The audit
  database was not affected, but any machine that is needs `alembic stamp` fixing.

---

## 3. Developer 1 — review before merge, then register

**Before merge** (architecture §8.1: Dev1 owns these files):

1. The anchor blocks and 3A rows in the nine shared files: `exceptions.py` (12 new
   classes), `domain/entities/__init__.py`, `infrastructure/repositories/__init__.py`,
   `application/__init__.py`, `tests/contract/test_route_authorization_coverage.py`,
   `tests/integration/test_route_authorization.py`, `types.ts`, `routes.tsx`,
   `Sidebar.tsx`.
2. **`Sidebar.tsx` now contains an audit fix** (most-specific active row, §1), plus
   the new `layout/Sidebar.test.tsx`. Behaviour for existing rows is unchanged except
   that only one row is ever active.

**After merge:**

3. `docs/contracts/migration-register.md`: the 0016 row still says "Follow-up
   completion (locked)", parent `0014`, "not started". It is now: conversation
   gauge + check-back column + follow-up completion, parent
   `onboarding_0020_retire_lifecycle`, merged. The 0018 row's parent becomes
   `onboarding_0016_engagement`.
4. Decide `/follow-ups` (top level, via `routes/AppRouter.tsx`) versus the current
   `/exporters/follow-ups` (phase 2 note §3). Either works; the sidebar fix makes
   the current one correct.
5. Optional: type `HistoryEntryResponse.details` as `dict[str, Any]` so
   `ConversationPanel.test.tsx` needs no cast (phase 2 note §2.6).
6. Acknowledge `engagement.md` (its §10 table) — the error codes in §7.
7. Authoritative API regeneration at the milestone (L1-14).

---

## 4. Developer 2 — review before merge

The 3A prompt (§3) says 0016 "needs Dev 2's review **before merge**":

1. **Migration 0016 on `exporter_profile`:** two columns (`conversation`
   `NOT NULL DEFAULT 'NOT_CONTACTED'`, `conversation_check_back_on DATE NULL`),
   `ck_exporter_profile_conversation_check_back`, `ix_exporter_profile_conversation`
   and the partial `ix_exporter_profile_conversation_check_back`. Mapped on
   `ExporterProfile` and nothing else in the table touched.
2. **`sample_data.py`:** three seeder hooks, the `SECTION_9_3_SLUG` report row, and
   `main()` printing it; plus the matching edit to
   `test_company_record_0014.py::test_sample_data_is_deterministic_and_safe_to_run_again`.

**After merge:** acknowledge `engagement.md` §2.1, and update
`docs/dev2-remaining-work.md` §4 — its items 4.1 (ORM foreign keys on contact and
activity), 4.3 (0016 parent) and 4.4 (tests/sample data) are **done by this PR**.

---

## 5. Developer 3B — after merge

1. **Seam S1:** call `ConversationService.mark_ready_now_for_opened_deal(company_id,
   deal_id=…, actor_id=…)` from `DealService.open_deal`, in the same session. It
   flushes and never commits, is idempotent, and clears any check-back date.
2. **Seam S2:** publish `api/deals.ts` / `hooks/deals.ts`; the "open a deal" button
   then goes in `components/OpenDealPrompt.tsx` only (whoever gets there first).
3. **Migrations:** 0018's `down_revision = "onboarding_0016_engagement"`.
4. **Barrels:** each late import in the three backend `__init__.py` files needs
   `# noqa: E402` (phase 2 note §2.5).
5. Acknowledge `engagement.md` §6.

---

## 6. Developer 4 — after merge

Acknowledge `engagement.md` §1: the conversation gauge is not the background
check, and neither reads the other. Nothing to build.

---

## 7. Developer 3a — after merge

1. **Collect the acknowledgements.** L3-01a's done-when is "`engagement.md`
   merged; 3B, Dev 2 and Dev 4 have each confirmed". Every row in its §10 is still
   *pending*.
2. Confirm the review of Dev2's L2-03 edit to
   `ExporterActivityRepository.list_pending` (`dev2-remaining-work.md` §4.2). The
   audit read it: an outer join to `exporter_profile.name`, correct.
3. §2.3 and §2.4 if the lead says yes.
4. Optional, per the plan's rebalancing valve: offer 3B the read-only document list
   screen (L3-11b).

---

## 8. Verification with the §1 fixes applied

```
alembic heads            -> onboarding_0016_engagement (head)      # exactly one
upgrade / downgrade -1 / upgrade                                   # clean
ruff                     -> 16 findings, all pre-existing
lint-imports             -> 19 kept, 0 broken
backend suite            -> 29 failed, 3472 passed, 6 skipped, 22 errors
                            identical failure set to the PR before the fixes;
                            none in onboarding; 27 known + 24 role-password (§2.5)
tsc                      -> clean
eslint                   -> 0 errors, 2 pre-existing warnings
vitest                   -> 78 passed (10 files)
vite build               -> ok
```

The two defect tests (`test_two_concurrent_completions_give_one_record_and_one_clean_refusal`,
`test_a_next_due_date_without_a_timezone_is_a_422_not_a_500`) and the sidebar test
fail against the PR's original code and pass with the fixes.
