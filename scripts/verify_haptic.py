#!/usr/bin/env python3
"""Recheck a completed wheel trial using getters only; never reapplies or restores settings."""
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
from inspect_haptic import query
from onboard_controlled_test import durable_plan, require


def without_path(value, device_key="device"):
    value = copy.deepcopy(value)
    value[device_key].pop("path", None)
    return value


def paired_signature(value):
    value = copy.deepcopy(value)
    value["normal"] = without_path(value["normal"])
    return value


def verify(directory):
    plan = json.loads((directory / "plan.json").read_text())
    require(plan["status"] == "restored_exactly", "This check is for a completed, restored trial")
    engine = Path(plan["engine"])
    require(hashlib.sha256(engine.read_bytes()).hexdigest() == plan["engine_sha256"],
            "Trial engine changed; no device queries sent")
    backup_path = directory / "original-wheel.json"
    require(hashlib.sha256(backup_path.read_bytes()).hexdigest() == plan["backup_sha256"],
            "Original backup checksum changed; no device queries sent")
    backup = json.loads(backup_path.read_text())
    require(backup["format"] == 1 and backup["kind"] == "haptic_settings_backup"
            and [s["slot"] for s in backup["slots"]] == backup["guard"]["slots"],
            "Incomplete wheel backup")
    results = []
    for before in backup["slots"]:
        slot = before["slot"]
        first = query(engine, "haptic-read", "--slot", str(slot))
        mappings = query(engine, "onboard-layers", "--slot", str(slot))
        second = query(engine, "haptic-read", "--slot", str(slot))
        require(first["kind"] == second["kind"] == "haptic_diagnostic"
                and first["format"] == second["format"] == 1,
                "Unexpected wheel export")
        expected = next(s["state"] for s in backup["mappings"]["slots"] if s["state"]["normal"]["slot"] == slot)
        guard_matches = without_path(first["guard"]) == without_path(backup["guard"])
        stable = without_path(first["guard"]) == without_path(second["guard"]) and first["state"] == second["state"]
        changed = sorted(key for key in before.keys() | first["state"].keys() if before.get(key) != first["state"].get(key))
        results.append({"slot": slot, "guard_matches": guard_matches, "stable": stable,
                        "changed_wheel_fields": changed,
                        "paired_mappings_match": paired_signature(mappings) == paired_signature(expected),
                        "before_active_position": before["active_position"],
                        "current_active_position": first["state"]["active_position"],
                        "snapshot": first, "second_snapshot": second, "mappings": mappings})
    matches = all(r["guard_matches"] and r["stable"] and not r["changed_wheel_fields"]
                  and r["paired_mappings_match"] for r in results)
    receipt = {"format": 1, "kind": "haptic_post_restore_readonly_check", "matches_original": matches,
               "scope": "captured wheel fields and paired mappings; unavailable metadata and physical feel are not verified",
               "slots": results}
    path = directory / f"post-restore-check-{time.time_ns()}.json"
    durable_plan(path, receipt)
    return path, receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    try:
        path, result = verify(args.directory)
    except (OSError, ValueError, KeyError, TypeError, StopIteration, subprocess.SubprocessError) as error:
        parser.exit(1, f"Read-only wheel check stopped: {error}\nNo settings writes were requested.\n")
    for slot in result["slots"]:
        print(f"Slot {slot['slot']}: active position {slot['before_active_position']} -> {slot['current_active_position']}; "
              f"changed wheel fields: {', '.join(slot['changed_wheel_fields']) or 'none'}; "
              f"identity/state match: {slot['guard_matches']}; stable: {slot['stable']}; "
              f"paired mappings match: {slot['paired_mappings_match']}")
    print("All captured settings still match the original." if result["matches_original"] else "A difference or unstable reading was found; keep this evidence for review.")
    print("No settings writes were requested. Physical feel and unavailable inactive metadata remain unverified.")
    print(f"Private evidence: {path}")


if __name__ == "__main__":
    main()
