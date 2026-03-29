USE DATABASE GRANDMA_MONITOR;
USE SCHEMA PUBLIC;
USE WAREHOUSE COMPUTE_WH;

-- Task 1: Enrich observations with natural language (every 5 minutes)
CREATE OR REPLACE TASK ENRICH_OBSERVATIONS
  WAREHOUSE = COMPUTE_WH
  SCHEDULE = '5 MINUTE'
AS
INSERT INTO ENRICHED_OBSERVATIONS (OBSERVATION_ID, NATURAL_DESCRIPTION, WELLNESS_SCORE, CONCERN_FLAGS)
SELECT 
    r.ID as OBSERVATION_ID,
    SNOWFLAKE.CORTEX.COMPLETE(
        'mistral-large',
        'You are a warm, caring assistant helping family members understand how their elderly loved one is doing. ' ||
        'Generate a brief, natural 1-2 sentence observation. Be reassuring but honest. ' ||
        'Input: ' || OBJECT_CONSTRUCT(
            'pose', r.POSE,
            'activity', r.ACTIVITY,
            'objects', r.OBJECTS_DETECTED,
            'room', r.ROOM_HINT,
            'time', TO_CHAR(r.OBSERVED_AT, 'HH12:MI AM')
        )::STRING
    ) as NATURAL_DESCRIPTION,
    -- Wellness score (1-10)
    CASE 
        WHEN r.IS_FALL_RISK THEN 3
        WHEN r.MOTION_LEVEL = 'none' AND r.MINUTES_SINCE_LAST_SEEN > 60 THEN 4
        WHEN r.POSE = 'lying' AND HOUR(r.OBSERVED_AT) BETWEEN 10 AND 20 THEN 5
        WHEN r.ACTIVITY = 'eating' THEN 9
        WHEN r.MOTION_LEVEL = 'normal' THEN 8
        ELSE 7
    END as WELLNESS_SCORE,
    -- Concern flags
    ARRAY_CONSTRUCT_COMPACT(
        IFF(r.POSE = 'lying' AND HOUR(r.OBSERVED_AT) BETWEEN 10 AND 20, 'unusual_rest_time', NULL),
        IFF(r.MOTION_LEVEL = 'none' AND r.MINUTES_SINCE_LAST_SEEN > 30, 'low_activity', NULL),
        IFF(r.IS_FALL_RISK, 'fall_risk', NULL)
    ) as CONCERN_FLAGS
FROM RAW_OBSERVATIONS r
WHERE r.OBSERVED_AT > DATEADD('minute', -6, CURRENT_TIMESTAMP())
  AND r.ID NOT IN (SELECT OBSERVATION_ID FROM ENRICHED_OBSERVATIONS WHERE OBSERVATION_ID IS NOT NULL);

-- Task 2: Generate daily summary (8 PM daily)
CREATE OR REPLACE TASK DAILY_SUMMARY
  WAREHOUSE = COMPUTE_WH
  SCHEDULE = 'USING CRON 0 20 * * * America/New_York'
AS
INSERT INTO DAILY_SUMMARIES (SUMMARY_DATE, SUMMARY_TEXT, TOTAL_OBSERVATIONS, ALERTS_COUNT, AVG_WELLNESS_SCORE, ACTIVE_HOURS)
SELECT
    CURRENT_DATE() as SUMMARY_DATE,
    SNOWFLAKE.CORTEX.COMPLETE(
        'mistral-large',
        'You are a warm, caring assistant. Write a 3-4 sentence daily summary for a family member about their elderly loved one. ' ||
        'Be warm and reassuring. Mention highlights and any concerns gently. ' ||
        'Data: ' || OBJECT_CONSTRUCT(
            'total_observations', stats.total_obs,
            'alerts', stats.alert_count,
            'avg_wellness', stats.avg_wellness,
            'activities_seen', stats.activities,
            'rooms_visited', stats.rooms
        )::STRING) as SUMMARY_TEXT,
    stats.total_obs as TOTAL_OBSERVATIONS,
    stats.alert_count as ALERTS_COUNT,
    stats.avg_wellness as AVG_WELLNESS_SCORE,
    stats.active_hours as ACTIVE_HOURS
FROM (
    SELECT
        COUNT(DISTINCT r.ID) as total_obs,
        COUNT(DISTINCT a.ID) as alert_count,
        AVG(e.WELLNESS_SCORE) as avg_wellness,
        ARRAY_AGG(DISTINCT r.ACTIVITY) as activities,
        ARRAY_AGG(DISTINCT r.ROOM_HINT) as rooms,
        COUNT(DISTINCT HOUR(r.OBSERVED_AT)) as active_hours
    FROM RAW_OBSERVATIONS r
    LEFT JOIN ENRICHED_OBSERVATIONS e ON r.ID = e.OBSERVATION_ID
    LEFT JOIN ALERTS a ON r.ID = a.OBSERVATION_ID
    WHERE DATE(r.OBSERVED_AT) = CURRENT_DATE()
) stats
WHERE NOT EXISTS (
    SELECT 1 FROM DAILY_SUMMARIES WHERE SUMMARY_DATE = CURRENT_DATE()
);

-- Enable tasks
ALTER TASK ENRICH_OBSERVATIONS RESUME;
ALTER TASK DAILY_SUMMARY RESUME;

SHOW TASKS;