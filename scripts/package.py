#!/usr/bin/env python3
"""Package the desktop sources with the static Rust engine for Linux x86-64."""
import argparse
import hashlib
from pathlib import Path
import shutil
import tarfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, help="An already-built static naga-macros executable")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    engine = args.engine or root / "target/x86_64-unknown-linux-musl/release/naga-macros"
    if not engine.is_file():
        parser.error("Build the static Rust target first (README.md), or pass --engine PATH.")
    dist = root / "dist"
    dist.mkdir(exist_ok=True)
    output = dist / "NagaLibre-linux-x86_64.tar.gz"
    files = [root / name for name in ("Cargo.toml", "Cargo.lock", "README.md", "HANDOFF.md", "LICENSE", "nagalibre", ".gitignore")]
    for folder in ("src", "gui", "scripts", "examples", "assets"):
        files.extend(p for p in (root / folder).rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")
    files.extend(p for p in (root / "inspection").glob("*") if p.is_file() and p.name != "layout-query-disassembly.txt")
    with tarfile.open(output, "w:gz") as archive:
        archive.add(engine, arcname="NagaLibre/naga-macros")
        for path in sorted(files):
            archive.add(path, arcname="NagaLibre/" + str(path.relative_to(root)))
    shutil.copy2(engine, dist / "naga-macros")
    artifacts = [p for p in dist.iterdir() if p.is_file() and (p.name == "naga-macros" or p.name.endswith(".tar.gz"))]
    with (dist / "SHA256SUMS").open("w") as out:
        for path in sorted(artifacts):
            out.write(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n")
    print(f"{output} ({output.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
