# Demonstrating the Exporter CRM

A walk-through of the CRM on sample data, then the main path live on a new company,
then the other paths. Every step below was walked in the redesigned UI on 5 October
2026, on a copy of the clean demo database, as the role named
([`remaining-work.md`](remaining-work.md) §13). [`architecture.md`](architecture.md)
explains the rules behind each step.

---

## 1. Before the demo

**Use a fresh database.** The database the test suite runs against collects thousands
of test companies, some in states the product cannot produce (tests set them up
directly). A demo on it shows noise and impossible records, and so does a demo
database somebody rehearsed on. Rebuild it from empty, and never run the test suite
against it.

On this machine the demo database is `crm_demo` on the `aner-postgres` container
(port 5433); the backend on `:8000` and the preview on `:4173` serve it. To rebuild
it, with `DATABASE_URL` **and** `DATABASE_SYNC_URL` pointing at a new, empty database
(alembic reads the second):

```bash
cd backend
python -m alembic upgrade head
python -m app.modules.onboarding.sample_data                  # the §3 companies
python -m uvicorn app.main:app --port 8000

cd ../frontend
pnpm install --frozen-lockfile                               # the redesign added packages
pnpm build && pnpm exec vite preview --port 4173 --strictPort  # http://localhost:4173
```

**Restart the preview after every build.** `vite preview` reads the list of built
files when it starts, so a preview left running across a rebuild serves an
`index.html` whose assets it does not know.

**Run the production build**, which proxies `/api` to the backend exactly as the dev
server does. Opening several tabs at once is safe; reloading several times within a
second can still sign you out (a reload that lands while a token refresh is answering
— R-49 in `remaining-work.md`), so reload once and let the page settle.

**Logins.** One per role you will show. `crm_demo` has five, each with a full name
(history, decisions and activities show who acted by name); the passwords are in
`C:/Users/ArshadMughal/crm_demo_accounts.txt`, never in this file.

| Account | Role | Used for |
|---|---|---|
| `rm@aner.com` (Relationship Manager) | OPERATIONS | the main path |
| `compliance@aner.com` (Compliance Officer) | COMPLIANCE | screening, checks, proposing |
| `compliance2@aner.com` (Compliance Approver) | COMPLIANCE | the second signature |
| `admin@aner.com` (Admin) | ADMIN | settings |
| `dev@aner.com` (Developer) | DEVELOPER | read-only and masking |

A new account must use a real-looking address (`ops@example.com`), never `.local` or
`.test`: the sign-in form refuses those, and so do `bootstrap` and `promote`.

**Have a harmless file ready** to upload (a sample PDF). Never upload a real
exporter's documents — see §6.

## 2. The screens

| Screen | Where |
|---|---|
| **Desk** — greeting, *Up next* (mine / team), pipeline counts, *Re-KYC due*; for a compliance officer *Awaiting your signature* | `/` |
| **Companies** — list, or the **board** by journey stage (`/pipeline` opens it); *Add company*, CSV import, RXIL intake (ADMIN) | `/companies`, `/companies?view=board`, `/companies/new`, `/companies/import`, `/companies/rxil-intake` |
| **A company** — hero standing (journey, qualification, conversation, background check) and the chapters *Profile*, *Qualification*, *Conversation*, *Deals & trade*, *Documents*, *Background check*, *Ledger* | `/companies/:id` (`?tab=` selects a chapter) |
| **A deal** — *Stage*, *Parties* (seller, invoicing branch, buyer), *Trade between these two*, *Paperwork*, *What was handed over*, *Ledger* | `/deals/:id` |
| **Agenda** — follow-ups and check-backs due | `/follow-ups` |
| **Review** — the compliance working day (COMPLIANCE, ADMIN) | `/review` |
| **Settings** — your profile for everyone; users, roles, *Qualification criteria* and *Required documents* for ADMIN | `/settings/profile`, `/settings/users`, `/settings/roles`, `/settings/qualification-criteria`, `/settings/deal-required-documents` |

**Find…** (`Ctrl K`) jumps to any company or screen. An address a role may not use
shows the same **"Nothing here."** as an address that does not exist.

## 3. Tour the sample companies (architecture §3.9)

1. **Company B — Bharat Precision Metals Ltd.** A **customer**: qualified, its
   background check `CLEAR` at low risk, two GST branches. On *Deals & trade*, the
   Hamburg order is **handed over** and the Rotterdam shipment is still gathering
   paperwork. Open the handed-over deal: *What was handed over* shows the buyer and
   paperwork as they stood. Open the company's *Ledger* to show the whole story in
   one place, including the journey's move to `CUSTOMER`.

   The Rotterdam shipment is not ready to hand over even though B is a customer: it
   has no pre-shipment document, and its buyer's sanctions and AML have not been
   checked. The sample data is written by the platform, not by a person, so its
   ledger rows read "By the platform" and its proposal and decision read
   `sample-data` and `sample-data-checker`. Everything done live in §4 shows the
   signed-in person's name.

   The sample deals record their buyer the **legacy** way, as details on the deal rather
   than as a company record. Their deal pages show a *Legacy buyer record — kept until
   this deal's buyer is a company (P4-10)* panel with **Buyer checks**, and no *Trade
   between these two*. That is the honest state of a database the buyer migration has
   not run on; say it out loud. The live path in §4 records a buyer **company** and the
   trade panel appears there.
2. **Company C — Coastal Seafood Exports Pvt Ltd.** A **prospect** whose check is
   **`FLAGGED`** (a failed screening item for suspicious bank indicators). Its Dubai
   deal is gathering paperwork with its buyer recorded, but is **not ready to hand
   over**, and the deal page names every reason: the company is a `PROSPECT`, not a
   `CUSTOMER`; its check is `FLAGGED`, not `CLEAR`; the deal has no pre-shipment
   document; and the buyer's sanctions and AML checks are `MISSING`, not `PASSED`.
3. **Company A — Aarav Textiles Pvt Ltd.** A prospect who said **"not now"**: the
   conversation is `NOT_NOW` with a check-back date, which shows on the Agenda.
4. **D** Deccan Leather Works (not qualified, and **paused**), **E** Eastern Spice
   Traders (**ended** — hidden from the default list, still found by searching), **F**
   Falcon Agro Exports (a new lead with no PAN, listed under *Identity to complete*)
   and **G** Bharat Metals (Pune office) (shares B's GSTIN, so it carries a duplicate
   warning — a GSTIN duplicate warns, a PAN duplicate is refused).

## 4. The main path, live (architecture §4.1)

As **OPERATIONS** (`rm@aner.com`) unless noted.

1. **Add a lead.** Desk → **Add company**. Type a PAN under *Start with an
   identifier*, then *Company name* and *Country* (`IN`) → **Create lead**. It starts
   as a `LEAD`. On *Profile* → *GST registrations*, **Add registration** with a GSTIN
   carrying the same PAN (`27` + PAN + `1Z5` is Maharashtra) → **Add**; the state comes
   from the GSTIN. Adding a second company with the same PAN is refused; the same
   GSTIN only warns. *(Also available: CSV import, and RXIL intake as ADMIN — an RXIL
   company arrives already qualified.)*
2. **No deal yet.** A lead has no **Open a deal**: the server refuses a deal to a
   company that has not been qualified.
3. **Qualify.** *Qualification*: for the two required criteria (*Annual revenue*,
   *Years in business*) press **Pass**, fill the observed value and the evidence, then
   **Record 2 results**. The header shows the server's suggestion. **Record: Qualified**
   → a note → **Confirm**. The journey moves to **`PROSPECT`** (the hero updates). The
   person decides: recording the opposite of the suggestion is allowed and is kept
   with the suggestion it overrode.
4. **Talk to them.** *Conversation*: press **Interested** → **Confirm**. **Log an
   activity** for a call or a follow-up with a due date.
5. **Open a deal.** *Deals & trade* → **Open a deal** → a *Reference* → **Open deal**.
   Opening a deal sets the conversation to **Ready now** in the same step (the toast
   says so). Open the deal and press **Start gathering paperwork**.

   **The buyer is a company record, not a set of details.** Press **Choose buyer
   company**. Type the buyer's name under *Find the company* and **press Enter** (or
   use **Search by identifier** for a full PAN, GSTIN or registration number → **Look
   up**). The picker looks for a company we already hold before it offers to create
   one, which is what stops a second record for the same company; pick one we hold
   with **Select**.

   For a buyer that is **genuinely new**, the answer is "No company on file matches"
   and the picker offers **Create buyer company**. Set *Country (ISO code)* to the
   buyer's country (for example `DE`): a foreign buyer needs its **Registration
   number**, and the button stays unavailable until it is filled (IQ-7); an Indian
   buyer is asked for a PAN or GSTIN instead. **Create buyer company** creates the
   company and names it as this deal's buyer **in one step**, and records the **trade
   relationship** between the two companies (*Trade between these two* appears). Show
   what it did *not* do: the new company is **not in the pipeline** — no lead, no
   journey, the board's counts unchanged — and the deal's *Ledger* says "Created as a
   deal's buyer: not in the pipeline".

   Show the refusals too. A name that only *looks like* one on file gives **Check these
   first** with the look-alikes and nothing preselected; "None of these is the buyer?"
   still lets you create it, because a name is never an identity (IQ-8). An identifier
   that already belongs to a company is refused in the server's words, and the form
   offers **Use the company on file** rather than a second record.

   The buyer company is **set once**: the picker disappears afterwards ("Chosen once —
   a deal pointed at the wrong buyer is withdrawn and reopened").
6. **Paperwork.** **Upload a document** → *Category* **Pre Shipment**, *Type*
   **Proforma invoice**, the sample file → **Upload**. It is scanned before it can be
   opened; the scanner is labelled **pass-through** because it is a placeholder. Before
   the upload the deal says `missing required documents: PRE_SHIPMENT`: a handover
   needs a scanned-clean pre-shipment document (IQ-10, IQ-11), and ADMIN changes which
   categories are required under **Settings → Required documents**.
7. **Record the invoicing branch** in the deal's *Parties* panel, under **Invoiced
   from**. Until a branch is chosen the panel says **Not recorded** — the seller has an
   active GST registration, so a handover asks which one. Each active registration is
   listed by its state and its GSTIN as the server sends it (masked for OPERATIONS);
   choosing records it at once (toast "Invoiced from …"). **Clear** removes the choice
   until the deal closes.
8. **Start the background check** on the company's *Background check* chapter: press
   **In review** → **Record decision** (OPERATIONS may start one).
9. **Switch to COMPLIANCE** (`compliance@aner.com`). On *Background check*:
   - *Review checklist*: set each of the seven items to **Passed** (or **Exempt** for
     the two exception questions) and **Save** each.
   - **Record a result** three times — *Check* **Kyb**, **Aml**, **Sanctions**, *Outcome*
     **Passed**, an *Evidence note* → **Record check**. *Required for Clear (this cycle)*
     turns to *KYB: Passed · AML: Passed · Sanctions: Passed* (rule B).
   - **Propose Clear** → *Risk rating* `LOW` and a reason → **Propose for approval**.
     Nothing moves yet: the hero shows **Awaiting approval**; the proposer can only
     withdraw it.
10. **The second signature.** Sign in as `compliance2@aner.com`. The Desk shows
    **Awaiting your signature 1** → **Approve** → **Approve** (two clicks; also on
    *Review*). On approval the company becomes a **`CUSTOMER`** in the same step — show
    the hero — the decision names both people, the Clear shows when it expires (one
    year), and "became customer" is announced (nobody receives it yet; §6). The
    proposer cannot approve their own proposal.
11. **Screen the buyer** (still COMPLIANCE). On the deal, the buyer's card shows
    *Sanctions: Not checked · AML: Not checked* and **Open the background check**. On
    the buyer company's *Background check*, **Record a result** for **Sanctions** and
    **Aml**, both **Passed**. A buyer's checks attach to the buyer and never change the
    seller's check (decision 9); the handover needs both `PASSED` (BQ-4), so a buyer
    nobody screened reads `MISSING` and blocks — show that refusal first if you want.
12. **Hand over** (back as OPERATIONS). The deal now offers **Hand over to lending** →
    **Hand over**. The deal is **`HANDED_OVER`**, "deal handed over" is announced for the
    lending team, and *What was handed over* shows the buyer and the paperwork as they
    stood, kept on the deal and never changed afterwards. The invoicing branch is now
    frozen with the deal.
13. **Record how it was paid.** **Record outcome**: *What happened* (`Paid`, `Part paid`,
    `Unpaid`, `Disputed` or `Not known`), *Proof* (claimed or proven), and — because the
    deal has no invoice yet — *Invoice number*, *Invoice date*, *Amount* and *Currency*
    together → **Record outcome**. Three things worth saying:

    - **This is not a deal stage.** The deal is closed; what happened to the money is a
      fact about the trade, recorded against the invoice (architecture §3.3).
    - **`Not known` is an answer and "no outcome recorded" is not.** A **Claimed** chip
      says nobody has shown proof yet, which is deliberately not the same as `Paid`.
    - **Nothing is totalled.** Each row carries its own amount *and* currency, and there
      is no total anywhere (IQ-4). A *past* invoice — trade from before either company
      came to us — is recorded on the seller's *Deals & trade* chapter under *Trade —
      sold to*.

    Then correct it: record a new outcome; the first stays under **Outcome history**,
    marked superseded.
14. **Show the Ledger** — on the deal and on the company. Each row says what changed
    and who did it: "Buyer company recorded: …", "Invoicing branch recorded:
    Maharashtra", "Invoice … recorded: 48250.00 EUR", "Payment outcome recorded: Paid
    (claimed)", "Branch added: Maharashtra", the screening item's question, the
    criterion, the check type. Rows written in one step are grouped as "Same moment".

## 5. Other paths (architecture §4.2)

- **A lead fails qualification:** **Record: Not qualified** with a reason code; it
  stays a lead and can be re-reviewed later with new results.
- **"Interested, but not now":** *Conversation* → **Not now** with a check-back date;
  it appears on the Agenda.
- **Compliance needs more:** **More information needed** with a note of what is
  needed; staff answer it back to **In review** with a note of what arrived.
- **A flagged branch** (COMPLIANCE, company B's *Profile* → *GST registrations*):
  **Flag** → a reason → **Flag branch**. It blocks only the deals invoiced through
  *that* branch — open the Rotterdam shipment: the refusal names the flagged state and
  the picker marks it "— flagged"; choosing B's other branch removes that reason.
- **A deactivated branch blocks too** (R-19, decided 4 October). Record a branch on a
  deal, then **Deactivate** that registration on the seller's *Profile*: the deal says
  "the invoicing branch … is deactivated", the picker shows it as "— deactivated", and
  choosing an active branch clears it.
- **New information about a customer:** as COMPLIANCE, reopen company B (**Record a
  decision** → back to *In review*, with a reason), then **Propose Flagged**, which a
  second officer approves. B stays a **customer**, but its Rotterdam deal's refusal
  now also says the background check is `FLAGGED`, not `CLEAR`. Reassess and clear it
  again — it is not announced as a new customer twice. **Start Re-KYC** / **Start
  Re-KYB** opens a new check cycle the same way.
- **A deal falls through:** **Withdraw** with a reason; the company is untouched.
- **Pausing or ending a relationship:** **Pause relationship** / **End relationship**
  with a reason; the journey is unchanged, and it can be cleared again.
- **Roles and masking:** open the same company as OPERATIONS and then COMPLIANCE —
  PAN and GSTIN are masked for OPERATIONS and shown in full (with reveal and copy) to
  COMPLIANCE. As DEVELOPER the CRM is read-only, identifiers are masked, and the
  background check is not shown at all; **branch flags are not shown either** (R-47):
  no flag chip, no flag count, no flag rows in the Ledger. Companies has no **Add
  company** or **Import**, and typing `/companies/new` gives the same "Nothing here."
  as an address that does not exist. Only ADMIN sees **Qualification criteria** and
  **Required documents** in Settings, and only COMPLIANCE and ADMIN see **Review**. An
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
- **The sample deals' buyers are legacy records** until the buyer migration (P4-6) runs.

Avoid:

- uploading real exporter documents;
- presenting role and permission editing in Settings as controlling CRM access — the CRM
  still checks the five built-in roles;
- relying on the order of two ledger rows made in the same step — both are there,
  grouped as "Same moment", but not ordered between themselves;
- reloading repeatedly in quick succession (R-49).
