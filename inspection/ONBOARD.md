# Naga V2 Pro onboard profiles

## Evidence and provenance

The re-uploaded Synapse bootstrap installer is identical to the original:
SHA-256 `e4eabf1a0cf030b773a1a14ed22f4cb337c5f85638863260215b6315d83eb570`.
It does not contain the full device controller. It was extracted, never run.

The model-specific Device167 package was obtained from
[Razer's CDN](https://cdn.razersynapse.com/1709508222Kov7zCpDRazer_167_0_Setup_v3.9.0331.030402.exe).
SHA-256 `564279d02e021a3ab3df1824d192cfc3781ed917dadfc5661189dbf84ccf6c25`.
The installed module identifies wired `AriaT1V2Wired_00A7`, receiver
`AriaT1V224G_00A8`, and Bluetooth `AriaT1V2BTLE_00A9` variants.

Static extraction and ILSpy decompilation of `RSy3_OnboardMem3.dll` reveal
`CRSy3_OnboardMem3M.ConvertToMacroEvents`, `AddMacro`, `GetMacroSize`, and
native calls through `OBM3_AddMacro`. Keyboard events carry makecodes, flags,
and delays. Native controller strings include `Storage_Macro_Add`,
`Storage_Macro_Data`, `Storage_Macro_Remove`, and `Storage_Macro_Info`.
This establishes a separate macro-storage path; the managed event structures
are not the USB wire format. No proprietary binaries or decompiled source are
redistributed, linked, or required at runtime.

The implementable profile protocol was cross-referenced against the MIT-licensed
[razer-naga-companion protocol implementation](https://github.com/Bmwascher/razer-naga-companion/blob/master/src/NagaBatteryTray/Hid/RazerProtocol.cs)
and its [device transport](https://github.com/Bmwascher/razer-naga-companion/blob/master/src/NagaBatteryTray/Hid/RazerDevice.cs).
That project's documentation reports exact Naga V2 Pro hardware verification,
including persistence across power cycles. These are external observations;
**NagaLibre's USB serial, mode, inventory and active-slot getters have now
succeeded on a physical mouse, as have button-record reads for slots 1 and 2;
slot 1's decoded factory actions match observed physical events. A controlled
slot-1 button-1 to B write, app exit/power-cycle persistence and exact backup
restoration have also passed on USB; other write cases remain unverified**.
NagaLibre implements the protocol independently in Rust.

## Implemented protocol

USB `1532:00a7` / `1532:00a8`, hidraw feature report ID zero, 90-byte body
(91 bytes with the report-ID prefix). The control interface is selected from
its HID descriptor, not an assumed interface number. Bluetooth is unsupported.
Transaction `0x1f`; XOR checksum over body bytes 2 through 87. Replies must
match transaction, class, command, checksum, and getter argument echoes.
Busy replies are polled without resending writes.

| Class/command | Operation | Payload size |
| --- | --- | --- |
| `00/82` | Serial number | 22 |
| `00/84`, `00/04` | Read/set normal or driver mode | 2 |
| `05/81` | Initialized slot inventory | Request 6; reply capacity byte + returned slot IDs (up to 6 total) |
| `05/84` | Read active slot | 6 |
| `05/04` | Activate initialized slot | 1 |
| `02/8c`, `02/0c` | Read/write button record | 10 |

The physical USB probe returned mode `00 00`, inventory `05 01 02` with
reported payload length 3, and active slot `01 00 00 00 00 00`. Inventory's
first byte is capacity, not a count of returned entries. The source parser
accepts compact and six-byte padded lists with initialized IDs bounded by capacity; this fix builds and passes
automated tests and both slots now read successfully on the physical mouse.
It does not alter transport framing.

Both slots report standard primary left/right records. Raw probing of slot 1
found category-2 length-2 records on grid buttons 1/2, and length-1 records on
buttons 3–12. Despite length 1, the modifier and HID usage bytes are both present:
ID 0x42 returned `01 42 00 02 01 00 20 00 00 00`. All twelve usages match
physical events KEY_1..KEY_9, KEY_0, KEY_MINUS, KEY_EQUAL in order. The earlier
[0] decoding discarded the trailing usage. The source now reads both keyboard
bytes for category 2 with declared length 1. A fresh physical read verified
all twelve decoded factory keys and preservation of raw records on buttons
3–12. A subsequent controlled button-1 to B write, app exit/power-cycle
persistence and exact original-backup restoration passed on USB. The user
confirmed physical B and left/right/middle clicks before restore, then key 1
after restore; original primary mappings and all twelve wire records were
verified exactly after restore. No hardware write counter was recorded;
only-ID-0x40 write behavior is regression-tested, with final unchanged records
checked on hardware.

Noncanonical records include optional `raw_record` metadata containing category,
original length, and all five data bytes. Snapshot JSON preserves this for exact
restore and rollback. Raw metadata is checked against decoded category/data
before writes. Canonical records omit it, and older snapshots still deserialize.
Full raw payloads remain available through `onboard-probe --slot 1`; this reads
primary buttons and grid without setting mode, activating slots or writing.

A button record is `[slot, button_id, hypershift, category, data_length, data…]`.
The normal/secondary selector and trigger encoding are now independently traced
in [HYPERSHIFT.md](HYPERSHIFT.md), with a separate read-only diagnostic export.
All existing mapping writers still use the normal bank.
Grid positions 1–12 address IDs `40`–`4b`. Category 2 encodes
`[modifier_mask, USB_HID_keyboard_usage]`; category 1 encodes a mouse button.
The mapping writer allows grid IDs plus the three explicitly mapped wheel controls
described below. Primary IDs 1, 2 and 3 never reach the writer. Successful saving sets normal mode
and activates the selected slot; no helper is needed to process these bindings.

## Save and recovery contract

1. Read an existing initialized slot, identity, mode, active slot and primary clicks.
2. Reject unsupported actions and unexpected primary clicks or device modes.
3. Re-read to reject stale state; send the prepared snapshot to the unprivileged GUI.
4. GUI atomically saves a private JSON backup, fsyncs file and directory, then
   acknowledges the prepared token. Failure here prevents all settings writes.
5. Recheck the snapshot, set normal mode if needed, write only changed grid
   actions, GET each entry to verify, activate the slot, and verify the full state.
   Normal saves compare decoded actions and retain original records for unchanged
   bindings. Changed actions are verified by decoded action, allowing equivalent
   firmware encoding. Unchanged records are verified byte for byte. Explicit
   backup restoration compares and verifies wire bytes even when actions match.
6. If any operation fails, attempt to restore every attempted binding (including
   a write whose acknowledgement failed), previous active slot, and previous mode.
   Rollback verifies original wire bytes, including unknown actions and trailing
   data. An incomplete rollback is reported explicitly. Disconnect/power loss can prevent
   rollback; keep the backup.
7. On success, the GUI stops the privileged helper. Closing the app leaves the
   firmware bindings in place.

Restore validates the backup's serial and USB product against the connected
mouse, makes a fresh backup of the current state, then uses the same write and
verification path. It restores the saved side-button records and activates their
slot. It does not restore primary clicks, delete profiles, or recreate macro data.
Existing macro references in a backup can be restored only while the underlying
mouse macro data still exists.

## Limits and next evidence

Standalone activation uses the existing `05/04` selector with a separate prepared
transaction. Both target and previous active-slot snapshots are backed up before
switching, then rechecked and verified afterward; only the active ID may change.
It requires normal mode and standard primary/middle actions on the target. On a
failed acknowledgement it attempts restoration of the previous active selector
and verifies original records without any mapping or mode writes. The desktop
flow has simulated failure/GUI coverage; standalone switching and physical output
on a different slot have not yet been verified on hardware.

The app can edit initialized slots and create unused slots on wired 00a7 after
the controlled default-allocation test below passed. It never writes primary
buttons; unexpected defaults cause cleanup of only the new slot. Deleting existing
slots and erase remain absent. The GUI
keeps a local draft; reading mouse slots displays the raw records in its log and
does not import them into or replace the draft. Saving compares all twelve draft
actions and writes only changed actions to the selected slot, retaining original
encoding for unchanged bindings. Hardware support currently covers the 12-button
plate, standard keys, modifier shortcuts and mouse-button outputs.

Multi-step onboard macro encoding, allocation, upload and deletion remain
unimplemented. Macro sequences are rejected before hardware writes and are
available in the separate software mode. Other plates use software mode with
input learning; automatic plate identification is now verified on USB (see
[FACEPLATES.md](FACEPLATES.md)).
DPI, RGB, firmware updates and arbitrary vendor command probes are outside this
implementation.

First hardware diagnostic: `sudo ./target/release/naga-macros onboard-read`. It only issues
getters (HID feature SET_REPORT is also the transport used to request a getter).
The controlled single-key write, app exit/power-cycle persistence, primary
controls before restore, and exact backup restoration have passed on one wired
mouse. Factory reset, physical failure rollback, unknown-action restoration,
modifier/mouse outputs, inactive-slot activation and receiver operation remain
untested. Post-restore physical primary clicks were not separately reported.
No broader hardware support or macro persistence is established by this test.

## Slot capacity enumeration (2026-10-19)

The inventory getter's first byte is now retained as `slot_capacity` in snapshots,
separate from the initialized `slots` IDs. New reads always supply this metadata;
older backups deserialize with unknown capacity rather than assuming five.
Fresh-snapshot comparison includes capacity, so a capacity change invalidates a
prepared save. Legacy backup restoration still uses fresh device state.

`onboard-slots` uses the existing mode/slot-inventory/active getters, returning
`capacity`, `initialized` and `active` without serial or button reads. It supports
empty inventories and does not create profiles. The V2 Pro protocol decoder
supports capacities 1–5 with compact or six-byte padded replies, rejecting invalid
IDs, duplicate entries, unsupported capacity and active IDs outside capacity.
This does not establish other models' onboard protocols.

The GUI shows the reported number of slots, disables uninitialized entries, and
displays initialized count versus capacity. Older helper snapshots only show
known initialized IDs with capacity explicitly unavailable. No slot-creation,
activation or mapping-write command was added by this change.

## Slot allocation investigation (2026-10-19)

Static analysis of the official Device167 wired controller (SHA-256
`dc7dcf529731e95ce6f712e7ce5166423b80ea26087648061cf343e7594578d7`)
identified the following native paths, expressed as RVAs:

- `CProtocol25` allocation at `0x282d0`: class `05`, command `02`, one-byte slot.
- Removal at `0x2d230`: class `05`, command `03`, one-byte slot; refuses slot 1.
- Metadata upload at `0x30720`: `05/08`, chunks of up to 64 bytes, prefixed by
  slot, big-endian offset and big-endian total length.
- `CStorage` allocation handler at `0x53c80` allocates, then uploads 250 bytes of
  profile metadata for slots above 1; it removes the allocation if upload fails.
  It can replace existing profiles. NagaLibre's trial explicitly refuses that.

These are independently described protocol facts, not redistributed decompiled
source. The upstream [companion protocol implementation](https://github.com/Bmwascher/razer-naga-companion/blob/master/src/NagaBatteryTray/Hid/RazerProtocol.cs)
also identifies allocation/removal opcodes; that is not proof of firmware defaults.
Allocation alone does not establish complete initialization, usable clicks,
safe activation, Synapse naming compatibility or power-cycle persistence.

`python3 scripts/slot_trial.py prepare` issues only existing getters, saving
private snapshots of every initialized slot and a checksummed plan.
`python3 scripts/slot_trial.py run` checks engine/runner/plan hashes
and consumes the plan before launching the hidden `onboard-slot-trial` command.
The backend rechecks all snapshots and creates/fsyncs an exclusive private journal
before allocation. It reads the temporary slot's primary, middle and twelve grid
records, then removes only that new slot. If allocation unexpectedly activated it,
cleanup first restores the previous active slot. Lost acknowledgements are never
retried; cleanup and full tracked-state verification still run. Failed cleanup
requires inspection, not a repeat allocation. No button, mode or metadata writes
are made by this temporary experiment.

The snapshots cover the existing read contract (identity, mode, inventory,
active slot, left/right and twelve grid records), not a full image of DPI, RGB,
wheel, Hypershift, macro memory or all firmware state. They cannot recreate a
deleted pre-existing profile. This is why the trial refuses existing targets and
does not claim complete profile cloning or recovery.

### Successful wired allocation trial and desktop creation

The user ran the temporary-slot-3 trial. It reported successful removal
and exact original tracked-state verification. The newly allocated slot read back
left/right/middle as category 1, data 1/2/3 respectively. All twelve grid entries
read as category 2 with modifier zero and HID usages
`1e 1f 20 21 22 23 24 25 26 27 2d 2e`. Every grid record had declared length 1
while retaining both keyboard bytes, matching the previously observed encoding.
The successful trial also checked unchanged active slot 1 and normal mode before
removal. These are hardware readbacks, not physical output or persistence tests.

The desktop creation path uses that allocation without metadata or mapping writes.
It requires a fresh read and a durable GUI backup of every existing slot, rejects
existing targets, receiver connections and non-normal mode, then rechecks state
immediately before allocating. It validates standard primary/middle and exact
decoded factory grid actions, and compares every existing snapshot with only the
inventory's addition allowed. A failed allocation acknowledgement still enters
cleanup; only the newly allocated slot may be removed. An unexpected activation
is restored to the original slot before cleanup. Failed cleanup is reported
explicitly and not retried. Success selects the inactive new slot for editing;
draft bindings are saved separately using the existing mapping path. First-profile
creation, existing-slot deletion, Synapse metadata/name compatibility, receiver
creation, physical operation and power-cycle persistence of newly created slots
remain unsupported or unverified. The complete desktop creation transaction has
automated coverage but has not yet been exercised on hardware.

## Wheel tilts and scroll-mode button (2026-10-19)

Static provenance uses the same official Device167 package and controller hash
listed above; proprietary payloads and disassembly remain private. DefaultMappings
for device 167 assigns MouseInput Button6/Button7 to ScrollLeft/ScrollRight and
DKM_57 to Cycle_Up_Scroll_Wheel_Stages. These are host input names, not wire IDs.
Configurator.167_0's OBMMappingConverter.ConvertMouseInputToMBtn (RVA 0x12248)
converts Button6/7 to abstract mouse inputs 6/7. ConvertDKMKeystoMw (RVA 0x11ba0)
converts DKM_57 to DKM makecode 87 (0x57).

The native storage getter calls input converter RVA 0x67790 before invoking the
button-record getter through protocol vtable offset 0x274. In the mouse-input
branch, jump table RVA 0x679b4 selects blocks at 0x678bc/0x678c0 for inputs 6/7,
which return 0x34/0x35. For DKM 87, the byte dispatch table at RVA 0x6792c and
jump table at 0x678d8 select block 0x6781d, returning 0x6d. The storage caller at
RVA 0x56474 passes that converted ID into the getter at RVA 0x28ca0, which encodes
class 02, command 8c through the transport getter (the native command header
contains 020c; the getter transport adds the read bit). Logical NagaLibre IDs
13/14/15 explicitly map to wire 34/35/6d. No arithmetic extension of the thumb-grid
address range or primary-click writer is permitted.

The app reads all three records into a separate optional controls snapshot field.
It writes only explicit supported key/shortcut/mouse-button edits, through the
same durable backup, stale checks, per-record readback and rollback used by the
grid. Unknown original firmware actions/raw encodings can be retained or restored
exactly. Keep stored binding leaves the current action intact; it does not guess
or synthesize the scroll-mode/tilt factory action. Main clicks and wheel rotation
remain outside the writer. The user has since supplied successful getter output:
logical 13 = category 1/data [4], logical 14 = category 1/data [5], logical 15 =
category 18/data [4]. The first two decode as Back/Forward; category 18 is retained
opaquely. This verifies readable records at these addresses, not physical
identification/output, writes or persistence. The UI exposes these controls in Mouse memory mode on
V2 Pro's 12-button layout; software relative-wheel triggers and other models'
control maps remain unimplemented.

### Default binding presets

The UI now stages function defaults for all fifteen supported controls. Tilt
presets use category 1/data 68 and 69 (hexadecimal). Native CStorage's decoder at RVA 0x54bf0
maps those values to abstract mouse actions 8/9, and the setter at RVA 0x57e50
maps them back through its dispatch table at 0x58380. The managed Button mapping
converter at RVA 0x12390 resolves those actions to MouseAssignment values 10/11,
which the UI maps to horizontal-scroll assignment types 6/7. By comparison, wire
09/0a map to abstract actions 6/7, MouseAssignment 6/7 and UI vertical-scroll types
4/5; they must not be used for horizontal presets. The UI's explicit RepeatScrollUp/
RepeatScrollDown IDs corroborate the separate vertical-scroll mapping. These presets
restore the function, without uploading Synapse's separate turbo/repeat settings.

For scroll-mode cycling, decoder category 18 dispatches to RVA 0x551df, setting
native mapping group 0x2c. Data byte 4 dispatches through table 0x55448 to block
0x54c6c, setting abstract action 5. The JSON converter's group-specific action
table at 0x60070 maps action 5 to block 0x5fc9f and string Haptic_CycleUp. This
also establishes the meaning of the user's captured category 18/data [4].
Normal save validation only accepts these three additional factory actions at
logical positions 13/14/15 respectively. Full restoration still preserves opaque
original wire records through the existing backup path. Default presets are
simulated-test covered; physical horizontal scrolling and mode cycling remain
unverified. Restore defaults edits the draft; Save performs the transaction.
