from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional, Set, Tuple
from urllib.request import urlretrieve

import cv2
import mediapipe as mp
import numpy as np
import torch
from ultralytics import YOLO

from cv.models import ActivityType, MotionLevel, Observation, PoseType

_CACHE_DIR = Path(__file__).resolve().parent / ".cache"
_POSE_LITE_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_lite/float16/1/pose_landmarker_lite.task"
)

# BlazePose indices (identical across legacy PoseLandmarker and Tasks lists).
_L_SHOULDER, _R_SHOULDER, _L_HIP, _R_HIP = 11, 12, 23, 24


def _device() -> str:
    return "cuda:0" if torch.cuda.is_available() else "cpu"


def _frame_quality_score(gray: np.ndarray) -> float:
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    variance = float(lap.var())
    return float(max(0.0, min(1.0, variance / 800.0)))


def _infer_pose_type_from_landmarks(
    landmarks: Optional[List[Any]],
    motion_level: MotionLevel,
) -> Tuple[PoseType, float]:
    if not landmarks or len(landmarks) <= max(_L_HIP, _R_HIP):
        return PoseType.UNKNOWN, 0.0

    ls, rs, lh, rh = (
        landmarks[_L_SHOULDER],
        landmarks[_R_SHOULDER],
        landmarks[_L_HIP],
        landmarks[_R_HIP],
    )
    ls_v = min(
        _visibility(ls),
        _visibility(rs),
        _visibility(lh),
        _visibility(rh),
    )
    if ls_v < 0.35:
        return PoseType.UNKNOWN, float(ls_v)

    shoulder_y = (ls.y + rs.y) / 2.0
    hip_y = (lh.y + rh.y) / 2.0
    dy = shoulder_y - hip_y

    if abs(dy) < 0.07:
        pose = PoseType.LYING
    elif dy < -0.06:
        pose = PoseType.WALKING if motion_level in (MotionLevel.HIGH, MotionLevel.NORMAL) else PoseType.STANDING
    else:
        pose = PoseType.SITTING

    return pose, float(min(1.0, max(0.5, ls_v)))


def _visibility(lm: Any) -> float:
    v = getattr(lm, "visibility", None)
    if v is None:
        return 1.0
    return float(v)


def _infer_activity(pose: PoseType, labels: Set[str]) -> Tuple[ActivityType, float]:
    labels_l = {x.lower() for x in labels}

    if pose == PoseType.LYING and {"bed", "couch", "sofa"} & labels_l:
        return ActivityType.SLEEPING, 0.65
    if pose == PoseType.LYING:
        return ActivityType.IDLE, 0.55
    if {"oven", "microwave", "refrigerator", "sink"} & labels_l and pose in (
        PoseType.STANDING,
        PoseType.WALKING,
        PoseType.SITTING,
    ):
        return ActivityType.COOKING, 0.7
    if {"tv", "laptop", "remote"} & labels_l and pose in (PoseType.SITTING, PoseType.LYING):
        return ActivityType.WATCHING_TV, 0.65
    if (
        {"bowl", "banana", "apple", "bottle", "cup", "fork", "knife", "spoon", "sandwich", "pizza"} & labels_l
    ) and pose in (
        PoseType.SITTING,
        PoseType.STANDING,
    ):
        return ActivityType.EATING, 0.65
    if pose == PoseType.UNKNOWN:
        return ActivityType.UNKNOWN, 0.4
    return ActivityType.IDLE, 0.55


def _motion_from_keypoints(
    prev: Optional[np.ndarray],
    cur: Optional[np.ndarray],
) -> MotionLevel:
    if prev is None or cur is None or prev.shape != cur.shape:
        return MotionLevel.NORMAL
    delta = np.mean(np.abs(cur - prev))
    if delta < 0.008:
        return MotionLevel.NONE
    if delta < 0.018:
        return MotionLevel.LOW
    if delta < 0.045:
        return MotionLevel.NORMAL
    return MotionLevel.HIGH


def _keypoint_vector_from_landmarks(landmarks: Optional[List[Any]]) -> Optional[np.ndarray]:
    if not landmarks:
        return None
    pts: List[float] = []
    for lm in landmarks:
        vis = _visibility(lm)
        if vis < 0.25:
            pts.extend([0.0, 0.0, 0.0])
        else:
            pts.extend([float(lm.x), float(lm.y), float(vis)])
    return np.array(pts, dtype=np.float32)


def _ensure_pose_model(path: Path = _CACHE_DIR / "pose_landmarker_lite.task") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 10_000:
        return path
    urlretrieve(_POSE_LITE_URL, path)
    return path


@dataclass
class _PoseHandles:
    backend: str
    legacy: Any = None
    landmarker: Any = None
    video_ms: int = 0


def _build_pose_handles(backend_pref: str) -> _PoseHandles:
    pref = (backend_pref or "auto").strip().lower()
    if pref == "none":
        return _PoseHandles(backend="none")

    if pref in ("auto", "legacy") and hasattr(mp, "solutions") and hasattr(mp.solutions, "pose"):
        legacy = mp.solutions.pose.Pose(
            static_image_mode=False,
            model_complexity=1,
            enable_segmentation=False,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        return _PoseHandles(backend="legacy", legacy=legacy)

    if pref == "legacy":
        raise RuntimeError(
            "CV_POSE_BACKEND=legacy but mediapipe.solutions.pose is not available "
            "(common on Python 3.13+ wheels). Use Python 3.10–3.12, or CV_POSE_BACKEND=tasks, or none."
        )

    if pref in ("auto", "tasks"):
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision

        model_path = _ensure_pose_model()
        options = vision.PoseLandmarkerOptions(
            base_options=python.BaseOptions(
                model_asset_path=str(model_path),
                delegate=python.BaseOptions.Delegate.CPU,
            ),
            running_mode=vision.RunningMode.VIDEO,
            num_poses=1,
            min_pose_detection_confidence=0.5,
            min_pose_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        landmarker = vision.PoseLandmarker.create_from_options(options)
        return _PoseHandles(backend="tasks", landmarker=landmarker)

    return _PoseHandles(backend="none")


def _extract_landmarks_rgb(
    rgb: np.ndarray,
    handles: _PoseHandles,
    prev_kp: Optional[np.ndarray],
) -> Tuple[Optional[List[Any]], Optional[np.ndarray], MotionLevel]:
    if handles.backend == "legacy" and handles.legacy is not None:
        result = handles.legacy.process(rgb)
        plm = result.pose_landmarks
        if plm is None:
            kp_vec = None
            motion = _motion_from_keypoints(prev_kp, None)
            return None, kp_vec, motion
        landmarks = list(plm.landmark)
        kp_vec = _keypoint_vector_from_landmarks(landmarks)
        motion = _motion_from_keypoints(prev_kp, kp_vec)
        return landmarks, kp_vec, motion

    if handles.backend == "tasks" and handles.landmarker is not None:
        handles.video_ms += 33
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = handles.landmarker.detect_for_video(mp_image, handles.video_ms)
        if not result.pose_landmarks:
            kp_vec = None
            motion = _motion_from_keypoints(prev_kp, None)
            return None, kp_vec, motion
        landmarks = list(result.pose_landmarks[0])
        kp_vec = _keypoint_vector_from_landmarks(landmarks)
        motion = _motion_from_keypoints(prev_kp, kp_vec)
        return landmarks, kp_vec, motion

    return None, None, MotionLevel.NORMAL


class CVPipeline:
    def __init__(
        self,
        yolo_model_name: str = "yolov8n.pt",
        *,
        pose_backend: Optional[str] = None,
    ) -> None:
        self._device = _device()
        self.yolo_model = YOLO(yolo_model_name)
        pref = pose_backend if pose_backend is not None else os.environ.get("CV_POSE_BACKEND", "auto")
        try:
            self._pose = _build_pose_handles(pref)
        except RuntimeError:
            self._pose = _PoseHandles(backend="none")
        self._prev_kp: Optional[np.ndarray] = None

    def close(self) -> None:
        if self._pose.backend == "legacy" and self._pose.legacy is not None:
            self._pose.legacy.close()
        if self._pose.backend == "tasks" and self._pose.landmarker is not None:
            self._pose.landmarker.close()

    def process_frame(
        self,
        frame: np.ndarray,
        *,
        session_id: str,
        minutes_since_last_seen_if_absent: int = 0,
    ) -> Observation:
        if frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError("frame must be HxWx3 BGR uint8")

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        quality = _frame_quality_score(gray)

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        landmarks, kp_vec, motion = _extract_landmarks_rgb(rgb, self._pose, self._prev_kp)
        self._prev_kp = kp_vec

        pose_type, pose_conf = _infer_pose_type_from_landmarks(landmarks, motion)

        results = self.yolo_model.predict(
            source=frame,
            device=self._device,
            imgsz=640,
            verbose=False,
        )
        raw_labels: List[str] = []
        person_detected = False
        if results:
            r = results[0]
            if r.boxes is not None and len(r.boxes):
                names = r.names or {}
                for cls, conf in zip(r.boxes.cls.tolist(), r.boxes.conf.tolist()):
                    if conf < 0.35:
                        continue
                    name = str(names.get(int(cls), str(int(cls))))
                    raw_labels.append(name)
                    if int(cls) == 0:
                        person_detected = True

        labels = sorted({x for x in raw_labels})

        if kp_vec is not None and pose_conf >= 0.35:
            person_detected = person_detected or True

        activity, act_conf = _infer_activity(pose_type, set(labels))

        observed_at = datetime.now(timezone.utc)
        oid = str(uuid.uuid4())
        room_hint = "unknown"
        if labels:
            room_hint = labels[0]

        is_fall_risk = person_detected and pose_type == PoseType.LYING and pose_conf >= 0.45

        mins_unseen = 0 if person_detected else max(0, int(minutes_since_last_seen_if_absent))

        return Observation(
            id=oid,
            observed_at=observed_at,
            person_detected=person_detected,
            pose=pose_type,
            pose_confidence=pose_conf,
            activity=activity,
            activity_confidence=act_conf,
            objects_detected=sorted(labels),
            room_hint=room_hint,
            is_fall_risk=is_fall_risk,
            motion_level=motion,
            minutes_since_last_seen=mins_unseen,
            frame_quality=quality,
            session_id=session_id,
        )
