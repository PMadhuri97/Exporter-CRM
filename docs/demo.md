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

On this machine the one CRM database is `aner_settlement` on the `aner-postgres`
container (port 5433), rebuilt clean on 5 October 2026; `backend/.env` points at it, so
a plain start of the backend on `:8000` serves it. **Do not run the test suite against
it** — create a throwaway database for that. To rebuild it, with `DATABASE_URL` **and**
`DATABASE_SYNC_URL` pointing at a new, empty database (alembic reads the second):

```bash
cd backend
python -m alembic upgrade head
python -m app.modules.onboarding.sample_data                  # the §3 companies
python -m uvicorn app.main:app --port 8000                     # add --reload only off-demo

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

**Logins.** One per role you will show. `aner_settlement` has one per role and two
COMPLIANCE (maker-checker needs the second), each with a full name (history, decisions
and activities show who acted by name); the passwords are in
`C:/Users/ArshadMughal/crm_demo_accounts.txt`, never in this file. After a rebuild,
copy the `auth.users` rows across (their hashes keep the passwords) or create the
accounts again.

| Account | Role | Used for |
|---|---|---|
| `rm@aner.com` (Relationship Manager) | OPERATIONS | the main path |
| `compliance@aner.com` (Compliance Officer) | COMPLIANCE | screening, checks, proposing |
| `compliance2@aner.com` (Compliance Approver) | COMPLIANCE, permission role **Compliance lead** | the second signature, high-risk approvals, assigning reviews |
| `admin@aner.com` (Admin) | ADMIN | users, roles and settings; reads the business but changes none of it |
| `dev@aner.com` (Developer) | DEVELOPER | read-only and masking |
| `apiuser@aner.com` (API User) | API_USER | "no workspace" — reaches nothing in the CRM |

A new account must use a real-looking address (`ops@example.com`), never `.local` or
`.test`: the sign-in form refuses those, and so do `bootstrap` and `promote`.

**The administrator does not work the business.** `admin@aner.com` can open every
company and deal but has no button that creates, edits, decides or approves anything,
sees tax IDs masked, and cannot download documents. Senior work comes from the two
seeded lead roles: give `compliance2@aner.com` the **Compliance lead** permission role
(Settings → Users → edit → *Permission role*), and an RM who assigns RMs the **Sales
lead** role. Someone who does both jobs uses two accounts.

**Have a harmless file ready** to upload (a sample PDF). Never upload a real
exporter's documents — see §6.

## 2. The screens

| Screen | Where |
|---|---|
| **Home** — *My follow-ups* (mine / team, with *Mark done*), *Check back on*, pipeline counts, *Re-KYC due*, recent companies; for a compliance officer *Items to approve* first | `/` |
| **Companies** — the list, or **Pipeline** (the board by journey stage; `/pipeline` opens it); *New company* (a side panel), *Import companies*, RXIL intake (COMPLIANCE) | `/companies`, `/companies?view=board`, `/companies/new`, `/companies/import`, `/companies/rxil-intake` |
| **A company** — the record header (key fields, the actions the server allows, the journey path), the tabs *Details*, *Qualification*, *Activity*, *Deals*, *Documents*, *Background check*, *History*, and related records on the right | `/companies/:id` (`?tab=` selects a tab) |
| **A deal** — the record header (stage, *Hand over to lending*, *Withdraw*), *Handover readiness*, the seller and buyer cards, *Trade between these two*, *Paperwork*, *What was handed over*, *History* | `/deals/:id` |
| **Follow-ups** — follow-ups by due date, and check-backs due | `/follow-ups` |
| **Compliance work** — the compliance working day: awaiting review, my reviews, awaiting my signature, Re-KYC due, and for a lead everyone's reviews, overdue and needs attention (COMPLIANCE) | `/approvals` (`/review` still works) |
| **Settings** — your profile for everyone; users and roles (each with its change **History**), *Qualification criteria* and *Required documents* for ADMIN | `/settings/profile`, `/settings/users`, `/settings/roles`, `/settings/qualification-criteria`, `/settings/deal-required-documents` |

**Search** in the header (`/` or `Ctrl K`) finds any company or page. An address a role
may not use shows the same **"Page not found"** as an address that does not exist.

## 3. Tour the sample companies (architecture §3.9)

1. **Company B — Bharat Precision Metals Ltd.** A **customer**: qualified, its
   background check `CLEAR` at low risk, two GST branches. On *Deals*, the
   Hamburg order is **handed over** and the Rotterdam shipment is still gathering
   paperwork. Open the handed-over deal: *What was handed over* shows the buyer and
   paperwork as they stood. Open the company's *History* to show the whole story in
   one place, including the journey's move to `CUSTOMER`.

   The Rotterdam shipment is not ready to hand over even though B is a customer: it
   has no pre-shipment document, and its buyer's sanctions and AML have not been
   checked. The sample data is written by the platform, not by a person, so its
   history rows read "By the platform" and its proposal and decision read
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
   conversation is `NOT_NOW` with a check-back date, which shows under *Check back on*.
4. **D** Deccan Leather Works (not qualified, and **paused**), **E** Eastern Spice
   Traders (**ended** — hidden from the default list, still found by searching), **F**
   Falcon Agro Exports (a new lead with no PAN, listed under *Identity to complete*)
   and **G** Bharat Metals (Pune office) (shares B's GSTIN, so it carries a duplicate
   warning — a GSTIN duplicate warns, a PAN duplicate is refused).

## 4. The main path, live (architecture §4.1)

As **OPERATIONS** (`rm@aner.com`) unless noted.

1. **Add a lead.** **+ New** → **New company** (a side panel). Type a PAN under
   *Start with an identifier*, then *Company name* and *Country* (pick **India**) → **Create
   lead**. It starts as a `LEAD`. On *Details* → *GST registrations*, **Add registration** with a GSTIN
   carrying the same PAN (`27` + PAN + `1Z5` is Maharashtra) → **Add**; the state comes
   from the GSTIN. Adding a second company with the same PAN is refused; the same
   GSTIN only warns. *(Also available: bulk import from the Excel template or a CSV,
   and RXIL intake as COMPLIANCE — an RXIL
   company arrives already qualified.)*
2. **No deal yet.** A lead has no **Open a deal**: the server refuses a deal to a
   company that has not been qualified.
3. **Qualify.** *Qualification*: for the two required criteria (*Annual revenue*,
   *Years in business*) press **Pass**, fill the observed value and the evidence, then
   **Record 2 results**. The header shows the server's suggestion. **Record: Qualified**
   → a note → **Confirm**. The company has no relationship manager yet, so the form says
   *you will become its RM*: qualifying makes it yours. The journey moves to
   **`PROSPECT`** (the path updates), *Details* → *Relationship manager* names you, and
   the company is now under **My companies** in the side navigation.
   (On a company with no RM, *Details* also offers **Assign to me** at any time; a
   **Sales lead** sees **Assign**, **Change** and **Clear**, the last two with a reason.) The
   person decides: recording the opposite of the suggestion is allowed and is kept
   with the suggestion it overrode.
4. **Talk to them.** *Activity*: click **Interested** on the path → **Mark as
   current** → **Confirm**. In the composer below, log a **Call**, or add a
   **Follow-up** with a due date (the header's **Log a call** jumps there).
5. **Open a deal.** *Deals* → **Open a deal** → a *Reference* → **Open deal**.
   Opening a deal sets the conversation to **Ready now** in the same step (the toast
   says so). Open the deal and press **Start gathering paperwork**.

   **The buyer is a company record, not a set of details.** Press **Choose buyer
   company**. Type the buyer's name under *Find the company* and **press Enter** (or
   use **Search by identifier** for a full PAN, GSTIN or registration number → **Look
   up**). The picker looks for a company we already hold before it offers to create
   one, which is what stops a second record for the same company; pick one we hold
   with **Select**.

   For a buyer that is **genuinely new**, the answer is "No company on file matches"
   and the picker offers **Create buyer company**. Pick the buyer's *Country* (for
   example **Germany**): a foreign buyer needs its **Registration
   number**, and the button stays unavailable until it is filled (IQ-7); an Indian
   buyer is asked for a PAN or GSTIN instead. **Create buyer company** creates the
   company and names it as this deal's buyer **in one step**, and records the **trade
   relationship** between the two companies (*Trade between these two* appears). Show
   what it did *not* do: the new company is **not in the pipeline** — no lead, no
   journey, the board's counts unchanged — and the deal's *History* says "Created as a
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
   needs a scanned-clean pre-shipment document (IQ-10, IQ-11), and the administrator changes which
   categories are required under **Settings → Required documents**.
7. **Record the invoicing branch** in the deal's *Parties* panel, under **Invoiced
   from**. Until a branch is chosen the panel says **Not recorded** — the seller has an
   active GST registration, so a handover asks which one. Each active registration is
   listed by its state and its GSTIN as the server sends it (masked for OPERATIONS);
   choosing records it at once (toast "Invoiced from …"). **Clear** removes the choice
   until the deal closes.
8. **Start the background check**: the header's **Start background check** (or the
   *Background check* tab) → **In review** → **Record decision** (OPERATIONS may start
   one). The company already has its RM from step 3; on one that does not, the dialog
   asks for one first. The check waits in **Awaiting review**: *Reviewer: Unassigned*.
9. **Switch to COMPLIANCE** (`compliance@aner.com`). The navigation's **Compliance work**
   lists the company under *Awaiting review*; open it and press **Assign to me** (or do
   it on the company's *Background check*, where the reviewer line now names you). Only
   the reviewer may ask for information or propose an outcome. On *Background check*:
   - *Review checklist*: set each of the seven items to **Passed** (or **Exempt** for
     the two exception questions) and **Save** each.
   - **Record a result** three times — *Check* **KYB**, **AML**, **Sanctions**, *Outcome*
     **Passed**, an *Evidence note* → **Record check**. *Required for Clear (this cycle)*
     turns to *KYB: Passed · AML: Passed · Sanctions: Passed* (rule B).
   - **Propose Clear** → *Risk rating* `LOW` and a reason → **Propose for approval**.
     Nothing moves yet: the header shows **Awaiting approval**; the proposer can only
     withdraw it.
10. **The second signature.** Sign in as `compliance2@aner.com`. Home shows
    **Items to approve 1** → **Approve** → **Approve** (two clicks; also on
    *Compliance work*, under *Awaiting your signature*). Neither the proposer, the
    reviewer nor the company's RM can approve; a Clear proposed at `HIGH` or `CRITICAL`
    risk needs a senior approver (`compliance:approve_high_risk`: the **Compliance lead**
    role; the administrator never approves). On approval the company becomes a **`CUSTOMER`** in the same step — show
    the journey path — the decision names both people, the Clear shows when it expires (one
    year), and "became customer" is announced (nobody receives it yet; §6). The
    proposer cannot approve their own proposal.
11. **Screen the buyer** (still COMPLIANCE). On the deal, the buyer's card shows
    *Sanctions: Not checked · AML: Not checked* and **Open the background check**. On
    the buyer company's *Background check*, **Record a result** for **Sanctions** and
    **AML**, both **Passed**. A buyer's checks attach to the buyer and never change the
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
      came to us — is recorded on the seller's *Deals* tab under *Trade —
      sold to*.

    Then correct it: record a new outcome; the first stays under **Outcome history**,
    marked superseded.
14. **Show the History** — on the deal and on the company. Each row says what changed
    and who did it: "Buyer company recorded: …", "Invoicing branch recorded:
    Maharashtra", "Invoice … recorded: 48250.00 EUR", "Payment outcome recorded: Paid
    (claimed)", "Branch added: Maharashtra", the screening item's question, the
    criterion, the check type. Rows written in one step are grouped as "Same moment".

## 5. Other paths (architecture §4.2)

- **A lead fails qualification:** **Record: Not qualified** with a reason code; it
  stays a lead and can be re-reviewed later with new results.
- **"Interested, but not now":** *Activity* → **Not now** with a check-back date;
  it appears under *Check back on* on Home and on Follow-ups.
- **Compliance needs more:** **More information needed** with a note of what is
  needed; staff answer it back to **In review** with a note of what arrived.
- **A flagged branch** (COMPLIANCE, company B's *Details* → *GST registrations*):
  **Flag** → a reason → **Flag branch**. It blocks only the deals invoiced through
  *that* branch — open the Rotterdam shipment: the refusal names the flagged state and
  the picker marks it "— flagged"; choosing B's other branch removes that reason.
- **A deactivated branch blocks too** (R-19, decided 4 October). Record a branch on a
  deal, then **Deactivate** that registration on the seller's *Details*: the deal says
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
  no flag badge, no flag count, no flag rows in the History. Companies has no **New
  company** or **Import companies**, there is no **+ New** in the header, and typing
  `/companies/new` gives the same "Page not found"
  as an address that does not exist. Only ADMIN sees **Qualification criteria** and
  **Required documents** in Settings, and only COMPLIANCE sees **Compliance work**. ADMIN
  reads every company and deal with identifiers masked and no write button anywhere. An
  API user signing in gets no workspace at all: no navigation, a short "ask an administrator"
  page, and only My profile.
- **Documents are read on screen:** as an RM, *Documents* → **View document** opens
  the file in the CRM's own viewer — a Word or Excel file arrives as a PDF — with the
  reader's name and the time across every page, and no Download anywhere. As COMPLIANCE
  the same document also has **Download**. Every view and download is in the audit
  trail. (Say it: nothing in a browser stops a screenshot; the watermark makes one
  traceable.)

### 5.1 Contacts and customer details

- **The handover needs someone to reach.** A prospect or customer with no active
  primary contact shows **No primary contact** in its header and on the Companies list
  (filter *Contacts* → *No primary contact*), and its deals list "the company has no
  active primary contact" under *Handover readiness* until one is added. In the main
  path, add a primary contact (*Contacts* → **Add**, *Make this the primary contact*)
  any time before step 12, or the handover is refused.
- **A contact who left** (company → *Contacts* → edit → *Status: Left company* with a
  reason): the contact drops out of the card behind *Show inactive*, stops being
  primary, and the change is in *History*. **Mark verified** stamps today's date;
  after a year the contact shows **Verification due**.
- **Addresses** (*Details* → *Addresses*): add a registered and a shipping address; the
  first of each type is its default. A foreign buyer with no GSTIN can hold one. A GST
  branch with a portal address offers **Create address**. The registered address shows
  beside "Is the registered address a physical business address?" on the background
  check, with **Changed since last Clear** if it was edited after the Clear.
- **Bank accounts** (*Details* → *Bank accounts*): as OPERATIONS, **Propose account**
  (an EEFC account in USD) → *Pending approval*, number shown as `••••5678`. A second
  RM or COMPLIANCE **Approve**s it (the proposer is never offered it) → *Pending
  verification*. COMPLIANCE uploads the cancelled cheque on *Documents*, then
  **Verify** → *Verified* and *Primary*. Only COMPLIANCE sees **Reveal**, and every
  reveal is in the audit trail. COMPLIANCE also sees a **Bank details** tab on
  *Compliance work*.
- **Payment terms** (ADMIN: *Settings* → *Payment terms*): eleven common terms are
  seeded. On a customer's *Details*, set the default to *DA 90 days*; a new deal shows
  it under *Value and terms*. Choosing *LC at sight* there asks why, and the reason is
  on the deal and in its history. The *Deals* list shows each deal's value.
- **Collections owner** (COMPLIANCE or a lead: *Details* → *Collections*): name anyone
  on the staff; *Companies* → *Collections: My collections* lists that person's
  companies, and **Reassign collections** moves a whole book at once.
- **Groups** (company → *Group* tab): **Set parent** → choose the parent and the
  relationship. The tree shows every member's stage, check, risk and open deals.
  Linking the parent under its own subsidiary is refused with a message.

### 5.2 Sanctions screening and automatic answers

- **Record a screening** (COMPLIANCE: company → *Background check* → *Sanctions
  screening* → **Record screening**). The UN and MHA lists are ticked and cannot be
  unticked. Add one possible match on the UN list and save: the standing is *Under
  review*. Open **Matches**, mark it **False positive** with a reason: the run is
  *Passed* and the company's SANCTIONS check passes, which is what the Clear needs
  from sanctions.
- **A true match** needs a second officer: mark a match **True match** — the company
  header shows **Sanctions match**, its deals cannot be handed over, and the match
  appears on *Compliance work → True matches*. A second COMPLIANCE user confirms it
  (*Failed*) or says it is **Not a match** (back to open, flag lifted).
- **A new list version** (ADMIN: *Settings → Sanctions lists* → *Change* the MHA list's
  version date): every company screened before appears on *Compliance work →
  Re-screen due*, with why.
- **Automatic answers** (ADMIN: *Settings → Qualification criteria* → add a yes/no
  criterion "Holds an IEC", *Answer automatically from: IEC check*). Record a passed IEC
  verification on a lead: its Qualification tab shows **Pass** with *Auto · IEC check ·
  today*. A person's later answer stands; the outcome is still recorded by a person.

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
- relying on the order of two history rows made in the same step — both are there,
  grouped as "Same moment", but not ordered between themselves;
- reloading repeatedly in quick succession (R-49).
