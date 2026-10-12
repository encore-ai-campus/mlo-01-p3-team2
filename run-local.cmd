@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Python environment not found. Follow the setup steps in RUN_GUIDE.md.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" manage.py migrate --noinput
if errorlevel 1 (
    pause
    exit /b 1
)
".venv\Scripts\python.exe" run-campus.py --port 8003
if errorlevel 1 pause
