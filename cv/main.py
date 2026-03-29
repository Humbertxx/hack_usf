from __future__ import annotations

import base64
import os
import uuid
from collections import deque
from contextlib import asynccontextmanager
from datetime import timezone
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional

import cv2
import numpy as np
from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel, ConfigDict
from dotenv import load_dotenv

from cv.alert_engine import AlertEngine
from cv.cv_pipeline import CVPipeline
from cv.identity_store import IdentityStore
from cv.models import ActivityType, Alert, Observation, PoseType
from cv.noise_filter import should_send
from cv.reid_embeddings import ReIDEmbedder
from cv.snowflake_client import create_snowflake_client
from cv.transition_events import (
    DEDUPE_DRINKING,
    DEDUPE_EATING,
    DEDUPE_FALLEN,
    collect_transition_events,
)
from cv.websocket_manager import WebSocketManager

LIVE_EVENT_BUFFER_MAX = 200

_LIVE_EVENT_THUMB_KEYS = frozenset({DEDUPE_EATING, DEDUPE_DRINKING, DEDUPE_FALLEN})

# Snowflake / API gate for "this frame counts as the enrolled person."
# Default 0.58 pairs with CV_REID_STICKY_THRESHOLD hysteresis (see cv_pipeline); raise if you want stricter storage.
def _min_identity_confidence() -> float:
    raw = os.environ.get("CV_MIN_IDENTITY_CONFIDENCE", "0.58").strip()
    try:
        return float(raw)
    except ValueError:
        return 0.58


def _fall_min_pose_confidence() -> float:
    """Minimum pose confidence to treat a fall alert as real for UI, Snowflake, and WS."""
    raw = os.environ.get("CV_FALL_MIN_POSE_CONFIDENCE", "0.72").strip()
    try:
        return float(raw)
    except ValueError:
        return 0.72


def _is_confirmed_fall(obs: Observation, alert: Optional[Alert]) -> bool:
    if alert is None or alert.alert_type != "fall_detected":
        return False
    if obs.pose != PoseType.LYING:
        return False
    return obs.pose_confidence >= _fall_min_pose_confidence()


def _load_runtime_env() -> None:
    """
    Load likely env files for local development without overriding exported vars.

    Order matters: repo-root .env stays supported, but backend-local env files are
    also loaded because Snowflake credentials currently live there.
    """
    repo_root = Path(__file__).resolve().parent.parent
    load_dotenv(repo_root / ".env")
    load_dotenv(repo_root / "backend" / ".env.humberto")
    load_dotenv(repo_root / "backend" / ".env")


def should_send_to_snowflake(
    obs: Observation,
    prev_sent: Optional[Observation],
    *,
    in_concern_window: bool = False,
) -> bool:
    """
    Determine if an observation should be sent to Snowflake.
    
    Requirements:
    1. Must pass basic noise filter (confidence, quality thresholds)
    2. If person detected, must be an enrolled person (Grandma/Grandpa)
       with identity confidence >= CV_MIN_IDENTITY_CONFIDENCE (see _min_identity_confidence)
    
    This ensures only high-quality, identified observations are stored.
    """
    if not should_send(obs, prev_sent, in_concern_window=in_concern_window):
        return False
    
    # If person detected, require enrolled identity with high confidence
    if obs.person_detected:
        # Must have primary person identified (enrolled subject)
        if not obs.primary_person_id:
            print(f"[Snowflake Filter] Skipping: person detected but no enrolled identity")
            return False
        
        # Must have high enough identity confidence (defaults align with ReID sticky floor)
        min_id = _min_identity_confidence()
        if obs.primary_identity_confidence is None or obs.primary_identity_confidence < min_id:
            conf = obs.primary_identity_confidence or 0.0
            print(f"[Snowflake Filter] Skipping: identity confidence too low ({conf:.2f} < {min_id})")
            return False
    
    return True


_THUMB_MAX_WIDTH = 320
_THUMB_JPEG_QUALITY = 70


def _encode_frame_thumbnail_bgr(frame: np.ndarray) -> Optional[str]:
    """Resize and JPEG-encode a BGR frame; return base64 ASCII or None on failure."""
    if frame is None or frame.size == 0:
        return None
    h, w = frame.shape[:2]
    if w > _THUMB_MAX_WIDTH:
        scale = _THUMB_MAX_WIDTH / w
        new_w = _THUMB_MAX_WIDTH
        new_h = max(1, int(h * scale))
        frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(
        ".jpg",
        frame,
        [int(cv2.IMWRITE_JPEG_QUALITY), _THUMB_JPEG_QUALITY],
    )
    if not ok:
        return None
    return base64.b64encode(buf.tobytes()).decode("ascii")


def _should_persist_thumbnail(
    obs: Observation,
    alert: Optional[Alert],
    *,
    confirmed_fall: bool,
) -> bool:
    if confirmed_fall:
        return True
    if obs.is_fall_risk:
        return (
            obs.pose == PoseType.LYING
            and obs.pose_confidence >= _fall_min_pose_confidence()
        )
    if obs.activity == ActivityType.EATING:
        return True
    if obs.activity == ActivityType.DRINKING:
        return True
    return False


def _observed_at_iso(obs: Observation) -> str:
    t = obs.observed_at
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.isoformat()


class MockSnowflakeClient:
    def __init__(self) -> None:
        self.observations: list[Observation] = []
        self.alerts: list[Alert] = []

    def add_observation(self, obs: Observation) -> None:
        identity_info = ""
        if obs.primary_person_id:
            identity_info = f" | {obs.primary_display_name} (conf={obs.primary_identity_confidence:.2f})"
        print(f"[MOCK SNOWFLAKE] Observation: {obs.id} - {obs.pose} - {obs.activity}{identity_info}")
        self.observations.append(obs)

    def add_alert(self, alert: Alert) -> None:
        print(f"[MOCK SNOWFLAKE] Alert: {alert.alert_type} - {alert.quick_message}")
        self.alerts.append(alert)

    def flush(self) -> None:
        print("[MOCK SNOWFLAKE] Flushed batch")

    def get_recent_live_events(
        self,
        *,
        since_minutes: int = 30,
        limit: int = 50,
    ) -> List[dict[str, Any]]:
        return []


class ProcessFrameResponse(BaseModel):
    ok: bool
    filtered: bool
    observation: dict[str, Any]
    alert: Optional[dict[str, Any]] = None


class EnrollResponse(BaseModel):
    success: bool
    subject_id: str
    embedding_count: int
    message: str


class SubjectInfo(BaseModel):
    subject_id: str
    display_name: str
    color: str
    embedding_count: int
    enrolled_at: str


class SubjectListResponse(BaseModel):
    subjects: List[SubjectInfo]


class LiveEventItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    dedupe_key: str
    event_type: str
    headline: str
    observed_at: str
    display_name: Optional[str] = None
    frame_thumb_base64: Optional[str] = None
    summary: Optional[str] = None
    meal_kind: Optional[str] = None


class LiveEventsResponse(BaseModel):
    """In-memory transition feed from the CV service (not Snowflake-scheduled)."""

    timezone: str = "America/New_York"
    events: List[LiveEventItem]


class PrimaryStateResponse(BaseModel):
    """Latest primary-person snapshot after a frame was persisted."""

    present: bool = False
    timezone: str = "America/New_York"
    pose: Optional[str] = None
    display_name: Optional[str] = None
    observed_at: Optional[str] = None
    session_id: Optional[str] = None
    activity: Optional[str] = None
    fallen_attention: bool = False


def create_app(
    *,
    pipeline_factory: Optional[Callable[[], CVPipeline]] = None,
    snowflake: Optional[Any] = None,
    identity_store: Optional[IdentityStore] = None,
) -> FastAPI:
    _load_runtime_env()

    store = identity_store or IdentityStore()
    pipeline_factory = pipeline_factory or (lambda: CVPipeline(identity_store=store))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.pipeline = pipeline_factory()
        yield
        app.state.pipeline.close()

    app = FastAPI(lifespan=lifespan)
    app.state.alert_engine = AlertEngine()
    app.state.ws_manager = WebSocketManager()
    app.state.snowflake = snowflake or create_snowflake_client()
    app.state.prev_sent: Observation | None = None
    app.state.identity_store = store
    app.state.reid_embedder: Optional[ReIDEmbedder] = None
    app.state.live_event_buffer = deque(maxlen=LIVE_EVENT_BUFFER_MAX)
    app.state.last_primary_snapshot: Optional[Dict[str, Any]] = None
    app.state.fall_attention_latched = False

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/primary-state", response_model=PrimaryStateResponse)
    def primary_state() -> PrimaryStateResponse:
        snap = app.state.last_primary_snapshot
        if not snap:
            return PrimaryStateResponse(present=False)
        return PrimaryStateResponse(present=True, **snap)

    @app.get("/api/live-events", response_model=LiveEventsResponse)
    def live_events(
        minutes: int = Query(default=30, ge=1, le=10_080),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> LiveEventsResponse:
        """
        Recent transition events (newest first). The ``minutes`` query is ignored;
        only the in-memory ring buffer is used.
        """
        _ = minutes
        buf: Deque[dict[str, Any]] = app.state.live_event_buffer
        tail = list(reversed(buf))[:limit]
        events = [LiveEventItem.model_validate(row) for row in tail]
        return LiveEventsResponse(events=events)

    @app.post("/process-frame", response_model=ProcessFrameResponse)
    async def process_frame(
        file: UploadFile = File(...),
        session_id: str = Query(default="default"),
        in_concern_window: bool = Query(default=False),
    ) -> ProcessFrameResponse:
        raw = await file.read()
        arr = np.frombuffer(raw, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            raise HTTPException(status_code=400, detail="Invalid or empty JPEG")

        obs = app.state.pipeline.process_frame(frame, session_id=session_id)
        obs_json = obs.model_dump(mode="json")

        should_send_result = should_send_to_snowflake(
            obs,
            app.state.prev_sent,
            in_concern_window=in_concern_window,
        )
        
        if not should_send_result:
            # Debug: show why it was filtered
            if obs.primary_person_id:
                print(f"[Snowflake Filter] Filtered despite identity: {obs.primary_display_name} (conf={obs.primary_identity_confidence:.3f})")
                if app.state.prev_sent:
                    same_pose = obs.pose == app.state.prev_sent.pose
                    same_activity = obs.activity == app.state.prev_sent.activity
                    same_objects = obs.objects_detected == app.state.prev_sent.objects_detected
                    print(f"[Snowflake Filter] Duplicate check: pose={same_pose}, activity={same_activity}, objects={same_objects}")
            return ProcessFrameResponse(
                ok=True,
                filtered=True,
                observation=obs_json,
                alert=None,
            )

        prev = app.state.prev_sent
        alert = app.state.alert_engine.check(obs)
        confirmed_fall = _is_confirmed_fall(obs, alert)

        thumb_b64: Optional[str] = None
        if _should_persist_thumbnail(obs, alert, confirmed_fall=confirmed_fall):
            thumb_b64 = _encode_frame_thumbnail_bgr(frame)
        obs_to_store = (
            obs.model_copy(update={"frame_thumb_base64": thumb_b64})
            if thumb_b64
            else obs
        )

        records: List[Dict[str, Any]] = collect_transition_events(prev, obs)
        if confirmed_fall:
            records.append(
                {
                    "dedupe_key": DEDUPE_FALLEN,
                    "event_type": "fallen",
                    "headline": alert.quick_message or "Possible fall detected",
                }
            )

        if confirmed_fall:
            app.state.fall_attention_latched = True
        if obs.pose in (PoseType.STANDING, PoseType.WALKING, PoseType.SITTING):
            app.state.fall_attention_latched = False

        min_fall_conf = _fall_min_pose_confidence()
        fallen_attention = (
            app.state.fall_attention_latched
            and obs.pose == PoseType.LYING
            and obs.pose_confidence >= min_fall_conf
        )

        buf: Deque[dict[str, Any]] = app.state.live_event_buffer
        obs_iso = _observed_at_iso(obs)
        for rec in records:
            want_thumb = thumb_b64 and rec["dedupe_key"] in _LIVE_EVENT_THUMB_KEYS
            buf.append(
                {
                    "id": str(uuid.uuid4()),
                    "dedupe_key": rec["dedupe_key"],
                    "event_type": rec["event_type"],
                    "headline": rec["headline"],
                    "observed_at": obs_iso,
                    "display_name": obs.primary_display_name,
                    "frame_thumb_base64": thumb_b64 if want_thumb else None,
                    "summary": None,
                    "meal_kind": None,
                }
            )

        pose_val = obs.pose.value if hasattr(obs.pose, "value") else str(obs.pose)
        act_val = obs.activity.value if hasattr(obs.activity, "value") else str(obs.activity)
        app.state.last_primary_snapshot = {
            "pose": pose_val,
            "display_name": obs.primary_display_name,
            "observed_at": obs_iso,
            "session_id": obs.session_id,
            "activity": act_val,
            "fallen_attention": fallen_attention,
        }

        app.state.prev_sent = obs
        app.state.snowflake.add_observation(obs_to_store)
        await app.state.ws_manager.broadcast_observation(obs)

        alert_json: Optional[dict[str, Any]] = None
        if alert is not None:
            if alert.alert_type == "fall_detected":
                if confirmed_fall:
                    app.state.snowflake.add_alert(alert)
                    app.state.ws_manager.register_alert(alert)
                    await app.state.ws_manager.broadcast_alert(alert)
                    alert_json = alert.model_dump(mode="json")
            else:
                app.state.ws_manager.register_alert(alert)
                await app.state.ws_manager.broadcast_alert(alert)
                alert_json = alert.model_dump(mode="json")

        app.state.snowflake.flush()

        return ProcessFrameResponse(
            ok=True,
            filtered=False,
            observation=obs_json,
            alert=alert_json,
        )

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        manager: WebSocketManager = app.state.ws_manager
        await manager.connect(websocket)
        try:
            while True:
                data = await websocket.receive_json()
                ok = manager.process_client_message(data)
                await websocket.send_json(
                    {
                        "type": "ack_result",
                        "ok": ok,
                        "alert_id": data.get("alert_id") if isinstance(data, dict) else None,
                    }
                )
        except WebSocketDisconnect:
            manager.disconnect(websocket)

    def _get_reid_embedder() -> ReIDEmbedder:
        """Lazy-load ReIDEmbedder on first enrollment request."""
        if app.state.reid_embedder is None:
            app.state.reid_embedder = ReIDEmbedder()
        return app.state.reid_embedder

    def _extract_embedding_from_image(image_bytes: bytes) -> tuple[np.ndarray, Optional[list[float]]]:
        """
        Extract person embedding from uploaded image.
        
        Detects person using YOLO, crops to the largest person bounding box,
        then extracts the ReID embedding from the crop.
        
        Returns:
            Tuple of (embedding, bbox) where bbox is [x1, y1, x2, y2] normalized or None
        """
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            raise HTTPException(status_code=400, detail="Invalid or empty image")

        h, w = frame.shape[:2]
        
        # Detect persons using YOLO
        pipeline: CVPipeline = app.state.pipeline
        results = pipeline.yolo_model.predict(source=frame, verbose=False)
        
        best_person_crop = None
        best_person_bbox = None
        best_area = 0
        
        if results and results[0].boxes is not None:
            boxes = results[0].boxes
            for i, cls in enumerate(boxes.cls.tolist()):
                if int(cls) == 0:  # person class
                    xyxy = boxes.xyxy[i].tolist()
                    x1, y1, x2, y2 = map(int, xyxy)
                    area = (x2 - x1) * (y2 - y1)
                    
                    if area > best_area:
                        best_area = area
                        # Add padding around the crop
                        pad_x = int((x2 - x1) * 0.05)
                        pad_y = int((y2 - y1) * 0.05)
                        crop_x1 = max(0, x1 - pad_x)
                        crop_y1 = max(0, y1 - pad_y)
                        crop_x2 = min(w, x2 + pad_x)
                        crop_y2 = min(h, y2 + pad_y)
                        best_person_crop = frame[crop_y1:crop_y2, crop_x1:crop_x2].copy()
                        best_person_bbox = [x1 / w, y1 / h, x2 / w, y2 / h]
        
        if best_person_crop is None:
            raise HTTPException(
                status_code=400, 
                detail="No person detected in image. Please ensure a person is clearly visible."
            )
        
        embedder = _get_reid_embedder()
        embedding = embedder.extract_embedding(best_person_crop)
        return embedding, best_person_bbox

    @app.post("/enroll-subject", response_model=EnrollResponse)
    async def enroll_subject(
        file: UploadFile = File(...),
        subject_id: str = Form(...),
        display_name: str = Form(...),
        color: Optional[str] = Form(None),
    ) -> EnrollResponse:
        """
        Enroll a new subject or add embedding to existing subject.
        
        The uploaded image should contain a clearly visible person.
        For best results, use a full-body or upper-body photo with good lighting.
        """
        if not subject_id or not subject_id.strip():
            raise HTTPException(status_code=400, detail="subject_id is required")
        if not display_name or not display_name.strip():
            raise HTTPException(status_code=400, detail="display_name is required")

        subject_id = subject_id.strip().lower()
        display_name = display_name.strip()

        raw = await file.read()
        if not raw:
            raise HTTPException(status_code=400, detail="Empty file uploaded")

        try:
            embedding, bbox = _extract_embedding_from_image(raw)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to extract embedding: {str(e)}"
            )

        store: IdentityStore = app.state.identity_store
        subject = store.enroll(
            subject_id=subject_id,
            display_name=display_name,
            embedding=embedding,
            color=color,
        )

        bbox_str = ""
        if bbox:
            bbox_str = f" (bbox: [{bbox[0]:.2f}, {bbox[1]:.2f}, {bbox[2]:.2f}, {bbox[3]:.2f}])"

        return EnrollResponse(
            success=True,
            subject_id=subject.subject_id,
            embedding_count=len(subject.embeddings),
            message=f"Subject '{display_name}' enrolled successfully{bbox_str}",
        )

    @app.get("/subjects", response_model=SubjectListResponse)
    async def list_subjects() -> SubjectListResponse:
        """List all enrolled subjects (without embeddings)."""
        store: IdentityStore = app.state.identity_store
        subjects_data = store.list_subjects(include_embeddings=False)
        
        subjects = [
            SubjectInfo(
                subject_id=s["subject_id"],
                display_name=s["display_name"],
                color=s["color"],
                embedding_count=s["embedding_count"],
                enrolled_at=s["enrolled_at"],
            )
            for s in subjects_data
        ]
        
        return SubjectListResponse(subjects=subjects)

    @app.delete("/subjects/{subject_id}")
    async def delete_subject(subject_id: str) -> dict[str, Any]:
        """Remove an enrolled subject."""
        store: IdentityStore = app.state.identity_store
        
        if store.delete(subject_id):
            return {
                "success": True,
                "message": f"Subject '{subject_id}' deleted successfully",
            }
        else:
            raise HTTPException(
                status_code=404,
                detail=f"Subject '{subject_id}' not found",
            )

    @app.post("/subjects/{subject_id}/add-view", response_model=EnrollResponse)
    async def add_subject_view(
        subject_id: str,
        file: UploadFile = File(...),
    ) -> EnrollResponse:
        """
        Add additional embedding view to improve matching accuracy.
        
        Up to 5 embeddings are stored per subject. Adding more will
        replace the oldest embedding.
        """
        store: IdentityStore = app.state.identity_store
        subject = store.get(subject_id)
        
        if subject is None:
            raise HTTPException(
                status_code=404,
                detail=f"Subject '{subject_id}' not found",
            )

        raw = await file.read()
        if not raw:
            raise HTTPException(status_code=400, detail="Empty file uploaded")

        try:
            embedding, bbox = _extract_embedding_from_image(raw)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to extract embedding: {str(e)}"
            )

        store.add_embedding(subject_id, embedding)
        updated_subject = store.get(subject_id)

        return EnrollResponse(
            success=True,
            subject_id=subject_id,
            embedding_count=len(updated_subject.embeddings) if updated_subject else 0,
            message=f"Added new view for subject '{subject_id}'",
        )

    @app.get("/subjects/{subject_id}")
    async def get_subject(subject_id: str) -> dict[str, Any]:
        """Get details for a specific enrolled subject."""
        store: IdentityStore = app.state.identity_store
        subject = store.get(subject_id)
        
        if subject is None:
            raise HTTPException(
                status_code=404,
                detail=f"Subject '{subject_id}' not found",
            )

        return {
            "subject_id": subject.subject_id,
            "display_name": subject.display_name,
            "color": subject.color,
            "embedding_count": len(subject.embeddings),
            "enrolled_at": subject.enrolled_at.isoformat(),
        }

    return app


app = create_app()
