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
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r cv/requirements-cuda128.lockstep.txt
bash cv/scripts/verify_runpod_gpu.sh
```

### RunPod: `torch.cuda.is_available()` is False

The script prints `nvidia-smi`, device nodes, and a `libcuda` check before importing PyTorch. Use that order to narrow it down:

1. **No `/dev/nvidia*` or `nvidia-smi` fails** — The machine is not a working GPU pod (CPU template, wrong region, or runtime did not attach the GPU). Create or restart a pod that includes an NVIDIA GPU and uses a CUDA-capable image.
2. **`nvidia-smi` works but PyTorch still says CUDA unavailable** — Often environment or a stale session:
   - Run `echo "$CUDA_VISIBLE_DEVICES"`. If it is empty, run `unset CUDA_VISIBLE_DEVICES` (an empty value can break enumeration).
   - Stop the pod and start it again; re-open a terminal and re-run the script in the same venv.
3. **Driver / runtime mismatch** — Very new PyTorch (cu128) needs a host driver that supports that CUDA generation. If everything else looks fine, try another RunPod PyTorch or CUDA base image, or ask support whether the node’s driver matches CUDA 12.8.

4. **`nvidia-smi` works but `/dev/nvidia0` is missing** — Some pods only expose `/dev/nvidiaN` (e.g. `nvidia7`); PyTorch may then show `CUDA unknown error` even when `libcuda` loads. From repo root, as root: `bash cv/scripts/ensure_nvidia0_alias.sh`, then `bash cv/scripts/verify_runpod_gpu.sh` again. That node is recreated on pod restart; a cleaner long-term fix is a GPU template that injects the usual `/dev/nvidia0`.
hackaton project for 2026 HackUsf


infra --> for Docker, deployment, and server setup
pi -->  for the Raspberry Pi capture script
shared --> types/schemas used by backend + frontend (observations, alerts)
data --> for SQLite/db artifacts (if you keep them in repo for dev)
scripts --> setup/dev helpers (seed data, run all services)
