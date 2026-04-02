"""SQLite data persistence layer for game results and training metadata.

Provides:
  - ensure_schema: Create/upgrade the SQLite database schema
  - GameResultWriter: Buffered batch writer for game results
  - TrainingRunWriter: Training run lifecycle management
  - GameResultReader: Dashboard-ready query interface (Plan 06-01 Task 2)
"""

from grid_tactics.db.reader import GameResultReader
from grid_tactics.db.schema import ensure_schema
from grid_tactics.db.writer import GameResultWriter, TrainingRunWriter

__all__ = [
    "ensure_schema",
    "GameResultReader",
    "GameResultWriter",
    "TrainingRunWriter",
]
