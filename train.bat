@echo off
echo ============================================
echo   GRID TACTICS TCG - RL Training
echo   GPU: RTX 4060 / 8 parallel envs
echo ============================================
echo.
echo Training 100,000 steps (quick demo ~5 min)
echo.
cd /d "%~dp0"
.venv\Scripts\python.exe -c "from grid_tactics.rl.training import train_self_play; result = train_self_play(total_timesteps=100_000, eval_freq=20_000, eval_games=30, n_envs=8, device='cuda', description='Quick GPU training (8 envs)'); print(); print('='*50); print(f'  Run ID: {result[\"run_id\"]}'); print(f'  Final Win Rate vs Random: {result[\"final_win_rate\"]:.1%%}'); print(f'  Model: {result[\"model_path\"]}'); print(f'  Database: {result[\"db_path\"]}'); print('='*50)"
echo.
echo Press any key to close...
pause >nul
