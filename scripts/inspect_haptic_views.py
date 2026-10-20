#!/usr/bin/env python3
"""Compare stored-profile and volatile Custom table getters; never sends settings writes."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from inspect_haptic import mappings, query, durable_plan, require, progress
from wheel_controlled_test import config_path


def capture(engine, directory):
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    before = mappings(engine)
    path = directory / "mappings-before.json"
    durable_plan(path, {"format": 1, "kind": "haptic_table_views_mapping_checkpoint", "slots": before})
    require(json.loads(path.read_text())["slots"] == before, "Private mapping checkpoint readback differs")
    durable_plan(directory / "inspection.json", {"format": 1, "engine_sha256": hashlib.sha256(engine.read_bytes()).hexdigest()})
    try:
        progress("Comparing stored-profile and volatile Custom tables twice; getters only…")
        result = query(engine, "haptic-table-views")
        require(result.get("format") == 1 and result.get("kind") == "unverified_haptic_table_views"
                and result.get("stable") is True, "Unexpected table-view diagnostic")
        guard, normal = result["guard"], before[0]["normal"]
        require(guard["device"] == normal["device"] and guard["slots"] == normal["slots"]
                and guard["active"] == normal["active"] and guard["mode"] == normal["mode"]
                and guard["capacity"] == normal["slot_capacity"] and guard["module_id"] == 3,
                "Table views belong to different device/state")
        durable_plan(directory / "table-views.json", result)
    finally:
        after = mappings(engine, before)
        durable_plan(directory / "mappings-after.json", {"format": 1, "slots": after})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, default=ROOT / "target/debug/naga-macros")
    args = parser.parse_args()
    directory = config_path().parent / f"haptic-table-views-{time.time_ns()}"
    try:
        result = capture(args.engine.resolve(), directory)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Table-view inspection stopped: {error}\nPrivate evidence: {directory}\nNo settings writes were requested.\n")
    print("Stored and volatile Custom table views repeated stably; paired mappings unchanged.")
    for name in ["stored", "live"]:
        print(f"{name.capitalize()} table point counts: {[len(t) for t in result[name]['tables']]}")
    print(f"Stored velocity matches clockwise prefix: {result['stored_prefix_overlap']}")
    print(f"Volatile velocity matches clockwise prefix: {result['live_prefix_overlap']}")
    print(f"Stored/volatile table equality (up, down, velocity): {result['stored_matches_live']}")
    print("No settings writes were requested. These diagnostic views are not a restorable backup.")
    print(f"Private evidence: {directory}")


if __name__ == "__main__":
    main()
