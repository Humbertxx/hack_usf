from typing import Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Query

try:
    from backend.config import DEFAULT_LIMIT, MAX_LIMIT
    from backend.server.snowflake_client import SnowflakeClient
except ImportError:  # Backward-compatible fallback for backend-only execution.
    from config import DEFAULT_LIMIT, MAX_LIMIT
    from server.snowflake_client import SnowflakeClient

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("")
def list_alerts(limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT), unacknowledged_only: bool = Query(True)) -> Dict[str, List[dict]]:
    client = SnowflakeClient()
    try:
        if unacknowledged_only:
            alerts = client.get_unacknowledged_alerts()
        else:
            alerts = client.get_recent_alerts()
        if limit and len(alerts) > limit:
            alerts = alerts[:limit]
        return {"alerts": alerts}
    finally:
        client.close()


@router.post("/acknowledge")
def acknowledge_alert(alert_id: str = Body(..., embed=True), acknowledged_by: Optional[str] = Body(None, embed=True)) -> Dict[str, str]:
    if not alert_id:
        raise HTTPException(status_code=400, detail="alert_id is required")
    client = SnowflakeClient()
    try:
        client.update_alert_acknowledged(alert_id, acknowledged_by)
        return {"status": "ok", "alert_id": alert_id}
    finally:
        client.close()
