@echo off
chcp 65001 >nul
REM ============================================================
REM  Lock down the app directory so a NORMAL (non-admin) Windows
REM  user CANNOT open / read the source code and model files.
REM
REM  How it works: the services run as SYSTEM and keep working;
REM  the operator only uses the app through the browser
REM  (http://localhost:8000). Since the operator is NOT a local
REM  admin, they cannot take ownership -> the code stays hidden.
REM
REM  RUN AS ADMINISTRATOR, one time, AFTER install_services.bat.
REM ============================================================

REM  App dir = parent of this deploy\ folder (auto-detected; folder name can be anything, e.g. VPvision_AI)
for %%I in ("%~dp0..") do set "APP_DIR=%%~fI"

REM  >>> EDIT THIS: the normal Windows account the operator logs in with <<<
set WORKER_USER=labeler

echo Applying NTFS ACL lockdown on %APP_DIR%
echo   SYSTEM + Administrators : full control (services + you)
echo   %WORKER_USER% : DENIED (cannot open/read anything)
echo.

icacls "%APP_DIR%" /inheritance:r /grant:r "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)F" /deny "%WORKER_USER%:(OI)(CI)F"

echo.
echo Done.
echo Verify: log in as %WORKER_USER%, try to open %APP_DIR%  -> Access Denied.
echo         but http://localhost:8000 still works in the browser.
echo.
echo To UNLOCK later (as admin):
echo   icacls "%APP_DIR%" /remove:d "%WORKER_USER%"
echo   icacls "%APP_DIR%" /inheritance:e
pause
