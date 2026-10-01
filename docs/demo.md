# Demonstrating the Exporter CRM

A walk-through of the CRM on sample data, then the main path live on a new company,
then the other paths. It follows architecture §4 (the PDF) and what the system does
today — [`architecture.md`](architecture.md) explains the rules behind each step.

---

## 1. Before the demo

**Use a fresh database.** The database the test suite runs against collects thousands
of test companies, some in states the product cannot produce (tests set them up
directly). A demo on it shows noise and impossible records. Run a separate Postgres
16 for the demo — for example a second container on a free port — and never run the
test suite against it.

With `backend/.env` pointing at that database (see [`development.md`](development.md)
§3 for every setting it needs):

```bash
cd backend
python -m alembic upgrade head
python -m app.platform.authentication.cli bootstrap           # ADMIN + COMPLIANCE from .env
python -m app.modules.onboarding.sample_data                  # the §3.9 companies
python -m uvicorn app.main:app

cd ../frontend && pnpm build && pnpm exec vite preview       # http://localhost:4173
```

**Run the production build** (`pnpm build && pnpm exec vite preview`), which proxies
`/api` to the backend exactly as the dev server does. The dev server (`pnpm dev`,
`http://localhost:5173`) also works: React's StrictMode runs the sign-in check twice
there, which used to sign people out on a reload, and no longer does (one refresh is
shared, and tabs take turns). It is still slower and noisier than the build. Opening
several tabs at once is safe; reloading several times within a second can still sign
you out (a reload that lands while a token refresh is answering — `open-items.md`
§1.2), so reload once and let the page settle.

**Logins.** Have one per role you will show: the ADMIN and COMPLIANCE users from
`bootstrap`, plus an OPERATIONS user (create it from Settings as ADMIN, or sign up and
run `python -m app.platform.authentication.cli promote <email> OPERATIONS`). A
DEVELOPER login is useful to show read-only access and masking. **Use real-looking
addresses** (`ops@example.com`), never a special-use domain such as `.local` or
`.test`: the sign-in form refuses those, and `bootstrap` and `promote` now refuse them
too rather than create an account that can never sign in. Give each account a full
name (Settings → Users; `bootstrap` creates its two without one, and those show by
email) — History, decisions and activities show who acted by name.

**Have a harmless file ready** to upload (a sample PDF). Never upload a real
exporter's documents — see §6.

## 2. The screens

| Screen | Where |
|---|---|
| Home — overdue follow-ups, check-backs due, counts per journey stage | `/` |
| Companies (tabs by journey), add, CSV import, RXIL intake (ADMIN) | `/companies`, `/companies/new`, `/companies/import`, `/companies/rxil-intake` |
| A company — Overview, Qualification, Conversation, Deals, Documents, Background check, History | `/companies/:id` |
| A deal — stage, buyer, paperwork, history | `/deals/:id` |
| Follow-ups, Pipeline | `/follow-ups`, `/pipeline` |
| Qualification criteria (ADMIN); users and roles | `/settings/qualification-criteria`, `/settings` |

## 3. Tour the sample companies (architecture §3.9)

1. **Company B — Bharat Precision Metals.** A **customer**: qualified, its background
   check `CLEAR` at low risk, two GSTINs. On its Deals tab, the Hamburg order is
   **handed over** and the Rotterdam shipment is still gathering paperwork. Open the
   handed-over deal and its history; open the company's History tab to show the whole
   story in one place, including the journey's move to `CUSTOMER`.
2. **Company C — Coastal Seafood Exports.** A **prospect** whose check is **`FLAGGED`**
   (a failed screening item for suspicious bank indicators). Its Dubai deal is gathering
   paperwork with its buyer recorded, but is **not ready to hand over**, and the deal page
   names both reasons: the company is a `PROSPECT`, not a `CUSTOMER`, and its check is
   `FLAGGED`, not `CLEAR`.
3. **Company A — Aarav Textiles.** A prospect who said **"not now"**: the conversation is
   `NOT_NOW` with a check-back date, which shows on Home and the Follow-ups screen.
4. **D** (not qualified, and **paused**), **E** (**ended** — hidden from the default list,
   still found by searching), **F** (a new lead with no PAN) and **G** (shares B's GSTIN,
   so it carries a duplicate warning — a GSTIN duplicate warns, a PAN duplicate is
   refused).

## 4. The main path, live (architecture §4.1)

As **OPERATIONS** unless noted.

1. **Add a lead.** Companies → add a company with a name, country, PAN and GSTIN. It
   starts as a `LEAD`. Adding a second company with the same PAN is refused; the same
   GSTIN only warns. *(Also available: CSV import, and RXIL intake as ADMIN — an RXIL
   company arrives already qualified.)*
2. **No deal yet.** A lead has no "Open a deal" action: the server refuses a deal to a
   company that has not been qualified.
3. **Qualify.** On the Qualification tab, record a result for each criterion with
   evidence; the screen shows the server's suggestion; record the outcome **QUALIFIED**.
   The journey moves to **`PROSPECT`**.
4. **Talk to them.** On the Conversation tab, move the gauge (for example
   `INTERESTED`). Log a call or a follow-up with a due date.
5. **Open a deal.** At `READY_NOW` the Conversation tab offers to open a deal (or use
   the Deals tab — opening one sets `READY_NOW` itself). On the deal page, record the
   buyer and move it to **gathering paperwork**.
6. **Paperwork.** Upload the sample file to the deal. It is scanned before it can be
   opened; the scanner is labelled **pass-through** because it is a placeholder.
7. **Start the background check** on the company's Background check tab (OPERATIONS
   may start one).
8. **Switch to COMPLIANCE.** Answer the seven screening items; optionally record a
   manual verification result with a note as evidence (a document can be evidence too,
   but only one uploaded to the company's own Documents tab — deal paperwork belongs to
   the deal). The `CLEAR` move lists any prerequisite still unmet until they are all
   met.

   On the deal page, COMPLIANCE can also record a **buyer check** (for example a
   `FAILED` sanctions check with a note; the buyer check types are Buyer, KYB, Company
   registry, Sanctions, AML, PEP and Adverse media): it is recorded against the buyer
   and never changes the company's background check (decision 9).

   **Say plainly: a failed buyer check does not block the deal's handover.** The
   handover guard (assumption A5) looks only at the company — a `CUSTOMER` whose check
   is `CLEAR` — and buyer checks never touch the company. Whether a `FAILED` sanctions
   or AML result on the buyer should block handover is an open business question
   ([`open-items.md`](open-items.md) §1.2).
9. **Record `CLEAR`** with a reason and a risk rating. The company becomes a
   **`CUSTOMER`** in the same step — show the journey on the company header, which
   changes without a reload — and
   "became customer" is announced to the customers team's event (nobody receives it
   yet; §6).
10. **Hand over the deal** (back as OPERATIONS): the move is now offered; confirm it.
    The deal is **`HANDED_OVER`**, its paperwork snapshot is fixed, and "deal handed
    over" is announced for the lending team.
11. **Show the History tab**: qualification, journey, conversation, deal, screening and
    background-check rows, each with who (by name) and why. A row about one thing of
    several names it — "Buyer recorded: …", the screening item's label, the
    criterion's label, the check type.

## 5. Other paths (architecture §4.2)

- **A lead fails qualification:** record **NOT_QUALIFIED** with a reason code; it stays
  a lead, and can be re-reviewed later with new results.
- **"Interested, but not now":** set the conversation to `NOT_NOW` with a check-back
  date; it appears on Follow-ups.
- **Compliance needs more:** move the check to `MORE_INFO` with a note of what is
  needed; staff answer it back to `IN_REVIEW` with a note of what arrived.
- **New information about a customer:** as COMPLIANCE, **reopen** company B
  (`CLEAR` → `IN_REVIEW`, with a reason), then **flag** it. B stays a **customer**, but
  its Rotterdam deal can no longer be handed over. Reassess and clear it again — it is
  not announced as a new customer twice.
- **A deal falls through:** withdraw it with a reason; the company is untouched.
- **Pausing or ending a relationship:** set the marker with a reason; the journey is
  unchanged, and it can be cleared again.
- **Roles and masking:** log in as OPERATIONS and then COMPLIANCE on the same company —
  PAN and GSTIN are masked for OPERATIONS and shown in full to COMPLIANCE. As DEVELOPER
  the CRM is read-only, identifiers are masked, and the background check is not shown
  at all.

## 6. Say this plainly during the demo

Everything below is labelled on screen or in the data; say it anyway.

- **The scanner is a pass-through and storage is local disk.** Real documents need a
  real scanner and S3 with Object Lock and KMS first (architecture §7.6).
- **Checks are recorded by hand.** Middesk, Trulioo and Sumsub are not connected; an
  "RXIL stub" result is a placeholder, not RXIL; the bank-activity panel says no feed is
  connected.
- **"Became customer" and "deal handed over" are announced, but no other team receives
  them yet.**

Avoid:

- uploading real exporter documents;
- presenting role and permission editing in Settings as controlling CRM access — the CRM
  still checks the five built-in roles;
- relying on the order of two history rows made in the same step — both are there, but
  the log does not order them between themselves.
