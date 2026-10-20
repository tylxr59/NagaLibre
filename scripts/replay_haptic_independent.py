#!/usr/bin/env python3
"""Replay current independently captured Custom tables, then recover and verify them.

Smooth Scroll stays selected. No generated curves, metadata, bindings or slot
activation writes. This preserves the checkpoint's current data, including any
overlap; it cannot restore unknown pre-replay historical settings.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from inspect_haptic import durable_plan, require
from replay_haptic_upload import invoke
from wheel_controlled_test import config_path


def run(engine, directory, checkpoint):
    raw = checkpoint.read_bytes()
    data = json.loads(raw)
    require(data.get("format") == 1 and data.get("kind") == "haptic_independent_checkpoint",
            "Requires the independent active-slot checkpoint; legacy backups are rejected")
    require(data.get("table_views", {}).get("stable") is True, "Checkpoint views are not stable")
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    backup = directory / "original-wheel.json"
    durable_plan(backup, data)
    require(json.loads(backup.read_text()) == data, "Independent checkpoint copy readback differs")
    plan = {"format": 1, "kind": "haptic_independent_replay", "status": "probing",
            "engine": str(engine), "engine_sha256": hashlib.sha256(engine.read_bytes()).hexdigest(),
            "backup_sha256": hashlib.sha256(backup.read_bytes()).hexdigest(),
            "source_checkpoint": str(checkpoint), "source_sha256": hashlib.sha256(raw).hexdigest()}
    durable_plan(directory / "plan.json", plan)
    invoke(directory, restore_only=False, independent=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "restore"))
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--engine", type=Path, default=ROOT / "target/debug/naga-macros")
    args = parser.parse_args()
    directory = (args.directory or config_path().parent / f"haptic-independent-replay-{time.time_ns()}").expanduser().resolve()
    try:
        if args.action == "restore":
            require(args.directory is not None, "Recovery requires the original --directory")
            invoke(directory, restore_only=True, independent=True)
        else:
            require(args.checkpoint is not None, "Run requires the original independent --checkpoint")
            run(args.engine.resolve(), directory, args.checkpoint.expanduser().resolve())
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, KeyboardInterrupt) as error:
        parser.exit(1, f"Independent replay stopped: {error}\nPrivate state: {directory}\n"
                    f"Preserve the helper and evidence. For a probing/restoring plan with an outstanding journal, use only:\n"
                    f"python3 scripts/replay_haptic_independent.py restore --directory '{directory}'\n")


if __name__ == "__main__":
    main()
