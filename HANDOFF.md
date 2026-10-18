# Project handoff

## Current work: 0.3.0 onboard profiles

The user confirmed 0.2.2 works and now explicitly requires persistence without
an app/helper. A new experimental hardware path implements existing onboard
slots for the 12-button plate: keyboard keys, modifier shortcuts, and mouse
button outputs. **No local physical mouse testing is possible.** The user's mouse
is on Arch/KDE, USB 1532:00a7; receiver 00a8 is also recognized. Do not claim
NagaLibre's hardware transport or persistence has been verified.

`src/onboard.rs` implements snapshot/prepare/commit/rollback and device-bound
backup restore. `src/onboard/hidraw.rs` handles descriptor selection and 91-byte
feature transactions. `src/session.rs` protocol 2 adds onboard_read,
onboard_prepare, onboard_restore and onboard_commit. The Qt GUI must durably
save the prepared snapshot before acknowledging the commit token. Only firmware
IDs 0x40–0x4b can reach the mapping writer. Primary clicks are read and checked
but never written. No slot create/delete, macro-arena or firmware-update commands.
On success normal mode and the chosen slot are verified, then the helper exits.

`gui/onboard.py` maps Linux key names to HID usages and saves private backups.
The GUI defaults to Mouse memory, with an explicit Software mode for existing
macro sequences and other plates. Read slots leaves the local draft unchanged;
saving writes all twelve draft actions. Reset in hardware mode writes factory
keys. Restore accepts matching mouse serial/product and restores side records
into their original slot; it does not recreate deleted underlying macro data.

See [inspection/ONBOARD.md](inspection/ONBOARD.md) for decompilation findings,
protocol references, safety boundaries and remaining work. The re-uploaded
installer is identical to the earlier one. Device167 was downloaded from the
Razer CDN and statically decompiled under /tmp, never executed or redistributed.
Managed macro handlers were recovered, but the native wire encoding is still
unknown. **Multi-step onboard macros are not implemented.** Software mode remains
available; do not silently pretend a software macro was stored in the mouse.

Next hardware step: `sudo ./naga-macros onboard-read`, then one key binding,
quit/reconnect persistence, primary-click checks, reset and backup restoration.
First resolve any read framing/schema mismatch before encouraging writes.

## Software engine and packaging

The earlier CLI macros and 0.2.2 Qt remapper work on the user's main machine.
Twelve side keys initially emit KEY_1..KEY_9, KEY_0, KEY_MINUS, KEY_EQUAL. The
mouse exposes overlapping event interfaces: prefer the ordinary keyboard node
when it covers configured triggers, preserve absolute metadata if an absolute
interface is required. Never hardcode event23/event26.

Version 0.2.0 accidentally allowed learning main clicks. Python and Rust now
reject BTN_LEFT/RIGHT/MIDDLE/BTN_MOUSE as triggers; learning ignores primary
clicks. Emergency software recovery: `sudo pkill -x naga-macros`, quit the old
GUI, update and reset. This stops software remaps; it does not revert saved
hardware mappings. Hardware recovery uses Reset 12 buttons / Restore backup.

Build/test commands are in README. The temporary development toolchain is
`RUSTUP_HOME=/tmp/naga-rustup CARGO_HOME=/tmp/naga-cargo /tmp/naga-cargo/bin/cargo`.
Use musl target and rust-lld for the static x86-64 engine. `scripts/package.py`
produces `dist/NagaLibre-linux-x86_64.tar.gz` and checksums. Arch uses system
PySide6; no Rust install is required on the main machine. Run `./nagalibre` as
the desktop user; only the Rust helper is elevated with pkexec. No service or
broad input permissions are installed. Read docs distinguish hardware/software.

All proprietary extraction/decompilation is under ignored inspection/payload
or /tmp. Never commit DLLs, EXEs, generated binaries, token material, or caches.
GitHub remote is https://github.com/tylxr59/NagaLibre. User previously authorized
pushing the project and releases. New hardware builds must be prereleases until
physical read/save/reconnect verification succeeds.

## Remaining work

1. Get the user's onboard-read output and fix any transport discrepancy.
2. Verify one B key, quit, reconnect, all primary controls, factory reset and restore.
3. Recover native macro wire encoding (allocation, event data, references), then
   test it before offering multi-step onboard storage.
4. Verify 6/2-button plates, identify faceplate notifications, and add support.
5. Hotplug and simultaneous external Synapse/OpenRazer access remain untested.
