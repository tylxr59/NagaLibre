# Working on NagaLibre

Read HANDOFF.md before changing hardware behavior. It holds current evidence,
known limitations, and the next work. README.md and docs/CLI.md are for people
building and using the app; keep agent instructions and session history here or
in HANDOFF.md. Protocol research belongs in inspection/ and is linked from the
handoff rather than repeated in user onboarding.

## Project scope

NagaLibre is an independent FOSS Linux reimplementation of the Razer Naga
side-button system. Current target: Naga V2 Pro, especially USB and its 12-button
plate. The GUI is Python/PySide6; the engine is Rust. It is not a complete Synapse
replacement. Do not present implemented but untested features as hardware-verified.

## Source-only distribution

- Distribute source and build instructions. Do not commit or upload compiled
  executables, bundled application archives, generated checksums, or proprietary
  Razer binaries. Do not create releases containing binary assets or reintroduce
  a binary-packaging workflow.
- Keep Cargo.lock tracked. Build output, venvs, Python caches, private backups,
  hardware-test plans and local proprietary extraction must remain untracked.
- The GUI uses target/release/naga-macros, unless NAGALIBRE_BACKEND explicitly
  overrides it. Do not prefer obsolete root/dist executables over a source build.
- Earlier GitHub releases contained binaries. This policy supersedes the old
  release workflow; it does not authorize deleting historical release assets or
  rewriting git history.

## Commands

Use the current stable Rust toolchain. For Qt, use distro PySide6 or the venv
from README.md. Activate the venv if using one; run Python checks with that
interpreter.

```sh
cargo fmt --check
cargo test --locked
cargo clippy --all-targets --locked -- -D warnings
cargo build --locked
QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s gui -p 'test_*.py' -v
cargo build --release --locked
./target/release/naga-macros check examples/macros.toml
```

GUI tests use the real debug engine for config/session checks and mock hardware
sessions for interactions. NAGALIBRE_TEST_BACKEND overrides the debug-engine path;
NAGALIBRE_BACKEND overrides the GUI helper path. NAGALIBRE_PYTHON selects the
launcher interpreter. NAGALIBRE_NO_PKEXEC=1 is for an environment with suitable
device permissions, not a reason to run the entire Qt app as root.

## Hardware and recovery invariants

- Only physical grid positions 1–12 (firmware IDs 0x40–0x4b) may reach the onboard
  mapping writer. Primary clicks may be read/checked but never written. Slot
  creation/deletion and guessed vendor probes are absent; do not add them casually.
- A normal save compares decoded actions, skips unchanged actions and preserves
  their original records. Changed actions verify semantically. Unchanged records,
  explicit backup restoration and rollback verify exact wire bytes, including
  unknown categories, nonstandard length fields and trailing bytes.
- Retain strict stale-snapshot checks. The unprivileged GUI must atomically save
  and fsync the prepared backup before acknowledging the commit token. A backup
  failure must prevent all settings writes. Attempt rollback for writes whose
  acknowledgements fail because those writes may already have landed.
- Software cleanup must release held output and evdev grabs. Session EOF ends
  the helper. Successful onboard saves stop the helper and remain active in
  firmware. Do not confuse stopping software remaps with restoring mouse memory.
- Never equate a local draft with the active mouse state. Stored values come from
  readback; read failures/slot changes invalidate them. Keep main clicks excluded
  from learning and from software trigger validation.
- Never hardcode event/hidraw numbers. Composite interfaces can overlap; preserve
  necessary absolute-axis metadata and prefer ordinary keyboard interfaces when
  they cover all mapped inputs.

For agent-driven live tests, establish device identity, read state and a durable
backup first. Get approval for the concrete write/restore plan unless the current
session already authorizes those exact actions. A past test approval is not
blanket permission for future mouse writes. The controlled runner requires a
private verified plan; do not bypass its approval, checksum or state gates.
Readbacks do not prove physical output, app exit or power-cycle persistence;
record user observations separately. Do not invent hardware access in this VM.

## Repository map

- src/onboard.rs: snapshots, action/wire comparison, preparation, save and rollback.
- src/onboard/hidraw.rs: descriptor-based discovery and Razer feature-report transport.
- src/config.rs and src/runtime.rs: software config validation, evdev/uinput and scheduling.
- src/session.rs: JSON-lines protocol and helper lifetime; src/main.rs: CLI.
- gui/app.py, model.py, onboard.py, backend.py: Qt UI, drafts, HID translation,
  durable backups and unprivileged process bridge.
- scripts/backup_onboard.py: read-only active-slot backup.
- scripts/onboard_controlled_test.py: staged, explicitly approved hardware test.
- inspection/: static research and protocol provenance; never proprietary payloads.

Keep fixes focused and run checks appropriate to changed behavior. Hardware
regressions should cover actual captures and failure/recovery cases, not just
mirror an implementation. Update HANDOFF.md when evidence or limitations change.
