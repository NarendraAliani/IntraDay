@echo off
setlocal enabledelayedexpansion
REM app.bat
REM
REM DEVELOPMENT-MODE, single-click launcher. Created at Checkpoint 10;
REM rewritten at Checkpoint 24A-finalization to add real startup
REM verification (poll each service's own health endpoint rather than
REM merely assuming a spawned window means the service is ready) and a
REM clearer, numbered, non-technical-user-friendly startup sequence.
REM
REM THIS IS NOT A PRODUCTION LAUNCHER. It contains no Docker, no secrets,
REM no production configuration, and starts development servers only.
REM Docker deployment remains explicitly deferred to a future "Production
REM Hardening/Deployment" checkpoint. This script never enables
REM TRADING_MODE=LIVE and never creates or prints a real credential.
REM
REM Checkpoint 11: the API is authenticated (session-cookie based - see
REM docs/architecture/AUTHENTICATION_AUTHORIZATION.md). This script
REM deliberately does NOT create a default user or superuser - doing so
REM silently would mean a fixed, guessable, hard-coded credential shipped
REM in source control, defeating the point of adding authentication. If
REM no user exists yet, create one manually (see the printed instructions
REM at the end) after the backend is confirmed running.
REM
REM Both the backend and frontend are launched via `start "title" cmd /k
REM "..."` - each in its OWN separate console window - specifically
REM because `manage.py runserver` and `npm run dev` both BLOCK forever;
REM running them sequentially in this script's own console (without
REM `start`) would mean the frontend command never runs until the
REM backend process exits. `start` returns immediately, letting this
REM script continue on to verify both services actually became healthy,
REM then exit cleanly - closing THIS launcher window never closes the
REM two separate server windows it spawned.
REM
REM Safe to re-run: it never overwrites an existing .env or
REM frontend/.env.local, and re-installing already-installed dependencies
REM is a fast no-op for both Poetry and npm.

title IntraDay Launcher
echo ==========================================
echo   IntraDay - Local Application Launcher
echo ==========================================
echo   Development mode only. No Docker. No live trading.
echo ==========================================
echo.

REM --- Resolve the project root as this script's own directory, so it
REM     works regardless of where the repository is checked out (never
REM     hard-code D:\IntraDay). %~dp0 always ends with a trailing backslash.
set "PROJECT_ROOT=%~dp0"
cd /d "%PROJECT_ROOT%" || (
    echo [FAIL] Could not switch to project root: %PROJECT_ROOT%
    pause
    exit /b 1
)

echo [1/8] Checking Python / Poetry...
where python >nul 2>nul
if errorlevel 1 (
    echo [FAIL] Python was not found on PATH. Install Python 3.12+ and re-run.
    pause
    exit /b 1
)
where poetry >nul 2>nul
if errorlevel 1 (
    echo [FAIL] Poetry was not found on PATH. Install Poetry ^(see
    echo        docs/development/LOCAL_DEVELOPMENT.md^) and re-run.
    pause
    exit /b 1
)
echo       OK - Python and Poetry found.

echo [2/8] Checking Node.js / npm...
where node >nul 2>nul
if errorlevel 1 (
    echo [FAIL] Node.js was not found on PATH. Install Node 20+ and re-run.
    pause
    exit /b 1
)
where npm >nul 2>nul
if errorlevel 1 (
    echo [FAIL] npm was not found on PATH. Install Node.js ^(includes npm^) and re-run.
    pause
    exit /b 1
)
echo       OK - Node.js and npm found.

echo [3/8] Checking backend dependencies / configuration...
if not exist "%PROJECT_ROOT%.venv\" (
    echo       Backend virtualenv not found - running "poetry install" ^(this may take a while^)...
    call poetry install --no-interaction
    if errorlevel 1 (
        echo [FAIL] "poetry install" failed. See output above.
        pause
        exit /b 1
    )
) else (
    echo       OK - backend virtualenv already present.
)
if not exist "%PROJECT_ROOT%.env" (
    if exist "%PROJECT_ROOT%.env.example" (
        echo       No .env found - copying .env.example as a starting point.
        copy /Y "%PROJECT_ROOT%.env.example" "%PROJECT_ROOT%.env" >nul
    )
) else (
    echo       OK - .env already present ^(left untouched^).
)

echo [4/8] Checking frontend dependencies / configuration...
if not exist "%PROJECT_ROOT%frontend\node_modules\" (
    echo       Frontend dependencies not found - running "npm install" ^(this may take a while^)...
    pushd "%PROJECT_ROOT%frontend"
    call npm install
    if errorlevel 1 (
        echo [FAIL] "npm install" failed. See output above.
        popd
        pause
        exit /b 1
    )
    popd
) else (
    echo       OK - frontend dependencies already present.
)
if not exist "%PROJECT_ROOT%frontend\.env.local" (
    if exist "%PROJECT_ROOT%frontend\.env.example" (
        echo       No frontend\.env.local found - copying frontend\.env.example.
        copy /Y "%PROJECT_ROOT%frontend\.env.example" "%PROJECT_ROOT%frontend\.env.local" >nul
    )
) else (
    echo       OK - frontend\.env.local already present ^(left untouched^).
)

echo [5/8] Checking database and applying migrations...
REM Requires PostgreSQL to be reachable (POSTGRES_* in .env). Safe to
REM re-run - `manage.py migrate` is itself idempotent.
call poetry run python manage.py migrate --no-input
if errorlevel 1 (
    echo [FAIL] "manage.py migrate" failed. Check PostgreSQL is running and
    echo        POSTGRES_* variables in .env are correct, then re-run.
    pause
    exit /b 1
)
echo       OK - database migrations applied.

echo [6/8] Starting backend on port 8000...
start "IntraDay Backend (Django - port 8000)" cmd /k "cd /d "%PROJECT_ROOT%" && poetry run python manage.py runserver 127.0.0.1:8000"

echo       Waiting for the backend to become ready...
set BACKEND_READY=0
for /l %%i in (1,1,30) do (
    if !BACKEND_READY! == 0 (
        curl -s -o nul -w "%%{http_code}" http://127.0.0.1:8000/healthz > "%TEMP%\intraday_backend_check.txt" 2>nul
        set /p BACKEND_STATUS=<"%TEMP%\intraday_backend_check.txt"
        if "!BACKEND_STATUS!"=="200" (
            set BACKEND_READY=1
        ) else (
            timeout /t 1 /nobreak >nul
        )
    )
)
del /q "%TEMP%\intraday_backend_check.txt" >nul 2>nul
if !BACKEND_READY! == 0 (
    echo [FAIL] Backend did not respond at http://127.0.0.1:8000/healthz within 30 seconds.
    echo        Check the "IntraDay Backend" window for errors. The frontend will
    echo        still be started below, but login will fail with a CSRF/403 error
    echo        until the backend is actually reachable - this is the documented
    echo        root cause of "Request failed with status 403" on first login.
) else (
    echo       OK - backend is listening and healthy at http://127.0.0.1:8000
)

echo [7/8] Starting frontend on port 5173...
start "IntraDay Frontend (Vite - port 5173)" cmd /k "cd /d "%PROJECT_ROOT%frontend" && npm run dev"

echo       Waiting for the frontend to become ready...
set FRONTEND_READY=0
for /l %%i in (1,1,30) do (
    if !FRONTEND_READY! == 0 (
        curl -s -o nul -w "%%{http_code}" http://127.0.0.1:5173/ > "%TEMP%\intraday_frontend_check.txt" 2>nul
        set /p FRONTEND_STATUS=<"%TEMP%\intraday_frontend_check.txt"
        if "!FRONTEND_STATUS!"=="200" (
            set FRONTEND_READY=1
        ) else (
            timeout /t 1 /nobreak >nul
        )
    )
)
del /q "%TEMP%\intraday_frontend_check.txt" >nul 2>nul
if !FRONTEND_READY! == 0 (
    echo [FAIL] Frontend did not respond at http://127.0.0.1:5173/ within 30 seconds.
    echo        Check the "IntraDay Frontend" window for errors.
) else (
    echo       OK - frontend is listening at http://127.0.0.1:5173
)

echo [8/8] Startup complete.
echo.
echo ==========================================
if !BACKEND_READY! == 1 if !FRONTEND_READY! == 1 (
    echo   Both services are UP and verified reachable.
) else (
    echo   WARNING: one or more services failed to respond - see above.
)
echo ==========================================
echo   Backend:   http://127.0.0.1:8000
echo   Frontend:  http://127.0.0.1:5173
echo.
echo   Open the Frontend URL above in your browser to use the app.
echo   Both servers run in their own separate windows - closing THIS
echo   launcher window will NOT stop them. Close those windows (or
echo   press Ctrl+C inside them) to stop the servers.
echo.
echo   No login user exists until you create one. In a new terminal
echo   (after the backend is running), run:
echo.
echo     poetry run python manage.py createsuperuser
echo.
echo   A superuser can both read and activate configuration. To
echo   create a read-only user instead, omit --superuser and add
echo   them to the "configuration-operators" group only if they
echo   should also be able to activate:
echo.
echo     poetry run python manage.py shell -c "from django.contrib.auth.models import User, Group; u = User.objects.create_user('username', password='changeme'); u.groups.add(Group.objects.get(name='configuration-operators'))"
echo.
echo   DEVELOPMENT MODE ONLY - no Docker, not production-hardened,
echo   TRADING_MODE=LIVE is never enabled by this script. See
echo   docs/architecture/AUTHENTICATION_AUTHORIZATION.md for the full
echo   security model.
echo ==========================================
echo.
echo Press any key to exit this launcher window (servers keep running)...
pause >nul

endlocal
