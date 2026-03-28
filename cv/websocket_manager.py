from __future__ import annotations

from collections import deque
from typing import Any, Deque, Dict, List, Optional

from fastapi import WebSocket

from cv.models import Alert, Observation

# Wire format:
# - {"type": "observation", "payload": <Observation as JSON>}
# - {"type": "alert", "priority": <Severity value>, "payload": <Alert as JSON>}
# Client ack: {"type": "ack", "alert_id": "<uuid>"}


class WebSocketManager:
    """Tracks WebSocket clients and broadcasts observations / alerts."""

    def __init__(self, *, max_tracked_alerts: int = 1000) -> None:
        self._connections: List[WebSocket] = []
        self._alerts_by_id: Dict[str, Alert] = {}
        self._alert_order: Deque[str] = deque()
        self._max_tracked_alerts = max(1, max_tracked_alerts)

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self._connections:
            self._connections.remove(websocket)

    def register_alert(self, alert: Alert) -> None:
        self._alerts_by_id[alert.id] = alert
        self._alert_order.append(alert.id)
        while len(self._alert_order) > self._max_tracked_alerts:
            oldest = self._alert_order.popleft()
            self._alerts_by_id.pop(oldest, None)

    def get_alert(self, alert_id: str) -> Optional[Alert]:
        return self._alerts_by_id.get(alert_id)

    def process_client_message(self, data: Any) -> bool:
        if not isinstance(data, dict):
            return False
        if data.get("type") != "ack":
            return False
        alert_id = data.get("alert_id")
        if not isinstance(alert_id, str) or not alert_id:
            return False
        existing = self._alerts_by_id.get(alert_id)
        if existing is None:
            return False
        updated = existing.model_copy(update={"acknowledged": True})
        self._alerts_by_id[alert_id] = updated
        return True

    async def broadcast_json(self, message: dict) -> None:
        if not self._connections:
            return
        dead: List[WebSocket] = []
        for ws in list(self._connections):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def broadcast_observation(self, obs: Observation) -> None:
        await self.broadcast_json(
            {"type": "observation", "payload": obs.model_dump(mode="json")}
        )

    async def broadcast_alert(self, alert: Alert) -> None:
        await self.broadcast_json(
            {
                "type": "alert",
                "priority": alert.severity.value,
                "payload": alert.model_dump(mode="json"),
            }
        )
