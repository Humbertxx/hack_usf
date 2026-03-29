"""
GET /api/insights-trends — daily meals, falls, and activity level from Snowflake.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query

try:
    from backend.server.demo_snowflake_guard import (
        demo_snowflake_guard_detail,
        snowflake_database_allows_demo_reads,
    )
    from backend.server.snowflake_client import SnowflakeClient
except ImportError:
    from server.demo_snowflake_guard import (
        demo_snowflake_guard_detail,
        snowflake_database_allows_demo_reads,
    )
    from server.snowflake_client import SnowflakeClient

router = APIRouter(prefix="/api/insights-trends", tags=["insights-trends"])

_TIMEZONE = "America/New_York"
_ACTIVITY_FORMULA = (
    "activity_level = round(100 * active / (active + sedentary)) with active = count of "
    "poses in ('standing','walking') and sedentary = count in ('sitting','lying'); "
    "0 if the denominator is 0. Meals = count of rows where ACTIVITY = 'eating'. "
    "Falls = count of ALERTS with ALERT_TYPE = 'fall_detected' for the person."
)


def _normalize_person_id(raw: str) -> str:
    p = (raw or "").strip().lower()
    if p not in ("grandma", "grandpa"):
        raise HTTPException(
            status_code=400,
            detail="person_id must be 'grandma' or 'grandpa'",
        )
    return p


@router.get("")
def get_insights_trends(
    person_id: str = Query("grandma", description="grandma | grandpa"),
    days: int = Query(7, ge=1, le=7, description="Number of calendar days (1-7), ending today"),
) -> Dict[str, Any]:
    if not snowflake_database_allows_demo_reads():
        raise HTTPException(status_code=403, detail=demo_snowflake_guard_detail())

    pid = _normalize_person_id(person_id)
    days_clamped = max(1, min(int(days), 7))
    client = SnowflakeClient()
    try:
        series: List[dict] = client.get_insights_trends(person_id=pid, days=days_clamped)
        return {
            "timezone": _TIMEZONE,
            "person_id": pid,
            "days": days_clamped,
            "activity_level_formula": _ACTIVITY_FORMULA,
            "series": series,
        }
    finally:
        client.close()
