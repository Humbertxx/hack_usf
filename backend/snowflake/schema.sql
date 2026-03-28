USE DATABASE GRANDMA_MONITOR;
USE SCHEMA PUBLIC;

-- Raw observations from RunPod CV pipeline
CREATE TABLE IF NOT EXISTS RAW_OBSERVATIONS (
    ID STRING PRIMARY KEY,
    OBSERVED_AT TIMESTAMP_NTZ NOT NULL,
    
    -- Person state
    PERSON_DETECTED BOOLEAN NOT NULL,
    POSE STRING,                    -- 'standing', 'sitting', 'lying', 'walking', 'unknown'
    POSE_CONFIDENCE FLOAT,
    
    -- Activity inference
    ACTIVITY STRING,                -- 'eating', 'watching_tv', 'sleeping', 'cooking', 'idle'
    ACTIVITY_CONFIDENCE FLOAT,
    
    -- Context
    OBJECTS_DETECTED ARRAY,         -- ['cup', 'remote', 'book']
    ROOM_HINT STRING,               -- 'kitchen', 'living_room', 'bedroom'
    
    -- Alert-relevant flags
    IS_FALL_RISK BOOLEAN DEFAULT FALSE,
    MOTION_LEVEL STRING,            -- 'none', 'low', 'normal', 'high'
    MINUTES_SINCE_LAST_SEEN INT DEFAULT 0,
    
    -- Quality metadata
    FRAME_QUALITY FLOAT,
    SESSION_ID STRING,
    
    -- Audit
    INSERTED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
)
CLUSTER BY (OBSERVED_AT);

-- Alerts table (for dashboard display)
CREATE TABLE IF NOT EXISTS ALERTS (
    ID STRING PRIMARY KEY,
    OBSERVATION_ID STRING REFERENCES RAW_OBSERVATIONS(ID),
    ALERT_TYPE STRING NOT NULL,         -- 'fall_detected', 'no_motion', 'not_seen'
    SEVERITY STRING NOT NULL,           -- 'critical', 'warning', 'info'
    TRIGGERED_AT TIMESTAMP_NTZ NOT NULL,
    
    -- Human-friendly message (pre-computed, no Cortex delay)
    QUICK_MESSAGE STRING,
    
    -- Dashboard state
    ACKNOWLEDGED BOOLEAN DEFAULT FALSE,
    ACKNOWLEDGED_AT TIMESTAMP_NTZ,
    ACKNOWLEDGED_BY STRING,
    
    -- Audit
    INSERTED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
)
CLUSTER BY (TRIGGERED_AT);

-- Cortex-enriched observations
CREATE TABLE IF NOT EXISTS ENRICHED_OBSERVATIONS (
    ID STRING PRIMARY KEY DEFAULT UUID_STRING(),
    OBSERVATION_ID STRING REFERENCES RAW_OBSERVATIONS(ID),
    ENRICHED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    
    -- Cortex-generated content
    NATURAL_DESCRIPTION STRING,     -- "Grandma is sitting in the living room..."
    WELLNESS_SCORE INT,             -- 1-10
    CONCERN_FLAGS ARRAY,            -- ['prolonged_sitting', 'skipped_lunch']
    
    -- Summary flag
    IS_DAILY_SUMMARY BOOLEAN DEFAULT FALSE
);

-- Daily summaries (aggregated by Cortex)
CREATE TABLE IF NOT EXISTS DAILY_SUMMARIES (
    ID STRING PRIMARY KEY DEFAULT UUID_STRING(),
    SUMMARY_DATE DATE NOT NULL,
    GENERATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    
    -- Cortex-generated narrative
    SUMMARY_TEXT STRING,
    
    -- Metrics
    TOTAL_OBSERVATIONS INT,
    ALERTS_COUNT INT,
    AVG_WELLNESS_SCORE FLOAT,
    ACTIVE_HOURS FLOAT,
    
    UNIQUE (SUMMARY_DATE)
)
CLUSTER BY (SUMMARY_DATE);
