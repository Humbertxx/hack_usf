from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from cv.models import (
    ActivityType,
    Alert,
    MotionLevel,
    Observation,
    PoseType,
    Severity,
)
from cv.websocket_manager import WebSocketManager


class _FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def accept(self) -> None:
        return None

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)


def _sample_observation(**kwargs: object) -> Observation:
    base: dict = dict(
        id="obs-1",
        observed_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        person_detected=True,
        pose=PoseType.STANDING,
        pose_confidence=0.9,
        activity=ActivityType.IDLE,
        activity_confidence=0.85,
        objects_detected=["chair"],
        room_hint="living",
        is_fall_risk=False,
        motion_level=MotionLevel.NORMAL,
        minutes_since_last_seen=0,
        frame_quality=0.9,
        session_id="sess",
    )
    base.update(kwargs)
    return Observation(**base)


def _sample_alert(**kwargs: object) -> Alert:
    base: dict = dict(
        id="alert-1",
        observation_id="obs-1",
        alert_type="fall_detected",
        severity=Severity.CRITICAL,
        triggered_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        quick_message="test",
    )
    base.update(kwargs)
    return Alert(**base)


def test_manager_connect_and_broadcast_observation() -> None:
    m = WebSocketManager()
    ws = _FakeWebSocket()
    asyncio.run(m.connect(ws))
    assert m.connection_count == 1
    obs = _sample_observation()
    asyncio.run(m.broadcast_observation(obs))
    assert len(ws.sent) == 1
    assert ws.sent[0]["type"] == "observation"
    assert ws.sent[0]["payload"]["id"] == obs.id
    m.disconnect(ws)
    assert m.connection_count == 0


def test_broadcast_alert_includes_priority() -> None:
    m = WebSocketManager()
    ws = _FakeWebSocket()
    asyncio.run(m.connect(ws))
    alert = _sample_alert()
    asyncio.run(m.broadcast_alert(alert))
    assert ws.sent[0]["type"] == "alert"
    assert ws.sent[0]["priority"] == "critical"
    assert ws.sent[0]["payload"]["alert_type"] == "fall_detected"


def test_ack_updates_tracked_alert() -> None:
    m = WebSocketManager()
    alert = _sample_alert(id="a-ack")
    m.register_alert(alert)
    assert m.get_alert("a-ack") is not None
    assert m.process_client_message({"type": "ack", "alert_id": "a-ack"}) is True
    updated = m.get_alert("a-ack")
    assert updated is not None
    assert updated.acknowledged is True


def test_ack_unknown_id_returns_false() -> None:
    m = WebSocketManager()
    assert m.process_client_message({"type": "ack", "alert_id": "missing"}) is False


def test_ack_invalid_payload() -> None:
    m = WebSocketManager()
    assert m.process_client_message({"type": "other"}) is False
    assert m.process_client_message("not-a-dict") is False


def test_dead_connection_removed_on_send_error() -> None:
    class BadWs(_FakeWebSocket):
        async def send_json(self, data: dict) -> None:
            raise OSError("closed")

    m = WebSocketManager()
    good = _FakeWebSocket()
    bad = BadWs()
    asyncio.run(m.connect(good))
    asyncio.run(m.connect(bad))
    asyncio.run(m.broadcast_observation(_sample_observation()))
    assert m.connection_count == 1
    assert len(good.sent) == 1
