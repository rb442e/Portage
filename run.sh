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
  [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null || true
  pkill -f "uvicorn app.main:app" 2>/dev/null || true
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
if [ ! -d ".venv" ]; then
  echo "→ creating Python virtual environment…"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
echo "→ installing backend dependencies…"
pip install -q --upgrade pip >/dev/null 2>&1 || true
pip install -q -r requirements.txt

free_port "$BACKEND_PORT"
echo "→ starting backend (uvicorn --reload)…"
uvicorn app.main:app --port "$BACKEND_PORT" --reload &
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
