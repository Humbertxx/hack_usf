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
CAPTURE_INTERVAL = 5  # seconds
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
    
    # Always show observation data
    pose = obs.get("pose", "unknown")
    pose_conf = obs.get("pose_confidence", 0)
    activity = obs.get("activity", "unknown")
    activity_conf = obs.get("activity_confidence", 0)
    person_detected = obs.get("person_detected", False)
    objects_detected = obs.get("objects_detected", [])
    frame_quality = obs.get("frame_quality", 0)
    detections = obs.get("detections", [])
    
    status = "[filtered]" if filtered else "[sent]"
    print(f"  {status} Person: {person_detected} | Quality: {frame_quality:.2f}")
    print(f"  Pose: {pose} ({pose_conf:.2f}) | Activity: {activity} ({activity_conf:.2f})")
    
    # Show identified persons
    for det in detections:
        if det.get("label") == "person":
            display_name = det.get("display_name")
            is_enrolled = det.get("is_enrolled", False)
            identity_conf = det.get("identity_confidence")
            person_id = det.get("person_id")
            
            if is_enrolled and display_name:
                conf_str = f" ({identity_conf:.0%})" if identity_conf else ""
                print(f"  Identity: {display_name}{conf_str}")
            elif person_id:
                print(f"  Identity: {person_id} (not enrolled)")
    
    if objects_detected:
        print(f"  Objects: {', '.join(objects_detected[:5])}", end="")
        if len(objects_detected) > 5:
            print(f" +{len(objects_detected) - 5} more", end="")
        print()
    
    if alert:
        alert_type = alert.get("alert_type", "unknown")
        message = alert.get("quick_message", "")
        print(f"  ALERT: {alert_type} - {message}")


# Color palette for different object classes (BGR)
_COLORS = [
    (0, 255, 0),    # green
    (255, 0, 0),    # blue
    (0, 0, 255),    # red
    (255, 255, 0),  # cyan
    (255, 0, 255),  # magenta
    (0, 255, 255),  # yellow
    (128, 255, 0),  # lime
    (255, 128, 0),  # sky blue
    (128, 0, 255),  # purple
    (0, 128, 255),  # orange
]


def _draw_detections(frame: np.ndarray, response: dict) -> np.ndarray:
    """Draw bounding boxes and labels on frame based on CV response."""
    if response is None:
        return frame
    
    obs = response.get("observation", {})
    detections = obs.get("detections", [])
    pose = obs.get("pose", "unknown")
    pose_conf = obs.get("pose_confidence", 0)
    activity = obs.get("activity", "unknown")
    
    h, w = frame.shape[:2]
    overlay = frame.copy()
    
    # Track unique labels for color assignment
    label_colors: dict = {}
    
    for det in detections:
        label = det.get("label", "?")
        conf = det.get("confidence", 0)
        bbox = det.get("bbox", [])
        display_name = det.get("display_name")
        is_enrolled = det.get("is_enrolled", False)
        bbox_color = det.get("bbox_color")
        identity_conf = det.get("identity_confidence")
        
        if len(bbox) != 4:
            continue
        
        # Use enrolled subject's color if available, otherwise assign by label
        if bbox_color and is_enrolled:
            # Parse hex color to BGR
            hex_color = bbox_color.lstrip('#')
            r, g, b = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
            color = (b, g, r)  # BGR format
        else:
            if label not in label_colors:
                label_colors[label] = _COLORS[len(label_colors) % len(_COLORS)]
            color = label_colors[label]
        
        # Convert normalized coords to pixel coords
        x1 = int(bbox[0] * w)
        y1 = int(bbox[1] * h)
        x2 = int(bbox[2] * w)
        y2 = int(bbox[3] * h)
        
        # Draw rectangle (thicker for enrolled subjects)
        thickness = 3 if is_enrolled else 2
        cv2.rectangle(overlay, (x1, y1), (x2, y2), color, thickness)
        
        # Build label text - show display_name for enrolled subjects
        if is_enrolled and display_name:
            if identity_conf:
                text = f"{display_name} ({identity_conf:.0%})"
            else:
                text = display_name
        else:
            text = f"{label} {conf:.0%}"
        
        (text_w, text_h), baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        cv2.rectangle(overlay, (x1, y1 - text_h - 10), (x1 + text_w + 4, y1), color, -1)
        
        # Draw label text
        cv2.putText(overlay, text, (x1 + 2, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
    
    # Draw pose/activity info at top
    info_text = f"Pose: {pose} ({pose_conf:.0%}) | Activity: {activity}"
    cv2.rectangle(overlay, (0, 0), (w, 35), (0, 0, 0), -1)
    cv2.putText(overlay, info_text, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    
    # Blend overlay with original (slight transparency for boxes)
    return cv2.addWeighted(overlay, 0.85, frame, 0.15, 0)


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
    last_response: Optional[dict] = None
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
                    if response:
                        last_response = response
                    if preview:
                        print(f"\n[capture] Frame sent ({len(jpeg)} bytes)")
                        if response:
                            _print_cv_result(response)
                    last_capture_time = now
            
            if preview:
                # Draw bounding boxes from last response
                display_frame = _draw_detections(frame, last_response)
                cv2.imshow(window_name, display_frame)
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    print("[capture] 'q' pressed, exiting.")
                    break
                time.sleep(0.03)  # ~30fps preview
            else:
                time.sleep(max(0.0, cfg.capture_interval_sec))
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
