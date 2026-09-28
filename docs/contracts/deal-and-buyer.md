# Contract — the deal and its buyer

**Owner:** Developer 3B · **Tables:** `onboarding.deal`, `onboarding.deal_buyer` · **Migration:** `onboarding_0018_deal_buyer`

**Used by:** Developer 2 (company lists and panels), Developer 4 (buyer checks attach
to the deal's buyer; the handover guard reads the company's background check),
Developer 3A (the `READY_NOW` prompt that opens a deal — seam S2).

**State.** All of it is built. §6's handover works end to end **except that its guard
can never pass** in this build: it needs a column Developer 4 has not shipped, so every
handover is refused and says why. §6 has the detail.

Architecture §3.3 ("The deal"), §3.5 and §3.6 are the source.

---

## 1. Values

```python
class DealStage(str, enum.Enum):
    OPEN = "OPEN"
    GATHERING_PAPERWORK = "GATHERING_PAPERWORK"
    HANDED_OVER = "HANDED_OVER"
    WITHDRAWN = "WITHDRAWN"
```

In `domain/entities/deal_enums.py` — **not** in `exporter_enums.py` (Developer 2's
company values) and **not** in `engagement_enums.py` (Developer 3A's). Database enum:
`onboarding.deal_stage_enum`.

### 1.1 Which moves exist

| From | To | Needs |
|---|---|---|
| `OPEN` | `GATHERING_PAPERWORK` | — |
| `OPEN` | `WITHDRAWN` | reason |
| `GATHERING_PAPERWORK` | `HANDED_OVER` | the §6 guard, and a buyer |
| `GATHERING_PAPERWORK` | `WITHDRAWN` | reason |

`HANDED_OVER` and `WITHDRAWN` are terminal: nothing leaves them. A deal that was
withdrawn in error is a **new deal**, not a reopened one — the same rule the journey
uses, and for the same reason: a record of what was decided must not be editable into
a different decision.

**A terminal deal is closed to edits, not only to stage moves.** Its buyer cannot be
changed and no document can be added to it (`storage-and-documents.md` §6.2), both
refused with `DEAL_TERMINAL`. A handed-over deal's buyer and paperwork are what the
lending team was given; a withdrawn deal's are history.

Unlike the conversation gauge, **any-value-to-any-value is not allowed here.** A stage
is a claim about what has happened to a deal, not a judgement, so an illegal move is
refused with `DEAL_TRANSITION_NOT_ALLOWED` (422) and leaves the row untouched.

---

## 2. A company has many deals

`deal.company_id` is a real foreign key to `exporter_profile.customer_id`
(`ON DELETE RESTRICT`: a company with deals is not deletable). No uniqueness — a
company has any number of deals over time, open ones included. Architecture §3.3.

**Only a `PROSPECT` or a `CUSTOMER` may have a deal opened.** A deal follows a sales
conversation, which applies from `PROSPECT` onward (assumption A4), and opening one
sets the conversation to `READY_NOW` (§5) — so `DealService.open_deal` refuses a
`LEAD` with 409 `DEAL_COMPANY_NOT_READY` before anything is written. (Implemented 29
September 2026 on the audit's recommendation; the programme lead to confirm. Seam
S1 checks no journey by design, so the check belongs here, where the deal is opened.)

Deleting a deal is not an operation. `WITHDRAWN` is how a deal ends.

---

## 3. The buyer

Its own table, `onboarding.deal_buyer`, one row per deal (`deal_id` unique), not
columns on `deal`.

**Why a table rather than columns.** Developer 4 attaches buyer checks to *the buyer*
(plan §8.2, decision 9): a verification result needs something with an id to point at,
and `entity_reference` pointing at a deal would make "a check about the buyer" and "a
check about the deal" the same thing. A separate row gives the buyer its own identity
without pretending it is a company.

| Column | Type | Null | Notes |
|---|---|---|---|
| `deal_id` | uuid | no | FK → `deal.id`, `ON DELETE CASCADE`, **unique** |
| `name` | varchar(500) | no | |
| `country` | char(2) | no | ISO-3166-1 alpha-2, uppercase |
| `registration_number` | varchar(100) | yes | Whatever the buyer's jurisdiction issues |
| `tax_id` | varchar(100) | yes | |
| `contact_email` | varchar(255) | yes | |
| `contact_phone` | varchar(50) | yes | |

**One buyer per deal.** A deal with two buyers is two deals: the buyer is who the
exporter is selling to, and financing one shipment for two buyers is not a thing the
prototype models.

**The buyer's identifiers and contact details are masked** for OPERATIONS and
DEVELOPER, like an exporter's PAN and GSTIN (`api/schemas/masking.py`, decision
12): `registration_number`, `tax_id`, `contact_email` and `contact_phone` reach them
masked on every deal route, a masked value is refused on `PUT .../buyer`, and a masked
field left out of that request keeps its stored value. COMPLIANCE and ADMIN see them
in full. (Changed 28 September 2026 in the frontend refresh, at the lead's call; it
reverses this contract's first design, which left the two identifiers visible.)

**The buyer is optional at `OPEN` and required to leave `GATHERING_PAPERWORK`.** A
deal often starts before the buyer is known; a handover without a buyer is not a
handover, since the payload carries buyer details (§6).

### 3.1 A buyer's problems stay on the buyer

Architecture §3.5 and decision 9. A buyer failing a check is recorded against the
buyer; a deal falling through is `WITHDRAWN` with a reason on the deal. **Neither
touches the company's record.** There is no "has a bad deal" or "buyer risk" field on
`exporter_profile`, and adding one would be a contract change, not a detail.

The deal page shows the buyer's checks to staff (`BuyerChecks`), read and recorded by
`deal_buyer.id`. Once the deal is `HANDED_OVER` or `WITHDRAWN`, no new check may be
recorded (D17, 409 `DEAL_CLOSED`), and the verifications list stops offering
`can_record_result` for that buyer; existing checks stay readable and reviewable.

---

## 4. Who may do what

Per architecture §3.7: OPERATIONS, COMPLIANCE and ADMIN open deals, move stages, and
edit the buyer. DEVELOPER reads. API_USER reaches nothing.

### 4.1 The server serves the allowed moves

`GET /onboarding/deals/{deal_id}` includes `allowed_stage_moves`, the moves **this
user** may make from the deal's current stage — the rules as data, so the screen asks
rather than keeping a copy (§7.5). Same shape as
`ExporterProfileService.allowed_marker_moves` and `ConversationService.allowed_moves`,
deliberately.

A move that is legal but blocked by the §6 guard is **not** in the list, and the
response says why through `handover_blocked_reason`, so the screen can explain
instead of offering a button that 409s.

`GET /onboarding/exporters/{company_id}/deals` carries `can_open_deal`: whether this
caller may open a deal on the company now — a staff role and a `PROSPECT` or
`CUSTOMER` company (§2). The screen offers "Open a deal" from it.

`allowed_stage_moves` and `handover_blocked_reason` are served only to a role that may
move a deal (OPERATIONS, COMPLIANCE, ADMIN). DEVELOPER is served no moves and no
reason: it could act on neither, and the reason names the company's background check,
which decision D8 keeps from DEVELOPER.

---

## 5. Seam S1 — opening a deal sets `READY_NOW`

Architecture §3.3: "opening a deal also sets this."

`DealService.open_deal` calls Developer 3A's
`ConversationService.mark_ready_now_for_opened_deal(company_id, deal_id=..., actor_id=...)`
in the same session and transaction, after the deal row exists (so `deal_id` is real)
and before the commit. Engagement contract §6 guarantees it is idempotent, checks no
journey stage and no role, and flushes without committing.

**This service never assigns `exporter_profile.conversation`** and never imports
Developer 3A's enum to compare against it (`company-record.md` §2.4 forbids writing
another developer's gauge field, "including just to keep it in step").

If 3A's method were somehow absent, `open_deal` ships without the call and the call
arrives as its own commit — never a stub of their service, and never the column
written directly.

---

## 6. Handover

`GATHERING_PAPERWORK → HANDED_OVER` requires, per assumption A5:

1. the company's journey is `CUSTOMER`, **and**
2. the company's background check is `CLEAR`.

Both are real: a company becomes a `CUSTOMER` when it is a `PROSPECT` with a `CLEAR`
check (`company-record.md` §3.2), and the check is read through Developer 4A's
published helper (`background-check.md` §10) — this service never creates or writes
that column (`company-record.md` §2.4). A company never checked reads `NOT_STARTED`,
and "not `CLEAR`" is never treated as "clear". While either condition is unmet,
`allowed_stage_moves` omits the move and `handover_blocked_reason` names **every** unmet
condition, journey first, joined with `"; "` — for example `the company is PROSPECT, not
CUSTOMER; the background check is FLAGGED, not CLEAR`. The guard share-locks the company row on the move (D10),
so a concurrent flag or reopen waits for the handover to commit.

On handover: write the history row first, then announce
`OnboardingEventPublisher.deal_handed_over(...)` after the commit — history is the
source of truth and the announcement is best effort (architecture §3.6).
`document_ids` is the snapshot of every document on the deal when it was handed
over, whatever its scan status (open item: whether to refuse a handover while a deal
document is not `AVAILABLE`).

---

## 7. History

Every stage change writes one row through Developer 1's `HistoryService.record(...)`,
in the same transaction as the change (architecture §3.8).

| Field | Value |
|---|---|
| `dimension` | `"deal"` — fixed by `history-row.md` §2 |
| `company_id` | always set, even though the change is about a deal |
| `deal_id` | always set for a `deal` row (`history-row.md` §2.1) |
| `event_type` | `deal_initial` at creation, `deal_transition` for a move |
| `source` | `deal_service.open_deal`, `deal_service.transition_stage`, … |
| `actor_id` | from the login session, never the request body (§7.5) |
| `reason` | required for `WITHDRAWN` (assumption A7) |

Buyer edits write `dimension="deal"` with `event_type="deal_buyer_changed"` and the
changed field names in `details` — a buyer's details are part of a deal's story, and
the alternative (a `buyer` dimension) would need a change to `history-row.md` §2,
which is Developer 1's.

---

## 8. Error codes

| Code | Status | When |
|---|---|---|
| `DEAL_NOT_FOUND` | 404 | No such deal. |
| `DEAL_TRANSITION_NOT_ALLOWED` | 422 | The move is not in §1.1 for the current stage. |
| `DEAL_TERMINAL` | 409 | A move out of `HANDED_OVER` or `WITHDRAWN`. |
| `DEAL_WITHDRAWAL_REASON_REQUIRED` | 422 | `WITHDRAWN` without a reason (A7). |
| `DEAL_BUYER_REQUIRED` | 422 | Leaving `GATHERING_PAPERWORK` with no buyer. |
| `DEAL_HANDOVER_BLOCKED` | 409 | The §6 guard is unmet: the company is not a `CUSTOMER`, or its check is not `CLEAR`. |
| `DEAL_COMPANY_NOT_FOUND` | 404 | Opening a deal for a company that does not exist. |
| `DEAL_COMPANY_NOT_READY` | 409 | Opening a deal for a company that is still a `LEAD` (§2). |

---

## 9. What this contract does not cover

- **Transactions and how they perform** — the lending side's, outside the CRM
  entirely (architecture §3.5). Not modelled here, not now, not later.
- **Underwriting decisions.** The CRM hands a deal over; whether to fund it is not
  its business.
- **Documents.** `storage-and-documents.md`, same owner.
