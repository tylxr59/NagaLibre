#!/usr/bin/env python3
"""Save a private independent active-slot wheel checkpoint using getters only."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from inspect_haptic import query, durable_plan, require, progress
from wheel_controlled_test import config_path


def capture(engine, directory):
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    helper_hash = hashlib.sha256(engine.read_bytes()).hexdigest()
    durable_plan(directory / "inspection.json", {"format": 1, "engine_sha256": helper_hash})
    progress("Capturing all-slot paired/reported state and active independent tables; getters only…")
    checkpoint = query(engine, "haptic-independent-checkpoint")
    require(checkpoint.get("format") == 1 and checkpoint.get("kind") == "haptic_independent_checkpoint"
            and checkpoint.get("table_views", {}).get("stable") is True,
            "Unexpected independent checkpoint response")
    require(hashlib.sha256(engine.read_bytes()).hexdigest() == helper_hash,
            "Helper changed during independent capture")
    path = directory / "checkpoint.json"
    durable_plan(path, checkpoint)
    require(json.loads(path.read_text()) == checkpoint, "Independent checkpoint readback differs")
    return path, checkpoint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, default=ROOT / "target/debug/naga-macros")
    args = parser.parse_args()
    directory = config_path().parent / f"haptic-independent-checkpoint-{time.time_ns()}"
    try:
        path, checkpoint = capture(args.engine.resolve(), directory)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Independent checkpoint stopped: {error}\nPrivate evidence: {directory}\nNo settings writes were requested.\n")
    views = checkpoint["table_views"]
    print(f"Independent active-slot checkpoint: slot {checkpoint['baseline']['guard']['active']}; point counts {[len(t) for t in views['live']['tables']]}")
    print(f"Stored/selector-zero equality: {views['stored_matches_live']}")
    print("All captured paired/reported state checked unchanged. No settings writes were requested.")
    print("Covers currently readable active tables; does not recover pre-replay originals or independent inactive tables.")
    print(f"Private checkpoint: {path}")
    print(f"SHA256: {hashlib.sha256(path.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
