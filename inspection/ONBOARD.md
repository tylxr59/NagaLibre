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
accepts compact and padded lists bounded by capacity; this fix builds and passes
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
Grid positions 1–12 address IDs `40`–`4b`. Category 2 encodes
`[modifier_mask, USB_HID_keyboard_usage]`; category 1 encodes a mouse button.
Only the twelve grid IDs can reach the mapping writer. Primary IDs 1 and 2
are read for validation and never written. Successful saving sets normal mode
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

The implementation edits existing slots only. Creating an empty slot could leave
primary buttons unbound, so create/delete/erase commands are absent. The GUI
keeps a local draft; reading mouse slots displays the raw records in its log and
does not import them into or replace the draft. Saving compares all twelve draft
actions and writes only changed actions to the selected slot, retaining original
encoding for unchanged bindings. Hardware support currently covers the 12-button
plate, standard keys, modifier shortcuts and mouse-button outputs.

Multi-step onboard macro encoding, allocation, upload and deletion remain
unimplemented. Macro sequences are rejected before hardware writes and are
available in the separate software mode. Other plates remain manual/software.
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
