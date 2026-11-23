#!/usr/bin/env bash
# One command: API on 8010, Vite on 5180. Ctrl-C stops both.
set -euo pipefail
cd "$(dirname "$0")/.."

API_PORT=8010
WEB_PORT=5180

need() { command -v "$1" >/dev/null 2>&1 || { echo "缺少 $1，请先安装" >&2; exit 1; }; }
need uv
need npm

if [ ! -d frontend/node_modules ]; then
  echo "→ 安装前端依赖"
  (cd frontend && npm install --no-audit --no-fund)
fi

echo "→ 同步后端依赖 (uv)"
(cd backend && uv sync --quiet)

cleanup() {
  trap - INT TERM EXIT
  [ -n "${API_PID:-}" ] && kill "$API_PID" 2>/dev/null || true
  [ -n "${WEB_PID:-}" ] && kill "$WEB_PID" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

echo "→ API  http://127.0.0.1:${API_PORT}"
(cd backend && uv run uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" --reload) &
API_PID=$!

echo "→ Web  http://127.0.0.1:${WEB_PORT}"
(cd frontend && npm run dev -- --port "$WEB_PORT") &
WEB_PID=$!

# 任一进程退出就收掉另一个，别留孤儿占端口（macOS 自带 bash 3.2 没有 wait -n）
while kill -0 "$API_PID" 2>/dev/null && kill -0 "$WEB_PID" 2>/dev/null; do
  sleep 1
done
