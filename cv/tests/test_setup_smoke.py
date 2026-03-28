"""
Fast checks that the environment can import and construct the Phase 3 stack
without starting uvicorn. Run: `cd cv && python -m pytest tests/test_setup_smoke.py -q`
before `uvicorn cv.main:app` from the repo root.
"""

from __future__ import annotations


def test_imports_cv_main_and_websocket_manager() -> None:
    import cv.main  # noqa: F401
    import cv.websocket_manager  # noqa: F401


def test_create_app_factory_does_not_require_yolo_at_import() -> None:
    from cv.main import create_app

    app = create_app(pipeline_factory=lambda: _MinimalPipeline())
    assert app is not None
    # Startup would still load real pipeline if using default factory; this only checks the factory hook.
    assert "/health" in [r.path for r in app.routes]


def test_fastapi_and_pydantic_available() -> None:
    import fastapi  # noqa: F401
    import pydantic  # noqa: F401


class _MinimalPipeline:
    def close(self) -> None:
        pass
