@echo off
title YOLO Backend
cd /d D:\yolo26s_platform
call venv\Scripts\activate
uvicorn server.main:app --host 0.0.0.0 --port 8000
pause
