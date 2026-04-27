@echo off
title YOLO Backend
cd /d D:\yolo26s_platform
call venv\Scripts\activate
REM Disable Ultralytics auto pip install (prevents hang on slow/offline networks)
set YOLO_AUTOINSTALL=False
uvicorn server.main:app --host 0.0.0.0 --port 8000
pause
