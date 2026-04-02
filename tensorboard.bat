@echo off
echo ============================================
echo   Opening TensorBoard (loss curves, rewards)
echo   Open http://localhost:6006 in your browser
echo   Press Ctrl+C to stop
echo ============================================
cd /d "%~dp0"
.venv\Scripts\tensorboard.exe --logdir data/tb_logs
