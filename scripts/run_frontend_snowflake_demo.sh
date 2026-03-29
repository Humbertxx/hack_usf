#!/usr/bin/env bash
# One command: unified FastAPI (Snowflake) on :8000 + Next dev with proxies pointed at it.
# Open http://localhost:3000/demo — then use Home / Timeline / Insights from the nav.
#
# Production safety: child uvicorn always gets SNOWFLAKE_DATABASE=GRANDMA_MONITOR_DEV (after .env).
# If your shell exports SNOWFLAKE_DATABASE=GRANDMA_MONITOR, this script exits so the demo is not
# started under an explicit production DB selection.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ "${SNOWFLAKE_DATABASE:-}" == "GRANDMA_MONITOR" ]]; then
  echo "run_frontend_snowflake_demo.sh: Unset SNOWFLAKE_DATABASE=GRANDMA_MONITOR in your shell before running." >&2
  exit 1
fi

if [[ -f .env ]]; then
  set -a
  # shellcheck source=/dev/null
  . ./.env
  set +a
fi

export SNOWFLAKE_DATABASE=GRANDMA_MONITOR_DEV

cleanup() {
  if [[ -n "${UVICORN_PID:-}" ]] && kill -0 "$UVICORN_PID" 2>/dev/null; then
    kill "$UVICORN_PID" 2>/dev/null || true
    wait "$UVICORN_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

PY="python3"
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
fi

echo "Starting uvicorn app:app on 127.0.0.1:8000 (SNOWFLAKE_DATABASE=$SNOWFLAKE_DATABASE)"
"$PY" -m uvicorn app:app --host 127.0.0.1 --port 8000 &
UVICORN_PID=$!

# Brief pause so Next's first API calls are less likely to race the listener.
sleep 1

cd "$ROOT/frontend"
export CV_API_BASE=http://127.0.0.1:8000
echo "Starting Next.js (CV_API_BASE=$CV_API_BASE). Then visit http://localhost:3000/demo"
npm run dev
