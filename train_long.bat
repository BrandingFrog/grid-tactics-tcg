@echo off
echo ============================================
echo   GRID TACTICS TCG - Long RL Training
echo   GPU: RTX 4060 / 8 parallel envs
echo ============================================
echo.
echo Training 2,000,000 steps (~30-60 min with GPU)
echo Agent should learn meaningful strategies
echo.
cd /d "%~dp0"
.venv\Scripts\python.exe -c "from grid_tactics.rl.training import train_self_play; result = train_self_play(total_timesteps=2_000_000, eval_freq=100_000, eval_games=50, n_envs=8, device='cuda', description='Long GPU training (8 envs, 2M steps)'); print(); print('='*50); print(f'  Run ID: {result[\"run_id\"]}'); print(f'  Final Win Rate vs Random: {result[\"final_win_rate\"]:.1%%}'); print(f'  Model: {result[\"model_path\"]}'); print(f'  Database: {result[\"db_path\"]}'); print('='*50)"
echo.
echo Press any key to close...
pause >nul
