"""Pytest: keep tests on lightweight models unless overridden."""

from __future__ import annotations

import os

os.environ.setdefault("CV_YOLO_MODEL", "yolov8n.pt")
os.environ.setdefault("CV_YOLO_IMGSZ", "640")
os.environ.setdefault("CV_REID_MODEL", "osnet_x0_25")
