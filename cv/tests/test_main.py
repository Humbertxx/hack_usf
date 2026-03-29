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
        primary_person_id="stub_subject",
        primary_display_name="Stub Person",
        primary_identity_confidence=0.9,
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
    app = create_app(pipeline_factory=lambda: stub, snowflake=_NoSnowflake())
    yield app, stub


def test_health(stub_app) -> None:
    app, _ = stub_app
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


class _NoSnowflake:
    def add_observation(self, obs) -> None:
        pass

    def add_alert(self, alert) -> None:
        pass

    def flush(self) -> None:
        pass


class SeqPipeline:
    def __init__(self, observations: list[Observation]) -> None:
        self._observations = list(observations)
        self.i = 0
        self.closed = False

    def process_frame(
        self,
        frame: np.ndarray,
        *,
        session_id: str,
        minutes_since_last_seen_if_absent: int = 0,
    ) -> Observation:
        if self.i >= len(self._observations):
            return self._observations[-1]
        o = self._observations[self.i]
        self.i += 1
        return o

    def close(self) -> None:
        self.closed = True


def test_live_events_empty_buffer() -> None:
    app = create_app(
        pipeline_factory=lambda: StubPipeline(),
        snowflake=_NoSnowflake(),
    )
    with TestClient(app) as client:
        r = client.get("/api/live-events?limit=10")
        assert r.status_code == 200
        body = r.json()
        assert body["timezone"] == "America/New_York"
        assert body["events"] == []


def test_live_events_eating_edge_in_buffer() -> None:
    base_kw = dict(
        observed_at=datetime.now(timezone.utc),
        person_detected=True,
        pose_confidence=0.9,
        activity=ActivityType.IDLE,
        activity_confidence=0.85,
        objects_detected=[],
        room_hint="living",
        is_fall_risk=False,
        motion_level=MotionLevel.NORMAL,
        minutes_since_last_seen=0,
        frame_quality=0.9,
        session_id="s1",
        primary_person_id="g",
        primary_display_name="Grandma",
        primary_identity_confidence=0.9,
    )
    o1 = Observation(id=str(uuid.uuid4()), pose=PoseType.SITTING, **base_kw)
    o2 = Observation(
        id=str(uuid.uuid4()),
        pose=PoseType.SITTING,
        **{**base_kw, "activity": ActivityType.EATING, "objects_detected": ["fork"]},
    )
    app = create_app(
        pipeline_factory=lambda: SeqPipeline([o1, o2]),
        snowflake=_NoSnowflake(),
    )
    with TestClient(app) as client:
        files = {"file": ("f.jpg", _jpeg_bytes(), "image/jpeg")}
        assert client.post("/process-frame?session_id=s1", files=files).status_code == 200
        assert client.post("/process-frame?session_id=s1", files=files).status_code == 200
        r = client.get("/api/live-events?limit=10")
        keys = {e["dedupe_key"] for e in r.json()["events"]}
        assert "activity_eating" in keys


def test_primary_state_after_frame() -> None:
    app = create_app(
        pipeline_factory=lambda: StubPipeline(),
        snowflake=_NoSnowflake(),
    )
    with TestClient(app) as client:
        files = {"file": ("f.jpg", _jpeg_bytes(), "image/jpeg")}
        assert client.post("/process-frame", files=files).status_code == 200
        r = client.get("/api/primary-state")
        assert r.status_code == 200
        data = r.json()
        assert data["present"] is True
        assert data["pose"] == "standing"
        assert data["display_name"] == "Stub Person"


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
