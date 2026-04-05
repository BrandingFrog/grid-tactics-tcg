"""Per-game state management mapping session tokens to player slots."""
import threading

from grid_tactics.card_library import CardLibrary
from grid_tactics.game_state import GameState
from grid_tactics.rng import GameRNG


class GameSession:
    """Holds a live game's state and maps session tokens to player indices."""

    def __init__(
        self,
        state: GameState,
        rng: GameRNG,
        library: CardLibrary,
        player_tokens: tuple[str, str],   # (p0_token, p1_token)
        player_names: tuple[str, str],     # (p0_name, p1_name)
        player_sids: list[str | None],     # [p0_sid, p1_sid] -- mutable for reconnect
    ):
        self.state = state
        self.rng = rng
        self.library = library
        self.player_tokens = player_tokens
        self.player_names = player_names
        self.player_sids = player_sids
        self.lock = threading.Lock()

    def get_player_idx(self, token: str) -> int | None:
        """Return 0 or 1 for the player index, or None if token not in game."""
        if token == self.player_tokens[0]:
            return 0
        elif token == self.player_tokens[1]:
            return 1
        return None

    def update_sid(self, token: str, new_sid: str) -> None:
        """Update socket ID for a player (used on reconnect)."""
        idx = self.get_player_idx(token)
        if idx is not None:
            self.player_sids[idx] = new_sid
