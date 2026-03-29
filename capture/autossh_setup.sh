#!/usr/bin/env bash
# Phase 4.2: persistent SSH tunnel (auto-reconnect) to the CV FastAPI server on RunPod.
#
# Prerequisite: autossh and SSH access with TCP forwarding allowed.
#   brew install autossh
#
# IMPORTANT: RunPod's proxied host ssh.runpod.io does NOT support ssh -L forwarding.
# Use RunPod's public URL instead (configure RUNPOD_PUBLIC_URL in capture/runpod.env) or a pod
# with direct (public IP) SSH.
#
# Configure in capture/runpod.env, or export RUNPOD_* and RUNPOD_ENV_FILE=/path/to/file
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
  echo "error: set RUNPOD_IP and RUNPOD_PORT in ${SCRIPT_DIR}/runpod.env." >&2
  exit 1
fi

if [[ "${RUNPOD_IP}" == "ssh.runpod.io" ]] && [[ -z "${RUNPOD_FORCE_SSH_TUNNEL:-}" ]]; then
  echo "error: ssh.runpod.io does not support SSH local port forwarding (-L)." >&2
  echo "  Set RUNPOD_PUBLIC_URL in capture/runpod.env (HTTP proxy or TCP http://ip:port from dashboard)" >&2
  echo "  and use ./capture/run_full_stack.sh, or use a pod with direct SSH + public IP." >&2
  exit 1
fi

if ! command -v autossh >/dev/null 2>&1; then
  echo "error: autossh not found. Install with: brew install autossh" >&2
  exit 1
fi

# RunPod "ssh user@ssh.runpod.io" uses a gateway username, not root. Override when needed.
RUNPOD_SSH_USER="${RUNPOD_SSH_USER:-root}"

ssh_args=( -T -o RequestTTY=no )
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
