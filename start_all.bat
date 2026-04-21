@echo off
echo ========================================
echo   YOLO26s-Seg 缺陷检测平台 启动中...
echo ========================================

echo [1/3] 启动后端...
start "" /min "D:\yolo26s_platform\start_backend.bat"
timeout /t 5 /nobreak >nul

echo [2/3] 启动 Celery Worker...
start "" /min "D:\yolo26s_platform\start_celery.bat"
timeout /t 3 /nobreak >nul

echo [3/3] 启动前端...
start "" /min "D:\yolo26s_platform\start_frontend.bat"
timeout /t 3 /nobreak >nul

echo ========================================
echo   全部启动完成！
echo   访问地址: http://localhost:5174
echo   默认账号: admin / admin123
echo ========================================
pause
