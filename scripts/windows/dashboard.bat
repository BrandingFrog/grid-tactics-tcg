@echo off
set "ROOT=%~dp0..\.."
echo ============================================
echo   Grid Tactics TCG - Web Dashboard
echo   Press Ctrl+C to stop
echo ============================================
cd /d "%ROOT%"
start "" /b "%ROOT%\.venv\Scripts\python.exe" "%ROOT%\scripts\dashboard.py"
timeout /t 2 /nobreak >nul
start http://localhost:5000
echo   Dashboard running at http://localhost:5000
echo   Waiting for server... (press Ctrl+C to stop)
pause >nul
