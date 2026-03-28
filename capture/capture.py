from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, Optional, Protocol

import cv2
import httpx
import numpy as np

# Defaults per WORKSTREAM_A_CV_SETUP.md Phase 4.1
RESOLUTION = (1280, 720)
CAPTURE_INTERVAL = 15  # seconds
JPEG_QUALITY = 85
SERVER_URL = "http://localhost:8080/process-frame"

_DEFAULT_MAX_QUEUE = 64
_DEFAULT_MAX_ATTEMPTS_PER_FRAME = 5
_DEFAULT_POST_TIMEOUT_SEC = 30.0


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class CaptureConfig:
    width: int
    height: int
    capture_interval_sec: float
    jpeg_quality: int
    server_url: str
    camera_index: int
    session_id: str
    in_concern_window: bool
    max_queue: int
    max_attempts_per_frame: int
    post_timeout_sec: float

    @classmethod
    def from_env(cls) -> CaptureConfig:
        w, h = RESOLUTION
        return cls(
            width=int(os.environ.get("CAPTURE_WIDTH", str(w))),
            height=int(os.environ.get("CAPTURE_HEIGHT", str(h))),
            capture_interval_sec=float(
                os.environ.get("CAPTURE_INTERVAL_SEC", str(CAPTURE_INTERVAL))
            ),
            jpeg_quality=int(os.environ.get("CAPTURE_JPEG_QUALITY", str(JPEG_QUALITY))),
            server_url=os.environ.get("CAPTURE_SERVER_URL", SERVER_URL).rstrip("/"),
            camera_index=int(os.environ.get("CAPTURE_CAMERA_INDEX", "0")),
            session_id=os.environ.get("CAPTURE_SESSION_ID", "default"),
            in_concern_window=_truthy_env("CAPTURE_IN_CONCERN_WINDOW"),
            max_queue=int(os.environ.get("CAPTURE_MAX_QUEUE", str(_DEFAULT_MAX_QUEUE))),
            max_attempts_per_frame=int(
                os.environ.get(
                    "CAPTURE_MAX_ATTEMPTS", str(_DEFAULT_MAX_ATTEMPTS_PER_FRAME)
                )
            ),
            post_timeout_sec=float(
                os.environ.get(
                    "CAPTURE_POST_TIMEOUT_SEC", str(_DEFAULT_POST_TIMEOUT_SEC)
                )
            ),
        )


def frame_to_jpeg(frame: np.ndarray, jpeg_quality: int) -> Optional[bytes]:
    """Encode BGR uint8 frame to JPEG bytes; returns None on OpenCV encode failure."""
    if frame is None or frame.size == 0:
        return None
    q = int(jpeg_quality)
    q = max(1, min(100, q))
    ok, buf = cv2.imencode(
        ".jpg", frame, (int(cv2.IMWRITE_JPEG_QUALITY), q)
    )
    if not ok:
        return None
    return buf.tobytes()


def resize_to_resolution(frame: np.ndarray, width: int, height: int) -> np.ndarray:
    """Resize frame to target WxH (matches 720p deliverable)."""
    if frame.shape[1] == width and frame.shape[0] == height:
        return frame
    return cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)


def _print_cv_result(response: dict) -> None:
    """Print CV detection results in a readable format."""
    filtered = response.get("filtered", False)
    obs = response.get("observation", {})
    alert = response.get("alert")
    
    if filtered:
        print("  [filtered - no significant change]")
        return
    
    pose = obs.get("pose", "unknown")
    confidence = obs.get("confidence", 0)
    detections = obs.get("detections", [])
    
    print(f"  Pose: {pose} (confidence: {confidence:.2f})")
    
    if detections:
        print(f"  Detections ({len(detections)}):")
        for det in detections[:5]:  # Show first 5
            label = det.get("label", "?")
            conf = det.get("confidence", 0)
            print(f"    - {label}: {conf:.2f}")
        if len(detections) > 5:
            print(f"    ... and {len(detections) - 5} more")
    else:
        print("  No detections")
    
    if alert:
        alert_type = alert.get("alert_type", "unknown")
        message = alert.get("quick_message", "")
        print(f"  ⚠️  ALERT: {alert_type} - {message}")


def post_frame(
    client: httpx.Client,
    *,
    server_url: str,
    jpeg_bytes: bytes,
    session_id: str,
    in_concern_window: bool,
    timeout_sec: float,
) -> Optional[dict]:
    """POST one JPEG to /process-frame; raises httpx.HTTPError on failure. Returns JSON response."""
    params = {
        "session_id": session_id,
        "in_concern_window": str(in_concern_window).lower(),
    }
    files = {"file": ("frame.jpg", jpeg_bytes, "image/jpeg")}
    response = client.post(server_url, params=params, files=files, timeout=timeout_sec)
    response.raise_for_status()
    try:
        return response.json()
    except Exception:
        return None


class _PostBytes(Protocol):
    def __call__(self, __jpeg: bytes) -> Optional[dict]: ...


def flush_queue(
    queue: Deque[bytes],
    *,
    post_bytes: _PostBytes,
    max_attempts_per_frame: int,
) -> Optional[dict]:
    """
    Drain queue by posting the front JPEG. On failure, keep it at the front and
    stop after max_attempts_per_frame so a later flush (or the next loop tick)
    can retry with backoff sleeps between attempts.
    
    Returns the last successful response dict, or None.
    """
    attempts = 0
    last_response: Optional[dict] = None
    while queue:
        jpeg = queue[0]
        try:
            last_response = post_bytes(jpeg)
            queue.popleft()
            attempts = 0
        except (httpx.HTTPError, OSError, ValueError):
            attempts += 1
            if attempts >= max_attempts_per_frame:
                return last_response
            time.sleep(min(30.0, 2 ** (attempts - 1)))
    return last_response


def run_capture(
    cfg: CaptureConfig,
    *,
    client: Optional[httpx.Client] = None,
    stop_flag: Optional[Callable[[], bool]] = None,
    preview: bool = False,
) -> None:
    """
    Open default camera, capture at cfg resolution every cfg.capture_interval_sec,
    enqueue JPEGs, and flush to the server with retries.
    
    If preview=True, shows a live camera feed in a window. Press 'q' to quit.
    """
    stop_flag = stop_flag or (lambda: False)
    own_client = client is None
    http = client or httpx.Client()

    def _post_bytes(jpeg_bytes: bytes) -> Optional[dict]:
        return post_frame(
            http,
            server_url=cfg.server_url,
            jpeg_bytes=jpeg_bytes,
            session_id=cfg.session_id,
            in_concern_window=cfg.in_concern_window,
            timeout_sec=cfg.post_timeout_sec,
        )

    cap = cv2.VideoCapture(cfg.camera_index)
    if not cap.isOpened():
        if own_client:
            http.close()
        raise RuntimeError(
            f"Cannot open camera index {cfg.camera_index}. "
            "On macOS grant Camera access to your terminal app."
        )

    pending: Deque[bytes] = deque(maxlen=cfg.max_queue)
    last_capture_time = 0.0
    window_name = "Capture Preview (press 'q' to quit)"
    
    if preview:
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(window_name, cfg.width, cfg.height)
        print(f"[capture] Preview window open. Posting every {cfg.capture_interval_sec}s. Press 'q' to quit.")
    
    try:
        while not stop_flag():
            ok, frame = cap.read()
            if not ok or frame is None:
                time.sleep(0.1)
                flush_queue(
                    pending,
                    post_bytes=_post_bytes,
                    max_attempts_per_frame=cfg.max_attempts_per_frame,
                )
                continue

            frame = resize_to_resolution(frame, cfg.width, cfg.height)
            
            if preview:
                cv2.imshow(window_name, frame)
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    print("[capture] 'q' pressed, exiting.")
                    break
            
            now = time.time()
            if now - last_capture_time >= cfg.capture_interval_sec:
                jpeg = frame_to_jpeg(frame, cfg.jpeg_quality)
                if jpeg is not None:
                    pending.append(jpeg)
                    response = flush_queue(
                        pending,
                        post_bytes=_post_bytes,
                        max_attempts_per_frame=cfg.max_attempts_per_frame,
                    )
                    if preview:
                        print(f"\n[capture] Frame sent ({len(jpeg)} bytes)")
                        if response:
                            _print_cv_result(response)
                    last_capture_time = now
            
            if not preview:
                time.sleep(max(0.0, cfg.capture_interval_sec))
            else:
                time.sleep(0.03)  # ~30fps preview
    finally:
        cap.release()
        if preview:
            cv2.destroyAllWindows()
        if own_client:
            http.close()


def main(argv: Optional[list[str]] = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(
        description="Capture camera frames and POST JPEGs to the CV server.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Verify config and camera open, then exit without posting.",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Show a live preview window of the camera feed.",
    )
    args = parser.parse_args(argv)

    cfg = CaptureConfig.from_env()
    stop = False

    def _handle_sigint(_sig: int, _frame: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _handle_sigint)
    signal.signal(signal.SIGTERM, _handle_sigint)

    if args.dry_run:
        cap = cv2.VideoCapture(cfg.camera_index)
        opened = cap.isOpened()
        cap.release()
        if not opened:
            print(
                f"Camera index {cfg.camera_index} not available.",
                file=sys.stderr,
            )
            return 2
        print(
            f"OK: camera {cfg.camera_index} opens; would POST to {cfg.server_url!r} "
            f"every {cfg.capture_interval_sec}s at {cfg.width}x{cfg.height} "
            f"(jpeg q={cfg.jpeg_quality})."
        )
        return 0

    try:
        run_capture(cfg, stop_flag=lambda: stop, preview=args.preview)
    except KeyboardInterrupt:
        return 130
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
