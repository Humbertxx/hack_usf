from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List

from pydantic import BaseModel


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


class Severity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class Observation(BaseModel):
    id: str
    observed_at: datetime
    person_detected: bool
    pose: PoseType
    pose_confidence: float
    activity: ActivityType
    activity_confidence: float
    objects_detected: List[str]
    room_hint: str
    is_fall_risk: bool
    motion_level: MotionLevel
    minutes_since_last_seen: int
    frame_quality: float
    session_id: str


class Alert(BaseModel):
    id: str
    observation_id: str
    alert_type: str
    severity: Severity
    triggered_at: datetime
    quick_message: str
    acknowledged: bool = False
