@echo off
chcp 65001 >nul
REM ============================================================
REM  Register backend + celery as Windows services via NSSM.
REM  Frontend is served by the backend (web\dist), so NO separate
REM  frontend service is needed. After this, open the browser at
REM  http://localhost:8000  (admin / admin123).
REM
REM  RUN AS ADMINISTRATOR, one time, on the target machine.
REM  Prereqs already done: Python venv ready, deps installed,
REM  MySQL + Redis running as services, web\dist built.
REM ============================================================

REM  App dir = parent of this deploy\ folder (auto-detected; folder name can be anything, e.g. VPvision_AI)
for %%I in ("%~dp0..") do set "APP_DIR=%%~fI"
set PY=%APP_DIR%\venv\Scripts\python.exe

REM  nssm.exe: put it next to this script, or set full path / add to PATH.
set NSSM=%~dp0nssm.exe
if not exist "%NSSM%" set NSSM=nssm.exe

REM  Your actual MySQL / Redis service names (so they start first).
REM  Check with:  sc query state= all ^| findstr /i "mysql redis"
set MYSQL_SVC=MySQL80
set REDIS_SVC=Redis

if not exist "%APP_DIR%\logs" mkdir "%APP_DIR%\logs"

echo === Registering VP_backend (uvicorn: API + web UI) ===
"%NSSM%" install VP_backend "%PY%" "-m uvicorn server.main:app --host 0.0.0.0 --port 8000"
"%NSSM%" set VP_backend AppDirectory "%APP_DIR%"
"%NSSM%" set VP_backend AppEnvironmentExtra YOLO_AUTOINSTALL=False PYTHONPATH=%APP_DIR%
"%NSSM%" set VP_backend AppStdout "%APP_DIR%\logs\backend.out.log"
"%NSSM%" set VP_backend AppStderr "%APP_DIR%\logs\backend.err.log"
"%NSSM%" set VP_backend Start SERVICE_AUTO_START
"%NSSM%" set VP_backend DependOnService %MYSQL_SVC% %REDIS_SVC%

echo === Registering VP_celery (training worker, pool=solo) ===
"%NSSM%" install VP_celery "%PY%" "-m celery -A server.tasks worker --loglevel=info --pool=solo"
"%NSSM%" set VP_celery AppDirectory "%APP_DIR%"
"%NSSM%" set VP_celery AppEnvironmentExtra YOLO_AUTOINSTALL=False PYTHONPATH=%APP_DIR%
"%NSSM%" set VP_celery AppStdout "%APP_DIR%\logs\celery.out.log"
"%NSSM%" set VP_celery AppStderr "%APP_DIR%\logs\celery.err.log"
"%NSSM%" set VP_celery Start SERVICE_AUTO_START
"%NSSM%" set VP_celery DependOnService %MYSQL_SVC% %REDIS_SVC%

echo === Starting services ===
net start VP_backend
net start VP_celery

echo.
echo Done. Open http://localhost:8000   (admin / admin123)
echo Manage services: services.msc   or   "%NSSM%" edit VP_backend
echo.
echo To remove later (as admin):
echo   net stop VP_backend ^& "%NSSM%" remove VP_backend confirm
echo   net stop VP_celery  ^& "%NSSM%" remove VP_celery confirm
pause
