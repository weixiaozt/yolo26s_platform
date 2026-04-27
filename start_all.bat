@echo off
chcp 65001 >nul
echo ========================================
echo   YOLO26s-Seg Platform Starting...
echo ========================================

echo [1/3] Starting Backend...
start "" /min "D:\yolo26s_platform\start_backend.bat"
timeout /t 5 /nobreak >nul

echo [2/3] Starting Celery Worker...
start "" /min "D:\yolo26s_platform\start_celery.bat"
timeout /t 3 /nobreak >nul

echo [3/3] Starting Frontend...
start "" /min "D:\yolo26s_platform\start_frontend.bat"
timeout /t 3 /nobreak >nul

echo ========================================
echo   All services started!
echo   URL: http://localhost:5174
echo   Default account: admin / admin123
echo ========================================
pause
