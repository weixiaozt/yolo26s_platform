@echo off
title YOLO Celery Worker
cd /d D:\yolo26s_platform
call venv\Scripts\activate
set PYTHONPATH=D:\yolo26s_platform
REM Disable Ultralytics auto pip install (prevents hang on slow/offline networks)
set YOLO_AUTOINSTALL=False
celery -A server.tasks worker --loglevel=info --pool=solo
pause
