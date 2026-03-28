#!/usr/bin/env bash
# One-shot Mac orchestration: start CV server on RunPod (if needed), tunnel, then capture.
#
# Prerequisites on Mac: autossh, curl, Python + capture deps (see capture/requirements.txt).
# Prerequisites on RunPod: repo clone at RUNPOD_REMOTE_REPO, cv deps installed, curl.
#
# From repo root:
#   ./capture/run_full_stack.sh
# Forward args to capture.capture after -- :
#   ./capture/run_full_stack.sh -- --dry-run
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUNPOD_ENV_FILE="${RUNPOD_ENV_FILE:-${SCRIPT_DIR}/runpod.env}"
if [[ -f "$RUNPOD_ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$RUNPOD_ENV_FILE"
  set +a
fi

LOCAL_PORT="${LOCAL_PORT:-8080}"
REMOTE_PORT="${REMOTE_PORT:-8080}"
RUNPOD_SSH_USER="${RUNPOD_SSH_USER:-root}"
RUNPOD_REMOTE_REPO="${RUNPOD_REMOTE_REPO:-/workspace/hack_usf}"
RUNPOD_REMOTE_PYTHON="${RUNPOD_REMOTE_PYTHON:-python3}"
HEALTH_WAIT_SEC="${HEALTH_WAIT_SEC:-60}"
PYTHON_BIN="${PYTHON:-python3}"

CAPTURE_ARGS=()
if [[ "${1:-}" == -- ]]; then
  shift
  CAPTURE_ARGS=("$@")
fi

if [[ -z "${RUNPOD_IP:-}" || -z "${RUNPOD_PORT:-}" ]]; then
  echo "error: set RUNPOD_IP and RUNPOD_PORT (see ${SCRIPT_DIR}/runpod.env.example)." >&2
  exit 1
fi

command -v curl >/dev/null 2>&1 || { echo "error: curl required for health checks." >&2; exit 1; }
command -v autossh >/dev/null 2>&1 || { echo "error: install autossh (brew install autossh)." >&2; exit 1; }
command -v "$PYTHON_BIN" >/dev/null 2>&1 || {
  echo "error: Python not found (${PYTHON_BIN}). Set PYTHON=... or install Python." >&2
  exit 1
}

ssh_base=(-p "$RUNPOD_PORT")
if [[ -n "${RUNPOD_SSH_IDENTITY:-}" ]]; then
  ssh_base+=(-i "$RUNPOD_SSH_IDENTITY")
fi

AUTOSSH_PID=""

cleanup() {
  if [[ -n "$AUTOSSH_PID" ]] && kill -0 "$AUTOSSH_PID" 2>/dev/null; then
    kill "$AUTOSSH_PID" 2>/dev/null || true
    wait "$AUTOSSH_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

echo "[run_full_stack] Ensuring uvicorn on pod at ${RUNPOD_REMOTE_REPO} (port ${REMOTE_PORT})..."
# ${REMOTE_PORT} expands on the Mac before ssh runs; \$(seq ...) runs on the pod.
ssh "${ssh_base[@]}" "${RUNPOD_SSH_USER}@${RUNPOD_IP}" bash -s <<EOF
set -euo pipefail
cd $(printf '%q' "$RUNPOD_REMOTE_REPO")
if curl -sf "http://127.0.0.1:${REMOTE_PORT}/health" >/dev/null; then
  echo "[run_full_stack] server already healthy on pod"
  exit 0
fi
nohup $(printf '%q' "$RUNPOD_REMOTE_PYTHON") -m uvicorn cv.main:app --host 0.0.0.0 --port $(printf '%q' "$REMOTE_PORT") >>/tmp/hack_usf-uvicorn.log 2>&1 &
sleep 2
for i in \$(seq 1 30); do
  curl -sf "http://127.0.0.1:${REMOTE_PORT}/health" >/dev/null && exit 0
  sleep 1
done
echo "[run_full_stack] uvicorn did not become healthy on pod (see /tmp/hack_usf-uvicorn.log)" >&2
exit 1
EOF

echo "[run_full_stack] Starting SSH tunnel (Mac 127.0.0.1:${LOCAL_PORT} -> pod 127.0.0.1:${REMOTE_PORT})..."
"${SCRIPT_DIR}/autossh_setup.sh" &
AUTOSSH_PID=$!

echo "[run_full_stack] Waiting for http://127.0.0.1:${LOCAL_PORT}/health (up to ${HEALTH_WAIT_SEC}s)..."
tunnel_ok=0
for ((i = 1; i <= HEALTH_WAIT_SEC; i++)); do
  if curl -sf "http://127.0.0.1:${LOCAL_PORT}/health" >/dev/null; then
    echo "[run_full_stack] Tunnel OK."
    tunnel_ok=1
    break
  fi
  if ! kill -0 "$AUTOSSH_PID" 2>/dev/null; then
    echo "error: autossh exited early; check SSH and capture/runpod.env." >&2 
    exit 1
  fi
  sleep 1
done
if [[ "$tunnel_ok" -ne 1 ]]; then
  echo "error: tunnel health check timed out after ${HEALTH_WAIT_SEC}s." >&2
  exit 1
fi

echo "[run_full_stack] Starting capture client..."
cd "$REPO_ROOT"
"$PYTHON_BIN" -m capture.capture "${CAPTURE_ARGS[@]}"
