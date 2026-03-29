"""
GET /api/primary-state — latest snapshot for one enrolled subject from Snowflake.

Response shape matches the CV PrimaryStateResponse expected by the dashboard.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query

try:
    from backend.server.demo_snowflake_guard import (
        demo_snowflake_guard_detail,
        snowflake_database_allows_demo_reads,
    )
    from backend.server.snowflake_client import SnowflakeClient, observed_at_cell_to_iso
except ImportError:
    from server.demo_snowflake_guard import (
        demo_snowflake_guard_detail,
        snowflake_database_allows_demo_reads,
    )
    from server.snowflake_client import SnowflakeClient, observed_at_cell_to_iso

router = APIRouter(prefix="/api/primary-state", tags=["primary-state"])

_TIMEZONE = "America/New_York"
_DEFAULT_PERSON = "grandma"
_MIN_LOOKBACK = 1
_MAX_LOOKBACK_MINUTES = 60 * 24 * 7  # one week


def _normalize_person_id(raw: str) -> str:
    p = (raw or "").strip().lower()
    if p not in ("grandma", "grandpa"):
        raise HTTPException(
            status_code=400,
            detail="person_id must be 'grandma' or 'grandpa'",
        )
    return p


def _fallen_attention(
    *,
    pose: str | None,
    is_fall_risk: bool | None,
    latest_alert: dict | None,
) -> bool:
    """
    Snowflake-only approximation of CV fall attention: lying pose plus either
    IS_FALL_RISK on the latest row or a fall_detected alert in the same lookback.
    """
    if not pose or str(pose).lower() != "lying":
        return False
    if is_fall_risk:
        return True
    if latest_alert and str(latest_alert.get("ALERT_TYPE", "")).lower() == "fall_detected":
        return True
    return False


@router.get("")
def get_primary_state(
    person_id: str = Query(_DEFAULT_PERSON, description="Subject id: grandma | grandpa"),
    lookback_minutes: int = Query(
        10_080,
        ge=_MIN_LOOKBACK,
        le=_MAX_LOOKBACK_MINUTES,
        description="Minutes to search back for the latest observation/alert",
    ),
) -> Dict[str, Any]:
    if not snowflake_database_allows_demo_reads():
        raise HTTPException(status_code=403, detail=demo_snowflake_guard_detail())

    pid = _normalize_person_id(person_id)
    client = SnowflakeClient()
    try:
        snap = client.get_live_status_snapshot(person_id=pid, lookback_minutes=lookback_minutes)
        if not snap or not snap.get("latest_observation"):
            return {
                "present": False,
                "timezone": _TIMEZONE,
                "pose": None,
                "display_name": None,
                "observed_at": None,
                "session_id": None,
                "activity": None,
                "fallen_attention": False,
            }

        obs = snap["latest_observation"]
        alert = snap.get("latest_alert")
        pose = obs.get("pose")
        pose_s = str(pose) if pose is not None else None
        activity = obs.get("activity")
        activity_s = str(activity).lower() if activity is not None else None

        fallen = _fallen_attention(
            pose=pose_s,
            is_fall_risk=bool(obs.get("is_fall_risk")),
            latest_alert=alert,
        )

        observed_iso = observed_at_cell_to_iso(obs.get("observed_at"))

        return {
            "present": True,
            "timezone": _TIMEZONE,
            "pose": pose_s,
            "display_name": obs.get("display_name"),
            "observed_at": observed_iso,
            "session_id": obs.get("session_id"),
            "activity": activity_s,
            "fallen_attention": fallen,
        }
    finally:
        client.close()
