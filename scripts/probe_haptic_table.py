#!/usr/bin/env python3
"""Replay eight existing custom-wheel points using the traced native framing."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from haptic_test import Session, checksum, command, durable_plan, require, saved
from wheel_controlled_test import config_path


def invoke(directory, *, restore_only):
    path = directory / "plan.json"
    plan = json.loads(path.read_text())
    require(plan["status"] in ("probing", "restoring"), "No outstanding table replay; do not repeat a completed probe")
    engine = Path(plan["engine"])
    backup = directory / "original-wheel.json"
    require(checksum(engine) == plan["engine_sha256"], "Helper changed; preserve it for recovery")
    require(checksum(backup) == plan["backup_sha256"], "Original backup checksum changed")
    args = ["sudo", str(engine), "haptic-table-probe", "--backup", str(backup),
            "--journal", str(directory / "helper-journal.jsonl")]
    if restore_only:
        plan["status"] = "restoring"
        durable_plan(path, plan)
        args.append("--restore")
    result = subprocess.run(args, stdout=subprocess.PIPE, text=True, check=True)
    report = json.loads(result.stdout)
    require(report.get("format") == 1 and report.get("kind") == "haptic_table_replay_result"
            and report.get("restore_only") is restore_only and report.get("restored_exactly") is True,
            "Helper did not confirm exact restoration; preserve the directory for recovery")
    durable_plan(directory / ("recovery-result.json" if restore_only else "result.json"), report)
    plan.update(status="restored_exactly", probe_passed=report.get("probe_passed") is True)
    durable_plan(path, plan)
    print("Original captured wheel state and paired mappings verified exactly; no stage selection changed.")
    if not restore_only:
        if plan["probe_passed"]:
            print("Native table framing was acknowledged and existing points read back unchanged.")
        else:
            for field, label in (("probe_acknowledgement_error", "Replay acknowledgement"),
                                 ("probe_verification_error", "Replay readback")):
                if report.get(field):
                    print(f"{label}: {report[field]}")
            recovery = report.get("recovery", {})
            if recovery.get("restore_acknowledgement_error"):
                print(f"Original-byte replay acknowledgement: {recovery['restore_acknowledgement_error']}")
            print("Table replay did not pass. Original state is verified; do not retry another packet length.")
    print(f"Private evidence: {directory}")


def run(engine, directory):
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    plan = {"format": 1, "kind": "haptic_table_replay", "status": "preparing",
            "engine": str(engine), "engine_sha256": checksum(engine)}
    path = directory / "plan.json"
    durable_plan(path, plan)
    with Session(engine) as session:
        require(session.hello.get("haptic_settings") is True, "Requires wired Naga V2 Pro and twelve-button plate")
        known = command(session, "haptic_read", "haptic_snapshot", slot=None)["snapshot"]
        state = known["state"]
        require(state["stages"][state["active_position"] - 1] == 0x85 and 0x86 not in state["stages"],
                "Keep Smooth Scroll selected and Custom disabled for this unchanged-point replay")
        prepared = command(session, "haptic_prepare", "haptic_prepared", known=known,
                           edit={"active_position": state["active_position"], "stages": state["stages"]})
        backup = saved(session, directory, prepared, "original-wheel.json")
        plan.update(backup_sha256=checksum(backup), slot=state["slot"])
    # No session commit. The bounded replay helper independently rechecks all state.
    plan["status"] = "probing"
    durable_plan(path, plan)
    invoke(directory, restore_only=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "restore"))
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--engine", type=Path, default=ROOT / "target/debug/naga-macros")
    args = parser.parse_args()
    directory = (args.directory or config_path().parent / f"haptic-table-replay-{time.time_ns()}").resolve()
    try:
        if args.action == "restore":
            require(args.directory is not None, "Restoration requires the original --directory")
            invoke(directory, restore_only=True)
        else:
            run(args.engine.resolve(), directory)
    except (OSError, ValueError, KeyError, TypeError, IndexError, subprocess.SubprocessError, KeyboardInterrupt, EOFError) as error:
        parser.exit(1, f"Table replay stopped: {error}\nPrivate state: {directory}\n"
                    f"Preserve the helper and all evidence. If the plan is probing/restoring, use only:\n"
                    f"python3 scripts/probe_haptic_table.py restore --directory '{directory}'\n")


if __name__ == "__main__":
    main()
