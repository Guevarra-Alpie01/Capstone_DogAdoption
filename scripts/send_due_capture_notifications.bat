@echo off
setlocal

REM Change to project root (this script assumes it lives in scripts\)
cd /d "%~dp0\.."

REM Run the SMS scheduler using the venv Python
".\venv\Scripts\python.exe" manage.py send_due_capture_notifications

endlocal
