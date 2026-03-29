from typing import Dict, List, Optional

from fastapi import APIRouter, Query

try:
    from backend.config import DEFAULT_LIMIT, MAX_LIMIT
    from backend.server.snowflake_client import SnowflakeClient
except ImportError:  # Backward-compatible fallback for backend-only execution.
    from config import DEFAULT_LIMIT, MAX_LIMIT
    from server.snowflake_client import SnowflakeClient

router = APIRouter(prefix="/api/live-events", tags=["live-events"])

_TIMEZONE = "America/New_York"
_DEFAULT_LOOKBACK_MINUTES = 30
_MAX_LOOKBACK_MINUTES = 60 * 24 * 7
_MAX_LIVE_EVENTS_LIMIT = min(MAX_LIMIT, 200)


@router.get("")
def list_live_events(
    minutes: int = Query(_DEFAULT_LOOKBACK_MINUTES, ge=1, le=_MAX_LOOKBACK_MINUTES),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=_MAX_LIVE_EVENTS_LIMIT),
) -> Dict[str, Optional[List[dict]] | str]:
    client = SnowflakeClient()
    try:
        events = client.get_recent_live_events(
            since_minutes=minutes,
            limit=limit,
        )
        return {
            "timezone": _TIMEZONE,
            "events": events,
        }
    finally:
        client.close()
