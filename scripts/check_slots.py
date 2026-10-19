#!/usr/bin/env python3
"""Read-only evidence checks for desktop activation and creation of one slot."""
import argparse
import copy
import json
from pathlib import Path
import subprocess

from check_defaults import backup
from wheel_controlled_test import (
    ROOT, DEVICE_MODELS, WheelSession, checksum, config_path, durable_plan,
    read, require, signature,
)


def prepare(directory, engine, session_factory=WheelSession):
    original = backup(directory, engine, session_factory)
    inactive = [n for n in original["slots"] if n != original["active"]]
    capacity = original.get("slot_capacity")
    require(isinstance(capacity, int), "Slot capacity unavailable")
    unused = [n for n in range(2, capacity + 1) if n not in original["slots"]]
    require(inactive and unused, "Test needs an initialized inactive slot and an unused slot")
    plan_path = directory / "plan.json"
    plan = json.loads(plan_path.read_text())
    plan.update(kind="slots", activate=inactive[0], create=unused[0])
    durable_plan(plan_path, plan)
    durable_plan(directory / "status.json", {"stage": "prepared", "plan_sha256": checksum(plan_path)})
    print(f"Backups complete. Original active slot: {original['active']}.")
    print(f"First activate existing slot {inactive[0]}; later create only slot {unused[0]}.")
    print("Use Activate slot, not Save bindings. Creation will retain one new slot; existing slots are never deleted.")
    print("Only getters were sent; perform the desktop operations separately.")


def normalized(original, active, slots):
    expected = copy.deepcopy(original)
    expected.update(active=active, slots=slots)
    return expected


def check(stage, directory, session_factory=WheelSession):
    status_path = directory / "status.json"
    status = json.loads(status_path.read_text())
    plan_path = directory / "plan.json"
    require(checksum(plan_path) == status["plan_sha256"], "Plan checksum changed")
    plan = json.loads(plan_path.read_text())
    require(plan["format"] == 1 and plan.get("kind") == "slots", "Not a slot test plan")
    require(checksum(directory / "original.json") == plan["original_sha256"], "Original backup changed")
    engine = Path(plan["engine"])
    require(checksum(engine) == plan["engine_sha256"], "Engine changed; inspect before proceeding")
    allowed = {"activated": ("prepared", "activated"),
               "switched-back": ("activated", "switched-back"),
               "created": ("switched-back", "created"),
               "new-active": ("created", "new-active"),
               "restored": ("prepared", "activated", "switched-back", "created", "new-active", "restored")}
    require(stage in allowed and status["stage"] in allowed[stage], "Check stages in order")
    original = plan["original"]
    added = stage in ("created", "new-active") or "new_snapshot" in status
    slots = sorted(original["slots"] + ([plan["create"]] if added else []))
    active = plan["activate"] if stage == "activated" else plan["create"] if stage == "new-active" else original["active"]
    with session_factory(engine) as session:
        for before in plan["snapshots"]:
            actual = read(session, before["slot"])
            require(signature(actual) == signature(normalized(before, active, slots)),
                    f"Original slot {before['slot']} or tracked device state changed unexpectedly")
        if added:
            new = read(session, plan["create"])
            if "new_snapshot" in status:
                require(signature(new) == signature(normalized(status["new_snapshot"], active, slots)),
                        "New slot changed since creation")
            else:
                expected = DEVICE_MODELS["naga_v2_pro"]["defaults"]["plates"]["12"]["bindings"]
                require([(b["button"], b["category"], b["data"]) for b in new["buttons"]] ==
                        [(i + 1, b["category"], b["data"]) for i, b in enumerate(expected)], "New grid defaults differ")
                require([(b["button"], b["category"], b["data"]) for b in new["primary"]] ==
                        [(1, 1, [1]), (2, 1, [2])], "New primary mappings differ")
                require(new["slot"] == plan["create"] and new["device"] == actual["device"] and new["slot_capacity"] == original["slot_capacity"]
                        and new["mode"] == original["mode"] and new["slots"] == slots and new["active"] == active,
                        "New slot identity or state differs")
                status["new_snapshot"] = new
    status["stage"] = stage
    durable_plan(status_path, status)
    print(f"{stage}: active slot {active}; initialized slots {slots}; original mapping records exact.")
    if added:
        print("New slot records verified. The newly created slot is retained.")
    print("Only getters were sent. Physical output and reconnect observations must be reported separately.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "activated", "switched-back", "created", "new-active", "restored"))
    parser.add_argument("--directory", type=Path, default=config_path().parent / "desktop-slot-verification")
    args = parser.parse_args()
    directory = args.directory.expanduser().resolve()
    try:
        if args.stage == "prepare":
            prepare(directory, ROOT / "target/release/naga-macros")
        else:
            check(args.stage, directory)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Slot check stopped: {error}\nKeep private backups: {directory}\n")


if __name__ == "__main__":
    main()
