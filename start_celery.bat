@echo off
title YOLO Celery Worker
cd /d D:\yolo26s_platform
call venv\Scripts\activate
set PYTHONPATH=D:\yolo26s_platform
celery -A server.tasks worker --loglevel=info --pool=solo
pause
