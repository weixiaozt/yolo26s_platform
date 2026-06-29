@echo off
rem Minimal update script - no fancy logic, just the 3 essential steps.

cd /d D:\yolo26s_platform
if errorlevel 1 (
    echo [ERR] D:\yolo26s_platform not found
    pause
    exit /b 1
)

echo.
echo === Step 1: git status ===
git status
echo.
pause

echo.
echo === Step 2: git fetch ===
git fetch origin main
echo.

echo.
echo === Step 3: commits to pull ===
git log --oneline HEAD..origin/main
echo.
echo Press any key to pull, or Ctrl+C to abort.
pause

echo.
echo === Step 4: kill backend processes BEFORE continuing ===
echo Run in another cmd: taskkill /F /IM python.exe
echo Then come back and press any key.
pause

echo.
echo === Step 5: git pull ===
git pull --ff-only origin main
echo.

echo.
echo === Step 6: new HEAD ===
git log --oneline -1
echo.
echo Done. Now restart uvicorn + celery + frontend.
pause
