"""
Snowflake client for CV pipeline.

Handles writing observations and alerts to Snowflake with identity support.
Uses cv.models (Pydantic) which include primary person fields.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, List, Optional, Tuple, Union
from zoneinfo import ZoneInfo

from cv.models import Alert, Observation

# Snowflake RAW_OBSERVATIONS uses TIMESTAMP_NTZ; we store America/New_York local wall time.
_US_EASTERN = ZoneInfo("America/New_York")


def _to_us_eastern_naive(dt: datetime) -> datetime:
    """Interpret naive datetimes as UTC (pipeline default), then convert to US Eastern wall clock."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_US_EASTERN).replace(tzinfo=None)


def _now_us_eastern_naive() -> datetime:
    return datetime.now(_US_EASTERN).replace(tzinfo=None)


def _normalize_objects_detected(value: Any) -> str:
    """
    Match backend/server/snowflake_client.py so VARIANT-bound JSON matches write_pandas.
    """
    if value is None:
        return "[]"
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return "[]"
        try:
            decoded = json.loads(stripped)
        except json.JSONDecodeError:
            return json.dumps([stripped])
        return json.dumps(decoded)
    if isinstance(value, (list, tuple)):
        return json.dumps(list(value))
    return json.dumps([value])


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
        
        account = os.getenv("SNOWFLAKE_ACCOUNT")
        user = os.getenv("SNOWFLAKE_USER")
        password = os.getenv("SNOWFLAKE_PASSWORD")
        warehouse = os.getenv("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH")
        database = os.getenv("SNOWFLAKE_DATABASE", "GRANDMA_MONITOR")
        schema = os.getenv("SNOWFLAKE_SCHEMA", "PUBLIC")
        
        print(f"[SnowflakeClient] Connecting with account={account}, user={user}, db={database}, schema={schema}")
        
        self.conn = snowflake.connector.connect(
            account=account,
            user=user,
            password=password,
            warehouse=warehouse,
            database=database,
            schema=schema,
            session_parameters={
                "PYTHON_CONNECTOR_QUERY_RESULT_FORMAT": "JSON"
            }
        )
        
        self.observation_buffer: List[dict] = []
        self.alert_buffer: List[dict] = []
        self.BATCH_SIZE = 10
        self.last_flush = datetime.now(timezone.utc)
        self.FLUSH_INTERVAL_SECONDS = 30
        
        # Align session clock with stored NTZ convention (US Eastern local).
        cursor = self.conn.cursor()
        cursor.execute("ALTER SESSION SET TIMEZONE = 'America/New_York'")
        cursor.execute("SELECT CURRENT_DATABASE(), CURRENT_SCHEMA(), CURRENT_USER()")
        ctx = cursor.fetchone()
        cursor.close()
        print(f"[SnowflakeClient] Connected! DB={ctx[0]}, Schema={ctx[1]}, User={ctx[2]}")
    
    def add_observation(self, obs: Observation) -> None:
        """Add observation to buffer. Flushes when batch size reached."""
        observed_at = _to_us_eastern_naive(obs.observed_at)
        inserted_at = _now_us_eastern_naive()

        row = {
            "ID": obs.id,
            "OBSERVED_AT": observed_at,
            "INSERTED_AT": inserted_at,
            "PERSON_DETECTED": obs.person_detected,
            "PRIMARY_PERSON_ID": obs.primary_person_id,
            "PRIMARY_DISPLAY_NAME": obs.primary_display_name,
            "IDENTITY_CONFIDENCE": obs.primary_identity_confidence,
            "POSE": obs.pose.value if hasattr(obs.pose, "value") else obs.pose,
            "POSE_CONFIDENCE": obs.pose_confidence,
            "ACTIVITY": obs.activity.value if hasattr(obs.activity, "value") else obs.activity,
            "ACTIVITY_CONFIDENCE": obs.activity_confidence,
            "OBJECTS_DETECTED": _normalize_objects_detected(obs.objects_detected),
            "ROOM_HINT": obs.room_hint,
            "IS_FALL_RISK": obs.is_fall_risk,
            "MOTION_LEVEL": obs.motion_level.value if hasattr(obs.motion_level, "value") else obs.motion_level,
            "MINUTES_SINCE_LAST_SEEN": obs.minutes_since_last_seen,
            "FRAME_QUALITY": obs.frame_quality,
            "SESSION_ID": obs.session_id,
            "FRAME_THUMB_BASE64": obs.frame_thumb_base64,
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
        triggered_at = _to_us_eastern_naive(alert.triggered_at)
        inserted_at = _now_us_eastern_naive()

        row = {
            "ID": alert.id,
            "OBSERVATION_ID": alert.observation_id,
            "ALERT_TYPE": alert.alert_type,
            "SEVERITY": alert.severity.value if hasattr(alert.severity, "value") else alert.severity,
            "TRIGGERED_AT": triggered_at,
            "INSERTED_AT": inserted_at,
            "QUICK_MESSAGE": alert.quick_message,
            "ACKNOWLEDGED": alert.acknowledged,
        }
        self.alert_buffer.append(row)
        
        print(f"[SNOWFLAKE] Alert: {alert.alert_type} - {alert.quick_message}")
        self.flush()
    
    @staticmethod
    def _write_pandas_result_summary(result: Union[bool, Tuple[Any, ...]]) -> tuple[bool, int]:
        """snowflake write_pandas returns (success, nchunks, nrows, ...) or legacy shapes."""
        if isinstance(result, tuple) and len(result) >= 3:
            return bool(result[0]), int(result[2])
        if isinstance(result, tuple) and len(result) == 2:
            return bool(result[0]), int(result[1])
        return bool(result), -1

    def flush(self) -> None:
        """Write buffered data to Snowflake."""
        import pandas as pd

        try:
            if self.observation_buffer:
                nbuf = len(self.observation_buffer)
                df = pd.DataFrame(self.observation_buffer)
                
                # Debug: verify connection is still alive
                try:
                    cursor = self.conn.cursor()
                    cursor.execute("SELECT CURRENT_DATABASE(), CURRENT_SCHEMA()")
                    db_info = cursor.fetchone()
                    cursor.close()
                    print(f"[SNOWFLAKE] Writing to {db_info[0]}.{db_info[1]}.RAW_OBSERVATIONS")
                except Exception as conn_err:
                    print(f"[SNOWFLAKE ERROR] Connection check failed: {conn_err}")
                    raise
                
                wp_out = self._write_pandas(
                    self.conn,
                    df,
                    "RAW_OBSERVATIONS",
                    auto_create_table=False,
                    use_logical_type=True,
                )
                ok, nrows = self._write_pandas_result_summary(wp_out)
                print(
                    f"[SNOWFLAKE] Flushed {nbuf} observations "
                    f"(write_pandas ok={ok}, rows_reported={nrows})",
                )
                if not ok:
                    raise RuntimeError("write_pandas returned success=False for RAW_OBSERVATIONS")
                if nrows >= 0 and nrows != nbuf:
                    raise RuntimeError(
                        f"write_pandas row count mismatch: buffered {nbuf}, reported {nrows}",
                    )
                
                # Verify the write by checking the row exists
                try:
                    first_id = self.observation_buffer[0]["ID"]
                    cursor = self.conn.cursor()
                    cursor.execute(
                        "SELECT COUNT(*) FROM RAW_OBSERVATIONS WHERE ID = %s",
                        (first_id,)
                    )
                    count = cursor.fetchone()[0]
                    cursor.close()
                    if count == 0:
                        print(f"[SNOWFLAKE WARNING] Row {first_id} not found after write!")
                    else:
                        print(f"[SNOWFLAKE] Verified: row {first_id} exists in table")
                except Exception as verify_err:
                    print(f"[SNOWFLAKE WARNING] Could not verify write: {verify_err}")
                
                self.observation_buffer = []

            if self.alert_buffer:
                nbuf = len(self.alert_buffer)
                df = pd.DataFrame(self.alert_buffer)
                wp_out = self._write_pandas(
                    self.conn,
                    df,
                    "ALERTS",
                    auto_create_table=False,
                    use_logical_type=True,
                )
                ok, nrows = self._write_pandas_result_summary(wp_out)
                print(
                    f"[SNOWFLAKE] Flushed {nbuf} alerts "
                    f"(write_pandas ok={ok}, rows_reported={nrows})",
                )
                if not ok:
                    raise RuntimeError("write_pandas returned success=False for ALERTS")
                if nrows >= 0 and nrows != nbuf:
                    raise RuntimeError(
                        f"write_pandas row count mismatch (alerts): buffered {nbuf}, reported {nrows}",
                    )
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

    def get_recent_live_events(
        self,
        *,
        since_minutes: int = 30,
        limit: int = 50,
    ) -> List[dict]:
        """
        Rows from LIVE_EVENTS joined to RAW_OBSERVATIONS for frame thumbnails.
        OBSERVED_AT is NTZ US Eastern wall time; returned ISO strings use offset for that zone.

        Args:
            since_minutes: Only events with OBSERVED_AT >= now - this many minutes (session TZ).
            limit: Max rows (most recent first).
        """
        since_minutes = max(1, min(int(since_minutes), 60 * 24 * 7))
        limit = max(1, min(int(limit), 200))

        def _ntz_row_to_iso(dt: Any) -> Optional[str]:
            if dt is None:
                return None
            if not isinstance(dt, datetime):
                return None
            # NTZ values are stored as America/New_York local wall time.
            naive = dt.replace(tzinfo=None) if dt.tzinfo else dt
            aware = naive.replace(tzinfo=_US_EASTERN)
            return aware.isoformat()

        sql = """
            SELECT
                e.ID,
                e.EVENT_TYPE,
                e.HEADLINE,
                e.SUMMARY,
                e.MEAL_KIND,
                e.OBSERVED_AT,
                e.PRIMARY_DISPLAY_NAME,
                r.FRAME_THUMB_BASE64
            FROM LIVE_EVENTS e
            INNER JOIN RAW_OBSERVATIONS r ON r.ID = e.OBSERVATION_ID
            WHERE e.OBSERVED_AT >= DATEADD('minute', -%s, CURRENT_TIMESTAMP())
            ORDER BY e.OBSERVED_AT DESC
            LIMIT %s
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute(sql, (since_minutes, limit))
            columns = [c[0].lower() for c in cursor.description or []]
            rows = cursor.fetchall()
        finally:
            cursor.close()

        out: List[dict] = []
        for row in rows:
            d = dict(zip(columns, row))
            out.append(
                {
                    "id": d.get("id"),
                    "event_type": d.get("event_type"),
                    "headline": d.get("headline"),
                    "summary": d.get("summary"),
                    "meal_kind": d.get("meal_kind"),
                    "observed_at": _ntz_row_to_iso(d.get("observed_at")),
                    "display_name": d.get("primary_display_name"),
                    "frame_thumb_base64": d.get("frame_thumb_base64"),
                }
            )
        return out

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
