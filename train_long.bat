@echo off
echo ============================================
echo   GRID TACTICS TCG - Long RL Training
echo ============================================
echo.
echo Training 500,000 steps (~30-60 min)
echo Agent should learn meaningful strategies
echo.
cd /d "%~dp0"
.venv\Scripts\python.exe -c "from grid_tactics.rl.training import train_self_play; result = train_self_play(total_timesteps=500_000, eval_freq=50_000, eval_games=50, description='Long training run'); print(); print('='*50); print(f'  Run ID: {result[\"run_id\"]}'); print(f'  Final Win Rate vs Random: {result[\"final_win_rate\"]:.1%%}'); print(f'  Model: {result[\"model_path\"]}'); print(f'  Database: {result[\"db_path\"]}'); print('='*50)"
echo.
echo Press any key to close...
pause >nul
