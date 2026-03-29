from __future__ import annotations

import uuid
from datetime import datetime, timezone

import cv2
import numpy as np
import pytest
from starlette.testclient import TestClient

from cv.main import create_app
from cv.models import (
    ActivityType,
    Alert,
    MotionLevel,
    Observation,
    PoseType,
    Severity,
)


def _jpeg_bytes() -> bytes:
    img = np.zeros((16, 16, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


def _stub_obs(session_id: str = "default") -> Observation:
    return Observation(
        id=str(uuid.uuid4()),
        observed_at=datetime.now(timezone.utc),
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
        session_id=session_id,
    )


class StubPipeline:
    def __init__(self) -> None:
        self.closed = False

    def process_frame(
        self,
        frame: np.ndarray,
        *,
        session_id: str,
        minutes_since_last_seen_if_absent: int = 0,
    ) -> Observation:
        return _stub_obs(session_id)

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def stub_app():
    stub = StubPipeline()
    app = create_app(pipeline_factory=lambda: stub)
    yield app, stub


def test_health(stub_app) -> None:
    app, _ = stub_app
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


class _SnowflakeLiveEventsStub:
    def get_recent_live_events(self, *, since_minutes: int = 30, limit: int = 50):
        return [
            {
                "id": "evt-1",
                "event_type": "eating",
                "headline": "Lunch",
                "summary": "Had lunch.",
                "meal_kind": "lunch",
                "observed_at": "2026-03-29T12:00:00-04:00",
                "display_name": "Grandma",
                "frame_thumb_base64": None,
            }
        ]

    def add_observation(self, obs) -> None:
        pass

    def add_alert(self, alert) -> None:
        pass

    def flush(self) -> None:
        pass


def test_live_events_reads_from_snowflake_stub() -> None:
    app = create_app(
        pipeline_factory=lambda: StubPipeline(),
        snowflake=_SnowflakeLiveEventsStub(),
    )
    with TestClient(app) as client:
        r = client.get("/api/live-events?minutes=30&limit=10")
        assert r.status_code == 200
        body = r.json()
        assert body["timezone"] == "America/New_York"
        assert len(body["events"]) == 1
        assert body["events"][0]["headline"] == "Lunch"
        assert body["events"][0]["event_type"] == "eating"


def test_process_frame_broadcasts_observation(stub_app) -> None:
    app, _ = stub_app
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            files = {"file": ("f.jpg", _jpeg_bytes(), "image/jpeg")}
            r = client.post("/process-frame?session_id=s1", files=files)
            assert r.status_code == 200
            body = r.json()
            assert body["ok"] is True
            assert body["filtered"] is False
            msg = ws.receive_json()
            assert msg["type"] == "observation"
            assert msg["payload"]["session_id"] == "s1"


def test_process_frame_second_identical_stub_filtered(stub_app) -> None:
    app, _ = stub_app
    with TestClient(app) as client:
        files = {"file": ("f.jpg", _jpeg_bytes(), "image/jpeg")}
        r1 = client.post("/process-frame", files=files)
        assert r1.json()["filtered"] is False
        r2 = client.post("/process-frame", files=files)
        assert r2.json()["filtered"] is True


def test_process_frame_rejects_bad_jpeg(stub_app) -> None:
    app, _ = stub_app
    with TestClient(app) as client:
        files = {"file": ("f.jpg", b"not-an-image", "image/jpeg")}
        r = client.post("/process-frame", files=files)
        assert r.status_code == 400


def test_websocket_ack_result(stub_app) -> None:
    app, _ = stub_app
    alert = Alert(
        id="ack-test-alert",
        observation_id="obs-x",
        alert_type="fall_detected",
        severity=Severity.CRITICAL,
        triggered_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        quick_message="m",
    )
    with TestClient(app) as client:
        app.state.ws_manager.register_alert(alert)
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "ack", "alert_id": alert.id})
            reply = ws.receive_json()
            assert reply["type"] == "ack_result"
            assert reply["ok"] is True
            assert app.state.ws_manager.get_alert(alert.id) is not None
            assert app.state.ws_manager.get_alert(alert.id).acknowledged is True


def test_pipeline_closed_on_app_shutdown(stub_app) -> None:
    app, stub = stub_app
    with TestClient(app):
        pass
    assert stub.closed is True
