@echo off
set "ROOT=%~dp0..\.."
cd /d "%ROOT%"
"%ROOT%\.venv\Scripts\python.exe" "%ROOT%\scripts\stats.py"
echo.
echo Press any key to close...
pause >nul
