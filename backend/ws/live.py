import asyncio
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

try:
    from backend.server.snowflake_client import SnowflakeClient
except ImportError:  # Backward-compatible fallback for backend-only execution.
    from server.snowflake_client import SnowflakeClient

router = APIRouter()

POLL_INTERVAL_SECONDS = float(os.getenv("WS_POLL_INTERVAL_SECONDS", "5"))


@router.websocket("/ws/live")
async def ws_live(websocket: WebSocket) -> None:
    await websocket.accept()
    client = SnowflakeClient()
    try:
        while True:
            observations, alerts, enriched, live_events = await asyncio.gather(
                asyncio.to_thread(client.get_recent_observations),
                asyncio.to_thread(client.get_unacknowledged_alerts),
                asyncio.to_thread(client.get_recent_enriched_observations),
                asyncio.to_thread(client.get_recent_live_events, since_minutes=30, limit=25),
            )
            payload: Dict[str, Any] = {
                "type": "live_update",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "observations": _safe_list(observations),
                "alerts": _safe_list(alerts),
                "enriched": _safe_list(enriched),
                "live_events": _safe_list(live_events),
            }
            await websocket.send_json(payload)
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
    except WebSocketDisconnect:
        return
    finally:
        client.close()


def _safe_list(value: List[dict] | None) -> List[dict]:
    return value if value is not None else []
