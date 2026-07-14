# Windows launchers

These batch files are convenience wrappers for local development. They resolve the repository root from their own location, so they can be launched from Explorer or any working directory.

- `dashboard.bat` starts the local training dashboard.
- `play.bat` starts the terminal AI-game viewer.
- `stats.bat` prints training statistics.
- `tensorboard.bat` opens TensorBoard for `data/tb_logs/`.
- `train.bat` and `train_long.bat` run local training presets.

Create the root `.venv` and install the relevant development/RL dependencies before using them.
