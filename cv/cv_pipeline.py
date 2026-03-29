from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.request import urlretrieve

import cv2
import mediapipe as mp
import numpy as np
import torch
from ultralytics import YOLO

from cv.models import ActivityType, Detection, MotionLevel, Observation, PoseType

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


def _legacy_pose_handle() -> _PoseHandles:
    legacy = mp.solutions.pose.Pose(
        static_image_mode=False,
        model_complexity=1,
        enable_segmentation=False,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    return _PoseHandles(backend="legacy", legacy=legacy)


def _tasks_pose_handle() -> _PoseHandles:
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


def _build_pose_handles(backend_pref: str) -> _PoseHandles:
    pref = (backend_pref or "auto").strip().lower()
    if pref == "none":
        return _PoseHandles(backend="none")

    can_legacy = hasattr(mp, "solutions") and hasattr(mp.solutions, "pose")

    if pref == "legacy":
        if not can_legacy:
            raise RuntimeError(
                "CV_POSE_BACKEND=legacy but mediapipe.solutions.pose is not available "
                "(common on Python 3.13+ wheels). Use Python 3.10–3.12, or CV_POSE_BACKEND=tasks, or none."
            )
        return _legacy_pose_handle()

    if pref == "auto" and can_legacy:
        try:
            return _legacy_pose_handle()
        except Exception:
            pass

    if pref in ("auto", "tasks"):
        try:
            return _tasks_pose_handle()
        except OSError as exc:
            # Tasks API loads mediapipe .so's that link libGLESv2 (often absent in headless GPU containers).
            if pref == "tasks":
                raise RuntimeError(
                    "MediaPipe tasks pose failed to load native libraries (typical: missing libGLESv2.so.2). "
                    "On Debian/Ubuntu: apt-get install -y libgles2-mesa "
                    "or set CV_POSE_BACKEND=legacy (if available) or none. "
                    f"Original error: {exc}"
                ) from exc
            return _PoseHandles(backend="none")

    return _PoseHandles(backend="none")


@dataclass
class _VisitorEntry:
    """Tracks an anonymous visitor with embedding and timestamp."""
    embedding: np.ndarray
    last_seen: float  # time.time()
    visitor_id: str


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


def _yolo_model_name() -> str:
    return os.environ.get("CV_YOLO_MODEL", "yolov8l.pt")


def _yolo_imgsz() -> int:
    raw = os.environ.get("CV_YOLO_IMGSZ", "960")
    try:
        v = int(raw)
        return max(320, min(1280, v))
    except ValueError:
        return 960


def _normalize_yolo_label(label: str) -> str:
    """Lowercase and collapse whitespace for comparison with COCO-style names."""
    return " ".join(label.strip().lower().split())


# Default COCO-80 allowlist after removing:
# - All vehicles (bicycle, car, motorcycle, airplane, bus, train, truck, boat)
# - Travel / mobility gear (skis, snowboard, skateboard, surfboard, suitcase)
# - Outdoor-only street & play (traffic light, fire hydrant, stop sign, parking meter, bench, kite, frisbee)
# - Animals except cat and dog
# - Extra indoor-clutter / non-priority: backpack, baseball bat/glove, bed, clock, donut, hair drier,
#   handbag, hot dog, keyboard, laptop, mouse, oven, sports ball, teddy bear, tennis racket,
#   tie, toilet, toothbrush, umbrella, vase
#   (microwave kept for cooking activity cues)
# Person is always kept in the detection loop (also in this set for activity labels).
_YOLO_DEFAULT_ALLOWED_LABELS: frozenset[str] = frozenset(
    {
        "apple",
        "banana",
        "book",
        "bottle",
        "bowl",
        "broccoli",
        "cake",
        "carrot",
        "cat",
        "cell phone",
        "chair",
        "couch",
        "cup",
        "dining table",
        "dog",
        "fork",
        "knife",
        "microwave",
        "orange",
        "person",
        "pizza",
        "potted plant",
        "refrigerator",
        "remote",
        "sandwich",
        "scissors",
        "sink",
        "spoon",
        "toaster",
        "tv",
        "wine glass",
    }
)


def _yolo_allowed_labels() -> frozenset[str]:
    """
    Comma-separated override via CV_YOLO_ALLOWED_LABELS (normalized like COCO names).
    If unset, uses _YOLO_DEFAULT_ALLOWED_LABELS.
    """
    raw = os.environ.get("CV_YOLO_ALLOWED_LABELS", "").strip()
    if not raw:
        return _YOLO_DEFAULT_ALLOWED_LABELS
    parts = [_normalize_yolo_label(p) for p in raw.split(",") if p.strip()]
    return frozenset(parts)


def _yolo_label_kept(label: str, cls_id: int, allowed: frozenset[str]) -> bool:
    """Standard COCO: class 0 is person; always keep person for ReID."""
    key = _normalize_yolo_label(label)
    if cls_id == 0 or key == "person":
        return True
    return key in allowed


class CVPipeline:
    VISITOR_BUFFER_SIZE = 50
    VISITOR_TTL_SECONDS = 300  # 5 minutes

    def __init__(
        self,
        yolo_model_name: Optional[str] = None,
        *,
        pose_backend: Optional[str] = None,
        identity_store: Optional[Any] = None,
    ) -> None:
        self._device = _device()
        name = yolo_model_name if yolo_model_name is not None else _yolo_model_name()
        self.yolo_model = YOLO(name)
        self._yolo_imgsz = _yolo_imgsz()
        self._yolo_allowed_labels = _yolo_allowed_labels()
        pref = pose_backend if pose_backend is not None else os.environ.get("CV_POSE_BACKEND", "auto")
        self._pose = _build_pose_handles(pref)
        self._prev_kp: Optional[np.ndarray] = None

        self._identity_store = identity_store
        self._reid_embedder: Optional[Any] = None
        self._visitor_buffer: List[_VisitorEntry] = []
        self._visitor_counter = 0

        if identity_store is not None:
            from cv.reid_embeddings import ReIDEmbedder

            self._reid_embedder = ReIDEmbedder()
            print(
                f"[CVPipeline] YOLO={name} imgsz={self._yolo_imgsz} | "
                f"ReID={self._reid_embedder.model_name} | "
                f"subjects={identity_store.count} | "
                f"yolo_allowed={len(self._yolo_allowed_labels)}"
            )
        else:
            print(
                f"[CVPipeline] YOLO={name} imgsz={self._yolo_imgsz} | "
                f"ReID disabled | yolo_allowed={len(self._yolo_allowed_labels)}"
            )

    def close(self) -> None:
        if self._pose.backend == "legacy" and self._pose.legacy is not None:
            self._pose.legacy.close()
        if self._pose.backend == "tasks" and self._pose.landmarker is not None:
            self._pose.landmarker.close()

    def _crop_person(
        self,
        frame: np.ndarray,
        bbox: List[float],
        padding: float = 0.05,
    ) -> np.ndarray:
        """
        Crop a person from the frame using normalized bbox coordinates.
        
        Args:
            frame: BGR image (HxWx3)
            bbox: Normalized [x1, y1, x2, y2] in 0-1 range
            padding: Extra padding around the bbox (fraction of bbox size)
            
        Returns:
            Cropped BGR image of the person.
        """
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = bbox
        
        bw = x2 - x1
        bh = y2 - y1
        x1 = max(0, x1 - bw * padding)
        y1 = max(0, y1 - bh * padding)
        x2 = min(1, x2 + bw * padding)
        y2 = min(1, y2 + bh * padding)
        
        px1 = int(x1 * w)
        py1 = int(y1 * h)
        px2 = int(x2 * w)
        py2 = int(y2 * h)
        
        px1 = max(0, min(px1, w - 1))
        py1 = max(0, min(py1, h - 1))
        px2 = max(px1 + 1, min(px2, w))
        py2 = max(py1 + 1, min(py2, h))
        
        return frame[py1:py2, px1:px2].copy()

    def _cleanup_visitor_buffer(self) -> None:
        """Remove expired visitor entries from the buffer."""
        now = time.time()
        self._visitor_buffer = [
            v for v in self._visitor_buffer
            if now - v.last_seen < self.VISITOR_TTL_SECONDS
        ]
        while len(self._visitor_buffer) > self.VISITOR_BUFFER_SIZE:
            self._visitor_buffer.pop(0)

    def _assign_visitor_id(
        self,
        embedding: np.ndarray,
        threshold: float = 0.65,
    ) -> str:
        """
        Assign a visitor ID for a non-enrolled person.
        
        Matches against recent visitor embeddings for session-level tracking.
        Creates a new visitor ID if no match found.
        
        Args:
            embedding: 512-dim normalized embedding
            threshold: Similarity threshold for matching
            
        Returns:
            Visitor ID like "visitor_1", "visitor_2", etc.
        """
        self._cleanup_visitor_buffer()
        
        best_match: Optional[_VisitorEntry] = None
        best_score = threshold
        
        for entry in self._visitor_buffer:
            sim = float(np.dot(embedding.flatten(), entry.embedding.flatten()))
            if sim > best_score:
                best_score = sim
                best_match = entry
        
        if best_match is not None:
            best_match.last_seen = time.time()
            best_match.embedding = embedding
            return best_match.visitor_id
        
        self._visitor_counter += 1
        visitor_id = f"visitor_{self._visitor_counter}"
        
        self._visitor_buffer.append(_VisitorEntry(
            embedding=embedding,
            last_seen=time.time(),
            visitor_id=visitor_id,
        ))
        
        return visitor_id

    def _enrich_person_detection(
        self,
        frame: np.ndarray,
        detection: Detection,
    ) -> None:
        """
        Enrich a person detection with identity information.
        
        Extracts embedding, matches against enrolled subjects,
        and updates detection fields in-place.
        """
        if self._reid_embedder is None or self._identity_store is None:
            return
        
        try:
            crop = self._crop_person(frame, detection.bbox)
            if crop.size == 0 or crop.shape[0] < 10 or crop.shape[1] < 10:
                return
            
            embedding = self._reid_embedder.extract_embedding(crop)
            
            # Debug: compute similarity scores against all enrolled subjects
            match = self._identity_store.match(embedding, threshold=0.65)
            debug_match = self._identity_store.match(embedding, threshold=0.0)
            if debug_match:
                debug_id, debug_sim = debug_match
                print(f"[ReID Debug] Best match: {debug_id} with similarity {debug_sim:.3f} (threshold: 0.65)")
            
            if match:
                subject_id, similarity = match
                subject = self._identity_store.get(subject_id)
                if subject:
                    detection.person_id = subject_id
                    detection.display_name = subject.display_name
                    detection.is_enrolled = True
                    detection.bbox_color = subject.color
                    detection.identity_confidence = similarity
                    print(f"[ReID] MATCHED: {subject.display_name} (sim={similarity:.3f})")
            else:
                detection.person_id = self._assign_visitor_id(embedding)
                detection.is_enrolled = False
                detection.bbox_color = "#808080"  # Gray for visitors
                detection.identity_confidence = None
                print(f"[ReID] No match above threshold, assigned: {detection.person_id}")
        except Exception as e:
            print(f"[ReID] Error during enrichment: {e}")

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
            imgsz=self._yolo_imgsz,
            verbose=False,
        )
        raw_labels: List[str] = []
        detections: List[Detection] = []
        person_detected = False
        h, w = frame.shape[:2]
        if results:
            r = results[0]
            if r.boxes is not None and len(r.boxes):
                names = r.names or {}
                boxes_xyxy = r.boxes.xyxy.tolist() if r.boxes.xyxy is not None else []
                for i, (cls, conf) in enumerate(zip(r.boxes.cls.tolist(), r.boxes.conf.tolist())):
                    if conf < 0.35:
                        continue
                    name = str(names.get(int(cls), str(int(cls))))
                    cls_i = int(cls)
                    if not _yolo_label_kept(name, cls_i, self._yolo_allowed_labels):
                        continue
                    raw_labels.append(name)
                    is_person = cls_i == 0
                    if is_person:
                        person_detected = True
                    if i < len(boxes_xyxy):
                        x1, y1, x2, y2 = boxes_xyxy[i]
                        bbox = [x1 / w, y1 / h, x2 / w, y2 / h]
                    else:
                        bbox = [0.0, 0.0, 0.0, 0.0]
                    detection = Detection(label=name, confidence=float(conf), bbox=bbox)
                    if is_person:
                        print(f"[CVPipeline] Person detected, running ReID enrichment...")
                        self._enrich_person_detection(frame, detection)
                        print(f"[CVPipeline] After enrichment: person_id={detection.person_id}, display_name={detection.display_name}")
                    detections.append(detection)

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

        # Extract primary enrolled person (highest confidence Grandma/Grandpa)
        primary_person_id: Optional[str] = None
        primary_display_name: Optional[str] = None
        primary_identity_confidence: Optional[float] = None
        
        best_enrolled_conf = 0.0
        for det in detections:
            if det.label == "person" and det.is_enrolled and det.identity_confidence is not None:
                if det.identity_confidence > best_enrolled_conf:
                    best_enrolled_conf = det.identity_confidence
                    primary_person_id = det.person_id
                    primary_display_name = det.display_name
                    primary_identity_confidence = det.identity_confidence
        
        if primary_person_id:
            print(f"[CVPipeline] Primary person: {primary_display_name} (conf={primary_identity_confidence:.3f})")

        return Observation(
            id=oid,
            observed_at=observed_at,
            person_detected=person_detected,
            pose=pose_type,
            pose_confidence=pose_conf,
            activity=activity,
            activity_confidence=act_conf,
            objects_detected=sorted(labels),
            detections=detections,
            room_hint=room_hint,
            is_fall_risk=is_fall_risk,
            motion_level=motion,
            minutes_since_last_seen=mins_unseen,
            frame_quality=quality,
            session_id=session_id,
            primary_person_id=primary_person_id,
            primary_display_name=primary_display_name,
            primary_identity_confidence=primary_identity_confidence,
        )
