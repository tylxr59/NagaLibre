# Project handoff

## Latest: unnecessary-write fix and controlled USB hardware test complete

Reviewed `50c43dd`: normal GUI saves compared whole Button structs including
raw_record, rewriting ten unchanged factory keyboard records. Fix `deb2668`
compares decoded actions, retains original raw records for unchanged actions,
and verifies those unchanged records exactly. Changed normal actions verify by
decoded action, allowing equivalent firmware encoding. Explicit backup restore
and rollback compare/verify exact wire bytes, including unknown actions and
trailing data. Stale snapshot checks remain strict. Primary writes and slot
creation/deletion remain absent.

Passed automated validation: 28 Rust tests, 21 offscreen GUI/backup/controlled
runner tests, Clippy with warnings denied, formatting and release build. The
captured-record regressions prove zero button writes for unchanged factory GUI
bindings, only ID 0x40 for button 1 to B, exact rollback after an accepted write
with failed acknowledgement (including unknown actions), and exact explicit
restore even when only encoding differs. Orchestration tests cover state/hash/
approval gates and durable recovery backup before commit acknowledgement.

Actual hardware results on USB 1532:00a7, 12-button plate, active slot 1:

- Fresh active-slot snapshot durably saved with file/directory fsync; its SHA256,
  0600 permissions and all ten original length-1 encodings checked independently.
- User explicitly approved only button 1 (ID 0x40) from key 1 to B and subsequent
  exact restoration. Apply used canonical GUI actions through the real Rust
  session. Saved and independent full readback verified B, other eleven exact
  wire records, primary mappings, mode [0, 0] and active slot 1 unchanged.
- User confirmed physical B output, then fully quitting NagaLibre, reconnecting/
  power-cycling the mouse, B still working, and normal left/right/middle clicks.
  A new read-only verify session confirmed the stored B and other records.
- User ran the approved restore. Save response and independent full readback
  matched the original snapshot exactly (all twelve wire records, including the
  ten length-1 encodings, primary mappings, mode and active slot; transient
  hidraw path excluded). The saved restore receipt and original backup checksum
  were independently checked afterward. User confirmed button 1 types 1 again.
- Physical primary clicks passed before restore; original primary mappings were
  verified after restore, but post-restore physical clicks were not separately
  reported. No slot creation/deletion, primary mapping writes or factory-reset
  command was performed. No transport write counter was captured on hardware;
  the only-0x40 write assertion is established by the regression and code path,
  with unchanged final records verified on hardware.

The original backup, its checksum, engine checksum, durable recovery backups,
latest snapshots and user confirmations remain private under
`~/.config/NagaLibre/`. The plan is `controlled-hardware-test.json`, status
restored_exactly_button_1_confirmed. Do not commit private plans, backups or
serial numbers. Apply cannot be repeated without a new prepared/approved plan;
no further mouse writes are requested by this completed test.

Device access requires local sudo authentication. The user ran the staged
commands locally because noninteractive sudo requires a password and an earlier
pkexec getter attempt timed out. `scripts/backup_onboard.py` performs only the
active-slot getter and durable backup. `scripts/onboard_controlled_test.py`
provides apply, verify (read-only), and exact restore, using the JSON session
protocol and stopping the helper after each stage. Physical input and reconnect
history come from user confirmation, not from the verify script alone.

Scope: this confirms one ordinary keyboard binding and exact backup restoration
on one wired mouse/slot. Hardware failure rollback, unknown-action restore,
modifier/mouse outputs, inactive-slot activation, receiver/Bluetooth, slot 2's
physical behavior, reset, other plates and multi-step macros remain unverified
or unsupported as documented. Existing released 0.3.1 binaries predate these
source fixes; no new release has been published.

## Earlier: physical probe identifies compact inventory reply

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

## Earlier: 0.3.1 display fix and main-PC handoff

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


## Historical: 0.3.0 implementation before hardware access

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

1. Completed for USB slot 1: inventory/action decoding, B write, app exit and
   reconnect persistence, primary clicks before restore, and exact backup restore.
2. Remaining hardware coverage: reset, failure rollback, unknown-action restore,
   additional action types, inactive slots and receiver behavior. Post-restore
   physical primary clicks were not separately confirmed.
3. Recover native macro wire encoding (allocation, event data, references), then
   test it before offering multi-step onboard storage.
4. Verify 6/2-button plates, identify faceplate notifications, and add support.
5. Hotplug and simultaneous external Synapse/OpenRazer access remain untested.
