# Contract — trade history

**Owner:** Developer 3 · **Tables:** `onboarding.trade_relationship`,
`onboarding.trade_invoice`, `onboarding.trade_invoice_outcome` ·
**Migrations:** `onboarding_0037_trade_history`

**Used by:** Developer 2 (the deal page mounts the pair's panel, task 2.11; the deal's
payment outcome is recorded after handover), Developer 1 (`trade` is one of the history
dimensions, and `trade` rows reach DEVELOPER with identifiers already masked —
`history-row.md`).

**State.** Built. Tables, services, the five routes, both panels and the relationship
backfill's code. The backfill has **not been run** on any environment; it is step 3 of
the operational order in `developer-allocation.md` §6 (runbook: `remaining-work.md` §8).

Plan P5-1 … P5-8 and architecture §3.5 are the source. Decisions: IQ-4 (currency),
IQ-19 (who may read), BQ-7 (`source` on every row).

---

## 1. What a trade relationship is

One **ordered pair** of company records: `(seller_company_id, buyer_company_id)`,
unique by `uq_trade_relationship_pair`, with `ck_trade_relationship_not_self` refusing
a company that trades with itself.

Ordered, not symmetric. A selling to B is a different relationship from B selling to A,
with different invoices and different risk, and the two are never folded together. Every
list in the API and both panels therefore come in two: *who this company sells to* and
*who it buys from*, the same shape as the deal lists (task 2.7).

**There is no `relationship_id` column on `deal`**, and none is needed (allocation §1,
adjustment 1). A deal already carries both sides — `company_id` and `buyer_company_id` —
so its relationship is a lookup on the unique pair, not a stored link. This is worth
stating because P5-5 assumed the column and worried about the terminal-deal freeze
having to allow a one-time write: with no column, nothing is written to `deal` and the
freeze is never involved. The cost is a join instead of a column.

A relationship is created **in the same transaction** as the write that implies it:
`DealService.set_buyer_company` calls `get_or_create_relationship`, so "every deal with
a buyer company has a relationship" is true rather than eventually true.
`get_or_create_relationship` is written as `INSERT … ON CONFLICT DO NOTHING` followed by
a read, inside a savepoint — not "look, then insert", which has a window between the two
statements and passes every single-threaded test. `created` comes back from
`RETURNING`, so it is the database's answer and not a guess.

`source` and `source_ref` say where a row came from (BQ-7):
`deal_buyer_recorded` with the deal id, `backfill` with the run id, or `manual`.

---

## 2. What an invoice is, and what an outcome is

An **invoice** is a fact about the past: `invoice_number` (unique per relationship),
`invoice_date`, `amount`, `currency`, and `deal_id` — **nullable**, because past trade
the exporter tells us about has no deal in this CRM (P5-8). Its identity is frozen the
moment it is written by `trg_trade_invoice_identity_immutability`. There is no edit: an
invoice whose amount could be changed afterwards is not evidence of anything, so a
mistake is corrected by recording the right invoice and the wrong one stays visible.

`deal_id`, when given, is a **deal between the relationship's two companies**: the
relationship's seller selling to its buyer company. Anything else is refused — a deal
that does not exist (404 `DEAL_NOT_FOUND`), or one between other companies or whose
buyer is still a legacy `deal_buyer` row (422 `TRADE_INVOICE_DEAL_NOT_THIS_PAIR`) —
because the value is frozen once written. Since 0042 the database also holds it to a
real deal (`fk_trade_invoice_deal_id`, `ON DELETE RESTRICT`; deals are never deleted).

**One invoice per deal is not a rule (D-03, open).** The deal route below creates one
when the deal has none and refuses invoice details once it has one; the relationship
route may still record a second against the same deal on purpose. When a deal has
several, the deal route answers about the **earliest**.

An **outcome** is one thing we learned about an invoice: `payment_status`,
`amount_paid`, `proof_status`, `evidence_note`, `evidence_refs`, `recorded_by/at` and
`supersedes_outcome_id`. `evidence_refs` is a list of `{type, ref}` in a verification
result's shape (`document` or `url`; a `url` must be http(s)), and the API types it with
verification's own models. The table is append-only (`public.prevent_mutation()`), and a
correction is a **new row naming the one it replaces** — the same shape as a
verification review. A partial unique index allows one head per invoice and one
superseder per row, so the chain is a line and not a tree: two people cannot each
correct the same outcome without seeing the other's. The service refuses to supersede
anything but the current head, with the error the UI shows.

**Concurrent outcomes.** Recording one locks the invoice row `FOR UPDATE` before the
head is read, so two outcomes for one invoice are decided one after the other: the
second sees the first as the head and is refused with 409 `TRADE_OUTCOME_STALE`. Two
simultaneous first outcomes, or two corrections of the same head, never surface as a
500.

`is_current` in the API means *nothing supersedes this row* — not *the newest
timestamp*. Two rows written in one transaction share a timestamp, so "newest" would
show the wrong one exactly when a correction was made in the same breath as the thing it
corrects.

### 2.1 The two gaps that must not look the same

| On screen | Means |
|---|---|
| **No outcome recorded** | Nobody has followed this invoice up. |
| **Not known** (`UNKNOWN`) | Somebody looked and could not say. |

`UNKNOWN` is a real answer: a relationship manager may know an invoice exists — the
exporter showed it to them — without knowing whether it was paid, and recording that is
more useful than recording nothing. It is why an outcome is required to carry a status
at all.

The same discipline applies to proof: `CLAIMED` is shown beside the payment status and
never folded into it. "Paid" and "Paid, claimed" must not look the same, because a
lending decision reads them differently. `PROVEN` is deliberately silent on screen —
proof is the expectation, and labelling it everywhere would make the rows that lack it
harder to spot.

---

## 3. Currency: stored, never converted (IQ-4)

Every amount keeps the currency it was invoiced in. There is **no reporting currency and
no rate**, here or anywhere, and nothing is totalled — not in the API, not in a panel.
A total across currencies would need a rate that does not exist, and a rate chosen to
make a total would be a number nobody could defend.

Amounts are `Numeric` in the database and **strings** in JSON, so a JSON number cannot
round them. The frontend formats them and never parses them.

---

## 4. The API

| Route | Who | Notes |
|---|---|---|
| `GET /exporters/{id}/trade-relationships?as=seller\|buyer` | staff + DEVELOPER | Two sides, two lists. `invoice_count` per row |
| `GET /trade-relationships/{id}` | staff + DEVELOPER | Invoices newest first, each with the outcome we currently believe |
| `GET /trade-invoices/{id}` | staff + DEVELOPER | The **whole** outcome chain, oldest first |
| `POST /trade-relationships/{id}/invoices` | staff | Identity frozen on write. This is how claimed past trade (P5-8) is recorded: the company page's trade panel offers **Record past invoice** on each relationship row (R-27), sending no `deal_id`, then, if an outcome is chosen, `POST /trade-invoices/{id}/outcomes` with `proof_status` `CLAIMED` unless the person has seen proof. If the outcome is refused after the invoice is written, the form says so and sends only the outcome again. A pair with no relationship yet has nowhere to record it: no route creates a relationship on its own |
| `POST /trade-invoices/{id}/outcomes` | staff | Append-only; `supersedes_outcome_id` must be the head |
| `POST /deals/{id}/payment-outcome` | staff | §5 |

**IQ-19 — "DEVELOPER reads masked" — is satisfied by the response shape rather than by
a masking pass.** A counterparty is served as `{company_id, name, country,
pipeline_status}` and carries **no identifiers for any role**: no PAN, no GSTIN, no CIN,
no registration number. There is therefore nothing here to mask, for anybody. A reader
who needs a counterparty's identifiers opens that company's page, where D8's masking
governs them in one place. This also matches what `history-row.md` already said about
`trade` rows reaching DEVELOPER.

---

## 5. The payment outcome after a handover (P5-6)

`POST /deals/{deal_id}/payment-outcome` is how an outcome is recorded on a deal. It
requires the deal to be `HANDED_OVER` (409 `DEAL_NOT_HANDED_OVER`) and its buyer to be a
**company** (409 `DEAL_BUYER_IS_NOT_A_COMPANY`): the relationship is between two company
records, and a legacy `deal_buyer` row is not one — such a deal waits for the buyer
migration.

It creates the deal's invoice if it has none, in which case the four invoice fields are
required **together or not at all**, and refuses invoice details when one already exists
(422 `TRADE_INVOICE_ALREADY_RECORDED`). Then it appends the outcome.

**All or nothing.** The request is checked before anything is written, and the
relationship, the invoice and the outcome are committed together, once. A refused
request — a `PARTIAL` with no `amount_paid`, malformed evidence, a stale
`supersedes_outcome_id` — leaves no invoice behind, so the corrected retry succeeds.
**One request per deal at a time:** the deal row is locked `FOR UPDATE` first, so two
first outcomes on a deal with no invoice cannot both create one; the second is told the
invoice exists.

**It is not a deal stage.** Handover is the end of the deal's own story; what happened to
the money afterwards is a fact about the trade (architecture §3.3). Nothing about a deal
changes here.

---

## 6. History

Every write records a `trade` history row on the **seller's** timeline, with the deal id
when there is one. The buyer company sees it through the read-side union task 2.7 added,
so a buyer-only company's timeline is not empty.

The relationship backfill writes **no** history rows. A row per backfilled pair would put
a few thousand entries dated the night of the migration onto timelines that record what
people did — and no person did it.

---

## 7. The relationship backfill (P5-5, task 3.23)

    python -m app.modules.onboarding.backfill_trade_relationships --dry-run
    python -m app.modules.onboarding.backfill_trade_relationships --apply --run-id <id>
    python -m app.modules.onboarding.backfill_trade_relationships --validate
    python -m app.modules.onboarding.backfill_trade_relationships --report-run --run-id <id>

**Run it only after the buyer migration (P4-6) has been applied** — step 3 of the
operational order. The dry run says so itself when it sees most deals still without a
buyer company, rather than handing over a report about the remainder.

Which deals need it: only the ones linked *without* going through
`DealService.set_buyer_company`, which creates the relationship itself. That is exactly
the set P4-6 links with an `UPDATE`.

Which deals count: every deal with a `buyer_company_id`, at any stage, **including
`WITHDRAWN`** — a relationship is "these two have dealt with each other", not "these two
completed a trade". What happened is carried by the invoices, and a withdrawn deal has
none, so such a pair shows as a relationship with nothing under it. That is true, and it
is what the panel renders. Two deals between the same pair produce **one** relationship,
which is why the report counts pairs and not deals.

It creates relationships and nothing else: no invoices (a deal having had a buyer is not
evidence that money moved, and inventing an invoice would put unproven numbers into
trade history), no history rows, no change to any deal. It is idempotent — a second run
writes nothing — because `get_or_create_relationship` is, not because a mapping table
says so.

**Undo:** `DELETE FROM onboarding.trade_relationship WHERE source = 'backfill' AND
source_ref = '<run id>'`, which is offered as a line to read rather than as a `--rollback`
flag: unlike the buyer migration there is nothing frozen in the way. Once an invoice hangs
off a backfilled relationship the foreign key refuses the delete, and `--report-run` says
how many do before you try.

---

## 8. Error codes

| Code | Status | When |
|---|---|---|
| `TRADE_RELATIONSHIP_NOT_FOUND` | 404 | No such relationship |
| `TRADE_RELATIONSHIP_IS_SELF` | 422 | Seller and buyer are the same company |
| `TRADE_INVOICE_NOT_FOUND` | 404 | No such invoice |
| `TRADE_OUTCOME_STALE` | 409 | `supersedes_outcome_id` is not the chain's head |
| `TRADE_INVOICE_ALREADY_RECORDED` | 422 | Invoice details sent for a deal that already has one |
| `TRADE_INVOICE_DEAL_NOT_THIS_PAIR` | 422 | An invoice's `deal_id` is not a deal between the relationship's two companies |
| `DEAL_NOT_FOUND` | 404 | An invoice's `deal_id` names no deal |
| `DEAL_NOT_HANDED_OVER` | 409 | A payment outcome on a deal that has not been handed over |
| `DEAL_BUYER_IS_NOT_A_COMPANY` | 409 | The deal's buyer is still a legacy `deal_buyer` row |

---

## 9. What this contract does not cover

- **Whether a trade was financed, and how that went.** The lending side's, outside the
  CRM entirely (architecture §3.5).
- **Any judgement derived from this history.** Nothing computes a score, a limit or a
  rating from invoices and outcomes. The record is served; reading it is a person's job.
- **Currency conversion.** See §3. Not now, not later.
- **The deal itself.** `deal-and-buyer.md`.
