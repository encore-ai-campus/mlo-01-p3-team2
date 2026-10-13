@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Python environment not found. Follow the setup steps in RUN_GUIDE.md.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" run-split.py
if errorlevel 1 pause
