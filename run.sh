#!/usr/bin/env bash
#
# Portage dev launcher — starts the backend, waits until it's healthy, then the
# frontend. Ctrl+C stops both. First run auto-creates the Python venv and installs
# backend + frontend dependencies.
#
#   ./run.sh
#
# Env overrides: PORTAGE_BACKEND_PORT (8000), PORTAGE_FRONTEND_PORT (5173)

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
BACKEND_PORT="${PORTAGE_BACKEND_PORT:-8000}"
FRONTEND_PORT="${PORTAGE_FRONTEND_PORT:-5173}"

BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  echo ""
  echo "⏹  Stopping Portage…"
  [ -n "$FRONTEND_PID" ] && kill "$FRONTEND_PID" 2>/dev/null || true
  [ -n "$BACKEND_PID" ] && { pkill -P "$BACKEND_PID" 2>/dev/null; kill "$BACKEND_PID" 2>/dev/null; } || true
  exit 0
}
trap cleanup INT TERM

# Free a TCP port held by a previous run (scoped to the given port only).
free_port() {
  local port="$1" pids
  pids="$(lsof -ti tcp:"$port" 2>/dev/null || true)"
  if [ -n "$pids" ]; then
    echo "→ freeing port $port (pids: $pids)"
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
    sleep 1
  fi
}

echo "▶  Portage launcher"
echo "   backend  : http://localhost:$BACKEND_PORT  (docs: /docs)"
echo "   frontend : http://localhost:$FRONTEND_PORT"
echo ""

# ---------------------------------------------------------------- backend ----
cd "$BACKEND"
if [ ! -x ".venv/bin/python" ]; then
  BASE_PY=""
  for cand in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
      BASE_PY="$cand"; break
    fi
  done
  if [ -z "$BASE_PY" ]; then
    echo "✗ Portage needs Python 3.10 or newer (found: $(python3 --version 2>&1)). Install it, e.g. 'brew install python@3.12'."
    exit 1
  fi
  echo "→ creating Python virtual environment with $BASE_PY…"
  "$BASE_PY" -m venv .venv
fi
# Always use the venv's own interpreter; a bare 'pip' can resolve to another Python (e.g. Anaconda).
PY="$BACKEND/.venv/bin/python"
"$PY" -m pip --version >/dev/null 2>&1 || "$PY" -m ensurepip --upgrade >/dev/null
echo "→ installing backend dependencies…"
"$PY" -m pip install -q --upgrade pip >/dev/null 2>&1 || true
"$PY" -m pip install -q -r requirements.txt

free_port "$BACKEND_PORT"
if [ -z "${PORTAGE_SMTP_HOST:-}" ] && [ -z "${PORTAGE_AUTH_DISABLED:-}" ]; then
  # Local development without a mail server: sign-in, sign-up and reset codes are printed below.
  export PORTAGE_AUTH_DEV_LOG_CODES="${PORTAGE_AUTH_DEV_LOG_CODES:-1}"
  echo "→ no PORTAGE_SMTP_HOST set: sign-in codes will be printed in this terminal"
fi
echo "→ starting backend (uvicorn --reload)…"
"$PY" -m uvicorn app.main:app --port "$BACKEND_PORT" --reload &
BACKEND_PID=$!

# ---- wait for backend health ----
printf "→ waiting for backend to be healthy"
for i in $(seq 1 60); do
  if curl -sf "http://localhost:$BACKEND_PORT/api/health" >/dev/null 2>&1; then
    printf " ✓\n"
    break
  fi
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    printf " ✗\nBackend process exited before becoming healthy.\n"
    cleanup
  fi
  printf "."
  sleep 0.5
  if [ "$i" -eq 60 ]; then
    printf " ✗\nBackend did not become healthy in time.\n"
    cleanup
  fi
done

# --------------------------------------------------------------- frontend ----
cd "$FRONTEND"
if [ ! -d "node_modules" ]; then
  echo "→ installing frontend dependencies (first run)…"
  npm install --no-audit --no-fund
fi

free_port "$FRONTEND_PORT"
echo "→ starting frontend (vite)…"
npm run dev -- --port "$FRONTEND_PORT" &
FRONTEND_PID=$!

echo ""
echo "✅ Portage is running."
echo "   Open  →  http://localhost:$FRONTEND_PORT"
echo "   Stop  →  Ctrl+C"
echo ""

# Keep the launcher in the foreground until interrupted (portable to bash 3.2).
wait
cleanup
