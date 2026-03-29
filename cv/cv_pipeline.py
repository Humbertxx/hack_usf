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
_POSE_HEAVY_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_heavy/float16/latest/pose_landmarker_heavy.task"
)

# BlazePose landmark indices (identical across legacy PoseLandmarker and Tasks lists).
# Face landmarks
_NOSE = 0
_L_EYE_INNER, _L_EYE, _L_EYE_OUTER = 1, 2, 3
_R_EYE_INNER, _R_EYE, _R_EYE_OUTER = 4, 5, 6
_L_EAR, _R_EAR = 7, 8
_MOUTH_L, _MOUTH_R = 9, 10
# Upper body
_L_SHOULDER, _R_SHOULDER = 11, 12
_L_ELBOW, _R_ELBOW = 13, 14
_L_WRIST, _R_WRIST = 15, 16
# Lower body  
_L_HIP, _R_HIP = 23, 24
_L_KNEE, _R_KNEE = 25, 26


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
    """
    Infer pose type from MediaPipe landmarks with fallback for partial visibility.
    
    Full body mode: Uses shoulders + hips (most accurate)
    Upper body mode: Uses nose + shoulders when hips aren't visible (e.g., sitting at table)
    """
    if not landmarks or len(landmarks) <= max(_L_KNEE, _R_KNEE):
        return PoseType.UNKNOWN, 0.0

    ls = landmarks[_L_SHOULDER]
    rs = landmarks[_R_SHOULDER]
    lh = landmarks[_L_HIP]
    rh = landmarks[_R_HIP]
    nose = landmarks[_NOSE]
    
    shoulder_vis = min(_visibility(ls), _visibility(rs))
    hip_vis = min(_visibility(lh), _visibility(rh))
    nose_vis = _visibility(nose)
    
    # Try full body pose detection first (most accurate)
    full_body_vis = min(shoulder_vis, hip_vis)
    if full_body_vis >= 0.35:
        shoulder_y = (ls.y + rs.y) / 2.0
        hip_y = (lh.y + rh.y) / 2.0
        dy = shoulder_y - hip_y

        lk = landmarks[_L_KNEE]
        rk = landmarks[_R_KNEE]
        knee_vis = min(_visibility(lk), _visibility(rk))
        hip_knee_y: Optional[float] = None
        if knee_vis >= 0.25:
            knee_y = (lk.y + rk.y) / 2.0
            hip_knee_y = knee_y - hip_y  # + when knees below hips (image y downward)

        # Torso roughly horizontal → lying (tighter band than before to avoid seated slouch → lie)
        if abs(dy) < 0.055:
            pose = PoseType.LYING
        elif dy < -0.055:  # shoulders above hips: upright
            # Seated (webcam): bent knees → small vertical hip–knee gap vs standing
            if hip_knee_y is not None and hip_knee_y < 0.15:
                pose = PoseType.SITTING
            elif motion_level == MotionLevel.HIGH:
                pose = PoseType.WALKING
            else:
                pose = PoseType.STANDING
        else:
            pose = PoseType.SITTING

        return pose, float(min(1.0, max(0.5, full_body_vis)))
    
    # Fallback: upper body only (shoulders + nose/face visible, hips occluded)
    # Common when sitting at a table across from camera
    upper_body_vis = min(shoulder_vis, nose_vis)
    if upper_body_vis >= 0.35:
        shoulder_y = (ls.y + rs.y) / 2.0
        nose_y = nose.y
        
        # Vertical distance from nose to shoulders
        # Lying: nose and shoulders at similar height
        # Sitting/Standing: nose clearly above shoulders
        nose_shoulder_dy = shoulder_y - nose_y
        
        if abs(nose_shoulder_dy) < 0.05:
            # Nose at same level as shoulders = lying down
            pose = PoseType.LYING
        elif nose_shoulder_dy > 0.08:
            # Nose well above shoulders = upright (sitting or standing)
            # Without hips, bias seated; only HIGH frame motion → walking
            if motion_level == MotionLevel.HIGH:
                pose = PoseType.WALKING
            else:
                pose = PoseType.SITTING
        else:
            # Nose slightly above shoulders - likely sitting
            pose = PoseType.SITTING
        
        # Lower confidence since we're using fallback method
        return pose, float(min(0.7, max(0.4, upper_body_vis)))
    
    # Even more fallback: just shoulders visible (face turned away)
    if shoulder_vis >= 0.4:
        # Can't determine much without face or hips — avoid NORMAL→standing (reads as "walking" sit)
        if motion_level == MotionLevel.HIGH:
            return PoseType.WALKING, 0.4
        elif motion_level == MotionLevel.NONE:
            return PoseType.SITTING, 0.4
        else:
            return PoseType.SITTING, 0.35
    
    return PoseType.UNKNOWN, 0.0


def _visibility(lm: Any) -> float:
    v = getattr(lm, "visibility", None)
    if v is None:
        return 1.0
    return float(v)


def _infer_activity(pose: PoseType, labels: Set[str]) -> Tuple[ActivityType, float]:
    """
    Infer activity from pose and detected objects (eating vs drinking vs idle/unknown).
    Beverage-only detections map to drinking; food/utensils map to eating (including meal + drink).
    """
    labels_l = {x.lower() for x in labels}

    food_eating = {
        "bowl",
        "banana",
        "apple",
        "fork",
        "knife",
        "spoon",
        "sandwich",
        "pizza",
        "cake",
        "carrot",
        "orange",
        "broccoli",
    }
    beverage = {"bottle", "cup", "wine glass"}

    upright = (PoseType.SITTING, PoseType.STANDING, PoseType.UNKNOWN)

    if pose == PoseType.LYING:
        return ActivityType.IDLE, 0.55
    if food_eating & labels_l and pose in upright:
        return ActivityType.EATING, 0.65 if pose != PoseType.UNKNOWN else 0.5
    if beverage & labels_l and pose in upright:
        return ActivityType.DRINKING, 0.65 if pose != PoseType.UNKNOWN else 0.5

    if pose == PoseType.UNKNOWN:
        if {"chair", "dining table"} & labels_l:
            return ActivityType.IDLE, 0.5
        if {"couch", "sofa"} & labels_l:
            return ActivityType.IDLE, 0.5
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


def _ensure_pose_model(path: Path = _CACHE_DIR / "pose_landmarker_heavy.task") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 10_000:
        return path
    urlretrieve(_POSE_HEAVY_URL, path)
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
        model_complexity=2,
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
    """
    Pose backends:
    - tasks / auto: BlazePose **heavy** landmarker only (pose_landmarker_heavy.task). No legacy fallback.
    - legacy: optional mediapipe.solutions.pose (different stack; not the heavy .task bundle).
    - none: pose disabled.
    """
    pref = (backend_pref or "tasks").strip().lower()
    if pref == "auto":
        pref = "tasks"
    if pref == "none":
        return _PoseHandles(backend="none")

    can_legacy = hasattr(mp, "solutions") and hasattr(mp.solutions, "pose")

    if pref == "legacy":
        if not can_legacy:
            raise RuntimeError(
                "CV_POSE_BACKEND=legacy but mediapipe.solutions.pose is not available "
                "(common on Python 3.13+ wheels). Use CV_POSE_BACKEND=tasks for the heavy landmarker, or none."
            )
        return _legacy_pose_handle()

    if pref == "tasks":
        try:
            return _tasks_pose_handle()
        except OSError as exc:
            raise RuntimeError(
                "MediaPipe Pose Landmarker (heavy) failed to load native libraries "
                "(typical: missing libGLESv2.so.2). On Debian/Ubuntu: apt-get install -y libgles2-mesa. "
                "To run without pose, set CV_POSE_BACKEND=none. "
                f"Original error: {exc}"
            ) from exc

    raise ValueError(
        f"Unknown CV_POSE_BACKEND={backend_pref!r}; use tasks, auto, legacy, or none."
    )


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
    # YOLOv8 model variants (increasing accuracy & VRAM):
    #   yolov8n.pt (nano)   - ~3M params, fastest
    #   yolov8s.pt (small)  - ~11M params
    #   yolov8m.pt (medium) - ~26M params
    #   yolov8l.pt (large)  - ~44M params
    #   yolov8x.pt (xlarge) - ~68M params, highest accuracy
    return os.environ.get("CV_YOLO_MODEL", "yolov8x.pt")


def _yolo_imgsz() -> int:
    # Higher imgsz = more detail, better small object detection
    # 5090 can easily handle 1280 or higher
    raw = os.environ.get("CV_YOLO_IMGSZ", "1280")
    try:
        v = int(raw)
        return max(320, min(1920, v))
    except ValueError:
        return 1280


def _normalize_yolo_label(label: str) -> str:
    """Lowercase and collapse whitespace for comparison with COCO-style names."""
    return " ".join(label.strip().lower().split())


# Hackathon / expo default: person + chair (scale/context) + eat/drink COCO classes only.
# No kitchen fixtures, TV/remote, couch, dining table, pets, or clutter — use CV_YOLO_ALLOWED_LABELS to widen.
# Person is always kept in the detection loop (class 0); this set is for non-person labels.
_YOLO_DEFAULT_ALLOWED_LABELS: frozenset[str] = frozenset(
    {
        "apple",
        "banana",
        "bottle",
        "bowl",
        "broccoli",
        "cake",
        "carrot",
        "chair",
        "cup",
        "fork",
        "knife",
        "orange",
        "person",
        "pizza",
        "sandwich",
        "spoon",
        "wine glass",
    }
)

# Food / drink (handheld) — allow lower YOLO conf so bottles/cups still drive activity inference
_YOLO_ACTIVITY_CLASS_NAMES: frozenset[str] = frozenset(
    x for x in _YOLO_DEFAULT_ALLOWED_LABELS if x not in {"person", "chair"}
)


def _yolo_detection_conf_threshold(label: str) -> float:
    """Stricter conf for person/context; softer for eat/drink props (often small / partly occluded)."""
    if _normalize_yolo_label(label) in _YOLO_ACTIVITY_CLASS_NAMES:
        raw = os.environ.get("CV_YOLO_ACTIVITY_MIN_CONF", "0.22").strip()
        try:
            return max(0.05, min(0.9, float(raw)))
        except ValueError:
            return 0.22
    return 0.35


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


def _reid_match_threshold() -> float:
    try:
        return float(os.environ.get("CV_REID_MATCH_THRESHOLD", "0.65"))
    except ValueError:
        return 0.65


def _reid_sticky_floor(match_high: float) -> Optional[float]:
    """
    Optional second, lower cosine floor to keep the same subject_id when the best
    gallery template still wins but similarity dips (lighting / crop / pose).
    Set CV_REID_STICKY_THRESHOLD="" to disable.
    """
    raw = os.environ.get("CV_REID_STICKY_THRESHOLD", "0.58").strip()
    if raw == "":
        return None
    try:
        v = float(raw)
    except ValueError:
        v = 0.58
    if v >= match_high:
        return None
    return v


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
        pref = pose_backend if pose_backend is not None else os.environ.get("CV_POSE_BACKEND", "tasks")
        self._pose = _build_pose_handles(pref)
        self._prev_kp: Optional[np.ndarray] = None

        self._identity_store = identity_store
        self._reid_embedder: Optional[Any] = None
        self._visitor_buffer: List[_VisitorEntry] = []
        self._visitor_counter = 0
        self._reid_sticky_subject_id: Optional[str] = None

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

            th_match = _reid_match_threshold()
            th_sticky = _reid_sticky_floor(th_match)
            bm = self._identity_store.best_match(embedding)
            if bm:
                debug_id, debug_sim = bm
                sticky_note = f", sticky≥{th_sticky}" if th_sticky is not None else ""
                print(
                    f"[ReID Debug] Best match: {debug_id} with similarity {debug_sim:.3f} "
                    f"(accept≥{th_match}{sticky_note})"
                )

            if bm is None:
                self._reid_sticky_subject_id = None
                detection.person_id = self._assign_visitor_id(embedding)
                detection.is_enrolled = False
                detection.bbox_color = "#808080"
                detection.identity_confidence = None
                print(f"[ReID] No enrolled subjects; assigned: {detection.person_id}")
                return

            best_id, best_sim = bm
            use_enrolled = False
            if best_sim >= th_match:
                use_enrolled = True
            elif (
                th_sticky is not None
                and self._reid_sticky_subject_id is not None
                and best_id == self._reid_sticky_subject_id
                and best_sim >= th_sticky
            ):
                use_enrolled = True
                print(
                    f"[ReID] STICKY: {best_id} sim={best_sim:.3f} "
                    f"(holding identity; between {th_sticky} and {th_match})"
                )

            if use_enrolled:
                self._reid_sticky_subject_id = best_id
                subject = self._identity_store.get(best_id)
                if subject:
                    detection.person_id = best_id
                    detection.display_name = subject.display_name
                    detection.is_enrolled = True
                    detection.bbox_color = subject.color
                    detection.identity_confidence = best_sim
                    print(f"[ReID] MATCHED: {subject.display_name} (sim={best_sim:.3f})")
            else:
                self._reid_sticky_subject_id = None
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
                    name = str(names.get(int(cls), str(int(cls))))
                    if conf < _yolo_detection_conf_threshold(name):
                        continue
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
        # Expo demo: no room layout; column kept for schema / Snowflake compatibility.
        room_hint = "unknown"

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
