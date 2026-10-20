#!/usr/bin/env python3
"""One-attempt recovery of the captured grid-1 layer echo using its original record."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from onboard_controlled_test import durable_plan, require
from inspect_layer_recovery import checksum
from wheel_controlled_test import config_path


def recover(directory, evidence_path=None, engine=None):
    engine = engine or ROOT / "target/debug/naga-macros"
    status_path = directory / "status.json"
    status = json.loads(status_path.read_text())
    require(status["stage"] in ("applying", "restoring"), "Recovery requires a failed, attempted trial")
    require(checksum(directory / "plan.json") == status["plan_sha256"], "Original plan checksum changed")
    plan = json.loads((directory / "plan.json").read_text())
    require(checksum(directory / "original.json") == plan["backup_sha256"], "Original paired backup checksum changed")
    require(checksum(Path(plan["engine"])) == plan["engine_sha256"], "Original release helper checksum changed")
    require(not list(directory.glob("echo-recovery-*/attempt.jsonl"))
            and not (directory / "echo-recovery-status.json").exists(),
            "Echo recovery was already attempted; collect new read-only evidence instead of retrying")
    if evidence_path is None:
        candidates = sorted(directory.glob("selector-evidence-*/observations.json"))
        require(bool(candidates), "Collect selector evidence first")
        evidence_path = candidates[-1]
    evidence = json.loads(evidence_path.read_text())
    backup = json.loads((directory / "original.json").read_text())
    require(evidence["kind"] == "unverified_selector_observations"
            and evidence["bank_identity_verified"] is False and evidence["slot"] == 1,
            "Recovery requires the captured slot-1 selector evidence")
    target = directory / f"echo-recovery-{time.time_ns()}"
    target.mkdir(mode=0o700, exist_ok=False)
    for name, content in (("original.json", backup), ("observations.json", evidence)):
        path = target / name
        durable_plan(path, content)
        require(json.loads(path.read_text()) == content, "Recovery input checkpoint failed")
    manifest = {"format": 1, "engine": str(engine), "engine_sha256": checksum(engine),
                "original_sha256": checksum(target / "original.json"),
                "evidence_sha256": checksum(target / "observations.json"),
                "original_trial_plan_sha256": status["plan_sha256"], "stage": "attempting"}
    # The unprivileged recovery checkpoint must be durable before invoking the
    # helper. Its create-new journal supplies a second no-retry boundary.
    durable_plan(directory / "echo-recovery-status.json", manifest)
    print("Checking fresh evidence and all backed-up slots before one original grid-1 normal write. This can take about 30 seconds.", flush=True)
    subprocess.run(["sudo", str(engine), "onboard-recover-grid-one-echo",
                    "--backup", str(target / "original.json"),
                    "--evidence", str(target / "observations.json"),
                    "--journal", str(target / "attempt.jsonl")], check=True)
    manifest["stage"] = "restored_exactly"
    durable_plan(directory / "echo-recovery-status.json", manifest)
    # Do not modify the original plan, backups, runners, or release build.
    require(checksum(directory / "plan.json") == status["plan_sha256"], "Original plan changed during repair")
    status.update(stage="restored", echo_recovery=str(target))
    durable_plan(status_path, status)
    print("Helper exited. Check original grid-1 output, DPI cycling and left/right/middle clicks, then reconnect USB and repeat.")
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=config_path().parent / "hypershift-test")
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    try:
        recover(args.directory.expanduser().resolve(), args.evidence)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Echo recovery stopped: {error}\nDo not repeat apply or recovery. Keep all backups and collect fresh selector evidence if a write was attempted.\n")


if __name__ == "__main__":
    main()
