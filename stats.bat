@echo off
cd /d "%~dp0"
.venv\Scripts\python.exe stats.py
echo.
echo Press any key to close...
pause >nul
