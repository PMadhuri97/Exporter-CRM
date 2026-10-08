# Contract — verification results and the screening checklist

> **Amendment, 9 October 2026 — permissions, and a read-only administrator.** Every CRM
> route now checks a permission (`require_permission`), not a role list; the grants each
> built-in role starts with are in `platform/authorization/catalog.py`
> (`BUILTIN_ROLE_PERMISSIONS`), seeded by `auth_0007_business_permissions`. The
> administrator (ADMIN) manages users, roles and settings and **reads** companies, deals,
> documents and compliance work, but creates, edits, decides, approves and assigns nothing,
> and sees tax identifiers masked. Wherever this document says "COMPLIANCE or ADMIN" (or
> lists ADMIN among those who write, decide, approve, assign, reveal or take in an RXIL
> package), read **COMPLIANCE** — or the holder of the named permission. The senior
> permissions (`exporters:assign_rm`, `compliance:assign`, `compliance:approve_high_risk`)
> are no longer "ADMIN, or the permission": they are held through the seeded **Sales lead**
> and **Compliance lead** roles. RXIL intake needs `exporters:partner_intake` (COMPLIANCE).

**Owner:** Developer 1 — the compliance engine (`docs/developer-allocation.md` §2.1, from
1 October 2026); built by Developer 4B (L4-02, L4-04 review half, L4-07, L4-09, L4-11) ·
**Migrations:** `onboarding_0021_verif_review`; since then `onboarding_0023_compliance_core`
(`subject_company_id`), `onboarding_0024_screen_evidence` (screening evidence),
`onboarding_0025_check_cycle` (`cycle_id`, the seven-item checklist) · **Status:** built
28 September 2026; this file replaces Developer 4B's task document (`dev4/4b-task.md`, removed
2 October 2026 — git history keeps it).

What a verification result is allowed to become once recorded, how a person reviews it, what
evidence a manual result needs, the screening checklist and its history, checks on a deal's
buyer, and the routes that serve them. The background check that *reads* these inputs, and the
seam it reads them through, are `background-check.md` (§12 for the seam).

**Source of truth.** The design PDF (retired on 4 October 2026 as outdated; recover it with `git show 451ef97:docs/Exporter-CRM-Architecture-and-Plan.pdf`) §3.3, §3.5, §7.6, decisions
5, 9; the lead's decisions recorded in §10. Where this contract and the architecture disagree,
the architecture wins.

---

## 1. Reviews are records, not edits

A verification result is reviewed by **adding** a `verification_review` row; nothing is ever
edited (0021).

| Column | Rule |
|---|---|
| `verification_result_id` | FK → `verification_result.id`, `ON DELETE RESTRICT` |
| `review_status` | `ACCEPTED`, `REJECTED` or `ESCALATED` (`verification_review_status_enum`) |
| `reviewed_by` | the caller, from the session — never a body field |
| `reviewed_at` | the database clock |
| `note` | the reviewer's reason; **required on a superseding review** (`ck_verification_review_supersede_note`) |
| `supersedes_review_id` | the review this one replaces; `NULL` only on the first |

The database keeps one chain per result: `uq_verification_review_supersedes` (a review is
superseded at most once), `uq_verification_review_first` (partial — one first review per
result), `fk_verification_review_supersedes` (composite, so a review supersedes only a review
of the **same** result), `ck_verification_review_not_self`, and
`trg_verification_review_append_only` (`prevent_mutation()`).

- **The latest review is the chain head** — the one nothing supersedes. The seam serves it as
  `latest_review_id` / `latest_review_status` / `latest_reviewed_at` (`background-check.md`
  §12), and Developer 1's `CLEAR` rule reads it (D2, `background-check.md` §14.1).
- `POST /verifications/{id}/review` takes `review_status`, `note`, `supersedes_review_id`.
  A first review omits `supersedes_review_id`; a later one must name the **current** head,
  else **409 `VERIFICATION_REVIEW_STALE`** — a compare-and-set, never a silent overwrite.
  A `PENDING` result is not reviewable: **422 `VERIFICATION_RESULT_NOT_REVIEWABLE`**.
- **Legacy verdicts.** 0021 copied every legacy `reviewed_by` / `review_status` into the table
  as that result's first review (its `reviewed_at` is the result's `updated_at`, the closest
  stored fact, and its note says so). The legacy columns and
  `trg_verification_result_field_immutability` are kept; nothing writes them after 0021. A
  result whose legacy columns are set but which has no review row (only possible by writing
  them outside the service after 0021) is refused with **409
  `VERIFICATION_LEGACY_REVIEW_UNCHAINED`** rather than given a "first" review that would
  overrule the legacy verdict with no link and no reason.
- **History:** each review writes a `verification` row (`history-row.md` §2): `from_value` the
  previous review status or `None`, `to_value` the new one, `reason` the note, `details` with
  `verification_result_id`, `review_id`, `supersedes_review_id`, `verification_type`. Company:
  the subject company (a buyer company's result goes to that company, with the deal as context);
  for a legacy `BUYER` result, the deal's company with `deal_id` set. Subjects with no company
  link write none (D15).

## 2. A reviewed result never changes

`trg_verification_result_outcome_freeze` (`prevent_reviewed_verification_outcome_change()`):
once a result has any review — a `verification_review` row or a legacy `review_status` —
`UPDATE` of `status`, `risk_level`, `normalized_result` or `valid_until` is refused.
`get_verification_status` asks the provider first, then re-reads the row `FOR UPDATE` and, if
it has been reviewed, **logs and ignores** the provider's new answer (L4-02). Reviews take the
same row lock, which closes the race the trigger alone cannot (a raw `UPDATE` racing a raw
review `INSERT`). Polling has no production caller; no scheduler exists.

## 3. Evidence on a manual result

- `evidence_note` and `evidence_refs` (an array of `{type, ref}`, the qualification contract's
  shape; `ck_verification_result_evidence_refs_array`) on `verification_result`, frozen once set
  by `trg_verification_result_input_immutability`.
- `type` is `document` (a `crm_document.id`) or `url`. A **`url` must be an absolute `http` or
  `https` link with a host** (422) — it is shown to other staff as a link, and a `javascript:`
  link would run in the reader's session. The UI applies the same rule and shows any stored
  non-web `url` as text.
- A **`document` must belong to the subject**: the company's own documents for a company
  subject; for a legacy `BUYER`, the buyer's deal's documents or that deal's company's. And it
  must be **`AVAILABLE`** (422 otherwise) — a document still being scanned can never be opened,
  and evidence is frozen once written. Ownership is checked first, so a foreign document's scan
  state is never disclosed. (D4, 4B side.)
- **D16:** a manual `PASSED` needs a non-blank note **or** at least one reference; `FAILED` and
  `REVIEW` need none. A manual `PENDING` is refused — nothing will ever poll it. The rule lives
  in one place: `domain/verification_evidence.check_manual_outcome`.
- A company subject must exist (404/422) — no ghost subjects.

## 4. Provenance

- Whatever the adapter reports is stored verbatim, never rewritten.
- **D7:** `POST /verifications` accepts `provider = "manual"` only (`ManualRouteProvider`);
  `"rxil"` is refused there (422) and reserved for RXIL's own intake (D12, blocked). The RXIL
  stub stores `rxil_stub` and refuses `PENDING`.
- No Middesk, Trulioo or Sumsub: `VerificationProvider` is not widened (providers stay manual
  this quarter, BQ-8; plan P7-1..3 deferred).

## 5. The screening checklist

- **One catalogue, on the server**, served with the list response (key, label, section, in
  order); the screen never hand-copies it. **Seven items since 1 October 2026**
  (`rules_version`, plan P2-4a): `website-reviewed` is retired — kept and readable, so an
  eight-item decision still reads, but refused on write (`background-check.md` §16).
- Status is `NEEDS_REVIEW`, `PASSED`, `FAILED` or `EXEMPT`, in the API **and** the database
  (`ck_screening_review_item_status`). An unknown key is 422; an unknown company 404.
- Append-only (`trg_screening_review_item_append_only`); the latest row per item is
  `created_at DESC, id DESC`, and the seam reads it within the current check cycle
  (`background-check.md` §12.2).
  Since 0024 a decision may carry `evidence_refs`.
- `GET /exporters/{id}/screening-review/{item_key}/history` — newest first, paged; the table
  **is** the history.
- **D9:** each decision is also written to the shared history log under the `screening`
  dimension (`screening_initial` / `screening_transition`; `history-row.md` §2).
- Responses serve **capabilities** (may this caller record a decision), so the screen keeps no
  role list.
- Writers take `FOR SHARE` on the company row before inserting, so a background-check move
  under `FOR UPDATE` reads a stable set (`background-check.md` §12.2).
- Screening is not a gauge and not qualification.

## 6. Checks on a deal's buyer

- **Legacy buyers** (a `deal_buyer` row, decision 9): a check with `entity_type = BUYER` names
  an existing `deal_buyer.id` — never the company or deal id. At record time the buyer's
  identity (name, country, registration number, tax id) is copied into `subject_snapshot`,
  because the deal's buyer can be edited in place under the same id; tax id and registration
  number in the snapshot are masked for OPERATIONS and DEVELOPER. Read through the seam's
  `buyer_checks(deal_buyer_id)` (legacy) and `GET /verifications?entity_type=BUYER&entity_reference=…`.
- **D17:** a new check on the buyer of a `HANDED_OVER` or `WITHDRAWN` deal is refused, **409
  `DEAL_CLOSED`**; existing checks stay readable and reviewable.
- A failed buyer check never touches the seller company or its background check.
- **Buyer companies** (plan P4-4/P4-5): a deal that names `buyer_company_id` has its buyer's
  checks recorded on that company like any company's (`subject_company_id`), read through
  `company_inputs`. Developer 2's buyer migration (P4-6) maps legacy `BUYER` results onto their
  new companies by setting `subject_company_id` once. `BuyerChecks.tsx` stays for legacy buyers
  until P4-10 (`remaining-work.md`, R-26).

## 7. Routes

| Route | Read / write roles | Notes |
|---|---|---|
| `POST /verifications` | COMPLIANCE, ADMIN | §3, §4; subject validation |
| `GET /verifications`, `GET /verifications/{id}` | OPERATIONS, COMPLIANCE, ADMIN | review chain served; `raw_result` never served |
| `POST /verifications/{id}/review` | COMPLIANCE, ADMIN | §1 |
| `GET /exporters/{id}/screening-review` (+ `/{item_key}/history`) | OPERATIONS, COMPLIANCE, ADMIN | catalogue, capabilities |
| `PUT /exporters/{id}/screening-review/{item_key}` | COMPLIANCE, ADMIN | §5 |
| `GET /exporters/{id}/bank-activity` | OPERATIONS, COMPLIANCE, ADMIN | states that **no provider feed is connected** — no fake findings |

- **D8:** DEVELOPER is refused on all of them, reads included; `normalized_result` is not
  masked for the staff roles that may read it. The history routes serve DEVELOPER no
  `verification` or `screening` rows (`history-row.md` §2, "Who reads what").
- Actors always come from the session; no caller-chosen actor, reviewer or source field.
- Every route has rows in both route-authorisation tables.

## 8. Placeholders are labelled, never invented

The dev-only placeholder generator is gone. Existing placeholder rows
(`normalized_result.stub = true`, no provider reference) are flagged, not deleted: the seam
reports `is_placeholder = true` and the screen labels them. Under D2 a placeholder blocks
`CLEAR` within its cycle; since check cycles, a company holding one starts a new cycle and the
placeholder stays behind (no D2 amendment: confirmed 2 October, `background-check.md` §14.2). No route creates a result nothing can resolve.

## 9. The screen

`VerificationSection` (props `{ customerId }`, rendered by the background-check panel) holds the
manual result form (evidence picked from the company's documents; `PASSED` without evidence is
refused on both sides), the result list with provider and placeholder labels and the review
chain, the superseding-review dialog, the screening checklist driven by the **served
catalogue** with per-item history, and the honest bank panel. Every control is gated on the
server's `capabilities`, never on a role comparison. A write (a result, a review, a screening
decision) refreshes the background-check query and the history lists, since both read what it
changed.

## 10. What not to build

No third verification framework (extend `verification_result`, its registry and adapters); no
new document system (evidence names `crm_document` ids); no fake provider results or bank
findings; no placeholder generator; no speculative RXIL package parsing (D12); no second backend
copy of the screening keys and no role lists in the frontend.

## 11. Decisions

All decided by the programme lead on 28 September 2026 unless stated. Shared numbering with
`background-check.md` §14, which holds D1–D6, D8, D10–D14 for the background check.

| # | Decision | Where |
|---|---|---|
| D2 | "Pending" — `PENDING`, `REVIEW` and placeholders block `CLEAR`, except a `REVIEW` result whose latest review is `ACCEPTED` or `REJECTED`. This side must keep `latest_review_status` = the chain head's status | `background-check.md` §14.1; §1 |
| D4 (4B side) | Which documents may be evidence: the subject's own (§3), `AVAILABLE` only. **Implemented; confirmed by the lead on 2 October 2026** (`background-check.md` §14.2) | `verification_service._check_evidence_documents` |
| D7 | Manual route is `manual` only; `rxil` refused there | `api/schemas/verification.py` |
| D8 | DEVELOPER refused; `normalized_result` not masked | routers; `history_router.py` |
| D9 | Screening decisions also go to the shared history log (`screening` dimension) | `screening_review_service.upsert_review_item` |
| D12 | RXIL's package and results contract — **blocked** (RXIL); blocks RXIL results intake (former task 4B-8) | `remaining-work.md` §5 (P7-6) |
| D15 | Checks on DIRECTOR / INVOICE / VESSEL / SHIPMENT write no history row (skipped and logged) | `verification_service._record_history` |
| D16 | Manual `PASSED` needs a note or a reference; `FAILED` / `REVIEW` need none | `domain/verification_evidence.py` |
| D17 | No new buyer check on a `HANDED_OVER` / `WITHDRAWN` deal (409 `DEAL_CLOSED`) | `verification_service._resolve_subject` |

## 12. Database tests

Every constraint and trigger above has a direct-SQL violation test that bypasses the ORM
(`migration-register.md` §2): `test_verification_review_schema.py`, `test_verification_reviews.py`,
`test_polling_safety.py`, `test_evidence_and_subjects.py`,
`test_screening_integrity.py`, `test_buyer_checks.py`,
`test_placeholders_provenance.py`; the pure rules in
`unit/test_verification_integrity_rules.py`.
