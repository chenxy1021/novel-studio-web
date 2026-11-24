#!/usr/bin/env bash
# Novel Studio 一键启动：后端 8010 + 前端 5180，日志和 pid 放在 .run/。
#
#   ./scripts/dev.sh            启动，Ctrl-C 一起停
#   ./scripts/dev.sh open       启动并打开浏览器
#   ./scripts/dev.sh stop       停掉两个服务（按端口收，孤儿进程也能收）
#   ./scripts/dev.sh status     看端口、健康和日志位置
#   ./scripts/dev.sh restart    先停再起
#
# 端口是项目约定（8000/5173 留给别的项目），不要改。
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT=$(pwd -P)
RUN_DIR="$ROOT/.run"
API_PORT=8010
WEB_PORT=5180
API_LOG="$RUN_DIR/api.log"
WEB_LOG="$RUN_DIR/web.log"
API_PID_FILE="$RUN_DIR/api.pid"
WEB_PID_FILE="$RUN_DIR/web.pid"
STOP_SENTINEL="$RUN_DIR/stopping"
API_PID=""
WEB_PID=""
INTERRUPTED=0

say()  { printf '\033[35m→\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '\033[33m!\033[0m %s\n' "$*" >&2; }
die()  { warn "$*"; exit 1; }

need() { command -v "$1" >/dev/null 2>&1 || die "缺少 $1，请先安装"; }

# 某些 macOS 没装 lsof 的情况极少；没有就退化成只看 pidfile
listeners() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -tiTCP:"$1" -sTCP:LISTEN 2>/dev/null || true
  fi
}

listen_detail() {
  command -v lsof >/dev/null 2>&1 || return 0
  lsof -nP -iTCP:"$1" -sTCP:LISTEN 2>/dev/null | awk 'NR > 1 { printf "    %s (pid %s)\n", $1, $2 }'
}

kill_listeners() {
  local port=$1 pids pid
  pids=$(listeners "$port")
  [ -n "$pids" ] || return 0
  for pid in $pids; do kill "$pid" 2>/dev/null || true; done
  sleep 1
  pids=$(listeners "$port")
  if [ -n "$pids" ]; then
    for pid in $pids; do kill -9 "$pid" 2>/dev/null || true; done
  fi
}

stop_one() {
  local name=$1 port=$2 pidfile=$3 pid=""
  if [ -f "$pidfile" ]; then
    pid=$(cat "$pidfile" 2>/dev/null || true)
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
    rm -f "$pidfile"
  fi
  kill_listeners "$port"
  if [ -z "$(listeners "$port")" ]; then
    ok "已停止 ${name}（:${port}）"
  else
    warn "${name}（:${port}）仍被占用，手动处理："
    listen_detail "$port"
  fi
}

stop_all() {
  say "停止 Novel Studio"
  # 正在前台跑着的 start 看到这个标记会安静退出，不再打「进程意外退出」
  mkdir -p "$RUN_DIR"
  : >"$STOP_SENTINEL"
  stop_one "API" "$API_PORT" "$API_PID_FILE"
  stop_one "Web" "$WEB_PORT" "$WEB_PID_FILE"
}

cleanup() {
  trap - INT TERM EXIT
  INTERRUPTED=1
  [ -n "$API_PID" ] && kill "$API_PID" 2>/dev/null || true
  [ -n "$WEB_PID" ] && kill "$WEB_PID" 2>/dev/null || true
  rm -f "$API_PID_FILE" "$WEB_PID_FILE" "$STOP_SENTINEL"
  kill_listeners "$API_PORT"
  kill_listeners "$WEB_PORT"
  wait 2>/dev/null || true
  ok "两个服务都已停止"
}

wait_http() {
  local url=$1 name=$2 log=$3 i=0
  while [ "$i" -lt 60 ]; do
    if curl -fsS -o /dev/null --max-time 2 "$url" 2>/dev/null; then
      ok "$name 就绪"
      return 0
    fi
    i=$((i + 1))
    sleep 1
  done
  warn "$name 60 秒内没起来，日志：$log"
  return 1
}

status_all() {
  local api_pids web_pids
  api_pids=$(listeners "$API_PORT")
  web_pids=$(listeners "$WEB_PORT")

  if [ -z "$api_pids" ]; then
    printf '  API  :%s  未运行\n' "$API_PORT"
  elif curl -fsS -o /dev/null --max-time 2 "http://127.0.0.1:$API_PORT/api/ping" 2>/dev/null; then
    printf '  API  :%s  运行中  http://127.0.0.1:%s/api/ping\n' "$API_PORT" "$API_PORT"
  else
    printf '  API  :%s  端口在监听，但 /api/ping 没响应\n' "$API_PORT"
    listen_detail "$API_PORT"
  fi

  if [ -z "$web_pids" ]; then
    printf '  Web  :%s  未运行\n' "$WEB_PORT"
  elif curl -fsS -o /dev/null --max-time 2 "http://127.0.0.1:$WEB_PORT/" 2>/dev/null; then
    printf '  Web  :%s  运行中  http://127.0.0.1:%s/\n' "$WEB_PORT" "$WEB_PORT"
  else
    printf '  Web  :%s  端口在监听，但首页没响应\n' "$WEB_PORT"
    listen_detail "$WEB_PORT"
  fi

  printf '  日志：%s  %s\n' "$API_LOG" "$WEB_LOG"
}

start() {
  local open_after=$1 busy=0

  need uv
  need npm
  need curl

  if [ -n "$(listeners "$API_PORT")" ]; then
    busy=1
    warn "端口 $API_PORT 已被占用："
    listen_detail "$API_PORT"
  fi
  if [ -n "$(listeners "$WEB_PORT")" ]; then
    busy=1
    warn "端口 $WEB_PORT 已被占用："
    listen_detail "$WEB_PORT"
  fi
  if [ "$busy" = 1 ]; then
    die "先运行 ./scripts/dev.sh stop 收掉旧进程"
  fi

  mkdir -p "$RUN_DIR"
  rm -f "$STOP_SENTINEL"

  if [ ! -d frontend/node_modules ]; then
    say "安装前端依赖"
    (cd frontend && npm install --no-audit --no-fund)
  fi

  say "同步后端依赖（uv sync）"
  (cd backend && uv sync --quiet)

  say "启动 API  → http://127.0.0.1:$API_PORT"
  (
    cd backend
    exec uv run uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" --reload
  ) >"$API_LOG" 2>&1 &
  API_PID=$!
  echo "$API_PID" >"$API_PID_FILE"

  say "启动 Web  → http://127.0.0.1:$WEB_PORT"
  (
    cd frontend
    exec npm run dev -- --port "$WEB_PORT"
  ) >"$WEB_LOG" 2>&1 &
  WEB_PID=$!
  echo "$WEB_PID" >"$WEB_PID_FILE"

  trap cleanup INT TERM EXIT

  wait_http "http://127.0.0.1:$API_PORT/api/ping" "API" "$API_LOG" || exit 1
  wait_http "http://127.0.0.1:$WEB_PORT/" "Web" "$WEB_LOG" || exit 1

  if [ "$open_after" = "open" ] && command -v open >/dev/null 2>&1; then
    open "http://127.0.0.1:$WEB_PORT/"
  fi

  echo
  ok "Novel Studio 已启动"
  printf '  Web  http://127.0.0.1:%s/\n' "$WEB_PORT"
  printf '  API  http://127.0.0.1:%s/api/ping\n' "$API_PORT"
  printf '  日志 %s\n' "$RUN_DIR"
  printf '  停止 Ctrl-C，或在另一个终端 ./scripts/dev.sh stop\n'
  echo

  # 任一进程退出就收掉另一个，别留孤儿占端口（macOS 自带 bash 3.2 没有 wait -n）
  while kill -0 "$API_PID" 2>/dev/null && kill -0 "$WEB_PID" 2>/dev/null; do
    if [ -f "$STOP_SENTINEL" ]; then
      cleanup
      exit 0
    fi
    sleep 1
  done

  # Ctrl-C：trap 里的 cleanup 已经收过尾
  if [ "$INTERRUPTED" = 1 ]; then
    exit 0
  fi
  # 另一个终端跑了 ./scripts/dev.sh stop：按标记安静收尾，不打「意外退出」
  if [ -f "$STOP_SENTINEL" ]; then
    cleanup
    exit 0
  fi

  if ! kill -0 "$API_PID" 2>/dev/null; then
    warn "API 退出了，最后 20 行日志："
    tail -n 20 "$API_LOG" 2>/dev/null || true
  fi
  if ! kill -0 "$WEB_PID" 2>/dev/null; then
    warn "Web 退出了，最后 20 行日志："
    tail -n 20 "$WEB_LOG" 2>/dev/null || true
  fi
  exit 1
}

case "${1:-start}" in
  start) start "" ;;
  open) start open ;;
  stop) stop_all ;;
  status) status_all ;;
  restart)
    stop_all
    start ""
    ;;
  *)
    die "用法：./scripts/dev.sh [start|open|stop|status|restart]"
    ;;
esac
