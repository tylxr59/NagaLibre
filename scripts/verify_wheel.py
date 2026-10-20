#!/usr/bin/env python3
"""Guide physical wheel remap checks locally, restoring after every trial."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

from wheel_controlled_test import (
    NAMES, ROOT, config_path, durable_plan, prepare, run_stage,
)
from onboard import stored_label


def observe(prompt, ask=input):
    while True:
        reply = ask(prompt + " [yes/no/skip]: ").strip().lower()
        if reply in ("yes", "no", "skip"):
            return reply
        print("Enter yes, no, or skip. Skipped checks remain unverified.")


def trial(directory, control, ask=input, prepare_trial=prepare, stage=run_stage):
    """Keep physical observations separate and attempt recovery after interruption."""
    observations = {}
    report = directory / "observations.json"

    def record(name, prompt):
        observations[name] = observe(prompt, ask)
        durable_plan(report, observations)

    prepare_trial(directory, ROOT / "target/release/naga-macros", control)
    plan = json.loads((directory / "plan.json").read_text())
    original = next(b for b in plan["original"]["controls"] if b["button"] == control)
    label = stored_label(original)
    print(f"Original stored binding for {NAMES[control]}: {label}")
    try:
        record("original_behavior", f"Try {NAMES[control]} in a suitable app. Does {label} work?")
        print(stage("apply", directory))
        record("b_output", f"In a blank text editor, does {NAMES[control]} type B?")
        record("primary_clicks", "Do left, right, and middle clicks work normally?")
        reconnected = observe(
            "Fully quit NagaLibre, unplug/reconnect the mouse by USB, and wait for it. Done?", ask)
        observations["reconnected"] = reconnected
        durable_plan(report, observations)
        if reconnected == "yes":
            record("b_after_reconnect", f"Does {NAMES[control]} still type B?")
            errors = []
            while True:
                try:
                    print(stage("verify", directory))
                    observations["reconnect_readback"] = "yes"
                    durable_plan(report, observations)
                    break
                except ValueError as error:
                    if "No matching reply to mouse command " not in str(error):
                        raise
                    errors.append(str(error))
                    durable_plan(directory / "readback_errors.json", errors)
                    print(f"Read-only verification failed: {error}")
                    retry = observe("Wake the mouse and check its USB cable. Retry the read-only check?", ask)
                    if retry != "yes":
                        observations["reconnect_readback"] = retry
                        durable_plan(report, observations)
                        break
    finally:
        # The runner consumes apply durably before commit. Even a lost reply
        # warrants recovery; a failure before that point has issued no writes.
        status = json.loads((directory / "status.json").read_text())
        if status["stage"] in ("applying", "applied", "verified", "restoring"):
            print(stage("restore", directory))
    record("restored_behavior", f"Does {NAMES[control]} have its original behavior again?")
    record("restored_primary_clicks", "Do left, right, and middle clicks still work normally?")
    return observations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--controls", nargs="+", type=int, choices=NAMES, default=[14, 15])
    parser.add_argument("--directory", type=Path)
    args = parser.parse_args()
    directory = (args.directory or config_path().parent / f"wheel-verification-{time.time_ns()}").expanduser().resolve()
    try:
        if not sys.stdin.isatty():
            raise ValueError("Run interactively in your local terminal for observations and sudo authentication")
        directory.mkdir(mode=0o700, parents=True, exist_ok=False)
        print("Keep the wired mouse and 12-button plate attached. Quit NagaLibre first.")
        print("Each trial changes one control to B, checks readback, then restores exact records.")
        print("These trials restore your existing bindings; they do not install factory defaults.")
        print(f"Private evidence: {directory}")
        for control in args.controls:
            results = trial(directory / str(control), control)
            if any(value != "yes" for value in results.values()):
                print("Some physical checks failed or were skipped. Original mapping restored; stopping for review.")
                return 1
        print("All requested physical observations passed and original tracked mappings were restored.")
        return 0
    except (EOFError, KeyboardInterrupt):
        print(f"\nInterrupted. Check the saved status before further writes: {directory}")
        return 1
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(f"Verification stopped: {error}\nKeep private backups: {directory}")
        print("If restoration did not finish, use wheel_test.py restore --directory <control-directory>.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
