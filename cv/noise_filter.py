from __future__ import annotations

from typing import Optional

from cv.models import Observation


def should_send(
    obs: Observation,
    prev_sent: Optional[Observation],
    *,
    in_concern_window: bool = False,
    min_confidence: float = 0.6,
    min_frame_quality: float = 0.4,
) -> bool:
    if obs.frame_quality < min_frame_quality:
        return False

    if not obs.person_detected and not in_concern_window:
        return False

    if obs.pose_confidence < min_confidence or obs.activity_confidence < min_confidence:
        return False

    if prev_sent is None:
        return True

    same_pose = obs.pose == prev_sent.pose
    same_activity = obs.activity == prev_sent.activity
    same_objects = obs.objects_detected == prev_sent.objects_detected
    if same_pose and same_activity and same_objects:
        return False

    return True
