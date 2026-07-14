@echo off
set "ROOT=%~dp0..\.."
cd /d "%ROOT%"
"%ROOT%\.venv\Scripts\python.exe" "%ROOT%\scripts\watch_game.py" 42 0.4
echo.
echo Press any key to close...
pause >nul
