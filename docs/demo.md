# Demonstrating the Exporter CRM

A walk-through of the CRM on sample data, then the main path live on a new company,
then the other paths. It follows the original design's §4 paths and what the system does
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

   The sample deals record their buyer the **legacy** way, as details on the deal rather
   than as a company record, so these deals show no Trade history panel and the Deals
   tab's *Sold to* reads "nobody recorded as a buyer from this company yet". That is the
   honest state of a database the buyer migration has not run on, and it is worth saying
   out loud rather than explaining away: the live path in §4 records a buyer **company**
   and the panel appears there.
2. **Company C — Coastal Seafood Exports.** A **prospect** whose check is **`FLAGGED`**
   (a failed screening item for suspicious bank indicators). Its Dubai deal is gathering
   paperwork with its buyer recorded, but is **not ready to hand over**, and the deal page
   names every reason: the company is a `PROSPECT`, not a `CUSTOMER`, its check is
   `FLAGGED`, not `CLEAR`, and the deal has no pre-shipment document yet.
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

   **The buyer is a company record, not a set of details** (task 2.4). Press **Choose
   buyer company** and search by name, or by a full PAN, GSTIN or registration number
   under **Search by identifier**: the picker looks for a company we already hold before
   it offers to create one, which is what stops a second record for the same company.
   Pick a buyer we hold with **Select**.

   For a buyer that is **genuinely new**, the server answers "No company on file
   matches" and the picker offers **Create buyer company** (R-24). The form asks only
   what identifies the company: a name, a country, and for a foreign buyer its
   **registration number**, which is required (IQ-7) — the button stays unavailable
   until it is filled; an Indian buyer is asked for a PAN or GSTIN instead. The number
   you searched with is already filled in. **Create buyer company** creates the
   company and names it as this deal's buyer **in one step**. Show what it did *not*
   do: the new company is **not in the pipeline** — it is no lead, has no journey, and
   the Pipeline board is unchanged — and its page says it exists because it was the
   buyer on a deal.

   Show the two refusals too. Searching by a name that only *looks like* one on file
   gives **Check these first** with the look-alikes and nothing preselected; "None of
   these is the buyer?" still lets you create it, because a name is never an identity
   (IQ-8). Typing an identifier that already belongs to a company instead is refused
   in the server's words ("already known"), and the form offers **Use the company on
   file** rather than a second record.

   The buyer company is **set once**: show that the picker disappears afterwards and
   that the only correction is to withdraw the deal and open another, so the change
   leaves a trail. Recording the buyer also creates the **trade relationship** between
   the two companies, in the same step.
6. **Paperwork.** Upload the sample file to the deal in the **Pre-shipment** category
   (for example a proforma invoice). It is scanned before it can be opened; the scanner
   is labelled **pass-through** because it is a placeholder. Before the upload the deal
   page says `missing required documents: PRE_SHIPMENT`: a handover needs a scanned-clean
   pre-shipment document (IQ-10, IQ-11), and ADMIN changes which categories are required
   under **Settings → Required documents**. A file in another category does not count.
7. **Start the background check** on the company's Background check tab (OPERATIONS
   may start one).
8. **Switch to COMPLIANCE.** Answer the seven screening items and record manual
   **KYB, AML and Sanctions** results as `PASSED`, each with a note as evidence — a
   Clear needs all three passed in the current cycle (rule B; the panel lists them
   under "Required for Clear"). A document can be evidence too, but only one uploaded to
   the company's own Documents tab — deal paperwork belongs to the deal. The `CLEAR`
   move lists any prerequisite still unmet until they are all met.

   On the deal page, COMPLIANCE can also record a **buyer check** (for example a
   `FAILED` sanctions check with a note; the buyer check types are Buyer, KYB, Company
   registry, Sanctions, AML, PEP and Adverse media): it is recorded against the buyer
   and never changes the company's background check (decision 9).

   **The buyer's checks now do decide.** Decision BQ-4 was answered yes, and the
   handover guard reads it since task 2.5: the buyer's sanctions **and** AML must both
   be `PASSED`. A buyer nobody has screened reads `MISSING`, which is why the guard
   says `PASSED` rather than "not `FAILED`" — so screen the buyer before trying the
   handover, and show the refusal first if you want to demonstrate it. A failed buyer
   check still never changes the *company's* background check (decision 9): it is
   recorded against the buyer, and only the handover reads it.
9. **Propose `CLEAR`** with a reason and a risk rating (maker-checker, decision A).
   Nothing moves yet: the check shows **Awaiting approval**, and the proposer can only
   withdraw it. **Sign in as a second officer** — the ADMIN account `bootstrap` made, or
   another COMPLIANCE user — and approve it from Home (**Proposals awaiting me** →
   Approve → Approve: two clicks) or from the company's Background check tab. On
   approval the company becomes a **`CUSTOMER`** in the same step — show the journey on
   the company header — the decision trail names both people, the Clear shows when it
   expires (one year), and "became customer" is announced to the customers team's
   event (nobody receives it yet; §6).
10. **Record the invoicing branch** (back as OPERATIONS), in the deal page's
    **Invoicing branch** panel. Until a branch is chosen the panel says **Not
    recorded** — the seller has an active GST registration, so a handover asks which
    one — and the stage panel's refusal includes "the invoicing branch is not
    recorded" (task 2.9; the company added in step 1 has one). Choose under **Invoiced
    from**: each active registration is listed by its state and its GSTIN as the server
    sends it — masked for OPERATIONS, in full for COMPLIANCE and ADMIN — and a flagged
    one is marked "— flagged". Choosing records it at once (a toast says "Invoiced from
    …"); there is no separate save. **Clear** removes the choice, and a different branch
    can be chosen, until the deal closes. After the handover the panel is read-only and
    says the branch is **frozen with the deal**. A seller with no active registration
    is not asked, and the panel says so instead of offering a choice.

    Worth showing alongside **flagging a branch** as COMPLIANCE (company B's Overview
    tab → GST registrations): a flagged branch blocks the deals invoiced through *that*
    branch and leaves the company's other branch working, which is the point of
    flagging a branch rather than a company. Company B's sample deals already have a
    branch, recorded by the sample data; flag that one and open the Rotterdam shipment —
    the refusal names the flagged state, the panel marks the branch **Flagged**, and
    choosing B's other branch removes that reason.
11. **Hand over the deal**: the move is now offered; confirm it.
    The deal is **`HANDED_OVER`**, and "deal handed over" is announced for the lending
    team. The deal page now shows **What was handed over**: the buyer and the paperwork
    as they stood at that moment, kept on the deal and never changed afterwards.
12. **Record how it was paid.** Still on the deal page, after the handover: **Record
    outcome** creates the deal's invoice if it has none — number, date, amount and
    currency together — and records what happened to it (`PAID`, `PARTIAL`, `UNPAID`,
    `DISPUTED` or **`UNKNOWN`**), with a note or a document as proof.

    Three things worth saying while it is on screen:

    - **This is not a deal stage.** The deal is already closed and stays closed;
      what happened to the money afterwards is a fact about the trade, recorded against
      the invoice (architecture §3.3).
    - **`UNKNOWN` is an answer and "no outcome recorded" is not.** The panel keeps them
      apart on purpose: the first means somebody looked and could not say, the second
      that nobody has followed it up. A chip reading **Claimed** says nobody has shown
      proof yet, which is deliberately not the same as `PAID`.
    - **Nothing is totalled.** Each row carries its own amount *and* its own currency,
      and there is no total anywhere — no reporting currency and no rate exist (IQ-4),
      so a total across currencies would be a number nobody could defend. (The deal
      page records the deal's own invoice. A *past* invoice — trade from before either
      company came to us, which is how a second currency appears — is recorded on the
      seller's Deals tab: **Record past invoice** on the buyer's row under *Sold to*,
      with an outcome if anybody knows it, "claimed" unless proof has been seen. It
      records no deal.)

    Then correct it: record a *new* outcome superseding the first. The old one stays
    visible under **Outcome history**, marked superseded, because an invoice corrected
    from `PAID` to `DISPUTED` is a different thing from one disputed from the start.

    **Trade history** now shows on the deal page as "Seller → Buyer" with the invoice
    beneath it, and on both companies' **Deals** tab under *Sold to* and *Bought from* —
    the same relationship read from each side, which is the point of a company record
    being one record whichever side of a trade it is on.
13. **Show the History tab**: qualification, journey, conversation, deal, GST
    registration, trade, screening and background-check rows, each with who (by name)
    and why. A row about one thing of
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
  (`CLEAR` → `IN_REVIEW`, with a reason), then **propose a flag**, which a second officer
  approves (a flag, like a Clear or a hold, takes two people). B stays a **customer**, but
  its Rotterdam deal can no longer be handed over. Reassess and clear it again — it is
  not announced as a new customer twice.
- **A deal falls through:** withdraw it with a reason; the company is untouched.
- **Pausing or ending a relationship:** set the marker with a reason; the journey is
  unchanged, and it can be cleared again.
- **Roles and masking:** log in as OPERATIONS and then COMPLIANCE on the same company —
  PAN and GSTIN are masked for OPERATIONS and shown in full to COMPLIANCE. As DEVELOPER
  the CRM is read-only, identifiers are masked, and the background check is not shown
  at all: Companies has no **Add company** or **Import CSV**, and typing
  `/companies/new` gives the same "Page not found" as an address that does not exist.
  Only ADMIN sees **Qualification criteria** and **Required documents** in the rail; for
  anyone else those addresses are "Page not found" too, never "Administrators only". An
  API user signing in gets no workspace at all: no rail, a short "ask an administrator"
  page, and only My profile.

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
