"""Device167 native action names; static evidence is in inspection/NATIVE_ACTIONS.md."""
import json
from pathlib import Path

NATIVE_ACTIONS = json.loads((Path(__file__).resolve().parent.parent / "devices/native-actions.json").read_text())
BY_ID = {action["id"]: action for action in NATIVE_ACTIONS}


def native_action(value):
    try:
        action = BY_ID[value]
    except (KeyError, TypeError):
        raise ValueError("Choose a supported media or scrolling action.") from None
    return {"category": action["category"], "data": list(action["data"])}


def native_id(category, data):
    return next((action["id"] for action in NATIVE_ACTIONS
                 if action["category"] == category and action["data"] == data), None)


def researched_label(category, data):
    """Recognize exact decoded shapes without normalizing preserved wire bytes."""
    action_id = native_id(category, data)
    if action_id:
        return BY_ID[action_id]["label"]
    if category == 6:
        if len(data) == 1:
            return {1: "DPI up", 2: "DPI down", 6: "Cycle DPI stages", 7: "Cycle DPI stages down"}.get(data[0])
        if len(data) == 2 and data[0] == 3:
            return f"DPI stage selector {data[1]}"
        if len(data) == 5 and data[0] == 5:
            x, y = (data[1] << 8) | data[2], (data[3] << 8) | data[4]
            return f"Temporary DPI · X {x}, Y {y} (release unverified)"
    if category == 7 and len(data) == 1:
        return {1: "Previous onboard profile", 2: "Next onboard profile",
                4: "Cycle onboard profiles up", 5: "Cycle onboard profiles down"}.get(data[0])
    return None
