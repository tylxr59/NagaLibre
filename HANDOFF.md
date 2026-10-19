# NagaLibre development handoff

Read [AGENTS.md](AGENTS.md) for standing instructions. This file records the
current implementation, evidence, and remaining work. User setup belongs in
[README.md](README.md); CLI usage is in [docs/CLI.md](docs/CLI.md).

## Current state

NagaLibre is an independent FOSS Linux reimplementation of Razer Naga side-button
bindings. Target mouse: Naga V2 Pro. The user's hardware machine runs Arch/KDE;
earlier development used a VM without the mouse. In the 2026-10-19 session,
the current execution environment reports CachyOS/Arch and the wired mouse is
visible. Direct hidraw access still requires local sudo authentication. Do not
assume one machine’s toolchain, device paths, sudo access, or private files exist
on another.

The GUI uses PySide6 and a locally built Rust engine. The source-only distribution
policy replaces the earlier binary-preview workflow. No compiled executables or
bundled application archives should be uploaded. scripts/package.py was removed.
The GUI now uses target/release/naga-macros unless NAGALIBRE_BACKEND is set,
preventing old root/dist preview executables from overriding a fresh source build.
At the user's subsequent request, all five historical GitHub preview releases
(v0.2.0 through v0.3.1) and their downloadable assets were removed. Source commits
and git tags were retained. Publishing releases is postponed until the user asks
to resume it; build from source in the meantime.

The README was rewritten for users, with requirements, source build commands,
support limits and app usage. AGENTS.md holds architecture, checks and hardware
invariants. The obsolete inspection/VALIDATION.md was removed; current validation
and hardware evidence belong here. Protocol research remains in inspection/.

Cargo package version remains 0.3.1; version alone does not identify whether a
local executable includes these source fixes. Rebuild from the intended commit.

## Hardware evidence

The latest completed onboard-write test is recorded in commit 8def909 and preceding
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
and remain in firmware. Plate selection is now automatic while connected; six- and two-button inputs
still require learning in software mode. Do not infer plate identity from one
shared key event.

## Research and provenance

- [Initial installer inspection](inspection/REPORT.md): statically extracted,
  never executed; bootstrap lacks the full controller.
- [Onboard protocol](inspection/ONBOARD.md): official Device167 package, native/
  managed investigation and independent protocol references. Proprietary payloads
  and decompiled code stay outside version control.
- [Faceplates](inspection/FACEPLATES.md): model-specific native/managed trace
  recovered hardware-module getter `00/b9`, one-byte payload/reply. Wired physical
  swaps verified IDs 3 (twelve), 4 (six), 1 (two), 0 (detached), then 3 again.
  This supersedes the inconclusive generic `00/86` layout investigation.

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
3. Verify 6/2-button software outputs and receiver detection. Faceplate detection
   and swaps are verified on USB; the helper currently polls once per second.
4. Exercise hotplug, cleanup and simultaneous external controller access.
5. Keep builds source-only; never revive the old binary-packaging workflow.

## Automatic faceplate detection (2026-10-19)

Pulled main fast-forward from 8def909 to ee84ce0 before this work. Re-extracted
the supplied bootstrap and official Device167 package without running Windows
code. The Naga-specific hardware-module trace and physical readings are in
inspection/FACEPLATES.md. User ran the existing durable backup script and the
new `faceplate --watch` diagnostic through sudo, then confirmed each plate swap.
No mouse settings were written. The backup and raw capture remain private/local.

The engine adds `faceplate [--watch]` and JSON session protocol 3. A `faceplate`
session command enables polling and emits changes with `module_id` and `buttons`.
Known IDs select the corresponding GUI draft automatically; switches stop active
software remaps and learning, preserve drafts and invalidate mouse snapshots.
Read errors show manual fallback; detached/unknown modules block Apply.
Software Apply carries an optional module_id checked immediately before starting;
onboard prepare/commit recheck the twelve-button plate when detection is enabled.
Older protocol-1/2 engines retain manual GUI behavior. Successful onboard saves
still terminate the helper, so detection resumes on the next connection.

Automated validation passed 29 Rust and 25 Python/Qt tests, formatting, Clippy
with warnings denied, debug/release builds and the example config check.
Regressions cover draft preservation, no-plate/unknown/error handling and queued
config cancellation. After launching the rebuilt app and being asked to connect
and swap plates, the user confirmed that desktop detection worked. This is a
user-reported GUI result; the exact plate sequence and authentication flow were
not separately recorded. The CLI watcher independently verified all three plates
and detach/reattach transitions.
The current environment has Cargo and PySide6 directly available; the older
/tmp toolchain and .venv instructions above describe a previous environment.
Receiver/Bluetooth and physical six-/two-button remapping remain unverified.

## Automatic stored-binding refresh (2026-10-19)

The user reported that the detected twelve-button plate still showed Stored:
unread. Plate detection invalidated the previous snapshot but did not request a
replacement on return to the supported plate. In Mouse memory mode, detecting
the twelve-button plate now automatically reads the selected slot when connected
and idle. The existing connection read remains automatic; an in-flight read/save
prevents duplicate automatic requests. Other plates and Software mode do not
trigger onboard reads. Stored values refresh without changing local drafts or
writing settings. A regression covers initial read/detection ordering, detach,
six-button detection, return to twelve buttons, and preserving draft B beside
stored 1. All 26 Python/Qt tests passed, along with diff whitespace validation.
The new automatic refresh has not yet been separately confirmed on hardware.

## Experimental multi-model software support (2026-10-19)

At the user's request, inspected available Razer binaries without additional
hardware. `inspection/MODELS.md` records seven official CDN packages, hashes,
USB identities, layout evidence and candidate Pro/Trinity hardware-module
getters. Do not equate static evidence with hardware-verified support.

Added the shared `devices/models.json` registry and `models` CLI. Discovery now
recognizes Naga Pro/Trinity/X/Left-Handed/Chroma/V2 HyperSpeed and Viper V2 Pro USB
variants. New models use Software mode with learned inputs; their GUI memory
option is disabled and the helper rejects vendor/onboard operations independently.
V2 Pro HID transport/writers remain unchanged. Bluetooth and unknown receivers
are not included. Multiple physical mice are rejected for automatic selection;
composite interfaces are grouped by USB ancestor. Session workers pin model and
physical path to prevent applying a stale draft after changing models.

The protocol-3 hello adds device metadata. The GUI selects the model's layouts
(including Trinity's seven-button plate), labels unverified models, and keeps
separate per-model draft files and an in-memory draft cache. Existing V2 Pro
profiles retain their path/schema. New models begin with empty triggers, and
reset preserves learned inputs instead of inventing factory outputs.

Validation: 31 Rust tests and 29 Python/Qt tests passed, plus Clippy with warnings
denied. Regressions cover unique IDs/capabilities, composite vs multiple mice,
experimental profile roundtrips/reset, model/draft isolation, and a real QProcess
session learning/applying on a simulated Trinity without any vendor commands.
No live writes or new model hardware tests were performed in this session.

## Device-support issue workflow (2026-10-19)

Added `.github/ISSUE_TEMPLATE/device-support.yml` and chooser config with a
structured GitHub form for new models, detection problems, and experimental
hardware results. It asks for exact model/connection, source revision, passive
inventory, layouts, optional faceplate/input observations, and follow-up testing.
`docs/DEVICE_SUPPORT.md` and a README section link directly to the form. GitHub
will expose it after these files reach the repository's default branch; no issue
was created or submitted during development.

Added `diagnose`: passive sysfs input/HID inventories for all Razer products,
including unknown/unsupported connections, capability masks, HID descriptors,
OS ID/version and kernel release. No device nodes, vendor requests, input capture,
serial/unique IDs, physical paths, hostname, drafts or backups are included.
Missing inventories/descriptors are reported. The default JSON filename is ignored.
`list --all-razer --json` includes unknown Razer products without enabling them.

The GUI always offers Request device support and highlights unknown/experimental
Razer devices. The link only prefills registry names and numeric USB IDs; raw
names, logs, profiles and serials are never put in the URL. Opening it requires
the user's click and submission stays in the browser. Unknown Razer interfaces
are described as devices rather than assumed to be mice.

The form and guide only recommend faceplate polling for the enabled V2 Pro.
Other models provide passive metadata and optional explicit input monitoring;
no arbitrary vendor probes, onboard saves, resets, backups or restoration are
requested. Physical observations are distinguished from getter results.

Validation: 32 Rust tests and 31 Python/Qt tests passed, plus Clippy and formatting.
Regressions cover unknown-device inclusion and private/unrelated data exclusion,
encoded issue URLs, duplicate interfaces, contextual UI hints and click-only
browser opening. YAML was parsed and checked locally against the used GitHub
issue-form fields; live GitHub rendering awaits publication to the default branch.

## Device-reported onboard capacity (2026-10-19)

At the user's request, preserve inventory capacity separately from initialized
IDs. The captured V2 Pro `05 01 02` reply now yields `slot_capacity: 5` and
`slots: [1, 2]` in snapshots. Old backups default the optional capacity field to
unknown and still restore through fresh snapshots. Capacity changes participate
in strict stale-state checks.

The new read-only `onboard-slots` CLI returns capacity, initialized IDs and active
slot without serial/button reads, including an empty inventory. Existing V2 Pro
mode/inventory/active getters are used; other models stay disabled. Compact and
six-byte padded inventories support capacities 1–5, with invalid/duplicate IDs
and active IDs outside capacity rejected. No profiles are created or activated.

The dropdown shows all slots within reported capacity and disables uninitialized
entries. A summary says e.g. “2 of 5 slots initialized”; older helper snapshots
retain initialized-only lists and explicitly unknown capacity. Read failures
invalidate the summary. Slot creation remains unimplemented. README, CLI/support
guides and issue form explain the distinction and optional serial-free inventory.

Validation covers captured capacity 5/IDs 1,2, sparse IDs, smaller capacities,
padded replies, empty inventories, getter-only transport calls, stale-capacity
save rejection, legacy restores and disabled UI entries. New capacity display
has not yet been separately confirmed by the user on hardware.
All 34 Rust and 32 Python/Qt tests passed, along with formatting, Clippy with
warnings denied, debug/release builds, whitespace and support-form YAML checks.
