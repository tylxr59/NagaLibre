#!/usr/bin/env python3
"""Save private all-slot mappings, then inspect HyperScroll without settings writes."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from onboard_controlled_test import durable_plan, require
from wheel_controlled_test import config_path


def query(engine, *arguments):
    result = subprocess.run(["sudo", str(engine), *arguments], check=True,
                            stdout=subprocess.PIPE, text=True)
    return json.loads(result.stdout)


def signature(value):
    value = copy.deepcopy(value)
    value["normal"]["device"].pop("path", None)
    return value


def progress(message):
    print(message, file=sys.stderr, flush=True)


def mappings(engine, expected=None):
    progress("Checking paired mappings after inspection…" if expected is not None
             else "Reading paired mappings for the private checkpoint…")
    first = query(engine, "onboard-layers")
    normal = first["normal"]
    require(normal["device"]["product"] == 0xa7 and normal["mode"] == [0, 0],
            "Connect wired Naga V2 Pro in normal mode with the twelve-button plate")
    require(normal["slot"] == normal["active"], "Active slot is not initialized")
    result = []
    for slot in normal["slots"]:
        progress(f"  Slot {slot}: using captured active-slot read." if slot == normal["slot"]
                 else f"  Slot {slot}: reading both mapping banks twice…")
        state = first if slot == normal["slot"] else query(engine, "onboard-layers", "--slot", str(slot))
        other = state["normal"]
        require(all(other[key] == normal[key] for key in ("device", "slots", "slot_capacity", "active", "mode")),
                "Mouse changed while backing up mappings")
        result.append(state)
    if expected is not None:
        require([signature(s) for s in result] == [signature(s) for s in expected],
                "Mapping state changed during wheel inspection")
    return result


def capture(engine, directory, *, firmware_version=False):
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    before = mappings(engine)
    # This durable checkpoint must precede the first haptic feature request.
    durable_plan(directory / "mappings-before.json", {"format": 1, "kind": "haptic_inspection_mapping_checkpoint", "slots": before})
    require(json.loads((directory / "mappings-before.json").read_text())["slots"] == before,
            "Mapping checkpoint readback differs")
    try:
        progress("Reading wheel configuration and all three tables twice…")
        state = query(engine, "haptic-read")
        require(state["format"] == 1 and state["kind"] == "haptic_diagnostic", "Unexpected wheel export")
        guard = state["guard"]
        normal = before[0]["normal"]
        require(guard["device"]["product"] == normal["device"]["product"]
                and guard["device"]["serial"] == normal["device"]["serial"]
                and guard["slots"] == normal["slots"] and guard["active"] == normal["active"]
                and guard["mode"] == normal["mode"] and guard["module_id"] == 3
                and guard["capacity"] == normal["slot_capacity"], "Wheel export belongs to different state")
        durable_plan(directory / "wheel.json", state)
        if firmware_version:
            progress("Reading firmware version twice and checking device identity…")
            version = query(engine, "haptic-firmware")
            require(version.get("format") == 1 and version.get("kind") == "haptic_firmware_diagnostic"
                    and version.get("guard") == guard and version.get("stable") is True,
                    "Firmware diagnostic belongs to different device/state")
            durable_plan(directory / "firmware.json", version)
    finally:
        after = mappings(engine, before)
        durable_plan(directory / "mappings-after.json", {"format": 1, "slots": after})
    return directory / "wheel.json", state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, default=ROOT / "target/debug/naga-macros")
    parser.add_argument("--firmware-version", action="store_true", help="Also read and privately save the two firmware version bytes")
    args = parser.parse_args()
    directory = config_path().parent / f"haptic-inspection-{time.time_ns()}"
    try:
        path, result = capture(args.engine.resolve(), directory, firmware_version=args.firmware_version)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Wheel inspection stopped: {error}\nPrivate checkpoint directory: {directory}\nNo settings writes were requested.\n")
    if args.firmware_version:
        version = json.loads((directory / "firmware.json").read_text())
        print(f"Reported firmware: {version['reported_version']}; raw bytes: {bytes(version['version_bytes']).hex(' ')}. Patch number is not reported by this getter.")
    state = result["state"]
    print("HyperScroll read twice; all initialized slots' paired mappings unchanged.")
    print(f"Active enabled-list position: {state['active_position']}; stage IDs: {bytes(state['stages']).hex(' ')}")
    print(f"Browsing mode: {state['browsing_mode']}; table points: {[len(t) for t in state['tables']]}")
    tables = state["tables"]
    if len(tables) == 3 and tables[2] and tables[0][:len(tables[2])] == tables[2]:
        print("Warning: velocity replies overlap the up table; independent down/velocity readback is unverified.")
    print(f"Metadata: {len(state['metadata'])} bytes; configuration: {bytes(state['configuration']).hex(' ')}")
    print(f"Private export: {path}")
    print(f"SHA256: {hashlib.sha256(path.read_bytes()).hexdigest()}")
    print("Diagnostic only; it is not a restorable wheel-settings backup.")


if __name__ == "__main__":
    main()
