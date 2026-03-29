import asyncio
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from server.snowflake_client import SnowflakeClient

router = APIRouter()

POLL_INTERVAL_SECONDS = float(os.getenv("WS_POLL_INTERVAL_SECONDS"))


@router.websocket("/ws/live")
async def ws_live(websocket: WebSocket) -> None:
    await websocket.accept()
    client = SnowflakeClient()
    try:
        while True:
            payload: Dict[str, Any] = {
                "type": "live_update",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "observations": _safe_list(client.get_recent_observations()),
                "alerts": _safe_list(client.get_unacknowledged_alerts()),
                "enriched": _safe_list(client.get_recent_enriched_observations()),
            }
            await websocket.send_json(payload)
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
    except WebSocketDisconnect:
        return
    finally:
        client.close()


def _safe_list(value: List[dict] | None) -> List[dict]:
    return value if value is not None else []
