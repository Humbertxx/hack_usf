from datetime import datetime, timedelta, timezone

from cv.alert_engine import AlertEngine
from cv.models import (
    ActivityType,
    MotionLevel,
    Observation,
    PoseType,
    Severity,
)


def _obs(
    oid: str,
    *,
    person: bool = True,
    pose: PoseType = PoseType.STANDING,
    motion: MotionLevel = MotionLevel.NORMAL,
    minutes_unseen: int = 0,
    at: datetime | None = None,
    pose_confidence: float = 0.9,
) -> Observation:
    t = at or datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    return Observation(
        id=oid,
        observed_at=t,
        person_detected=person,
        pose=pose,
        pose_confidence=pose_confidence,
        activity=ActivityType.IDLE,
        activity_confidence=0.8,
        objects_detected=[],
        room_hint="",
        is_fall_risk=False,
        motion_level=motion,
        minutes_since_last_seen=minutes_unseen,
        frame_quality=0.9,
        session_id="s",
    )


def test_fall_detected_when_lying_after_standing() -> None:
    eng = AlertEngine()
    t0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert eng.check(_obs("1", pose=PoseType.STANDING, at=t0)) is None
    alert = eng.check(_obs("2", pose=PoseType.LYING, at=t0 + timedelta(seconds=1)))
    assert alert is not None
    assert alert.alert_type == "fall_detected"
    assert alert.severity == Severity.CRITICAL
    assert alert.triggered_at == t0 + timedelta(seconds=1)


def test_fall_detected_when_lying_after_sitting() -> None:
    eng = AlertEngine()
    t0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert eng.check(_obs("1", pose=PoseType.SITTING, at=t0)) is None
    alert = eng.check(_obs("2", pose=PoseType.LYING, at=t0 + timedelta(seconds=1)))
    assert alert is not None
    assert alert.alert_type == "fall_detected"
    assert alert.severity == Severity.CRITICAL


def test_fall_detected_when_lying_after_walking() -> None:
    eng = AlertEngine()
    t0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert eng.check(_obs("1", pose=PoseType.WALKING, at=t0)) is None
    alert = eng.check(_obs("2", pose=PoseType.LYING, at=t0 + timedelta(seconds=2)))
    assert alert is not None
    assert alert.alert_type == "fall_detected"


def test_cold_start_lying_once_with_confidence() -> None:
    eng = AlertEngine()
    t0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    a1 = eng.check(
        _obs("1", pose=PoseType.LYING, at=t0, pose_confidence=0.5),
    )
    assert a1 is not None
    assert a1.alert_type == "fall_detected"
    assert "session start" in a1.quick_message.lower()
    a2 = eng.check(_obs("2", pose=PoseType.LYING, at=t0 + timedelta(seconds=1)))
    assert a2 is None


def test_cold_start_lying_skipped_when_pose_confidence_low() -> None:
    eng = AlertEngine()
    t0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert (
        eng.check(
            _obs("1", pose=PoseType.LYING, at=t0, pose_confidence=0.44),
        )
        is None
    )


def test_no_motion_after_threshold() -> None:
    eng = AlertEngine()
    t0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    eng.check(_obs("1", motion=MotionLevel.NONE, at=t0))
    past = t0 + timedelta(minutes=31)
    alert = eng.check(
        _obs("2", motion=MotionLevel.NONE, at=past),
        now=past,
        no_motion_threshold=timedelta(minutes=30),
    )
    assert alert is not None
    assert alert.alert_type == "no_motion"


def test_not_seen_when_minutes_high() -> None:
    eng = AlertEngine()
    t = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    alert = eng.check(
        _obs("1", person=False, minutes_unseen=121, at=t),
        now=t,
    )
    assert alert is not None
    assert alert.alert_type == "not_seen"
