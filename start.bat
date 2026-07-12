@echo off
REM ============================================================
REM  WhatsApp Export Viewer - Windows one-click launcher
REM  Double-click this file to start the panel.
REM ============================================================
setlocal
cd /d "%~dp0backend"

where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo [ERROR] Python was not found on your PATH.
  echo Install Python 3.10+ from https://www.python.org/downloads/
  echo and make sure you tick "Add python.exe to PATH" during setup.
  echo.
  pause
  exit /b 1
)

if not exist ".venv" (
  echo First run: creating virtual environment...
  python -m venv .venv
)

REM Always install/update dependencies (fast when already satisfied). This also
REM repairs an existing .venv after a requirements change, e.g. the SQLAlchemy
REM upgrade needed for Python 3.13/3.14.
echo Installing/updating dependencies...
call ".venv\Scripts\python.exe" -m pip install --upgrade pip
call ".venv\Scripts\python.exe" -m pip install -r requirements.txt

echo.
echo ============================================================
echo   WhatsApp Export Viewer is starting.
echo   Open your browser at:   http://localhost:8000
echo   (Leave this window open. Press Ctrl+C to stop.)
echo ============================================================
echo.

REM Open the browser a few seconds after the server starts.
start "" /min cmd /c "timeout /t 4 >nul & start """" http://localhost:8000"

".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --timeout-keep-alive 300
pause
