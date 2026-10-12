@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Install the project Python environment first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -B configure-lan.py --port 8003
if errorlevel 1 (
    echo Right-click allow-lan.cmd and choose Run as administrator, then retry.
)
pause
