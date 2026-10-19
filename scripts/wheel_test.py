#!/usr/bin/env python3
"""Convenient entry point for prepared wheel tests and exact restoration."""
import argparse
from pathlib import Path
import subprocess

from wheel_controlled_test import ROOT, NAMES, config_path, prepare, run_stage


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
        parser.exit(1, f"Wheel test stopped: {error}\nKeep backups; do not repeat apply after a failed write.\n")


if __name__ == "__main__":
    main()
