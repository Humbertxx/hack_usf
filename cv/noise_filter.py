from __future__ import annotations

from typing import Optional

from cv.models import Observation

# High-confidence identity match bypasses pose/activity requirements
# (e.g., sitting at desk where MediaPipe can't see full body) test
HIGH_IDENTITY_CONFIDENCE = 0.75


def should_send(
    obs: Observation,
    prev_sent: Optional[Observation],
    *,
    in_concern_window: bool = False,
    min_pose_confidence: float = 0.35,  # Lowered for upper-body-only fallback detection
    min_activity_confidence: float = 0.45,  # Lowered to allow context-based activity inference
    min_frame_quality: float = 0.2,
) -> bool:
    """
    Gate before Snowflake.
    
    If we have a high-confidence identity match (enrolled person like Grandma),
    we're more lenient on pose/activity since the person detection itself is valuable.
    
    Thresholds align with cv_pipeline outputs:
    - Pose uses max(0.5, visibility) → floor 0.5
    - IDLE / lying-idle activities use 0.55 (not 0.6)
    """
    if obs.frame_quality < min_frame_quality:
        print(f"[NoiseFilter] Rejected: frame_quality={obs.frame_quality:.2f} < {min_frame_quality}")
        return False

    if not obs.person_detected and not in_concern_window:
        print(f"[NoiseFilter] Rejected: no person detected and not in concern window")
        return False

    # Check if we have a high-confidence enrolled identity
    has_strong_identity = (
        obs.primary_person_id is not None 
        and obs.primary_identity_confidence is not None
        and obs.primary_identity_confidence >= HIGH_IDENTITY_CONFIDENCE
    )

    # If pose/activity confidence is low but we have strong identity, allow it
    if (
        obs.pose_confidence < min_pose_confidence
        or obs.activity_confidence < min_activity_confidence
    ):
        if has_strong_identity:
            print(f"[NoiseFilter] Accepted: low pose/activity but strong identity "
                  f"({obs.primary_display_name} conf={obs.primary_identity_confidence:.2f})")
        else:
            print(f"[NoiseFilter] Rejected: pose_conf={obs.pose_confidence:.2f}, activity_conf={obs.activity_confidence:.2f}")
            return False

    if prev_sent is None:
        print(f"[NoiseFilter] Accepted: first observation")
        return True

    same_pose = obs.pose == prev_sent.pose
    same_activity = obs.activity == prev_sent.activity
    same_objects = obs.objects_detected == prev_sent.objects_detected
    
    # For strong identity matches, also check if identity changed
    same_identity = obs.primary_person_id == prev_sent.primary_person_id
    
    if same_pose and same_activity and same_objects and same_identity:
        print(f"[NoiseFilter] Rejected: duplicate (pose={obs.pose}, activity={obs.activity}, identity={obs.primary_person_id})")
        return False

    print(f"[NoiseFilter] Accepted: state changed (pose={obs.pose}, activity={obs.activity})")
    return True
