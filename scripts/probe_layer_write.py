#!/usr/bin/env python3
"""Probe one secondary assignment, observe both selectors, and restore before exit."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from onboard_controlled_test import Session, durable_plan, require
from inspect_layer_recovery import checksum
from wheel_controlled_test import config_path


def run(stage, directory, engine=None, session_factory=Session):
    engine = engine or ROOT / "target/debug/naga-macros"
    if stage == "run":
        require(not directory.exists(), "Use a fresh directory; do not repeat a probe attempt")
        print("Backing up both banks of every initialized slot; no settings writes yet.", flush=True)
        with session_factory(engine) as session:
            require(session.hello.get("hypershift_transactions") is True, "Wired layer access unavailable")
            read = session.command("onboard_layers_read", slot=1)
            require(read.get("type") == "onboard_layers_snapshot", "Unexpected paired read")
            prepared = session.command("onboard_layers_prepare", edits=[])
            require(prepared.get("type") == "onboard_layers_prepared", "Unexpected backup response")
            backup = prepared["backup"]
            require(backup["kind"] == "paired_mapping_backup", "Invalid paired backup")
            # No commit token is sent to the session; preparation is getters only.
        directory.mkdir(mode=0o700, parents=True, exist_ok=False)
        path = directory / "original.json"
        durable_plan(path, backup)
        require(json.loads(path.read_text()) == backup, "Original backup readback failed")
        durable_plan(directory / "plan.json", {"engine": str(engine.resolve()),
                     "engine_sha256": checksum(engine), "backup_sha256": checksum(path),
                     "runner_sha256": checksum(Path(__file__))})
        durable_plan(directory / "status.json", {"stage": "prepared", "plan_sha256": checksum(directory / "plan.json")})
    else:
        require(stage == "restore", "Unknown probe stage")
    status = json.loads((directory / "status.json").read_text())
    require(checksum(directory / "plan.json") == status["plan_sha256"], "Probe plan changed")
    plan = json.loads((directory / "plan.json").read_text())
    engine = Path(plan["engine"])
    require(checksum(engine) == plan["engine_sha256"]
            and checksum(Path(__file__)) == plan["runner_sha256"], "Probe helper or runner changed")
    require(checksum(directory / "original.json") == plan["backup_sha256"], "Probe backup changed")
    status["stage"] = "attempting" if stage == "run" else "restoring"
    durable_plan(directory / "status.json", status)
    command = ["sudo", str(engine), "onboard-layer-write-probe",
               "--backup", str(directory / "original.json"), "--journal", str(directory / "attempt.jsonl")]
    if stage == "restore":
        command.append("--restore")
    print("Checking fresh state, then observing one secondary write and restoring both originals. Allow about 40 seconds for these checks.", flush=True)
    result = subprocess.run(command, check=True, stdout=subprocess.PIPE, text=True)
    report = json.loads(result.stdout)
    require(report["restored_exactly"] is True, "Probe restoration was not verified")
    durable_plan(directory / "result.json", report)
    status["stage"] = "restored_exactly"
    durable_plan(directory / "status.json", status)
    if report["result"].get("observed_selector_1_b_only") is True:
        print("Selector-1 read returned B while selector-0 action and other tracked state stayed original.")
        for record in report["result"]["observations"]["records"]:
            if record["logical"] == 1:
                print(f"Grid 1: requested {record['requested_layer']}, echoed {record['echoed_layer']}, raw {bytes(record['record']).hex(' ')}")
    print("Exact original paired backup restored and verified before helper exit. No Hypershift trigger was assigned.")
    print(f"Private evidence: {directory}")
    print("Check original grid 1, DPI cycling and primary clicks. This readback probe does not verify physical Hypershift behavior.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", nargs="?", choices=("run", "restore"), default="run")
    parser.add_argument("--directory", type=Path, default=config_path().parent / "layer-write-probe")
    args = parser.parse_args()
    directory = args.directory.expanduser().resolve()
    try:
        run(args.stage, directory)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Write probe stopped: {error}\nKeep backups: {directory}\nDo not repeat run. If a write was attempted and restoration failed, use the restore stage with this directory.\n")


if __name__ == "__main__":
    main()
