# E9 — Screening Review Workspace

E9 moves the E8 screening workspace from browser-only prototype state to a backend-backed compliance review workflow.

## Added

- Persistent screening review checklist (status + comment + reviewer + timestamp).
- Bank activity API contract for Surepass/Finpass-style suspicious-activity findings.
- Bank activity UI backed by the API; returns an honest empty state until a provider feed is connected.
- Compliance/Admin users can edit checklist decisions; other roles can read them.
- Existing provider verification results and compliance decision flow remain intact.
- E8 manual stub checks remain non-decisive (`PENDING`) and do not fabricate pass/fail outcomes.

## New backend routes

- `GET /api/v1/onboarding/exporters/{customer_id}/screening-review`
- `PUT /api/v1/onboarding/exporters/{customer_id}/screening-review/{item_key}`
- `GET /api/v1/onboarding/exporters/{customer_id}/bank-activity`

## Database migration

Run:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m alembic upgrade head
```

Migration added: `onboarding_0010_screen_review`.

## Local test sequence

Backend:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m alembic upgrade head
python -m uvicorn app.main:app --reload --port 8000
```

Frontend:

```powershell
cd frontend
pnpm install
pnpm test
pnpm run typecheck
pnpm run build
pnpm run dev
```

## Deliberate gap

E9 does not invent bank transactions or suspicious-activity flags. The bank findings table/API is ready for provider ingestion, but Surepass/Finpass is not connected yet.
