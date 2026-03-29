USE DATABASE GRANDMA_MONITOR;
USE SCHEMA PUBLIC;

-- Destructive rebuild: drop tables in dependency order
DROP TABLE IF EXISTS DETECTIONS;
DROP TABLE IF EXISTS DAILY_SUMMARIES;
DROP TABLE IF EXISTS ENRICHED_OBSERVATIONS;
DROP TABLE IF EXISTS LIVE_EVENTS;
DROP TABLE IF EXISTS ALERTS;
DROP TABLE IF EXISTS RAW_OBSERVATIONS;

-- Raw observations from RunPod CV pipeline
CREATE TABLE IF NOT EXISTS RAW_OBSERVATIONS (
    ID VARCHAR(36) PRIMARY KEY,


    -- OBSERVED_AT / INSERTED_AT: US Eastern local wall time (America/New_York), TIMESTAMP_NTZ (writers set explicitly).
    OBSERVED_AT TIMESTAMP_NTZ NOT NULL,
    INSERTED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    
    -- Person state
    PERSON_DETECTED BOOLEAN NOT NULL,
    PRIMARY_PERSON_ID VARCHAR(50),
    PRIMARY_DISPLAY_NAME VARCHAR(100),
    IDENTITY_CONFIDENCE FLOAT,


    POSE  VARCHAR(20) NOT NULL,                    -- 'standing', 'sitting', 'lying', 'walking', 'unknown'
    POSE_CONFIDENCE FLOAT NOT NULL,
    
    -- Activity inference
    ACTIVITY STRING,                -- 'eating', 'drinking', 'idle', 'unknown'
    ACTIVITY_CONFIDENCE FLOAT,
    
    -- Context
    OBJECTS_DETECTED VARIANT,         -- ['cup', 'remote', 'book']
    ROOM_HINT VARCHAR(50),               -- expo: typically 'unknown' (no room inference)
    
    -- Alert-relevant flags
    IS_FALL_RISK BOOLEAN DEFAULT FALSE,
    MOTION_LEVEL VARCHAR(10),            -- 'none', 'low', 'normal', 'high'
    MINUTES_SINCE_LAST_SEEN INTEGER DEFAULT 0,
    
    -- Quality metadata
    FRAME_QUALITY FLOAT,
    SESSION_ID VARCHAR(50) NOT NULL,

    -- Optional small JPEG thumbnail (base64) for eating / fall-related rows; capped in CV (e.g. max width 320, Q70).
    FRAME_THUMB_BASE64 VARCHAR
)
CLUSTER BY (OBSERVED_AT);

-- Discrete live feed rows (populated by scheduled task: cortex_live_events.sql). One row per source observation.
CREATE TABLE IF NOT EXISTS LIVE_EVENTS (
    ID VARCHAR(36) PRIMARY KEY DEFAULT UUID_STRING(),

    OBSERVATION_ID VARCHAR(36) NOT NULL UNIQUE REFERENCES RAW_OBSERVATIONS(ID),

    PRIMARY_PERSON_ID VARCHAR(50),
    PRIMARY_DISPLAY_NAME VARCHAR(100),

    EVENT_TYPE VARCHAR(30) NOT NULL,
    OBSERVED_AT TIMESTAMP_NTZ NOT NULL,
    CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),

    MEAL_KIND VARCHAR(20),
    HEADLINE VARCHAR(500),
    SUMMARY VARCHAR

)
CLUSTER BY (OBSERVED_AT);

-- Alerts table (for dashboard display)
CREATE TABLE IF NOT EXISTS ALERTS (
    ID VARCHAR(36) PRIMARY KEY,
    
    OBSERVATION_ID VARCHAR(36),
    
    -- alert details
    ALERT_TYPE  VARCHAR(30) NOT NULL,         -- 'fall_detected', 'no_motion', 'not_seen'
    SEVERITY  VARCHAR(10) NOT NULL,   -- 'critical', 'warning', 'info'
    QUICK_MESSAGE VARCHAR(500),
    
    --timestamps
    -- TRIGGERED_AT / INSERTED_AT: US Eastern local wall time when using Python writers.
    TRIGGERED_AT TIMESTAMP_NTZ NOT NULL,
    INSERTED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),

    -- Dashboard state
    ACKNOWLEDGED BOOLEAN DEFAULT FALSE,
    ACKNOWLEDGED_AT TIMESTAMP_NTZ,
    ACKNOWLEDGED_BY VARCHAR(100),
    
    -- TRY CONTRAINS LATER !!!!!!!!!!!!
    CONSTRAINT fk_observation 
       FOREIGN KEY (OBSERVATION_ID) 
       REFERENCES RAW_OBSERVATIONS(ID)

    
)
CLUSTER BY (TRIGGERED_AT);

-- Cortex-enriched observations
CREATE TABLE IF NOT EXISTS ENRICHED_OBSERVATIONS (
    ID STRING PRIMARY KEY DEFAULT UUID_STRING(),
    OBSERVATION_ID VARCHAR(36) REFERENCES RAW_OBSERVATIONS(ID),
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

CREATE TABLE IF NOT EXISTS DETECTIONS (
    -- Primary Key
    ID VARCHAR(36) PRIMARY KEY,
    
    -- Foreign Key
    OBSERVATION_ID VARCHAR(36) NOT NULL,       -- FK to RAW_OBSERVATIONS.ID
    
    -- Detection Details
    LABEL VARCHAR(50) NOT NULL,                -- 'person', 'cup', 'tv', etc.
    CONFIDENCE FLOAT NOT NULL,                 -- 0.0-1.0
    BBOX VARIANT,                              -- JSON: [x1, y1, x2, y2] normalized 0-1
    
    -- Person-specific (only for LABEL='person')
    PERSON_ID VARCHAR(50),                     -- 'grandma', 'grandpa', 'visitor_1'
    DISPLAY_NAME VARCHAR(100),
    IS_ENROLLED BOOLEAN DEFAULT FALSE,
    IDENTITY_CONFIDENCE FLOAT,
    
    -- Metadata
    INSERTED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    
    -- Constraint
    CONSTRAINT fk_det_observation 
        FOREIGN KEY (OBSERVATION_ID) 
        REFERENCES RAW_OBSERVATIONS(ID)
);
