@echo off
rem Starts the VMS dev servers if they aren't already running, then opens the app.
rem Safe to run any number of times. Needs uv and Node.js; nothing else to install.
rem   API  http://localhost:8000  (also starts the embedded PostgreSQL)
rem   Web  http://localhost:5173
rem Each server runs in its own window; close that window to stop it.
setlocal
cd /d "%~dp0"

where uv >nul 2>&1 || (echo uv is not installed: https://docs.astral.sh/uv/ & pause & exit /b 1)
where npm >nul 2>&1 || (echo Node.js / npm is not installed: https://nodejs.org/ & pause & exit /b 1)

rem ---------- First run: local settings (embedded PostgreSQL, no Redis/MinIO needed) ----------
set "SEED="
if not exist "api\.env" (
  echo First run: creating api\.env with local settings...
  (
    echo ENV=dev
    echo DATABASE_URL=postgresql+asyncpg://vms_app:vms_app@127.0.0.1:54329/vms
    echo DATABASE_ADMIN_URL=postgresql+asyncpg://vms:vms@127.0.0.1:54329/vms
    echo REDIS_URL=memory://
    echo STORAGE_BACKEND=local
  ) > "api\.env"
  set "SEED=&& uv run python -m scripts.seed"
)

rem ---------- Phones: QR codes and links use this PC's Wi-Fi address ----------
rem (follows the address if the router changes it; LAN_ADDRESS=off in api\.env turns this off)
pushd api
uv run python -m scripts.lan_address
popd

rem Where the app is opened: PUBLIC_WEB_URL in api\.env (an https:// address there also
rem makes the web server use https, e.g. for the camera on phones), else localhost.
set "WEB=http://localhost:5173"
for /f "usebackq tokens=1,* delims==" %%a in ("api\.env") do if /i "%%a"=="PUBLIC_WEB_URL" set "WEB=%%b"

rem ---------- API (and PostgreSQL) ----------
rem Starts PostgreSQL, applies any new database migrations (and on the first run loads
rem the demo data), then runs the API with auto-reload.
call :listening 8000
if errorlevel 1 (
  echo Starting the API...
  start "VMS API" /d "%~dp0api" cmd /k "uv run python scripts\local_pg.py start && uv run alembic upgrade head %SEED% && uv run python scripts\dev_api.py"
) else (
  echo API already running on port 8000.
)

rem ---------- Web ----------
call :listening 5173
if errorlevel 1 (
  if not exist "web\node_modules" (
    echo Installing web packages ^(first run^)...
    call npm --prefix web install || (pause & exit /b 1)
  )
  echo Starting the web app...
  start "VMS web" /d "%~dp0web" cmd /k npm run dev
) else (
  echo Web already running on port 5173.
)

rem ---------- Wait until both answer (the first start can take a minute) ----------
echo Waiting for the servers...
set /a tries=0
:wait
set /a tries+=1
if %tries% gtr 90 (
  echo Still not up after 3 minutes. Check the "VMS API" and "VMS web" windows for errors.
  pause
  exit /b 1
)
rem (ping is the delay: unlike timeout it also works when the script has no console)
curl -s -o nul -f http://127.0.0.1:8000/healthz || (ping -n 3 127.0.0.1 >nul & goto wait)
curl -s -o nul -k https://127.0.0.1:5173/ || curl -s -o nul http://127.0.0.1:5173/ || (ping -n 3 127.0.0.1 >nul & goto wait)

echo.
echo VMS is running:
echo   App            %WEB%
echo   Mock WhatsApp  %WEB%/dev/whatsapp
echo   API docs       http://localhost:8000/api/docs
if not defined VMS_NO_BROWSER start "" %WEB%
exit /b 0

rem errorlevel 0 if something is listening on port %1, else 1
:listening
netstat -ano -p tcp | findstr /r /c:":%1 .*LISTENING" >nul
exit /b %errorlevel%
