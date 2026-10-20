#!/usr/bin/env python3
"""Controlled wired wheel-stage trial with durable backup and automatic restoration."""
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
from onboard_controlled_test import Session, durable_plan, require
from wheel_controlled_test import config_path
from haptic_presets import PRESET_NAMES, PRESET_DESCRIPTIONS, BUILTIN_PRESETS


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(session, name, expected, **arguments):
    event = session.command(name, **arguments)
    require(event.get("type") == expected, event.get("message", f"Unexpected helper response: {event.get('type')}"))
    return event


def saved(session, directory, prepared, name):
    backup = directory / name
    durable_plan(backup, prepared["backup"])
    require(json.loads(backup.read_text()) == prepared["backup"], "Durable wheel backup readback differs")
    return backup


def restore(directory):
    plan_path = directory / "plan.json"
    plan = json.loads(plan_path.read_text())
    require(plan["status"] in ("applying", "applied", "restoring"), "No outstanding wheel trial to restore")
    engine = Path(plan["engine"])
    require(checksum(engine) == plan["engine_sha256"], "Engine changed; keep this trial intact for recovery")
    backup_path = directory / "original-wheel.json"
    require(checksum(backup_path) == plan["backup_sha256"], "Original backup checksum changed")
    backup = json.loads(backup_path.read_text())
    with Session(engine) as session:
        prepared = command(session, "haptic_restore", "haptic_prepared", backup=backup, slot=plan["slot"])
        saved(session, directory, prepared, "before-restoration.json")
        plan["status"] = "restoring"
        durable_plan(plan_path, plan)
        after = command(session, "haptic_commit", "haptic_saved", token=prepared["token"])["snapshot"]
    original = next(s for s in backup["slots"] if s["slot"] == plan["slot"])
    require(after["state"] == original, "Original wheel state did not restore exactly")
    durable_plan(directory / "restored.json", after)
    plan["status"] = "restored_exactly"
    durable_plan(plan_path, plan)
    print("Original wheel settings restored exactly; both mapping banks and other slots checked unchanged.")


def ask_match(prompt):
    while True:
        answer = input(prompt + " [y/n/unsure; optional notes; q to stop]: ").strip()
        first = answer.split(maxsplit=1)[0].lower().rstrip(".,:;") if answer else ""
        if first in ("q", "quit"):
            raise KeyboardInterrupt
        verdict = {"y": "yes", "yes": "yes", "n": "no", "no": "no", "u": "unsure", "unsure": "unsure"}.get(first)
        if verdict:
            return {"verdict": verdict, "answer": answer}
        print("Enter y, n or unsure, with any observations after it; q stops safely.")


def same_starting_state(actual, expected):
    actual, expected = copy.deepcopy(actual), copy.deepcopy(expected)
    for state in (actual, expected):
        state["guard"]["device"].pop("path", None)
    return actual == expected


def trial(engine, directory, position, order=None, *, preset=None, expected_start=None, allow_unchanged=False, check_cycle=False):
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    plan_path = directory / "plan.json"
    plan = {"format": 1, "engine": str(engine), "engine_sha256": checksum(engine), "status": "preparing"}
    durable_plan(plan_path, plan)
    try:
        with Session(engine) as session:
            require(session.hello.get("haptic_settings") is True, "Wheel settings require a wired mouse and updated helper")
            known = command(session, "haptic_read", "haptic_snapshot", slot=None)["snapshot"]
            if expected_start is not None:
                require(same_starting_state(known, expected_start), "Starting wheel/device state changed between guided tests; no settings write attempted")
            edit = {"active_position": position, "stages": order or known["state"]["stages"]}
            unchanged = edit == {"active_position": known["state"]["active_position"], "stages": known["state"]["stages"]}
            require(allow_unchanged or not unchanged, "Choose a stage/order different from the current state")
            if preset is not None:
                require(1 <= position <= len(edit["stages"]) and edit["stages"][position - 1] == preset,
                        "Named preset does not match the selected list position")
                plan.update(preset_id=preset, preset_name=PRESET_NAMES[preset], expected_description=PRESET_DESCRIPTIONS[preset], unchanged=unchanged)
            prepared = command(session, "haptic_prepare", "haptic_prepared", known=known, edit=edit)
            backup_path = saved(session, directory, prepared, "original-wheel.json")
            plan.update(status="applying", backup_sha256=checksum(backup_path), slot=known["state"]["slot"], edit=edit)
            durable_plan(plan_path, plan)
            after = command(session, "haptic_commit", "haptic_saved", token=prepared["token"])["snapshot"]
            durable_plan(directory / "applied.json", after)
        plan["status"] = "applied"
        durable_plan(plan_path, plan)
        if preset is None:
            print(f"Wheel saved at enabled-list position {position}; stage IDs {bytes(edit['stages']).hex(' ')}.")
        else:
            print(f"\nTesting {PRESET_NAMES[preset]}" + (" (already selected; no settings change needed)." if unchanged else "."))
            print(PRESET_DESCRIPTIONS[preset])
        print("Feel the wheel and confirm ordinary scrolling and primary clicks.")
        print("For persistence, reconnect USB now and check the feel again. Keep the twelve-button plate attached.")
        observation = (ask_match(f"Does this feel like {PRESET_NAMES[preset]} as described?") if preset is not None
                       else input("Describe the results, then press Enter to restore (empty = unverified): "))
        plan["user_observation"] = observation
        durable_plan(plan_path, plan)
        if check_cycle:
            print("Before restoration, press the scroll-mode button five times, feeling the wheel after each press.")
            plan["cycle_observation"] = ask_match("Did the feel change while cycling, then return to the starting feel after five presses?")
            durable_plan(plan_path, plan)
    finally:
        persisted = json.loads(plan_path.read_text())
        if persisted["status"] in ("applying", "applied", "restoring"):
            restore(directory)
    print(f"Private trial directory: {directory}")
    print("After restoration, check original feel, scrolling and primary clicks; report those observations separately.")
    return json.loads(plan_path.read_text())


def guided(engine, directory):
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    path = directory / "guided-plan.json"
    suite = {"format": 1, "kind": "guided_haptic_presets", "status": "preparing",
             "engine": str(engine), "engine_sha256": checksum(engine), "steps": []}
    durable_plan(path, suite)
    try:
        with Session(engine) as session:
            require(session.hello.get("haptic_settings") is True, "Guided wheel tests require wired Naga V2 Pro")
            starting = command(session, "haptic_read", "haptic_snapshot", slot=None)["snapshot"]
        state = starting["state"]
        require(len(state["stages"]) == len(BUILTIN_PRESETS) and set(state["stages"]) == set(BUILTIN_PRESETS),
                "Exactly the five built-in presets must already be enabled for this guided selection-only test")
        baseline_id = state["stages"][state["active_position"] - 1]
        require(baseline_id in PRESET_NAMES, "Unknown original preset")
        suite.update(status="running", starting=starting)
        durable_plan(path, suite)
        for preset in BUILTIN_PRESETS:
            child = directory / f"preset-{PRESET_NAMES[preset].lower().replace(' ', '-')}"
            suite["current_trial"] = str(child)
            durable_plan(path, suite)
            result = trial(engine, child, state["stages"].index(preset) + 1, preset=preset,
                           expected_start=starting, allow_unchanged=True, check_cycle=preset == BUILTIN_PRESETS[0])
            require(result["status"] == "restored_exactly", "Guided trial did not restore")
            step = {"preset": PRESET_NAMES[preset], "trial": str(child),
                    "observation": result["user_observation"], "stored_restore": "exact"}
            if "cycle_observation" in result:
                step["cycle_observation"] = result["cycle_observation"]
            suite["steps"].append(step)
            durable_plan(path, suite)
            step["original_feel"] = ask_match(f"After restoration, is your original {PRESET_NAMES[baseline_id]} feel back, with normal scrolling and clicks?")
            if step["original_feel"]["verdict"] != "yes":
                suite["status"] = "physical_restore_uncertain"
                durable_plan(path, suite)
                print("Stopped before another preset: stored restoration passed, but original physical behavior needs review.")
                return
            durable_plan(path, suite)
        suite["status"] = "completed"
        durable_plan(path, suite)
        print("\nGuided preset checks completed; original captured settings restored between every preset.")
        for step in suite["steps"]:
            print(f"{step['preset']}: {step['observation']['verdict']}; original feel after restore: {step['original_feel']['verdict']}")
    except BaseException:
        suite["status"] = "interrupted"
        durable_plan(path, suite)
        print(f"Guided test stopped. Inspect the current trial status before recovery: {suite.get('current_trial', directory)}")
        raise
    finally:
        print(f"Private guided evidence: {directory}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("trial", "restore", "guided"))
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--position", type=int, choices=range(1, 7), default=1)
    parser.add_argument("--order", nargs="+", type=lambda value: int(value, 16), help="Enabled stage IDs in hexadecimal")
    parser.add_argument("--engine", type=Path, default=ROOT / "target/debug/naga-macros")
    args = parser.parse_args()
    directory = args.directory or config_path().parent / f"haptic-stage-trial-{time.time_ns()}"
    try:
        if args.stage == "restore":
            require(args.directory is not None, "Restore needs the original --directory")
            restore(directory)
        elif args.stage == "guided":
            require(args.order is None, "Guided selection tests preserve the existing enabled-stage order")
            guided(args.engine.resolve(), directory)
        else:
            trial(args.engine.resolve(), directory, args.position, args.order)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, KeyboardInterrupt, EOFError) as error:
        parser.exit(1, f"Wheel trial stopped: {error}\nPrivate state: {directory}\nRead plan.json status before any retry.\n")


if __name__ == "__main__":
    main()
