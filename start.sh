#!/usr/bin/env bash
# DSH 工作台启动脚本（Linux / macOS）
set -e
cd "$(dirname "$0")"

PORT="${1:-8799}"

if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "找不到 python，请先安装 Python 3.8+"
  exit 1
fi

# 端口被占用就先杀掉旧进程（仅 Linux/macOS）
if command -v lsof >/dev/null 2>&1; then
  OLD=$(lsof -ti tcp:"$PORT" 2>/dev/null || true)
  if [ -n "$OLD" ]; then
    echo "端口 $PORT 被占用，关闭旧进程 $OLD"
    kill -9 $OLD 2>/dev/null || true
    sleep 1
  fi
fi

echo "启动 DSH 工作台: http://127.0.0.1:$PORT"
exec "$PY" server.py --port "$PORT"
