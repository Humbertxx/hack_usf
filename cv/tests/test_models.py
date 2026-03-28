from datetime import datetime, timezone

from cv.models import (
    ActivityType,
    Alert,
    MotionLevel,
    Observation,
    PoseType,
    Severity,
)


def test_observation_roundtrip_json() -> None:
    obs = Observation(
        id="o1",
        observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        person_detected=True,
        pose=PoseType.STANDING,
        pose_confidence=0.9,
        activity=ActivityType.IDLE,
        activity_confidence=0.8,
        objects_detected=["chair"],
        room_hint="living",
        is_fall_risk=False,
        motion_level=MotionLevel.LOW,
        minutes_since_last_seen=0,
        frame_quality=0.85,
        session_id="sess",
    )
    data = obs.model_dump(mode="json")
    back = Observation.model_validate(data)
    assert back == obs


def test_alert_defaults() -> None:
    alert = Alert(
        id="a1",
        observation_id="o1",
        alert_type="fall_detected",
        severity=Severity.CRITICAL,
        triggered_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        quick_message="test",
    )
    assert alert.acknowledged is False
