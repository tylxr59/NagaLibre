#!/usr/bin/env python3
"""Back up, test one wheel control as B, verify, and restore its exact records."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "gui"))
sys.path.insert(0, str(ROOT / "scripts"))
from model import config_path, DEVICE_MODELS
from onboard import write_backup
from onboard_controlled_test import Session, durable_plan, require

NAMES = {c["button"]: c["name"].removeprefix("Wheel tilt ") for c in DEVICE_MODELS["naga_v2_pro"]["defaults"]["controls"]}
# Keep the established test description for completed left/right tilt trials.
NAMES.update({13: "left tilt", 14: "right tilt"})


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def signature(snapshot):
    snapshot = copy.deepcopy(snapshot)
    snapshot["device"].pop("path", None)
    return snapshot


class WheelSession(Session):
    def __init__(self, engine):
        super().__init__(engine)
        self.expecting_plate = False

    def __enter__(self):
        super().__enter__()
        try:
            require(self.hello.get("protocol") == 4 and self.hello.get("wheel_controls") is True,
                    "Engine does not support wheel controls")
            self.expecting_plate = True
            self.command("faceplate")
            self.expecting_plate = False
        except BaseException:
            super().__exit__(None, None, None)
            raise
        return self

    def receive(self):
        while True:
            event = super().receive()
            if event.get("type") == "faceplate":
                require(event.get("module_id") == 3 and event.get("buttons") == 12,
                        "Attach the 12-button plate; no further test commands will be sent")
                if not self.expecting_plate:
                    continue
            return event


def read(session, slot=None):
    event = session.command("onboard_read", slot=slot)
    require(event.get("type") == "onboard_snapshot", "Unexpected read response")
    return event["snapshot"]


def changed(snapshot, target):
    snapshot = copy.deepcopy(snapshot)
    for index, button in enumerate(snapshot["controls"]):
        if button["button"] == target:
            snapshot["controls"][index] = {"button": target, "category": 2, "data": [0, 5]}
            return snapshot
    raise ValueError("Missing target control")


def verify_changed(actual, original, target):
    expected = changed(original, target)
    record = next(b for b in actual["controls"] if b["button"] == target)
    require((record["category"], record["data"]) == (2, [0, 5]), "Target did not read back as B")
    # Firmware may encode the changed keyboard record differently. Everything
    # else, including unknown actions/raw bytes and capacity, stays exact.
    for i, button in enumerate(expected["controls"]):
        if button["button"] == target:
            expected["controls"][i] = copy.deepcopy(record)
    require(signature(actual) == signature(expected), "Another tracked record or device state changed")


def prepare(directory, engine, target, session_factory=WheelSession):
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    engine_hash = checksum(engine)
    with session_factory(engine) as session:
        original = read(session)
        require(original["device"]["product"] == 0xA7 and original["mode"] == [0, 0]
                and original["active"] == original["slot"], "Requires wired active slot in normal mode")
        require([(b["category"], b["data"]) for b in original["primary"]] == [(1, [1]), (1, [2])],
                "Standard primary clicks required")
        require(len(original["buttons"]) == 12 and sorted(b["button"] for b in original["controls"]) == sorted(NAMES),
                "Incomplete mapping backup")
        record = next(b for b in original["controls"] if b["button"] == target)
        require((record["category"], record["data"]) != (2, [0, 5]), "Target is already B; choose a different trial")
        snapshots = [read(session, slot) for slot in original["slots"]]
        for snapshot in snapshots:
            for key in ("device", "slots", "slot_capacity", "active", "mode"):
                require(snapshot[key] == original[key], "Mouse changed while backing up")
        require(signature(read(session, original["slot"])) == signature(original), "Active slot changed while backing up")
    require(checksum(engine) == engine_hash, "Engine changed while preparing")
    plan = {"format": 1, "target": target, "original": original, "snapshots": snapshots,
            "engine": str(engine), "engine_sha256": engine_hash,
            "runner_sha256": checksum(Path(__file__)),
            "session_sha256": checksum(ROOT / "scripts/onboard_controlled_test.py")}
    durable_plan(directory / "plan.json", plan)
    digest = checksum(directory / "plan.json")
    durable_plan(directory / "status.json", {"stage": "prepared", "plan_sha256": digest})
    print(f"Read-only preparation complete: wired mouse, active slot {original['slot']}, 12-button plate.")
    print(f"Test: change only {NAMES[target]} to B; verify every other tracked record unchanged; exit helper.")
    print("Then check physical B output and primary clicks, reconnect and verify, and restore the exact original records.")
    print(f"Private backup/plan: {directory}")
    print(f"Plan SHA-256: {digest}")
    print("No settings changed. Preparation complete; apply and restore use the saved plan.")


def run_stage(stage, directory, session_factory=WheelSession):
    status_path = directory / "status.json"
    status = json.loads(status_path.read_text())
    plan_path = directory / "plan.json"
    require(checksum(plan_path) == status["plan_sha256"], "Plan checksum changed")
    plan = json.loads(plan_path.read_text())
    engine = Path(plan["engine"])
    require(plan["format"] == 1 and plan["target"] in NAMES, "Invalid plan")
    require(checksum(engine) == plan["engine_sha256"], "Engine changed; inspect before proceeding")
    require(checksum(Path(__file__)) == plan["runner_sha256"] and
            checksum(ROOT / "scripts/onboard_controlled_test.py") == plan["session_sha256"], "Runner changed")
    if stage == "apply":
        require(status["stage"] == "prepared", "Apply already attempted; inspect/restore instead of retrying")
    else:
        require(status["stage"] in ("applying", "applied", "verified", "restoring", "restored"), "Apply has not been attempted")
    original, target = plan["original"], plan["target"]
    with session_factory(engine) as session:
        current = read(session, original["slot"])
        # Check every other initialized slot before any prepare/write.
        for expected in plan["snapshots"]:
            if expected["slot"] != original["slot"]:
                require(signature(read(session, expected["slot"])) == signature(expected), "Another slot changed; inspect manually")
        if stage == "verify":
            verify_changed(current, original, target)
            status["stage"] = "verified"
            durable_plan(status_path, status)
            return "B readback verified; other tracked records unchanged. Physical input and reconnect need your confirmation."
        # Reading another slot changes the helper's prepared-save selection.
        # Select/re-read the intended active slot before preparing a transaction.
        require(signature(read(session, original["slot"])) == signature(current),
                "Target changed while checking other slots; no prepare sent")
        if stage == "apply":
            require(signature(current) == signature(original), "Mouse changed since backup; no writes attempted")
            desired = [{"button": b["button"], "category": b["category"], "data": b["data"]} for b in original["buttons"]]
            event = session.command("onboard_prepare", buttons=desired,
                                    controls=[{"button": target, "category": 2, "data": [0, 5]}])
        else:
            if signature(current) != signature(original):
                verify_changed(current, original, target)
            event = session.command("onboard_restore", backup=original)
        require(event.get("type") == "onboard_prepared" and signature(event["backup"]) == signature(current),
                "Prepared backup differs; no commit sent")
        recovery = write_backup(directory / "profiles.json", event["backup"], event["token"])
        require(json.loads(recovery.read_text()) == event["backup"], "Recovery backup readback failed")
        status.update(stage="applying" if stage == "apply" else "restoring", recovery=str(recovery))
        durable_plan(status_path, status)
        saved = session.command("onboard_commit", token=event["token"])
        require(saved.get("type") == "onboard_saved", "Unexpected commit response; do not repeat apply")
        after = read(session, original["slot"])
        for snapshot in (saved["snapshot"], after):
            if stage == "apply":
                verify_changed(snapshot, original, target)
            else:
                require(signature(snapshot) == signature(original), "Exact restore did not verify")
        for expected in plan["snapshots"]:
            if expected["slot"] != original["slot"]:
                require(signature(read(session, expected["slot"])) == signature(expected), "Another slot changed after commit")
        status.update(stage="applied" if stage == "apply" else "restored", latest_snapshot=after)
        durable_plan(status_path, status)
    if stage == "apply":
        return f"Only {NAMES[target]} reads as B; other tracked records unchanged. Helper exited. Test in a text editor and check left/right/middle clicks."
    return "Exact original tracked records restored and verified. Helper exited. Confirm the control's original physical behavior."


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "apply", "verify", "restore"))
    parser.add_argument("--control", type=int, choices=NAMES, default=13)
    parser.add_argument("--directory", type=Path)
    args = parser.parse_args()
    directory = (args.directory or config_path().parent / f"wheel-test-{args.control}").expanduser().resolve()
    try:
        if args.stage == "prepare":
            prepare(directory, ROOT / "target/release/naga-macros", args.control)
        else:
            print(run_stage(args.stage, directory))
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Wheel test stopped: {error}\nKeep backups. Do not repeat apply after a failed write.\n")


if __name__ == "__main__":
    main()
