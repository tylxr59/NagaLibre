#!/usr/bin/env python3
"""Read both mapping banks and durably save a private diagnostic export."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from onboard_controlled_test import durable_plan
from wheel_controlled_test import config_path, require


def capture(engine, directory, slot=None, probe=False):
    command = ["sudo", str(engine), "onboard-layer-probe" if probe else "onboard-layers"]
    if slot is not None:
        command += ["--slot", str(slot)]
    # Keep sudo's prompt visible and authenticate in the user's local terminal.
    result = subprocess.run(command, check=True, stdout=subprocess.PIPE, text=True)
    export = json.loads(result.stdout)
    require(export["format"] == 1, "Unexpected layer export")
    normal = export["normal"]
    require(slot is None or normal["slot"] == slot, "Wrong slot returned")
    require([b["button"] for b in normal["primary"]] == [1, 2], "Incomplete normal primary checks")
    if probe:
        require(export["kind"] == "unverified_layer_replies" and export["secondary_verified"] is False,
                "Probe must remain explicitly unverified")
        require([r["button"] for r in export["replies"]] == list(range(1, 17))
                and all(r["requested_layer"] == 1 and len(r["record"]) == 7 for r in export["replies"]),
                "Incomplete diagnostic replies")
        banks = (normal,)
    else:
        require(export["hypershift"]["layer"] == 1, "Unexpected secondary layer")
        require(export["hypershift"]["primary_inspected"] is False, "Unexpected secondary inspection scope")
        normal_echoes = export.get("normal_echoes", [{"button": n, "layer": 0} for n in range(1,17)])
        require([e["button"] for e in normal_echoes] == list(range(1,17))
                and all(e["layer"] in (0,1) for e in normal_echoes), "Incomplete normal-echo metadata")
        echoes = export["hypershift"]["echoes"]
        require([e["button"] for e in echoes] == list(range(1, 17))
                and all(e["layer"] in (0, 1) for e in echoes), "Incomplete layer-echo metadata")
        banks = (normal, export["hypershift"])
    for bank in banks:
        require([b["button"] for b in bank["buttons"]] == list(range(1, 13))
                and [b["button"] for b in bank["controls"]] == [13, 14, 15, 16], "Incomplete mapping export")
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    path = directory / ("unverified-replies.json" if probe else "layers.json")
    durable_plan(path, export)
    require(json.loads(path.read_text()) == export, "Diagnostic export readback differs")
    return path, export


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slot", type=int, choices=range(1, 6))
    parser.add_argument("--probe", action="store_true", help="Capture raw replies as unverified evidence, preserving their layer echoes")
    args = parser.parse_args()
    directory = config_path().parent / f"layer-inspection-{time.time_ns()}"
    try:
        path, export = capture(ROOT / "target/release/naga-macros", directory, args.slot, args.probe)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        detail = error.stderr.strip() if isinstance(error, subprocess.CalledProcessError) and error.stderr else str(error)
        parser.exit(1, f"Layer inspection stopped: {detail}\nNo mouse settings writes were requested.\n")
    normal = export["normal"]
    if args.probe:
        print("UNVERIFIED reply evidence: secondary-bank selection is not established.")
        print("Reply bytes repeated consistently; normal state and twelve-button plate checked unchanged.")
    else:
        print("Normal and requested layer-1 records read twice; normal state and twelve-button plate checked unchanged.")
        print("Secondary primary-click records were not inspected; normal primary records are included.")
        normal_ones = sum(e["layer"] == 1 for e in export.get("normal_echoes", []))
        print(f"Normal-request replies reporting layer 1: {normal_ones}/16; actual echoes retained.")
        zero_echoes = sum(e["layer"] == 0 for e in export["hypershift"]["echoes"])
        print(f"V2 Pro zero-echo quirk: {zero_echoes}/16 replies; actual echoes retained. Held/release behavior remains unverified.")
    print(f"Product: {normal['device']['product']:04x}; read slot: {normal['slot']}; active slot: {normal['active']}.")
    if args.probe:
        for reply in export["replies"]:
            comparison = "matches normal" if reply["matches_normal_wire"] else "DIFFERS from normal"
            print(f"Button {reply['button']} (wire {reply['wire_id']:02x}): requested {reply['requested_layer']}, "
                  f"echoed {reply['echoed_layer']}; {comparison}")
    else:
        for record in export["hypershift"]["buttons"] + export["hypershift"]["controls"]:
            print(f"Hypershift {record['button']}: category {record['category']:02x}, data {bytes(record['data']).hex() or '(empty)'}")
    print(f"Private export: {path}")
    print(f"SHA256: {hashlib.sha256(path.read_bytes()).hexdigest()}")
    print("Only getters were sent. This diagnostic export is not accepted by Restore backup.")


if __name__ == "__main__":
    main()
