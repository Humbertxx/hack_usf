-- activities 

CREATE TABLE IF NOT EXISTS ACTIVITY_EVENTS (
    -- Primary Key
    ID VARCHAR(36) PRIMARY KEY,
    
    -- Person Identification
    PERSON_ID VARCHAR(50),                     -- 'grandma', 'grandpa', 'visitor_1'
    DISPLAY_NAME VARCHAR(100),                 -- 'Grandma', 'Grandpa'
    
    -- Event Type
    EVENT_TYPE VARCHAR(50) NOT NULL,           -- See event types below
    
    -- Timestamps (ALL in UTC) - CRITICAL FOR GENAI
    EVENT_STARTED_AT TIMESTAMP_NTZ NOT NULL,   -- When activity began
    EVENT_ENDED_AT TIMESTAMP_NTZ,              -- When activity ended (NULL if ongoing)
    DURATION_MINUTES INTEGER,                  -- Calculated duration
    
    -- Confidence & Context
    CONFIDENCE FLOAT,                          -- Average confidence across observations
    OBJECTS_CONTEXT VARIANT,                   -- JSON array of objects seen during event
    
    -- GenAI Output
    GENAI_SUMMARY VARCHAR(1000),               -- AI-generated description (populated later)
    
    -- Metadata
    SESSION_ID VARCHAR(50),
    INSERTED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- Index for recent events (dashboard polling)
CREATE INDEX IF NOT EXISTS idx_events_started 
ON ACTIVITY_EVENTS (EVENT_STARTED_AT DESC);

-- Index for person-specific event history
CREATE INDEX IF NOT EXISTS idx_events_person 
ON ACTIVITY_EVENTS (PERSON_ID, EVENT_STARTED_AT DESC);

-- Enable the task
ALTER TASK AGGREGATE_ACTIVITY_EVENTS RESUME;