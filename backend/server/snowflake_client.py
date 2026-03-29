import os
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo
import snowflake.connector
from snowflake.connector.pandas_tools import write_pandas
from snowflake.connector.constants import PARAMETER_PYTHON_CONNECTOR_QUERY_RESULT_FORMAT
import pandas as pd
from dotenv import load_dotenv

try:
    from backend.config import MAX_LIMIT
    from backend.models import Alert, Observation
except ImportError:  # Backward-compatible fallback for backend-only execution.
    from models import Observation, Alert
    from config import MAX_LIMIT

# remember init in class is related to .env

_US_EASTERN = ZoneInfo("America/New_York")


def _load_runtime_env() -> None:
    """
    Load likely env files for backend execution without overriding exported vars.

    This mirrors the CV app behavior so the repository-level FastAPI app can be
    started from the repo root and still find Snowflake credentials in common
    local development locations.
    """
    repo_root = Path(__file__).resolve().parents[2]
    load_dotenv(repo_root / ".env")
    load_dotenv(repo_root / "backend" / ".env.humberto")
    load_dotenv(repo_root / "backend" / ".env")


def _to_us_eastern_naive(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_US_EASTERN).replace(tzinfo=None)


def _now_us_eastern_naive() -> datetime:
    return datetime.now(_US_EASTERN).replace(tzinfo=None)


def _normalize_objects_detected(value: Any) -> str:
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


def _decode_variant_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            decoded = json.loads(stripped)
        except json.JSONDecodeError:
            return [stripped]
        if isinstance(decoded, list):
            return [str(item) for item in decoded]
        return [str(decoded)]
    return [str(value)]


def _ntz_row_to_iso(dt: Any) -> Optional[str]:
    if dt is None or not isinstance(dt, datetime):
        return None
    naive = dt.replace(tzinfo=None) if dt.tzinfo else dt
    aware = naive.replace(tzinfo=_US_EASTERN)
    return aware.isoformat()


def observed_at_cell_to_iso(value: Any) -> Optional[str]:
    """Normalize Snowflake OBSERVED_AT (VARCHAR or TIMESTAMP) to ISO-8601 Eastern."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return _ntz_row_to_iso(value)
    s = str(value).strip()
    if not s:
        return None
    if "T" in s and len(s) >= 19:
        return s
    base = s.split(".")[0][:19]
    try:
        naive = datetime.strptime(base, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return s
    return naive.replace(tzinfo=_US_EASTERN).isoformat()


def _extract_cortex_text(raw: Any) -> str:
    """
    Normalize Snowflake Cortex COMPLETE output into a plain assistant response.
    """
    if raw is None:
        return ""
    if isinstance(raw, dict):
        choices = raw.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                msg = first.get("messages") or first.get("message") or first.get("text")
                if isinstance(msg, str):
                    return msg.strip()
        content = raw.get("content")
        if isinstance(content, str):
            return content.strip()
        return json.dumps(raw)
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return ""
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            return text
        return _extract_cortex_text(decoded)
    return str(raw)


class SnowflakeClient:
    def __init__(self):
        _load_runtime_env()
        self.conn = snowflake.connector.connect(
            account=os.getenv('SNOWFLAKE_ACCOUNT'),
            user=os.getenv('SNOWFLAKE_USER'),
            password=os.getenv('SNOWFLAKE_PASSWORD'),
            warehouse=os.getenv('SNOWFLAKE_WAREHOUSE', 'COMPUTE_WH'),
            database=os.getenv('SNOWFLAKE_DATABASE', 'GRANDMA_MONITOR'),
            schema=os.getenv('SNOWFLAKE_SCHEMA', 'PUBLIC'),
            session_parameters={
                "PYTHON_CONNECTOR_QUERY_RESULT_FORMAT": "JSON"
            }
        )
        cur = self.conn.cursor()
        cur.execute("ALTER SESSION SET TIMEZONE = 'America/New_York'")
        cur.close()
        self.observation_buffer: List[dict] = []
        self.alert_buffer: List[dict] = []
        self.BATCH_SIZE = 10
        self.last_flush = datetime.now(timezone.utc)
        self.FLUSH_INTERVAL_SECONDS = 30
    
    def add_observation(self, obs: Observation):
        """Add observation to buffer. Flushes when batch size reached."""
        observed_at = _to_us_eastern_naive(obs.observed_at)
        inserted_at = _now_us_eastern_naive()
        row = {
            'ID': obs.id,
            'OBSERVED_AT': observed_at,
            'INSERTED_AT': inserted_at,
            'PERSON_DETECTED': obs.person_detected,
            'PRIMARY_PERSON_ID': getattr(obs, 'primary_person_id', None),
            'PRIMARY_DISPLAY_NAME': getattr(obs, 'primary_display_name', None),
            'IDENTITY_CONFIDENCE': getattr(obs, 'primary_identity_confidence', None),
            'POSE': obs.pose.value if hasattr(obs.pose, 'value') else obs.pose,
            'POSE_CONFIDENCE': obs.pose_confidence,
            'ACTIVITY': obs.activity.value if hasattr(obs.activity, 'value') else obs.activity,
            'ACTIVITY_CONFIDENCE': obs.activity_confidence,
            'OBJECTS_DETECTED': _normalize_objects_detected(obs.objects_detected),
            'ROOM_HINT': obs.room_hint,
            'IS_FALL_RISK': obs.is_fall_risk,
            'MOTION_LEVEL': obs.motion_level.value if hasattr(obs.motion_level, 'value') else obs.motion_level,
            'MINUTES_SINCE_LAST_SEEN': obs.minutes_since_last_seen,
            'FRAME_QUALITY': obs.frame_quality,
            'SESSION_ID': obs.session_id,
            'FRAME_THUMB_BASE64': getattr(obs, 'frame_thumb_base64', None),
        }
        self.observation_buffer.append(row)
        
        if len(self.observation_buffer) >= self.BATCH_SIZE:
            self.flush()
    
    def add_alert(self, alert: Alert):
        """Add alert to buffer. Alerts are also flushed with observations."""
        triggered_at = _to_us_eastern_naive(alert.triggered_at)
        inserted_at = _now_us_eastern_naive()
        row = {
            'ID': alert.id,
            'OBSERVATION_ID': alert.observation_id,
            'ALERT_TYPE': alert.alert_type,
            'SEVERITY': alert.severity.value if hasattr(alert.severity, 'value') else alert.severity,
            'TRIGGERED_AT': triggered_at,
            'INSERTED_AT': inserted_at,
            'QUICK_MESSAGE': alert.quick_message,
            'ACKNOWLEDGED': alert.acknowledged
        }
        self.alert_buffer.append(row)
        
        # Alerts are high priority - flush immediately
        self.flush()
    
    def flush(self):
        """Write buffered data to Snowflake."""
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
    
    def check_flush_needed(self):
        """Check if time-based flush is needed."""
        elapsed = (datetime.now(timezone.utc)- self.last_flush).total_seconds()
        if elapsed > self.FLUSH_INTERVAL_SECONDS and self.observation_buffer:
            self.flush()
        
    # mark alert as acknowledge
    def update_alert_acknowledged(self, alert_id: str, acknowledged_by: Optional[str]):
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
    def get_recent_observations(self, limit: int = MAX_LIMIT) -> List[dict]:
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                SELECT
                    ID,
                    TO_VARCHAR(OBSERVED_AT) AS OBSERVED_AT,
                    PERSON_DETECTED,
                    PRIMARY_PERSON_ID,
                    PRIMARY_DISPLAY_NAME,
                    IDENTITY_CONFIDENCE,
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
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
            for row in rows:
                row["OBJECTS_DETECTED"] = _decode_variant_list(row.get("OBJECTS_DETECTED"))
            return rows
        finally:
            cursor.close()

    def get_recent_alerts(self, limit: int = MAX_LIMIT) -> List[dict]:
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                SELECT
                    a.ID,
                    a.OBSERVATION_ID,
                    a.ALERT_TYPE,
                    a.SEVERITY,
                    TO_VARCHAR(a.TRIGGERED_AT) AS TRIGGERED_AT,
                    a.QUICK_MESSAGE,
                    a.ACKNOWLEDGED,
                    TO_VARCHAR(a.ACKNOWLEDGED_AT) AS ACKNOWLEDGED_AT,
                    a.ACKNOWLEDGED_BY,
                    TO_VARCHAR(a.INSERTED_AT) AS INSERTED_AT,
                    o.PRIMARY_PERSON_ID,
                    o.PRIMARY_DISPLAY_NAME
                FROM ALERTS a
                LEFT JOIN RAW_OBSERVATIONS o ON o.ID = a.OBSERVATION_ID
                ORDER BY a.TRIGGERED_AT DESC
                LIMIT %s
            """, (limit,), _statement_params={PARAMETER_PYTHON_CONNECTOR_QUERY_RESULT_FORMAT: "JSON"})
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        finally:
            cursor.close()

    def get_recent_live_events(
        self,
        *,
        since_minutes: int = 30,
        limit: int = 50,
    ) -> List[dict]:
        """
        Read live-feed rows using the repository Snowflake schema.

        Returns the same API-facing shape used by the CV service so callers can
        adopt the backend reader without changing the existing frontend contract.
        """
        since_minutes = max(1, min(int(since_minutes), 60 * 24 * 7))
        limit = max(1, min(int(limit), 200))

        cursor = self.conn.cursor()
        try:
            cursor.execute("""
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
            """, (since_minutes, limit))
            columns = [col[0].lower() for col in cursor.description or []]
            rows = cursor.fetchall()
        finally:
            cursor.close()

        events: List[dict] = []
        for row in rows:
            record = dict(zip(columns, row))
            events.append(
                {
                    "id": record.get("id"),
                    "event_type": record.get("event_type"),
                    "headline": record.get("headline"),
                    "summary": record.get("summary"),
                    "meal_kind": record.get("meal_kind"),
                    "observed_at": _ntz_row_to_iso(record.get("observed_at")),
                    "display_name": record.get("primary_display_name"),
                    "frame_thumb_base64": record.get("frame_thumb_base64"),
                }
            )
        return events

    def get_recent_enriched_observations(self, limit: int = MAX_LIMIT) -> List[dict]:
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                SELECT
                    e.ID,
                    e.OBSERVATION_ID,
                    TO_VARCHAR(e.ENRICHED_AT) AS ENRICHED_AT,
                    e.NATURAL_DESCRIPTION,
                    e.WELLNESS_SCORE,
                    e.CONCERN_FLAGS,
                    e.IS_DAILY_SUMMARY,
                    o.PRIMARY_PERSON_ID,
                    o.PRIMARY_DISPLAY_NAME,
                    TO_VARCHAR(o.OBSERVED_AT) AS OBSERVED_AT
                FROM ENRICHED_OBSERVATIONS e
                LEFT JOIN RAW_OBSERVATIONS o ON o.ID = e.OBSERVATION_ID
                WHERE e.IS_DAILY_SUMMARY = FALSE
                ORDER BY e.ENRICHED_AT DESC
                LIMIT %s
            """, (limit,), _statement_params={PARAMETER_PYTHON_CONNECTOR_QUERY_RESULT_FORMAT: "JSON"})
            columns = [col[0] for col in cursor.description]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
            for row in rows:
                row["CONCERN_FLAGS"] = _decode_variant_list(row.get("CONCERN_FLAGS"))
            return rows
        finally:
            cursor.close()

    # ackowledgement alert for dashboard
    def get_unacknowledged_alerts(self) -> List[dict]:
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                SELECT
                    a.ID,
                    a.OBSERVATION_ID,
                    a.ALERT_TYPE,
                    a.SEVERITY,
                    TO_VARCHAR(a.TRIGGERED_AT) AS TRIGGERED_AT,
                    a.QUICK_MESSAGE,
                    a.ACKNOWLEDGED,
                    TO_VARCHAR(a.ACKNOWLEDGED_AT) AS ACKNOWLEDGED_AT,
                    a.ACKNOWLEDGED_BY,
                    TO_VARCHAR(a.INSERTED_AT) AS INSERTED_AT,
                    o.PRIMARY_PERSON_ID,
                    o.PRIMARY_DISPLAY_NAME
                FROM ALERTS a
                LEFT JOIN RAW_OBSERVATIONS o ON o.ID = a.OBSERVATION_ID
                WHERE a.ACKNOWLEDGED = FALSE
                ORDER BY a.TRIGGERED_AT DESC
            """,_statement_params={PARAMETER_PYTHON_CONNECTOR_QUERY_RESULT_FORMAT: "JSON"})
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        finally:
            cursor.close()

    def get_live_status_snapshot(
        self,
        *,
        person_id: str,
        lookback_minutes: int = 30,
    ) -> Optional[dict]:
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                SELECT
                    PRIMARY_PERSON_ID,
                    PRIMARY_DISPLAY_NAME,
                    TO_VARCHAR(OBSERVED_AT) AS OBSERVED_AT,
                    DATEDIFF('minute', OBSERVED_AT, CURRENT_TIMESTAMP()) AS MINUTES_AGO,
                    POSE,
                    ACTIVITY,
                    SESSION_ID,
                    ROOM_HINT,
                    MOTION_LEVEL,
                    IS_FALL_RISK,
                    MINUTES_SINCE_LAST_SEEN,
                    OBJECTS_DETECTED,
                    FRAME_QUALITY,
                    IDENTITY_CONFIDENCE
                FROM RAW_OBSERVATIONS
                WHERE PRIMARY_PERSON_ID = %s
                  AND DATEDIFF('minute', OBSERVED_AT, CURRENT_TIMESTAMP()) <= %s
                ORDER BY OBSERVED_AT DESC
                LIMIT 1
            """, (person_id, lookback_minutes), _statement_params={PARAMETER_PYTHON_CONNECTOR_QUERY_RESULT_FORMAT: "JSON"})
            row = cursor.fetchone()
            if row is None:
                return None

            columns = [col[0] for col in cursor.description]
            record = dict(zip(columns, row))
            latest_observation = {
                "person_id": record.get("PRIMARY_PERSON_ID"),
                "display_name": record.get("PRIMARY_DISPLAY_NAME"),
                "observed_at": record.get("OBSERVED_AT"),
                "minutes_ago": record.get("MINUTES_AGO"),
                "pose": record.get("POSE"),
                "activity": record.get("ACTIVITY"),
                "session_id": record.get("SESSION_ID"),
                "room_hint": record.get("ROOM_HINT"),
                "motion_level": record.get("MOTION_LEVEL"),
                "is_fall_risk": record.get("IS_FALL_RISK"),
                "minutes_since_last_seen": record.get("MINUTES_SINCE_LAST_SEEN"),
                "objects_detected": _decode_variant_list(record.get("OBJECTS_DETECTED")),
                "frame_quality": record.get("FRAME_QUALITY"),
                "identity_confidence": record.get("IDENTITY_CONFIDENCE"),
            }

            cursor.execute("""
                SELECT
                    a.ID,
                    a.OBSERVATION_ID,
                    a.ALERT_TYPE,
                    a.SEVERITY,
                    TO_VARCHAR(a.TRIGGERED_AT) AS TRIGGERED_AT,
                    a.QUICK_MESSAGE,
                    a.ACKNOWLEDGED
                FROM ALERTS a
                LEFT JOIN RAW_OBSERVATIONS o ON o.ID = a.OBSERVATION_ID
                WHERE o.PRIMARY_PERSON_ID = %s
                  AND DATEDIFF('minute', a.TRIGGERED_AT, CURRENT_TIMESTAMP()) <= %s
                ORDER BY a.TRIGGERED_AT DESC
                LIMIT 1
            """, (person_id, lookback_minutes), _statement_params={PARAMETER_PYTHON_CONNECTOR_QUERY_RESULT_FORMAT: "JSON"})
            alert_row = cursor.fetchone()
            latest_alert = None
            if alert_row is not None:
                alert_columns = [col[0] for col in cursor.description]
                latest_alert = dict(zip(alert_columns, alert_row))

            return {
                "latest_observation": latest_observation,
                "latest_alert": latest_alert,
            }
        finally:
            cursor.close()

    def get_insights_trends(
        self,
        *,
        person_id: str,
        days: int,
    ) -> List[dict]:
        """
        Daily aggregates for insights charts: meals (eating activity), falls (alerts),
        activity level 0-100 from pose counts. Days are US Eastern calendar days
        (session TIMEZONE). Returns oldest-to-newest rows aligned to a day spine.
        """
        days = max(1, min(int(days), 7))
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                """
                WITH spine AS (
                    SELECT DATEADD('day', -seq, CURRENT_DATE()) AS day_dt
                    FROM (SELECT SEQ4() AS seq FROM TABLE(GENERATOR(ROWCOUNT => %s)))
                ),
                obs_daily AS (
                    SELECT
                        DATE(OBSERVED_AT) AS day_dt,
                        SUM(IFF(LOWER(ACTIVITY) = 'eating', 1, 0)) AS meals,
                        SUM(IFF(LOWER(POSE) IN ('standing', 'walking'), 1, 0)) AS active_cnt,
                        SUM(IFF(LOWER(POSE) IN ('sitting', 'lying'), 1, 0)) AS sedentary_cnt
                    FROM RAW_OBSERVATIONS
                    WHERE PRIMARY_PERSON_ID = %s
                      AND DATE(OBSERVED_AT) >= (SELECT MIN(day_dt) FROM spine)
                      AND DATE(OBSERVED_AT) <= (SELECT MAX(day_dt) FROM spine)
                    GROUP BY 1
                ),
                falls_daily AS (
                    SELECT
                        DATE(a.TRIGGERED_AT) AS day_dt,
                        COUNT(*) AS falls
                    FROM ALERTS a
                    INNER JOIN RAW_OBSERVATIONS o ON o.ID = a.OBSERVATION_ID
                    WHERE o.PRIMARY_PERSON_ID = %s
                      AND a.ALERT_TYPE = 'fall_detected'
                      AND DATE(a.TRIGGERED_AT) >= (SELECT MIN(day_dt) FROM spine)
                      AND DATE(a.TRIGGERED_AT) <= (SELECT MAX(day_dt) FROM spine)
                    GROUP BY 1
                )
                SELECT
                    s.day_dt,
                    COALESCE(o.meals, 0) AS meals,
                    COALESCE(f.falls, 0) AS falls,
                    COALESCE(
                        ROUND(
                            100 * COALESCE(o.active_cnt, 0)
                            / NULLIF(COALESCE(o.active_cnt, 0) + COALESCE(o.sedentary_cnt, 0), 0)
                        ),
                        0
                    ) AS activity_level
                FROM spine s
                LEFT JOIN obs_daily o ON o.day_dt = s.day_dt
                LEFT JOIN falls_daily f ON f.day_dt = s.day_dt
                ORDER BY s.day_dt
                """,
                (days, person_id, person_id),
            )
            columns = [col[0].lower() for col in cursor.description or []]
            rows = cursor.fetchall()
        finally:
            cursor.close()

        out: List[dict] = []
        for row in rows:
            rec = dict(zip(columns, row))
            day_val = rec.get("day_dt")
            if day_val is None:
                continue
            if hasattr(day_val, "isoformat"):
                date_str = day_val.isoformat()
            else:
                date_str = str(day_val)[:10]
            dt_eastern = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=_US_EASTERN)
            label_short = dt_eastern.strftime("%m/%d")
            label_dow = dt_eastern.strftime("%a")
            out.append(
                {
                    "date": date_str,
                    "label": f"{label_dow} {label_short}",
                    "meals_per_day": int(rec.get("meals") or 0),
                    "falls_per_day": int(rec.get("falls") or 0),
                    "activity_level": int(rec.get("activity_level") or 0),
                }
            )
        return out

    def get_timeline_items(
        self,
        *,
        person_id: str,
        range_key: str,
        limit: int = 250,
    ) -> List[dict]:
        """
        Return chronological timeline rows for one subject and range.

        Range values:
          - today: current US Eastern date
          - yesterday: previous US Eastern date
          - week: current date and previous 6 days
        """
        normalized_range = (range_key or "").strip().lower()
        if normalized_range not in {"today", "yesterday", "week"}:
            normalized_range = "today"
        limit = max(1, min(int(limit), 500))

        cursor = self.conn.cursor()
        try:
            cursor.execute(
                """
                SELECT
                    o.OBSERVED_AT AS observed_at,
                    COALESCE(e.EVENT_TYPE, a.ALERT_TYPE, 'observation') AS event_type,
                    COALESCE(
                        e.HEADLINE,
                        IFF(
                            a.ALERT_TYPE = 'fall_detected',
                            o.PRIMARY_DISPLAY_NAME || ': possible fall detected',
                            INITCAP(REPLACE(o.POSE, '_', ' ')) || ' - ' || INITCAP(REPLACE(o.ACTIVITY, '_', ' '))
                        )
                    ) AS title,
                    COALESCE(
                        e.SUMMARY,
                        a.QUICK_MESSAGE,
                        o.PRIMARY_DISPLAY_NAME || ' observed in ' || REPLACE(o.ROOM_HINT, '_', ' ')
                    ) AS summary
                FROM RAW_OBSERVATIONS o
                LEFT JOIN LIVE_EVENTS e ON e.OBSERVATION_ID = o.ID
                LEFT JOIN ALERTS a
                  ON a.OBSERVATION_ID = o.ID
                 AND a.ALERT_TYPE = 'fall_detected'
                WHERE o.PRIMARY_PERSON_ID = %s
                  AND (
                        (%s = 'today' AND DATE(o.OBSERVED_AT) = CURRENT_DATE())
                     OR (%s = 'yesterday' AND DATE(o.OBSERVED_AT) = DATEADD('day', -1, CURRENT_DATE()))
                     OR (
                            %s = 'week'
                        AND DATE(o.OBSERVED_AT) >= DATEADD('day', -6, CURRENT_DATE())
                        AND DATE(o.OBSERVED_AT) <= CURRENT_DATE()
                     )
                  )
                ORDER BY o.OBSERVED_AT ASC
                LIMIT %s
                """,
                (person_id, normalized_range, normalized_range, normalized_range, limit),
            )
            rows = cursor.fetchall()
            columns = [col[0].lower() for col in cursor.description or []]
        finally:
            cursor.close()

        items: List[dict] = []
        for row in rows:
            record = dict(zip(columns, row))
            observed_at = record.get("observed_at")
            iso_value = _ntz_row_to_iso(observed_at)
            display_time = ""
            if isinstance(observed_at, datetime):
                display_time = observed_at.strftime("%I:%M %p").lstrip("0")
            elif iso_value:
                display_time = iso_value[11:16]
            items.append(
                {
                    "observed_at": iso_value,
                    "time": display_time,
                    "event_type": str(record.get("event_type") or "observation").lower(),
                    "title": str(record.get("title") or "Activity update"),
                    "summary": str(record.get("summary") or ""),
                }
            )
        return items

    def get_recent_live_event_headlines(
        self,
        *,
        person_id: str,
        limit: int = 8,
    ) -> List[dict]:
        limit = max(1, min(int(limit), 20))
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                """
                SELECT
                    EVENT_TYPE,
                    HEADLINE,
                    OBSERVED_AT
                FROM LIVE_EVENTS
                WHERE PRIMARY_PERSON_ID = %s
                  AND DATE(OBSERVED_AT) >= DATEADD('day', -6, CURRENT_DATE())
                ORDER BY OBSERVED_AT DESC
                LIMIT %s
                """,
                (person_id, limit),
            )
            rows = cursor.fetchall()
            columns = [col[0].lower() for col in cursor.description or []]
        finally:
            cursor.close()

        out: List[dict] = []
        for row in rows:
            rec = dict(zip(columns, row))
            out.append(
                {
                    "event_type": str(rec.get("event_type") or ""),
                    "headline": str(rec.get("headline") or ""),
                    "observed_at": _ntz_row_to_iso(rec.get("observed_at")),
                }
            )
        return out

    def complete_insights_chat(
        self,
        *,
        person_id: str,
        user_message: str,
        model: str,
    ) -> Dict[str, Any]:
        weekly_trends = self.get_insights_trends(person_id=person_id, days=7)
        recent_headlines = self.get_recent_live_event_headlines(person_id=person_id, limit=8)
        context_payload = {
            "timezone": "America/New_York",
            "person_id": person_id,
            "activity_level_formula": (
                "activity_level = round(100 * active / (active + sedentary)), "
                "active poses: standing/walking, sedentary poses: sitting/lying."
            ),
            "weekly_trends": weekly_trends,
            "recent_live_event_headlines": recent_headlines,
        }
        context_json = json.dumps(context_payload, separators=(",", ":"))

        prompt = (
            "You are an elder care insights assistant. "
            "Use ONLY the provided JSON context. "
            "If context is missing, say you are unsure. "
            "Cite specific day labels and values when making claims. "
            "Keep response concise, supportive, and factual.\n\n"
            f"Context JSON:\n{context_json}\n\n"
            f"User question:\n{user_message.strip()}"
        )

        cursor = self.conn.cursor()
        try:
            cursor.execute(
                """
                SELECT SNOWFLAKE.CORTEX.COMPLETE(%s, %s) AS RESPONSE
                """,
                (model, prompt),
            )
            row = cursor.fetchone()
            raw = row[0] if row else None
        finally:
            cursor.close()

        reply = _extract_cortex_text(raw)
        return {
            "reply": reply or "I could not generate a response from the available context.",
            "context": context_payload,
            "model": model,
        }

    # flush the remaining data and close connection
    def close(self):
        self.flush()
        self.conn.close()
