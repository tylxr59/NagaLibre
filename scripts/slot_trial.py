#!/usr/bin/env python3
"""Prepare or run the temporary onboard-slot allocation experiment.

Preparation issues getters only. Run creates and removes one unused slot and
never writes button mappings. Private plans include serials and bindings.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "gui"))
from model import config_path, save_profile


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def durable(path, data):
    save_profile(path, data)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_slot(engine, slot=None):
    command = ["sudo", str(engine), "onboard-read"]
    if slot is not None:
        command += ["--slot", str(slot)]
    return json.loads(subprocess.check_output(command, text=True))


def prepare(directory, engine):
    directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    engine_hash = digest(engine)
    initial = read_slot(engine)
    require(initial["device"]["product"] == 0xA7 and initial["mode"] == [0, 0],
            "Requires wired Naga V2 Pro in normal mode")
    require(initial["active"] in initial["slots"], "Active slot must be initialized")
    capacity = initial.get("slot_capacity")
    require(isinstance(capacity, int) and 1 <= capacity <= 5, "Capacity unavailable")
    unused = [n for n in range(2, capacity + 1) if n not in initial["slots"]]
    require(unused, "No unused slot for the experiment")
    snapshots = [read_slot(engine, n) for n in initial["slots"]]
    for snapshot in snapshots:
        for key in ("device", "slots", "slot_capacity", "active", "mode"):
            require(snapshot[key] == initial[key], "Mouse changed while backing up")
    require(digest(engine) == engine_hash, "Engine changed while preparing")
    plan_path = directory / "plan.json"
    durable(plan_path, {"format": 1, "target": unused[0], "snapshots": snapshots})
    manifest = {
        "status": "prepared", "engine": str(engine), "engine_sha256": engine_hash,
        "runner_sha256": digest(Path(__file__).resolve()),
        "plan_sha256": digest(plan_path),
    }
    durable(directory / "manifest.json", manifest)
    print(f"Read-only preparation complete: {len(snapshots)} of {capacity} slots initialized; "
          f"active slot {initial['active']}; temporary target {unused[0]}.")
    print("Plan: allocate target, read defaults, remove target, verify every original slot. "
          "If allocation changes the active slot, restore the original before removal. "
          "No button mappings or device mode will be written.")
    print(f"Private backup: {directory}")
    print(f"Plan SHA-256: {manifest['plan_sha256']}")
    print("No settings were changed. Preparation complete; run uses the saved plan.")


def run(directory):
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    plan_path = directory / "plan.json"
    require(manifest["status"] == "prepared", "Trial already attempted; do not repeat")
    require(manifest["plan_sha256"] == digest(plan_path), "Plan checksum mismatch")
    engine = Path(manifest["engine"])
    require(digest(engine) == manifest["engine_sha256"], "Engine changed; prepare a fresh plan")
    require(digest(Path(__file__).resolve()) == manifest["runner_sha256"], "Runner changed; prepare a fresh plan")
    plan = json.loads(plan_path.read_text())
    journal = directory / "journal.jsonl"
    require(not journal.exists(), "Journal already exists; inspect the previous attempt")
    # Consumed durably before launching: an interrupted write is never retried.
    manifest["status"] = "attempted"
    durable(manifest_path, manifest)
    result = subprocess.run([
        "sudo", str(engine), "onboard-slot-trial", "--plan", str(plan_path),
        "--journal", str(journal),
    ], check=False)
    manifest["status"] = "completed" if result.returncode == 0 else "inspect_required"
    durable(manifest_path, manifest)
    if journal.exists():
        # The privileged helper creates a root-owned private journal. Preserve
        # an unprivileged durable copy for review, without printing serials.
        contents = subprocess.check_output(["sudo", "cat", str(journal)], text=True)
        events = [json.loads(line) for line in contents.splitlines()]
        durable(directory / "receipt.json", events)
        for event in events:
            if event["stage"] == "defaults_read":
                snapshot = event["snapshot"]
                print(json.dumps({"new_slot": snapshot["slot"], "primary": snapshot["primary"],
                                  "middle": event["middle"], "buttons": snapshot["buttons"]}, indent=2))
    require(result.returncode == 0,
            "Trial failed. Keep the private journal and backups; inspect state before further writes.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "run"))
    parser.add_argument("--directory", type=Path,
                        default=config_path().parent / "slot-creation-trial")
    args = parser.parse_args()
    try:
        directory = args.directory.expanduser().resolve()
        if args.stage == "prepare":
            prepare(directory, (ROOT / "target/release/naga-macros").resolve())
        else:
            run(directory)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Slot trial stopped: {error}\n")


if __name__ == "__main__":
    main()
