from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from backend.api.alerts import router as alerts_router
from backend.api.insights_chat import router as insights_chat_router
from backend.api.insights_trends import router as insights_trends_router
from backend.api.live_events import router as live_events_router
from backend.api.observations import router as observations_router
from backend.api.primary_state import router as primary_state_router
from backend.api.timeline import router as timeline_router
from backend.ws.live import router as live_ws_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Hack USF Unified API",
        description="Repository-level FastAPI entrypoint for backend routes, websockets, and optional CV mounting.",
        version="0.1.0",
    )

    app.include_router(observations_router)
    app.include_router(alerts_router)
    app.include_router(live_events_router)
    app.include_router(primary_state_router)
    app.include_router(insights_trends_router)
    app.include_router(insights_chat_router)
    app.include_router(timeline_router)
    app.include_router(live_ws_router)

    cv_mount_error = _try_mount_cv_app(app)
    app.state.cv_mount_error = cv_mount_error

    @app.get("/")
    def root() -> dict[str, Any]:
        return {
            "service": "hack_usf",
            "docs": "/docs",
            "health": "/health",
            "backend_routes": [
                "/api/observations",
                "/api/alerts",
                "/api/live-events",
                "/api/primary-state",
                "/api/insights-trends",
                "/api/insights-chat",
                "/api/timeline",
                "/ws/live",
            ],
            "cv_mount_prefix": "/cv",
            "cv_mounted": cv_mount_error is None,
        }

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "backend": "mounted",
            "cv_mounted": app.state.cv_mount_error is None,
            "cv_mount_error": app.state.cv_mount_error,
        }

    return app


def _try_mount_cv_app(app: FastAPI) -> str | None:
    try:
        from cv.main import create_app as create_cv_app
    except Exception as exc:  # pragma: no cover - depends on optional CV deps
        return f"{type(exc).__name__}: {exc}"

    app.mount("/cv", create_cv_app())
    return None


app = create_app()
