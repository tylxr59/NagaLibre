#!/usr/bin/env python3
"""Collect read-only selector evidence without modifying the prepared trial."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from onboard_controlled_test import durable_plan, require, wire
from wheel_controlled_test import config_path


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capture(directory, engine):
    status = json.loads((directory / "status.json").read_text())
    require(checksum(directory / "plan.json") == status["plan_sha256"], "Plan checksum changed")
    plan = json.loads((directory / "plan.json").read_text())
    require(checksum(directory / "original.json") == plan["backup_sha256"], "Original backup checksum changed")
    backup = json.loads((directory / "original.json").read_text())
    print("Reading both selectors twice; no settings writes. Keep the GUI closed.", flush=True)
    start = time.monotonic()
    result = subprocess.run(["sudo", str(engine), "onboard-selector-inspect"],
                            check=True, stdout=subprocess.PIPE, text=True)
    evidence = json.loads(result.stdout)
    require(evidence["kind"] == "unverified_selector_observations"
            and evidence["bank_identity_verified"] is False, "Unexpected diagnostic envelope")
    slot = evidence["slot"]
    saved = next(s for s in backup["slots"] if s["state"]["normal"]["slot"] == slot)
    serial = bytes(evidence["metadata"]["serial_bytes"]).decode().strip("\x00").strip()
    require(serial == saved["state"]["normal"]["device"]["serial"]
            and evidence["metadata"]["device"]["product"] == saved["state"]["normal"]["device"]["product"],
            "Diagnostic belongs to another mouse or connection")
    records = evidence["records"]
    require(len(records) == 35, "Incomplete diagnostic records")
    expected = {(0, None, n) for n in (1, 2, 3)}
    wires = [*range(0x40, 0x4c), 0x34, 0x35, 0x6d, 0x60]
    expected.update((layer, n, w) for layer in (0, 1) for n, w in enumerate(wires, 1))
    require({(r["requested_layer"], r["logical"], r["wire"]) for r in records} == expected
            and all(r["echoed_layer"] in (0, 1) and len(r["record"]) == 7 for r in records),
            "Unexpected diagnostic addresses or records")
    output = directory / f"selector-evidence-{time.time_ns()}"
    output.mkdir(mode=0o700, exist_ok=False)
    path = output / "observations.json"
    durable_plan(path, evidence)
    require(json.loads(path.read_text()) == evidence, "Diagnostic evidence readback differs")
    print(f"Read-only capture completed in {time.monotonic() - start:.1f}s; active slot {slot}.")
    print("Bank identity remains UNVERIFIED; requested selectors and returned echoes are separate evidence.")
    for record in records:
        logical, layer = record["logical"], record["requested_layer"]
        if logical is None:
            originals = saved["state"]["normal"]["primary"] + [saved["middle"]]
            original = next(b for b in originals if b["button"] == record["wire"])
            name = f"primary wire {record['wire']:02x}"
        else:
            bank = saved["state"]["hypershift"] if layer else saved["state"]["normal"]
            original = next(b for b in bank["buttons"] + bank["controls"] if b["button"] == logical)
            name = f"control {logical}"
        comparison = "matches saved bytes" if record["record"] == wire(original) else "DIFFERS from saved bytes"
        print(f"{name}: requested {layer}, echoed {record['echoed_layer']}; {comparison}")
    print(f"Private evidence: {path}\nSHA256: {checksum(path)}")
    print("Original backup, trial runner and saved release helper were not modified. No restoration is claimed.")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=config_path().parent / "hypershift-test")
    args = parser.parse_args()
    try:
        capture(args.directory.expanduser().resolve(), ROOT / "target/debug/naga-macros")
    except (OSError, ValueError, KeyError, TypeError, StopIteration, subprocess.SubprocessError) as error:
        parser.exit(1, f"Read-only recovery inspection stopped: {error}\nKeep all trial backups. No settings writes were requested.\n")


if __name__ == "__main__":
    main()
