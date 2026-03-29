from __future__ import annotations

from typing import Optional

from cv.models import Observation


def should_send(
    obs: Observation,
    prev_sent: Optional[Observation],
    *,
    in_concern_window: bool = False,
    min_pose_confidence: float = 0.5,
    min_activity_confidence: float = 0.55,
    min_frame_quality: float = 0.4,
) -> bool:
    """
    Gate before Snowflake. Thresholds align with cv_pipeline outputs:
    - Pose uses max(0.5, visibility) → floor 0.5
    - IDLE / lying-idle activities use 0.55 (not 0.6), so a single min for both blocked almost all idle frames.
    """
    if obs.frame_quality < min_frame_quality:
        print(f"[NoiseFilter] Rejected: frame_quality={obs.frame_quality:.2f} < {min_frame_quality}")
        return False

    if not obs.person_detected and not in_concern_window:
        print(f"[NoiseFilter] Rejected: no person detected and not in concern window")
        return False

    if (
        obs.pose_confidence < min_pose_confidence
        or obs.activity_confidence < min_activity_confidence
    ):
        print(f"[NoiseFilter] Rejected: pose_conf={obs.pose_confidence:.2f}, activity_conf={obs.activity_confidence:.2f}")
        return False

    if prev_sent is None:
        print(f"[NoiseFilter] Accepted: first observation")
        return True

    same_pose = obs.pose == prev_sent.pose
    same_activity = obs.activity == prev_sent.activity
    same_objects = obs.objects_detected == prev_sent.objects_detected
    if same_pose and same_activity and same_objects:
        print(f"[NoiseFilter] Rejected: duplicate (pose={obs.pose}, activity={obs.activity})")
        return False

    print(f"[NoiseFilter] Accepted: state changed (pose={obs.pose}, activity={obs.activity})")
    return True
