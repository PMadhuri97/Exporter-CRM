# Contract — the event envelope

**Owner:** Developer 1 · **Code:** `backend/app/platform/messaging/schemas.py`

The CRM announces a handful of things to other teams. This is the shape of
those announcements and the rules about what they are and are not for.

Changing this contract needs the agreement of all four developers and of
whoever owns the platform's other topics.

---

## 1. Decision U2 — the envelope carries the actor and the deal

The architecture says the envelope carries the event name, its id, the time, the
company, the deal when there is one, who caused it, and a small payload. The
platform's `EventEnvelope` had no actor and no deal field, so the two had to go
somewhere.

**Resolved: extend the envelope.** `actor_id` and `deal_id` are now fields on
`EventEnvelope`, both `str | None` defaulting to `None`.

The alternative — a documented convention that CRM producers put them in
`payload` — was rejected because nothing would enforce it. A producer that
forgot `actor_id` would fail at no point: not at construction, not at publish,
not at the consumer. A field with a type does.

The change is additive in both directions:

- Every existing producer keeps working; both fields are keyword-only on
  `build_envelope` with `None` defaults.
- An old message parses into a new envelope (the fields take their defaults).
- A consumer that does not read them is unaffected.

**The company is `partition_key`, not a new field.** Customer events are already
keyed by customer id so one company's events stay ordered on one partition, and
`customer.registered` has used it that way since the topic existed. A deal has
no such ordering requirement of its own, so `deal_id` is a plain field.

---

## 2. The envelope

```python
class EventEnvelope(BaseModel):
    event_id: str            # uuid4 — the deduplication key
    event_type: EventType    # e.g. "company.became_customer"
    topic: Topic             # resolved from event_type, never passed in
    partition_key: str       # the company id, for a CRM event
    transaction_id: str | None = None
    correlation_id: str | None = None
    actor_id: str | None = None      # who caused it; None = the platform
    deal_id: str | None = None       # the deal, when there is one
    occurred_at: str                 # ISO-8601, UTC
    producer: str = "aner-settlement-platform"
    payload: dict = {}
```

| Field | CRM meaning |
|---|---|
| `event_id` | Deduplication key. Kafka delivers at-least-once; every consumer checks this against `processed_events` before acting. |
| `partition_key` | **The company id.** Always set for a CRM event. |
| `deal_id` | The deal, for `deal.handed_over`. `None` on company-level events. |
| `actor_id` | `str(user.id)` from the login session. `None` means the platform acted on its own behalf — the same meaning `actor_id` carries on a history row, so the answer does not change shape between the record and the announcement of it. |
| `correlation_id` | Traces one request across services. **Not** an actor. |
| `transaction_id` | Unused by the CRM; it belongs to the settlement topics. |
| `occurred_at` | When the envelope was built, which is after the history row was written. |

---

## 3. The two CRM events

Both are **planned, not built** — see §6.

### `company.became_customer`

Announced when a company reaches `CUSTOMER`: it is a Prospect and its background
check is `CLEAR`, whichever happens second (assumption A1).

```
partition_key : <company id>
actor_id      : <the user whose action completed the move>
deal_id       : None
payload       : {
    "company_id"          : str,
    "name"                : str,
    "country"             : str,
    "pan"                 : str | None,
    "gstins"              : [str],
    "risk_rating"         : "LOW" | "MEDIUM" | "HIGH" | "CRITICAL",
    "clearing_decision_id": str,
}
```

Consumer: the customers team, later (decision 10). Nothing receives it today,
which is expected and is why the CRM only announces.

### `deal.handed_over`

Announced when a deal is handed to the lending team. Only permitted when the
company is a `CUSTOMER` and its background check is `CLEAR` (assumption A5).

```
partition_key : <company id>
actor_id      : <the user who handed it over>
deal_id       : <the deal id>
payload       : {
    "deal_id"     : str,
    "company_id"  : str,
    "buyer"       : {"name": str, "country": str, "identifiers": {...}},
    "document_ids": [str],
}
```

Consumer: the lending team, later.

Neither event type exists in `EventType` yet. Adding one is a member plus a
`TOPIC_FOR_EVENT` entry — Python only, no migration.

---

## 4. Rules

**The history row is the source of truth. The announcement is best effort.**
Publish **after** the history row is written. If the publish fails, log it and
carry on — the change already happened and is already recorded. Never let a
failed announcement roll back or block the operation that caused it.
`OnboardingEventPublisher._emit` already does exactly this: it catches every
exception from `bus.publish` and logs a warning.

**Events are never the source of business state.** Nothing reconstructs a
company's journey, a gauge or a deal from the event stream. A consumer that
needs state reads it. This holds in the repository today and must keep holding.

**Events are not history.** History is a durable row this repository protects
with a database trigger. An event is a notification that may be dropped. They
answer different questions and neither substitutes for the other.

**One event per topic.** `TOPIC_FOR_EVENT` maps each `EventType` to exactly one
`Topic`; `build_envelope` resolves it. A producer never passes a topic.

---

## 5. Four things that are all different

The repository keeps these apart, and this contract exists partly to keep them
apart.

| | What it is | Where it lives |
|---|---|---|
| **Business state** | The current value. The truth. | `exporter_profile`, `verification_result` |
| **History** | Every change to that value, append-only, DB-enforced. | `exporter_lifecycle_history` and the specialised append-only tables |
| **Domain events** | A best-effort notification to another team. | `EventEnvelope` on the bus |
| **Integration events** | Something an outside system sent us. | `onboarding_webhook_events`, HMAC-verified |

---

## 6. What is implemented today

| Item | State |
|---|---|
| `EventBus`, in-memory and Kafka backends, topic routing | **implemented** |
| `actor_id` / `deal_id` on the envelope and `build_envelope` | **implemented** (this contract) |
| Best-effort publish that never raises to the caller | **implemented** |
| `EventType.COMPANY_BECAME_CUSTOMER` / `DEAL_HANDED_OVER` | **not built** — L1-12 |
| A CRM event helper any service can call | **not built** — L1-12 |
| Any CRM service publishing anything | **not built** — the CRM publishes nothing today |
| A receiver for either event | **not built** — other teams, later |

The only producers on the bus today are the legacy `onboarding_service` and the
Sumsub `webhook_service`, both emitting `customer.*` events. No Exporter CRM
code path publishes.
