-- Grid Tactics Training Database Schema
-- Run this in Supabase SQL Editor after creating your project

-- Training runs (one per pod launch)
CREATE TABLE training_runs (
  run_id TEXT PRIMARY KEY,
  run_name TEXT,
  started_at TIMESTAMPTZ DEFAULT NOW(),
  ended_at TIMESTAMPTZ,
  total_timesteps BIGINT,
  current_steps BIGINT DEFAULT 0,
  current_fps REAL DEFAULT 0,
  gpu_name TEXT,
  gpu_util REAL DEFAULT 0,
  method TEXT DEFAULT 'default',
  seed INTEGER,
  n_envs INTEGER,
  n_steps INTEGER,
  batch_size INTEGER,
  hyperparameters JSONB DEFAULT '{}',
  model_path TEXT,
  final_win_rate REAL,
  pod_id TEXT,
  cost_per_hr REAL DEFAULT 0
);

-- Evaluation snapshots (written every EVAL_FREQ steps)
CREATE TABLE training_snapshots (
  id BIGSERIAL PRIMARY KEY,
  run_id TEXT REFERENCES training_runs(run_id),
  timestep BIGINT NOT NULL,
  win_rate REAL,
  pg_loss REAL,
  v_loss REAL,
  entropy REAL,
  fps REAL,
  gpu_util REAL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Game results (optional, for detailed analysis)
CREATE TABLE game_results (
  id BIGSERIAL PRIMARY KEY,
  run_id TEXT REFERENCES training_runs(run_id),
  episode_num INTEGER,
  winner INTEGER,
  turn_count INTEGER,
  p1_hp INTEGER,
  p2_hp INTEGER,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Card balance stats (aggregated per run)
CREATE TABLE card_stats (
  id BIGSERIAL PRIMARY KEY,
  run_id TEXT REFERENCES training_runs(run_id),
  card_id TEXT,
  times_played BIGINT DEFAULT 0,
  win_rate REAL,
  avg_damage REAL,
  pick_rate REAL,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Future: player accounts
CREATE TABLE players (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  username TEXT UNIQUE,
  email TEXT UNIQUE,
  rating INTEGER DEFAULT 1000,
  games_played INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for dashboard queries
CREATE INDEX idx_snapshots_run ON training_snapshots(run_id);
CREATE INDEX idx_snapshots_timestep ON training_snapshots(run_id, timestep);
CREATE INDEX idx_runs_active ON training_runs(ended_at) WHERE ended_at IS NULL;
CREATE INDEX idx_game_results_run ON game_results(run_id);

-- Enable realtime for live dashboard
ALTER PUBLICATION supabase_realtime ADD TABLE training_snapshots;
ALTER PUBLICATION supabase_realtime ADD TABLE training_runs;

-- Row Level Security (allow public read, authenticated write)
ALTER TABLE training_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE training_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE game_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE card_stats ENABLE ROW LEVEL SECURITY;

-- Public read access for dashboard
CREATE POLICY "Public read" ON training_runs FOR SELECT USING (true);
CREATE POLICY "Public read" ON training_snapshots FOR SELECT USING (true);
CREATE POLICY "Public read" ON game_results FOR SELECT USING (true);
CREATE POLICY "Public read" ON card_stats FOR SELECT USING (true);

-- Service role write (pods use service key)
CREATE POLICY "Service write" ON training_runs FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Service write" ON training_snapshots FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Service write" ON game_results FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Service write" ON card_stats FOR ALL USING (true) WITH CHECK (true);
