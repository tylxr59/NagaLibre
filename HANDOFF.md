# NagaLibre development handoff

Read [AGENTS.md](AGENTS.md) for standing instructions. This file records the
current implementation, evidence, and remaining work. User setup belongs in
[README.md](README.md); CLI usage is in [docs/CLI.md](docs/CLI.md).

## Current state

TODO section 1 is complete for the requested session scope. The user explicitly
deferred six-/two-button physical mapping tests; those remain unverified and
should not block the next active feature, Hypershift research. Receiver software
remapping and untested action/connection combinations remain outside this evidence.

Verified on the user's Naga V2 Pro with the twelve-button plate:

- DPI-cycle getter returned category 6/data [6] on wired slots 1/2. The user
  confirmed sensitivity cycling, remapping to B and cycling after exact restore.
  DPI stage values were not read; no stage table or sensor settings were written.
- Right tilt -> B and primary clicks physically passed with exact restore. Its
  original binding was F14; left tilt's original was F13. A reconnect getter
  failed, so right-tilt B persistence remains unverified. The earlier left-tilt
  physical B result remains applicable.
- Scroll-mode cycling, remapping to B, primary clicks, USB reconnect persistence
  and restored cycling/clicks all passed. Other tracked records/slots stayed exact.
- Desktop Restore defaults was verified draft-only before saving. All sixteen
  saved defaults read back correctly, and the user confirmed the grid keys, both
  horizontal tilt directions, wheel-mode/DPI cycling and primary clicks. Exact
  original mappings and other slots were restored afterward.
- Desktop activation of existing slot 2, return to slot 1 and creation of slot 3
  passed independent readback. Creation left slot 1 active and original slots'
  mappings exact. New-slot activation, all twelve outputs, primary clicks and
  persistence after USB unplug/replug were confirmed. Final state is slot 1
  active, inventory [1, 2, 3]; slot 3 is retained. The desktop authentication
  prompt succeeded. No existing slots were deleted.
- Onboard Ctrl+A on grid 1 and right click on grid 2 physically passed over USB,
  including Ctrl release and primary clicks. Readbacks checked every other
  tracked record and initialized slot exactly; exact restoration passed.
- The same output test passed through receiver 00a8: active/all-slot backups,
  twelve-button detection, GUI save, physical output/primary clicks, persistence
  after the requested mouse power-off/receiver reconnect sequence, and GUI exact
  backup restoration. The user confirmed all requested physical steps worked.
  Private restored readbacks for slots 1/2/3 were independently compared with
  their originals. Plan and original-backup integrity were checked. Receiver
  slot creation remains disabled; receiver slot activation and smaller-plate
  swaps were not tested.

Final hardware state from the receiver restoration: original tracked mappings,
mode and active slot 1 restored; initialized slots [1, 2, 3]. Local drafts remain
separate and may still contain the Ctrl+A/right-click experiment. Do not infer
active firmware state from those drafts. All private captures/backups stay local.

New source test tools:

- `scripts/verify_wheel.py` wraps the existing controlled runner with fresh
  per-control backups and explicit yes/no/skip physical observations. It checks
  B readback after reconnect and attempts exact restoration after interruptions
  or lost commit replies. It displays original binding labels and offers explicit
  retries only for unmatched-reply read failures; writes/state mismatches are
  never retried. Restore failure stops the run and preserves recovery evidence.
- `scripts/check_defaults.py prepare|staged|saved|restored` sends only getters.
  It durably backs up all slots and a GUI-restorable original snapshot, checking
  all sixteen defaults or `--test outputs` (Ctrl+A/right click). Unchanged actions
  retain exact wire bytes; changed actions verify semantically. Output staging
  validates the persisted GUI draft before the save. Fully quit the GUI first.
  Readbacks, including failed checks, are saved privately. Explicit
  `--connection receiver` requires 00a8 and separate receiver evidence paths;
  normal preparation requires wired 00a7. Later checks stay identity-bound.
- `scripts/check_slots.py` sends only getters around GUI activation/creation.
  It permits only planned active/inventory changes and preserves exact original
  mapping records. New grid/primary defaults and later tracked new-slot records
  are checked. It has no settings writers or deletion commands.

Two informative failures were recovered. The first output attempt also saved
factory tilt drafts, changing F13/F14 to horizontal scroll. Its unchanged-record
check rejected this; exact restore passed. Persisted-draft validation now catches
that configuration before another GUI save. A mode getter (00/84) failed during
right-tilt reconnect verification and a button getter (02/8c) failed during slot
verification. A GUI helper was still running after the latter failure; concurrent
polling is a possible cause, not a proven diagnosis. Fully quitting the GUI and
retrying its read-only check passed. Keep CLI getters and GUI polling separate.

Final validation: 52 Rust and 70 Python/Qt tests passed, formatting, Clippy with
warnings denied, debug/release builds, example config check and diff whitespace
checks. Regressions cover interrupted observation/accepted-write lost replies,
read-only retries, strict other-slot/raw-record preservation, incorrect shortcut
modifiers, unexpected factory drafts, evidence retention, slot-state changes and
explicit receiver identity binding. No compiled assets are added to distribution.

## Earlier implementation and protocol context

These entries preserve implementation-stage evidence. The completed physical
checks above supersede earlier statements that those paths were unverified.

Added the second top button, DPI-cycle, as logical 16 -> wire 0x60. The official
Device167 defaults identify DKM_SB_03 with DPI_CycleUp; managed EMwDKMKeys gives
DKMID_DKMKEY_SB03 = 82. The native input dispatch at RVA 0x67790 sends 82 to
0x67809 -> 0x60. DPI action category 6/data [6] decodes at 0x55084 to abstract
action 11, mapped through table 0x6003c to 0x5f6a1 (DPI/CycleUp). The default
cycles the existing DPI stage table; no stage values, primary clicks or sensor
configuration are written. The fresh control-16 trial preparation read category
6/data [6] from both initialized wired slots (1 and 2), with slot 1 active and
the twelve-button plate attached. The user ran the sudo preparation; the private
plan checksum and unchanged engine were independently checked. The plan remains
prepared without settings writes. The user confirmed that pressing the DPI
button cycles pointer sensitivity through different speeds and back to the
starting speed. The user then ran the apply stage and reported that it works:
physical DPI-button output as B is confirmed. The private status is applied and
its saved readback has category 2/data [0, 5]; the runner checked other tracked
records and slots unchanged. The restore stage subsequently completed: plan
integrity was checked, status is restored, and the saved final snapshot matches
the original exactly (excluding the transient device path), including DPI category
6/data [6]. The runner also checked other initialized slots unchanged. The user
confirmed physical DPI cycling works again after restoration. Reconnect persistence
and primary-click behavior were not separately reported for this trial.
This mapping backup does not read DPI stage values,
so it cannot establish that the stage table is unchanged.

Per-device `defaults` now live in devices/models.json: plate trigger keys and
verified onboard bindings, extra-control labels/IDs/addresses/default actions.
Both Python and Rust consume it, including creation's grid-default validation.
The writer retains a separate safe address set and only accepts each registry
factory action on its declared position. Unknown model defaults remain empty;
experimental model capabilities and input learning are unchanged. See
devices/README.md for the schema. Existing three-control drafts append a fourth
Keep stored binding control without replacing edits; old three-control hardware
backups preserve the current DPI record. New backups include all four controls.
Restore defaults now covers sixteen supported bindings. No live writes were made.
Validation passed 52 Rust and 47 Python/Qt tests, including DPI-only writes/raw
rollback, legacy backup preservation, profile migration and registry integrity.

The reset button is now Restore defaults. In hardware mode it stages all twelve
grid defaults plus wheel left/right horizontal scroll and scroll-mode cycling;
it sends no device requests until Save bindings to mouse is clicked. It works
offline and preserves other plates. Software mode retains its existing stop/reset/
apply-pass-through behavior. Each wheel control has a separate Factory default
mode and per-control Use default stages that preset; Keep stored binding remains
a separate option and is still the initial draft state for existing profiles.
Factory actions are explicit position-scoped presets: logical 13 -> category 1
data [0x68], 14 -> 1/[0x69], 15 -> 18/[4]. The native decoder confirms the earlier
captured 18/[4] is Haptic_CycleUp; it is now labeled Cycle wheel modes. See the
native trace in inspection/ONBOARD.md. These presets restore binding functions,
not device settings such as wheel tension, stages, DPI, RGB or Synapse turbo rate.
Physical horizontal output/cycling remains unverified; no live writes were made.
Validation passed 51 Rust and 46 Python/Qt tests, including scoped preset
validation, rollback, offline draft-only restoration and profile round trips.

The user reported "That works" after left tilt -> B, confirming physical B
output. Local wheel-test-13 status now reports restored, so the runner verified
exact original tracked records after restoration. Physical original Back behavior,
primary clicks and reconnect persistence have not been separately reported.

At the user's request, removed separate authorization requirements from repository
instructions, runners and CLI flags. Test stages now use their saved plans directly;
checksums, durable backups, stale-state checks, repeat prevention and recovery
remain. Sudo/polkit authentication remains. scripts/wheel_test.py is a convenience
entry point; wheel_controlled_test.py also runs directly without approval arguments.
Existing completed plan files remain historical evidence and are not reused.
This cleanup passed 50 Rust tests, 45 Python/Qt tests, formatting, Clippy,
debug/release builds and example config validation. CLI help confirms that the
wheel/slot runners and hidden slot-trial engine command have no approval flags.

The user asked to run the wheel remapping test. Added scripts/wheel_controlled_test.py
with prepare/apply/verify/restore stages, initially logical control 13 (left tilt)
to B on the currently active wired slot. Preparation is read-only and saves all
initialized snapshots in a private checksummed plan. The saved plan hash, engine/runner/session hashes, stable state and a 12-button
plate are checked before test stages. The prepared active-slot backup must be durably written before
commit. Apply is consumed before the commit, so a lost reply cannot invite a
repeat apply. Verify reads only; restore accepts either the original state or
exactly the intended target-to-B change and verifies exact original tracked
records afterward. All other slots are checked before and after writes. The
target slot is re-read after inspecting other slots so helper selection cannot
accidentally address a different slot. Helper exits after each stage. Physical
input, reconnect persistence and restored behavior must be recorded separately.
The runner's six simulated
tests and four existing controlled-test regressions pass. The shared Session now
accepts supported protocols 2/3/4; the wheel-specific session requires protocol 4,
wheel_controls capability and watches the plate, aborting on non-12-button events.

The user subsequently ran the read-only controls query on the wired mouse.
All three getters succeeded: logical 13 returned category 1/data [4], logical 14
category 1/data [5], and logical 15 category 18/data [4]. The first two decode as
Back/Forward using the existing mouse-action decoder. Keep the last action as an
opaque firmware assignment until its meaning is independently established; do
not infer physical behavior from readback. Added a captured-state regression for
preserving all three during a grid-only save and restoring category 18 via backup.
At that stage writes and physical behavior remained unverified; the subsequent
left-tilt test and restoration are recorded above. The readback command did not modify any mappings.

Wheel controls added to Mouse memory mode: tilt left/right and the scroll-mode
button below the wheel. Official Device167 DefaultMappings.xml uses Mouse
Button6/Button7 and DKM_57 (scroll stage cycle). Managed ConvertDKMKeystoMw maps
DKM_57 to 87; native converter RVA 0x67790 maps mouse buttons 6/7 to wire
0x34/0x35 and DKM 87 to 0x6d. See inspection/ONBOARD.md for the trace.
Logical positions 13/14/15 have explicit allowlisted addresses; left/right/middle
remain unwritable. Snapshots retain the twelve grid records and add a default-empty
controls array for compatibility. New reads get all three control records;
backup/restore/stale checks/rollback include them. Legacy backups preserve current
wheel records. Normal saves only write controls explicitly edited in the draft;
Keep stored binding preserves exact firmware actions, including unknown encodings.
Initially Reset 12 buttons left wheel drafts intact; the Restore defaults behavior
above supersedes this. Software mode retains its
existing plate triggers and leaves firmware wheel behavior intact. No onboard
sequence support or wheel tension/scroll-stage settings were added.
New GUI controls and drafts are isolated from other models. The protocol-4 hello
advertises wheel_controls and onboard_prepare accepts an optional controls list.
Read/write/output of these three IDs still needs a user-run hardware check; no
agent-driven live writes were performed. New read requests are statically derived
getters, not guessed probes. Validation passed 49 Rust and 39 Python/Qt tests,
including each address, raw unknown-record rollback after lost acknowledgement,
legacy backup preservation, modern backup restoration, GUI translation/persistence
and storage-mode switches. Debug/release builds, Clippy and formatting passed.

Standalone slot activation is now implemented. Select any initialized inactive
slot and click Activate slot; it can read an unread target without changing the
draft. The protocol-4 hello advertises slot_activation. Preparation reads/checks
the target and previous active slot; the GUI fsyncs both backups before commit.
Commit rechecks both snapshots, writes only 05/04, and verifies both complete
tracked snapshots with only active changed. No mapping/mode writes occur. Normal
mode, standard target primary/middle clicks and the detected 12-button plate are
required. A failed acknowledgement triggers restoration of the old active slot
and unchanged-record checks; incomplete rollback is explicit. Successful activation
updates the dropdown and stored tiles while leaving the helper connected for
further reads/switches; quitting does not request any restoration. No new hardware
writes or live activation tests were performed in this implementation turn.
Validation passed 46 Rust tests and 38 Python/Qt tests, including lost-switch
acknowledgement, failed rollback, unsafe/stale targets, two durable backups before
commit, second-backup failure, and draft preservation. Prior creation evidence
and tests below remain applicable.

Slot creation now has a desktop path for wired 00a7 with the detected 12-button
plate. The user completed the slot-3 trial: creation returned standard
left/right/middle mappings and the twelve expected grid keys, all grid records
with declared length 1. The runner removed slot 3, verified original slots 1/2,
active slot 1 and normal mode. No physical new-slot output, reconnect/power-cycle
persistence or desktop creation transaction has been tested on hardware.

The GUI's Create slot button chooses the next unused ID, prepares snapshots of
all existing slots, durably saves the complete creation plan, then acknowledges
the commit token. Session protocol 4 advertises slot_creation only for wired
00a7. Creation rechecks every snapshot immediately before allocation, reads and
validates new primary/middle/grid defaults and verifies original slots with only
the added inventory entry allowed. No button mappings, mode or metadata are
written; the previous active slot stays active. Success selects the new inactive
slot and keeps the local draft. Save remains a separate action that activates the
selected slot. On any allocation/verification failure, cleanup only removes the
new target, including after a failed allocation acknowledgement; unexpected
activation first restores the previous active slot. Incomplete cleanup is an
explicit error, never a silent retry. Existing-slot deletion and first-profile
creation remain unsupported. Receiver creation remains disabled.

The hidden onboard-slot-trial CLI and scripts/slot_trial.py remain available for
temporary experiments. The completed plan is consumed and must not be repeated.
New experiments require fresh snapshots and a new plan.
Private snapshots cover only the established read contract, not complete profile
images. Creation backup files contain a plan with all original snapshots and a
target; the ordinary Restore backup command accepts individual mapping snapshots,
not the complete creation plan. See inspection/ONBOARD.md for evidence and limits.

Validation passed 43 Rust tests, 36 Python/Qt tests, formatting, Clippy with
warnings denied, debug/release builds and example config validation. Coverage
includes stale/existing targets, lost allocation acknowledgements, unexpected
activation, invalid primary defaults, failed cleanup, durable GUI backups before
commit, backup failure, unchanged drafts, and receiver/plate capability gates.

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
- Change of button 1 (firmware ID 0x40) from 1 to B through
  the real session using canonical GUI actions. Save and independent readback
  showed B, the other eleven exact records, standard primary mappings, unchanged
  mode and unchanged active slot.
- User confirmed physical B output, fully quitting NagaLibre, reconnecting/
  power-cycling, B still working, and normal left/right/middle clicks. A fresh
  read-only session verified the saved B and other records.
- Backup restore: save response and independent readback matched all
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
Do not commit the private files or mouse serial. That test is complete. A new apply requires fresh backups and a prepared plan.

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

The prioritized, session-sized feature backlog is in [TODO.md](TODO.md), including
Synapse gaps beyond OpenRazer's current Naga V2 Pro API. Use it to select the next
chunk and keep the hardware evidence in this handoff current.

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
invalidate the summary. At that stage slot creation was unimplemented; the current
desktop creation path is described above. README, CLI/support
guides and issue form explain the distinction and optional serial-free inventory.

Validation covers captured capacity 5/IDs 1,2, sparse IDs, smaller capacities,
padded replies, empty inventories, getter-only transport calls, stale-capacity
save rejection, legacy restores and disabled UI entries. New capacity display
has not yet been separately confirmed by the user on hardware.
All 34 Rust and 32 Python/Qt tests passed, along with formatting, Clippy with
warnings denied, debug/release builds, whitespace and support-form YAML checks.
