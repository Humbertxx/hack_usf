from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional


class PoseType(str, Enum):
    STANDING = "standing"
    SITTING = "sitting"
    LYING = "lying"
    WALKING = "walking"
    UNKNOWN = "unknown"


class ActivityType(str, Enum):
    EATING = "eating"
    WATCHING_TV = "watching_tv"
    SLEEPING = "sleeping"
    COOKING = "cooking"
    IDLE = "idle"
    UNKNOWN = "unknown"


class MotionLevel(str, Enum):
    NONE = "none"
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class AlertType(str, Enum):
    FALL_DETECTED = "fall_detected"
    NO_MOTION = "no_motion"
    NOT_SEEN = "not_seen"


class Severity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


@dataclass
class Observation:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    person_detected: bool = False
    pose: Optional[PoseType | str] = None
    pose_confidence: Optional[float] = None

    activity: Optional[ActivityType | str] = None
    activity_confidence: Optional[float] = None

    objects_detected: List[str] = field(default_factory=list)
    room_hint: Optional[str] = None

    is_fall_risk: bool = False
    motion_level: Optional[MotionLevel | str] = None
    minutes_since_last_seen: int = 0

    frame_quality: Optional[float] = None
    session_id: Optional[str] = None


@dataclass
class Alert:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    observation_id: Optional[str] = None
    alert_type: AlertType | str = AlertType.NO_MOTION
    severity: Severity | str = Severity.INFO
    triggered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    quick_message: Optional[str] = None
    acknowledged: bool = False
