from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Callable, List, Optional

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
from pydantic import BaseModel

from cv.alert_engine import AlertEngine
from cv.cv_pipeline import CVPipeline
from cv.identity_store import IdentityStore
from cv.models import Alert, Observation
from cv.noise_filter import should_send
from cv.reid_embeddings import ReIDEmbedder
from cv.websocket_manager import WebSocketManager


class MockSnowflakeClient:
    def __init__(self) -> None:
        self.observations: list[Observation] = []
        self.alerts: list[Alert] = []

    def add_observation(self, obs: Observation) -> None:
        print(f"[MOCK SNOWFLAKE] Observation: {obs.id} - {obs.pose}")
        self.observations.append(obs)

    def add_alert(self, alert: Alert) -> None:
        print(f"[MOCK SNOWFLAKE] Alert: {alert.alert_type} - {alert.quick_message}")
        self.alerts.append(alert)

    def flush(self) -> None:
        print("[MOCK SNOWFLAKE] Flushed batch")


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


def create_app(
    *,
    pipeline_factory: Optional[Callable[[], CVPipeline]] = None,
    snowflake: Optional[MockSnowflakeClient] = None,
    identity_store: Optional[IdentityStore] = None,
) -> FastAPI:
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
    app.state.snowflake = snowflake or MockSnowflakeClient()
    app.state.prev_sent: Observation | None = None
    app.state.identity_store = store
    app.state.reid_embedder: Optional[ReIDEmbedder] = None

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

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

        if not should_send(
            obs,
            app.state.prev_sent,
            in_concern_window=in_concern_window,
        ):
            return ProcessFrameResponse(
                ok=True,
                filtered=True,
                observation=obs_json,
                alert=None,
            )

        app.state.prev_sent = obs
        app.state.snowflake.add_observation(obs)
        await app.state.ws_manager.broadcast_observation(obs)

        alert = app.state.alert_engine.check(obs)
        alert_json: Optional[dict[str, Any]] = None
        if alert is not None:
            app.state.snowflake.add_alert(alert)
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

    def _extract_embedding_from_image(image_bytes: bytes) -> np.ndarray:
        """Extract person embedding from uploaded image."""
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            raise HTTPException(status_code=400, detail="Invalid or empty image")

        embedder = _get_reid_embedder()
        embedding = embedder.extract_embedding(frame)
        return embedding

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
            embedding = _extract_embedding_from_image(raw)
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

        return EnrollResponse(
            success=True,
            subject_id=subject.subject_id,
            embedding_count=len(subject.embeddings),
            message=f"Subject '{display_name}' enrolled successfully",
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
            embedding = _extract_embedding_from_image(raw)
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
