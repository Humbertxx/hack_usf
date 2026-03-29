from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from cv.models import Alert, MotionLevel, Observation, PoseType, Severity


@dataclass
class AlertEngineState:
    previous_pose: Optional[PoseType] = None
    last_person_seen_at: Optional[datetime] = None
    motion_none_since: Optional[datetime] = None
    cold_start_lying_emitted: bool = False


class AlertEngine:
    def __init__(self) -> None:
        self._state = AlertEngineState()

    def check(
        self,
        observation: Observation,
        *,
        now: Optional[datetime] = None,
        no_motion_threshold: timedelta = timedelta(minutes=30),
        not_seen_since_person_threshold: timedelta = timedelta(minutes=120),
        cold_start_pose_confidence: float = 0.45,
    ) -> Optional[Alert]:
        t = now or datetime.now(timezone.utc)
        obs_time = observation.observed_at
        if obs_time.tzinfo is None:
            obs_time = obs_time.replace(tzinfo=timezone.utc)

        prev_pose = self._state.previous_pose
        self._state.previous_pose = observation.pose

        if observation.person_detected:
            self._state.last_person_seen_at = obs_time
            if observation.motion_level != MotionLevel.NONE:
                self._state.motion_none_since = None
            elif self._state.motion_none_since is None:
                self._state.motion_none_since = obs_time
        else:
            self._state.motion_none_since = None

        # Fall / collapse: upright or seated → lying (aligns with is_fall_risk on sustained lying).
        if observation.pose == PoseType.LYING and prev_pose in (
            PoseType.STANDING,
            PoseType.WALKING,
            PoseType.SITTING,
        ):
            return Alert(
                id=str(uuid.uuid4()),
                observation_id=observation.id,
                alert_type="fall_detected",
                severity=Severity.CRITICAL,
                triggered_at=obs_time,
                quick_message=(
                    "Possible fall: transitioned to lying from standing, walking, or sitting"
                ),
            )

        # Session starts with person already lying — one alert per engine lifetime (demo / cold start).
        if (
            prev_pose is None
            and observation.pose == PoseType.LYING
            and observation.person_detected
            and observation.pose_confidence >= cold_start_pose_confidence
            and not self._state.cold_start_lying_emitted
        ):
            self._state.cold_start_lying_emitted = True
            return Alert(
                id=str(uuid.uuid4()),
                observation_id=observation.id,
                alert_type="fall_detected",
                severity=Severity.CRITICAL,
                triggered_at=obs_time,
                quick_message="Person on ground at session start — verify",
            )

        if observation.person_detected and self._state.motion_none_since is not None:
            if observation.motion_level == MotionLevel.NONE:
                if obs_time - self._state.motion_none_since >= no_motion_threshold:
                    return Alert(
                        id=str(uuid.uuid4()),
                        observation_id=observation.id,
                        alert_type="no_motion",
                        severity=Severity.CRITICAL,
                        triggered_at=t,
                        quick_message="No meaningful motion detected for an extended period",
                    )
            else:
                self._state.motion_none_since = None

        last_seen = self._state.last_person_seen_at
        minutes_stale = observation.minutes_since_last_seen >= int(
            not_seen_since_person_threshold.total_seconds() // 60
        )
        internal_stale = (
            last_seen is not None
            and obs_time - last_seen >= not_seen_since_person_threshold
        )
        if not observation.person_detected and (minutes_stale or internal_stale):
            return Alert(
                id=str(uuid.uuid4()),
                observation_id=observation.id,
                alert_type="not_seen",
                severity=Severity.WARNING,
                triggered_at=t,
                quick_message="No person detected for an extended period since last sighting",
            )

        return None
