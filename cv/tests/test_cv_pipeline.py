import numpy as np
import pytest


@pytest.mark.integration
def test_cv_pipeline_processes_blank_frame(monkeypatch) -> None:
    # Pose backends may require a display/EGL (macOS CI, some headless nodes). YOLO still validates the stack.
    monkeypatch.setenv("CV_POSE_BACKEND", "none")
    from cv.cv_pipeline import CVPipeline

    pipe = CVPipeline(yolo_model_name="yolov8n.pt")
    try:
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        obs = pipe.process_frame(frame, session_id="test-session")
        assert obs.session_id == "test-session"
        assert obs.frame_quality >= 0.0
        assert isinstance(obs.objects_detected, list)
    finally:
        pipe.close()


def test_device_helper_cpu_when_no_cuda() -> None:
    import torch

    from cv.cv_pipeline import _device

    if torch.cuda.is_available():
        assert _device() == "cuda:0"
    else:
        assert _device() == "cpu"
