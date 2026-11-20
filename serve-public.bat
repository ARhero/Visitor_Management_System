@echo off
rem Runs VMS for the internet: one process, one port, HTTPS (docs\public-setup.md).
rem Run "uv run python -m scripts.go_public https://<public-ip>:<port>" in api\ once first.
rem Don't run start.bat at the same time: both would run the background jobs.
setlocal
cd /d "%~dp0"

where uv >nul 2>&1 || (echo uv is not installed: https://docs.astral.sh/uv/ & pause & exit /b 1)
where npm >nul 2>&1 || (echo Node.js / npm is not installed: https://nodejs.org/ & pause & exit /b 1)
if not exist "api\.certs\cert.pem" (
  echo No HTTPS certificate yet. First run, in the api folder:
  echo   uv run python -m scripts.go_public https://YOUR-PUBLIC-IP:PORT
  pause & exit /b 1
)
set "VMS_PORT="
for /f "usebackq tokens=1,* delims==" %%a in ("api\.env") do if /i "%%a"=="VMS_PORT" set "VMS_PORT=%%b"
if not defined VMS_PORT (echo VMS_PORT is missing from api\.env: run scripts.go_public first & pause & exit /b 1)

if not exist "web\node_modules" call npm --prefix web install || (pause & exit /b 1)
echo Building the web app...
call npm --prefix web run build || (pause & exit /b 1)

cd api
uv run python scripts\local_pg.py start || (pause & exit /b 1)
uv run alembic upgrade head || (pause & exit /b 1)
echo.
echo VMS is starting on port %VMS_PORT% (HTTPS). Close this window to stop it.
uv run uvicorn app.main:app --host 0.0.0.0 --port %VMS_PORT% --ssl-keyfile .certs\key.pem --ssl-certfile .certs\cert.pem --timeout-graceful-shutdown 3
pause
