#!/usr/bin/env python3
"""Upload one fresh macro, verify contents, optionally observe playback, then recover."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from onboard_controlled_test import durable_plan, require
from wheel_controlled_test import config_path
from inspect_haptic import query, signature


def durable_text(path, text):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as output:
        output.write(text)
        output.flush()
        os.fsync(output.fileno())
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def restored(before, after):
    expected_guard = copy.deepcopy(before["guard"])
    expected_guard["device"]["path"] = after["guard"]["device"]["path"]
    require(after["guard"] == expected_guard, "Device, mode, plate or inventory changed")
    require([signature(m) for m in before["mappings"]] == [signature(m) for m in after["mappings"]],
            "Original paired mapping records/echoes were not restored exactly")
    entries = lambda value: sorted(value["storage"]["entries"], key=lambda e: e["id"])
    require(entries(before) == entries(after), "Original macro contents differ or owned allocation remains")
    for name in ("max_macros", "storage_bytes", "stored_count"):
        require(before["storage"][name] == after["storage"][name], f"Macro {name} changed")


def trial(engine, directory, mode, count=3, physical=True, observe=input, timeline="keys"):
    require(timeline in ("keys", "shortcut"), "Unknown trial timeline")
    require(timeline != "shortcut" or mode == "once", "Shortcut trial requires once playback")
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    config = directory / "trial.toml"
    steps = "{tap='KEY_B'},{wait_ms=120}"
    if mode == "sequence":
        steps += ",{tap='KEY_C'},{wait_ms=120}"
    if timeline == "shortcut":
        steps = "{chord=['KEY_LEFTSHIFT','KEY_B']},{wait_ms=120},{tap='KEY_C'},{wait_ms=120}"
    durable_text(config, f"tap_ms=80\n[[binding]]\ntrigger='KEY_1'\nsteps=[{steps}]\n")
    request = {"trigger": "KEY_1", "guid": str(uuid.uuid4()), "name": "NagaLibre playback trial",
               "button": 1, "layer": 0, "playback": {"mode": mode}}
    if mode == "counted":
        request["playback"]["count"] = count
    request_path = directory / "request.json"
    durable_plan(request_path, request)
    print("Preparing wired macro contents and all-slot paired/middle-click backup…", flush=True)
    backup = query(engine, "onboard-macro-prepare", str(config), str(request_path))
    require(backup.get("kind") == "onboard_macro_transaction_backup" and backup.get("complete_profile") is False,
            "Invalid macro transaction backup")
    backup_path = directory / "backup.json"
    durable_plan(backup_path, backup)
    require(json.loads(backup_path.read_text()) == backup, "Durable backup readback differs")
    checksum = hashlib.sha256(backup_path.read_bytes()).hexdigest()
    before = backup["contents"]["inspection"]
    durable_plan(directory / "before.json", before)
    offline = subprocess.run([str(engine), "onboard-macro-plan", str(directory / "before.json"),
                              str(config), str(request_path)], check=True, capture_output=True, text=True)
    plan = json.loads(offline.stdout)
    durable_plan(directory / "offline-plan.json", plan)
    journal = directory / "transaction.journal.jsonl"
    applied = None
    observations = {"playback": mode, "timeline": timeline, "physical_testing_requested": physical,
                    "outputs": None, "primary_clicks": None, "reconnect": None}
    try:
        print("Uploading the fresh entry, checking nonempty getters, then binding grid 1…", flush=True)
        applied = query(engine, "onboard-macro-apply", str(backup_path), str(journal))
        durable_plan(directory / "applied.json", applied)
        found = next((e for e in applied["storage"]["entries"] if e["id"] == plan["entry"]["id"]), None)
        require(found == plan["entry"], "Uploaded bytes differ from the independently saved offline plan")
        print("Native metadata/data readback matched. The helper has exited; grid 1 uses mouse memory.", flush=True)
        if physical:
            descriptions = {"once": "Press grid 1 once: expect one B and a released key.",
                            "counted": f"Press grid 1 once: expect {count} B presses, then silence.",
                            "while_held": "Hold grid 1 to repeat B; release it and check repetition stops.",
                            "toggle": "Press grid 1 to start B repetition; press again and check it stops.",
                            "sequence": "The timeline contains B then C. Tap grid 1 slowly four times, waiting a second "
                                        "between taps. Record what each tap emits and whether output continues after release."}
            if timeline == "shortcut":
                descriptions["once"] = ("Turn Caps Lock off. Press grid 1 once in an empty editor: expect Bc "
                                        "(uppercase B, lowercase c). Type d manually afterward: expect lowercase d.")
            print(descriptions[mode], flush=True)
            observations["outputs"] = observe("Record observed outputs/release behavior (include failures): ")
            observations["primary_clicks"] = observe("Check left/right/middle clicks and record the result: ")
            if mode in ("toggle", "while_held"):
                observe("Stop playback with the toggle button/release the held button before continuing. Press Enter: ")
            observations["reconnect"] = observe("Reconnect USB, try grid 1 again, stop any repetition, and record persistence: ")
        durable_plan(directory / "observations.json", observations)
    finally:
        if journal.exists():
            print("Restoring exact original bindings, then removing only this upload's allocation…", flush=True)
            after = query(engine, "onboard-macro-recover", str(journal))
            durable_plan(directory / "recovered.json", after)
            restored(before, after)
            require(hashlib.sha256(backup_path.read_bytes()).hexdigest() == checksum, "Original backup file changed")
            print("Original macro contents and scoped paired/middle mappings verified; owned allocation removed.", flush=True)
    return applied, observations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, default=ROOT / "target/release/naga-macros")
    parser.add_argument("--playback", choices=("once", "counted", "while_held", "toggle", "sequence"), default="once")
    parser.add_argument("--timeline", choices=("keys", "shortcut"), default="keys",
                        help="Shortcut tests Shift+B followed by unmodified C; requires once playback")
    parser.add_argument("--count", type=int, choices=range(1, 256), metavar="1..255", default=3)
    parser.add_argument("--readback-only", action="store_true", help="Upload/verify/recover immediately; records no physical verification")
    parser.add_argument("--restore", type=Path, metavar="JOURNAL", help="Resume recovery only; never creates another upload")
    args = parser.parse_args()
    engine = args.engine.resolve()
    directory = config_path().parent / f"macro-trial-{time.time_ns()}"
    try:
        if args.restore:
            after = query(engine, "onboard-macro-recover", str(args.restore.resolve()))
            output = args.restore.parent / f"recovered-{time.time_ns()}.json"
            durable_plan(output, after)
            print(f"Scoped transaction recovery verified. Private readback: {output}")
            return
        print("Close other NagaLibre/OpenRazer/Polychromatic controllers before this test.")
        trial(engine, directory, args.playback, args.count, not args.readback_only, timeline=args.timeline)
    except (OSError, ValueError, KeyError, TypeError, EOFError, subprocess.SubprocessError, KeyboardInterrupt) as error:
        parser.exit(1, f"Macro trial stopped: {error}\nPrivate evidence: {directory}\n"
                    "If recovery did not complete, keep the journal and resume with --restore JOURNAL.\n")
    print(f"Private evidence: {directory}")
    if args.readback_only:
        print("Readback/recovery only: physical outputs, release and reconnect persistence were not tested.")
    else:
        print("Physical observations are recorded separately; inspect them for failures before claiming verification.")


if __name__ == "__main__":
    main()
