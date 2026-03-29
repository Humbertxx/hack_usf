"""
Snowflake client for CV pipeline.

Handles writing observations and alerts to Snowflake with identity support.
Uses cv.models (Pydantic) which include primary person fields.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import List, Optional

from cv.models import Alert, Observation


class SnowflakeClient:
    """
    Real Snowflake client for production use.
    
    Requires environment variables:
        SNOWFLAKE_ACCOUNT
        SNOWFLAKE_USER
        SNOWFLAKE_PASSWORD
        SNOWFLAKE_WAREHOUSE (default: COMPUTE_WH)
        SNOWFLAKE_DATABASE (default: GRANDMA_MONITOR)
        SNOWFLAKE_SCHEMA (default: PUBLIC)
    """
    
    def __init__(self) -> None:
        import snowflake.connector
        from snowflake.connector.pandas_tools import write_pandas
        
        self._write_pandas = write_pandas
        
        self.conn = snowflake.connector.connect(
            account=os.getenv("SNOWFLAKE_ACCOUNT"),
            user=os.getenv("SNOWFLAKE_USER"),
            password=os.getenv("SNOWFLAKE_PASSWORD"),
            warehouse=os.getenv("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"),
            database=os.getenv("SNOWFLAKE_DATABASE", "GRANDMA_MONITOR"),
            schema=os.getenv("SNOWFLAKE_SCHEMA", "PUBLIC"),
            session_parameters={
                "PYTHON_CONNECTOR_QUERY_RESULT_FORMAT": "JSON"
            }
        )
        
        self.observation_buffer: List[dict] = []
        self.alert_buffer: List[dict] = []
        self.BATCH_SIZE = 10
        self.last_flush = datetime.now(timezone.utc)
        self.FLUSH_INTERVAL_SECONDS = 30
        
        print(f"[SnowflakeClient] Connected to {os.getenv('SNOWFLAKE_DATABASE', 'GRANDMA_MONITOR')}")
    
    def add_observation(self, obs: Observation) -> None:
        """Add observation to buffer. Flushes when batch size reached."""
        observed_at = obs.observed_at
        if getattr(observed_at, "tzinfo", None) is not None:
            observed_at = observed_at.astimezone(timezone.utc).replace(tzinfo=None)
        
        row = {
            "ID": obs.id,
            "OBSERVED_AT": observed_at,
            "PERSON_DETECTED": obs.person_detected,
            "PRIMARY_PERSON_ID": obs.primary_person_id,
            "PRIMARY_DISPLAY_NAME": obs.primary_display_name,
            "IDENTITY_CONFIDENCE": obs.primary_identity_confidence,
            "POSE": obs.pose.value if hasattr(obs.pose, "value") else obs.pose,
            "POSE_CONFIDENCE": obs.pose_confidence,
            "ACTIVITY": obs.activity.value if hasattr(obs.activity, "value") else obs.activity,
            "ACTIVITY_CONFIDENCE": obs.activity_confidence,
            "OBJECTS_DETECTED": json.dumps(obs.objects_detected),
            "ROOM_HINT": obs.room_hint,
            "IS_FALL_RISK": obs.is_fall_risk,
            "MOTION_LEVEL": obs.motion_level.value if hasattr(obs.motion_level, "value") else obs.motion_level,
            "MINUTES_SINCE_LAST_SEEN": obs.minutes_since_last_seen,
            "FRAME_QUALITY": obs.frame_quality,
            "SESSION_ID": obs.session_id,
        }
        self.observation_buffer.append(row)
        
        identity_info = ""
        if obs.primary_person_id:
            conf = obs.primary_identity_confidence or 0.0
            identity_info = f" | {obs.primary_display_name} (conf={conf:.2f})"
        print(f"[SNOWFLAKE] Buffered observation: {obs.id} - {obs.pose} - {obs.activity}{identity_info}")
        
        if len(self.observation_buffer) >= self.BATCH_SIZE:
            self.flush()
    
    def add_alert(self, alert: Alert) -> None:
        """Add alert to buffer. Alerts are high priority - flush immediately."""
        triggered_at = alert.triggered_at
        if getattr(triggered_at, "tzinfo", None) is not None:
            triggered_at = triggered_at.astimezone(timezone.utc).replace(tzinfo=None)
        
        row = {
            "ID": alert.id,
            "OBSERVATION_ID": alert.observation_id,
            "ALERT_TYPE": alert.alert_type,
            "SEVERITY": alert.severity.value if hasattr(alert.severity, "value") else alert.severity,
            "TRIGGERED_AT": triggered_at,
            "QUICK_MESSAGE": alert.quick_message,
            "ACKNOWLEDGED": alert.acknowledged,
        }
        self.alert_buffer.append(row)
        
        print(f"[SNOWFLAKE] Alert: {alert.alert_type} - {alert.quick_message}")
        self.flush()
    
    def flush(self) -> None:
        """Write buffered data to Snowflake."""
        import pandas as pd
        
        try:
            if self.observation_buffer:
                df = pd.DataFrame(self.observation_buffer)
                self._write_pandas(
                    self.conn,
                    df,
                    "RAW_OBSERVATIONS",
                    auto_create_table=False,
                    use_logical_type=True,
                )
                print(f"[SNOWFLAKE] Flushed {len(self.observation_buffer)} observations")
                self.observation_buffer = []
            
            if self.alert_buffer:
                df = pd.DataFrame(self.alert_buffer)
                self._write_pandas(
                    self.conn,
                    df,
                    "ALERTS",
                    auto_create_table=False,
                    use_logical_type=True,
                )
                print(f"[SNOWFLAKE] Flushed {len(self.alert_buffer)} alerts")
                self.alert_buffer = []
            
            self.last_flush = datetime.now(timezone.utc)
            
        except Exception as e:
            print(f"[SNOWFLAKE ERROR] Flush failed: {e}")
            raise
    
    def check_flush_needed(self) -> None:
        """Check if time-based flush is needed."""
        elapsed = (datetime.now(timezone.utc) - self.last_flush).total_seconds()
        if elapsed > self.FLUSH_INTERVAL_SECONDS and self.observation_buffer:
            self.flush()
    
    def close(self) -> None:
        """Flush remaining data and close connection."""
        self.flush()
        self.conn.close()
        print("[SNOWFLAKE] Connection closed")


def create_snowflake_client() -> SnowflakeClient:
    """
    Factory function to create Snowflake client.
    
    Raises clear error if credentials are missing.
    """
    required_vars = ["SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD"]
    missing = [var for var in required_vars if not os.getenv(var)]
    
    if missing:
        raise EnvironmentError(
            f"Missing Snowflake credentials: {', '.join(missing)}. "
            "Set these environment variables or add to .env file."
        )
    
    return SnowflakeClient()
