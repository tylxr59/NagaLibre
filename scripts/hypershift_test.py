#!/usr/bin/env python3
"""Staged wired Hypershift trial with private paired-bank backups and exact restore."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from onboard_controlled_test import Session, durable_plan, require
from wheel_controlled_test import config_path

EDITS = [
    {"layer": 1, "action": {"button": 1, "category": 2, "data": [0, 5]}},
    {"layer": 0, "action": {"button": 16, "category": 12, "data": [1]}},
]


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def comparable(value):
    value = copy.deepcopy(value)
    if "normal" in value:
        value["normal"]["device"].pop("path", None)
        value.setdefault("normal_echoes", [{"button": n, "layer": 0} for n in range(1,17)])
    elif "slots" in value:
        for slot in value["slots"]:
            slot["state"] = comparable(slot["state"])
    return value


def check_state(actual, original, applied=False):
    expected = copy.deepcopy(original)
    if applied:
        for edit in EDITS:
            bank = actual["hypershift"] if edit["layer"] else actual["normal"]
            wanted = expected["hypershift"] if edit["layer"] else expected["normal"]
            key = "buttons" if edit["action"]["button"] <= 12 else "controls"
            index = next(i for i, button in enumerate(bank[key]) if button["button"] == edit["action"]["button"])
            action = {k: bank[key][index][k] for k in ("button", "category", "data")}
            require(action == edit["action"], "Hypershift test action did not read back")
            wanted[key][index] = bank[key][index]  # Changed actions may be reencoded by firmware.
            number = edit["action"]["button"]
            expected.setdefault("normal_echoes", [{"button": n, "layer": 0} for n in range(1,17)])
            for echoes in (expected["normal_echoes"], expected["hypershift"]["echoes"]):
                next(e for e in echoes if e["button"] == number)["layer"] = edit["layer"]
    require(comparable(actual) == comparable(expected), "Another paired-bank record or tracked state changed")


def read(session, slot=None):
    event = session.command("onboard_layers_read", slot=slot)
    require(event.get("type") == "onboard_layers_snapshot", "Unexpected layer read response")
    return event["snapshot"]


def prepared(session, **arguments):
    event = session.command(**arguments)
    require(event.get("type") == "onboard_layers_prepared", "Unexpected layer preparation response")
    backup = event["backup"]
    require(backup["format"] == 1 and backup["kind"] == "paired_mapping_backup", "Unexpected paired backup")
    return event


def prepare(directory, engine, session_factory=Session):
    require(not directory.exists(), "Use a fresh directory; keep previous backups")
    with session_factory(engine) as session:
        require(session.hello.get("hypershift_transactions") is True, "Engine lacks wired layer transactions")
        original = read(session)
        event = prepared(session, name="onboard_layers_prepare", edits=EDITS)
        # No commit: preparation only sends getters and checks every slot twice.
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    backup = directory / "original.json"
    durable_plan(backup, event["backup"])
    require(json.loads(backup.read_text()) == event["backup"], "Original backup readback failed")
    plan = {"format": 1, "engine": str(engine.resolve()), "engine_sha256": checksum(engine),
            "runner_sha256": checksum(Path(__file__)),
            "session_sha256": checksum(ROOT / "scripts/onboard_controlled_test.py"),
            "original": original, "backup_sha256": checksum(backup)}
    durable_plan(directory / "plan.json", plan)
    durable_plan(directory / "status.json", {"stage": "prepared", "plan_sha256": checksum(directory / "plan.json")})
    return "Read-only preparation complete. Both banks of every initialized slot are backed up. No settings changed."


def run_stage(stage, directory, session_factory=Session):
    plan_path = directory / "plan.json"
    status_path = directory / "status.json"
    status = json.loads(status_path.read_text())
    require(checksum(plan_path) == status["plan_sha256"], "Plan checksum changed")
    plan = json.loads(plan_path.read_text())
    engine = Path(plan["engine"])
    require(plan["format"] == 1 and checksum(engine) == plan["engine_sha256"], "Engine changed since preparation")
    require(checksum(Path(__file__)) == plan["runner_sha256"]
            and checksum(ROOT / "scripts/onboard_controlled_test.py") == plan["session_sha256"], "Test runner changed")
    require(checksum(directory / "original.json") == plan["backup_sha256"], "Original backup checksum changed")
    backup = json.loads((directory / "original.json").read_text())
    if stage == "apply":
        require(status["stage"] == "prepared", "Apply was already attempted; verify or restore instead")
    else:
        require(status["stage"] in ("applying", "applied", "verified", "restoring", "restored"), "Apply has not been attempted")
    with session_factory(engine) as session:
        for saved in backup["slots"]:
            current = read(session, saved["state"]["normal"]["slot"])
            active = current["normal"]["slot"] == plan["original"]["normal"]["slot"]
            if stage != "restore" or not active:
                check_state(current, saved["state"], applied=active and stage != "apply")
        current = read(session, plan["original"]["normal"]["slot"])
        if stage == "verify":
            status["stage"] = "verified"
            durable_plan(status_path, status)
            return "Both test actions read back; every other scoped record and slot is exact. Physical hold/release and persistence need your observation."
        event = (prepared(session, name="onboard_layers_prepare", edits=EDITS) if stage == "apply"
                 else prepared(session, name="onboard_layers_restore", backup=backup))
        target = next(s["state"] for s in event["backup"]["slots"] if s["state"]["normal"]["slot"] == current["normal"]["slot"])
        check_state(target, current)
        if stage == "apply":
            require(comparable(event["backup"]) == comparable(backup), "Prepared paired backup differs; no commit sent")
        # This unprivileged, fsynced checkpoint must succeed before token acknowledgement.
        recovery = directory / f"{stage}-recovery.json"
        durable_plan(recovery, event["backup"])
        require(json.loads(recovery.read_text()) == event["backup"], "Recovery backup readback failed")
        status.update(stage="applying" if stage == "apply" else "restoring", recovery=str(recovery))
        durable_plan(status_path, status)
        saved = session.command("onboard_commit", token=event["token"])
        require(saved.get("type") == "onboard_layers_saved", "Unexpected commit result; do not repeat apply")
        check_state(saved["snapshot"], plan["original"], applied=stage == "apply")
        status["stage"] = "applied" if stage == "apply" else "restored"
        durable_plan(status_path, status)
    return ("Applied: hold DPI and press grid 1 for B; release DPI and grid 1 should have its original output. Helper exited. Check primary clicks, reconnect, then verify and restore."
            if stage == "apply" else "Exact original paired-bank records restored and verified. Helper exited. Check original grid 1, DPI cycling and primary clicks.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "apply", "verify", "restore"))
    parser.add_argument("--directory", type=Path, default=config_path().parent / "hypershift-test")
    args = parser.parse_args()
    directory = args.directory.expanduser().resolve()
    try:
        print(prepare(directory, ROOT / "target/release/naga-macros") if args.stage == "prepare" else run_stage(args.stage, directory))
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as error:
        parser.exit(1, f"Hypershift trial stopped: {error}\nKeep private backups: {directory}\nIf apply was attempted, use the restore stage; do not repeat apply.\n")
    print(f"Private backup/plan: {directory}")


if __name__ == "__main__":
    main()
