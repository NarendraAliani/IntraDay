@echo off
setlocal enabledelayedexpansion
REM app.bat
REM
REM DEVELOPMENT-MODE launcher. Created at Checkpoint 10 once the Frontend
REM UX Testing Readiness Gate was satisfied (Persistence, Business API,
REM Frontend, and Human Workflow all YES — see taskReport.md's
REM Checkpoint 10 section). Starts the Django dev server and the Vite dev
REM server so a human can exercise the Configuration Viewer's risk-
REM activation workflow locally.
REM
REM THIS IS NOT A PRODUCTION LAUNCHER. It contains no Docker, no secrets,
REM no production configuration, and starts development servers only.
REM Docker deployment remains explicitly deferred to a future "Production
REM Hardening/Deployment" checkpoint.
REM
REM Checkpoint 11: the API is now authenticated (session-cookie based -
REM see docs/architecture/AUTHENTICATION_AUTHORIZATION.md). This script
REM deliberately does NOT create a default user or superuser - doing so
REM silently would mean a fixed, guessable, hard-coded credential shipped
REM in source control, defeating the point of adding authentication. If
REM no user exists yet, create one manually (see the printed instructions
REM below) after the backend server is running.
REM
REM Safe to re-run: it never overwrites an existing .env or
REM frontend/.env.local, and re-installing already-installed dependencies
REM is a fast no-op for both Poetry and npm.

echo ============================================================
echo  IntraDay - DEVELOPMENT MODE launcher (app.bat)
echo  Not for production use. No Docker.
echo ============================================================
echo.

REM --- Resolve the project root as this script's own directory, so it
REM     works regardless of where the repository is checked out (never
REM     hard-code D:\IntraDay). %~dp0 always ends with a trailing backslash.
set "PROJECT_ROOT=%~dp0"
cd /d "%PROJECT_ROOT%" || (
    echo [FAIL] Could not switch to project root: %PROJECT_ROOT%
    exit /b 1
)
echo [ OK ] Project root: %PROJECT_ROOT%

REM --- Prerequisite checks -----------------------------------------------
where python >nul 2>nul
if errorlevel 1 (
    echo [FAIL] Python was not found on PATH. Install Python 3.12+ and re-run.
    exit /b 1
)
echo [ OK ] Python found.

where poetry >nul 2>nul
if errorlevel 1 (
    echo [FAIL] Poetry was not found on PATH. Install Poetry ^(see
    echo        docs/development/LOCAL_DEVELOPMENT.md^) and re-run.
    exit /b 1
)
echo [ OK ] Poetry found.

where node >nul 2>nul
if errorlevel 1 (
    echo [FAIL] Node.js was not found on PATH. Install Node 20+ and re-run.
    exit /b 1
)
echo [ OK ] Node.js found.

where npm >nul 2>nul
if errorlevel 1 (
    echo [FAIL] npm was not found on PATH. Install Node.js ^(includes npm^) and re-run.
    exit /b 1
)
echo [ OK ] npm found.

REM --- Backend: install dependencies if the virtualenv is missing --------
if not exist "%PROJECT_ROOT%.venv\" (
    echo [ .. ] Backend virtualenv not found - running "poetry install"...
    call poetry install --no-interaction
    if errorlevel 1 (
        echo [FAIL] "poetry install" failed. See output above.
        exit /b 1
    )
) else (
    echo [ OK ] Backend virtualenv already present - skipping install.
)

REM --- Backend: create .env from the template if missing (never
REM     overwrites an existing one, and .env.example never contains real
REM     secrets - see .env.example itself).
if not exist "%PROJECT_ROOT%.env" (
    if exist "%PROJECT_ROOT%.env.example" (
        echo [ .. ] No .env found - copying .env.example as a starting point.
        copy /Y "%PROJECT_ROOT%.env.example" "%PROJECT_ROOT%.env" >nul
    )
) else (
    echo [ OK ] .env already present - leaving it untouched.
)

REM --- Frontend: install dependencies if node_modules is missing ---------
if not exist "%PROJECT_ROOT%frontend\node_modules\" (
    echo [ .. ] Frontend dependencies not found - running "npm install"...
    pushd "%PROJECT_ROOT%frontend"
    call npm install
    if errorlevel 1 (
        echo [FAIL] "npm install" failed. See output above.
        popd
        exit /b 1
    )
    popd
) else (
    echo [ OK ] Frontend dependencies already present - skipping install.
)

REM --- Frontend: create .env.local from the template if missing ----------
if not exist "%PROJECT_ROOT%frontend\.env.local" (
    if exist "%PROJECT_ROOT%frontend\.env.example" (
        echo [ .. ] No frontend\.env.local found - copying frontend\.env.example.
        copy /Y "%PROJECT_ROOT%frontend\.env.example" "%PROJECT_ROOT%frontend\.env.local" >nul
    )
) else (
    echo [ OK ] frontend\.env.local already present - leaving it untouched.
)

REM --- Backend: apply database migrations ---------------------------------
REM Checkpoint 12: a real gap found while touching this file - app.bat never
REM ran migrations at all, so a fresh database would be missing every table
REM (including this checkpoint's new AuditLogEntry). Safe to re-run:
REM `manage.py migrate` is itself idempotent - already-applied migrations
REM are skipped. Requires PostgreSQL to be reachable (POSTGRES_* in .env);
REM if it isn't, this fails with a clear Django error rather than silently
REM leaving the schema out of date.
echo [ .. ] Applying database migrations...
call poetry run python manage.py migrate --no-input
if errorlevel 1 (
    echo [FAIL] "manage.py migrate" failed. Check PostgreSQL is running and
    echo        POSTGRES_* variables in .env are correct, then re-run.
    exit /b 1
)

echo.
echo [ .. ] Starting the Django dev server (http://127.0.0.1:8000) in a new window...
start "IntraDay backend (Django dev server)" cmd /k "cd /d "%PROJECT_ROOT%" && poetry run python manage.py runserver"

echo [ .. ] Starting the Vite dev server (http://127.0.0.1:5173) in a new window...
start "IntraDay frontend (Vite dev server)" cmd /k "cd /d "%PROJECT_ROOT%frontend" && npm run dev"

echo.
echo ============================================================
echo  Backend:  http://127.0.0.1:8000  (Django dev server)
echo  Frontend: http://127.0.0.1:5173  (Vite dev server)
echo.
echo  Both servers are running in their own windows. Close those
echo  windows (or Ctrl+C inside them) to stop them.
echo.
echo  No login user exists until you create one. In the backend
echo  server window (or a new terminal, after "poetry install"),
echo  run:
echo.
echo    poetry run python manage.py createsuperuser
echo.
echo  A superuser can both read and activate configuration. To
echo  create a read-only user instead, omit --superuser and add
echo  them to the "configuration-operators" group only if they
echo  should also be able to activate:
echo.
echo    poetry run python manage.py shell -c "from django.contrib.auth.models import User, Group; u = User.objects.create_user('username', password='changeme'); u.groups.add(Group.objects.get(name='configuration-operators'))"
echo.
echo  DEVELOPMENT MODE ONLY - no Docker, not production-hardened.
echo  See docs/architecture/AUTHENTICATION_AUTHORIZATION.md for the
echo  full security model and its current limitations.
echo ============================================================

endlocal
