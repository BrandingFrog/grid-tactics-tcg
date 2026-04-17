"""Action serialization codec -- JSON wire transport for Action dataclass.

Converts between grid_tactics.actions.Action and JSON-compatible dicts
for Socket.IO transport.

Usage:
    data = serialize_action(action)      # Action -> dict (for JSON)
    action = reconstruct_action(data)    # dict -> Action (from JSON)
"""

from __future__ import annotations

from grid_tactics.actions import Action
from grid_tactics.enums import ActionType


def serialize_action(action: Action) -> dict:
    """Serialize an Action to a JSON-compatible dict.

    - action_type is always included (as int)
    - None-valued optional fields are omitted (compact JSON)
    - Tuple positions are converted to lists for JSON compatibility

    Args:
        action: The Action to serialize.

    Returns:
        Dict suitable for JSON serialization.
    """
    result: dict = {"action_type": int(action.action_type)}

    if action.card_index is not None:
        result["card_index"] = action.card_index

    if action.position is not None:
        result["position"] = list(action.position)

    if action.minion_id is not None:
        result["minion_id"] = action.minion_id

    if action.target_id is not None:
        result["target_id"] = action.target_id

    if action.target_pos is not None:
        result["target_pos"] = list(action.target_pos)

    if action.discard_card_index is not None:
        result["discard_card_index"] = action.discard_card_index

    if action.transform_target is not None:
        result["transform_target"] = action.transform_target

    if action.sacrifice_minion_id is not None:
        result["sacrifice_minion_id"] = action.sacrifice_minion_id

    return result


def reconstruct_action(data) -> Action:
    """Reconstruct an Action from a JSON-parsed dict.

    - Validates data is a dict with 'action_type' key
    - Converts list positions back to tuples
    - Raises ValueError on invalid input

    Args:
        data: Dict from JSON parsing (e.g., from Socket.IO message).

    Returns:
        Frozen Action dataclass.

    Raises:
        ValueError: If data is not a dict, or missing action_type,
                    or contains invalid values.
    """
    if not isinstance(data, dict):
        raise ValueError(
            f"Expected dict, got {type(data).__name__}"
        )

    if "action_type" not in data:
        raise ValueError(
            "Missing required field 'action_type'"
        )

    try:
        action_type = ActionType(data["action_type"])

        card_index = data.get("card_index")
        minion_id = data.get("minion_id")
        target_id = data.get("target_id")

        position = data.get("position")
        if position is not None:
            position = tuple(position)

        target_pos = data.get("target_pos")
        if target_pos is not None:
            target_pos = tuple(target_pos)

        discard_card_index = data.get("discard_card_index")
        transform_target = data.get("transform_target")
        sacrifice_minion_id = data.get("sacrifice_minion_id")

        return Action(
            action_type=action_type,
            card_index=card_index,
            position=position,
            minion_id=minion_id,
            target_id=target_id,
            target_pos=target_pos,
            discard_card_index=discard_card_index,
            transform_target=transform_target,
            sacrifice_minion_id=sacrifice_minion_id,
        )
    except (KeyError, TypeError) as e:
        raise ValueError(f"Invalid action data: {e}") from e
