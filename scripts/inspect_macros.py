#!/usr/bin/env python3
"""Privately capture native onboard macro storage using getters only."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from onboard_controlled_test import durable_plan, require
from wheel_controlled_test import config_path
from inspect_haptic import mappings, query, signature


def build_checkpoint(engine, path):
    # Offline validation runs as the user; no device access or sudo is needed.
    result = subprocess.run([str(engine), "onboard-macro-checkpoint", str(path)],
                            check=True, stdout=subprocess.PIPE, text=True)
    return json.loads(result.stdout)


def capture(engine, directory):
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    before = mappings(engine)
    durable_plan(directory / "mappings-before.json", {
        "format": 1, "kind": "macro_inspection_mapping_checkpoint", "slots": before})
    path = directory / "macros.json"
    try:
        print("Reading native macro inventory, metadata and data twice…", file=sys.stderr, flush=True)
        result = query(engine, "onboard-macros")
        require(result.get("format") == 1 and result.get("kind") == "onboard_macro_diagnostic"
                and result.get("restorable") is False, "Unexpected macro diagnostic")
        require([signature(s) for s in result["mappings"]] == [signature(s) for s in before],
                "Macro diagnostic mappings differ from the durable checkpoint")
        durable_plan(path, result)
        require(json.loads(path.read_text()) == result, "Macro diagnostic file readback differs")
        checkpoint = build_checkpoint(engine, path)
        require(checkpoint.get("kind") == "onboard_macro_storage_checkpoint"
                and checkpoint.get("format") == 1
                and checkpoint.get("complete_profile") is False
                and checkpoint.get("restoration_implemented") is False
                and checkpoint.get("inspection") == result, "Invalid macro storage checkpoint")
        checkpoint_path = directory / "macro-checkpoint.json"
        durable_plan(checkpoint_path, checkpoint)
        require(json.loads(checkpoint_path.read_text()) == checkpoint,
                "Macro checkpoint file readback differs")
    finally:
        after = mappings(engine)
        durable_plan(directory / "mappings-after.json", {"format": 1, "slots": after})
        require([signature(s) for s in after] == [signature(s) for s in before],
                "Paired mappings changed during macro inspection")
    return path, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, default=ROOT / "target/release/naga-macros")
    args = parser.parse_args()
    directory = config_path().parent / f"macro-inspection-{time.time_ns()}"
    try:
        path, result = capture(args.engine.resolve(), directory)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Macro inspection stopped: {error}\nPrivate directory: {directory}\nNo settings writes were requested.\n")
    storage = result["storage"]
    print("Macro storage read twice; scoped mappings and mouse state checked unchanged.")
    print(f"Stored macros: {storage['stored_count']}; reported capacity: {storage['max_macros']}.")
    print(f"Storage: {storage['storage_bytes']} bytes; available: {storage['free_bytes']}; reclaimable: {storage['reclaimable_bytes']}.")
    print(f"Private export: {path}")
    print(f"Validated content checkpoint: {path.parent / 'macro-checkpoint.json'}")
    print(f"SHA256: {hashlib.sha256(path.read_bytes()).hexdigest()}")
    print("Diagnostic only; restoration is not implemented. Export contains private macro contents and device identity.")


if __name__ == "__main__":
    main()
