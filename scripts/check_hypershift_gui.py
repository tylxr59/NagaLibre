#!/usr/bin/env python3
"""Independently check GUI Hypershift staging, save and restore using getters only."""
import argparse
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from onboard_controlled_test import Session, durable_plan, require
from hypershift_test import check_state, checksum, comparable
from wheel_controlled_test import config_path


def current_backup(engine, session_factory=Session):
    with session_factory(engine) as session:
        require(session.hello.get("hypershift_transactions") is True, "Use wired USB and the updated helper")
        read = session.command("onboard_layers_read", slot=None)
        require(read.get("type") == "onboard_layers_snapshot", "Unexpected layer read")
        event = session.command("onboard_layers_prepare", edits=[])
        require(event.get("type") == "onboard_layers_prepared", "Unexpected paired backup response")
        backup = event["backup"]
        require(backup["kind"] == "paired_mapping_backup", "Unexpected paired backup")
        # No commit token: even preparation of this empty edit set is read-only.
    return backup


def run(stage, directory, engine=None, session_factory=Session):
    engine = engine or ROOT / "target/release/naga-macros"
    if stage == "prepare":
        require(not directory.exists(), "Use a fresh directory and keep all prior backups")
        backup = current_backup(engine, session_factory)
        directory.mkdir(mode=0o700, parents=True, exist_ok=False)
        path = directory / "original.json"
        durable_plan(path, backup)
        require(json.loads(path.read_text()) == backup, "Original paired backup readback failed")
        durable_plan(directory / "plan.json", {"format": 1, "backup_sha256": checksum(path),
                                              "active": backup["slots"][0]["state"]["normal"]["active"]})
        return ("Both banks of every initialized slot backed up. No settings changed.\n"
                "In the GUI, use stored bindings as draft, set normal DPI = Hold for Hypershift and secondary grid 1 = B.\n"
                "Save draft locally, then quit the GUI before the staged check.\n"
                f"GUI Restore backup file: {path}")
    plan = json.loads((directory / "plan.json").read_text())
    require(plan["format"] == 1 and checksum(directory / "original.json") == plan["backup_sha256"], "Original backup checksum changed")
    original = json.loads((directory / "original.json").read_text())
    actual = current_backup(engine, session_factory)
    expected = copy.deepcopy(original)
    if stage == "saved":
        require(len(actual["slots"]) == len(original["slots"]), "Slot inventory changed")
        for before, after in zip(original["slots"], actual["slots"]):
            check_state(after["state"], before["state"], applied=before["state"]["normal"]["slot"] == plan["active"])
        # State records above were checked with semantic equivalence only for the
        # two intended edits. Compare every other backup field, including middle.
        for target, after in zip(expected["slots"], actual["slots"]):
            target["state"] = after["state"]
    else:
        require(stage in ("staged", "restored"), "Unknown verification stage")
    require(comparable(actual) == comparable(expected), "Another record, slot, echo or tracked state changed")
    durable_plan(directory / f"{stage}.json", actual)
    return {"staged": "Both banks and all slots are unchanged. Draft-only check passed. Reopen the GUI and save bindings to mouse.",
            "saved": "DPI Hypershift and secondary grid-1 B read back; all other scoped records/slots are exact. Test physical hold/release, clicks and reconnect, then restore the original paired backup in the GUI.",
            "restored": "All original paired records, echoes, normal primary checks, slots and device state match exactly. Check original physical outputs; optionally use stored bindings as draft and Save draft to clear local test edits."}[stage]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "staged", "saved", "restored"))
    parser.add_argument("--directory", type=Path, default=config_path().parent / "hypershift-gui-verification")
    args = parser.parse_args()
    directory = args.directory.expanduser().resolve()
    print("Keep USB and the twelve-button plate attached; quit the GUI before running this check. Reading all slots…", flush=True)
    try:
        print(run(args.stage, directory))
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"GUI check stopped: {error}\nKeep original backups: {directory}\nNo mouse settings writes were requested.\n")
    print("Only getters were sent. Physical observations must be reported separately.")


if __name__ == "__main__":
    main()
