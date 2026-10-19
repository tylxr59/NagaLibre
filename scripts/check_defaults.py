#!/usr/bin/env python3
"""Back up and check desktop defaults or output tests using getters only."""
import argparse
import copy
import json
from pathlib import Path
import subprocess
import time

from wheel_controlled_test import (
    ROOT, DEVICE_MODELS, WheelSession, checksum, config_path, durable_plan,
    read, require, signature,
)
from model import load_profile
from onboard import hardware_buttons, hardware_controls


def defaults_match(actual, original):
    expected = copy.deepcopy(original)
    defaults = DEVICE_MODELS["naga_v2_pro"]["defaults"]
    groups = (("buttons", [dict(button=i + 1, **b) for i, b in enumerate(defaults["plates"]["12"]["bindings"])]),
              ("controls", [dict(button=c["button"], **c["binding"]) for c in defaults["controls"]]))
    for group, desired in groups:
        require([b["button"] for b in actual[group]] == [b["button"] for b in desired], "Incomplete default readback")
        for index, (before, after, action) in enumerate(zip(original[group], actual[group], desired)):
            require((after["category"], after["data"]) == (action["category"], action["data"]),
                    f"{group} {action['button']} does not have its default action")
            if (before["category"], before["data"]) != (action["category"], action["data"]):
                expected[group][index] = copy.deepcopy(after)
    require(signature(actual) == signature(expected), "Unchanged records or other tracked state changed")


def outputs_match(actual, original):
    expected = copy.deepcopy(original)
    require(len(actual["buttons"]) == len(original["buttons"]), "Incomplete output readback")
    for number, category, data in ((1, 2, [1, 4]), (2, 1, [2])):
        index = next(i for i, b in enumerate(original["buttons"]) if b["button"] == number)
        after = actual["buttons"][index]
        require((after["button"], after["category"], after["data"]) == (number, category, data),
                f"Button {number} does not have the expected test action")
        before = original["buttons"][index]
        if (before["category"], before["data"]) != (category, data):
            expected["buttons"][index] = copy.deepcopy(after)
    differences = []
    for group in ("buttons", "controls", "primary"):
        wanted = {b["button"]: b for b in expected.get(group, [])}
        found = {b["button"]: b for b in actual.get(group, [])}
        differences.extend(f"{group} {number}" for number in sorted(wanted.keys() | found.keys())
                           if wanted.get(number) != found.get(number))
    require(signature(actual) == signature(expected), "Another mapping record or tracked state changed"
            + (": " + ", ".join(differences) if differences else ""))


def validate_output_draft(profile, original):
    require(profile.get("storage", "hardware") == "hardware", "Choose Mouse memory before staging this test")
    desired = copy.deepcopy(original)
    for group, actions in (("buttons", hardware_buttons(profile)), ("controls", hardware_controls(profile))):
        for action in actions:
            index = next(i for i, b in enumerate(original[group]) if b["button"] == action["button"])
            before = original[group][index]
            if (before["category"], before["data"]) != (action["category"], action["data"]):
                desired[group][index] = action
    try:
        outputs_match(desired, original)
    except ValueError as error:
        raise ValueError(f"Local draft does not match the output trial: {error}. "
                         "Set all four extra controls to Keep stored binding, preserve other grid actions, "
                         "and save the draft or fully quit the GUI before retrying. No mouse writes were sent.") from error


def backup(directory, engine, session_factory=WheelSession, connection="usb"):
    require(connection in ("usb", "receiver"), "Unsupported test connection")
    product = 0xA8 if connection == "receiver" else 0xA7
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    engine_hash = checksum(engine)
    with session_factory(engine) as session:
        original = read(session)
        require(original["device"]["product"] == product and original["mode"] == [0, 0]
                and original["slot"] == original["active"],
                f"Requires {connection} active slot in normal mode (product {product:04x})")
        snapshots = [read(session, n) for n in original["slots"]]
        for snapshot in snapshots:
            for key in ("device", "slots", "slot_capacity", "mode", "active"):
                require(snapshot[key] == original[key], "Mouse changed while backing up")
        require(signature(read(session, original["slot"])) == signature(original), "Active slot changed while backing up")
    require(checksum(engine) == engine_hash, "Engine changed during backup")
    durable_plan(directory / "original.json", original)
    plan = {"format": 1, "engine": str(engine), "engine_sha256": engine_hash,
            "original": original, "snapshots": snapshots,
            "original_sha256": checksum(directory / "original.json")}
    durable_plan(directory / "plan.json", plan)
    durable_plan(directory / "status.json", {"stage": "prepared", "plan_sha256": checksum(directory / "plan.json")})
    return original


def prepare(directory, engine, session_factory=WheelSession, test="defaults", connection="usb"):
    require(test in ("defaults", "outputs"), "Unknown desktop test")
    original = backup(directory, engine, session_factory, connection)
    if test == "outputs":
        plan_path = directory / "plan.json"
        plan = json.loads(plan_path.read_text())
        plan["test"] = test
        durable_plan(plan_path, plan)
        durable_plan(directory / "status.json", {"stage": "prepared", "plan_sha256": checksum(plan_path)})
    print(f"All initialized slots backed up. Active slot: {original['slot']}.")
    print(f"Original mapping backup for the GUI Restore backup button: {directory / 'original.json'}")
    if test == "outputs":
        print("No settings changed. Stage grid button 1 = Ctrl+A and grid button 2 = BTN_RIGHT.")
        print("Preserve other grid assignments; set all four extra controls to Keep stored binding. Do not save yet.")
    else:
        print("No settings changed. In Mouse memory, select the active slot and click Restore defaults; do not save yet.")


def check(stage, directory, session_factory=WheelSession):
    status = json.loads((directory / "status.json").read_text())
    require(checksum(directory / "plan.json") == status["plan_sha256"], "Plan checksum changed")
    plan = json.loads((directory / "plan.json").read_text())
    require(plan["format"] == 1, "Unknown plan format")
    test = plan.get("test", "defaults")
    require(test in ("defaults", "outputs"), "Unknown desktop test")
    require(checksum(directory / "original.json") == plan["original_sha256"], "Original backup changed")
    require(json.loads((directory / "original.json").read_text()) == plan["original"], "Original backup differs from plan")
    engine = Path(plan["engine"])
    require(checksum(engine) == plan["engine_sha256"], "Engine changed; inspect before proceeding")
    require(stage in ("staged", "saved", "restored"), "Unknown check")
    require(stage != "saved" or status["stage"] in ("staged", "saved"), "Check draft-only state before saving defaults")
    if stage == "staged" and test == "outputs":
        validate_output_draft(load_profile(config_path()), plan["original"])
    with session_factory(engine) as session:
        for original in plan["snapshots"]:
            actual = read(session, original["slot"])
            durable_plan(directory / f"readback-{stage}-slot-{original['slot']}-{time.time_ns()}.json", actual)
            if stage == "saved" and original["slot"] == plan["original"]["slot"]:
                (outputs_match if test == "outputs" else defaults_match)(actual, original)
            else:
                require(signature(actual) == signature(original), "Tracked state differs from original backup")
    # Persist only after every slot passes; a failed check leaves evidence intact.
    status["stage"] = stage
    durable_plan(directory / "status.json", status)
    print({"staged": "Tracked mouse state is unchanged. Draft-only check passed. You can now save the test draft in the GUI.",
           "saved": ("Ctrl+A and right-click read back correctly; all other tracked records and slots are exact." if test == "outputs" else
                     "All sixteen defaults read back correctly; unchanged records and other slots are exact."),
           "restored": "All original tracked records, slots, mode and active slot match exactly."}[stage])
    print("Only getters were sent. Physical behavior must be reported separately.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "staged", "saved", "restored"))
    parser.add_argument("--test", choices=("defaults", "outputs"), default="defaults")
    parser.add_argument("--connection", choices=("usb", "receiver"), default="usb",
                        help="Expected preparation connection and default evidence directory; checks remain bound to the saved plan")
    parser.add_argument("--directory", type=Path)
    args = parser.parse_args()
    prefix = "receiver-" if args.connection == "receiver" else ""
    directory = (args.directory or config_path().parent / f"{prefix}{args.test}-verification").expanduser().resolve()
    try:
        if args.stage == "prepare":
            prepare(directory, ROOT / "target/release/naga-macros", test=args.test, connection=args.connection)
        else:
            check(args.stage, directory)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Desktop check stopped: {error}\nKeep the original backup: {directory}\n")


if __name__ == "__main__":
    main()
