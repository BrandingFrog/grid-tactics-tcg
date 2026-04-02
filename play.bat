@echo off
cd /d "%~dp0"
.venv\Scripts\python.exe watch_game.py 42 0.4
echo.
echo Press any key to close...
pause >nul
