# Relationship manager ownership and compliance review assignment: audit and plan

**Date:** 7 October 2026 · **Base:** `main` @ `d449485` · **Status:** plan only. No code has been changed. **Business decisions agreed 7 October 2026 (§11).**
**Scope:** the Exporter CRM (`backend/app/modules/onboarding`, `frontend/src/modules/onboarding`) and the platform auth and permission code it uses.

---

## 0. Summary

Most of the proposal stands. The repository already has the hard parts: a maker-checker engine enforced in the service and the database, append-only decisions, proposals and history, row locking, and an unused `relationship_manager_user_id` column. What is missing is **who** is working on something: a named relationship manager, a named reviewer, worklists, waiting times and a view for the Compliance lead or admin. The plan adds two current-value columns, one index, a set of history events, about ten routes and four screens. Assignment events go into the existing append-only history log, so no new audit table is needed. Concurrent edits are handled with a field-level "seen value" check that reuses the row lock already in place. No version column is needed.

Six parts of the proposal need to change:

1. **On Hold cannot be proposed from a review.** The engine allows `IN_REVIEW → CLEAR | FLAGGED` and then `FLAGGED → ON_HOLD`.
2. **No Compliance Lead role exists.** Use the existing custom-role and permission mechanism instead of adding a role.
3. **Lead-assigned checker: defer.** A pooled checker plus a senior-approval permission covers the real need.
4. **High risk gets a senior checker, not a third approver.**
5. **Notifications in v1 should be computed worklists and badges.** A notification table can come later, together with email.
6. **SLA has to follow business hours.** Otherwise a 4-hour approval target produces a false "overdue" every evening.

The business decisions are now agreed (§11):
- **Who can be RM:** OPERATIONS users only.
- **Claiming and changing an RM:** anyone eligible can claim a company with no RM; changing an existing RM needs ADMIN or `exporters:assign_rm`.
- **Lead capabilities are permissions,** not roles: `exporters:assign_rm`, `compliance:assign` and `compliance:approve_high_risk`.
- **High risk:** a HIGH or CRITICAL CLEAR needs a senior checker. There is no third approval stage.
- **RM requirement:** enforced when someone acts, never as a database rule.
- **SLA:** the architecture is agreed and the values stay configurable.
- **Notifications in v1:** computed worklists and badges only.
- **Concurrency:** field-level conflict detection.

What remains is listed in **Decision status** at the end.

---

## 1. What exists today

| Area | Finding | Where |
|---|---|---|
| Company record | `ExporterProfile` is one row per company. Gauges (`background_check`, `conversation`, `qualification`, `journey`) are current-value columns **on the same row**, and each has a single writer service | `domain/entities/exporter_profile.py` |
| Owner field | `relationship_manager` is free text (255). It is in `_EDITABLE_FIELDS`, so any staff user can PATCH it | `application/exporter_profile_service.py:145` |
| RM user link | `relationship_manager_user_id` is a nullable UUID with no FK to `auth.users`, which is deliberate and matches the codebase's actor-id convention. **Nothing writes it.** It is already returned in every company response | migration `onboarding_0009_rm_user_id`, `api/schemas/exporter.py:304` |
| RM and masking | Masking was already decoupled from ownership. `can_reveal_identifiers` admits COMPLIANCE and ADMIN only, and the ownership exception was removed so that populating the column cannot widen PII access. The column docstrings in the entity and migration 0009 still describe the old purpose and are out of date | `api/schemas/masking.py:59`, `platform/authorization/catalog.py` |
| Roles | The enum has ADMIN, COMPLIANCE, OPERATIONS (shown as "RM" in the UI and demo), DEVELOPER and API_USER. **There is no lead or manager role.** Custom roles exist (`auth.role`, `users.role_id`, `require_permission`), but CRM routes use `require_role`. Frontend capabilities come from the role enum (`platform/access/capabilities.ts`), except Settings, which reads `/auth/me/permissions` | `platform/authentication/models.py`, `platform/authorization/services.py` |
| Staff lookup | `display_names()` resolves user ids to names. **No CRM route lists assignable staff:** `/auth/users` needs `users:view` | `platform/authentication/directory.py` |
| Deactivation | `users.is_active` and `deactivated_at`. Deactivation revokes refresh tokens. Auth cannot import CRM modules (module rule), so it cannot hand over records itself | `api/rest/auth/router.py` |
| Company edits | One field per PATCH from the UI (`CompanyPanel.patchFor`). The service locks the row `FOR UPDATE`, writes one `profile` history row per changed field with `from` and `to`, and commits once. **No stale detection:** no version, no ETag, no If-Match. `updated_at` is ORM `onupdate=now()` and changes on *every* write to the row, gauge moves included | `exporter_profile_service.py:update_profile`, `platform/database/models.py:TimestampMixin` |
| Stale-check precedent | Moves accept a `seen_value` and return 409 `BACKGROUND_CHECK_STATE_CHANGED` when it no longer matches under the lock. Qualification criteria return `QUALIFICATION_CRITERION_CHANGED`. Proposals become stale on a fingerprint change | `background_check_service.record_decision`, `exceptions.py:619` |
| Compliance check | The background-check gauge has six states and nine legal moves (contract §3). Move 1 (start) is open to OPERATIONS, COMPLIANCE and ADMIN. `MORE_INFO` is set by COMPLIANCE or ADMIN and returned by any staff user with a note. **The review is a gauge state, not an entity.** There is no review row to hang a reviewer on | `docs/contracts/background-check.md` §2–3 |
| Maker-checker | `IN_REVIEW→CLEAR`, `IN_REVIEW→FLAGGED` and `FLAGGED→ON_HOLD` are proposals (202). Approve and reject are for any COMPLIANCE or ADMIN user except the proposer (403 `BACKGROUND_CHECK_SELF_APPROVAL`, also a DB constraint). Withdraw is for the proposer only. There is one open proposal per company, and while it is open nothing else moves. Approving a stale proposal is refused. A kill switch exists, but it can be off only in local and test environments | contract §12.5, `domain/entities/background_check_proposal.py` |
| Risk vocabulary | `BackgroundCheckRisk` = `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`, recorded on a CLEAR proposal and decision only (refused on other outcomes) | `domain/entities/background_check_enums.py` |
| Queue | `GET /background-check/proposals?status=open&awaiting=me` lists the oldest first and excludes the caller's own proposals. It is shown on the Approvals page and the Home card. **There is no "in review" list** (the `ApprovalsPage.tsx` header says it waits for the backend) and no company list filter on `background_check` | `api/background_check_router.py:895`, `pages/ApprovalsPage.tsx` |
| Immutability | Decisions, evidence, proposals, resolutions, check cycles and history rows are append-only at both layers (`AppendOnlyRepository` plus a `prevent_mutation()` trigger). Company fields stay editable after a CLEAR | contract §5, `history-row.md` |
| Audit | One shared append-only history log (`exporter_lifecycle_history` through `HistoryService.record`). `dimension` is a free string, so **a new dimension needs no migration**. `HIDDEN_FROM_DEVELOPER` exists | `domain/history_dimensions.py` |
| Notifications | `modules/notifications` handles outbound webhook and email for **payments**. `notification_events.transaction_id` is a non-null FK to `payments.transactions`. **It cannot be used for staff in-app notifications. No in-app notification model or UI exists.** | `modules/notifications/domain/entities/notifications.py` |
| Scheduling | APScheduler runs platform jobs only. No CRM job, no business calendar, no holiday list | `main.py` lifespan |
| Next migration | `onboarding_0044` (revision id must be ≤ 32 characters) | `migrations/` |

**Contradictions with the brief**

- **On Hold** is not a review outcome. It is a second maker-checker move from FLAGGED.
- **"RM starts the review"**: any staff role can start it today, and nothing ties the starter to the RM.
- **"Compliance Lead / escalate to lead"**: the role does not exist. The agreed answer is a permission, not a role (§11).
- **"Later save overwrites silently"** is true at the level of intent. At the database level the saves are serialised and the history keeps an accurate `from` value, so no data is lost: the problem is only the missing warning.
- **"Records immutable after finalisation"** is true for the decision trail, but not for the company record.
- **The UI says "Owner" on the company page and "RM" on lists.**

---

## 2. Enterprise comparison

| Pattern | How mature products do it | Relevant? | Now or later | Simplest version for us |
|---|---|---|---|---|
| Single primary owner | Salesforce and Dynamics: every record has one `Owner` (a user or a team). HubSpot: a company owner | Yes | **Now** | `relationship_manager_user_id`, one OPERATIONS user |
| Teams and shared ownership | Salesforce Account Teams, Dynamics owner and access teams | Later | Defer | None until a second role per company (credit, ops) exists |
| Mass transfer and reassign on exit | Salesforce *Mass Transfer Records* (from user to user, optionally keeping the team). Dynamics *Reassign Records* on the user. HubSpot advises reassigning before deactivating | Yes | **Now** | Bulk reassign by filter (from RM, optional journey), with a reason and a run id |
| Ownership separate from permission | Salesforce: owner and sharing rules are separate concepts | Yes | **Now** | Ownership grants nothing. This is already true for masking |
| Queue with pick, release and assign | Dynamics queues: **Pick** sets *Worked By*, **Release** clears it, and **Assign** is a supervisor push | Yes | **Now** | Claim, release, and assign by a holder of `compliance:assign` |
| Push routing by capacity and skills | Salesforce Omni-Channel (routing model, capacity, push timeout), Pega Get Next Work (urgency) | No (2–6 officers) | Not justified | — |
| Maker-checker | Sumsub and Didit 4-eyes: the maker's resolution is staged and only applied by a checker. Didit enforces "submitter cannot approve" on the server, and a rejection returns the case to the maker | Yes | **Exists** | Keep the current engine |
| Checker selection | Sumsub and Didit: checkers are a designated *pool* (blueprint or queue), and the maker does not pick | Yes | **Now (pool)** | Shared queue, as built |
| Separation of duties beyond self-approval | ServiceNow: the requester cannot approve at any stage, typically by excluding them from the approval group | Yes | **Now** | Exclude the proposer, the reviewer and the company's RM from approving |
| Multi-step approval by criteria | Salesforce approval processes: steps with entry criteria, record lock, submitter recall | Partly | Now (one rule) | A senior permission is required to approve a high-risk CLEAR. No third step |
| SLA with a business schedule | ServiceNow SLA definitions with a schedule and holidays, plus 50/75/100% milestones. Pega goal, deadline and passed deadline | Yes | **Now (computed)** | Due time computed from a business calendar, with "due soon" and "overdue" flags. No timers |
| Escalation | ServiceNow and Pega: escalation actions at milestones | Yes | Now (visibility only) | *Overdue* list and badge for holders of `compliance:assign`. No automatic reassignment |
| Optimistic concurrency | Dataverse `RowVersion` and `IfRowVersionMatches`, and ETag/If-Match on the Web API. Salesforce collision detection is record-level and is known for false conflicts when integrations touch the record | Yes | **Now** | **Field-level** seen value, because our gauges share the row |
| Record locking during approval | Salesforce locks the record while an approval is pending | Partly | Exists | Already true for the check: nothing moves while a proposal is open |

---

## 3. Gap analysis

| Area | Current | Proposed | Gap | Reusable | Change | Risk |
|---|---|---|---|---|---|---|
| RM relationship | Free text, and a user-id column nothing writes | One OPERATIONS user per company | Nothing writes the id, and there is no staff picker | Column 0009, `display_names` | Writer service, picker route, backfill | Low |
| RM assignment | Anyone edits the free text | Self-claim when unassigned; change only by ADMIN or `exporters:assign_rm`, with a reason | No assign action | `_lock_profile`, `HistoryService` | `POST …/relationship-manager` and a `relationship_manager` history dimension | Low |
| RM reassignment | — | Single and bulk | None | Lock, history | Bulk route with a run id | Medium (bulk lock order) |
| Ownership history | Free-text edits recorded as `profile` rows | Clear history | No user-level history | History log (append-only) | New dimension with user ids in `details` | Low |
| Company permissions | `_STAFF` edits everything | Unchanged | — | — | None. Ownership never gates | — |
| PAN/GSTIN masking | COMPLIANCE and ADMIN only | RM gains nothing | Out-of-date comments | `can_reveal_identifiers`, `test_masking_sweep.py` | Regression test and comment fix | Low |
| Concurrent editing | Row lock, last write wins, no warning | Warn on the same field | No stale check | `seen_value` pattern, existing lock | Optional `seen` map on PATCH, 409 `COMPANY_FIELD_CHANGED` | Low |
| Review assignment | None | Claim, or assign by a holder of `compliance:assign` | No reviewer | — | `background_check_reviewer_id` and `_assigned_at` columns | Medium |
| Review queue | None ("in review" not served) | Awaiting review | No route | Due-list route shape | `GET /background-check/reviews?view=…` | Low |
| Reviewer identity | Proposer = `created_by` | Named reviewer | Not enforced | Proposal provenance | Propose and request-info require the reviewer (auto-claim if unassigned) | Medium |
| Approval queue | Shared, `awaiting=me` | Shared | Excludes only the proposer | Route exists | Add eligibility (reviewer, RM, high-risk) | Low |
| Checker identity | `approved_by` on the decision | Independent | Reviewer and RM may approve | DB constraint for the proposer | Service checks for reviewer and RM | Low |
| Maker-checker | Service and DB | Same | — | All | — | — |
| Reassignment | — | A Compliance lead or admin (`compliance:assign`) reassigns | — | — | Assign route with permission and reason | Low |
| Notifications | None in-app | In-app | No infrastructure | Queue routes, Home cards | Computed worklists and nav badges (v1). No inbox, no email | Medium (expectations) |
| SLA | None | Configurable review, approval and information-request clocks | No calendar | `compliance_settings.py` | Pure business-time function and settings | Medium |
| Escalation | None | To the Compliance lead or admin | No lead role | Custom roles | `compliance:assign` permission and Overdue view | Low |
| High-risk approval | Any checker | Senior checker for a HIGH or CRITICAL CLEAR | No rule | Risk on the proposal | `compliance:approve_high_risk` permission | Low |
| Audit trail | Decisions and proposals | Plus assignments | None for assignments | History log | `background_check_assignment` dimension, hidden from DEVELOPER | Low |

---

## 4. Challenging the proposal

**RM**

1. **Can a Lead have no RM?** **Decided: yes.** An RM is optional at the Lead stage. Leads are imported in bulk, and forcing an RM onto them creates fake ownership. They are shown in an *Unassigned* view instead. Starting a compliance check is an exception, covered in item 2.
2. **Must a Prospect always have an RM?** **Decided:** an RM is expected for normal pipeline actions. It is enforced **at the action**, never as a database rule.
   - The QUALIFIED outcome form prompts for an RM. An OPERATIONS caller defaults to themselves.
   - Starting a compliance check on an in-pipeline company, including a Lead, prompts for an RM if none is set.
   - Existing and imported Prospects, and those created by the RXIL intake (ADMIN), may temporarily have no RM. They appear in *Unassigned Prospects*.
   - A hard database rule would break those paths.
3. **Do buyer-only companies need an RM?** **Decided: not in v1.** Compliance is never blocked because a buyer-only company has no RM. Their information requests go to a shared *Unowned info requests* list. Routing them to the seller's RM through `created_via_deal_id` is deferred.
4. **One primary RM or several owners?** **Decided:** one primary RM.
   - **Only OPERATIONS users can be RMs.** ADMIN administers and assigns ownership but is not a normal RM. COMPLIANCE is never an RM, which also keeps the rule "the reviewer and checker are not the RM" meaningful.
   - No new RM role. The existing `relationship_manager_user_id` is used.
   - Several owners would dilute accountability, which is the whole point of the field.
5. **Teams?** Later. There is no second relationship role yet.
6. **Who can change ownership?** **Decided:**
   - On a company with **no RM**, an eligible user (OPERATIONS) may claim it by setting **themselves** as RM.
   - Assigning someone else, or changing or clearing an existing RM, requires **ADMIN** or **`exporters:assign_rm`**. That permission is held by sales or CRM lead custom roles. A **reason** is mandatory for a change or a clear.
   - Every assignment is a `relationship_manager` row in the existing append-only history log.
   - This is tighter than today, where anyone can edit the free-text Owner field.
7. **Should ownership affect visibility?** **Decided: no.** It adds a *My companies* filter only. It grants no access, and no access to masked identifiers.
8. **Is bulk reassignment enough when someone leaves?** Almost. Two more views are needed, because auth cannot call the CRM when it deactivates someone:
   - *Companies with an inactive RM*.
   - The same view for reviews held by an inactive reviewer.

   Bulk reassignment should also allow splitting a filtered list, not only "everything to one person". The target is always an active OPERATIONS user.
9. **Is the conflict warning right?** **Decided: yes,** using the codebase's own 409 seen-value pattern. The message names who made the change and when, taken from the latest history row for that field. The user's typed input is kept so they can reload and reapply it.
10. **Field-level or record-level conflicts?** **Decided: field-level.** There is no version column and no ETag in v1.
    - `updated_at` changes on every gauge, marker or conversation move on the same row.
    - A record-level check would therefore fire on an RM's edit whenever compliance moved the check. That is the Salesforce false-collision problem.

**Compliance**

11. **Is "Assign to me" the right v1 mechanism?** **Decided: yes.** It is backed up by assignment from a holder of `compliance:assign`.
12. **Pull, push or hybrid?** **Hybrid.** Officers pull from *Awaiting review*. A Compliance lead or admin (`compliance:assign`) pushes when an item sits too long.
13. **Workload-based automatic assignment?** **Decided: not in v1.** With fewer than 10 officers it is not worth it. The `compliance:assign` views show each officer's open count instead.
14. **Can the Compliance lead assign and reassign?** **Yes.** Any holder of `compliance:assign` can, meaning Compliance lead custom roles and ADMIN. A reason is mandatory when taking a review from someone. This is a permission, not a `COMPLIANCE_LEAD` role.
15. **Can anyone choose the reviewer?** Never the RM and never the maker. A holder of `compliance:assign` can. An officer may only claim for themselves. The reviewer never chooses their checker.
16. **How is maker-checker enforced technically?** The existing service check and DB constraint (proposer ≠ approver) stay the source of truth. Added on top:
    - A service-level check that the approver is neither the company's current RM nor the current reviewer.
    - The high-risk permission check.

    All of this runs under the company row lock that approval already takes.
17. **What if only two Compliance users are eligible?** It works: A reviews and B approves. If B is unavailable, ADMIN approves.
    - The queue serves `eligible_checker_count`.
    - When it is 0, the item goes to the *Needs attention* view for holders of `compliance:assign`. An example is a high-risk CLEAR whose only senior holder is its reviewer.
    - **At least two users must hold `compliance:approve_high_risk`** (decided), so one senior approver being away does not block high-risk CLEARs.
18. **What if the reviewer becomes unavailable?** A holder of `compliance:assign` reassigns the review. An open proposal survives a reviewer change. Only the proposer, or a holder of `compliance:assign`, can withdraw it (see the withdraw rule in §7).
19. **Can an officer release a review?** **Decided: yes.** The item goes back to Awaiting review with an optional note. Release is refused while their proposal is open: they withdraw it first.
20. **Should approvals expire or be reassigned?** No expiry. A pooled approval is never "assigned", so there is nothing to reassign; overdue approvals escalate. Staleness already invalidates proposals whose inputs changed.
21. **Are the proposed SLAs right?** **Decided:** configurable. The final numbers are not fixed yet. The brief's targets are the starting defaults:
    - Review: 1 business day.
    - Approval: 4 business hours.
    - Response to an information request: 1 business day.

    Review is measured from *assigned*. Time to pick up is a separate figure, measured from start. The review clock **pauses during MORE_INFO**, and the information-request clock runs instead.
22. **Business hours?** **Decided: yes.** The business hours are configurable and in Asia/Kolkata, with a configurable holiday list. There is no background scheduler: overdue status is computed on read.
23. **Does high risk always need a third approver?** **Decided: no.**
    - A CLEAR proposed with risk `HIGH` or `CRITICAL` (the existing `BackgroundCheckRisk` values) can be approved only by ADMIN or a holder of `compliance:approve_high_risk`.
    - That senior checker is the **second** independent person, not a third. The flow stays: reviewer proposes CLEAR, then an eligible senior checker approves, then the decision is final.
    - There is no third approval stage. A true three-step chain is deferred.
24. **Are Flagged and On Hold different?** **Decided: yes, and the correction stands.** A review ends in `IN_REVIEW → CLEAR | FLAGGED`. `FLAGGED → ON_HOLD` is a later decision on a flagged company, and it is also maker-checker.
    - Both are resting states with no review SLA.
    - The RM sees both under *Decisions on my companies*.
    - Neither reveals the reason text to DEVELOPER (already enforced).
25. **What happens after a rejected approval?** The gauge stays put and the reviewer stays assigned. The item returns to *My reviews* with "Returned: <reason>". After two rejections on the same check, it also appears in the `compliance:assign` views.
26. **Can the reviewer change their proposal after rejection?** Not edit it, because it is append-only. They make a **new** proposal or request more information.
27. **What must be immutable after the final decision?** It already is: the decision, its evidence, the proposal, the resolution, the cycle and all history rows, including the new assignment events. The reviewer column is cleared when the review ends; the trail stays in history. Company fields stay editable, which is out of scope here but a known risk: a PAN change after CLEAR does not reopen the check.

---

## 5. Recommended flow

```
LEGEND  [U] user action   (S) system action   <Q> queue/worklist   {P} permission   «A» audit (history dimension.event)

COMPANY  (RM = an active OPERATIONS user; ownership grants no visibility and no identifier access)
[U] create / import ──(S)──> LEAD   RM optional          <Q> Unassigned
[U] claim on unassigned {OPERATIONS, sets self only}       «A» relationship_manager.assigned
[U] assign an OPERATIONS user {ADMIN | exporters:assign_rm} «A» relationship_manager.assigned
[U] change / clear RM {ADMIN | exporters:assign_rm}, reason required
                                                            «A» relationship_manager.reassigned / .cleared
[U] record QUALIFIED {staff}: RM prompted (OPERATIONS caller defaults to self) ──(S)──> PROSPECT
(S) RXIL intake / import / existing -> PROSPECT without RM (allowed)   <Q> Unassigned Prospects
(S) buyer-only company: RM not required
[U] bulk reassign {ADMIN | exporters:assign_rm}, reason, run_id     «A» relationship_manager.reassigned ×N
(S) RM user deactivated                                    <Q> Inactive-RM companies

COMPLIANCE CHECK
[U] Start check {staff}; in-pipeline company with no RM -> RM prompt
      (OPERATIONS caller: self; ADMIN | exporters:assign_rm: picks an OPERATIONS user;
       anyone else: refused until an RM is set). Buyer-only: no RM needed.
    (S) gauge NOT_STARTED->IN_REVIEW, reviewer = none       «A» background_check (existing)
    <Q> Awaiting review     badge: all officers and holders of compliance:assign
[U] Assign to me {COMPLIANCE|ADMIN}, not the company's RM   «A» background_check_assignment.claimed
[U] Assign / reassign {ADMIN | compliance:assign}, reason     «A» …assigned / …reassigned
    (the RM never chooses the reviewer)
[U] Release {reviewer}                                      «A» …released  -> back to Awaiting review
    <Q> My reviews (reviewer)   <Q> In review, everyone's {ADMIN | compliance:assign}
[U] Reviewer requests info {reviewer}  IN_REVIEW->MORE_INFO     «A» background_check (existing)
    <Q> Info requested on my companies (RM) / Unowned info requests (buyer-only)
        review clock paused, information-request clock runs
[U] RM records what arrived {staff}  MORE_INFO->IN_REVIEW       -> back in My reviews
[U] Reviewer proposes CLEAR (risk) | FLAGGED {reviewer}   (never ON_HOLD directly; never names a checker)
                                                            «A» background_check_approval (existing)
    <Q> Awaiting approval (pool), excluding proposer/reviewer and RM;
        CLEAR with HIGH|CRITICAL only for {ADMIN | compliance:approve_high_risk}
        (the senior checker is the second person; there is no third stage)
[U] Checker approves ──(S)──> decision written, gauge moves, reviewer cleared,
                               PROSPECT->CUSTOMER if CLEAR (existing)    «A» existing + assignment.ended
[U] Checker rejects (reason) ──> gauge unchanged, back to reviewer's My reviews
[U] Proposer withdraws ──> back to reviewer
(S) FLAGGED: later proposal FLAGGED->ON_HOLD (same maker-checker); reassess/reopen
    -> IN_REVIEW with the actor as reviewer                 «A» …claimed
(S) computed on every read (no scheduler): due_at / overdue per item
    <Q> Overdue, Needs attention {ADMIN | compliance:assign}
NOTIFY (v1, computed only; no persisted inbox, no email): nav badges for My reviews,
  Awaiting approval, Info requested, Overdue; Home card "Decisions on my companies (14 days)"
  for RM and reviewer. Never a PAN/GSTIN or reason text in a badge or card.
```

---

## 6. Data model (migration `onboarding_0044_assignment`)

| Field | Why | Reuse? | Null | Who writes | Where |
|---|---|---|---|---|---|
| `exporter_profile.relationship_manager_user_id` | The RM (always an active OPERATIONS user when written) | **Reuse (0009)** | Yes (Leads, buyer-only, temporarily unassigned Prospects) | `ExporterProfileService.assign_relationship_manager` only | Main record, as a current value |
| index `ix_exporter_profile_rm_user` (partial, not null) | My companies, bulk reassign | — | — | — | 0044 |
| `exporter_profile.relationship_manager` (text) | Legacy label | Keep, **read-only** | Yes | Backfill only. Removed from `_EDITABLE_FIELDS` | Drop in a later release |
| `exporter_profile.background_check_reviewer_id` | The named reviewer, listed without a join (the codebase's current-value convention) | New | Yes (unassigned or not under review) | `BackgroundCheckService` only (the gauge's single writer) | Main record |
| `exporter_profile.background_check_reviewer_assigned_at` | Review SLA start, "with X since" | New | Yes. Null exactly when the reviewer is null (CHECK) | Same | Main record |
| Checker id | — | **Not needed**: `approved_by` on the decision and `created_by` on the resolution already record it | — | — | — |
| Assignment history | Immutable trail | **History log**, two new dimensions: `background_check_assignment` (events `claimed`, `assigned`, `reassigned`, `released`, `ended`; `details` = `{from_user_id, to_user_id, reason, cycle_id}`) and `relationship_manager` (events `assigned`, `reassigned`, `cleared`; `details` = `{from_user_id, to_user_id, reason, bulk_run_id}`) | — | Append-only, written in the same transaction | No new table |
| SLA timestamps | Due and overdue | **Derived**: start = the latest decision's `decided_at`; review = `reviewer_assigned_at`; approval = proposal `created_at`; info = the MORE_INFO decision's `decided_at` | — | Computed on read | No columns |
| Escalation state | — | Computed, never stored (no job to keep it true) | — | — | — |
| Version column | — | **Not needed**: the field-level seen value is checked under the existing row lock | — | — | — |

Add `CHECK (background_check_reviewer_id IS NULL OR background_check IN ('IN_REVIEW','MORE_INFO'))`. The check is enforced in the DB so a missed clear cannot leave a reviewer on a decided company. Update the out-of-date column docstrings that still describe the RM column as a PII-reveal key.

There is **no** database constraint requiring an RM (the requirement is enforced at the action, §4 item 2). There is no new role, user or notification table. The capabilities of a Compliance lead and a sales lead are permissions granted through the existing custom roles.

---

## 7. API and backend

All routes go under `/onboarding`. New routes use `require_permission` where a permission is the gate (the documented direction in `authorization/services.py`), and `require_role` elsewhere. Each route needs rows in both authorisation tables and regenerated OpenAPI artifacts.

**Permissions** are added to `catalog.py`. Each is checked as "ADMIN role **or** the permission", so editing ADMIN's seeded grants cannot lock administrators out of these actions.

| Permission | Allows | Intended holders |
|---|---|---|
| `exporters:assign_rm` | assigning someone else as RM, changing or clearing an RM, bulk reassignment | ADMIN; sales or CRM lead custom roles (enum OPERATIONS plus this grant) |
| `compliance:assign` | assigning and reassigning reviewers, withdrawing an absent proposer's proposal, the In review, Overdue and Needs attention views | ADMIN; Compliance lead custom roles (enum COMPLIANCE plus this grant) |
| `compliance:approve_high_risk` | approving a CLEAR with risk `HIGH` or `CRITICAL` | ADMIN; senior Compliance users. **At least two users should hold it** |

There is no `COMPLIANCE_LEAD` enum value. "Compliance lead or admin" means a holder of `compliance:assign`. A custom role needs `is_assignable` set to true. The frontend reads these three from `/auth/me/permissions`, as Settings already does.

| Action | Route | Auth | Rules | Audit | Errors |
|---|---|---|---|---|---|
| Staff picker | `GET /staff?role=OPERATIONS\|COMPLIANCE` | READER | Active users only: id, name, role. The RM picker asks for OPERATIONS | — | — |
| Assign RM | `POST /exporters/{id}/relationship-manager {user_id\|null, reason?, seen_user_id}` | Any OPERATIONS user may set **themselves** when the RM is null. Assigning someone else, changing a non-null RM, or clearing one needs ADMIN or `exporters:assign_rm` | Lock the row. The target must be an **active OPERATIONS user** (local `require_active_user` equivalent). Reason required on a change or clear. `seen_user_id` must match | `relationship_manager.*` | 403, 409 `RELATIONSHIP_MANAGER_CHANGED`, 422 inactive or not OPERATIONS, 422 missing reason |
| Bulk reassign | `POST /relationship-managers/reassign {from_user_id, to_user_id, company_ids?, journey?, reason, dry_run}` | ADMIN or `exporters:assign_rm` | Target must be an active OPERATIONS user. Lock companies in `customer_id` order (avoids deadlock). Skip rows whose RM has changed. Return the counts | One row per company and a shared `bulk_run_id` | 422 |
| My companies | `GET /exporters?relationship_manager=me\|<id>\|none` | READER | Filter only. Ownership never narrows what a reader sees | — | — |
| Edit field | `PATCH /exporters/{id}` plus optional `seen: {field: value}` | staff | Under the existing lock, compare each seen value with the current value. **Masked fields** compare `mask(current)` for that viewer, so no raw value is needed. A mismatch refuses the whole edit | existing `profile` rows | 409 `COMPANY_FIELD_CHANGED {field, changed_by_name, changed_at, current (masked per viewer)}` |
| Start check (existing) | `POST …/decisions` to `IN_REVIEW` from `NOT_STARTED` | as today | **Added:** an in-pipeline company with no RM needs one in the same request (`relationship_manager_user_id`, under the same rules as Assign RM). An OPERATIONS caller may name themselves. A caller who may not assign is refused. Buyer-only (`NOT_IN_PIPELINE`) companies are exempt | `relationship_manager.assigned` when set | 409 `RELATIONSHIP_MANAGER_REQUIRED` |
| QUALIFIED outcome (existing) | qualification outcome route | as today | **Added:** a person recording QUALIFIED on a company with no RM supplies one, under the same rules. The RXIL intake and imports are exempt | as above | 409 `RELATIONSHIP_MANAGER_REQUIRED` |
| Claim | `POST /exporters/{id}/background-check/reviewer/claim` | COMPLIANCE, ADMIN | Gauge is IN_REVIEW or MORE_INFO. Unassigned. Caller ≠ company RM | `…claimed` | 409 `REVIEW_ALREADY_ASSIGNED`, 409 `REVIEWER_IS_RM` |
| Assign or reassign | `PUT …/reviewer {user_id, reason}` | ADMIN or `compliance:assign` | Target is an active COMPLIANCE or ADMIN user and ≠ RM. Reason required when replacing someone | `…assigned` or `…reassigned` | 409, 422 |
| Release | `POST …/reviewer/release {note?}` | the current reviewer, ADMIN, or `compliance:assign` | No open proposal by the reviewer | `…released` | 409 `BACKGROUND_CHECK_PROPOSAL_OPEN` |
| Move and propose (existing) | `POST …/decisions` | as today | **Added:** request-info and propose need caller = reviewer. An unassigned check auto-claims for the caller in the same transaction. Assigned to someone else gives 409. A proposal never names a checker. RM's info return (move 4) is unchanged. Reassess and reopen set the actor as reviewer. Landing on CLEAR, FLAGGED or ON_HOLD clears the reviewer (`…ended`) | existing and new | 409 `REVIEW_ASSIGNED_TO_OTHER` |
| Approve (existing) | `…/proposals/{id}/approve` | COMPLIANCE, ADMIN | Existing proposer ≠ approver enforcement unchanged. **Added:** approver ≠ current reviewer and ≠ company RM. A CLEAR with `HIGH` or `CRITICAL` risk needs ADMIN or `compliance:approve_high_risk`. Approval is final: there is no further stage | existing | 403 `BACKGROUND_CHECK_CONFLICT_OF_INTEREST`, 403 `HIGH_RISK_APPROVAL_REQUIRED` |
| Withdraw (existing) | `…/withdraw` | the proposer, **or ADMIN or `compliance:assign`** (needed when the proposer has left) | — | existing | — |
| Worklists | `GET /background-check/reviews?view=awaiting\|mine\|in_review\|overdue\|needs_attention` | COMPLIANCE, ADMIN (`in_review`, `overdue` and `needs_attention` need ADMIN or `compliance:assign`) | Serves name, journey, RM name, reviewer name, `waiting_since`, `due_at`, `is_overdue`, `stage` (review, info or approval), `rejection_count`, `reviewer_inactive`. **Never an identifier** | — | — |
| Approval queue (existing) | `?awaiting=me` | — | Also excludes items where the caller is the reviewer or RM, or the item is high-risk and the caller lacks the permission. Adds `due_at`, `is_overdue` and `eligible_checker_count` | — | — |
| Info requests | `GET /background-check/info-requests?relationship_manager=me\|none` | staff | MORE_INFO companies, with the requested note (on the list only; never in a badge or card) | — | — |
| Badge counts | `GET /worklist/counts` | staff | One call for the nav: counts per list the caller can see. Counts only, no text | — | — |

**SLA:** a pure `business_time.add(start, duration, calendar)` and `elapsed()` in `domain/`, with configuration in `compliance_settings.py`:
- `CRM_SLA_REVIEW`, `CRM_SLA_APPROVAL`, `CRM_SLA_INFO`. The defaults are the brief's targets; the final values are not fixed.
- `CRM_BUSINESS_HOURS`, defaulting to Monday–Friday in `Asia/Kolkata`.
- `CRM_HOLIDAYS`.
- A "due soon" threshold at 75%.

Everything is computed on read. There is no scheduler or background job.

**Concurrency:** every write stays under `_lock_profile` (`FOR UPDATE`). Assignment writes take the same lock as moves, so claim, propose and approve serialise with each other. The existing history behaviour is unchanged. Add the new cases to `test_compliance_concurrency.py`.

---

## 8. Frontend (minimum)

Every new action and view is driven by the server's `allowed_actions`, or by `/auth/me/permissions` for the three new permissions. Nothing checks a role literal for "lead", and there is no Compliance Lead role in the UI.

- **Company page (`CompanyPanel.tsx`):**
  - Rename "Owner" to **Relationship manager**. The field becomes a staff picker (`/staff?role=OPERATIONS`) instead of free text.
  - When no RM is set, OPERATIONS users see **Assign to me**.
  - ADMIN and holders of `exporters:assign_rm` see **Assign**, **Change** and **Clear**, with a required reason for Change and Clear.
  - Everyone else, COMPLIANCE included, sees the RM read-only.
  - An inactive RM shows a warning chip.
  - Ownership history appears in the existing `HistoryTimeline` under the new dimension; no new panel.
- **Lists:**
  - The RM column shows the user's name.
  - Add *My companies* and *Unassigned* views to `CompaniesViewSwitch`. *Unassigned* includes unassigned Prospects.
  - ADMIN and holders of `exporters:assign_rm` get a *Reassign* bulk action: select rows, choose an OPERATIONS target, enter a reason, see a dry-run count, confirm.
- **Edit conflict:**
  - On 409 `COMPANY_FIELD_CHANGED`, the inline field shows "Changed by *X* at *time* to *value*. Reload before saving." with a **Reload** button that refetches the record.
  - The typed value is kept in the input so it can be reapplied.
  - `patchFor` sends `seen` for the edited field.
- **Approvals page → "Compliance work":**
  - The left rail gets sections *Awaiting review* (with **Assign to me**), *My reviews*, *Awaiting your signature* (existing) and *Re-KYC due* (existing).
  - For ADMIN and holders of `compliance:assign` only, it adds *In review (everyone)*, *Overdue* and *Needs attention*.
  - Each row shows the waiting time, an overdue or due-soon chip, a High-risk chip (from `RiskChip`, with "Senior approval" on HIGH or CRITICAL CLEARs) and "Returned ×n".
  - The right pane keeps the existing `BackgroundCheckPanel`.
- **Background-check panel:**
  - A reviewer line reads "Reviewer: *X* since *t*" or "Unassigned".
  - Claim, Release and Reassign appear as served by `allowed_actions`, which is extended with `CLAIM`, `RELEASE` and `ASSIGN`. Keep the existing rule that the frontend never decides permissions.
  - The start dialog asks for an RM when the server says one is required. It offers "Me" to an OPERATIONS caller and the picker to ADMIN or `exporters:assign_rm`, and does not ask for buyer-only companies.
  - The propose dialog offers CLEAR and FLAGGED from a review, and has no checker field.
  - Approve is hidden with a reason when the caller is not eligible.
- **Nav badges and Home cards (the v1 notification mechanism):**
  - Counts come from `/worklist/counts`, refetched on focus and every 60 seconds.
  - Home cards: *Info requested on my companies* and *Decisions on my companies (14 days)*.
  - No inbox and no email.
  - No PAN or GSTIN, and no reason text, in any badge or card.

---

## 9. Implementation plan

### Must-have (in dependency order)

| # | Unit | Files | Backend / DB / API | Frontend | Tests | Acceptance criteria |
|---|---|---|---|---|---|---|
| 1 | **Permissions and staff picker** | `authorization/catalog.py`, seed migration, new `api/staff_router.py` | 3 permissions, seeded to ADMIN and checked as "ADMIN or permission"; `GET /staff` | `usePermissions` path into `useCan` for these 3 | catalog, route auth table, picker excludes inactive users | A custom role with enum COMPLIANCE plus `compliance:assign` can call the assignment routes; plain COMPLIANCE gets 403; no new enum value |
| 2 | **RM assignment** | `exporter_profile_service.py`, `exporter_router.py`, `history_dimensions.py`, `history-row.md`, migration 0044 (index) | Assign route (self-claim when unassigned; ADMIN or `exporters:assign_rm` otherwise; OPERATIONS targets only; reason on change), `relationship_manager` dimension, list filter, text field read-only | picker on `CompanyPanel`, list views | see §10 RM | The RM is always an active OPERATIONS user, every change is in history with its reason, and OPERATIONS still sees masked identifiers |
| 3 | **Legacy owner backfill** | command module (same `--dry-run/--apply/--validate` shape as the existing data commands) | Exact, case-insensitive match of the free text to one active **OPERATIONS** user's `full_name`; others, including names matching ADMIN or COMPLIANCE users, are reported | — | match, ambiguous, none, non-OPERATIONS match, idempotent re-run | Dry run lists the unmatched rows; apply writes history with `source=backfill` |
| 4 | **Bulk reassign** | service and route | Ordered locks, `bulk_run_id`, reason, dry run | bulk action, inactive-RM view | from→to, subset, concurrent single change skipped | Former RM owns 0 of the moved companies; one history row per company |
| 5 | **Field-level conflict check** | `update_profile`, `UpdateExporterProfileRequest`, `exceptions.py` | `seen` map, 409 with who and when | conflict message and Reload | see §10 | Same-field stale save refused; a different-field save passes |
| 6 | **Review assignment** | entity, migration 0044 (2 columns plus CHECK), `background_check_service.py`, router | claim, assign, release, auto-claim, end on decision, reassess and reopen set the actor | reviewer line and actions in the panel | see §10 | No CLEAR, FLAGGED or ON_HOLD proposal without a named reviewer |
| 7 | **Checker eligibility and high risk** | `approve`, queue query | reviewer and RM exclusion, senior rule for `HIGH`/`CRITICAL` CLEARs, `eligible_checker_count` | disabled Approve with reason | see §10 | High-risk CLEAR approved only by a senior checker in one step; the RM and the reviewer can never approve |
| 8 | **Business time and worklists** | `domain/business_time.py`, `compliance_settings.py`, worklist and count routes | computed due and overdue; no scheduler | Compliance work page sections, nav badges, Home cards | unit tests across weekend, holiday and end of day; lists | Every list item shows waiting time and its due state; holders of `compliance:assign` see Overdue |
| 9 | **RM at the action** (depends on 2) | `start_review` path, `qualification_service.record_outcome` | in-pipeline start and human QUALIFIED need or set an RM; RXIL, import, existing and buyer-only paths exempt | prompts in the dialogs | the paths in §10 | No new in-pipeline check starts without an RM; buyer-only checks are never blocked |

The RM work (units 2–5 and 9) and the compliance work (units 6–8) can proceed in parallel once unit 1 is done. Units 2 and 6 share migration 0044: agree who owns it first, or split it into 0044 and 0045.

### Recommended later

- A persisted notification inbox (`staff_notification` written in the same transaction as the event: read/unread, a bell). Build it together with email, as one outbox serving both.
- Routing a buyer-only company's info requests to the seller's RM.
- Officer workload shown on the assign dialog.
- Dropping the legacy `relationship_manager` text column.
- A "reopen on identity change after CLEAR" rule.

### Enterprise features not justified now

- Teams and shared ownership.
- Push or capacity-based routing (Omni-Channel and Get Next Work style).
- Skills-based routing.
- A scheduler that reassigns automatically on SLA breach.
- A true three-step approval chain.
- A lead-directed named checker.
- Ownership-scoped visibility or reveal.
- ETags or record-level versioning.

---

## 10. Test strategy

Backend tests go in `tests/integration/` (with the real DB, which is the existing pattern) plus unit tests for the pure rules. Frontend tests go in Vitest beside each component. Gate: `pytest --crm` and Vitest at baseline.

**RM**
- **Eligibility:**
  - Only an active OPERATIONS user can be set as RM. ADMIN, COMPLIANCE, DEVELOPER and inactive targets get 422.
  - An ADMIN can assign an OPERATIONS user but cannot be the RM.
- **Self-claim:**
  - An OPERATIONS user may set themselves on an unassigned company.
  - Setting someone else without ADMIN or `exporters:assign_rm` gives 403.
  - A COMPLIANCE user cannot claim.
- **Change, clear and reason:**
  - Changing or clearing an existing RM as plain OPERATIONS gives 403.
  - ADMIN can change or clear.
  - An OPERATIONS user with `exporters:assign_rm` can change or clear.
  - A missing reason gives 422.
  - A stale `seen_user_id` gives 409.
- **Audit:** history rows carry the from and to ids and the reason.
- **Bulk reassign:**
  - It moves only the selected companies and refuses a non-OPERATIONS target.
  - A row changed concurrently is skipped.
  - The former RM's *My companies* is empty.
  - The dry run writes nothing.
- **Visibility and masking:**
  - `test_masking_sweep.py` is extended so that an OPERATIONS user who is the RM still receives masked PAN, GSTIN, IEC and CIN on every read, including history.
  - The company list and reads return the same rows whether or not the caller is the RM.

**RM at the action**
- Leads:
  - A Lead is created and imported without an RM.
  - Starting a check on an in-pipeline Lead or Prospect with no RM gives 409 `RELATIONSHIP_MANAGER_REQUIRED`, unless an RM is supplied.
- Supplying an RM on start:
  - An OPERATIONS starter may name themselves.
  - ADMIN or `exporters:assign_rm` may pick an OPERATIONS user.
  - A COMPLIANCE starter without the permission is refused.
- Recording QUALIFIED by a person needs or sets an RM.
- The RXIL intake and imports create Prospects without one, and they appear in *Unassigned Prospects*.
- A buyer-only company's check starts, runs and is decided with no RM, and its info request appears in *Unowned info requests*.
- No DB constraint refuses a null RM.

**Concurrency**
- Two users edit different fields: both succeed, with two history rows.
- The same field with an old `seen` gives 409 naming the first editor and the time.
- A masked viewer's `seen` is compared masked to masked.
- Omitting `seen` keeps today's behaviour.
- A gauge move between read and save does **not** trigger a conflict.
- Two sessions racing on the same field leave one success and one 409 (in `test_compliance_concurrency.py` style).
- No version column or ETag is introduced.
- Frontend: the 409 shows the message, Reload refetches, and the typed text is kept.

**Compliance**
- **Start and claim:**
  - The RM starts a check and it lands in Awaiting review.
  - Claim works, and a second claim gives 409.
  - A user who is somehow both COMPLIANCE and the company's RM (for example after a role change) cannot claim (`REVIEWER_IS_RM`).
- **Assignment by permission:**
  - A custom role with enum COMPLIANCE plus `compliance:assign` assigns and reassigns with a reason.
  - Plain COMPLIANCE gets 403.
  - ADMIN can assign without an explicit grant.
  - No code path checks for a lead enum value.
- **Release:**
  - Release returns the item to the queue.
  - Release with an open proposal gives 409.
- **Propose:**
  - Propose by a non-reviewer gives 409.
  - Propose on an unassigned check auto-claims.
  - The propose request has no checker field (a supplied one is refused by `extra="forbid"`).
  - Proposing ON_HOLD from IN_REVIEW is refused.
  - FLAGGED→ON_HOLD stays maker-checker.
- **Information request:** request-info, then the RM's return, sends the check back to My reviews, and the SLA pause is computed.
- **Separation of duties:**
  - Approver = proposer gives 403 (existing).
  - Approver = reviewer or RM gives 403.
  - The `awaiting=me` queue excludes all three.
- **High risk:**
  - A CLEAR with `HIGH` or `CRITICAL` approved without the senior permission gives 403.
  - With the permission, or as ADMIN, it succeeds in one step and the decision is final, with no further pending stage.
  - `LOW` and `MEDIUM` CLEARs and FLAGGED proposals need no senior.
- **After a decision:**
  - Reject keeps the gauge and the reviewer and increments `rejection_count`.
  - Withdraw by a holder of `compliance:assign` when the proposer is inactive.
  - A decision clears the reviewer and writes `…ended`.
  - The DB CHECK refuses a reviewer on a CLEAR company.
  - Decisions, proposals and assignment history are refused on UPDATE and DELETE.
  - Reassess and reopen set the actor as reviewer.
- **Races:**
  - A claim racing an assignment leaves one winner.
  - Approve racing a reassign is serialised by the lock.

**SLA**
- Unit tests for the business-time function in Asia/Kolkata:
  - Friday 17:00 plus 4 business hours.
  - A span across a configured holiday.
  - A start outside hours.
- Overdue and due-soon flags on each list.
- The review clock excludes MORE_INFO time, and the information-request clock runs.
- No scheduler job is registered.

**Notifications (computed)**
- Badge counts match the lists for each role and permission.
- DEVELOPER gets none.
- No list, badge or card payload contains an identifier or a decision reason (add this to the masking sweep).
- No notification table and no email is written.

**Edge cases**
- A high-risk CLEAR whose only senior holder is its reviewer gives `eligible_checker_count = 0`, and the item goes to Needs attention.
- A reviewer deactivated mid-review is flagged.
- A company whose check moves to FLAGGED while assigned has its reviewer cleared.

---

## 11. Agreed business decisions (7 October 2026)

| # | Decision | Agreed |
|---|---|---|
| 1 | Who can be RM | **OPERATIONS users only.** ADMIN assigns but is not a normal RM; COMPLIANCE is never an RM. No new RM role. `relationship_manager_user_id` is used. RM is optional at the Lead stage. Ownership is separate from authorisation |
| 2 | Changing an existing RM | No RM: an eligible (OPERATIONS) user may claim it for themselves. Existing RM: a change needs **ADMIN or `exporters:assign_rm`**, with a **reason**. Audited in the append-only history log. Ownership controls neither visibility nor identifier access. Bulk reassignment as recommended |
| 3 | Permissions | `exporters:assign_rm` held by ADMIN and sales or CRM lead custom roles. `compliance:assign` held by ADMIN and Compliance lead custom roles. `compliance:approve_high_risk` held by ADMIN and senior Compliance users, with **at least two holders**. Uses the existing custom-role and permission mechanism; no hard-coded lead role |
| 4 | High risk | A CLEAR with risk `HIGH` or `CRITICAL` (the existing `BackgroundCheckRisk` values) needs `compliance:approve_high_risk`. The senior checker is the second person; there is no third stage |
| 5 | Reviewer assignment | Shared queue: Awaiting review, then Assign to me, or assignment and reassignment by `compliance:assign`. Release allowed. The RM never chooses the reviewer. No automatic routing. Audited |
| 6 | Checker selection | Pooled. The checker is not the proposer or reviewer, the RM, or an unauthorised user. No lead-directed named checker in v1. The existing maker-checker service and DB enforcement remain the source of truth |
| 7 | RM by lifecycle stage | Not a DB invariant. Lead: optional. Prospect: expected for normal pipeline actions; existing and imported Prospects may temporarily have none. Prompt for or set an RM at accountability actions, including starting compliance on an in-pipeline company. Buyer-only: not required, and compliance is never blocked by its absence |
| 8 | Compliance lead | A capability (`compliance:assign`), not an enum role |
| 9 | SLA and notifications | The architecture is agreed: configurable values, business hours in Asia/Kolkata, configurable holidays, review, approval and information-request clocks, review paused during MORE_INFO, computed overdue and worklists, no scheduler. v1 notifications are computed worklists, badges and Home cards only, with no PAN, GSTIN or reason text. The inbox and email are deferred |
| 10 | On Hold | `IN_REVIEW → CLEAR \| FLAGGED`, then `FLAGGED → ON_HOLD`. Not a direct review outcome |
| 11 | Concurrency | Field-level `seen` check, 409 naming who and when, typed input kept, row locking and history unchanged. No version column and no ETag in v1 |

---

## 12. Final verdict

1. **Keep unchanged:**
   - One primary RM linked to a user.
   - Ownership as responsibility, never authorisation, with no extra access to masked identifiers.
   - Audited assignment, and bulk reassignment on exit.
   - The RM never picks the reviewer, and the maker never picks the checker.
   - Claim plus assignment.
   - In-app first, email later.
   - No third approver for every case.
   - Finalised decisions stay immutable.
2. **Change:**
   - On Hold is not a review outcome: FLAGGED→ON_HOLD is its own maker-checker step.
   - The "Compliance Lead" becomes a permission (`compliance:assign`), not a role.
   - High risk means a *senior checker* as the second person, not a third.
   - The SLA is business-hours aware, configurable and paused during information requests.
   - Conflict detection is field-level.
   - Checker exclusion widens to the reviewer and the RM.
   - The RM is required at the points where a person acts, not as a DB invariant.
   - RMs are OPERATIONS users only.
   - Changing an existing RM needs ADMIN or `exporters:assign_rm`.
3. **Remove:** the lead-assigned checker from v1, and any idea of returning a leaving RM's companies to Admin.
4. **Defer:**
   - A persisted notification inbox and email notifications.
   - Teams and shared ownership.
   - Workload, capacity and skills-based routing.
   - Automatic SLA reassignment.
   - A true three-step approval.
   - A lead-directed named checker.
   - ETag or record-level versioning.
   - Automatic routing of buyer-only companies to the seller's RM.
5. **Adopt:**
   - A single owner plus mass transfer (Salesforce, Dynamics).
   - Pick, release and assign queue semantics (Dynamics).
   - A pooled checker with server-enforced maker ≠ checker (Sumsub, Didit).
   - Approvers that exclude the requester (ServiceNow).
   - Criteria-gated approval (Salesforce).
   - Schedule-aware SLA milestones (ServiceNow, Pega), computed rather than timed.
   - A conditional update on the seen value (the Dataverse concurrency principle, applied per field).
6. **Not yet:** Omni-Channel style push routing, capacity models, teams, record-level ETags, ownership-scoped visibility, scheduled automatic reassignment.
7. **Flow:** §5.
8. **Minimum:** units 1–9 of §9:
   - One migration (two columns, a CHECK and an index).
   - Two history dimensions.
   - Three permissions.
   - About ten routes.
   - Changes to `CompanyPanel`, the lists, the Approvals page and the background-check panel.
9. **Biggest risks:**
   - (a) The tighter rule for changing an existing RM surprising sales users.
   - (b) Eligibility rules leaving **zero** eligible checkers in a small team. Mitigated by `eligible_checker_count`, the Needs attention view and at least two senior holders.
   - (c) The legacy owner backfill mis-matching names. Mitigated by exact matching to OPERATIONS users only, with a dry run.
   - (d) Expectations about "notifications" if badges are judged insufficient.
   - (e) Too few users holding `compliance:approve_high_risk`.
10. **Decision status:**
    - **Decided for implementation:** everything in §11.
    - **Configurable later:** SLA values, business hours and the holiday calendar. Unit 8 is built with defaults.
    - **Explicitly deferred:** item 4 above.

    Nothing in §11 blocks any unit.

**Confidence:** high (≈85%) on the codebase findings and the data and API shape, because each claim is traced to a file. With the business decisions now settled, the design itself is also high confidence. Medium (≈65%) on the final SLA values and on whether badges will satisfy users, which depend on how the compliance team works.

---

### Sources

- Salesforce Mass Transfer and account teams: [Data Loader — keep account teams](https://developer.salesforce.com/docs/atlas.en-us.264.0.dataLoader.meta/dataLoader/loader_keep_account_teams_config.htm), [Mass transfer overview](https://automationchampion.com/2021/06/17/mass-transfer-records-using-salesforce1-app/)
- Salesforce approval processes (record lock, recall, steps): [ApprovalProcess metadata](https://developer.salesforce.com/docs/atlas.en-us.api_meta.meta/api_meta/meta_approvalprocess.htm)
- Salesforce collision detection: [Visualforce — updating records issues](https://developer.salesforce.com/docs/atlas.en-us.pages.meta/pages/vf_dev_best_practices_known_issues_updating.htm)
- Salesforce Omni-Channel routing: [Trailhead — Enhanced Omni-Channel](https://trailhead.salesforce.com/content/learn/modules/enhanced-omni-channel/improve-work-distribution-with-enhanced-omni-channel)
- Dynamics 365 queues (pick, release, assign, Worked By): [Work with queues](https://learn.microsoft.com/en-us/dynamics365/customer-service/use/work-with-queues), [Releasing and assigning queue items](https://carldesouza.com/releasing-queue-item-behavior-in-dynamics-365/)
- Dynamics 365 reassign records: [Update record owner](https://learn.microsoft.com/mt-mt/power-platform/admin/update-record-owner)
- Dataverse optimistic concurrency: [Reduce potential data loss using optimistic concurrency](https://technet.microsoft.com/en-us/library/dn932125), [Conditional operations (Web API)](https://learn.microsoft.com/lv-lv/powerapps/developer/data-platform/webapi/perform-conditional-operations-using-web-api)
- HubSpot removing users and reassigning: [Remove HubSpot users](https://knowledge.hubspot.com/user-management/remove-hubspot-users)
- ServiceNow SLA schedules: [SLA timeline and business schedule](https://www.servicenow.com/docs/r/MlbQAgTiiiMOLOw9T36wJg/fEDE~4ajQGT8kp4xORlOSQ); requester cannot approve: [community](https://www.servicenow.com/community/itsm-forum/change-prevent-requester-from-approving/td-p/606308)
- Pega Get Next Work and SLA goal and deadline: [Pega Academy](https://academy.pega.com/node/89436)
- Sumsub 4-eyes review: [docs.sumsub.com](https://docs.sumsub.com/docs/4-eyes-review)
- Didit case management and four-eyes: [Case management](https://docs.didit.me/console/case-management), [Four-eyes](https://docs.didit.me/console/case-management/four-eyes.md)

---

## Decision Status

The core business decisions are **decided for implementation** (§11):
- RM ownership and eligibility.
- RM claim and change rules.
- Compliance reviewer assignment.
- Maker-checker separation.
- High-risk approval.
- Enforcing the RM requirement at each lifecycle stage.
- SLA architecture.
- v1 notifications.
- Concurrency.

What remains is configuration or deliberately deferred work. None of it blocks units 1–9.

**Configurable (values only, the code is built with defaults):**
- SLA durations for review, approval and information requests. The starting defaults are 1 business day, 4 business hours and 1 business day.
- Business hours within Asia/Kolkata and the holiday calendar.
- The "due soon" threshold (75%) and the badge refresh interval (60 seconds).
- Which named users receive the three permissions. At least two must hold `compliance:approve_high_risk`.

**Explicitly deferred:**
- A persisted notification inbox, and email notifications.
- Teams and shared ownership.
- Workload, capacity and skills-based routing.
- Automatic SLA reassignment.
- A true three-step approval.
- A lead-directed named checker.
- ETag or record-level versioning.
- Automatic routing of buyer-only companies' information requests to the seller's RM.
- Dropping the legacy `relationship_manager` text column.
- A rule that reopens a CLEAR check when the company's identity changes.
