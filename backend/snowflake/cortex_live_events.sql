-- Live dashboard feed: meal/snack windows in SQL + Cortex summary per row.
--
-- Prerequisites:
--   * GRANDMA_MONITOR.PUBLIC migrated (RAW_OBSERVATIONS.FRAME_THUMB_BASE64, LIVE_EVENTS) — see migrate_frame_thumb_and_live_events.sql
--   * Snowflake Cortex enabled; mistral-large (or substitute) available to the role running the task
--   * Role may USE WAREHOUSE COMPUTE_WH and INSERT/SELECT on the tables below
--
-- Event sources (deduped by LIVE_EVENTS.OBSERVATION_ID unique):
--   * ACTIVITY = 'eating' with breakfast/lunch/dinner vs snack from ROW_NUMBER() in the same local calendar day window
--   * ALERTS.ALERT_TYPE = 'fall_detected' joined to the triggering RAW_OBSERVATIONS row
--
-- After first deploy: ALTER TASK CORTEX_LIVE_EVENTS RESUME;

USE DATABASE GRANDMA_MONITOR;
USE SCHEMA PUBLIC;
USE WAREHOUSE COMPUTE_WH;

ALTER SESSION SET TIMEZONE = 'America/New_York';

CREATE OR REPLACE TASK CORTEX_LIVE_EVENTS
  WAREHOUSE = COMPUTE_WH
  SCHEDULE = '2 MINUTE'
AS
INSERT INTO LIVE_EVENTS (
    ID,
    OBSERVATION_ID,
    PRIMARY_PERSON_ID,
    PRIMARY_DISPLAY_NAME,
    EVENT_TYPE,
    OBSERVED_AT,
    CREATED_AT,
    MEAL_KIND,
    HEADLINE,
    SUMMARY
)
WITH eating_base AS (
    SELECT
        r.ID,
        r.OBSERVED_AT,
        r.PRIMARY_PERSON_ID,
        r.PRIMARY_DISPLAY_NAME,
        r.POSE,
        r.ACTIVITY,
        r.OBJECTS_DETECTED,
        CASE
            WHEN CAST(r.OBSERVED_AT AS TIME) < TO_TIME('12:00:00') THEN 'breakfast'
            WHEN CAST(r.OBSERVED_AT AS TIME) < TO_TIME('17:30:00') THEN 'lunch'
            ELSE 'dinner'
        END AS base_meal_window
    FROM RAW_OBSERVATIONS r
    WHERE r.ACTIVITY = 'eating'
      AND r.OBSERVED_AT > DATEADD('day', -7, CURRENT_TIMESTAMP())
      AND NOT EXISTS (SELECT 1 FROM LIVE_EVENTS e WHERE e.OBSERVATION_ID = r.ID)
),
eating_ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY COALESCE(PRIMARY_PERSON_ID, '_none'), DATE(OBSERVED_AT), base_meal_window
            ORDER BY OBSERVED_AT
        ) AS rn
    FROM eating_base
),
eating_candidates AS (
    SELECT
        ID AS OBSERVATION_ID,
        OBSERVED_AT,
        PRIMARY_PERSON_ID,
        PRIMARY_DISPLAY_NAME,
        POSE,
        ACTIVITY,
        OBJECTS_DETECTED,
        'eating' AS EVENT_TYPE,
        IFF(rn = 1, base_meal_window, 'snack') AS MEAL_KIND
    FROM eating_ranked
),
fall_candidates AS (
    SELECT
        r.ID AS OBSERVATION_ID,
        r.OBSERVED_AT,
        r.PRIMARY_PERSON_ID,
        r.PRIMARY_DISPLAY_NAME,
        r.POSE,
        r.ACTIVITY,
        r.OBJECTS_DETECTED,
        'fall_detected' AS EVENT_TYPE,
        CAST(NULL AS VARCHAR(20)) AS MEAL_KIND
    FROM RAW_OBSERVATIONS r
    INNER JOIN ALERTS a
        ON a.OBSERVATION_ID = r.ID
        AND a.ALERT_TYPE = 'fall_detected'
    WHERE r.OBSERVED_AT > DATEADD('day', -7, CURRENT_TIMESTAMP())
      AND NOT EXISTS (SELECT 1 FROM LIVE_EVENTS e WHERE e.OBSERVATION_ID = r.ID)
),
candidates AS (
    SELECT * FROM eating_candidates
    UNION ALL
    SELECT * FROM fall_candidates
)
SELECT
    UUID_STRING(),
    c.OBSERVATION_ID,
    c.PRIMARY_PERSON_ID,
    c.PRIMARY_DISPLAY_NAME,
    c.EVENT_TYPE,
    c.OBSERVED_AT,
    CURRENT_TIMESTAMP(),
    c.MEAL_KIND,
    CASE
        WHEN c.EVENT_TYPE = 'fall_detected' THEN
            COALESCE(c.PRIMARY_DISPLAY_NAME, 'Your loved one') || ': possible fall detected'
        WHEN c.MEAL_KIND IS NOT NULL THEN
            COALESCE(c.PRIMARY_DISPLAY_NAME, 'Your loved one') || ' — ' || INITCAP(c.MEAL_KIND)
        ELSE
            'Update from home monitoring'
    END AS HEADLINE,
    SNOWFLAKE.CORTEX.COMPLETE(
        'mistral-large',
        'You are a warm, concise assistant for a family care dashboard. Write ONE short paragraph (2-4 sentences) summarizing this event for relatives. Be reassuring but factual. Do not invent medical details. '
        || 'Input: ' || OBJECT_CONSTRUCT(
            'event_type', c.EVENT_TYPE,
            'pose', c.POSE,
            'activity', c.ACTIVITY,
            'objects', c.OBJECTS_DETECTED,
            'display_name', c.PRIMARY_DISPLAY_NAME,
            'meal_kind', c.MEAL_KIND,
            'alert_type', IFF(c.EVENT_TYPE = 'fall_detected', 'fall_detected', NULL),
            'local_time_eastern', TO_CHAR(c.OBSERVED_AT, 'YYYY-MM-DD HH12:MI:SS AM')
        )::STRING
    ) AS SUMMARY
FROM candidates c;

ALTER TASK CORTEX_LIVE_EVENTS RESUME;

SHOW TASKS;
