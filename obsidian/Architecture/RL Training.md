# RL Training

## Strategy
- **MaskablePPO** (sb3-contrib) for the Gymnasium-wrapped Python env.
- **Custom tensor PPO loop** in `tensor_train.py` for high-throughput GPU training (bypasses SB3 rollout collection).

## Pipeline
1. Tensor engine collects N parallel rollouts on GPU.
2. Legal action mask gates the policy.
3. PPO gradient updates.
4. Snapshots + game results stream to [[Deployment|Supabase]].

## Files
- `src/grid_tactics/rl/`
- `tensor_train.py`, `cloud_train.py`
- `manage_pods.py`, `deploy_runpod.py`

## Phases
- [[../Phases/v1.0/Phase 05 RL Environment Interface]]
- [[../Phases/v1.0/Phase 06 RL Training Pipeline]]
