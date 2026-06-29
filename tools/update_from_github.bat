@echo off
setlocal EnableDelayedExpansion

rem ============================================================
rem  yolo26s_platform - Update from GitHub
rem  Pull latest main, run db auto-migration on backend restart.
rem  Keeps: local db data, storage/, .env, venv, node_modules.
rem ============================================================

cd /d D:\yolo26s_platform
if errorlevel 1 (
    echo [ERR] D:\yolo26s_platform not found
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   yolo26s_platform - Update from GitHub
echo ============================================================
echo.
echo This script will:
echo   1. Check git status (no uncommitted local changes)
echo   2. Show how many commits behind
echo   3. Tell you to kill backend processes manually
echo   4. git pull origin main
echo   5. Tell you to restart backend (db auto-migration)
echo.
echo Will NOT do (you do these):
echo   - kill uvicorn / celery
echo   - start backend / frontend
echo   - touch database (backend auto-migrates on startup)
echo   - install pip / npm deps (none added in this update)
echo.
pause

rem ---- 1. check git ----
echo.
echo [1/5] Checking git status...
echo.
git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
    echo [ERR] Not a git repo. If deployed by manual copy, init it first:
    echo       cd D:\yolo26s_platform
    echo       git init ^&^& git remote add origin https://github.com/weixiaozt/yolo26s_platform.git
    echo       git fetch ^&^& git checkout -ft origin/main
    pause
    exit /b 1
)

for /f "tokens=*" %%b in ('git rev-parse --abbrev-ref HEAD') do set BRANCH=%%b
echo Current branch: !BRANCH!
if not "!BRANCH!"=="main" (
    echo [WARN] Not on main branch. Suggest: git checkout main
    set /p CONT=Continue anyway? [y/N]:
    if /i not "!CONT!"=="y" exit /b 0
)

echo.
echo --- Local uncommitted changes ---
git status --short
echo.

git diff --quiet
set DIRTY=!errorlevel!
git diff --cached --quiet
set DIRTY_CACHED=!errorlevel!

if not "!DIRTY!"=="0" (
    echo [WARN] Local uncommitted changes detected.
    echo Suggest: git stash   OR   git commit -am "..."
    echo.
    set /p CONT=Auto stash now? [y/N]:
    if /i "!CONT!"=="y" (
        git stash push -m "auto-stash-before-update"
        echo [OK] Stashed. Recover later with: git stash pop
    ) else (
        echo [Abort] Handle local changes first
        pause
        exit /b 1
    )
)
if not "!DIRTY_CACHED!"=="0" (
    echo [WARN] Staged but uncommitted changes. Commit or reset first.
    pause
    exit /b 1
)

rem ---- 2. fetch + show behind ----
echo.
echo [2/5] Fetching from GitHub...
git fetch origin main
if errorlevel 1 (
    echo [ERR] git fetch failed, check network
    pause
    exit /b 1
)

echo.
echo --- Commits to be pulled ---
git log --oneline HEAD..origin/main
echo.

for /f %%n in ('git rev-list --count HEAD..origin/main') do set BEHIND=%%n
if "!BEHIND!"=="0" (
    echo [INFO] Already up to date, nothing to pull
    pause
    exit /b 0
)
echo [INFO] !BEHIND! commit^(s^) behind
echo.
set /p CONT=Confirm update? [y/N]:
if /i not "!CONT!"=="y" exit /b 0

rem ---- 3. tell user to kill processes ----
echo.
echo [3/5] You must stop backend services BEFORE pulling
echo.
echo In another cmd window:
echo   tasklist ^| findstr python              (find PIDs)
echo   taskkill /F /PID ^<uvicorn pid^>
echo   taskkill /F /PID ^<celery pid^>
echo.
echo Or kill all python processes (be careful):
echo   taskkill /F /IM python.exe
echo.
pause

rem ---- 4. git pull ----
echo.
echo [4/5] git pull --ff-only origin main...
git pull --ff-only origin main
if errorlevel 1 (
    echo [ERR] pull failed. Possible: local conflict OR remote force-pushed.
    echo Manual fix: git status / git fetch / git reset --hard origin/main
    pause
    exit /b 1
)

echo.
echo --- New HEAD ---
git log --oneline -1
echo.

rem ---- 5. restart instructions ----
echo.
echo [5/5] Update done! Restart backend now (db auto-migration runs on startup)
echo.
echo Start backend (uvicorn):
echo   set YOLO_AUTOINSTALL=False
echo   D:\yolo26s_platform\venv\Scripts\python.exe -m uvicorn server.main:app --host 0.0.0.0 --port 8000
echo.
echo Start celery worker:
echo   set YOLO_AUTOINSTALL=False
echo   D:\yolo26s_platform\venv\Scripts\python.exe -m celery -A server.tasks worker --loglevel=info --pool=solo
echo.
echo Start frontend:
echo   cd D:\yolo26s_platform\web
echo   npm run dev
echo.
echo Verify in browser http://localhost:5174 :
echo   - Project list grouped by 4 task types (seg / cls / obb / det)
echo   - Inference page model dropdown shows cancelled tasks too
echo   - TrainConfig page has "Save as default" + "Restore defaults" buttons
echo.

if exist .git\refs\stash (
    echo [Reminder] You stashed local changes. Restore with:
    echo   git stash pop
    echo.
)

echo ============================================================
echo  Update complete
echo ============================================================
pause
endlocal
