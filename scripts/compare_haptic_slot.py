#!/usr/bin/env python3
"""Compare an existing slot's table views, then restore the original active slot.

Only the established paired slot-activation transaction may write. No wheel,
mapping, mode, slot-allocation or deletion setters are used.
"""
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
from inspect_haptic import mappings, query, signature, progress, durable_plan, require
from wheel_controlled_test import WheelSession, config_path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_pairs(checkpoint, active):
    result = copy.deepcopy(checkpoint["pairs"])
    for state in result:
        state["normal"]["active"] = active
    return result


def check_guard(report, checkpoint, active):
    normal = checkpoint["pairs"][0]["normal"]
    expected = {"device": normal["device"], "mode": normal["mode"],
                "slots": normal["slots"], "capacity": normal["slot_capacity"],
                "active": active, "module_id": 3}
    require(report["guard"] == expected, "Wheel diagnostic belongs to different device/state")


def views(engine, checkpoint, active):
    report = query(engine, "haptic-table-views")
    require(report.get("format") == 1 and report.get("kind") == "unverified_haptic_table_views"
            and report.get("stable") is True, "Unexpected table-view response")
    check_guard(report, checkpoint, active)
    return report


def wheels(engine, checkpoint):
    result = []
    active = checkpoint["pairs"][0]["normal"]["active"]
    for slot in checkpoint["pairs"][0]["normal"]["slots"]:
        progress(f"  Reading reported wheel state for slot {slot} twice…")
        report = query(engine, "haptic-read", "--slot", str(slot))
        require(report.get("format") == 1 and report.get("kind") == "haptic_diagnostic"
                and report["state"]["slot"] == slot, "Unexpected wheel response")
        check_guard(report, checkpoint, active)
        result.append(report)
    return result


def response(session, name, event_type, **kwargs):
    event = session.command(name, **kwargs)
    require(event.get("type") == event_type, f"Unexpected {name} response")
    return event


def activate(engine, directory, plan, checkpoint, current, target, phase):
    require(digest(engine) == plan["engine_sha256"], "Engine changed before activation")
    require(digest(directory / "checkpoint.json") == plan["checkpoint_sha256"],
            "Checkpoint changed before activation")
    expected = expected_pairs(checkpoint, current)
    with WheelSession(engine) as session:
        read = response(session, "onboard_layers_read", "onboard_layers_snapshot", slot=None)["snapshot"]
        require(signature(read) == signature(next(s for s in expected if s["normal"]["slot"] == current)),
                "Active paired state differs from checkpoint; no activation requested")
        prepared = response(session, "onboard_activate", "onboard_layers_activation_prepared", slot=target)
        backup = prepared["backup"]
        require(backup.get("format") == 1 and backup.get("kind") == "paired_mapping_backup"
                and [signature(s["state"]) for s in backup["slots"]] == [signature(s) for s in expected],
                "Prepared all-slot paired backup differs from checkpoint")
        path = directory / f"{phase}-paired-backup.json"
        durable_plan(path, backup)
        require(json.loads(path.read_text()) == backup, "Prepared backup readback differs")
        plan["status"] = phase
        plan["activation_backup"] = path.name
        durable_plan(directory / "plan.json", plan)
        # A failed acknowledgement may already have switched slots. The caller
        # must run restoration even when this command raises.
        saved = response(session, "onboard_commit", "onboard_layers_activated", token=prepared["token"])
        target_expected = next(s for s in expected_pairs(checkpoint, target) if s["normal"]["slot"] == target)
        require(signature(saved["snapshot"]) == signature(target_expected), "Activated snapshot differs")


def load(directory):
    plan = json.loads((directory / "plan.json").read_text())
    require(plan.get("format") == 1 and plan.get("kind") == "haptic_slot_comparison",
            "Not a slot-comparison plan")
    engine = Path(plan["engine"])
    require(digest(engine) == plan["engine_sha256"], "Engine changed; keep the original helper for recovery")
    path = directory / "checkpoint.json"
    require(digest(path) == plan["checkpoint_sha256"], "Private checkpoint checksum changed")
    return engine, plan, json.loads(path.read_text())


def restore(directory):
    engine, plan, checkpoint = load(directory)
    require(plan["status"] in ("switching", "inspecting", "restoring", "verification_failed"),
            "No outstanding activation in this plan")
    original, target = plan["original"], plan["target"]
    current = mappings(engine)
    active = current[0]["normal"]["active"]
    require(active in (original, target), "Another slot became active; inspect the private plan before recovery")
    require([signature(s) for s in current] == [signature(s) for s in expected_pairs(checkpoint, active)],
            "Paired state changed; automatic activation stopped")
    if active != original:
        progress(f"Restoring original active slot {original}…")
        activate(engine, directory, plan, checkpoint, active, original, "restoring")
    plan["status"] = "verification_failed"
    durable_plan(directory / "plan.json", plan)
    # Restoration writes only the active-slot selector; discrepancies in wheel
    # getters are recorded, never 'fixed' by uploading ambiguous curve data.
    after = {"pairs": mappings(engine, checkpoint["pairs"]), "wheels": wheels(engine, checkpoint),
             "views": views(engine, checkpoint, original)}
    durable_plan(directory / "after-restoration.json", after)
    require(after == checkpoint, "Original slot selected, but captured state differs; no curve recovery was attempted")
    plan["status"] = "restored_captured_state"
    durable_plan(directory / "plan.json", plan)


def run(engine, directory, target):
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    plan = {"format": 1, "kind": "haptic_slot_comparison", "engine": str(engine),
            "engine_sha256": digest(engine), "target": target, "status": "preparing"}
    durable_plan(directory / "plan.json", plan)
    checkpoint = {"pairs": mappings(engine)}
    normal = checkpoint["pairs"][0]["normal"]
    original = normal["active"]
    require(target in normal["slots"] and target != original, "Choose an existing inactive slot")
    plan["original"] = original
    checkpoint["wheels"] = wheels(engine, checkpoint)
    checkpoint["views"] = views(engine, checkpoint, original)
    path = directory / "checkpoint.json"
    durable_plan(path, checkpoint)
    require(json.loads(path.read_text()) == checkpoint, "Checkpoint readback differs")
    plan["checkpoint_sha256"] = digest(path)
    plan["status"] = "prepared"
    durable_plan(directory / "plan.json", plan)
    try:
        progress(f"Temporarily activating existing slot {target}; no curve or binding uploads…")
        activate(engine, directory, plan, checkpoint, original, target, "switching")
        plan["status"] = "inspecting"
        durable_plan(directory / "plan.json", plan)
        report = views(engine, checkpoint, target)
        stored = next(w["state"] for w in checkpoint["wheels"] if w["state"]["slot"] == target)
        require(report["stored"]["configuration"] == stored["configuration"]
                and report["stored"]["tables"] == stored["tables"], "Target stored tables changed across activation")
        durable_plan(directory / "target-views.json", report)
        mappings(engine, expected_pairs(checkpoint, target))
        plan["comparison_completed"] = True
        durable_plan(directory / "plan.json", plan)
    finally:
        # Reload durable status: activation backup or plan fsync can fail before
        # any commit. Such a failure must not trigger a new settings operation.
        saved = json.loads((directory / "plan.json").read_text())
        if saved["status"] in ("switching", "inspecting", "restoring"):
            restore(directory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    trial = sub.add_parser("run")
    trial.add_argument("--slot", type=int, required=True, choices=range(1, 6))
    trial.add_argument("--engine", type=Path, default=ROOT / "target/debug/naga-macros")
    recovery = sub.add_parser("restore")
    recovery.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    directory = (args.directory.expanduser().resolve() if args.operation == "restore" else
                 config_path().parent / f"haptic-slot-comparison-{time.time_ns()}")
    try:
        if args.operation == "restore":
            restore(directory)
        else:
            run(args.engine.resolve(), directory, args.slot)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, KeyboardInterrupt) as error:
        parser.exit(1, f"Slot comparison stopped: {error}\nPrivate evidence: {directory}\nRead plan.json status before retrying; restore is available for an outstanding activation.\n")
    print("Original active slot restored; all captured wheel replies and paired mappings match.")
    path = directory / "target-views.json"
    if path.exists():
        result = json.loads(path.read_text())
        print(f"Target stored/selector-zero table equality: {result['stored_matches_live']}")
        print(f"Target velocity matches CW prefix (stored, selector zero): {result['stored_prefix_overlap']}, {result['live_prefix_overlap']}")
    print("Only slot activation was written; no curves or bindings were uploaded. Physical feel was not tested.")
    print(f"Private evidence: {directory}")


if __name__ == "__main__":
    main()
