import os
import uuid
from datetime import datetime, timezone
from typing import List
import snowflake.connector
from snowflake.connector.pandas_tools import write_pandas
from snowflake.connector.constants import PARAMETER_PYTHON_CONNECTOR_QUERY_RESULT_FORMAT
import pandas as pd

try:
    from models import Observation, Alert
except ModuleNotFoundError:
    from backend.models import Observation, Alert

class SnowflakeClient:
    def __init__(self):
        self.conn = snowflake.connector.connect(
            account=os.getenv('SNOWFLAKE_ACCOUNT'),
            user=os.getenv('SNOWFLAKE_USER'),
            password=os.getenv('SNOWFLAKE_PASSWORD'),
            warehouse='COMPUTE_WH',
            database='GRANDMA_MONITOR',
            schema='PUBLIC',
            session_parameters={
                "PYTHON_CONNECTOR_QUERY_RESULT_FORMAT": "JSON"
            }
        )
        self.observation_buffer: List[dict] = []
        self.alert_buffer: List[dict] = []
        self.BATCH_SIZE = 10
        self.last_flush = datetime.now(timezone.utc)
        self.FLUSH_INTERVAL_SECONDS = 30
    
    def add_observation(self, obs: Observation):
        """Add observation to buffer. Flushes when batch size reached."""
        observed_at = obs.observed_at
        if getattr(observed_at, "tzinfo", None) is not None:
            observed_at = observed_at.astimezone(timezone.utc).replace(tzinfo=None)
        row = {
            'ID': obs.id,
            'OBSERVED_AT': observed_at,
            'PERSON_DETECTED': obs.person_detected,
            'POSE': obs.pose.value if hasattr(obs.pose, 'value') else obs.pose,
            'POSE_CONFIDENCE': obs.pose_confidence,
            'ACTIVITY': obs.activity.value if hasattr(obs.activity, 'value') else obs.activity,
            'ACTIVITY_CONFIDENCE': obs.activity_confidence,
            'OBJECTS_DETECTED': obs.objects_detected,
            'ROOM_HINT': obs.room_hint,
            'IS_FALL_RISK': obs.is_fall_risk,
            'MOTION_LEVEL': obs.motion_level.value if hasattr(obs.motion_level, 'value') else obs.motion_level,
            'MINUTES_SINCE_LAST_SEEN': obs.minutes_since_last_seen,
            'FRAME_QUALITY': obs.frame_quality,
            'SESSION_ID': obs.session_id
        }
        self.observation_buffer.append(row)
        
        if len(self.observation_buffer) >= self.BATCH_SIZE:
            self.flush()
    
    def add_alert(self, alert: Alert):
        """Add alert to buffer. Alerts are also flushed with observations."""
        triggered_at = alert.triggered_at
        if getattr(triggered_at, "tzinfo", None) is not None:
            triggered_at = triggered_at.astimezone(timezone.utc).replace(tzinfo=None)
        row = {
            'ID': alert.id,
            'OBSERVATION_ID': alert.observation_id,
            'ALERT_TYPE': alert.alert_type,
            'SEVERITY': alert.severity.value if hasattr(alert.severity, 'value') else alert.severity,
            'TRIGGERED_AT': triggered_at,
            'QUICK_MESSAGE': alert.quick_message,
            'ACKNOWLEDGED': alert.acknowledged
        }
        self.alert_buffer.append(row)
        
        # Alerts are high priority - flush immediately
        self.flush()
    
    def flush(self):
        """Write buffered data to Snowflake."""
        
        cursor = self.conn.cursor()
        
        try:
            # Flush observations
            if self.observation_buffer:
                df = pd.DataFrame(self.observation_buffer)
                write_pandas(
                    self.conn,
                    df,
                    'RAW_OBSERVATIONS',
                    auto_create_table=False,
                    use_logical_type=True
                )
                print(f"[SNOWFLAKE] Flushed {len(self.observation_buffer)} observations")
                self.observation_buffer = []
            
            # Flush alerts
            if self.alert_buffer:
                df = pd.DataFrame(self.alert_buffer)
                write_pandas(
                    self.conn,
                    df,
                    'ALERTS',
                    auto_create_table=False,
                    use_logical_type=True
                )
                print(f"[SNOWFLAKE] Flushed {len(self.alert_buffer)} alerts")
                self.alert_buffer = []
            
            self.last_flush = datetime.now(timezone.utc)
            
        except Exception as e:
            print(f"[SNOWFLAKE ERROR] Flush failed: {e}")
            raise
        finally:
            cursor.close()
    
    def check_flush_needed(self):
        """Check if time-based flush is needed."""
        elapsed = (datetime.now(timezone.utc)- self.last_flush).total_seconds()
        if elapsed > self.FLUSH_INTERVAL_SECONDS and self.observation_buffer:
            self.flush()
        
    # mark alert as acknowledge
    def update_alert_acknowledged(self, alert_id: str, acknowledged_by: str):
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                UPDATE ALERTS 
                SET ACKNOWLEDGED = TRUE,
                    ACKNOWLEDGED_AT = CURRENT_TIMESTAMP(),
                    ACKNOWLEDGED_BY = %s
                WHERE ID = %s
            """, (acknowledged_by, alert_id))
            self.conn.commit()
        finally:
            cursor.close()
    # fetch recent observations made for dashboard
    def get_recent_observations(self, limit: int = 50) -> List[dict]:
        cursor = self.conn.cursor()
        try:
            cursor.execute(f"""
                SELECT
                    ID,
                    TO_VARCHAR(OBSERVED_AT) AS OBSERVED_AT,
                    PERSON_DETECTED,
                    POSE,
                    POSE_CONFIDENCE,
                    ACTIVITY,
                    ACTIVITY_CONFIDENCE,
                    OBJECTS_DETECTED,
                    ROOM_HINT,
                    IS_FALL_RISK,
                    MOTION_LEVEL,
                    MINUTES_SINCE_LAST_SEEN,
                    FRAME_QUALITY,
                    SESSION_ID,
                    TO_VARCHAR(INSERTED_AT) AS INSERTED_AT
                FROM RAW_OBSERVATIONS 
                ORDER BY OBSERVED_AT DESC 
                LIMIT %s
            """, (limit,), _statement_params={PARAMETER_PYTHON_CONNECTOR_QUERY_RESULT_FORMAT: "JSON"})
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        finally:
            cursor.close()
    # ackowledgement alert for dashboard
    def get_unacknowledged_alerts(self) -> List[dict]:
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                SELECT
                    ID,
                    OBSERVATION_ID,
                    ALERT_TYPE,
                    SEVERITY,
                    TO_VARCHAR(TRIGGERED_AT) AS TRIGGERED_AT,
                    QUICK_MESSAGE,
                    ACKNOWLEDGED,
                    TO_VARCHAR(ACKNOWLEDGED_AT) AS ACKNOWLEDGED_AT,
                    ACKNOWLEDGED_BY,
                    TO_VARCHAR(INSERTED_AT) AS INSERTED_AT
                FROM ALERTS 
                WHERE ACKNOWLEDGED = FALSE 
                ORDER BY TRIGGERED_AT DESC
            """,_statement_params={PARAMETER_PYTHON_CONNECTOR_QUERY_RESULT_FORMAT: "JSON"})
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        finally:
            cursor.close()
    # flush the remaining data and close connection
    def close(self):
        self.flush()
        self.conn.close()
