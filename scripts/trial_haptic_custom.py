#!/usr/bin/env python3
"""Test Custom with existing CW/CCW curves and constant unit velocity, then restore."""
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
from haptic_test import ask_match
from wheel_controlled_test import config_path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def invoke(directory, *, restore):
    path = directory / "plan.json"
    plan = json.loads(path.read_text())
    require(plan.get("format") == 1 and plan.get("kind") == "haptic_unit_velocity_trial"
            and plan["status"] in ("applying", "applied", "restoring"), "No outstanding matching trial")
    engine = Path(plan["engine"])
    backup = directory / "original-wheel.json"
    require(digest(engine) == plan["engine_sha256"], "Helper changed; preserve the trial for recovery")
    require(digest(backup) == plan["backup_sha256"], "Original independent checkpoint changed")
    if restore:
        plan["status"] = "restoring"
        durable_plan(path, plan)
    args = ["sudo", str(engine), "haptic-unit-velocity-trial", "--checkpoint", str(backup),
            "--journal", str(directory / "helper-journal.jsonl")]
    if restore:
        args.append("--restore")
    result = subprocess.run(args, stdout=subprocess.PIPE, text=True, check=True)
    report = json.loads(result.stdout)
    require(report.get("format") == 1, "Unexpected trial receipt")
    if restore:
        require(report.get("kind") == "haptic_independent_replay_result"
                and report.get("restored_exactly") is True
                and report.get("active_table_verification") == "selector_zero", "Independent restoration not confirmed")
        completed = True
    else:
        require(report.get("kind") == "haptic_unit_velocity_trial_result", "Unexpected apply receipt")
        completed = report.get("restored_exactly") is True
        require((report.get("applied") is True and not completed
                 and report.get("active_table_verification") == "selector_zero")
                or (report.get("applied") is False and completed), "Incomplete trial outcome")
    durable_plan(directory / ("restored.json" if restore else "applied.json"), report)
    plan["status"] = "restored_exactly" if completed else "applied"
    durable_plan(path, plan)
    return report


def run(engine, directory, checkpoint):
    raw = checkpoint.read_bytes()
    data = json.loads(raw)
    require(data.get("format") == 1 and data.get("kind") == "haptic_independent_checkpoint",
            "Requires an independent checkpoint of the current Smooth Scroll baseline")
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    backup = directory / "original-wheel.json"
    durable_plan(backup, data)
    require(json.loads(backup.read_text()) == data, "Independent checkpoint readback differs")
    path = directory / "plan.json"
    durable_plan(path, {"format": 1, "kind": "haptic_unit_velocity_trial", "status": "applying",
                        "engine": str(engine), "engine_sha256": digest(engine),
                        "backup_sha256": digest(backup), "source_sha256": hashlib.sha256(raw).hexdigest()})
    try:
        print("Uploading the fixed velocity trial and selecting Custom; keep USB connected until the feel prompt.", flush=True)
        report = invoke(directory, restore=False)
        if not report["applied"]:
            print(f"Trial did not apply; current captured state restored exactly: {report.get('apply_error', '')}")
            return
        print("Custom selected. Existing up/down resistance curves are unchanged; speed-based strength is now constant.")
        print("Try slow and fast turns in both directions. Check ordinary scrolling and primary clicks.")
        print("Do not press the profile or scroll-mode buttons during this trial.")
        print("Reconnect USB now, then check feel, scrolling and clicks again. Keep the twelve-button plate attached.")
        answer = input("Describe feel and reconnect results, then press Enter to restore (empty = unverified; q stops safely): ").strip()
        if answer.lower() in ("q", "quit"):
            raise KeyboardInterrupt
        plan = json.loads(path.read_text())
        plan["user_observation"] = answer or "unverified"
        durable_plan(path, plan)
    finally:
        plan = json.loads(path.read_text())
        if plan["status"] in ("applying", "applied", "restoring"):
            if (directory / "helper-journal.jsonl").exists():
                print("Restoring original selection and independently captured tables…", flush=True)
                invoke(directory, restore=True)
            else:
                plan["status"] = "stopped_before_helper_journal"
                durable_plan(path, plan)
    print("Original captured tables and Smooth Scroll selection restored exactly; paired mappings and other slots checked.")
    observation = ask_match("Is the original Smooth Scroll feel back, with normal scrolling and primary clicks?")
    plan = json.loads(path.read_text())
    plan["original_feel_after_restore"] = observation
    durable_plan(path, plan)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "restore"))
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--engine", type=Path, default=ROOT / "target/debug/naga-macros")
    args = parser.parse_args()
    directory = (args.directory or config_path().parent / f"haptic-custom-trial-{time.time_ns()}").expanduser().resolve()
    try:
        if args.action == "restore":
            require(args.directory is not None, "Restore requires the original --directory")
            invoke(directory, restore=True)
            print("Original captured tables and selection restored exactly. Check original feel, scrolling and clicks separately.")
        else:
            require(args.checkpoint is not None, "Run requires --checkpoint")
            run(args.engine.resolve(), directory, args.checkpoint.expanduser().resolve())
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, KeyboardInterrupt, EOFError) as error:
        parser.exit(1, f"Custom trial stopped: {error}\nPrivate state: {directory}\n"
                    "Read plan.json status before any retry. Keep the same helper for an outstanding trial.\n"
                    f"Recovery: python3 scripts/trial_haptic_custom.py restore --directory '{directory}'\n")
    print(f"Private trial directory: {directory}")


if __name__ == "__main__":
    main()
