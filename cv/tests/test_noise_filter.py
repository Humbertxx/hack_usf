from datetime import datetime, timezone

from cv.models import (
    ActivityType,
    MotionLevel,
    Observation,
    PoseType,
)
from cv.noise_filter import should_send


def _obs(**overrides) -> Observation:
    base = dict(
        id="1",
        observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        person_detected=True,
        pose=PoseType.STANDING,
        pose_confidence=0.9,
        activity=ActivityType.IDLE,
        activity_confidence=0.9,
        objects_detected=["chair"],
        room_hint="r",
        is_fall_risk=False,
        motion_level=MotionLevel.NORMAL,
        minutes_since_last_seen=0,
        frame_quality=0.8,
        session_id="s",
    )
    base.update(overrides)
    return Observation(**base)


def test_noise_filter_skips_low_quality() -> None:
    obs = _obs(frame_quality=0.1)
    assert should_send(obs, None) is False


def test_noise_filter_skips_no_person_without_concern() -> None:
    obs = _obs(person_detected=False, frame_quality=0.9, minutes_since_last_seen=5)
    assert should_send(obs, None, in_concern_window=False) is False


def test_noise_filter_allows_no_person_in_concern_window() -> None:
    obs = _obs(
        person_detected=False,
        pose_confidence=0.0,
        activity_confidence=0.0,
        pose=PoseType.UNKNOWN,
        activity=ActivityType.UNKNOWN,
        frame_quality=0.9,
    )
    # confidence gate still applies unless we lower threshold
    assert should_send(obs, None, in_concern_window=True, min_confidence=0.0) is True


def test_noise_filter_skips_low_confidence() -> None:
    obs = _obs(pose_confidence=0.2)
    assert should_send(obs, None) is False


def test_noise_filter_skips_duplicate_of_previous() -> None:
    first = _obs()
    second = first.model_copy(update={"id": "2"})
    assert should_send(first, None) is True
    assert should_send(second, first) is False


def test_noise_filter_allows_when_objects_change() -> None:
    first = _obs()
    second = first.model_copy(update={"id": "2", "objects_detected": ["tv"]})
    assert should_send(second, first) is True
