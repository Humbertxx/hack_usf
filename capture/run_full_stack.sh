#!/usr/bin/env bash
# One-shot Mac orchestration: start CV on RunPod (if needed), then capture.
#
# RunPod ssh.runpod.io does NOT support ssh -L tunnels. Use RUNPOD_HTTP_URL (HTTP proxy
# from the RunPod dashboard) so the Mac posts frames to https://...proxy.runpod.net.
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
RUNPOD_HTTP_URL="${RUNPOD_HTTP_URL:-}"
RUNPOD_HTTP_URL="${RUNPOD_HTTP_URL%/}"

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
command -v "$PYTHON_BIN" >/dev/null 2>&1 || {
  echo "error: Python not found (${PYTHON_BIN}). Set PYTHON=... or install Python." >&2
  exit 1
}

if [[ -z "$RUNPOD_HTTP_URL" ]] && [[ "${RUNPOD_IP}" == "ssh.runpod.io" ]]; then
  echo "error: ssh.runpod.io cannot be used for SSH port forwarding (-L)." >&2
  echo "  In RunPod: expose port ${REMOTE_PORT} (HTTP), copy the proxy base URL, then add to capture/runpod.env:" >&2
  echo "    RUNPOD_HTTP_URL=https://<id>-<port>.proxy.runpod.net" >&2
  echo "  (No autossh tunnel needed.)" >&2
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
ssh "${ssh_opts[@]}" "${RUNPOD_SSH_USER}@${RUNPOD_IP}" bash -s <<EOF
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

if [[ -n "$RUNPOD_HTTP_URL" ]]; then
  echo "[run_full_stack] Checking public URL (no SSH tunnel): ${RUNPOD_HTTP_URL}/health"
  tunnel_ok=0
  for ((i = 1; i <= HEALTH_WAIT_SEC; i++)); do
    if curl -sf "${RUNPOD_HTTP_URL}/health" >/dev/null; then
      echo "[run_full_stack] Public health OK."
      tunnel_ok=1
      break
    fi
    sleep 1
  done
  if [[ "$tunnel_ok" -ne 1 ]]; then
    echo "error: ${RUNPOD_HTTP_URL}/health did not respond within ${HEALTH_WAIT_SEC}s." >&2
    echo "  Expose port ${REMOTE_PORT} as HTTP on the pod and check RUNPOD_HTTP_URL." >&2
    exit 1
  fi
  export CAPTURE_SERVER_URL="${RUNPOD_HTTP_URL}/process-frame"
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
"$PYTHON_BIN" -m capture.capture "${CAPTURE_ARGS[@]}"
