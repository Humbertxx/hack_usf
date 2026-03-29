"""
Setup and behavior tests for the capture client.
Run before live capture: `pip install -r capture/requirements-dev.txt`
then `python -m pytest capture/tests -q` from the repo root.
"""

from __future__ import annotations

from collections import deque
from unittest.mock import MagicMock, patch

import cv2
import httpx
import numpy as np
import pytest

from capture.capture import (
    CAPTURE_INTERVAL,
    JPEG_QUALITY,
    RESOLUTION,
    SERVER_URL,
    CaptureConfig,
    flush_queue,
    frame_to_jpeg,
    main,
    post_frame,
    resize_to_resolution,
)


def _clear_capture_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "CAPTURE_WIDTH",
        "CAPTURE_HEIGHT",
        "CAPTURE_INTERVAL_SEC",
        "CAPTURE_JPEG_QUALITY",
        "CAPTURE_SERVER_URL",
        "CAPTURE_CAMERA_INDEX",
        "CAPTURE_SESSION_ID",
        "CAPTURE_IN_CONCERN_WINDOW",
        "CAPTURE_MAX_QUEUE",
        "CAPTURE_MAX_ATTEMPTS",
        "CAPTURE_POST_TIMEOUT_SEC",
        "CAPTURE_WARMUP_SECONDS",
    ):
        monkeypatch.delenv(key, raising=False)


def test_config_defaults_match_workstream_phase4(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_capture_env(monkeypatch)
    cfg = CaptureConfig.from_env()
    assert (cfg.width, cfg.height) == RESOLUTION == (1920, 1080)
    assert cfg.capture_interval_sec == float(CAPTURE_INTERVAL)
    assert cfg.jpeg_quality == JPEG_QUALITY == 95
    assert cfg.server_url == SERVER_URL == "http://localhost:8080/process-frame"
    assert cfg.camera_index == 0
    assert cfg.session_id == "default"
    assert cfg.in_concern_window is False
    assert cfg.warmup_seconds == 1.5


def test_config_reads_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_capture_env(monkeypatch)
    monkeypatch.setenv("CAPTURE_WIDTH", "640")
    monkeypatch.setenv("CAPTURE_HEIGHT", "480")
    monkeypatch.setenv("CAPTURE_INTERVAL_SEC", "2.5")
    monkeypatch.setenv("CAPTURE_SERVER_URL", "http://example.com/process-frame/")
    monkeypatch.setenv("CAPTURE_SESSION_ID", "room-a")
    monkeypatch.setenv("CAPTURE_IN_CONCERN_WINDOW", "1")
    monkeypatch.setenv("CAPTURE_WARMUP_SECONDS", "2.25")
    cfg = CaptureConfig.from_env()
    assert cfg.width == 640 and cfg.height == 480
    assert cfg.capture_interval_sec == 2.5
    assert cfg.server_url == "http://example.com/process-frame"
    assert cfg.session_id == "room-a"
    assert cfg.in_concern_window is True
    assert cfg.warmup_seconds == 2.25


def test_import_dependencies_for_capture_client() -> None:
    import httpx as _httpx  # noqa: F401
    import numpy as _np  # noqa: F401

    import cv2 as _cv2  # noqa: F401

    for mod in (_httpx, _np, _cv2):
        assert mod is not None


def test_frame_to_jpeg_and_resize() -> None:
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frame[10:100, 20:200] = (0, 255, 0)
    out = resize_to_resolution(frame, 1280, 720)
    assert out.shape == (720, 1280, 3)
    jpeg = frame_to_jpeg(out, 85)
    assert jpeg is not None and jpeg.startswith(b"\xff\xd8")
    decoded = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded is not None and decoded.shape[0] == 720


def test_frame_to_jpeg_rejects_empty() -> None:
    assert frame_to_jpeg(np.array([]), 85) is None


@pytest.mark.parametrize(
    "content_type",
    ["application/json", "application/json; charset=utf-8"],
)
def test_post_frame_multipart_and_query(content_type: str) -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["method"] = request.method
        return httpx.Response(200, headers={"content-type": content_type}, json={"ok": True})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        post_frame(
            client,
            server_url="http://localhost:8080/process-frame",
            jpeg_bytes=b"\xff\xd9fake",
            session_id="s1",
            in_concern_window=True,
            timeout_sec=5.0,
        )

    url = str(seen["url"])
    assert "session_id=s1" in url
    assert "in_concern_window=true" in url
    assert seen["method"] == "POST"


def test_post_frame_raises_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="no")

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        with pytest.raises(httpx.HTTPStatusError):
            post_frame(
                client,
                server_url="http://localhost:8080/process-frame",
                jpeg_bytes=b"\xff\xd9",
                session_id="default",
                in_concern_window=False,
                timeout_sec=5.0,
            )


@patch("capture.capture.time.sleep", return_value=None)
def test_flush_queue_drains_on_success(_mock_sleep: MagicMock) -> None:
    q: deque[bytes] = deque([b"a", b"b"])
    posted: list[bytes] = []

    def post_bytes(data: bytes) -> None:
        posted.append(data)

    flush_queue(q, post_bytes=post_bytes, max_attempts_per_frame=3)
    assert posted == [b"a", b"b"]
    assert len(q) == 0


@patch("capture.capture.time.sleep", return_value=None)
def test_flush_queue_stops_after_max_attempts(_mock_sleep: MagicMock) -> None:
    q: deque[bytes] = deque([b"x"])
    calls = {"n": 0}

    def post_bytes(_data: bytes) -> None:
        calls["n"] += 1
        raise httpx.ConnectError("down", request=MagicMock())

    flush_queue(q, post_bytes=post_bytes, max_attempts_per_frame=3)
    assert calls["n"] == 3
    assert list(q) == [b"x"]


@patch("capture.capture.time.sleep", return_value=None)
def test_flush_queue_retries_then_drains(_mock_sleep: MagicMock) -> None:
    q: deque[bytes] = deque([b"one"])
    state = {"fails": 2}

    def post_bytes(data: bytes) -> None:
        if state["fails"] > 0:
            state["fails"] -= 1
            raise httpx.ConnectError("down", request=MagicMock())
        assert data == b"one"

    flush_queue(q, post_bytes=post_bytes, max_attempts_per_frame=5)
    assert len(q) == 0


def test_main_dry_run_exits_ok_when_camera_opens(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_capture_env(monkeypatch)
    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    with patch("capture.capture.cv2.VideoCapture", return_value=mock_cap):
        code = main(["--dry-run"])
    assert code == 0
    mock_cap.release.assert_called_once()


def test_main_dry_run_exits_error_when_camera_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_capture_env(monkeypatch)
    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = False
    with patch("capture.capture.cv2.VideoCapture", return_value=mock_cap):
        code = main(["--dry-run"])
    assert code == 2
