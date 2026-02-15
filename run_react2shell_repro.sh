#!/bin/bash
# React2Shell 复现：安装、启动、打 POC。任何方式退出都会关掉有洞的进程。
set -e
cd "$(dirname "$0")"
PORT=${PORT:-3011}
PID=""

cleanup() {
  echo ""
  echo "[cleanup] Stopping repro server on port $PORT..."
  # 1) 杀 npm 整棵子树（含 next-server）
  [ -n "$PID" ] && pkill -9 -P "$PID" 2>/dev/null || true
  [ -n "$PID" ] && kill -9 "$PID" 2>/dev/null || true
  # 2) 按端口杀（防止漏掉脱离父进程的 next-server）
  if command -v fuser >/dev/null 2>&1; then
    fuser -k "${PORT}/tcp" 2>/dev/null || true
  fi
  PIDS=$(lsof -ti:"$PORT" 2>/dev/null) || true
  [ -n "$PIDS" ] && echo "$PIDS" | xargs kill -9 2>/dev/null || true
  sleep 1
  PIDS=$(lsof -ti:"$PORT" 2>/dev/null) || true
  [ -n "$PIDS" ] && echo "$PIDS" | xargs kill -9 2>/dev/null || true
  true
}
trap cleanup EXIT INT TERM

echo "=== React2Shell repro (port $PORT) ==="

echo "[1] Installing deps..."
if command -v pnpm >/dev/null 2>&1; then
  pnpm install || pnpm install --legacy-peer-deps
else
  echo "    (no pnpm, using npm and skipping preinstall)"
  npm install --legacy-peer-deps --ignore-scripts
fi

echo "[2] Freeing port $PORT if in use..."
PIDS=$(lsof -ti:"$PORT" 2>/dev/null) || true
[ -n "$PIDS" ] && echo "$PIDS" | xargs kill -9 2>/dev/null || true
sleep 3
if lsof -ti:"$PORT" >/dev/null 2>&1; then
  echo "    Port $PORT still in use (need sudo?). Try: PORT=$((PORT+1)) ./run_react2shell_repro.sh"
  exit 1
fi

echo "[3] Starting Next.js dev server on $PORT..."
npm run dev -- -p "$PORT" &
PID=$!

echo "[4] Waiting 45s for server..."
sleep 45

echo "[5] Running POC (whoami)..."
python3 scripts/react2shell_poc.py --url "http://localhost:$PORT" --cmd whoami

echo "[6] Done."
