#!/usr/bin/env python3
"""Read the active mouse slot and durably save its unmodified private snapshot."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "gui"))
from model import config_path  # noqa: E402
from onboard import write_backup  # noqa: E402


def backup_active(engine, profile_path):
    # Elevate only the existing Rust getter; keep file ownership with the user.
    result = subprocess.run(
        ["sudo", str(engine), "onboard-read"],
        check=True, stdout=subprocess.PIPE, text=True,
    )
    snapshot = json.loads(result.stdout)
    if snapshot["slot"] != snapshot["active"]:
        raise ValueError("Active slot is not initialized; refusing to back up a substitute slot.")
    path = write_backup(profile_path, snapshot, str(time.time_ns()))
    if json.loads(path.read_text()) != snapshot:
        raise ValueError("Backup readback did not match the mouse snapshot.")
    return path, snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        path, snapshot = backup_active(ROOT / "target/release/naga-macros", config_path())
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Backup failed: {error}\n")
    print(f"Durable backup: {path}")
    print(f"SHA256: {hashlib.sha256(path.read_bytes()).hexdigest()}")
    print(f"File permissions: {path.stat().st_mode & 0o777:03o}")
    print(f"Active slot: {snapshot['active']}; mode: {snapshot['mode']}")
    print("Primary actions:", [(b["button"], b["category"], b["data"]) for b in snapshot["primary"]])
    print("Side actions:", [(b["button"], b["category"], b["data"]) for b in snapshot["buttons"]])
    print("Original raw records preserved:", sum("raw_record" in b for b in snapshot["buttons"]))
    print("Only getters were issued; no mouse settings changed.")


if __name__ == "__main__":
    main()
