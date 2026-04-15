#!/bin/bash
# ============================================================
# YOLO26s-Seg 标注训练平台 — 快速启动脚本
# ============================================================
# 使用方式:
#   chmod +x start.sh
#   ./start.sh
# ============================================================

set -e

echo "============================================"
echo "  YOLO26s-Seg 标注训练平台"
echo "============================================"

# 1. 启动 MySQL + Redis
echo ""
echo "[1/3] 启动 MySQL 和 Redis..."
docker compose up -d mysql redis
echo "      等待 MySQL 就绪..."
sleep 8

# 2. 启动 Celery Worker（后台）
echo "[2/3] 启动 Celery Worker..."
celery -A server.tasks worker -l info -c 1 &
CELERY_PID=$!
echo "      Celery Worker PID: $CELERY_PID"

# 3. 启动 FastAPI
echo "[3/3] 启动 FastAPI 后端..."
echo ""
echo "============================================"
echo "  后端地址: http://localhost:8000"
echo "  API 文档: http://localhost:8000/docs"
echo "============================================"
echo ""
uvicorn server.main:app --reload --host 0.0.0.0 --port 8000

# 退出时关闭 Celery
kill $CELERY_PID 2>/dev/null
