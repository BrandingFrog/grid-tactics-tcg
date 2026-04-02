@echo off
echo ============================================
echo   GRID TACTICS TCG - RL Training
echo ============================================
echo.
echo This will train an RL agent using MaskablePPO
echo with self-play. Results saved to data/training.db
echo.
echo Training 50,000 steps (quick demo ~5-10 min)
echo For better results, use train_long.bat (500K steps)
echo.
cd /d "%~dp0"
.venv\Scripts\python.exe -c "from grid_tactics.rl.training import train_self_play; result = train_self_play(total_timesteps=50_000, eval_freq=10_000, eval_games=30, description='Quick training run'); print(); print('='*50); print(f'  Run ID: {result[\"run_id\"]}'); print(f'  Final Win Rate vs Random: {result[\"final_win_rate\"]:.1%%}'); print(f'  Model: {result[\"model_path\"]}'); print(f'  Database: {result[\"db_path\"]}'); print('='*50)"
echo.
echo Press any key to close...
pause >nul
