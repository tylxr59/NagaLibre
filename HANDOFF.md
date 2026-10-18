# Project handoff

## Current state

Version 0.2.2 is an initial Linux input remapper plus a Qt 6 desktop UI.
The target mouse is the **Razer Naga V2 Pro**, and the user's main machine runs
**Arch Linux with KDE Plasma**. The mouse is attached to that machine, not the
development environment.

The user confirmed the initial CLI macros work on real hardware, including
copy/paste. The twelve side buttons emit, in order:

```text
KEY_1 KEY_2 KEY_3 KEY_4 KEY_5 KEY_6
KEY_7 KEY_8 KEY_9 KEY_0 KEY_MINUS KEY_EQUAL
```

Their device uses USB ID `1532:00a7`. There were three event interfaces, with
side-button input on the keyboard interface. Event numbers can change, so the
desktop helper discovers matching Naga interfaces rather than hardcoding paths.
Wireless ID `1532:00a8` is also recognized.

The new GUI and held-key remapping still need physical testing. Do not describe
the new GUI, other plates, or automatic faceplate detection as device-verified.

The user reported that 0.2.0 remapped left click to A. Its learning flow accepted
BTN_LEFT and configuration validation allowed primary-button triggers. Version
0.2.1 ignores left/right/middle clicks during learning, makes the observed input
field read-only, and rejects main mouse buttons as triggers in both Python and
the Rust engine. Mouse clicks remain allowed as macro outputs. Reset clears bad
learned inputs; Esc stops remapping and Ctrl+Q quits with the GUI focused.
Immediate recovery for an already-running bad mapping is
`sudo pkill -x naga-macros`; then quit the old GUI, update, and reset the plate.

The user next hit `event26 exposes absolute axes` when binding button 1 to B.
The engine matched overlapping advertised key capabilities on the mouse's
composite interfaces and rejected any interface with absolute axes. Version
0.2.2 prefers non-absolute keyboard interfaces if they cover all configured
inputs. If an absolute interface is needed, its axis metadata and ABS events
are mirrored instead of rejecting the whole configuration. New selection
regressions pass; applying this fix still needs confirmation on the user's mouse.

## Architecture

- `src/main.rs`: CLI commands `list`, `monitor`, `check`, `run`, and `session`.
- `src/config.rs`: strict TOML validation and macro compilation. Each binding
  has either `key` (held remap) or `steps` (macro). `binding = []` means defaults.
- `src/runtime.rs`: evdev grabs, uinput passthrough, macro scheduling, held-key
  reference counting, and cleanup. Only interfaces containing mapped inputs
  are grabbed; other interfaces remain untouched.
- `src/session.rs`: JSON-line desktop protocol over stdin/stdout. Monitor does
  not grab input. Apply switches to remapping. EOF or shutdown stops the helper,
  so closing/crashing the GUI cannot leave an independently running daemon.
- `gui/app.py`: PySide6 Qt Widgets window, learning, macro editor, plate profiles,
  live input highlights, and system tray. A Qt lock prevents duplicate GUI instances.
- `gui/backend.py`: QProcess bridge. The GUI stays unprivileged and launches the
  Rust session through pkexec with the desktop authentication agent. Stop uses
  the protocol/EOF rather than trying to signal a root process from a user GUI.
- `gui/model.py`: profile schema, atomic saves, and conversion to engine TOML.
  Profiles live under `$XDG_CONFIG_HOME/NagaLibre/profiles.json`, normally
  `~/.config/NagaLibre/profiles.json`. Invalid existing files are preserved.

The 12-, 6-, and 2-button plates have independent, manually selected profiles.
Only the 12-button plate has verified initial inputs. Use Learn input for the
other plates. Reset stops remapping and returns to passthrough; it does not
write factory mappings or anything else to the mouse's firmware/onboard memory.

## Inspection work

The user supplied a Synapse installer. It was extracted and statically inspected,
never executed. See `inspection/REPORT.md` and `inspection/FACEPLATES.md`.
Native detection DLL disassembly recovered a generic layout query (`0x00/0x86`,
two-byte payload), but **no verified mapping to Naga faceplates**. Do not infer
that a layout value is a button count or add guessed HID writes.

Useful next evidence is the installed Naga-specific Synapse module or a USB
capture of Synapse while switching between known plates. The extracted installer
payload and raw disassembly remain ignored local analysis material, not repository
source or release content. The current application uses no proprietary DLLs.

## Verification and packaging

Last validation: nine Rust tests and eight Python/Qt tests passed; Rust clippy
passed with warnings denied; formatting checks passed. Tests cover compilation,
routing, overlapping key ownership, real engine config validation, profile
resets/persistence, Qt edit/apply/learn flows through a mock helper, and protocol
error/EOF handling. Qt tests explicitly drain deferred deletion because they
use processEvents rather than a full app event loop.
Regression coverage rejects primary-click remaps in the engine and profile model,
checks that primary clicks do not complete learning, and verifies reset clears
old primary-click inputs without preventing mouse clicks as macro outputs.
Interface-selection tests cover overlapping ordinary/absolute interfaces and
retaining a necessary absolute interface. Actual absolute-axis passthrough is
not hardware-tested in the development environment.

```sh
cargo test --locked
cargo clippy --all-targets --locked -- -D warnings
cargo fmt --check
cargo build --locked
python3 -m venv .venv
.venv/bin/pip install -r gui/requirements.txt
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s gui -p 'test_*.py' -v
```

Build the static Rust engine, then the small desktop archive:

```sh
rustup target add x86_64-unknown-linux-musl
CARGO_TARGET_X86_64_UNKNOWN_LINUX_MUSL_LINKER=rust-lld \
  cargo build --release --locked --target x86_64-unknown-linux-musl
python3 scripts/package.py
```

`dist/NagaLibre-linux-x86_64.tar.gz` contains GUI source, the static engine,
documentation, artwork, and project source. `dist/SHA256SUMS` records artifact
checksums. Generated archives/build caches are ignored by git. The Arch package
uses system PySide6 (`sudo pacman -S --needed pyside6`), not a bundled Qt runtime.
Launch `./nagalibre` as a normal desktop user and click Connect mouse.

## Next work

1. Test the GUI on the user's Arch/KDE machine: stop any old CLI remapper, connect,
   check all twelve highlights, apply a shortcut and a held-key binding, then
   reset to defaults. Check tray Quit and input restoration.
2. Learn and verify the actual inputs for the six- and two-button plates.
3. Investigate real faceplate notifications/queries with additional evidence.
4. Check hot unplug/reconnect and failure cleanup on hardware. Current behavior
   requires manual reconnect/rescan and Apply; it does not auto-resume remapping.

Longer-term direction is a FOSS Linux-native Razer control app. DPI/RGB control,
onboard programming, login autostart, and automatic plate detection are not
implemented. Macros currently run in the host process and require it to stay open.
