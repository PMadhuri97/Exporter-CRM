# From lead to customer — the whole story

How one exporter travels through the Exporter CRM, told in order, with every turning
the road can take. Each act names **who** acts, **what** the system does, and **what it
refuses**.

This is the narrative companion to two documents that already exist:
[`architecture.md`](architecture.md) is the reference — the rules organised by concept —
and [`demo.md`](demo.md) is the click-by-click script. Read this one to understand the
journey; use `demo.md` to drive the screen.

Everything below is what the system does **today**. Where something is simulated rather
than real it is marked ⚠ inline, and §12 collects all of them.

---

## 1. The cast

Five roles. Three of them are staff who do the work; one watches; one is locked out of
the CRM entirely.

| Role | Who they are | What the story asks of them |
|---|---|---|
| **OPERATIONS** | The relationship manager. Sales-side. | Finds the lead, records the conversation, opens deals, gathers paperwork, starts the background check, hands the deal over. **Sees tax identifiers masked.** |
| **COMPLIANCE** | The compliance officer. | Answers the screening checklist, records and reviews verification results, and is the only role (with ADMIN) that can clear, flag or hold a company. **Sees identifiers in full.** |
| **ADMIN** | The administrator. | Everything COMPLIANCE and OPERATIONS can do, plus the things that shape the system: qualification criteria, RXIL intake, and user and role management. |
| **DEVELOPER** | Internal technical staff. | Reads the CRM to support it. Identifiers masked, **and the background check, verification and screening are invisible to them entirely** — not greyed out, absent (D8). |
| **API_USER** | What public sign-up grants. | Nothing. Reaches no CRM screen or route at all. |

**A principle you will see repeatedly:** a role that may not reveal a value gets **no
reveal control at all**, never a disabled one. A disabled eye icon still says "this data
exists, you just can't have it".

---

## 2. What the CRM is tracking

One company carries a **journey** and three independent **gauges**. They are deliberately
separate — conflating them is how a sales opinion ends up looking like a compliance
verdict.

| | Question it answers | Who moves it |
|---|---|---|
| **Journey** — `LEAD` → `PROSPECT` → `CUSTOMER` | How far is this relationship? | **Nobody, by hand.** It follows from the other two. Forward only. |
| **Qualification** | Did they meet our commercial requirements? | OPERATIONS / COMPLIANCE / ADMIN record an outcome |
| **Conversation** | How is the sales conversation going? | OPERATIONS / COMPLIANCE / ADMIN |
| **Background check** | Is it safe and lawful to work with them? | COMPLIANCE / ADMIN (OPERATIONS may only start one) |
| **Marker** — `NONE` / `PAUSED` / `ENDED` | Is the relationship paused or over, commercially? | Staff, with a reason |

The **marker is not a compliance hold.** A concern about a company goes on the background
check. The marker is for "their factory is shut until January" — a commercial pause.

---

## Act 1 — A lead arrives

**Who:** OPERATIONS (or ADMIN, for the RXIL route)

Falcon Agro Exports comes in. There are three doors:

1. **Typed in by hand** — Companies → add. Name and country are required.
2. **CSV import** — a template download, then a file. For a list from an event or a broker.
3. **RXIL intake** — **ADMIN only**. A company arriving from RXIL is delivered **already
   qualified** (decision 7), so it lands as a `PROSPECT`, skipping Act 2.

The company starts as a **`LEAD`**.

### What can go wrong here

| Situation | What happens |
|---|---|
| Same **PAN** as an existing company | **Refused.** A PAN is one legal entity; two rows would split its history. |
| Same **GSTIN** as an existing company | **Warned, not refused.** A group can legitimately share one. Falcon's sibling *G* carries this warning against Bharat Precision Metals. |
| No PAN yet | Fine. Falcon is seeded exactly this way — a real lead often arrives with only a name. |
| A masked role triggers the PAN-duplicate refusal | They learn *that* a company holds that PAN. A known leak, tracked in [`open-items.md`](open-items.md). |
| Website given as `ftp://` or a script URL | Refused — `http(s)` only. |

> ⚠ **No live RXIL feed.** The RXIL intake screen accepts a delivery; nothing is polling
> RXIL. Automatic intake waits on RXIL's package contract (D12).

---

## Act 2 — Qualification: are they worth pursuing?

**Who:** OPERATIONS, COMPLIANCE or ADMIN record it. **ADMIN** owns the criteria themselves.

The criteria are **settings, not code** — versioned rows an ADMIN manages on
`/settings/qualification-criteria`. Adding "minimum annual export turnover" needs no
deployment.

Staff record a **result per criterion** — `PASS`, `FAIL` or `UNKNOWN` — each with
evidence. The server then **suggests** an outcome from those results. A **person** records
the actual outcome. The suggestion never decides.

### The two endings

**`QUALIFIED`** → the journey moves **`LEAD` → `PROSPECT`**, in the same transaction, with
a history row saying why. In the prototype this is **final** (assumption A2).

**`NOT_QUALIFIED`** → needs **at least one reason code**. The company **stays a `LEAD`**.
It is not dead: it can be **re-reviewed** later with new results, and the new outcome
supersedes the old one rather than erasing it. Deccan Leather Works is seeded here.

### What can go wrong here

| Situation | What happens |
|---|---|
| `NOT_QUALIFIED` with no reason code | Refused. |
| Trying to re-qualify a `QUALIFIED` company | Refused — `QUALIFIED` is final (A2). |
| Two people record an outcome at once | The company row is locked; the second sees the first's result. |
| Someone wants to open a deal now | **Refused** — see Act 4. |

---

## Act 3 — The conversation, and following up

**Who:** OPERATIONS, COMPLIANCE, ADMIN

The conversation gauge applies **from `PROSPECT` onward** (assumption A4) — there is
nothing to record about a relationship that has not begun.

`NOT_CONTACTED` → `REACHING_OUT` → `SPOKE_TO_THEM` → `INTERESTED` → `NOT_NOW` → `READY_NOW`

Unlike every other state machine here, **any value may follow any other** (except itself).
That is deliberate: this is a **judgement about a relationship**, not a pipeline. A
conversation really can go from `INTERESTED` straight back to `REACHING_OUT`.

### "Interested, but not right now"

`NOT_NOW` **requires a check-back date, and it cannot be in the past**. Aarav Textiles is
seeded here. That date puts the company on the **Follow-ups** screen and on **Home** when
it falls due — visible to the *whole team*, not just whoever set it.

Follow-ups are activities with a due date. Completing one writes a **locked completion
record** — you cannot quietly un-complete it.

### What can go wrong here

| Situation | What happens |
|---|---|
| `NOT_NOW` with no date, or a past date | Refused. |
| Setting the gauge on a `LEAD` | Refused — the gauge starts at `PROSPECT`. |
| Setting a value to itself | Refused; it would record nothing. |
| Changing a check-back date | **Takes two moves today** — move away and back. A known rough edge. |

---

## Act 4 — A deal: is there a real, current need?

**Who:** OPERATIONS, COMPLIANCE, ADMIN

A qualification says they are worth pursuing. A **deal** says there is a specific shipment
to finance, now.

**Only a `PROSPECT` or a `CUSTOMER` may have a deal opened.** A `LEAD` is refused with
`DEAL_COMPANY_NOT_READY` — because opening a deal also moves the conversation gauge, and
that gauge does not apply to leads.

**Opening a deal sets the conversation to `READY_NOW`** in the same transaction. The two
facts cannot disagree, because they commit together.

A company may have **any number of deals**. Each has **at most one buyer**, stored as its
own row — because a check about a buyer must attach to the buyer, never to the company
(decision 9). Bharat Precision Metals is seeded with two: a handed-over Hamburg order and
a Rotterdam shipment still gathering paperwork.

### The deal's stages

| From | To | Needs |
|---|---|---|
| `OPEN` | `GATHERING_PAPERWORK` | — |
| `OPEN` or `GATHERING_PAPERWORK` | `WITHDRAWN` | a reason |
| `GATHERING_PAPERWORK` | `HANDED_OVER` | a buyer **and** the handover guard (Act 8) |

`HANDED_OVER` and `WITHDRAWN` are **terminal**. A terminal deal takes **no more documents**
and its **buyer can no longer be changed** — what the lending team was handed must stay
what they were handed.

### What can go wrong here

| Situation | What happens |
|---|---|
| Opening a deal on a `LEAD` | Refused — `DEAL_COMPANY_NOT_READY` |
| Handing over with no buyer | Refused |
| Withdrawing with no reason | Refused |
| Uploading to a handed-over deal | Refused — `DEAL_TERMINAL` |
| A deal falls through | Withdraw it with a reason. **The company is untouched** — no black mark on the exporter. |
| A buyer fails a check | Recorded **on the buyer**. The company's background check does not move (decision 9). |

---

## Act 5 — Collecting the paperwork

**Who:** OPERATIONS, COMPLIANCE, ADMIN

A document belongs to **exactly one company or one deal** — never both, never neither.
That distinction matters later: **only a company's own documents count as evidence for
clearing it.** Deal paperwork belongs to the deal.

Categories are a fixed list the server checks; the **types within them are settings**
(`document-types.yaml`), so a new type needs no deployment.

### Every upload is quarantined first

```
PENDING_SCAN  →  AVAILABLE       (clean — the only status that can be opened)
              →  QUARANTINED     (never served)
              →  SCAN_FAILED     (never served)
```

A document that is not `AVAILABLE` **cannot be downloaded by anyone** — not by role, by
state. There is no role that opens a quarantined file. Downloads use **signed, expiring
links**, and the link is a scope, not a credential: the content route still checks who you
are.

> ⚠ **The scanner is a labelled pass-through.** It returns "clean" for everything and says
> so on every row, in every response and on the upload form. It is **not a virus scanner**.
> Storage is **local disk** — no S3, no Object Lock, no KMS, no retention lock.
> **Do not upload real exporter documents to this build.**

### What can go wrong here

| Situation | What happens |
|---|---|
| A category filed against the wrong owner type | Refused |
| A file type with no extension in the allow-list | Refused (422) |
| Over 25 MB | Refused in the browser before it is sent |
| A Hindi or `₹` file name | Works — stored as given, served with an RFC 6266 header |
| Downloading a `QUARANTINED` file | Refused to every role |
| An expired link | Refused (403) |
| Deleting a document | **Not possible.** Seven-year retention argues against it and the database refuses it. |

---

## Act 6 — The checks behind the check

**Who:** COMPLIANCE and ADMIN record and review these. OPERATIONS may read them. DEVELOPER cannot see them at all.

The background check does **not run checks**. It records a **decision on inputs**. Those
inputs are three things:

### 1. Verification results

One row per check on one subject. The subject is either the **company** (`EXPORTER`) or a
**deal's buyer** (`BUYER`).

- A manual **`PASSED`** needs **a note or at least one evidence reference** (D16) — you
  cannot assert a pass with nothing behind it.
- A manual **`PENDING`** is **refused** outright. "I started something" is not a result.
- **Evidence** is either a document — which must exist, belong to that subject, and be
  `AVAILABLE` — or an `http(s)` link.
- **Reviews form an append-only chain.** A later review must name the current one and give
  a note, or it is refused as **stale (409)**. Nobody overwrites someone else's review.
- A reviewed result can **never** be changed by a later provider poll — enforced by the
  service *and* a database trigger.
- A new check on a **buyer of a closed deal** is refused (D17).

> ⚠ **No provider is connected.** Middesk, Trulioo and Sumsub are disconnected (A13); the
> route accepts `provider="manual"` only (D7). An "RXIL stub" row is a **placeholder**, not
> RXIL, and says so.

### 2. The screening checklist — eight items

Served by the server, not copied into the browser. Each is answered `PASSED`, `FAILED`,
`EXEMPT` or `NEEDS_REVIEW`, and each answer is a **new row with its own history**.

| Group | Item |
|---|---|
| Company checks | Has the website been reviewed? |
| | Is the registered address a physical business address? |
| | Does the declared business activity make sense for the exporter? |
| Volume and activity | Does expected payment and trading activity fit the business? |
| EDD | Have bank statements / bank-linked activity been reviewed? |
| | Were suspicious bank activity indicators investigated? |
| Exception | If an exception exists, has it been formally approved? |
| | Has supporting evidence for the exception been attached? |

### 3. Bank activity

> ⚠ The panel says **`NOT_CONNECTED`**. No feed exists, and **no findings are invented**.

---

## Act 7 — The background check itself

**Who:** OPERATIONS may **start** a check and **answer** a `MORE_INFO`. Everything else is COMPLIANCE or ADMIN.

Every move writes a **new, locked decision** that supersedes the one before. **Nothing is
ever edited.** A reopen is a new decision, not a correction.

| From | To | Who | Needs |
|---|---|---|---|
| `NOT_STARTED` | `IN_REVIEW` | OPS, COMP, ADMIN | — |
| `IN_REVIEW` | `CLEAR` | COMP, ADMIN | reason + risk + the prerequisites below |
| `IN_REVIEW` | `MORE_INFO` | COMP, ADMIN | a note of **what is needed** |
| `MORE_INFO` | `IN_REVIEW` | OPS, COMP, ADMIN | a note of **what arrived** |
| `IN_REVIEW` | `FLAGGED` | COMP, ADMIN | a reason |
| `FLAGGED` | `ON_HOLD` | COMP, ADMIN | a reason |
| `FLAGGED` / `ON_HOLD` | `IN_REVIEW` | COMP, ADMIN | a reason (reassessment) |
| `CLEAR` | `IN_REVIEW` | COMP, ADMIN | a reason (**reopen**) |

**There is no `CLEAR` → `FLAGGED`.** New information about a cleared company is acted on by
**reopening it first**, so the reason is on the record before anything is concluded.

### What `CLEAR` requires

All four, settled as decisions D1–D4:

1. **A risk rating** — `LOW`, `MEDIUM`, `HIGH` or `CRITICAL`. Required on `CLEAR` and
   **refused on every other move**.
2. **No check still pending** — nothing `PENDING`, nothing in `REVIEW` without an accepted
   or rejected review, and **no placeholder rows**.
3. **All eight screening items `PASSED` or `EXEMPT`.** A **`FAILED` item means `FLAGGED`,
   not `CLEAR`** — a clearance that named a failed sanctions item as evidence would be
   indefensible.
4. **At least one pinned evidence id.**

A **`FAILED` verification does not block `CLEAR` by itself** — that is an answer, and
compliance weighs it and records the risk. A **failed screening item does** block. That
asymmetry is deliberate.

The screen **lists every unmet prerequisite** rather than refusing one at a time.

Every move **pins an evidence snapshot**: the verification results, screening rows and the
company's own `AVAILABLE` documents it rested on. A later upload cannot change what a past
decision rested on.

### What can go wrong here

| Situation | What happens |
|---|---|
| OPERATIONS tries to flag | **403** — roles are checked **per move**, not just per route |
| `CLEAR` with no risk | Refused (422) |
| A risk rating on a `FLAGGED` move | Refused — risk belongs to a clearance |
| `CLEAR` with items outstanding | **409, naming every unmet one** |
| Someone else moved the gauge while your screen was open | **409** — the screen sends the value it was showing |
| Two moves at once | The company row is locked; one wins, the chain never forks |

---

## Act 8 — Becoming a customer

This is the moment the story has been building to, and it is worth watching closely
because **nobody presses a "make customer" button.**

> **`PROSPECT` + background check `CLEAR` → `CUSTOMER`, whichever becomes true second.**

Two roads reach it, and **both commit in one transaction** with the move that completed the
condition:

- **Qualified first, cleared second** — COMPLIANCE records `CLEAR`, and the promotion
  happens inside that same commit.
- **Cleared first, qualified second** — a `LEAD` that was already cleared becomes
  `QUALIFIED`; it moves to `PROSPECT` and straight on to `CUSTOMER` in that commit.

Because both callers lock the company row first, a `CLEAR` and a `QUALIFIED` landing at the
same instant make the move **exactly once**. **No committed state is ever `PROSPECT` and
`CLEAR` at the same time.**

It is **idempotent**: a customer that is reopened and cleared again is **not** promoted or
announced twice.

After the commit, `company.became_customer` is announced, carrying the risk rating and the
id of the decision that cleared them.

### Then the deal is handed over

**Who:** OPERATIONS

The **handover guard** needs both halves of assumption A5:

- the company is a **`CUSTOMER`**, and
- its background check is **`CLEAR`**.

Until both hold, the deal page **names every unmet condition** instead of offering a button
that would fail. Coastal Seafood Exports is seeded to show exactly this: its Dubai deal
lists *two* reasons — a `PROSPECT`, not a `CUSTOMER`, and `FLAGGED`, not `CLEAR`.

The guard **share-locks the company row** while the handover commits (D10), so a flag or
reopen landing at that moment **waits** rather than slipping past. The handover snapshots
the buyer and the document ids, writes its history row, and announces `deal.handed_over`.

> ⚠ **Both announcements reach nobody yet.** The bus is in memory and no receiver is built
> (decision 10). The history row is the source of truth; the announcement is best effort.

---

## Act 9 — Life after "customer"

The story does not stop.

**New information arrives about a customer.** COMPLIANCE **reopens** the check
(`CLEAR` → `IN_REVIEW`, with a reason), then flags it.

- The company **stays a `CUSTOMER`.** The journey never moves backwards (A5).
- But its open deals **can no longer be handed over** — the guard needs `CLEAR`.
- Reassess and clear it again, and it is **not announced as a new customer twice**.
- The risk chip keeps showing the **last recorded rating, explicitly labelled as such**
  (D6) — it is the last assessment, not a claim about the company now.

**The relationship pauses or ends.** Set the **marker** with a reason. `ENDED` companies
are **hidden from default lists but stay searchable** — Eastern Spice Traders is seeded
this way. The journey is untouched; the marker can be cleared again.

---

## 10. The same story, per role

| Act | OPERATIONS | COMPLIANCE | ADMIN | DEVELOPER |
|---|---|---|---|---|
| 1 Intake | adds, imports | adds, imports | + RXIL intake | reads, masked |
| 2 Qualification | records results & outcome | same | + manages criteria | reads |
| 3 Conversation | sets gauge, follow-ups | same | same | reads |
| 4 Deals | opens, moves, buyer | same | same | reads — **no stage moves offered** |
| 5 Documents | uploads, downloads | same | same | reads, masked |
| 6 Verification | **read only** | records & reviews | same | **invisible** |
| 6 Screening | **read only** | decides | same | **invisible** |
| 7 Background check | **start + answer `MORE_INFO` only** | all nine moves | same | **invisible** |
| 8 Handover | hands over | can | can | **no blocked-reason shown** |
| — Users & roles | — | — | Settings → Users, Roles | — |

**Masking is done by the server**, never only in the browser — a caller reading the JSON
directly gets no more than the screen shows. An exact search by PAN, GSTIN or IEC is
**refused** to masked roles, because a match alone would reveal which company holds it.

---

## 11. Everything the system refuses — one list

For the awkward question in the room.

**Intake:** duplicate PAN · non-`http(s)` website
**Qualification:** `NOT_QUALIFIED` with no reason code · re-qualifying a `QUALIFIED` company
**Conversation:** the gauge on a `LEAD` · `NOT_NOW` without a future check-back date · a value to itself
**Deals:** a deal on a `LEAD` · handover with no buyer · withdrawal with no reason · editing a terminal deal's buyer
**Documents:** wrong category for the owner · unsupported type · over 25 MB · downloading anything not `AVAILABLE` · an expired link · **any deletion**
**Verification:** manual `PENDING` · manual `PASSED` with neither note nor evidence · evidence that isn't `AVAILABLE` or isn't the subject's · a stale review · a new check on a closed deal's buyer
**Background check:** any move not in the nine · `CLEAR` → `FLAGGED` · `CLEAR` without risk · risk on a non-`CLEAR` move · `CLEAR` with prerequisites unmet · OPERATIONS doing anything but start/answer · a move from a stale screen
**Handover:** a company that is not a `CUSTOMER` · a check that is not `CLEAR`
**Everywhere:** `API_USER` reaches nothing · DEVELOPER writes nothing

---

## 12. What is not real in this build

Say these out loud rather than waiting to be asked.

| | |
|---|---|
| **The virus scanner** | A labelled pass-through. Returns clean for everything. **No real documents.** |
| **Storage** | Local disk. No S3, Object Lock, KMS or retention lock. |
| **Verification providers** | Middesk, Trulioo, Sumsub disconnected. `provider="manual"` only. An "RXIL stub" is a placeholder. |
| **Bank activity** | No feed. The panel says `NOT_CONNECTED` and invents nothing. |
| **RXIL intake** | The screen accepts a delivery; nothing polls RXIL. |
| **Events** | `company.became_customer` and `deal.handed_over` are announced; **no receiver exists**, and a publish lost after the commit is not retried. |
| **Role editing** | Settings can edit roles and permissions, but **CRM routes still check the five built-in roles** — editing a CRM permission changes no CRM access today. |

**Also worth knowing**, from [`open-items.md`](open-items.md): the `CLEAR` evidence rule is
satisfied by the eight screening answers alone, so a company **can** be cleared with no
document and no verification result; placeholder verification rows can never stop blocking
`CLEAR`; two history rows written in one step share a timestamp, so **do not rely on their
order between themselves**.

---

## 13. A ten-minute run sheet

Sample companies are seeded by `python -m app.modules.onboarding.sample_data`.

1. **Show the finished article.** Bharat Precision Metals — a `CUSTOMER`, `CLEAR` at low
   risk, one deal handed over. Open its **History** tab: the whole story in one place.
2. **Show a blocked one.** Coastal Seafood Exports — `FLAGGED`, and its deal names **both**
   reasons it cannot be handed over.
3. **Now walk a new one**, as OPERATIONS: add a lead → try to open a deal (**refused**) →
   qualify it (**becomes a `PROSPECT`**) → set the conversation → open a deal → record the
   buyer → upload a document → start the background check.
4. **Switch to COMPLIANCE.** Answer the eight screening items. Try `CLEAR` early to show it
   **listing what is still outstanding**. Then record `CLEAR` with a reason and a risk —
   and show the journey read **`CUSTOMER`** on the header, with nobody having pressed
   "make customer".
5. **Back as OPERATIONS**, hand the deal over. Show the frozen paperwork snapshot.
6. **Show a reopen.** As COMPLIANCE, reopen and flag Bharat. It **stays a customer**, but
   its Rotterdam deal can no longer be handed over.
7. **Switch to DEVELOPER.** The background check, verification and screening are **simply
   not there**, and identifiers are masked.

**Use a fresh database** — see [`demo.md`](demo.md) §1. The test database collects
thousands of companies, some in states the product cannot actually produce.
