"""Profiles and config conversion, kept independent of Qt for testing."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
from native_actions import BY_ID, native_action

DEVICE_MODELS = {m["id"]: m for m in json.loads((Path(__file__).resolve().parent.parent / "devices/models.json").read_text())}
DEFAULT_KEYS = DEVICE_MODELS["naga_v2_pro"]["defaults"]["plates"]["12"]["keys"]
CONTROL_NAMES = tuple(c["name"] for c in DEVICE_MODELS["naga_v2_pro"]["defaults"]["controls"])


def default_control(factory=False):
    return {"trigger": "", "mode": "factory" if factory else "default", "value": "", "steps": []}
PROTECTED_INPUTS = frozenset(("BTN_LEFT", "BTN_RIGHT", "BTN_MIDDLE", "BTN_MOUSE"))
SYMBOLS = {"KEY_MINUS": "-", "KEY_EQUAL": "="}
ALIASES = {
    "CTRL": "LEFTCTRL", "CONTROL": "LEFTCTRL", "ALT": "LEFTALT",
    "SHIFT": "LEFTSHIFT", "META": "LEFTMETA", "SUPER": "LEFTMETA", "WIN": "LEFTMETA",
    "ESC": "ESC", "ESCAPE": "ESC", "RETURN": "ENTER", "SPACE": "SPACE",
    "PGUP": "PAGEUP", "PGDOWN": "PAGEDOWN", "DEL": "DELETE", "INS": "INSERT",
    "BACKTAB": "TAB", "-": "MINUS", "=": "EQUAL", ",": "COMMA", ".": "DOT",
    "/": "SLASH", ";": "SEMICOLON", "'": "APOSTROPHE", "[": "LEFTBRACE",
    "]": "RIGHTBRACE", "\\": "BACKSLASH", "`": "GRAVE",
}


def key_code(text: str) -> str:
    text = text.strip().upper()
    if not text:
        raise ValueError("Enter a key or shortcut first.")
    if text.startswith(("KEY_", "BTN_")):
        code = text
    else:
        code = "KEY_" + ALIASES.get(text, text.replace(" ", ""))
    if not re.fullmatch(r"(?:KEY|BTN)_[A-Z0-9_]+", code):
        raise ValueError(f"Unrecognized key: {text}")
    return code


def shortcut(text: str) -> list[str]:
    keys = [key_code(part) for part in text.split("+")]
    if len(set(keys)) != len(keys):
        raise ValueError("A shortcut cannot contain the same key twice.")
    return keys


def display_key(code: str) -> str:
    return SYMBOLS.get(code, code.removeprefix("KEY_").replace("LEFTCTRL", "Ctrl").replace("LEFTSHIFT", "Shift").replace("LEFTALT", "Alt").replace("LEFTMETA", "Super"))


def default_button(index: int, plate: str, device="naga_v2_pro") -> dict:
    return {"trigger": DEVICE_MODELS[device]["defaults"]["plates"][plate]["keys"][index], "mode": "default", "value": "", "steps": []}


def keep_binding():
    return {"trigger": "", "mode": "keep", "value": "", "steps": []}


def new_profile(device="naga_v2_pro") -> dict:
    layouts = DEVICE_MODELS[device]["plates"]
    profile = {"version": 1, "plate": layouts[0], "plates": {p: [default_button(i, p, device) for i in range(int(p))] for p in layouts}}
    if device != "naga_v2_pro":
        profile.update(device=device, storage="software")
        for buttons in profile["plates"].values():
            for button in buttons:
                button["trigger"] = ""
    if device == "naga_v2_pro":
        profile.update(version=2, controls=[default_control() for _ in CONTROL_NAMES],
                       hypershift=[keep_binding() for _ in range(16)])
    return profile


def config_path() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "NagaLibre" / "profiles.json"


def load_profile(path: Path, device="naga_v2_pro") -> dict:
    if not path.exists():
        return new_profile(device)
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("Profile must contain an object.")
    if value.get("device", "naga_v2_pro") != device:
        raise ValueError("This profile belongs to another mouse model.")
    layouts = DEVICE_MODELS[device]["plates"]
    if value.get("version") not in (1, 2) or value.get("plate") not in layouts:
        raise ValueError("Unsupported profile format; the file was left untouched.")
    for plate in layouts:
        buttons = value["plates"][plate]
        if len(buttons) != int(plate):
            raise ValueError(f"Invalid {plate}-button profile.")
        for button in buttons:
            if not isinstance(button, dict):
                raise ValueError("Invalid button data.")
            if button["mode"] not in ("default", "key", "shortcut", "macro", "keep", "disabled", "hypershift", "native"):
                raise ValueError("Unknown binding type.")
            if button["mode"] == "native":
                if device != "naga_v2_pro" or plate != "12":
                    raise ValueError("Native actions require the Naga V2 Pro twelve-button plate.")
                native_action(button.get("value"))
            if button["mode"] == "hypershift" and (device != "naga_v2_pro" or plate != "12"):
                raise ValueError("Hypershift triggers require the Naga V2 Pro twelve-button plate.")
            if not isinstance(button["trigger"], str) or not isinstance(button["value"], str) or not isinstance(button["steps"], list):
                raise ValueError("Invalid button data.")
            for step in button["steps"]:
                if not isinstance(step, dict) or len(step) != 1:
                    raise ValueError("Invalid macro step.")
                kind, argument = next(iter(step.items()))
                valid = (kind in ("tap", "down", "up") and isinstance(argument, str)) or (kind == "wait_ms" and type(argument) is int) or (kind == "chord" and isinstance(argument, list) and all(isinstance(k, str) for k in argument))
                if not valid:
                    raise ValueError("Invalid macro action.")
    controls = value.get("controls", [])
    count = len(DEVICE_MODELS[device]["defaults"]["controls"])
    if not isinstance(controls, list) or (controls and len(controls) not in (3, count)) or (controls and not count):
        raise ValueError("Invalid wheel controls.")
    for control in controls:
        if not isinstance(control, dict) or control.get("mode") not in ("default", "factory", "key", "shortcut", "macro", "keep", "disabled", "hypershift", "native"):
            raise ValueError("Invalid wheel control binding.")
        if control["mode"] == "native":
            native_action(control.get("value"))
        if not isinstance(control.get("trigger"), str) or not isinstance(control.get("value"), str) or not isinstance(control.get("steps"), list):
            raise ValueError("Invalid wheel control data.")
    if controls:
        # Existing three-control drafts predate the DPI button. Preserve every
        # edit and append pass-through controls; never silently restore defaults.
        value["controls"] = controls + [default_control() for _ in range(count - len(controls))]
    if device == "naga_v2_pro":
        secondary = value.get("hypershift", [keep_binding() for _ in range(16)])
        if not isinstance(secondary, list) or len(secondary) != 16:
            raise ValueError("Invalid Hypershift draft.")
        for button in secondary:
            if (not isinstance(button, dict) or button.get("mode") not in ("keep", "key", "shortcut", "disabled", "native")
                    or not isinstance(button.get("trigger"), str) or not isinstance(button.get("value"), str)
                    or not isinstance(button.get("steps"), list)):
                raise ValueError("Invalid Hypershift binding; nested triggers and macros are unsupported.")
            if button["mode"] == "native":
                native_action(button.get("value"))
        if not value.get("controls"):
            value["controls"] = [default_control() for _ in CONTROL_NAMES]
        value.update(version=2, hypershift=secondary)
    elif "hypershift" in value:
        raise ValueError("Hypershift drafts are only supported for Naga V2 Pro.")
    return value


def save_profile(path: Path, profile: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".profiles-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as out:
            json.dump(profile, out, indent=2)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def runtime_config(profile: dict) -> str:
    """Defaults are real passthrough, not artificial key taps."""
    bindings = []
    seen = set()
    for index, button in enumerate(profile["plates"][profile["plate"]]):
        trigger = button["trigger"]
        if trigger:
            trigger = key_code(trigger)
            if trigger in seen:
                raise ValueError(f"Buttons share input {trigger}. Learn each button separately.")
            seen.add(trigger)
        if button["mode"] in ("default", "keep"):
            continue
        if button["mode"] in ("hypershift", "disabled", "factory", "native"):
            raise ValueError("This binding requires Mouse memory mode; it is not a software macro.")
        if trigger in PROTECTED_INPUTS:
            raise ValueError("Main mouse buttons cannot be side-button inputs. Reset the plate or use Learn input to select a side button.")
        if not trigger:
            raise ValueError(f"Learn the input for button {index + 1} first.")
        binding = f"[[binding]]\ntrigger = {json.dumps(trigger)}\n"
        if button["mode"] == "key":
            binding += f"key = {json.dumps(key_code(button['value']))}\n"
        else:
            steps = [{"chord": shortcut(button["value"])}] if button["mode"] == "shortcut" else button["steps"]
            if not steps:
                raise ValueError(f"Button {index + 1} has no macro steps.")
            rendered = []
            for step in steps:
                if len(step) != 1:
                    raise ValueError("Each macro step needs one action.")
                kind, value = next(iter(step.items()))
                if kind == "wait_ms":
                    if type(value) is not int or not 0 <= value <= 60000:
                        raise ValueError("Delays must be 0–60000 ms.")
                    encoded = str(value)
                elif kind == "chord":
                    encoded = json.dumps([key_code(k) for k in value])
                elif kind in ("tap", "down", "up"):
                    encoded = json.dumps(key_code(value))
                else:
                    raise ValueError(f"Unknown macro action: {kind}")
                rendered.append(f"{{ {kind} = {encoded} }}")
            binding += "steps = [" + ", ".join(rendered) + "]\n"
        bindings.append(binding)
    return "tap_ms = 20\n" + ("\n".join(bindings) if bindings else "binding = []\n")


def reset_plate(profile: dict, plate: str) -> None:
    # Preserve learned inputs on the unverified plates, but remove all remapping.
    old = profile["plates"][plate]
    profile["plates"][plate] = [default_button(i, plate, profile.get("device", "naga_v2_pro")) for i in range(int(plate))]
    if plate != "12" or profile.get("device", "naga_v2_pro") != "naga_v2_pro":
        for before, after in zip(old, profile["plates"][plate]):
            after["trigger"] = before["trigger"] if before["trigger"] not in PROTECTED_INPUTS else ""


def binding_label(button: dict) -> str:
    if button["mode"] == "native":
        return BY_ID.get(button["value"], {}).get("label", "Unknown native action")
    if button["mode"] == "keep":
        return "Keep stored binding"
    if button["mode"] == "hypershift":
        return "Hold for Hypershift"
    if button["mode"] == "disabled":
        return "Disabled"
    if button["mode"] == "factory":
        return "Factory default"
    if button["mode"] == "default":
        return display_key(button["trigger"]) if button["trigger"] else "Default"
    if button["mode"] == "macro":
        return f"Macro · {len(button['steps'])} steps"
    return button["value"] or "Unassigned"
