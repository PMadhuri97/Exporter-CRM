# Dev1 — what is left

**As of 26 September 2026**, after the Dev1 integration gate. Backend suite
**3,050 passing / 22 failed / 5 errors** (the 27 red items are the pre-existing
payments/FX and compliance-screening tests that hit routes this checkout does
not mount). One Alembic head. Frontend: 24 tests, 0 lint errors, build passes.

Tasks L1-01 to L1-14 meet their stated acceptance criteria. This file is only
what remains, so it reads shorter than the work does.

Three of the five items below are **not Dev1's to decide**. They are listed
here because Dev1 is blocked on them or is the likely implementer once someone
decides — not because Dev1 can close them alone.

---

## 1. Open Dev1 items

### 1.1 L1-02 — contracts need acknowledgement

**Status: partial. Blocking nobody yet, but it is the Week 0 exit criterion.**

The three contracts are written and merged:

| Contract | File |
|---|---|
| History row | `docs/contracts/history-row.md` |
| Event envelope | `docs/contracts/event-envelope.md` |
| Migration register | `docs/contracts/migration-register.md` |

The task's acceptance criterion is "merged **and acknowledged by all**". The
merge happened; the acknowledgement has not. Section 7.5 says a contract
changes only with the agreement of its owner and every user of it, which is
meaningless if the users never read it.

**What closes this:** Dev2, Dev3 and Dev4 each confirm they have read the three
documents and that nothing in them conflicts with what they are about to build.
Twenty minutes in the daily check-in, not a work item.

**Where it will bite if skipped:** the history contract fixes `dimension` values
per gauge (§2) and which moves require a `reason` (§4). Two developers guessing
at those independently is exactly the drift the contract exists to stop.

### 1.2 L1-15 — spare-capacity hand-over

**Status: deferred. Depends on Dev2.**

From Week 3, Dev1 has spare capacity and takes screens from L2-14 (the company
list, the three-column pipeline, or the import screen) if Dev2 is behind, with
Dev2 reviewing. Nothing to do until Dev2 says so; §10's risk table says hand
screens over *early* rather than late.

### 1.3 L1-14 — continuing duties

**Status: mechanism complete, duty ongoing.**

L1-14 is marked `cont.` in the plan — it does not finish. What now runs
automatically versus what still needs a person:

| Duty | Automated? |
|---|---|
| API types match the API | **Yes.** `backend/tests/contract/test_openapi_artifact_is_current.py` regenerates the document and fails on any difference. |
| Every mounted route is classified | **Yes.** `test_route_authorization_coverage.py` fails on an unclassified route, a stale table row, or a CRM route admitting `API_USER`. |
| Running `pnpm generate:api` after a backend route change | **No.** The check tells you it is stale; a person still regenerates. |
| Keeping the migration register current as 0014-0019 land | **No.** |
| Reviewing the shared files §8.1 assigns to Dev1 | **No.** |

The shared files Dev1 reviews: `onboarding/exceptions.py`, the entity and
repository indexes, `conftest.py`, `alembic.ini`, `importlinter.ini`, the
route-authorisation test file, and `frontend/src/lib/api/*`,
`src/platform/auth/*`, `src/routes/*`, `layout/Sidebar.tsx`.

---

## 2. Decisions Dev1 is blocked on

These are not Dev1 tasks. Each needs a decision from the programme lead before
anyone writes code.

### 2.1 U1 — who owns the allowed-moves endpoint

**Status: unassigned. This is the one place the target architecture is still
violated in code.**

Section 7.5: *"The server serves allowed moves. The frontend fetches the allowed
journey, gauge and deal moves for the current user instead of keeping
hand-copied tables."*

Today `frontend/src/modules/onboarding/constants.ts:103-139` hand-copies
`PERMITTED_LIFECYCLE_TRANSITIONS`, `COMPLIANCE_GATED_FROM_STATUSES` and
`canMoveLifecycleFrom` from
`backend/app/modules/onboarding/application/exporter_profile_service.py`. The
file says so itself: *"a drifted copy shows officers moves the backend will
reject."*

It was not implemented in any Dev1 phase because it appears in no task list
L1-01 to L1-15, and because the endpoint must cover the journey (Dev2),
qualification (Dev2), conversation (Dev3), background check (Dev4), deals
(Dev3) and the current user's permissions. Building it as Dev1 would absorb
three other developers' contract surface.

**The cost of leaving it unassigned is not neutral.** Dev2, Dev3 and Dev4 each
need a legal-moves table for their own gauge. If the endpoint has no owner when
they start, the likely outcome is **four** hand-copied tables instead of one,
and four places to drift.

**What is needed:** name an owner. If that owner is Dev1, it is a genuine task
and needs adding to the plan; the shape is one endpoint returning, for a given
company and the calling user, the permitted next values per dimension.

### 2.2 U4 — do services stop committing their own transactions

**Status: needs a decision. No primitive is missing.**

The invariant from §3.8 — *"Developers must update both in the same
transaction"* — **holds within a single service call** and is proven:
`test_a_rollback_discards_the_state_change_and_its_history_together` assigns a
status, flushes a history row, rolls back, and asserts in a fresh session that
neither survives. `HistoryService` never commits.

It **does not hold across two service calls.** Ten of the files under
`app/modules/onboarding/application/` commit their own session, so
the §8.2 hand-off "Dev4 signals CLEAR → Dev2 moves the company to CUSTOMER" is
two transactions. A crash between them leaves a company whose check is CLEAR
and whose journey never moved.

**There is nothing to build.** `get_db`
(`app/platform/database/services.py:74`) is already request-scoped and commits
once at the end of the request. The problem is services committing *before* the
request ends, fragmenting a transaction that already exists.

**Why Dev1 has not fixed it:** the commits live in files §8.1 assigns to other
people — `exporter_profile_service.py` (Dev2), `verification_service.py`
(Dev4), `exporter_contact_activity_service.py` (Dev3). Removing them changes
behaviour in three owners' files.

**The decision is:** do services stop calling `commit()` and let `get_db` own
the transaction? If yes, it is a coordinated change across those files, and
whoever makes it needs to check every caller that currently relies on the
commit having happened.

**Raise this before building either hand-off in §8.2, not after.**

### 2.3 U6 — CI does not exist

**Status: external ownership item. Not satisfied, and not claimed to be.**

Verified absent: no `.github/`, no `.gitlab-ci.yml`, no Jenkinsfile, no
pipeline configuration of any kind anywhere in the repository.

Three rules in the plan assume one:

- §7.5 — *"Tests stay at the baseline… Anything else blocks a merge."*
- §7.7 — *"Suite at baseline; frontend builds; no new lint or import-rule violations."*
- Milestone M5 — *"M5 test passes in CI."*

None is enforceable today. Every gate in the Dev1 phases was run by hand.

No CI provider was invented, per the brief. If one is set up, it must run:

```bash
cd backend
alembic heads                     # exactly one
python -m pytest -q --no-cov -p no:cacheprovider
ruff check .
lint-imports --config importlinter.ini   # the --config flag is required;
                                         # the bare command finds no config

cd ../frontend
pnpm tsc -b --noEmit
pnpm eslint .
pnpm vitest run
pnpm build
```

Baseline to compare against: **3,050 passed / 22 failed / 5 errors / 6 skipped**
backend, **24 passed** frontend, **18** ruff findings, **19** import-linter
contracts kept.

---

## 3. Smaller loose ends

**The architecture document is no longer in the repository.**
`docs/Exporter-CRM-Architecture-and-Plan.pdf` was untracked and has been
removed. Decision 12, the role matrix (§3.7) and the twelve settled decisions
live only there. Worth restoring and committing — every contract in
`docs/contracts/` cites it.

**`_actor_type_for` labels a compliance approval `API_CLIENT`.**
`case_service.py:338` maps `TransitionSource.USER_ACTION` to
`ActorType.API_CLIENT`, although `ActorType`'s own docstring says
`COMPLIANCE_OFFICER` covers "any role-gated back-office endpoint". Not a
security defect — the actor id is recorded either way, which was the L1-05 fix.
A semantic correction for whoever owns the legacy case path.

**Eighteen pre-existing ruff findings.** Unchanged through all six Dev1 phases
and deliberately untouched: twelve are in two auto-generated Alembic merge
files, the rest are import ordering that predates this work.

---

## 4. What Dev1 must not do

Listed because each is adjacent enough to look like Dev1's:

- **The allowed-moves endpoint**, until it has an owner (§2.1).
- **Removing `self._db.commit()`** from Dev2/3/4's services (§2.2).
- **Any company, gauge, deal or buyer model.** `DealsPanel` renders `null` and
  `HistoryService.list_for_deal` returns an empty page precisely so that no
  fake model was needed to make a Dev1 test pass.
- **Writing non-`journey` history rows.** The log accepts every dimension; the
  writers belong to the gauge owners.
- **Connecting the case engine, Middesk, Trulioo or Sumsub** (A6, A13).
- **Inventing a CI provider.**

---

## 5. Definition of done for Dev1

Dev1 is finished when:

1. Dev2, Dev3 and Dev4 have acknowledged the three contracts (§1.1).
2. U1 has an owner (§2.1) — not necessarily an implementation, but an owner.
3. U4 has a decision (§2.2).
4. L1-15 is either taken on or explicitly declined by Dev2 (§1.2).

Items 2 and 3 are decisions, not code. Dev1 cannot close them alone, and should
not proceed as though they are closed.
