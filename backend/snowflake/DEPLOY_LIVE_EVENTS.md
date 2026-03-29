# Deploying live events + frame thumbnails (Snowflake)

This guide is for whoever manages **GRANDMA_MONITOR.PUBLIC**. It covers the schema additions for **Raw observation thumbnails** and the **LIVE_EVENTS** feed, plus the **CORTEX_LIVE_EVENTS** scheduled task that fills that feed.

Coordinate with whoever deploys the CV service: the **`RAW_OBSERVATIONS.FRAME_THUMB_BASE64`** column should exist **before** running a CV build that writes that column (or the app may error on `write_pandas`).

---

## Prerequisites

- **Database / schema:** `GRANDMA_MONITOR.PUBLIC` (adjust `USE` statements in the scripts if your names differ).
- **Warehouse:** Scripts assume **`COMPUTE_WH`**; change if you use another default warehouse for tasks.
- **Privileges:** Role can run DDL (`ALTER TABLE`, `CREATE TABLE`, `CREATE TASK`), `USAGE` on the warehouse, and `SELECT`/`INSERT` on the relevant tables.
- **Cortex:** [Snowflake Cortex](https://docs.snowflake.com/en/user-guide/snowflake-cortex) enabled for the account; the task calls **`SNOWFLAKE.CORTEX.COMPLETE('mistral-large', ...)`**. If **`mistral-large`** is not entitled in your account, edit `cortex_live_events.sql` and replace it with a model your account supports before creating/replacing the task.
- **Timezone:** Writers and this task assume **America/New_York** for local wall time on `TIMESTAMP_NTZ` fields (consistent with existing Python clients).

---

## Current implementation specification

This section describes the live-events feature **as currently implemented in this repository**, across the CV service, Snowflake, and frontend dashboard.

### End-to-end flow

1. The CV API processes frames in **`cv/main.py`**.
2. When a persisted observation is relevant to the live feed, the CV API may attach **`frame_thumb_base64`** to the observation before Snowflake write.
3. **`cv/snowflake_client.py`** writes raw observations to **`RAW_OBSERVATIONS`** and alerts to **`ALERTS`**, storing local **America/New_York** wall time in `TIMESTAMP_NTZ` columns.
4. The Snowflake task **`CORTEX_LIVE_EVENTS`** runs every **2 minutes** and inserts deduplicated rows into **`LIVE_EVENTS`** from:
   - eating observations in **`RAW_OBSERVATIONS`**
   - fall alerts in **`ALERTS`** joined back to **`RAW_OBSERVATIONS`**
5. The CV API endpoint **`GET /api/live-events`** reads from **`LIVE_EVENTS`**, joins back to **`RAW_OBSERVATIONS`** for thumbnails, and returns JSON to consumers.
6. The Next.js route handler **`frontend/app/api/live-events/route.ts`** proxies browser requests to the CV API.
7. The dashboard page **`frontend/app/dashboard/page.tsx`** polls that route every **120 seconds** and renders the returned event cards.

### Data specification

#### `RAW_OBSERVATIONS.FRAME_THUMB_BASE64`

- Type: nullable `VARCHAR`
- Encoding: base64 ASCII for a JPEG image
- Current CV encoder behavior:
  - max width **320 px**
  - JPEG quality **70**
  - stored without requiring a `data:` URL prefix
- Current write conditions in the CV app:
  - the observation has a fall alert (`alert_type = 'fall_detected'`), or
  - `obs.is_fall_risk = true`, or
  - `obs.activity = 'eating'`

#### `LIVE_EVENTS`

Each row represents **one user-facing feed event** derived from exactly one raw observation.

| Column | Type | Current meaning |
|------|------|---------|
| `ID` | `VARCHAR(36)` | Event row ID (`UUID_STRING()` by default) |
| `OBSERVATION_ID` | `VARCHAR(36)` | Source raw observation ID; unique, so one raw row yields at most one live event |
| `PRIMARY_PERSON_ID` | `VARCHAR(50)` | Enrolled subject ID if known |
| `PRIMARY_DISPLAY_NAME` | `VARCHAR(100)` | Display name if known |
| `EVENT_TYPE` | `VARCHAR(30)` | Currently `eating` or `fall_detected` |
| `OBSERVED_AT` | `TIMESTAMP_NTZ` | Source event time in America/New_York wall time |
| `CREATED_AT` | `TIMESTAMP_NTZ` | Time the live-event row was inserted |
| `MEAL_KIND` | `VARCHAR(20)` | Currently `breakfast`, `lunch`, `dinner`, `snack`, or `NULL` |
| `HEADLINE` | `VARCHAR(500)` | Short display title generated in SQL |
| `SUMMARY` | `VARCHAR` | Cortex-generated short paragraph |

### Event generation rules

#### Eating events

- Source rows come from **`RAW_OBSERVATIONS`** where `ACTIVITY = 'eating'`.
- Only observations from roughly the **last 7 days** are considered.
- Already-processed observations are skipped using `NOT EXISTS` against **`LIVE_EVENTS`**.
- Meal windows are determined entirely in SQL from local time:
  - before `12:00:00` => `breakfast`
  - before `17:30:00` => `lunch`
  - otherwise => `dinner`
- Ranking is partitioned by:
  - `COALESCE(PRIMARY_PERSON_ID, '_none')`
  - `DATE(OBSERVED_AT)`
  - the base meal window
- The **first** eating observation in a given partition keeps the meal window (`breakfast` / `lunch` / `dinner`).
- Any later eating observations in that same partition become **`snack`** events.

#### Fall events

- Source rows come from **`ALERTS`** where `ALERT_TYPE = 'fall_detected'`.
- Each alert is joined to its source row in **`RAW_OBSERVATIONS`** by `OBSERVATION_ID`.
- Only rows from roughly the **last 7 days** are considered.
- Already-processed observations are skipped using `NOT EXISTS` against **`LIVE_EVENTS`**.

#### Shared insertion behavior

- The task unions eating candidates and fall candidates, then inserts them into **`LIVE_EVENTS`**.
- Headline generation is deterministic:
  - fall event => `"<display name>: possible fall detected"` with fallback `"Your loved one"`
  - meal/snack event => `"<display name> — <MealKind>"` with fallback `"Your loved one"`
  - final fallback => `"Update from home monitoring"`
- `SUMMARY` is generated by **`SNOWFLAKE.CORTEX.COMPLETE`** with a prompt that asks for:
  - one short paragraph
  - 2 to 4 sentences
  - reassuring but factual tone
  - no invented medical details

### API specification

#### CV API endpoint

**Route:** `GET /api/live-events`

**Query parameters**

| Name | Type | Default | Current validation |
|------|------|---------|--------------------|
| `minutes` | integer | `30` | `1 <= minutes <= 10080` |
| `limit` | integer | `50` | `1 <= limit <= 200` |

**Current response shape**

```json
{
  "timezone": "America/New_York",
  "events": [
    {
      "id": "evt-1",
      "event_type": "eating",
      "headline": "Grandma — Lunch",
      "summary": "Grandma appears to be having lunch in a calm setting.",
      "meal_kind": "lunch",
      "observed_at": "2026-03-29T12:00:00-04:00",
      "display_name": "Grandma",
      "frame_thumb_base64": "<base64-jpeg-or-null>"
    }
  ]
}
```

**Field notes**

- `observed_at` is returned as an ISO-8601 string with the **America/New_York** offset applied.
- `frame_thumb_base64` may be `null`.
- The frontend currently accepts either:
  - plain base64 JPEG content, or
  - a full `data:image/jpeg;base64,...` URL

#### Frontend proxy behavior

- **`frontend/app/api/live-events/route.ts`** forwards:
  - `minutes`
  - `limit`
- Upstream base URL comes from `CV_API_BASE`, defaulting to `http://127.0.0.1:8080`.
- Errors are passed through as JSON when possible; connection failures return HTTP `500` with `{ "error": "Failed to connect to CV server" }`.

### Deployment acceptance criteria

After deployment is complete, the current implementation should satisfy all of the following:

1. **Schema ready**
   - `RAW_OBSERVATIONS` includes `FRAME_THUMB_BASE64`
   - `LIVE_EVENTS` exists with `OBSERVATION_ID` unique and FK-linked to `RAW_OBSERVATIONS.ID`
2. **Task ready**
   - `CORTEX_LIVE_EVENTS` exists
   - schedule is `2 MINUTE`
   - task state is `STARTED` / resumed
3. **Data path works**
   - a new eating observation or `fall_detected` alert leads to a `LIVE_EVENTS` row after the task runs
   - repeated task runs do not create duplicate live events for the same observation
4. **API contract works**
   - `GET /api/live-events?minutes=30&limit=10` returns HTTP `200`
   - response contains `timezone` and `events`
   - returned rows are ordered by `OBSERVED_AT DESC`
5. **Dashboard contract works**
   - the dashboard can render rows with or without thumbnails
   - empty state is shown when there are no recent events
   - the dashboard poll cadence remains aligned with the Snowflake task cadence (currently 2 minutes)

---

## Step 1 — Schema migration (existing database)

For an **already provisioned** schema (do **not** run the destructive `schema.sql` full rebuild on prod):

1. Open a worksheet as the appropriate role.
2. Run the full script:

   **`backend/snowflake/migrate_frame_thumb_and_live_events.sql`**

   This will:

   - Add **`FRAME_THUMB_BASE64`** (nullable `VARCHAR`) to **`RAW_OBSERVATIONS`** if missing.
   - Create **`LIVE_EVENTS`** if it does not exist (FK to **`RAW_OBSERVATIONS.ID`** via **`OBSERVATION_ID`**, unique constraint so each raw row yields at most one live event).

3. Verify:

   ```sql
   DESCRIBE TABLE RAW_OBSERVATIONS;
   DESCRIBE TABLE LIVE_EVENTS;
   ```

---

## Step 2 — Greenfield / full rebuild (optional)

If you are **rebuilding** the schema from scratch in a dev/sandbox only, use **`backend/snowflake/schema.sql`**. It is **destructive** (drops and recreates tables). It already includes **`FRAME_THUMB_BASE64`** and **`LIVE_EVENTS`** in the correct dependency order.

Do **not** use `schema.sql` against production without a backup and explicit approval.

---

## Step 3 — Deploy or update the Cortex task

1. Ensure Step 1 (or Step 2) completed successfully and **`LIVE_EVENTS`** exists.
2. Run:

   **`backend/snowflake/cortex_live_events.sql`**

   This script:

   - Sets session timezone to **`America/New_York`**.
   - **`CREATE OR REPLACE TASK CORTEX_LIVE_EVENTS`** with **`SCHEDULE = '2 MINUTE'`**.
   - Defines the **`INSERT INTO LIVE_EVENTS ...`** logic (eating + meal/snack windows in SQL, fall rows from **`ALERTS`**, **`CORTEX.COMPLETE`** for **`SUMMARY`** only).
   - Ends with **`ALTER TASK CORTEX_LIVE_EVENTS RESUME`**.

3. **First-time caution:** If you prefer to validate the `INSERT` logic manually before automation runs, you can:

   - **`ALTER TASK CORTEX_LIVE_EVENTS SUSPEND;`**
   - Copy the `INSERT ... SELECT` payload from the task definition into a worksheet, run as a **limited** test (e.g. extra `WHERE` on time or `LIMIT` via a wrapper), then **`RESUME`** when satisfied.

4. Confirm task state:

   ```sql
   SHOW TASKS LIKE 'CORTEX_LIVE_EVENTS' IN SCHEMA GRANDMA_MONITOR.PUBLIC;
   ```

5. **Task history / failures:** Use **`TASK_HISTORY`** (or Snowflake’s Tasks UI) to debug errors (common issues: Cortex permissions, model name, warehouse suspended, or missing table/column).

---

## Step 4 — Application coordination (not Snowflake-only)

After **`FRAME_THUMB_BASE64`** exists:

- Deploy the **CV** service that writes **`FRAME_THUMB_BASE64`** on selected frames (eating / fall-risk / fall-alert paths). Until then, the column remains NULL.

**`LIVE_EVENTS`** rows appear only after:

- New qualifying raw rows (and/or alerts) exist, and  
- The **`CORTEX_LIVE_EVENTS`** task has run successfully.

---

## Quick reference — files

| File | Purpose |
|------|---------|
| `migrate_frame_thumb_and_live_events.sql` | Safe migration for existing DBs |
| `schema.sql` | Full rebuild (destructive); includes thumb + `LIVE_EVENTS` |
| `cortex_live_events.sql` | `CORTEX_LIVE_EVENTS` task (2-minute schedule) |
| `cortex_tasks.sql` | Existing **ENRICH_OBSERVATIONS** / **DAILY_SUMMARY** tasks (unchanged by this feature) |

---

## Operational notes

- **Cost / storage:** Thumbnails are small JPEGs (CV caps width, moderate quality). **`LIVE_EVENTS.SUMMARY`** is generated by Cortex each inserted row — monitor **task credits** and Cortex usage.
- **Lookback:** The task only considers raw observations (and fall joins) from roughly the **last 7 days** that are **not** already in **`LIVE_EVENTS`**; adjust the `DATEADD('day', -7, ...)` window in `cortex_live_events.sql` if you need a different retention for backfill.
- **Model change:** If you swap `mistral-large` for another model, use **`CREATE OR REPLACE TASK`** again (or run the whole `cortex_live_events.sql` script after editing the model string).
