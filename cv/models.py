from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

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


class Detection(BaseModel):
    label: str
    confidence: float
    bbox: List[float]  # [x1, y1, x2, y2] normalized 0-1
    person_id: Optional[str] = None
    display_name: Optional[str] = None
    is_enrolled: bool = False
    bbox_color: Optional[str] = None
    identity_confidence: Optional[float] = None


class Observation(BaseModel):
    id: str
    observed_at: datetime
    person_detected: bool
    pose: PoseType
    pose_confidence: float
    activity: ActivityType
    activity_confidence: float
    objects_detected: List[str]
    detections: List[Detection] = []  # Full detection info with bboxes
    room_hint: str
    is_fall_risk: bool
    motion_level: MotionLevel
    minutes_since_last_seen: int
    frame_quality: float
    session_id: str
    # Primary enrolled person (Grandma/Grandpa) - extracted from detections
    primary_person_id: Optional[str] = None
    primary_display_name: Optional[str] = None
    primary_identity_confidence: Optional[float] = None


class Alert(BaseModel):
    id: str
    observation_id: str
    alert_type: str
    severity: Severity
    triggered_at: datetime
    quick_message: str
    acknowledged: bool = False
