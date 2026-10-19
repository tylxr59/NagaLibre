#!/usr/bin/env python3
"""Run one approved button-1-to-B test, read-only verification, or exact restore."""
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
from onboard import write_backup


def require(condition, message):
    if not condition:
        raise ValueError(message)


def wire(button):
    return button.get("raw_record", [button["category"], len(button["data"]), *button["data"], *([0] * (5 - len(button["data"])))])


def signature(snapshot):
    return (
        snapshot["format"], snapshot["device"]["product"], snapshot["device"]["serial"],
        snapshot["slots"], snapshot["active"], snapshot["slot"], snapshot["mode"],
        [(b["button"], wire(b)) for b in snapshot["primary"]],
        [(b["button"], wire(b)) for b in snapshot["buttons"]],
    )


def verify_b(snapshot, original):
    expected = json.loads(json.dumps(original))
    require(len(snapshot["buttons"]) == 12, "Incomplete side-button readback")
    first = snapshot["buttons"][0]
    require((first["button"], first["category"], first["data"]) == (1, 2, [0, 5]), "Button 1 did not read back as B")
    expected["buttons"][0] = first
    require(signature(snapshot) == signature(expected), "Another record, mode, slot or device differs from the original backup")


def durable_plan(path, plan):
    save_profile(path, plan)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class Session:
    def __init__(self, engine):
        self.engine = engine
        self.process = None

    def __enter__(self):
        self.process = subprocess.Popen(
            ["sudo", str(self.engine), "session"], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, text=True, bufsize=1,
        )
        try:
            hello = self.receive()
            require(hello.get("type") == "hello" and hello.get("protocol") == 2, "Unexpected helper protocol")
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def receive(self):
        line = self.process.stdout.readline()
        require(bool(line), "Helper exited before replying")
        event = json.loads(line)
        if event.get("type") == "error":
            raise ValueError(event["message"])
        return event

    def command(self, name, **arguments):
        self.process.stdin.write(json.dumps({"command": name, **arguments}) + "\n")
        self.process.stdin.flush()
        return self.receive()

    def __exit__(self, *_):
        if self.process:
            self.process.stdin.close()  # EOF shuts down without retaining a helper.
            self.process.wait(timeout=45)
            self.process.stdout.close()


def run_stage(stage, path, session_factory=Session):
    plan = json.loads(path.read_text())
    require(plan.get("write_approved") is True, "The controlled test has not been approved")
    backup = Path(plan["backup"])
    require(hashlib.sha256(backup.read_bytes()).hexdigest() == plan["backup_sha256"], "Original backup checksum changed")
    original = json.loads(backup.read_text())
    engine = Path(plan["engine"])
    require(hashlib.sha256(engine.read_bytes()).hexdigest() == plan["engine_sha256"], "Engine changed since the plan was approved")
    require(original["slot"] == original["active"] == plan["slot"] and original["mode"] == [0, 0], "Test requires the original active slot in normal mode")
    require([(b["button"], b["category"], b["data"]) for b in original["primary"]] == [(1, 1, [1]), (2, 1, [2])], "Backup lacks standard primary clicks")
    require(len(original["buttons"]) == 12 and original["buttons"][0]["data"] == [0, 30], "Backup is not the approved key-1 baseline")
    if stage == "apply":
        require(plan["status"] == "approved", "Apply already attempted; inspect state or restore instead of retrying")
    with session_factory(engine) as session:
        read = session.command("onboard_read", slot=original["slot"])
        require(read.get("type") == "onboard_snapshot", "Unexpected read response")
        current = read["snapshot"]
        if stage == "verify":
            verify_b(current, original)
            plan["status"] = "b_readback_verified_physical_checks_pending"
            plan["latest_snapshot"] = current
            durable_plan(path, plan)
            return "B readback verified; other eleven wire records, primary mappings, mode and active slot match the backup. Physical input and reconnect history require user confirmation."
        if stage == "apply":
            require(signature(current) == signature(original), "Mouse changed since the approved backup; no write was attempted")
            # Supply canonical actions just like the GUI; the Rust plan retains
            # the original raw records for all eleven unchanged bindings.
            desired = [{"button": b["button"], "category": b["category"], "data": b["data"]} for b in original["buttons"]]
            desired[0] = {"button": 1, "category": 2, "data": [0, 5]}
            prepared = session.command("onboard_prepare", buttons=desired)
        else:
            require(stage == "restore", "Unknown test stage")
            if signature(current) != signature(original):
                verify_b(current, original)
            prepared = session.command("onboard_restore", backup=original)
        require(prepared.get("type") == "onboard_prepared", "Unexpected prepare response")
        require(signature(prepared["backup"]) == signature(current), "Mouse changed while preparing; no write was attempted")
        recovery = write_backup(path.parent / "profiles.json", prepared["backup"], prepared["token"])
        require(json.loads(recovery.read_text()) == prepared["backup"], "Recovery backup readback failed")
        plan["status"] = "applying" if stage == "apply" else "restoring"
        plan["pre_commit_backup"] = str(recovery)
        durable_plan(path, plan)
        saved = session.command("onboard_commit", token=prepared["token"])
        require(saved.get("type") == "onboard_saved", "Unexpected commit response")
        # A second full read verifies the state independently of the save reply.
        fresh = session.command("onboard_read", slot=original["slot"])
        require(fresh.get("type") == "onboard_snapshot", "Unexpected verification response")
        after = fresh["snapshot"]
        if stage == "apply":
            verify_b(saved["snapshot"], original)
            verify_b(after, original)
            plan["status"] = "applied_physical_input_and_reconnect_pending"
        else:
            require(signature(saved["snapshot"]) == signature(original) and signature(after) == signature(original), "Restored snapshot differs from original wire records")
            plan["status"] = "restored_exactly_physical_input_check_pending"
        plan["latest_snapshot"] = after
        durable_plan(path, plan)
    return (
        "Button 1 reads as B; all other wire records, primary mappings, mode and slot verified unchanged. Helper exited. Test physical B and left/right/middle clicks, then quit NagaLibre, reconnect the mouse, and run the verify stage."
        if stage == "apply" else
        "Original backup restored; all twelve wire records, primary mappings, mode and active slot verified exactly. Helper exited. Check physical button 1 types 1 and primary clicks work."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("apply", "verify", "restore"))
    args = parser.parse_args()
    try:
        print(run_stage(args.stage, config_path().parent / "controlled-hardware-test.json"))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Controlled test stopped: {error}\nKeep the original backup. Do not repeat apply after a failed write.\n")


if __name__ == "__main__":
    main()
