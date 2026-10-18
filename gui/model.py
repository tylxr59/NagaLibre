"""Profiles and config conversion, kept independent of Qt for testing."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile

DEFAULT_KEYS = [f"KEY_{i}" for i in range(1, 10)] + ["KEY_0", "KEY_MINUS", "KEY_EQUAL"]
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


def default_button(index: int, plate: str) -> dict:
    return {"trigger": DEFAULT_KEYS[index] if plate == "12" else "", "mode": "default", "value": "", "steps": []}


def new_profile() -> dict:
    return {"version": 1, "plate": "12", "plates": {p: [default_button(i, p) for i in range(int(p))] for p in ("12", "6", "2")}}


def config_path() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "NagaLibre" / "profiles.json"


def load_profile(path: Path) -> dict:
    if not path.exists():
        return new_profile()
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("Profile must contain an object.")
    if value.get("version") != 1 or value.get("plate") not in ("12", "6", "2"):
        raise ValueError("Unsupported profile format; the file was left untouched.")
    for plate in ("12", "6", "2"):
        buttons = value["plates"][plate]
        if len(buttons) != int(plate):
            raise ValueError(f"Invalid {plate}-button profile.")
        for button in buttons:
            if not isinstance(button, dict):
                raise ValueError("Invalid button data.")
            if button["mode"] not in ("default", "key", "shortcut", "macro"):
                raise ValueError("Unknown binding type.")
            if not isinstance(button["trigger"], str) or not isinstance(button["value"], str) or not isinstance(button["steps"], list):
                raise ValueError("Invalid button data.")
            for step in button["steps"]:
                if not isinstance(step, dict) or len(step) != 1:
                    raise ValueError("Invalid macro step.")
                kind, argument = next(iter(step.items()))
                valid = (kind in ("tap", "down", "up") and isinstance(argument, str)) or (kind == "wait_ms" and type(argument) is int) or (kind == "chord" and isinstance(argument, list) and all(isinstance(k, str) for k in argument))
                if not valid:
                    raise ValueError("Invalid macro action.")
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
        if button["mode"] == "default":
            continue
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
    profile["plates"][plate] = [default_button(i, plate) for i in range(int(plate))]
    if plate != "12":
        for before, after in zip(old, profile["plates"][plate]):
            after["trigger"] = before["trigger"]


def binding_label(button: dict) -> str:
    if button["mode"] == "default":
        return display_key(button["trigger"]) if button["trigger"] else "Default"
    if button["mode"] == "macro":
        return f"Macro · {len(button['steps'])} steps"
    return button["value"] or "Unassigned"
