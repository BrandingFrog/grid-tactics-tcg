@echo off
echo ============================================
echo   Grid Tactics TCG - Web Dashboard
echo   Press Ctrl+C to stop
echo ============================================
cd /d "%~dp0"
start "" /b .venv\Scripts\python.exe dashboard.py
timeout /t 2 /nobreak >nul
start http://localhost:5000
echo   Dashboard running at http://localhost:5000
echo   Waiting for server... (press Ctrl+C to stop)
pause >nul
