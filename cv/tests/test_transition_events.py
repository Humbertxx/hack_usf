from __future__ import annotations

import uuid
from datetime import datetime, timezone

from cv.models import ActivityType, MotionLevel, Observation, PoseType
from cv.transition_events import (
    DEDUPE_DRINKING,
    DEDUPE_EATING,
    DEDUPE_SIT_TO_WALK,
    DEDUPE_WALK_TO_SIT,
    collect_transition_events,
)


def _obs(
    *,
    pose: PoseType,
    activity: ActivityType = ActivityType.IDLE,
    prev_pose: PoseType | None = None,
) -> tuple[Observation | None, Observation]:
    def one(p: PoseType, a: ActivityType) -> Observation:
        return Observation(
            id=str(uuid.uuid4()),
            observed_at=datetime.now(timezone.utc),
            person_detected=True,
            pose=p,
            pose_confidence=0.9,
            activity=a,
            activity_confidence=0.85,
            objects_detected=[],
            room_hint="living",
            is_fall_risk=False,
            motion_level=MotionLevel.NORMAL,
            minutes_since_last_seen=0,
            frame_quality=0.9,
            session_id="s",
            primary_person_id="g",
            primary_display_name="Grandma",
            primary_identity_confidence=0.9,
        )

    prev = one(prev_pose, ActivityType.IDLE) if prev_pose is not None else None
    curr = one(pose, activity)
    return prev, curr


def test_sit_to_walk() -> None:
    prev, curr = _obs(prev_pose=PoseType.SITTING, pose=PoseType.WALKING)
    ev = collect_transition_events(prev, curr)
    assert len(ev) == 1
    assert ev[0]["dedupe_key"] == DEDUPE_SIT_TO_WALK


def test_walk_to_sit() -> None:
    prev, curr = _obs(prev_pose=PoseType.WALKING, pose=PoseType.SITTING)
    ev = collect_transition_events(prev, curr)
    assert len(ev) == 1
    assert ev[0]["dedupe_key"] == DEDUPE_WALK_TO_SIT


def test_sitting_to_standing_no_event() -> None:
    prev, curr = _obs(prev_pose=PoseType.SITTING, pose=PoseType.STANDING)
    ev = collect_transition_events(prev, curr)
    assert ev == []


def test_standing_to_walking_no_event() -> None:
    prev, curr = _obs(prev_pose=PoseType.STANDING, pose=PoseType.WALKING)
    ev = collect_transition_events(prev, curr)
    assert ev == []


def test_eating_edge_only() -> None:
    prev, curr = _obs(prev_pose=PoseType.SITTING, pose=PoseType.SITTING, activity=ActivityType.EATING)
    ev = collect_transition_events(prev, curr)
    assert len(ev) == 1
    assert ev[0]["dedupe_key"] == DEDUPE_EATING


def test_eating_no_duplicate_while_still_eating() -> None:
    prev, curr = _obs(prev_pose=PoseType.SITTING, pose=PoseType.STANDING)
    prev = prev.model_copy(update={"activity": ActivityType.EATING})
    curr = curr.model_copy(update={"activity": ActivityType.EATING})
    ev = collect_transition_events(prev, curr)
    assert DEDUPE_EATING not in {e["dedupe_key"] for e in ev}


def test_drinking_edge() -> None:
    prev, curr = _obs(prev_pose=PoseType.SITTING, pose=PoseType.SITTING, activity=ActivityType.IDLE)
    curr = curr.model_copy(
        update={"id": str(uuid.uuid4()), "activity": ActivityType.DRINKING},
    )
    ev = collect_transition_events(prev, curr)
    assert len(ev) == 1
    assert ev[0]["dedupe_key"] == DEDUPE_DRINKING


def test_first_frame_eating_prev_none() -> None:
    curr = Observation(
        id=str(uuid.uuid4()),
        observed_at=datetime.now(timezone.utc),
        person_detected=True,
        pose=PoseType.SITTING,
        pose_confidence=0.9,
        activity=ActivityType.EATING,
        activity_confidence=0.85,
        objects_detected=[],
        room_hint="living",
        is_fall_risk=False,
        motion_level=MotionLevel.NORMAL,
        minutes_since_last_seen=0,
        frame_quality=0.9,
        session_id="s",
        primary_person_id="g",
        primary_display_name="Grandma",
        primary_identity_confidence=0.9,
    )
    ev = collect_transition_events(None, curr)
    assert len(ev) == 1
    assert ev[0]["dedupe_key"] == DEDUPE_EATING
