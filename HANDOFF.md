# Project handoff

## Latest: prevent unnecessary writes before controlled hardware testing

Reviewed commit `50c43dd`: normal GUI saves compared complete Button structs,
including raw_record. Canonical factory drafts therefore rewrote ten semantically
unchanged length-1 keyboard records. Per-write and final verification also used
complete struct equality.

Normal saves now compare button number, category and decoded data, and resolve
unchanged actions to the original captured record. Changed GUI actions verify
by decoded action, permitting equivalent firmware encoding; unchanged bindings
verify exact wire bytes. Explicit backup restoration compares and verifies exact
wire bytes, even for equivalent actions. Rollback also restores/verifies exact
bytes, including unknown categories and trailing data. Stale snapshot checks
remain strict. Primary writes and slot creation/deletion remain absent.

Passed: 28 Rust tests, 17 offscreen GUI/backup tests, Clippy with warnings denied,
formatting checks and release build. New captured-record regressions cover zero
button writes for an unchanged factory draft, only ID 0x40 for button 1 to B,
exact rollback after an accepted-but-failed write (including unknown actions),
and exact encoding restoration. An additional test permits changed-action
re-encoding during normal saves but rejects it for explicit exact restoration.

Hardware phase: **blocked on fresh read/backup access, before write approval**.
Noninteractive sudo still needs a password; the read-only pkexec attempt timed
out after 90 seconds. No fresh backup was created by that attempt. The user
should run `python3 scripts/backup_onboard.py` as their normal desktop user.
It elevates only the Rust active-slot getter with sudo, then saves the exact
snapshot through the existing private, atomic, file-and-directory-fsynced
backup writer and checks JSON readback. It prints a path/hash and action summary;
keep private backups and serial numbers out of Git. Tests cover preserved raw
data/private permissions and failure without creating a substitute-slot backup.

No hardware writes have been performed with this change. Ask for explicit
approval after the backup and concrete plan are ready: only active-slot button 1
(ID 0x40) from key 1 to B (HID usage 0x05), leaving mode, selected slot, other
eleven raw records and primary clicks intact. Verify readback and primary
records, have the user test clicks and B, quit the app/helper and reconnect,
then re-read/test persistence. Finally restore the original backup and verify
all records exactly. Writes, physical click checks, reconnect persistence and
live backup restoration remain pending; do not describe mock tests as hardware.

## Latest: physical probe identifies compact inventory reply

The USB-connected mouse (`1532:00a7`, control interface `/dev/hidraw6` at
probe time) was probed with the checksum-verified 0.3.1 release. All four
getters succeeded: serial returned 22 bytes, mode `00 00`, inventory
`05 01 02` with length **3**, and active slot `01 00 00 00 00 00`.
Do not commit the mouse's serial number. The descriptor exposes the expected
report-ID-zero, 90-byte feature report.

The reference protocol identifies the first inventory byte as capacity, followed
by existing slot IDs. The failure was the requirement for exactly six returned
bytes; the transport already correctly respects the reply's data_size. The
source parser now accepts compact inventories bounded by capacity (maximum 5),
retaining slot-range, duplicate and empty-inventory rejection. Regression tests
cover the observed three-byte reply, padded replies via the existing fake, and
malformed inventories. A framing test verifies reply-length handling.

The user chose to install this machine's distro Rust toolchain and asked to
continue locally, superseding the earlier no-toolchain-on-main-PC guidance.
The corrected source builds locally. All 22 Rust tests and 15 offscreen GUI
tests pass; `cargo fmt --check` and Clippy with warnings denied pass.
**The inventory parser fix is now hardware-verified:** the user ran the corrected
release binary's read-only `onboard-read --slot 1` and `--slot 2`; both succeeded,
reporting slots [1, 2], active slot 1, normal mode [0, 0], and standard primary
left/right records. Slot 1 side buttons 1 and 2 declared keyboard
length 2; the remaining ten declared length 1. The original decoder returned
only [0] for those ten buttons and all buttons in slot 2. Physical monitoring
in active slot 1 nevertheless confirmed KEY_1..KEY_9, KEY_0, KEY_MINUS,
KEY_EQUAL, in order.

The user ran `onboard-probe --slot 1` (new optional slot argument reads primary
IDs 1/2 and grid IDs 0x40..0x4b with existing echo checks). Complete payloads
confirmed that the HID usages are present after the zero modifier despite the
declared length 1: e.g. ID 0x42 returned `01 42 00 02 01 00 20 00 00 00`.
All twelve trailing usages match the observed factory outputs. The local source
now decodes category-2 length-1 records using both modifier and usage bytes.
The user re-ran the rebuilt binary's `onboard-read --slot 1`: all twelve
decoded bindings now match the observed factory key outputs, with raw_record
retained on buttons 3–12. This verifies both read-side fixes on physical USB.

`Button.raw_record` optionally preserves the original seven bytes (category,
length, all five data bytes) whenever canonical encoding would differ. Backup
JSON retains this metadata, including trailing bytes for unknown categories.
Restore/rollback writes the original record and validates it against decoded
data before writes. Old canonical records need no extra field. Tests cover all
twelve captured records, JSON round trips, rollback/restore of length-1 records,
and rejection of inconsistent raw metadata. All 22 Rust tests, 15 GUI tests,
formatting, Clippy and release build pass. No live write test has occurred.

The requested read-only inventory investigation is complete. Slot 2's physical
behavior remains untested. Next hardware phase, if requested: durably back up
the verified slot, test a binding change, app exit/reconnect persistence,
primary controls, reset and backup restoration. The subsequent fix described
above now avoids rewriting equivalent draft actions. Hardware writes require
the user's approval of the controlled test plan.

The downloaded 0.3.1 binary
at `/tmp/nagalibre-probe.U8lvTx/naga-macros` still contains the old parser.
Unprivileged access to hidraw6 fails and noninteractive sudo requires a password;
the user ran the diagnostics locally. No settings writes or persistence tests
have occurred.

## Latest: 0.3.1 display fix and main-PC handoff

The user tried 0.3.0 on the mouse. `get_slots()` fails with
`Invalid onboard profile inventory`. Their screenshot shows B in button 1
but the physical key still emits 1: this is an old local software draft, not
a successful hardware read. No hardware save has been confirmed.

0.3.1 separates **Stored** and **Draft** on tiles, shows unread after failed
reads, labels the editor as a draft, and disables hardware saves/reset until
the selected slot has been read successfully. Unknown firmware actions are
displayed as raw action data. A verified save retains its displayed snapshot
after the helper stops; fresh read is required before saving again.

`sudo ./naga-macros onboard-probe` issues only serial, mode, inventory, and
active-slot getters and prints their raw payloads/errors as JSON. Get inventory
output BEFORE changing the parser: the previous schema assumes a six-byte
payload, first byte capacity <=5, followed by slot IDs. The screenshot alone
does not establish which assumption is wrong. Do not guess a relaxed parser or
claim the protocol failure is fixed. The error now includes actual bytes.

The user asked whether moving development to their main PC with the mouse
attached would help: yes. Continue there from GitHub; do not install this VM
workspace or temporary Rust environment on their PC. On main, inspect hidraw
descriptors and getter replies first, then verify one binding, app exit,
power-cycle persistence, primary clicks, reset and backup restoration.


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
saving compares all twelve draft actions and writes only changed actions.
Reset in hardware mode writes factory keys. Restore accepts matching mouse
serial/product and restores side records
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
