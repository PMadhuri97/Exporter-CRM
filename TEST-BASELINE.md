# Backend test baseline

The reference point for "was this already red?". Established 2026-09-23 against a
clean `alembic upgrade head`. Anyone who sees a failure not listed here has
introduced it.

## How to reproduce

```
docker compose up -d postgres            # repo root; waits healthy on :5433
cd backend
alembic upgrade head
python -m pytest -p no:cacheprovider --no-cov -q -rf --timeout=120 --timeout-method=thread
```

`--no-cov` overrides the `--cov` flags in `pyproject.toml`'s `addopts`: a baseline
is about pass/fail, and the coverage pass adds runtime without changing a single
verdict. `-p no:cacheprovider` keeps the run from writing `.pytest_cache` into the
tree. Everything else — `testpaths`, `asyncio_mode`, the 120s per-test timeout —
comes from `backend/pyproject.toml` and is not overridden.

Alembic head at the time of this run: `onboarding_0010_screen_review`.

## Environment prerequisite (this bit bites)

`google-cloud-logging==3.11.4` and `google-cloud-storage==2.19.0` are declared in
`backend/requirements.txt` (lines 19-20) but are easy to end up without. Without
them, **collection aborts with 2 errors** before a single test runs:

```
app/platform/audit_framework/tests/test_gcp_integration.py
app/platform/audit_framework/tests/test_posting_audit_logging.py
    ModuleNotFoundError: No module named 'google.api_core'
```

That is a provisioning gap, not a code regression. `pip install -r requirements.txt`
clears it. Verify before trusting any run:

```
python -m pytest -p no:cacheprovider --no-cov -q --collect-only | tail -1
# => 2692 tests collected in ~7s, zero collection errors
```

## Numbers

| | |
|---|---|
| Collected | **2692** (0 collection errors) |
| Passed | **2658** |
| Failed | **23** |
| Errors | **5** (all fixture-setup, not test-body) |
| Skipped | **6** |
| Wall clock | 398s (6m38s) |
| Exit code | 1 |

## The 28 red items, by root cause

### Cause A — out-of-scope routers are not mounted (27 of 28)

`app/api/rest/router.py:12-27` deliberately drops the `payments`, `fx`, `ledger`,
`settlement`, `reconciliation` and `rails` API layers from this checkout. Their
domain entities and migrations are present — which is why **nothing fails to
import** — but their HTTP routes do not exist. Every test below asks for one of
those routes and gets `404 {"detail":"Not Found"}`.

These are pre-existing and environmental. They are not assertions about onboarding
behaviour, and fixing them means mounting routers that are out of scope here.

Errors (5) — all die in fixture setup at `POST /api/v1/payments` → 404:

```
app/modules/compliance/tests/integration/test_compliance.py
    ERROR at setup of test_screen_already_screened_returns_409
    ERROR at setup of test_get_screenings_success
    ERROR at setup of test_approval_missing_auth
    ERROR at setup of test_approval_wrong_role_denied
    ERROR at setup of test_get_approvals_missing_auth
```

Failures (22):

```
app/modules/audit/tests/integration/test_audit.py
    test_payments_audit_alias                          GET /payments/{id}/audit -> 404
    test_correlation_captured_from_request_header      POST /fx/quotes          -> 404

app/modules/compliance/tests/integration/test_compliance.py   (POST /payments -> 404)
    test_screen_kyb_fails_sender
    test_screen_kyb_fails_beneficiary
    test_screen_sanctions_hit_blocks_transaction
    test_screen_dnfbp_triggers_edd
    test_screen_high_risk_triggers_aml_manual_review
    test_screen_clean_transaction_moves_to_under_review
    test_approval_transaction_not_under_review
    test_full_maker_checker_approval_flow
    test_same_user_both_roles_rejected
    test_maker_rejection_declines_transaction
    test_checker_rejection_declines_transaction
    test_approval_after_complete_returns_409

app/modules/compliance/tests/integration/test_screening_uses_rule_registry.py   (POST /payments -> 404)
    test_a_designated_sector_triggers_edd_through_the_registry
    test_a_standard_sector_does_not_trigger_edd
    test_an_ordinary_amount_is_not_sent_for_value_review
    test_a_large_amount_is_sent_for_value_review
    test_lowering_the_threshold_in_configuration_changes_the_decision
    test_retiring_the_dnfbp_rule_stops_the_edd_obligation
    test_an_elevated_customer_rating_still_reviews_without_any_rule
    test_sanctions_screening_is_unaffected
```

Representative error:

```
>       assert resp.status_code == 202, f"Payment creation failed: {resp.text}"
E       AssertionError: Payment creation failed: {"detail":"Not Found"}
E       assert 404 == 202
```

### Cause B — one stale assertion (1 of 28)

```
app/modules/onboarding/tests/integration/test_exp1_exporter_api.py::test_full_exporter_profile_flow

>       assert replay_resp.status_code == 201  # service returns created=False; router doesn't remap status
E       assert 200 == 201
```

This is the only genuinely stale red item, and it is a *test* bug, not a product
bug. The test's inline comment asserts the router does not remap the status for an
idempotent replay. It does now — `docs/exporter-crm-frontend-tickets.md:364-372`
records that the 200-vs-201 gap was found against a live server and fixed on both
the `create_lead` and `create_or_get_profile` branches. The endpoint returning 200
on replay is correct; the assertion was never updated.

Owned by whoever owns `exporter_router.py` and this test file. Left untouched here
on purpose — it is in another developer's lane this week.

## Import failures

**None.** All 2692 tests import cleanly. The out-of-scope modules named at
`app/api/rest/router.py:12-27` are present as domain entities plus migrations,
which is enough to import; only their `api/` layer is absent, and that surfaces as
404s at request time, never as an `ImportError`.

Any future `ImportError` or `ModuleNotFoundError` at collection is therefore new
and should be treated as a regression — with the single exception of the
`google.api_core` provisioning gap documented above.

---

# Delta — end of phase (2026-09-23)

Same command, same database, after the E9 data-integrity work landed.

| | Baseline | After | Δ |
|---|---|---|---|
| Collected | 2692 | **2712** | +20 |
| Passed | 2658 | **2678** | **+20** |
| Failed | 23 | **23** | 0 |
| Errors | 5 | **5** | 0 |
| Skipped | 6 | **6** | 0 |
| Wall clock | 398s | 340s | −58s |

**No regressions.** The 23 failures and 5 errors are the same tests, with the
same causes, as the baseline above — 27 of them the unmounted `payments`/`fx`
routers, and one the stale 200-vs-201 assertion in
`test_exp1_exporter_api.py::test_full_exporter_profile_flow`. Nothing moved from
green to red.

The +20 are all in the new
`app/modules/onboarding/tests/integration/test_e9_screening_review_service.py`.

Alembic head moved `onboarding_0010_screen_review` → `onboarding_0011_e9_audit`,
verified `upgrade → downgrade → upgrade` against a live Postgres.

The 21 DB-backed state-machine tests that moved out of `tests/unit/` into
`tests/integration/test_state_machine_api.py` (22 of them, in fact — see the
phase notes) are counted in both columns; relocating them changed no totals.
