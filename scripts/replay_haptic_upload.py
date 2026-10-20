#!/usr/bin/env python3
"""Replay the full original Custom configuration and all three tables, with exact recovery."""
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


def invoke(directory, *, restore_only, independent=False):
    path = directory / "plan.json"
    plan = json.loads(path.read_text())
    kind = "haptic_independent_replay" if independent else "haptic_upload_replay"
    require(plan.get("format") == 1 and plan.get("kind") == kind, "Not a matching complete-upload replay plan")
    require(plan["status"] in ("probing", "restoring"), "No outstanding full upload; do not repeat a completed probe")
    engine = Path(plan["engine"])
    backup = directory / "original-wheel.json"
    require(checksum(engine) == plan["engine_sha256"], "Helper changed; preserve it for recovery")
    require(checksum(backup) == plan["backup_sha256"], "Original backup checksum changed")
    args = ["sudo", str(engine), "haptic-independent-replay" if independent else "haptic-upload-replay",
            "--checkpoint" if independent else "--backup", str(backup),
            "--journal", str(directory / "helper-journal.jsonl")]
    if restore_only:
        plan["status"] = "restoring"
        durable_plan(path, plan)
        args.append("--restore")
    print("Starting full original-settings upload and recovery; keep USB connected until completion.", file=sys.stderr, flush=True)
    result = subprocess.run(args, stdout=subprocess.PIPE, text=True, check=True)
    report = json.loads(result.stdout)
    require(report.get("format") == 1 and report.get("kind") == f"{kind}_result"
            and report.get("restore_only") is restore_only and report.get("restored_exactly") is True,
            "Helper did not confirm exact restoration; preserve the directory for recovery")
    if independent:
        require(report.get("active_table_verification") == "selector_zero",
                "Helper did not confirm independent active-table verification")
    durable_plan(directory / ("recovery-result.json" if restore_only else "result.json"), report)
    plan.update(status="restored_exactly", probe_passed=report.get("probe_passed") is True)
    durable_plan(path, plan)
    print("Complete original upload acknowledged; all captured wheel state and paired mappings verified exactly.")
    print("Smooth Scroll remains selected; Custom was not enabled.")
    if not restore_only:
        if plan["probe_passed"]:
            print("Complete unchanged-settings upload passed: configuration, clockwise, counterclockwise and velocity tables.")
        else:
            for field, label in (("probe_upload_error", "Replay upload"),
                                 ("probe_verification_error", "Replay readback")):
                if report.get(field):
                    print(f"{label}: {report[field]}")
            print("Initial upload did not pass; the complete original recovery upload and exact readback passed. Do not rerun this trial.")
    print(f"Private evidence: {directory}")


def run(engine, directory):
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    plan = {"format": 1, "kind": "haptic_upload_replay", "status": "preparing",
            "engine": str(engine), "engine_sha256": checksum(engine)}
    path = directory / "plan.json"
    durable_plan(path, plan)
    print("Preparing private paired-mapping and wheel backup; no settings writes yet…", file=sys.stderr, flush=True)
    with Session(engine) as session:
        require(session.hello.get("haptic_settings") is True, "Requires wired Naga V2 Pro and twelve-button plate")
        known = command(session, "haptic_read", "haptic_snapshot", slot=None)["snapshot"]
        state = known["state"]
        require(state["stages"][state["active_position"] - 1] == 0x85 and 0x86 not in state["stages"],
                "Keep Smooth Scroll selected and Custom disabled for this complete unchanged-settings replay")
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
    directory = (args.directory or config_path().parent / f"haptic-upload-replay-{time.time_ns()}").resolve()
    try:
        if args.action == "restore":
            require(args.directory is not None, "Restoration requires the original --directory")
            invoke(directory, restore_only=True)
        else:
            run(args.engine.resolve(), directory)
    except (OSError, ValueError, KeyError, TypeError, IndexError, subprocess.SubprocessError, KeyboardInterrupt, EOFError) as error:
        parser.exit(1, f"Full upload stopped: {error}\nPrivate state: {directory}\n"
                    f"Preserve the helper and all evidence. If the plan is probing/restoring, use only:\n"
                    f"python3 scripts/replay_haptic_upload.py restore --directory '{directory}'\n")


if __name__ == "__main__":
    main()
