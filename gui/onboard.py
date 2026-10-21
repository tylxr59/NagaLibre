"""Translate editable side-button actions into the Naga's keyboard records."""
import os
from pathlib import Path
import re

from model import DEVICE_MODELS, key_code, shortcut, save_profile

MODIFIERS = dict(zip(
    ("KEY_LEFTCTRL", "KEY_LEFTSHIFT", "KEY_LEFTALT", "KEY_LEFTMETA", "KEY_RIGHTCTRL", "KEY_RIGHTSHIFT", "KEY_RIGHTALT", "KEY_RIGHTMETA"),
    (1, 2, 4, 8, 16, 32, 64, 128),
))
HID_KEYS = {f"KEY_{chr(65+i)}": 4+i for i in range(26)}
HID_KEYS.update({f"KEY_{i}": 0x1d+i for i in range(1, 10)})
HID_KEYS.update({f"KEY_F{i}": 0x39+i for i in range(1, 13)})
HID_KEYS.update({f"KEY_F{i}": 0x5b+i for i in range(13, 25)})
HID_KEYS.update(dict(zip(
    ("KEY_0", "KEY_ENTER", "KEY_ESC", "KEY_BACKSPACE", "KEY_TAB", "KEY_SPACE", "KEY_MINUS", "KEY_EQUAL", "KEY_LEFTBRACE", "KEY_RIGHTBRACE", "KEY_BACKSLASH", "KEY_SEMICOLON", "KEY_APOSTROPHE", "KEY_GRAVE", "KEY_COMMA", "KEY_DOT", "KEY_SLASH", "KEY_CAPSLOCK"),
    (0x27, 0x28, 0x29, 0x2a, 0x2b, 0x2c, 0x2d, 0x2e, 0x2f, 0x30, 0x31, 0x33, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39),
)))
HID_KEYS.update(dict(zip(
    ("KEY_SYSRQ", "KEY_SCROLLLOCK", "KEY_PAUSE", "KEY_INSERT", "KEY_HOME", "KEY_PAGEUP", "KEY_DELETE", "KEY_END", "KEY_PAGEDOWN", "KEY_RIGHT", "KEY_LEFT", "KEY_DOWN", "KEY_UP", "KEY_NUMLOCK", "KEY_KPSLASH", "KEY_KPASTERISK", "KEY_KPMINUS", "KEY_KPPLUS", "KEY_KPENTER"),
    range(0x46, 0x59),
)))
HID_KEYS.update({f"KEY_KP{i}": 0x58+i for i in range(1, 10)})
HID_KEYS.update({"KEY_KP0": 0x62, "KEY_KPDOT": 0x63, "KEY_102ND": 0x64, "KEY_COMPOSE": 0x65, "KEY_KPEQUAL": 0x67})
MOUSE_KEYS = {"BTN_LEFT": 1, "BTN_RIGHT": 2, "BTN_MIDDLE": 3, "BTN_SIDE": 4, "BTN_BACK": 4, "BTN_EXTRA": 5, "BTN_FORWARD": 5}
FACTORY_CONTROL_LABELS = tuple(c["default_label"] for c in DEVICE_MODELS["naga_v2_pro"]["defaults"]["controls"])


def keyboard_action(keys):
    modifiers = 0
    usages = []
    for key in keys:
        if key in MODIFIERS:
            modifiers |= MODIFIERS[key]
        elif key in HID_KEYS:
            usages.append(HID_KEYS[key])
        else:
            raise ValueError(f"{key} is not supported in mouse memory yet. Use a standard keyboard key or shortcut.")
    if len(usages) > 1:
        raise ValueError("An onboard shortcut supports modifiers and one main key. Multi-key sequences need the software engine for now.")
    if not usages and not modifiers:
        raise ValueError("No keyboard action selected.")
    return {"category": 2, "data": [modifiers, usages[0] if usages else 0]}


def hardware_buttons(profile):
    if profile["plate"] != "12":
        raise ValueError("Mouse-memory support currently covers the verified 12-button plate. Other plates can use software mode.")
    buttons = profile["plates"]["12"]
    if len(buttons) != 12:
        raise ValueError("The 12-button profile is incomplete.")
    result = []
    for i, button in enumerate(buttons):
        mode = button["mode"]
        if mode == "default":
            defaults = DEVICE_MODELS[profile.get("device", "naga_v2_pro")]["defaults"]["plates"]["12"]["bindings"]
            if len(defaults) != 12:
                raise ValueError("No verified onboard defaults for this model.")
            action = {"category": defaults[i]["category"], "data": list(defaults[i]["data"])}
        elif mode == "disabled":
            action = {"category": 0, "data": []}
        elif mode in ("keep", "hypershift"):
            raise ValueError("This draft needs the wired paired-layer save path. Connect by USB to preserve stored grid actions or assign Hypershift.")
        elif mode == "key":
            code = key_code(button["value"])
            action = {"category": 1, "data": [MOUSE_KEYS[code]]} if code in MOUSE_KEYS else keyboard_action([code])
        elif mode == "shortcut":
            action = keyboard_action(shortcut(button["value"]))
        else:
            raise ValueError(f"Button {i+1} is a sequence. Choose Macro in Customize for a journaled upload, or software mode for helper playback.")
        result.append({"button": i+1, **action})
    return result


def hardware_controls(profile):
    result = []
    definitions = DEVICE_MODELS[profile.get("device", "naga_v2_pro")]["defaults"]["controls"]
    for index, button in enumerate(profile.get("controls", [])):
        mode = button["mode"]
        if mode in ("default", "keep"):
            continue  # Preserve exact stored action, including firmware functions.
        if mode == "factory":
            binding = definitions[index]["binding"]
            action = {"category": binding["category"], "data": list(binding["data"])}
        elif mode == "disabled":
            action = {"category": 0, "data": []}
        elif mode == "hypershift":
            raise ValueError("Hypershift assignments require the wired paired-layer save path.")
        elif mode == "key":
            code = key_code(button["value"])
            action = {"category": 1, "data": [MOUSE_KEYS[code]]} if code in MOUSE_KEYS else keyboard_action([code])
        elif mode == "shortcut":
            action = keyboard_action(shortcut(button["value"]))
        else:
            raise ValueError("Choose Macro on the control in Customize to upload a saved sequence.")
        result.append({"button": definitions[index]["button"], **action})
    return result


def write_backup(profile_path: Path, snapshot: dict, token: str) -> Path:
    serial = re.sub(r"[^A-Za-z0-9_-]", "_", snapshot["device"]["serial"])
    if not token.isdecimal() or len(token) > 40:
        raise ValueError("Invalid hardware backup token.")
    path = profile_path.parent / "backups" / f"{serial}-slot-{snapshot['slot']}-{token}.json"
    save_profile(path, snapshot)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return path


def write_creation_backup(profile_path: Path, plan: dict, token: str) -> Path:
    if not token.isdecimal() or len(token) > 40:
        raise ValueError("Invalid hardware backup token.")
    snapshots = plan["snapshots"]
    if plan["format"] != 1 or not snapshots or plan["target"] in snapshots[0]["slots"]:
        raise ValueError("Invalid slot creation backup.")
    serial = re.sub(r"[^A-Za-z0-9_-]", "_", snapshots[0]["device"]["serial"])
    path = profile_path.parent / "backups" / f"{serial}-create-slot-{plan['target']}-{token}.json"
    save_profile(path, plan)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return path


def stored_label(record):
    """Describe an actual firmware record without guessing unknown categories."""
    category, data = record.get("category"), record.get("data", [])
    if category in (3, 4, 5, 15) and len(data) == (3 if category == 3 else 2):
        macro_id = (data[0] << 8) | data[1]
        playback = f"{data[2]} time(s)" if category == 3 else {4: "while held", 5: "toggle", 15: "sequence"}[category]
        return f"Macro {macro_id:04x} · {playback}"
    if category == 12 and data == [1]:
        return "Hold for Hypershift"
    if category == 0 and not data:
        return "Disabled"
    if category == 1 and len(data) == 1:
        return {1: "Left click", 2: "Right click", 3: "Middle click", 4: "Back", 5: "Forward", 9: "Scroll up", 10: "Scroll down", 0x68: "Scroll left", 0x69: "Scroll right"}.get(data[0], f"Mouse {data[0]}")
    if category == 18 and data == [4]:
        return "Cycle wheel modes"
    if category == 6 and data == [6]:
        return "Cycle DPI stages"
    if category == 2 and len(data) == 2:
        from model import display_key
        names = {1: "Ctrl", 2: "Shift", 4: "Alt", 8: "Super", 16: "Right Ctrl", 32: "Right Shift", 64: "Right Alt", 128: "Right Super"}
        parts = [name for bit, name in names.items() if data[0] & bit]
        key = next((key for key, usage in HID_KEYS.items() if usage == data[1]), None)
        if data[1]:
            parts.append(display_key(key) if key else f"HID {data[1]:02x}")
        return "+".join(parts) or "No key"
    return f"Action {category:02x}: " + bytes(data).hex()


def layer_edits(profile):
    """Translate sparse paired drafts; never manufacture unknown stored actions."""
    if profile.get("device", "naga_v2_pro") != "naga_v2_pro" or profile["plate"] != "12":
        raise ValueError("Hypershift editing requires the Naga V2 Pro twelve-button plate.")
    normal = profile["plates"]["12"] + profile.get("controls", [])
    secondary = profile.get("hypershift", [])
    if len(normal) != 16 or len(secondary) != 16:
        raise ValueError("Both layer drafts must contain all sixteen controls.")
    result = []
    for layer, buttons in enumerate((normal, secondary)):
        for index, button in enumerate(buttons):
            mode = button["mode"]
            if mode == "keep" or (layer == 0 and index >= 12 and mode == "default"):
                continue
            if mode in ("default", "factory") and layer == 0:
                binding = (DEVICE_MODELS["naga_v2_pro"]["defaults"]["plates"]["12"]["bindings"][index]
                           if index < 12 else DEVICE_MODELS["naga_v2_pro"]["defaults"]["controls"][index-12]["binding"])
                action = {"category": binding["category"], "data": list(binding["data"])}
            elif mode == "hypershift" and layer == 0:
                action = {"category": 12, "data": [1]}
            elif mode == "disabled":
                action = {"category": 0, "data": []}
            elif mode == "key":
                code = key_code(button["value"])
                action = {"category": 1, "data": [MOUSE_KEYS[code]]} if code in MOUSE_KEYS else keyboard_action([code])
            elif mode == "shortcut":
                action = keyboard_action(shortcut(button["value"]))
            else:
                raise ValueError("Layers support keys, shortcuts, disabled actions and a normal-layer Hypershift trigger; macros and nested triggers are unsupported.")
            result.append({"layer": layer, "action": {"button": index+1, **action}})
    return result


def draft_from_record(record, secondary=False):
    """Known actions become editable; everything else stays explicitly preserved."""
    from model import keep_binding
    draft = keep_binding()
    category, data = record["category"], record["data"]
    if category == 12 and data == [1] and not secondary:
        draft["mode"] = "hypershift"
    elif category == 0 and data == []:
        draft["mode"] = "disabled"
    elif category == 1 and len(data) == 1 and 1 <= data[0] <= 5:
        draft.update(mode="key", value=next(k for k, v in MOUSE_KEYS.items() if v == data[0]))
    elif category == 2 and len(data) == 2:
        keys = [key for key, mask in MODIFIERS.items() if data[0] & mask]
        key = next((key for key, usage in HID_KEYS.items() if usage == data[1]), None)
        if data[1] and key is None:
            return draft
        if key:
            keys.append(key)
        if keys:
            draft.update(mode="key" if len(keys) == 1 else "shortcut", value="+".join(keys))
    if not secondary and record["button"] >= 13:
        if draft["mode"] == "keep":
            draft["mode"] = "default"
        definition = DEVICE_MODELS["naga_v2_pro"]["defaults"]["controls"][record["button"]-13]
        if category == definition["binding"]["category"] and data == definition["binding"]["data"]:
            draft["mode"] = "factory"
    return draft


def write_layer_backup(profile_path, backup, token):
    if backup.get("format") != 1 or backup.get("kind") != "paired_mapping_backup" or not backup.get("slots"):
        raise ValueError("Invalid paired mapping backup.")
    if not token.isdecimal() or len(token) > 40:
        raise ValueError("Invalid hardware backup token.")
    first = backup["slots"][0]["state"]["normal"]
    serial = re.sub(r"[^A-Za-z0-9_-]", "_", first["device"]["serial"])
    path = profile_path.parent / "backups" / f"{serial}-both-layers-{token}.json"
    save_profile(path, backup)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return path
