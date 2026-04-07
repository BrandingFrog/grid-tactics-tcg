# Tensor Engine

PyTorch batched implementation under `src/grid_tactics/tensor_engine/`. Runs N games simultaneously on GPU at 100K+ FPS.

## Contract
- Mutating tensors (not immutable).
- `step_batch(actions: Tensor)` resolves all N games in parallel.
- Must maintain **rule parity** with the Python [[Game Engine (Python)]] — verified by tests.

## Used By
- [[RL Training]]
- `tensor_train.py`

## Parity Phases
- [[../Phases/v1.1/Phase 14.1 Melee Move-and-Attack]] — pending_attack parity
- [[../Phases/v1.1/Phase 14.2 Tutor Choice Prompt]] — pending_tutor parity
