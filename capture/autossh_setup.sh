#!/usr/bin/env bash
# Phase 4.2: persistent SSH tunnel (auto-reconnect) to the CV FastAPI server on RunPod.
#
# Prerequisite: autossh and SSH key access to the pod.
#   brew install autossh
#
# Configure once (pick one):
#   1) Copy and edit: cp capture/runpod.env.example capture/runpod.env
#      Put RUNPOD_IP=... and RUNPOD_PORT=... in runpod.env (sourced automatically).
#   2) Export in your shell or ~/.zshrc:
#        export RUNPOD_IP="..." RUNPOD_PORT="..."
#   3) Point elsewhere: RUNPOD_ENV_FILE=/path/to/file ./capture/autossh_setup.sh
#
# Then from repo root: ./capture/autossh_setup.sh
#
# Optional overrides:
#   LOCAL_PORT (default 8080)  — port on your Mac
#   REMOTE_PORT (default 8080) — uvicorn port on the pod (127.0.0.1 on RunPod)
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNPOD_ENV_FILE="${RUNPOD_ENV_FILE:-${SCRIPT_DIR}/runpod.env}"
if [[ -f "$RUNPOD_ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$RUNPOD_ENV_FILE"
  set +a
fi

LOCAL_PORT="${LOCAL_PORT:-8080}"
REMOTE_PORT="${REMOTE_PORT:-8080}"

if [[ -z "${RUNPOD_IP:-}" || -z "${RUNPOD_PORT:-}" ]]; then
  echo "error: set RUNPOD_IP and RUNPOD_PORT (e.g. in ${SCRIPT_DIR}/runpod.env — see runpod.env.example)." >&2
  exit 1
fi

if ! command -v autossh >/dev/null 2>&1; then
  echo "error: autossh not found. Install with: brew install autossh" >&2
  exit 1
fi

# RunPod "ssh user@ssh.runpod.io" uses a gateway username, not root. Override when needed.
RUNPOD_SSH_USER="${RUNPOD_SSH_USER:-root}"

ssh_args=()
if [[ -n "${RUNPOD_SSH_IDENTITY:-}" ]]; then
  ssh_args+=(-i "$RUNPOD_SSH_IDENTITY")
fi
ssh_args+=(
  -L "${LOCAL_PORT}:127.0.0.1:${REMOTE_PORT}"
  -p "${RUNPOD_PORT}"
  -N
  "${RUNPOD_SSH_USER}@${RUNPOD_IP}"
)

exec autossh -M 0 \
  -o "ServerAliveInterval=30" \
  -o "ServerAliveCountMax=3" \
  -o "ExitOnForwardFailure=yes" \
  -- "${ssh_args[@]}"
