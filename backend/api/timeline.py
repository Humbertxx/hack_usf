"""
GET /api/timeline — chronological timeline items for one person and date range.
"""

from __future__ import annotations

from typing import Any, Dict

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

router = APIRouter(prefix="/api/timeline", tags=["timeline"])

_TIMEZONE = "America/New_York"
_VALID_RANGES = {"today", "yesterday", "week"}


def _normalize_person_id(raw: str) -> str:
    person_id = (raw or "").strip().lower()
    if person_id not in ("grandma", "grandpa"):
        raise HTTPException(
            status_code=400,
            detail="person_id must be 'grandma' or 'grandpa'",
        )
    return person_id


def _normalize_range(raw: str) -> str:
    range_key = (raw or "").strip().lower()
    if range_key not in _VALID_RANGES:
        raise HTTPException(
            status_code=400,
            detail="range must be one of: today, yesterday, week",
        )
    return range_key


@router.get("")
def get_timeline(
    person_id: str = Query("grandma", description="grandma | grandpa"),
    range: str = Query("today", description="today | yesterday | week"),
) -> Dict[str, Any]:
    if not snowflake_database_allows_demo_reads():
        raise HTTPException(status_code=403, detail=demo_snowflake_guard_detail())

    pid = _normalize_person_id(person_id)
    range_key = _normalize_range(range)

    client = SnowflakeClient()
    try:
        items = client.get_timeline_items(person_id=pid, range_key=range_key)
        return {
            "timezone": _TIMEZONE,
            "person_id": pid,
            "range": range_key,
            "items": items,
        }
    finally:
        client.close()
