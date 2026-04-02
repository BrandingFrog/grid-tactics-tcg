"""Action space encoder -- stub for TDD RED phase."""

ACTION_SPACE_SIZE = 1262


class ActionEncoder:
    def encode(self, action, state):
        raise NotImplementedError("TDD RED: not yet implemented")

    def decode(self, action_int, state, library):
        raise NotImplementedError("TDD RED: not yet implemented")


def build_action_mask(state, library, encoder):
    raise NotImplementedError("TDD RED: not yet implemented")
