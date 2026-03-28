# hack_usf

Hackathon project for 2026 Hack USF.

## Layout

| Directory | Role |
|-----------|------|
| **`backend/`** | API and shared backend services (non-CV). |
| **`cv/`** | Computer vision: models, pipeline, FastAPI entry (future), requirements, tests, RunPod GPU check script. |
| **`frontend/`** | Web client. |

CV tests run from the `cv/` folder so imports resolve (`pythonpath` = repo root). Example:

```bash
pip install -r cv/requirements-dev.txt
cd cv && python -m pytest
```

RunPod (CUDA 12.8, PyTorch ≥ 2.8), from repository root:

```bash
pip install -r cv/requirements-cuda128.lockstep.txt
bash cv/scripts/verify_runpod_gpu.sh
```
