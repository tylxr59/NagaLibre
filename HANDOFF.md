# NagaLibre development handoff

Read [AGENTS.md](AGENTS.md) for standing instructions. This file records the
current implementation, evidence, and remaining work. User setup belongs in
[README.md](README.md); CLI usage is in [docs/CLI.md](docs/CLI.md).

## Current state

NagaLibre is an independent FOSS Linux reimplementation of Razer Naga side-button
bindings. Target mouse: Naga V2 Pro. The user's hardware machine runs Arch/KDE;
this development VM has no mouse attached. Do not assume one machine's toolchain,
device paths, sudo access, or private files exist on another.

The GUI uses PySide6 and a locally built Rust engine. The source-only distribution
policy replaces the earlier binary-preview workflow. No compiled executables or
bundled application archives should be uploaded. scripts/package.py was removed.
The GUI now uses target/release/naga-macros unless NAGALIBRE_BACKEND is set,
preventing old root/dist preview executables from overriding a fresh source build.
Earlier GitHub binary release assets are historical; they were not deleted and
predate the current hardware fixes. Do not recommend them for testing.

The README was rewritten for users, with requirements, source build commands,
support limits and app usage. AGENTS.md holds architecture, checks and hardware
invariants. The obsolete inspection/VALIDATION.md was removed; current validation
and hardware evidence belong here. Protocol research remains in inspection/.

Cargo package version remains 0.3.1; version alone does not identify whether a
local executable includes these source fixes. Rebuild from the intended commit.

## Hardware evidence

The latest completed live test is recorded in commit 8def909 and preceding
commits deb2668, dd0d727 and 594fea9. Device: USB 1532:00a7, 12-button plate,
active slot 1, normal mode [0, 0]. Receiver 1532:00a8 is recognized but unverified.
Bluetooth onboard access is unsupported. Slot inventory reports initialized
slots [1, 2]; physical behavior of slot 2 is untested.

Verified on the user's wired mouse:

- Serial/mode/inventory/active getters and button-table reads for slots 1 and 2.
- All twelve active-slot outputs: KEY_1..KEY_9, KEY_0, KEY_MINUS, KEY_EQUAL.
- Durable active-slot backup: private file, file/directory fsync, checksum, and
  preservation of the ten original nonstandard keyboard encodings.
- Explicitly approved change of button 1 (firmware ID 0x40) from 1 to B through
  the real session using canonical GUI actions. Save and independent readback
  showed B, the other eleven exact records, standard primary mappings, unchanged
  mode and unchanged active slot.
- User confirmed physical B output, fully quitting NagaLibre, reconnecting/
  power-cycling, B still working, and normal left/right/middle clicks. A fresh
  read-only session verified the saved B and other records.
- Approved backup restore: save response and independent readback matched all
  original wire records, primary mappings, mode, active slot and identity.
  Transient hidraw path was excluded. Restore receipt and backup hash checked;
  user confirmed button 1 typed 1 again.

There was no hardware transport write counter. The only-0x40 assertion is backed
by regression tests and the code path, plus final unchanged records on hardware.
Post-restore physical primary clicks were not separately reported, although their
stored mappings matched. Hardware failure rollback, unknown-action restore,
modifier/mouse outputs, inactive-slot activation, receiver behavior, factory reset,
other plates and multi-step macros remain unverified or unsupported.

Private backups, checksums, engine checksum, recovery records, receipts and user
confirmations remain on the hardware machine under ~/.config/NagaLibre/. Its
controlled-hardware-test.json status was restored_exactly_button_1_confirmed.
Do not commit the private files or mouse serial. That test is complete and does
not authorize additional writes. A new apply requires a fresh approved plan.

Local sudo authentication was needed. The user ran staged commands because
noninteractive sudo required a password and an earlier pkexec getter attempt
timed out. Do not describe the live test as a full Qt/polkit end-to-end test.

## Protocol details that caused earlier bugs

The control interface is selected by its HID descriptor: report ID zero and a
90-byte feature body (91 bytes with the report-ID prefix). Never hardcode a USB
interface, hidraw node or event number.

The mouse returned inventory payload `05 01 02`, length 3: capacity 5 followed by
existing slot IDs. The original fixed-six-byte decoder rejected it. The current
parser accepts compact inventories bounded by capacity, retaining range,
duplicate and empty-list checks. This correction was verified on hardware.

Keyboard records on grid buttons 1/2 used declared data length 2. Buttons 3–12
used length 1 while still carrying modifier and usage bytes. Example complete
payload for button 3: `01 42 00 02 01 00 20 00 00 00`. Reading only the declared
length discarded the HID usage and produced [0]. The decoder now reads both
keyboard bytes in this case and retains raw_record when the canonical bytes
would differ. Hardware readback matched all twelve observed factory outputs.

raw_record holds the original category, length and all five data bytes. It must
round-trip unknown categories, nonstandard lengths and trailing data. Metadata
is checked against decoded category/data before writing. Old snapshots without
raw metadata remain supported.

Review of commit 50c43dd found ten unnecessary writes when GUI canonical actions
were compared to whole Button structs. Fix deb2668 separates decoded-action
comparison from exact-wire comparison:

- Normal prepare retains original records for unchanged actions and skips writes.
- Changed normal actions verify semantically, allowing firmware re-encoding.
- Unchanged records, explicit restore and rollback verify exact bytes.
- Stale snapshot checks remain strict, including raw data.

Regressions establish zero button writes for unchanged captured factory bindings,
only 0x40 for button 1 to B, exact rollback after an accepted write with failed
acknowledgement, unknown-action preservation, and exact restore when only encoding
differs. The unprivileged GUI durably saves a backup before commit acknowledgement.

## Software engine and UI context

Software macros and the composite-interface fix were confirmed on the user's
mouse. Its pointer/keyboard/consumer interfaces overlap; prefer an ordinary
keyboard node when sufficient, while preserving required absolute-axis metadata.

An early preview let users learn left click as a trigger. Both Python and Rust
now reject BTN_LEFT/RIGHT/MIDDLE/BTN_MOUSE as triggers and learning ignores primary
clicks. Clicks remain valid outputs. Emergency software recovery is to stop the
helper (`sudo pkill -x naga-macros`); this never undoes saved onboard bindings.

Stored and Draft values are separate. Read failure or selecting an unread slot
invalidates stored display and disables saves/reset. Reading leaves the draft
unchanged. Saving compares all twelve draft actions and activates the selected
slot; it is not limited to the currently selected tile. A verified saved snapshot
remains displayed after the helper exits; another save needs a fresh read.

Closing software mode to tray keeps the helper running. Session EOF, Quit and
process termination release software input grabs. Onboard saves stop the helper
and remain in firmware. Other plates require manual selection/input learning in
software mode; do not infer plate identity from one shared key event.

## Research and provenance

- [Initial installer inspection](inspection/REPORT.md): statically extracted,
  never executed; bootstrap lacks the full controller.
- [Onboard protocol](inspection/ONBOARD.md): official Device167 package, native/
  managed investigation and independent protocol references. Proprietary payloads
  and decompiled code stay outside version control.
- [Faceplates](inspection/FACEPLATES.md): recovered generic 00/86 layout query is
  not verified as Naga plate identification. No mapping to plate counts is known.

The managed module exposes macro conversion/storage handlers but its host event
structures are not the USB wire format. Native multi-step allocation/upload/
delete encoding remains unknown. Do not claim onboard sequences are implemented;
the software engine remains the available sequence path.

## Validation and local environment

The source-only cleanup passed 28 Rust and 23 Python/Qt tests, Clippy with
warnings denied and formatting. New lookup regressions ensure old root/dist
executables cannot override the source build, while an explicit backend override
still works. Local documentation links and tracked ELF/PE exclusion were checked.
A native release build, example-config check and offscreen launch through
./nagalibre also passed. Live evidence is limited to the completed test above,
separate from these automated results.

For this VM only, the temporary toolchain is available through:

```sh
RUSTUP_HOME=/tmp/naga-rustup CARGO_HOME=/tmp/naga-cargo /tmp/naga-cargo/bin/cargo
```

The existing .venv has PySide6; use .venv/bin/python for offscreen GUI tests here.
These are development conveniences, not installation instructions for users.
Use the portable build/check commands in AGENTS.md on other machines.

## Remaining work

1. Broaden controlled hardware coverage: reset, failure rollback, shortcuts/mouse
   outputs, inactive slots and receiver behavior, plus the Qt/polkit workflow.
2. Recover and verify native multi-step macro storage before offering it in UI.
3. Verify 6/2-button plates and investigate actual faceplate notifications.
4. Exercise hotplug, cleanup and simultaneous external controller access.
5. Keep builds source-only; never revive the old binary-packaging workflow.
