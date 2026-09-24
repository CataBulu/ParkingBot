@echo off
REM Starts the dashboard backend (Starlette, :8765) and frontend (Vite dev server, :5173)
REM in two separate windows. Close a window (or press Ctrl+C in it) to stop that server.
setlocal
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"
set "FRONTEND=%~dp0dashboard\frontend"

if not exist "%PY%" (
    echo Creating Python environment (.venv^)...
    python -m venv "%~dp0.venv" || goto :error
    "%PY%" -m pip install -q -r "%~dp0dashboard\backend\requirements.txt" || goto :error
)

if not exist "%FRONTEND%\node_modules" (
    echo Installing frontend dependencies...
    pushd "%FRONTEND%"
    call npm install --silent || (popd & goto :error)
    popd
)

start "Parking Bot - backend" cmd /k ""%PY%" "%~dp0dashboard\backend\app.py""
start "Parking Bot - frontend" /d "%FRONTEND%" cmd /k "npm run dev -- --port 5173 --strictPort"

echo.
echo Backend:  http://127.0.0.1:8765
echo Frontend: http://localhost:5173  (open this one - hot reload)
timeout /t 4 /nobreak >nul
start "" http://localhost:5173
exit /b 0

:error
echo [ERROR] Setup failed - see the messages above.
pause
exit /b 1
