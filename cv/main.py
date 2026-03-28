from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Callable, Optional

import cv2
import numpy as np
from fastapi import (
    FastAPI,
    File,
    HTTPException,
    Query,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel

from cv.alert_engine import AlertEngine
from cv.cv_pipeline import CVPipeline
from cv.models import Alert, Observation
from cv.noise_filter import should_send
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


def create_app(
    *,
    pipeline_factory: Optional[Callable[[], CVPipeline]] = None,
    snowflake: Optional[MockSnowflakeClient] = None,
) -> FastAPI:
    pipeline_factory = pipeline_factory or (lambda: CVPipeline())

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

    return app


app = create_app()
