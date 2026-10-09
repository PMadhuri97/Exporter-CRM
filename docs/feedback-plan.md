# Prototype feedback plan

Business leads reviewed the prototype and left 22 comments in `crm_prototype_sam.xlsx`
(one sheet, comments beside 13 screenshots). This plan turns those comments, plus the
problems found while checking them against the code, into work the team can pick up.

- **Written:** 8 October 2026, against `feature/rm-compliance-allocation` @ `dd34ea3`.
- **Decisions:** all answered by the product owner on 8 October 2026 (section 2).
- **Item IDs** (F1, X1, W1.3 …) exist only for this plan and its discussion. Do not put
  them in file names, code, comments, tests, migration names or the UI; describe the
  behaviour instead.

---

## 1. How to read this plan

| Section | What it gives you |
|---|---|
| 2. Decisions | Every choice made, with the reason and any risk accepted |
| 3. What already exists | Which comments are already partly or fully built, so nobody rebuilds them |
| 4. Cross-cutting rules | Patterns every item must follow (permissions, settings, audit, migrations) |
| 5–8. Waves 1–4 | The work, in order: current state, changes, acceptance criteria, tests, size |
| 9. Reply to the leads | A short answer per comment, ready to send back |
| 10. Deferred | What was deliberately left for later |
| 11. Definition of done | Gates every item must pass |

**Sizes:** S = up to 1 day · M = 2–4 days · L = 1–2 weeks · XL = more than 2 weeks
(one developer, including tests).

---

## 2. Decisions

| # | Topic | Decision | Reason / risk accepted |
|---|---|---|---|
| D1 | Admin's business access | **Read-only.** Admin manages users, roles and settings and can view companies and deals, but cannot create, edit, import, decide or approve anything. | Separates duties while keeping Admin able to help users. Admin also loses compliance decisions and approvals. |
| D2 | Someone who needs both admin and business work | **A separate second account** (e.g. `sam.admin` and `sam`). No multi-role support. | Every action shows which role was used. Needs no change to the one-role-per-user model. |
| D3 | Approval for user creation and role changes | **None.** Creating users, changing roles and editing role permissions stay as they are today: one admin, applied immediately, no second admin. The existing guards stay (no changing your own role, no deactivating yourself, the last role manager is protected). | The lead's comment was a question, not a requirement. Revised 8 Oct 2026; this replaces the earlier "approve access grants" decision. |
| D4 | Record of user and role changes | **Audit trail only.** Every user and role change is written to the audit trail (today it only reaches application logs). The process itself is unchanged. | Gives a "who changed whose access" answer without adding an approval step. Small and separate (W2.2); can be dropped without affecting anything else. |
| D5 | Document download | **Compliance only** (new permission, enforced). Everyone else previews on screen. | Compliance sometimes has to send KYC packs to auditors. RMs are the largest group, so they carry the most leak risk. |
| D6 | Word/Excel preview | **Convert to PDF on upload** for preview. The original is kept for users with download rights. | Everyone can read every file without a download. |
| D7 | Sanctions, first release | **Structured manual recording:** a screening run, the lists checked with their dates, and each hit with a disposition. Built so a provider can fill the same records later. | Answers "multiple sanctions" without waiting on a vendor contract. |
| D8 | Which sanctions lists | **Minimal and configurable.** Admin manages the list in Settings, seeded with **UN Security Council** and **India MHA/UAPA**. OFAC, EU and UK HMT can be added later without code. | These two are the legal baseline for an Indian entity. |
| D9 | Deciding a true sanctions match | **Configurable.** Default: **a second officer approves** (like a Clear). Other settings: single officer, or a head-of-compliance permission. | Keeps four-eyes on the highest-impact decision and leaves room to tighten or relax it. |
| D10 | Exempt on checks | **Left as is.** No change to behaviour or wording. Exempt remains a checklist-item answer only. The explanation goes back to the lead (section 9). | The owner chose not to change it now. |
| D11 | Where "at least one primary contact" bites | **Deal handover is blocked** without an active primary contact. A warning appears on the record and in lists. Becoming Customer is not blocked. | Fits the existing handover rule list. Companies do not silently get stuck as Prospects. |
| D12 | Contact date and status | **Status** (Active / Inactive / Left company, with when and why) **plus a "last verified" date** and a re-verify reminder. | Gives a usable contact history and keeps contact data fresh. |
| D13 | Who owns the customer master | **The CRM, for now.** Structured fields and stable IDs so an ERP can pull them later. | Unblocks the leads now. ERP sync is deferred (section 10). |
| D14 | Collector | **An internal "Collections owner"** per company, assigned like the RM. | Matches the ERP meaning of "collector". Reuses the RM assignment pattern. |
| D15 | Parent / child | **Group view and roll-up**, plus suggestions from shared directors or UBOs. No group-level limits. | Gives the group picture without credit-limit work, which needs deal values first. |
| D16 | Payment terms | **A customer default plus a per-deal override with a reason.** Deals also gain **value and currency**. | Matches how terms really vary by deal. Deal value is needed anyway. |
| D17 | Bank-detail controls | **Approval + verification + masking.** Every add or change needs a second person (configurable; see section 4, rule 3). An account is unusable until verified. Numbers are masked unless the user has the reveal permission. The RM and Compliance are alerted on changes. | Bank-detail changes are a classic fraud route. |
| D18 | Import template | **Excel template**: an *Instructions* sheet and a *Companies* sheet with dropdowns. The importer accepts `.xlsx` and `.csv`. | Prevents errors instead of only reporting them. Adds `openpyxl` to the backend. |
| D19 | Word for a row that did not import | **"Failed"** (as the lead asked). A whole file that cannot be read says **"File not accepted"**. | **Risk accepted:** "Failed" also means a failed compliance check. Mitigation in W1.3. |
| D20 | "Conversation" label | **Rename to "Communication"** (as the lead asked). | **Risk accepted:** users may look there for emails and calls, which live under Activity. Mitigation in W1.8. |
| D21 | Qualification suggestion with no required criteria | **Suggest Qualified when at least one criterion is recorded and none failed.** Required criteria, when set, must still all pass. Always show the reason. | Fixes a bug: today it always says "Not qualified" when every criterion is optional. |
| D22 | Automatic qualification | **Auto-record, a person decides.** Criterion results are recorded automatically from CRM data, marked "Auto · source · date", and a person can override them. The Qualified / Not qualified outcome stays a human decision. | Saves effort and keeps "the suggestion is not the decision". |
| D23 | Where this plan lives | `docs/feedback-plan.md` | `docs/plan.md` already holds the post-demo plan. |
| D24 | Sequencing | **Four waves by risk:** quick fixes, then security, then customer master, then sanctions and automation. | Each wave can ship on its own. |

---

## 3. What already exists

Checked against the code before planning. Nothing below needs rebuilding.

| Comment | Status | What is already built | Where |
|---|---|---|---|
| F1 Template instructions | Partly | The template is generated from the importer's own column list. Validation messages are detailed. | `backend/app/modules/onboarding/application/company_import_service.py:71-87` |
| F2 Required vs `*` | Partly | The shared `Field` component renders `*` from a `required` prop. About 15 forms still hand-write "(required)" or "(optional)". | `frontend/src/components/ui/Field.tsx:25` |
| F3 Refused/Rejected | Built, inconsistent words | One server status (`rejected`) shown as "refused", "Refused", "rejected" and "Rejected", plus "Line n" next to "Row n" | `frontend/src/modules/onboarding/pages/CompanyImportPage.tsx:38,96,107,126,236` |
| F5 Settings grouping | Built | The "Rules" group exists. Only the styling is weak. | Settings page |
| F9 User-admin approval | Built; no approval needed (D3) | Users cannot change their own role, cannot deactivate themselves, and the last role manager is protected. Self-signup is off. Changes go only to application logs, not the audit trail (X5). | `backend/app/api/rest/auth/router.py` (~lines 640-690) |
| F11 Sanctions | Foundation | A Sanctions check type. Append-only results with provider, date, expiry, raw result and evidence. Check cycles with rules version. A Clear needs a sanctions pass in the current cycle and expires. Directors can be check subjects. Buyer sanctions are a handover rule. | `onboarding/domain/entities/verification_result.py`, `check_cycle.py`, `domain/handover_conditions.py` |
| F12 Exempt | Built elsewhere | Exempt is a **screening-checklist** answer. Manual check results are Passed / Failed / Review. | `frontend/.../components/ScreeningChecklist.tsx:413`, `background-check-labels.ts:16` |
| F13 Conversation | Built | "Conversation" is the company's contact status. Calls, emails and meetings are already logged as **Activity**. | `onboarding/domain/entities/exporter_activity.py`, `engagement_enums.py` |
| F13b Auto-qualification | Plumbing built | Results carry source (MANUAL/IMPORT/RXIL/AUTOMATED), who decided (person or system), observed value, confidence and evidence. RXIL already writes automated results. | `onboarding/domain/entities/qualification.py`, `infrastructure/rxil/company_package.py:174` |
| F14 Preview-only | Partly | An in-app viewer for PDF, images and text. Other files can only be downloaded. Anyone can download. Views and downloads are not logged. | `frontend/.../components/DocumentViewer.tsx`, `useOpenDocument.ts:28`, `onboarding/api/document_router.py:222,412` |
| F16 Primary contact | Half | At most one primary contact per company (database index). Zero is allowed. Promotion to Customer is automatic on Qualified + Clear. The handover rule list is built to take new conditions. | `application/exporter_contact_activity_service.py:50,133`, `application/exporter_profile_service.py:1233`, `domain/handover_conditions.py` |
| F18 Addresses | Partly | GST registrations (branches) store state and a free-text address. | `onboarding/domain/entities/exporter_gstin.py:107-129` |
| F19 Bank details | Pieces outside the CRM | A platform `customers` module has a bank-account table (encrypted number, IFSC, currency, verified flag), but no API and no link to CRM companies. A `BANK_ACCOUNT` verification type exists. Bank-activity findings exist. | `backend/app/modules/customers/domain/entities/customers.py:61-82`, `orchestration_enums.py` |
| F22 Collector | Pattern to copy | RM assignment: an assigned user, a permission, bulk reassignment and a "my companies" view. | `exporter_profile.relationship_manager_user_id`, `api/staff_router.py` |

**Missing entirely:** F4 preview table · F6 country picker · F10 Admin separation (and permission
enforcement) · F17 contact status · F20 payment terms (and deal value) · F21 parent/child.

**Bugs:** F15 multi-file drop keeps only the first file (`DocumentsByCategory.tsx:158`) · F7
evidence error shown under an optional field (`ManualResultForm.tsx:107,232`).

### Found during the check, not raised by the leads

| # | Finding | Where | Planned in |
|---|---|---|---|
| X1 | The qualification suggestion is always "Not qualified" when no criterion is required | `application/qualification_service.py:643-654` | W1.9 |
| X2 | The import preview drops empty cells, so later values shift columns | `CompanyImportPage.tsx:238` | W1.2 |
| X3 | Admin can record and approve compliance decisions, so four-eyes can be met by an Admin | `api/background_check_router.py:161-162`, `api/screening_router.py:64` | W2.1 |
| X4 | Most permissions in the Roles screen gate nothing. Routes are hard-coded by role (57 `UserRole.ADMIN` references in onboarding and auth routes). The frontend also treats ADMIN as having every permission. | `platform/authorization/catalog.py` (`enforced=False`), `frontend/src/platform/access/usePermissions.ts:69` | W2.1 |
| X5 | User and role changes are not in the audit trail | `api/rest/auth/router.py` | W2.2 |
| X6 | The checklist asks "Is the registered address a physical business address?" but there is no address field | `application/screening_review_service.py:91` | W3.3 |
| X7 | Deals have no value or currency | `onboarding/domain/entities/deal.py` | W3.5 |
| X8 | Country is free text in four forms; the header shows "IN" | see W1.7 | W1.7 |
| X9 | The environment is served over plain HTTP ("Not secure" in every screenshot) | deployment | W1.10 |

---

## 4. Cross-cutting rules

Every item below follows these. They are listed once here instead of in each item.

1. **Permissions, not roles.** New and touched routes check a permission
   (`require_permission(module, action)`, `platform/authorization/services.py:83`), not
   `require_role(...)`. New permissions go in `platform/authorization/catalog.py` with
   `enforced=True` and a seeded default per built-in role (an `auth_00NN` migration). On the
   frontend, gate with the capability manifest (`platform/access/capabilities.ts`) or
   `useHasPermission`, never by role name.
2. **Behaviour switches are settings.** Follow `application/compliance_settings.py`: a
   `CRM_*` value in `platform.configuration.Settings`, read at call time, validated at
   start-up, with the default written in this plan. **Reference lists that admins maintain**
   (sanctions lists, payment terms) are data managed under Settings → Rules, versioned
   like qualification criteria.
3. **Approvals reuse one pattern.** Bank-detail changes and sanctions true-match
   decisions work like background-check proposals: propose, then approve or reject. The
   approver may not be the proposer, the request carries a reason, it shows on the
   Compliance work screen, and SLA targets apply. Build the approval-mode check once
   (`OFF | SECOND_PERSON | PERMISSION_HOLDER | BOTH`) and use it for both. User
   administration does **not** use it (D3).
4. **Everything sensitive is audited.** Use the audit trail (the `audit` module), not
   application logs: who, what, before → after, and the approver if any. This covers user
   and role changes, document views and downloads, bank-detail reveals and changes, and
   sanctions dispositions.
5. **Masking.** New sensitive fields (bank account numbers) follow the tax-ID rule: masked
   unless the user holds a reveal permission, and every reveal is audited.
6. **Migrations.** Next free revisions: `onboarding_0045_…` and `auth_0007_…`. One
   migration per item where possible, named by behaviour
   (e.g. `onboarding_0045_contact_status`). `alembic heads` must print exactly one head.
7. **API contract.** After any API change, regenerate `openapi.json` and the frontend
   `schema.ts`, and update the matching file in `docs/contracts/`.
8. **History.** Every new field a person edits writes a History row, consistent with
   today's company record.
9. **Wording.** Use the shared `Field` component (`*` marks required). Use business names
   in messages (PAN, GSTIN), never column keys or enum values.

---

## 5. Wave 1: quick fixes and bugs

Low risk and visible in every demo. Items are independent and can be split across people.
**Wave size: about 2–3 weeks for one developer, or about 1 week for two.**

### W1.1 Multi-file upload (F15): bug · M

- **Now:** the drop handler keeps only the first file (`DocumentsByCategory.tsx:158`). The
  upload dialog holds one file because each upload needs a category and document type.
  The server takes one file per request, which stays as is.
- **Change (frontend):**
  1. Accept several files from drop and from the file picker (`multiple`).
  2. A batch dialog lists every file. Category and document type are set once for all
     and can be changed per row. Rows can be removed before uploading.
  3. Upload files one request each (2 at a time). Show progress and scan status per file.
     Successful files stay when another fails, and a failed file can be retried.
  4. Limits: `CRM_UPLOAD_MAX_FILES` (default 10) per batch, plus the existing size limit,
     both shown in the dialog.
  5. Used for both company and deal documents (same component).
- **Acceptance:** dropping 5 files uploads 5 documents with their chosen categories. One
  oversized file fails on its own row and the other 4 succeed.
- **Tests:** vitest for drop, picker, per-row category and partial failure.

### W1.2 Import preview as a grid (F4, X2) · S

- **Now:** cells joined with " · " after empty cells are dropped (`CompanyImportPage.tsx:238`).
- **Change (frontend):** a scrollable grid. Headers come from the file. Empty cells are
  shown as empty. The first column is the row number (the same number used in the
  results). The first 10 rows are shown with "N rows in file". Columns missing from the
  template, or not in it, are highlighted before upload.
- **Acceptance:** a file with a blank PAN shows the blank in the PAN column and the
  later values stay under their own headers.
- **Note:** if the design rule against tables still applies, this is the agreed exception
  (a file preview is inherently tabular).

### W1.3 Import result wording (F3) · S

- **Decision D19:** "Failed" for a row. "File not accepted" for a whole file.
- **Change (frontend only; API status values unchanged):** the tile reads "N failed", the
  section "Failed rows", the badge "Failed", and the summary line uses the same word. Use
  "Row n" everywhere. Messages use business names (PAN, GSTIN, IEC, CIN, Source), the
  allowed sources are listed by their labels, and "RXIL intake" is replaced with plain
  wording.
- **Mitigation for the two meanings of "Failed":** the import page always says
  "Failed rows" or "rows failed to import", never a bare "Failed". Compliance screens
  keep "Failed" for checks.
- **Acceptance:** one word for a failed row everywhere on the page. No raw column keys or
  enum lists in messages.

### W1.4 Required-field convention (F2) · S

- **Change:** replace the ~15 hand-written "(required)" / "(optional)" labels with
  `Field required`. Add one "* required" note at the top of each form that has a required
  field. Keep "optional" only where a group rule needs it (W1.5).
- **Acceptance:** `grep "(required)"` finds no form labels. Record a decision shows
  "Reason *".

### W1.5 Evidence error placement (F7) · S

- **Now:** one form-level error rendered directly under "Evidence link (optional)".
- **Change (frontend):** wrap note, document and link in one group headed "Evidence".
  When Outcome = Passed, the group heading shows "at least one required" before submit.
  On submit without evidence, the error is attached to the group (highlighted border,
  message under the heading) and focus moves to the note.
- **Acceptance:** the error never appears under a single field. Screen readers announce it
  for the group.

### W1.6 Settings grouping (F5) · S

- **Change:** two clearly separated groups in the Settings side menu: **Access** (My
  profile, Users, Roles) and **System configuration** (Qualification criteria, Required
  documents, and later Sanctions lists and Payment terms). Use stronger group headings and
  a divider.

### W1.7 Country picker (F6, X8) · S–M

- **Now:** free text in New company (`AddExporterPage.tsx:189`), Create buyer
  (`CreateBuyerCompanyForm.tsx:108`), Deal buyer (`DealDetailPage.tsx:152`) and the company
  edit panel (`CompanyPanel.tsx:224`). A `countryName()` helper exists (`constants.ts:84`).
- **Change (frontend):** one shared searchable `CountrySelect` that shows names, stores the
  ISO 3166-1 alpha-2 code, and pins India at the top. Use it in all four forms. Show
  country names in every read view (company header, deal buyer, lists).
- **Backend:** none (validation already requires the ISO code).
- **Acceptance:** typing "ind" offers India and Indonesia. The company header reads
  "India", not "IN".

### W1.8 Rename "Conversation" to "Communication" (F13) · S

- **Decision D20.** Rename it in the header badge label, the History filter, toasts
  (`ConversationPath.tsx:66`), `HistoryTimeline.tsx:51` and `ExporterDetailPage.tsx:234`.
  Internal names (`conversation` field, API) stay unchanged.
- **Mitigation:** the History filter and the badge get a tooltip: "Communication status.
  Calls, emails and meetings are under Activity." Add an **Activity** filter to History if
  it is not already there.
- **Acceptance:** the word "Conversation" no longer appears in the UI.

### W1.9 Qualification suggestion rule (X1) · S

- **Decision D21.** In `_suggest` (`qualification_service.py:643`):
  - If any active criterion is required, every required one must Pass (unchanged).
  - If none is required, suggest **Qualified** when at least one active criterion has a
    current result and none of them is Fail. Otherwise suggest **Not qualified**.
- **Also:** return a short reason with the suggestion (e.g. "3 of 7 recorded, none failed"
  or "Annual revenue failed"). Show it next to "Suggested: …" on the Qualification tab.
- **Acceptance:** the screenshot's case (3 Pass, 4 not recorded, none required) suggests
  Qualified with the reason shown. One Fail makes it Not qualified.
- **Tests:** unit tests for the rule; update existing suggestion tests.

### W1.10 HTTPS on the environment (X9) · S (infrastructure)

- A certificate on the load balancer, an HTTPS listener, HTTP redirected to HTTPS, and
  secure cookies. Do this before the next lead review: the leads asked for preview-only
  documents and bank details on a site marked "Not secure".

### W1.11 Excel import template (F1) · M

- **Decision D18.**
- **Backend:**
  1. Add `openpyxl` to the backend dependencies (it is not installed today).
  2. `GET /imports/companies/template?format=xlsx` (keep `csv`) builds the workbook from
     the **same** column definitions and allowed values the validator uses.
     - **Instructions sheet:** one row per column, giving whether the value is mandatory,
       the format, an example and the allowed values.
     - **Companies sheet:** a header row and dropdown validation for country (name →
       code), source (labels) and Yes/No style fields. Industry stays free text, because
       no industry master list exists.
  3. `POST /imports/companies` accepts `.xlsx` as well as `.csv`. Read the Companies
     sheet only. Row numbers match the sheet's rows.
- **Frontend:** the download button offers Excel (default) or CSV. The upload accepts both.
- **Acceptance:** a user filling the Excel template from the Instructions sheet alone,
  with valid data, gets zero format errors. A CSV import behaves exactly as today.
- **Tests:** a generated template round-trips through the importer. A wrong-sheet or
  wrong-header file is "File not accepted".

### W1.12 Exempt (F12): no change

- **Decision D10.** No code change. The explanation goes back to the lead (section 9).

---

## 6. Wave 2: security and access

Changes who can do what, so it needs a demo-account review before release.
**Wave size: about 3–4 weeks for one developer.**

### W2.1 Enforce permissions; make Admin read-only (F10, X3, X4) · L

- **Decision D1 + D2.**
- **Now:** ADMIN holds every permission (`catalog.py:194`). The company, verification and
  screening permissions are declared but `enforced=False`. Routes are hard-coded with
  `require_role(…, ADMIN)` (57 references). Admin can decide and approve compliance. The
  frontend treats ADMIN as holding everything (`usePermissions.ts:69`).
- **Backend:**
  1. Replace `require_role` with `require_permission` on every onboarding route
     (companies, contacts, activities, deals, documents, qualification, screening,
     background check, import, partner intake). Mark those modules `enforced=True`.
  2. Add a `settings` permission module (`settings:manage`) for qualification criteria,
     required documents, sanctions lists and payment terms. These are Admin-only today
     via `require_role(ADMIN)`.
  3. New built-in ADMIN grants: `users:*`, `roles:*`, `settings:manage`, `audit:view`,
     and **view-only** business permissions (`exporters:view`, `verifications:view`,
     `screening:view`). No create, edit, transition, decide, approve, assign or
     tax-ID reveal.
  4. Compliance decision and approval routes accept only holders of the compliance
     permissions. Admin can no longer be the second officer.
  5. Partner (RXIL) intake: move from "Admin only" to a permission
     (`exporters:partner_intake`), granted to Compliance by default. Revisit if the leads
     want a different owner.
  6. Migration `auth_0007_…` updates ADMIN's seeded grants. Built-in roles are editable,
     so the migration changes ADMIN only where its grants still match the original seed,
     and logs any role it skipped.
- **Frontend:** remove the `role === 'ADMIN'` shortcut in `useHasPermission`. Update the
  capability manifest. Hide or disable create, edit and decide controls when the
  permission is missing (no dead buttons).
- **Data and demo:** demo accounts that used Admin for business work need a second
  account with a business role (D2). Update `docs/demo.md` and the seed or loader scripts.
- **Tests:** many fixtures use an admin user for business actions and will fail. Switch
  them to the matching role or `user_with_permissions`. Add a permission-matrix test:
  every route × every built-in role → allowed or refused.
- **Acceptance:** an Admin can open any company and deal but every write returns 403 and
  no write button is shown. Unticking a permission in Roles actually removes that ability.
- **Risk:** large test churn. Land it as its own PR and run the full `--crm` suite.

### W2.2 Audit trail for user and role changes (X5) · S–M

- **Decisions D3 + D4.** No approval step and no change to how users or roles are created
  or edited. One admin acts and the change applies immediately, as today.
- **Backend:** every user and role change writes an audit-trail entry (the `audit`
  module): who, which user or role, what changed (before → after), and when. That covers
  create user, change role or permission role, activate or deactivate, reset password,
  and create, edit or delete a role (including its permission list). The routes in
  `api/rest/auth/router.py` and `api/rest/auth/roles_router.py` keep their existing
  guards.
- **Frontend:** a "History" section on each user and on each role in Settings → Access,
  readable by `users:view` / `roles:view` holders.
- **Acceptance:** after Admin A changes Priya's role to Compliance, Priya's History shows
  "Role: RM → Compliance, by Admin A, 8 Oct 2026 14:05". The change itself applied
  immediately.
- **Optional:** this item is independent and can be dropped without affecting any other
  item.

### W2.3 Documents: preview by default, download by permission (F14) · L

- **Decisions D5 + D6.**
- **Backend:**
  1. A new `documents:download` permission, enforced and granted to Compliance by default.
     Both the download route and the download-link route refuse without it
     (`document_router.py:398-412`).
  2. A **preview** route serves a safe rendition inline: PDF, or an image re-encoded as
     PNG or JPEG, with `Content-Disposition: inline`, a sandboxing Content Security Policy
     and `nosniff`. Originals are still served as attachments only, so the protection
     against active content stays.
  3. **PDF conversion:** after the scan passes, Word, Excel, PowerPoint and similar files
     are converted to PDF with LibreOffice running headless in a worker or container.
     Store the rendition next to the original. Rendition status: preparing / ready /
     unavailable. A failed conversion leaves the original intact and shows "Preview
     unavailable".
  4. Audit entries for every **view** and every **download** (document, user, time).
- **Frontend:**
  1. Render PDFs with an embedded viewer (`pdfjs-dist`) that has no save or print
     controls, instead of the browser's own PDF viewer.
  2. A watermark overlay on every page and image: user name, date and time.
  3. The Download button only appears with `documents:download`.
  4. Office files show "Preparing preview…" until the rendition is ready.
- **Infrastructure:** LibreOffice in the backend image (or a separate converter service),
  with a timeout and a memory limit.
- **Acceptance:** an RM can read a `.docx` as a watermarked PDF, sees no Download button,
  and gets 403 on a direct download URL. A Compliance user can download. Both actions
  appear in the audit trail.
- **Stated limit:** preview-only stops casual saving but cannot stop screenshots or
  determined copying from the browser. The leads should know this.

---

## 7. Wave 3: contacts and customer master

Decision D13: the CRM owns this data for now. Every entity gets a stable ID and an
`updated_at` so a future ERP export or sync is straightforward.
**Wave size: about 6–8 weeks for one developer; W3.4 is the largest.**

### W3.1 Contact status and verification date (F17) · M

- **Decision D12.**
- **Data (`onboarding_0045_contact_status`):** `status` (ACTIVE / INACTIVE / LEFT_COMPANY,
  default ACTIVE), `status_changed_at`, `status_reason`, `last_verified_at` and
  `last_verified_by` on the contact.
- **Rules:**
  - Moving a contact out of Active requires a reason.
  - An inactive contact cannot be primary. Deactivating the primary clears the flag and
    raises the "no primary contact" warning (W3.2).
  - A "Mark verified" action stamps the date.
  - `CRM_CONTACT_REVERIFY_MONTHS` (default 12) marks a contact "Verification due" once that
    many months have passed since the last verification (computed on read).
- **Frontend:** a status pill on each contact. Inactive contacts are hidden behind
  "Show inactive (n)". Status and date fields in the contact sheet. History rows for each
  change.
- **Acceptance:** a contact marked "Left company" with a reason disappears from the
  default list, appears in History, and cannot be made primary.

### W3.2 Primary contact required at handover (F16) · S–M

- **Decision D11.**
- **Backend:** add a condition to the handover rule list (`domain/handover_conditions.py`):
  "the seller has an active primary contact". It reports the message "Add an active
  primary contact for {company} before handing over".
- **Frontend:** a "No primary contact" warning on the company header (Customers and
  Prospects) and a filter or badge in the companies list.
- **Acceptance:** handing over a deal for a company without an active primary contact is
  refused with that message, alongside any other unmet conditions. Adding one clears it.

### W3.3 Customer addresses (F18, X6) · M

- **Data (`onboarding_0046_company_addresses`):** a `company_address` record with type
  (REGISTERED, BILLING, SHIPPING, FACTORY_WAREHOUSE, CORRESPONDENCE), line 1, line 2,
  city, state, postal code, country (ISO via W1.7), is-default per type, active, and
  created/updated fields. A company can have many addresses.
- **GST branches:** add an optional `address_id` on the GST registration. Keep the existing
  free-text address and offer "Create address from GST registration".
- **Rules:** one default per type per company. Deactivate rather than delete. History rows
  for every change.
- **Compliance:** the checklist item "Is the registered address a physical business
  address?" shows the default registered address beside it. A change to the registered
  address after the last Clear shows "Changed since last Clear" on the Background check
  tab.
- **Frontend:** an **Addresses** section on the company Details tab with add, edit and set
  default.
- **Acceptance:** a foreign buyer (no GSTIN) can hold an address. The registered address
  appears next to the checklist question.

### W3.4 Bank accounts with approval, verification and masking (F19) · L–XL

- **Decision D17.** Build this inside the onboarding module, linked to the CRM company.
  The platform `customers` bank table is a different customer model with no API. Reuse
  its encryption approach if suitable, not the table.
- **Data (`onboarding_0047_company_bank_accounts`):** a `company_bank_account` record with:
  - account holder name, bank name, branch
  - account number (encrypted at rest, with the last 4 digits stored separately for
    display)
  - IFSC, SWIFT/BIC, IBAN (for foreign accounts), currency (ISO 4217)
  - account type (CURRENT, EEFC, SAVINGS, OTHER) and the **AD (Authorised Dealer) code**
  - is-primary per currency
  - status: PENDING_APPROVAL → PENDING_VERIFICATION → VERIFIED, or REJECTED or INACTIVE
  - verification method (cancelled cheque, bank letter, penny-drop) and evidence
    document reference
  - verified by and verified at

  A **change** to an account creates a new pending version; the old one stays in force
  until the new one is approved and verified.
- **Settings:** `CRM_BANK_CHANGE_APPROVAL_MODE` uses the approval modes in section 4, rule 3 (default
  `SECOND_PERSON`). Permissions:
  - `exporters:manage_bank_accounts` (RM and Compliance) to propose
  - `exporters:approve_bank_accounts` (Compliance) to approve
  - `exporters:view_bank_details` (Compliance) to reveal full numbers
- **Verification:** an account becomes VERIFIED either when a cancelled cheque or bank
  letter is attached and a Compliance user confirms it, or when a passed `BANK_ACCOUNT`
  verification result is linked (the existing verification framework; a penny-drop
  provider is a later adapter). An unverified account can never be primary or used on a
  deal.
- **Alerts:** every proposal, approval and rejection notifies the company's RM and the
  Compliance queue (the `notifications` module). Every reveal and change is audited.
- **Frontend:** a **Bank accounts** section showing masked numbers and status pills, a
  propose-change sheet, an approval card on Compliance work, and a reveal button (with
  permission) that is audited.
- **Acceptance:** an RM adds an EEFC account, which shows "Pending approval". A second
  person approves it ("Pending verification"). A Compliance user attaches a cheque and
  verifies it ("Verified"). The RM never sees the full number. Each step is in History and
  the audit trail.

### W3.5 Deal value, currency and payment terms (F20, X7) · M–L

- **Decision D16.**
- **Data (`onboarding_0048_payment_terms_and_deal_value`):**
  - A `payment_term` reference list (Settings → Rules → Payment terms, `settings:manage`)
    with code, label, kind (ADVANCE, LC_SIGHT, LC_USANCE, DP, DA, OPEN_ACCOUNT), days
    (for usance, DA and open account) and active. Seeded with common terms.
  - Company: `default_payment_term_id`.
  - Deal: `value_amount` (numeric), `currency` (ISO 4217), `payment_term_id` and
    `payment_term_override_reason`.
- **Rules:** a new deal inherits the company default. Choosing a different term requires a
  reason. Value, currency and term are frozen into the handover snapshot. Retired terms
  stay readable on old deals.
- **Frontend:** a payment terms settings page; a default term on the company Details tab;
  value, currency and term on the deal form and header; the All deals list can show the
  value.
- **Follow-on:** the deal value can auto-record the "Typical deal size" criterion (W4.2).
- **Acceptance:** a customer with default "DA 90 days" opens a deal that shows DA 90 days.
  Changing it to "LC at sight" asks for a reason, and the reason appears in History.

### W3.6 Collections owner (F22) · M

- **Decision D14.**
- **Data (`onboarding_0049_collections_owner`):** `collections_owner_user_id` on the company.
- **Permission:** `exporters:assign_collector` (enforced), granted by default to Compliance
  and to holders of `exporters:assign_rm`. Not granted to Admin (D1: Admin is read-only
  on business data).
- **Reuse the RM pieces:** an owner field with a picker, bulk reassign, and a "My
  collections" filter (like *My companies*). History rows for every change.
- **Note:** collectors are usually finance staff. A built-in "Finance" role does not exist
  yet. Until it does, any active staff user can be picked.
- **Acceptance:** a company shows "Collections owner: Meera". Bulk reassignment moves 20
  companies in one action, with History rows.

### W3.7 Parent / child companies (F21) · M–L

- **Decision D15.**
- **Data (`onboarding_0050_company_groups`):** `parent_company_id` (self-reference) and
  `group_relationship` (SUBSIDIARY, BRANCH_OFFICE, GROUP_COMPANY, JOINT_VENTURE) on the
  company. Cycles are refused with a recursive check in the service and a
  database-side guard. The ultimate parent is computed on read.
- **Group view:** a **Group** tab on any member. It shows the tree, and each member's
  stage, background-check status, risk rating, open deals and deal value (once W3.5
  lands). No group-level limits or decisions (deferred).
- **Suggestions:** a "Possible group members" list from shared directors or UBOs, where
  that data is recorded. Suggestions are never linked automatically; a person confirms.
- **Permissions:** `exporters:edit` to link or unlink. History rows on both companies.
- **Acceptance:** linking A as the parent of B shows both in A's Group tab. Linking A under
  B as well is refused with a clear message.

---

## 8. Wave 4: sanctions and automation

The largest design work. Start the W4.1 design while Wave 3 is being built.
**Wave size: about 5–6 weeks for one developer.**

### W4.1 Structured sanctions screening (F11) · XL

- **Decisions D7, D8, D9.**
- **Reference data:** Settings → Rules → **Sanctions lists** (`settings:manage`), with
  code, name, issuing authority, active, mandatory and current-version date. Versioned like
  qualification criteria. Seeded active and mandatory: **UN Security Council
  Consolidated List** and **India MHA / UAPA designated list**. OFAC, EU and UK HMT can
  be added as entries with no code change.
- **Data (`onboarding_0051_sanctions_screening`):**
  - **Screening run:**
    - subject: the company, a director or a UBO (existing subject types)
    - check cycle, performed by and performed at
    - provider (MANUAL for now) and provider reference
    - the lists screened, each with the version date used
    - search terms used (name, aliases, country)
    - outcome, derived from its hits
  - **Hit:** run, list, matched name, list entry ID, match score or strength, and
    disposition (OPEN, FALSE_POSITIVE, TRUE_MATCH, ESCALATED) with reason, decided by,
    approved by and dates.
- **Rules:**
  1. A run must cover every **active mandatory** list, otherwise it cannot be saved as
     complete.
  2. Run outcome: **Passed** when there are no hits, or every hit is FALSE_POSITIVE.
     **Failed** when any hit is TRUE_MATCH. **Review** while any hit is OPEN or ESCALATED.
  3. A completed run writes or links the existing **SANCTIONS verification result** for
     the cycle. The existing rule "a sanctions check must have passed in this cycle"
     therefore keeps working unchanged.
  4. **True match:** controlled by `CRM_SANCTIONS_TRUE_MATCH_APPROVAL = SINGLE |
     SECOND_OFFICER | HEAD` (default `SECOND_OFFICER`; `HEAD` uses a new
     `compliance:approve_true_match` permission). While a true match is proposed, the
     company is flagged immediately; the flag is confirmed or removed on decision.
  5. **Coverage:** the Background check tab shows each subject (company, each director,
     each UBO) with its latest run, the lists covered and the date. Unscreened subjects
     are highlighted.
  6. **Re-screening triggers:**
     - Clear expiry (already built).
     - An admin records a **new version date** on a list: every company whose latest run
       used an older version appears on a **"Re-screen due"** worklist (alongside Re-KYC
       due on Compliance work).
     - The company name changes, or a director or UBO is added.
  7. Hits and dispositions are append-only. A changed disposition is a new row that
     supersedes the old one.
- **Frontend:**
  - a "Record screening" form (lists pre-ticked from settings, add hits, disposition per
    hit)
  - a run detail view with a hits table
  - a true-match approval card on Compliance work
  - the coverage panel and the Re-screen due tab
- **Ready for a provider later:** a provider adapter fills the same run and hit records
  through the existing verification-adapter registry (`domain/workflow_dependencies.py`).
  No model change is needed.
- **Acceptance:** an officer records a run against UN and MHA with one hit, marks it a
  false positive with a reason, and the run is Passed. The Clear rule sees a sanctions
  pass. Recording a new MHA version date puts the company on Re-screen due.

### W4.2 Automatic qualification results (F13b) · M–L

- **Decision D22.**
- **Configuration:** add an optional **auto source** to a qualification criterion
  (creating a new version, as today). The admin picks from a fixed list:

  | Auto source | Rule |
  |---|---|
  | IEC verification | Pass if a passed IEC check exists |
  | Years since established | From `year_established`, or the incorporation year in the CIN |
  | Company industry | Compared with the criterion's allowed values |
  | Export markets | Compared with the allowed values |
  | Trade history | Pass if at least one recorded export |
  | Deal value | Largest or typical deal value, after W3.5 |

- **Backend:** an evaluator runs when its source data changes (company edit, verification
  recorded, trade history import, deal value change). It writes a result with source
  AUTOMATED, decided by the system, the observed value and an evidence link.
  - **A result recorded by a person always wins.** The evaluator never overwrites a newer
    manual result.
  - The suggestion (W1.9) recalculates.
  - The **outcome stays a person's decision**.
- **Frontend:** the result shows "Auto · IEC check · 8 Oct 2026". Pass / Fail / Unknown
  buttons still let a person override.
- **Acceptance:** recording a passed IEC verification immediately shows "Holds an export
  licence (IEC): Pass (Auto)". A person's later Fail stands and is not replaced.

---

## 9. Reply to the leads

| Comment | Answer |
|---|---|
| Import template: add an instructions tab | Yes. The template becomes an Excel file with an Instructions sheet and dropdowns. CSV still works. (W1.11) |
| Instead of "·" use a table | Yes. The preview becomes a grid. We also found it was hiding empty cells, which is now fixed. (W1.2) |
| Use Failed / Error instead of Rejected / Refused | Yes. A row that did not import is "Failed" everywhere on the page, and an unreadable file is "File not accepted". (W1.3) |
| User creation approval, role and permission change process? | Not needed. User creation and role changes stay as they are (one admin, no second approval). Existing safeguards stay: nobody can change their own role or deactivate themselves. Every change will be recorded in the audit trail so there is a record of who changed whose access. (W2.2) |
| Admin should not add companies or deals | Agreed. Admin becomes read-only on business data and can no longer approve compliance decisions. People who need both get two accounts. (W2.1) |
| Align System Config vs User Creation | Yes. Settings is split into "Access" and "System configuration". (W1.6) |
| Country drop-down | Yes, in all four forms where country is entered, and names are shown instead of codes. (W1.7) |
| Error message placement | Yes. The evidence rule is now shown on the evidence group as a whole. (W1.5) |
| Required or "*" | "*" everywhere, with one legend per form. (W1.4) |
| Sanctions can be multiple: how are they recorded and maintained? | Each screening will record which lists were checked (configurable; UN and India MHA to start), each possible match with its decision, and a second officer approves true matches. Updating a list puts affected companies on a re-screen worklist. (W4.1) |
| No Exempt in the Outcome list | Intended: Exempt applies to **checklist questions**, not to checks. KYB, AML and Sanctions must pass. The Exempt option is on each item in the screening checklist. No change planned. |
| Some can pass automatically from the background check | Yes. Criteria such as IEC held, years in business and industry will be recorded automatically and marked "Auto". The Qualified decision stays with a person. We also fixed the suggestion showing "Not qualified" when all criteria are optional. (W1.9, W4.2) |
| Conversation → Communication | Yes, renamed to "Communication". Calls, emails and meetings remain under Activity. (W1.8) |
| Online preview only, no local copies | Yes. Everyone gets a watermarked on-screen preview (Word and Excel included). Only Compliance can download, and every view and download is logged. Note that screenshots cannot be prevented. (W2.3) |
| Multiple files: only one uploaded | Bug confirmed and fixed: several files can be dropped, each with its own category. (W1.1) |
| At least one primary contact; date and status per contact | A deal cannot be handed over without an active primary contact, and a warning shows on the company. Contacts get Active / Inactive / Left company with dates, and a "last verified" date. (W3.1, W3.2) |
| Addresses, bank details, payment terms, parent/child, collector | All planned with the CRM as the owner of this data: typed addresses; bank accounts with approval, verification and masking; payment terms per customer with a per-deal override; group view; and an internal Collections owner. (W3.3–W3.7) |

---

## 10. Deferred (decided, not in this plan)

- A live sanctions screening provider and daily automatic re-screening (W4.1 is built
  ready for it).
- A penny-drop bank verification provider (plugs into the `BANK_ACCOUNT` check).
- Group-level limits, exposure and risk decisions (needs deal values in production first).
- ERP sync or export of the customer master (D13). Stable IDs and `updated_at` are in
  place for it.
- Multiple roles per user (D2 chose separate accounts).
- An approval step for user creation and role changes (D3: the lead asked whether it was needed; answered no).
- A built-in Finance role for collectors.
- Exempt on checks (D10).
- An industry master list (the import template keeps industry as free text).

---

## 11. Definition of done (every item)

1. Acceptance criteria above met and shown in the running app.
2. Backend gates, run from `backend/` on a **throwaway** database (never the working
   `aner_settlement` DB):
   ```
   ./.venv/Scripts/alembic.exe heads          # exactly one head
   ./.venv/Scripts/python.exe -m pytest --crm -q --no-cov -p no:cacheprovider
   ./.venv/Scripts/ruff.exe check .
   ./.venv/Scripts/lint-imports.exe --config importlinter.ini
   ```
   Run the whole suite (without `--crm`) only when an item touches `app/platform`,
   `app/shared`, `app/main.py` or another module. W2.1 does (it changes `app/platform/authorization`).
3. Frontend gates, run from `frontend/`:
   `npx tsc -b --noEmit ; npx eslint . ; npx vitest run ; npx vite build`
4. `openapi.json` and `schema.ts` regenerated, and `docs/contracts/` updated.
5. `docs/demo.md` updated where a demo step or account changes (especially W2.1).
6. New settings documented with their defaults in `docs/development.md`.
7. No plan IDs in code, tests, migrations or UI (section 1).

---

## 12. Summary by wave

| Wave | Items | Size (one developer) | Ships |
|---|---|---|---|
| 1 Quick fixes and bugs | W1.1–W1.11 | about 2–3 weeks | Every wording and form fix, the upload bug, the preview grid, the suggestion rule, HTTPS, the Excel template |
| 2 Security and access | W2.1–W2.3 | about 3–4 weeks | Read-only Admin, enforced permissions, audit trail of user and role changes, preview-only documents |
| 3 Contacts and customer master | W3.1–W3.7 | about 6–8 weeks | Contact status, primary-contact rule, addresses, bank accounts, deal value and payment terms, collections owner, groups |
| 4 Sanctions and automation | W4.1–W4.2 | about 5–6 weeks | Structured sanctions runs and hits, re-screen worklist, automatic qualification results |

Waves 1 and 3 can run in parallel with a second developer. Wave 2 should land before any
real customer data (bank details, KYC documents) goes onto the environment.
