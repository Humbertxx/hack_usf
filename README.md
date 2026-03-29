# hack_usf

Hackathon project for 2026 Hack USF.

## What lives where

| Area | Role |
|------|------|
| **`frontend/`** | Next.js 16 app. Dev server on port **3000**. The enrollment UI talks to the CV API via Next **Route Handlers** (for example `app/api/enroll/route.ts` forwards `POST` to the CV server so the browser avoids CORS issues). Those handlers default to **`http://localhost:8080`**. |
| **`backend/`** | FastAPI-oriented modules (API shapes, models, Snowflake client, WebSocket helpers). The repository now has a root **`app.py`** that mounts backend routes and websockets, with optional CV mounting under **`/cv`** if CV dependencies import successfully. |
| **`cv/`** | Computer vision pipeline and **FastAPI** app (`cv.main:app`): `/health`, `/enroll-subject`, `/subjects`, WebSocket `/ws`, etc. Dependencies in `cv/requirements.txt`; tests and GPU scripts under `cv/`. |

Other top-level folders (not exhaustive): **`capture/`** — Pi capture and RunPod/SSH helpers; **`shared/`** — types for frontend/backend; **`infra/`**, **`data/`**, **`scripts/`** — deployment and dev utilities.

CV tests expect imports from the repo root (`pythonpath` = repo root):

```bash
pip install -r cv/requirements-dev.txt
cd cv && python -m pytest
```

---

## Run the unified FastAPI app

From the **repository root**:

```bash
cd /path/to/hack_usf

python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install --upgrade pip
pip install -r backend/requirements.txt

uvicorn app:app --host 0.0.0.0 --port 8000
```

Useful endpoints:

- `GET /health`
- `GET /api/observations`
- `GET /api/alerts`
- `GET /api/live-events`
- `WS /ws/live`
- `GET /cv/health` if the CV app mounted successfully

---

## Run the frontend (local)

From `frontend/`:

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). Enrollment and related flows expect a CV server (or tunnel) on **port 8080** on your Mac, because the Next API route proxies to `http://localhost:8080`.

---

## Demo insights stack (dev-only Snowflake)

Use the demo launcher when you want `/demo`, Timeline, Insights trends, and Insights chat to read from the unified FastAPI app (`:8000`) with a dev Snowflake database:

```bash
./scripts/run_frontend_snowflake_demo.sh
```

Operational checklist:

- The script forces `SNOWFLAKE_DATABASE=GRANDMA_MONITOR_DEV` for the backend process and refuses an explicitly exported `SNOWFLAKE_DATABASE=GRANDMA_MONITOR` in your shell.
- Keep your default root `.env` behavior unchanged for non-demo workflows; use this script or a separate shell session for demo runs instead of permanently rewriting `.env`.
- Insights chat uses `SNOWFLAKE.CORTEX.COMPLETE` through FastAPI (`POST /api/insights-chat`); set `SNOWFLAKE_CORTEX_MODEL` only if you need a model override (default: `mistral-large`).
- New demo-specific routes (`/api/insights-trends`, `/api/timeline`, `/api/insights-chat`) are guard-railed to dev DB names (`GRANDMA_MONITOR_DEV` or `_DEV`) unless emergency override `ALLOW_NON_DEV_SNOWFLAKE_FOR_INSIGHTS` is explicitly set.

---

## Run the CV server (Python venv)

From the **repository root** (so `cv` imports work as a package):

```bash
cd /path/to/hack_usf

python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install --upgrade pip
pip install -r cv/requirements.txt
# torchreid often needs a separate install (see comments at bottom of cv/requirements.txt), e.g.:
# pip install --no-build-isolation git+https://github.com/KaiyangZhou/deep-person-reid.git
```

Optional: copy or symlink **`.env`** at the repo root if you use Snowflake from the CV app (credentials are documented in `my-docs/DB_SNOWFLAKE_CONFIG.md`).

Start the API (same shell, venv activated, cwd = repo root):

```bash
uvicorn cv.main:app --host 0.0.0.0 --port 8080
```

Check [http://127.0.0.1:8080/health](http://127.0.0.1:8080/health). On a **GPU pod** (e.g. RunPod), install the CUDA PyTorch stack first — see comments in `cv/requirements.txt` and the RunPod section below.

---

## SSH tunnel from MacBook → CV server (remote testing)

When the FastAPI app runs on a **remote** machine (GPU pod) and listens on **8080** (often only on `127.0.0.1` there), forward remote **8080** to your Mac’s **8080** so the Next.js app and `app/api/enroll/route.ts` keep using `http://localhost:8080`.

### 1. Configure RunPod / SSH

Copy `capture/runpod.env.example` to `capture/runpod.env` and set at least:

- **`RUNPOD_IP`** — host that supports **local port forwarding** (`ssh -L`). **Not** `ssh.runpod.io` for `-L` (that gateway does not support it).
- **`RUNPOD_PORT`** — SSH port.
- Optional: **`RUNPOD_SSH_USER`**, **`RUNPOD_SSH_IDENTITY`**, **`LOCAL_PORT`** / **`REMOTE_PORT`** (defaults **8080**).

If you only have RunPod’s HTTP proxy URL, use that URL from clients instead of a tunnel, or use a pod with direct SSH — see comments in `capture/autossh_setup.sh` and `capture/run_full_stack.sh`.

### 2. Persistent tunnel with autossh (recommended)

```bash
brew install autossh
cd /path/to/hack_usf
./capture/autossh_setup.sh
```

That runs something equivalent to: local **8080** → remote **`127.0.0.1:8080`** (adjust with `LOCAL_PORT` / `REMOTE_PORT`). Leave the process running while you test.

### 3. One-shot SSH (no autossh)

Replace placeholders with values from `capture/runpod.env`:

```bash
ssh -N -L 8080:127.0.0.1:8080 -p RUNPOD_PORT RUNPOD_SSH_USER@RUNPOD_IP
```

### 4. End-to-end dev loop

1. On the remote host (or locally): `uvicorn cv.main:app --host 0.0.0.0 --port 8080` (or bind to `127.0.0.1` if you only ever reach it via tunnel).
2. On the Mac: tunnel as above so **localhost:8080** hits the remote API.
3. On the Mac: `cd frontend && npm run dev` → use the web app; enrollment hits Next, which proxies to **localhost:8080**.

---

## RunPod (CUDA 12.8, PyTorch ≥ 2.8), from repository root

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
   - If **`NVIDIA_VISIBLE_DEVICES=void`**, CUDA is intentionally disabled for the container stack (`cuInit` fails, PyTorch sees no GPU). Run **`export NVIDIA_VISIBLE_DEVICES=all`** or **`unset NVIDIA_VISIBLE_DEVICES`** and try again; find what reset it (`grep -r void ~/.bashrc /etc/profile /workspace 2>/dev/null`).
   - Run `echo "$CUDA_VISIBLE_DEVICES"`. If it is empty, run `unset CUDA_VISIBLE_DEVICES` (an empty value can break enumeration).
   - Stop the pod and start it again; re-open a terminal and re-run the script in the same venv.
3. **Driver / runtime mismatch** — Very new PyTorch (cu128) needs a host driver that supports that CUDA generation. If everything else looks fine, try another RunPod PyTorch or CUDA base image, or ask support whether the node’s driver matches CUDA 12.8.

4. **`nvidia-smi` works but `/dev/nvidia0` is missing** — Some pods only expose `/dev/nvidiaN` (e.g. `nvidia7`). If you can write under `/dev`, try `ln -sf /dev/nvidia7 /dev/nvidia0` (or `bash cv/scripts/ensure_nvidia0_alias.sh`). **`mknod` is often blocked** on managed pods; a symlink may still work.

5. **Symlink `/dev/nvidia0` exists but PyTorch still says CUDA unavailable** — The problem is not only the device name. Run `python3 cv/scripts/diagnose_cuda_driver.py` (it maps which `libcuda` is loaded and **re-tries once with `LD_LIBRARY_PATH` unset** if `cuInit` returns 999).

6. **`LD_LIBRARY_PATH` includes `/usr/local/cuda`** — The linker may load the toolkit’s **stub** `libcuda` before the real driver in `/lib`; then **`cuInit` → CUDA_ERROR_UNKNOWN** and PyTorch shows the same. Run `unset LD_LIBRARY_PATH` (or drop the cuda entries) in the shell before Python, and fix any profile that exports it for interactive logins.

---

## Layout (quick reference)

| Directory | Role |
|-----------|------|
| **`backend/`** | API modules, models, services (non-CV); no standalone server entry in-repo. |
| **`cv/`** | Computer vision: models, pipeline, **FastAPI** `cv.main`, requirements, tests, RunPod GPU check script. |
| **`frontend/`** | Web client (Next.js). |
| **`infra/`** | Docker, deployment, server setup. |
| **`capture/`** | Raspberry Pi capture script; RunPod/SSH helpers (`autossh_setup.sh`, `run_full_stack.sh`). |
| **`shared/`** | Types/schemas used by backend + frontend (observations, alerts). |
| **`data/`** | SQLite/db artifacts (if kept in repo for dev). |
| **`scripts/`** | Setup/dev helpers. |

More detail on enrollment HTTP contracts: `my-docs/FRONTEND_CV_ENROLLMENT_API.md`.
