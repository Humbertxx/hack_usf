#!/usr/bin/env bash
# One-shot Mac orchestration: start CV on RunPod (if needed), then capture.
#
# RunPod ssh.runpod.io does NOT support ssh -L. Set RUNPOD_PUBLIC_URL to reach the API:
#   HTTP service: https://<id>-<internal-port>.proxy.runpod.net
#   TCP expose:   http://<public-ip>:<mapped-port>  (FastAPI is still HTTP over that TCP socket)
#
# From repo root:
#   ./capture/run_full_stack.sh
# Forward args to capture.capture after -- :
#   ./capture/run_full_stack.sh -- --dry-run
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Source repo root .env first (Snowflake credentials, etc.)
if [[ -f "${REPO_ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${REPO_ROOT}/.env"
  set +a
fi

# Then source runpod.env (can override or add RunPod-specific vars)
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
# Prefer RUNPOD_PUBLIC_URL; RUNPOD_HTTP_URL kept as an alias for older runpod.env files.
RUNPOD_PUBLIC_URL="${RUNPOD_PUBLIC_URL:-${RUNPOD_HTTP_URL:-}}"
RUNPOD_PUBLIC_URL="${RUNPOD_PUBLIC_URL%/}"

CAPTURE_ARGS=()
if [[ "${1:-}" == -- ]]; then
  shift
  CAPTURE_ARGS=("$@")
fi

if [[ -z "${RUNPOD_IP:-}" || -z "${RUNPOD_PORT:-}" ]]; then
  echo "error: set RUNPOD_IP and RUNPOD_PORT in ${SCRIPT_DIR}/runpod.env." >&2
  exit 1
fi

command -v curl >/dev/null 2>&1 || { echo "error: curl required for health checks." >&2; exit 1; }
command -v "$PYTHON_BIN" >/dev/null 2>&1 || {
  echo "error: Python not found (${PYTHON_BIN}). Set PYTHON=... or install Python." >&2
  exit 1
}

if [[ -z "$RUNPOD_PUBLIC_URL" ]] && [[ "${RUNPOD_IP}" == "ssh.runpod.io" ]]; then
  echo "error: ssh.runpod.io cannot be used for SSH port forwarding (-L)." >&2
  echo "  Expose internal port ${REMOTE_PORT} on the pod, then set RUNPOD_PUBLIC_URL in capture/runpod.env:" >&2
  echo "    HTTP service: https://<id>-${REMOTE_PORT}.proxy.runpod.net" >&2
  echo "    TCP expose:    http://<public-ip>:<mapped-port>  (from RunPod Connect)" >&2
  exit 1
fi

# Non-TTY SSH avoids: "Your SSH client doesn't support PTY" on RunPod's gateway.
ssh_opts=( -T -o RequestTTY=no -p "$RUNPOD_PORT" )
if [[ -n "${RUNPOD_SSH_IDENTITY:-}" ]]; then
  ssh_opts+=(-i "$RUNPOD_SSH_IDENTITY")
fi

AUTOSSH_PID=""

cleanup() {
  if [[ -n "${AUTOSSH_PID:-}" ]] && kill -0 "$AUTOSSH_PID" 2>/dev/null; then
    kill "$AUTOSSH_PID" 2>/dev/null || true
    wait "$AUTOSSH_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

echo "[run_full_stack] Ensuring uvicorn on pod at ${RUNPOD_REMOTE_REPO} (port ${REMOTE_PORT})..."
# ${REMOTE_PORT} expands on the Mac before ssh runs; \$(seq ...) runs on the pod.
if ! ssh "${ssh_opts[@]}" "${RUNPOD_SSH_USER}@${RUNPOD_IP}" bash -s <<EOF
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
then
  echo "" >&2
  echo "hint: On the pod, install CV deps once (from repo root), then re-run this script:" >&2
  echo "  cd $(printf '%q' "$RUNPOD_REMOTE_REPO") && python3 -m pip install -r cv/requirements.txt" >&2
  echo "  (Install CUDA torch first if needed — see comments at top of cv/requirements.txt.)" >&2
  echo "If you use a venv, set RUNPOD_REMOTE_PYTHON in capture/runpod.env to that python." >&2
  exit 1
fi

if [[ -n "$RUNPOD_PUBLIC_URL" ]]; then
  echo "[run_full_stack] Checking public URL (no SSH tunnel): ${RUNPOD_PUBLIC_URL}/health"
  tunnel_ok=0
  for ((i = 1; i <= HEALTH_WAIT_SEC; i++)); do
    if curl -sf "${RUNPOD_PUBLIC_URL}/health" >/dev/null; then
      echo "[run_full_stack] Public health OK."
      tunnel_ok=1
      break
    fi
    sleep 1
  done
  if [[ "$tunnel_ok" -ne 1 ]]; then
    echo "error: ${RUNPOD_PUBLIC_URL}/health did not respond within ${HEALTH_WAIT_SEC}s." >&2
    echo "  Expose internal port ${REMOTE_PORT} (HTTP or TCP) and check RUNPOD_PUBLIC_URL." >&2
    exit 1
  fi
  export CAPTURE_SERVER_URL="${RUNPOD_PUBLIC_URL}/process-frame"
else
  command -v autossh >/dev/null 2>&1 || {
    echo "error: install autossh for SSH tunnel (brew install autossh)." >&2
    exit 1
  }
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
  export CAPTURE_SERVER_URL="http://127.0.0.1:${LOCAL_PORT}/process-frame"
fi

echo "[run_full_stack] Starting capture client (POST to ${CAPTURE_SERVER_URL})..."
cd "$REPO_ROOT"
"$PYTHON_BIN" -m capture.capture ${CAPTURE_ARGS[@]+"${CAPTURE_ARGS[@]}"}
