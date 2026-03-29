# Backend Structure

This backend is organized by responsibility to keep the CV pipeline, API, and realtime updates cleanly separated.

## Entry Point

- Repository-level FastAPI entrypoint: `app.py` at the repo root
- Backend routers mounted there:
  - `backend/api/observations.py`
  - `backend/api/alerts.py`
  - `backend/api/live_events.py`
  - `backend/ws/live.py`
- Optional CV app mount: `/cv` when `cv.main` imports successfully

Run from the repository root:

```bash
pip install -r backend/requirements.txt
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

## Folders
- api: FastAPI routes and request/response schemas
- models: data models and domain objects
- services: CV pipeline, Claude integration, business logic
- ws: WebSocket handlers and realtime broadcast
- config: environment and config templates
- scripts: dev helpers (seed, run, smoke tests)

## Demo Snowflake seeding (dev only)

Use the non-production dev database when seeding weekly mock rows:

```bash
SNOWFLAKE_DATABASE=GRANDMA_MONITOR_DEV python -m backend.scripts.seed_mock_week --include-grandpa --days 7
```

## Insights chat env notes (dev demo)

- Route: `POST /api/insights-chat`
- Snowflake guard: route refuses non-dev DBs unless emergency env `ALLOW_NON_DEV_SNOWFLAKE_FOR_INSIGHTS` is set.
- Cortex model env: `SNOWFLAKE_CORTEX_MODEL` (default: `mistral-large`).
