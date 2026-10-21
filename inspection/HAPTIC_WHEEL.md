# HyperScroll Pro wheel protocol research

## Current limitation

Stored-profile table replies may alias: reported velocity is the CW prefix, and
both extracted firmware images drop intra-page offsets when locating subtables.
See [firmware investigation](HAPTIC_FIRMWARE.md#stored-table-address-translation-discards-subtable-offsets).
Earlier matching getter bytes do not establish independent table preservation.
Full upload from this ambiguous backup pattern is now blocked; the next step is
a read-only stored/volatile comparison, not a changed custom parameter.

## Status and provenance

Research completed 2026-10-20 for the Device167 wired and receiver native
controllers. This establishes host encodings, not firmware acceptance, tactile
behavior, persistence or recovery. The research itself performed no device
requests. A subsequent wired getter capture and stage transaction implementation
are described below; custom setters remain absent.

The official package, extraction policy and download provenance are in
[ONBOARD.md](ONBOARD.md). All addresses below are RVAs, relative to each PE image
base (`10000000` in the inspected images). Local proprietary payloads, IL and
disassembly remain under ignored `inspection/payload/`.

| Input | SHA-256 |
| --- | --- |
| Device167 setup | `564279d02e021a3ab3df1824d192cfc3781ed917dadfc5661189dbf84ccf6c25` |
| Wired `RzCtl_00A7.dll` | `dc7dcf529731e95ce6f712e7ce5166423b80ea26087648061cf343e7594578d7` |
| Receiver `RzCtl_00A8.dll` | `1a9543ae2a71aa3b2e8ae028e2de10dfa3df44cfac907885a621e087680c9cc3` |
| `Configurator.167_0.dll` | `c4ebf9405e9fee7fb1258184b3ac8f945fae5c07d1c04a88486222b6ada11889` |

Razer's [wheel customization guide](https://dl.razerzone.com/videos/transcripts/How%20to%20customize%20the%20HyperScroll%20Pro%20Wheel%20of%20the%20Razer%20Naga%20V2%20Pro-9757.pdf)
describes five presets plus Custom, stage reordering/disabling, tension 0–100,
steps 8–96 and separate up/down curve editing. Those are product/UI ranges,
not verified firmware bounds.

Checked [OpenRazer's mouse classes](https://github.com/openrazer/openrazer/blob/master/daemon/openrazer_daemon/hardware/mouse.py)
on 2026-10-20: `RazerNagaV2ProWired` and its receiver subclass do not advertise
haptic-stage or custom-wheel methods. This feature still fills a gap in that
model's exposed API. Other models' wheel methods do not establish this protocol.

## Trace chain and connection scope

`CHapticScroll` registers these five JSON operations for get and set:
`HapticScroll_ActiveStage`, `HapticScroll_Stages`,
`HapticScroll_BrowsingMode`, `HapticScroll_CustomStage`, and
`HapticScroll_CustomStageMetaData`. Wired registration is at `275f0`/`279c0`;
receiver registration is at `27200`/`275d0`.

| JSON operation | Wired get / set | Receiver get / set |
| --- | --- | --- |
| ActiveStage | `25350` / `267e0` | `24f50` / `263f0` |
| Stages | `26440` / `27340` | `26050` / `26f50` |
| BrowsingMode | `254d0` / `269c0` | `250d0` / `265d0` |
| CustomStage | `25580` / `26b60` | `25180` / `26770` |
| CustomStageMetaData | `26110` / `27140` | `25d20` / `26d50` |

Follow their indirect calls through the protocol vtables at wired `7ab1c` and
receiver `7fc04`. These are the actual tables containing the known mapping
getter at slot `+274`, not merely similarly named functions or strings.
All fifteen entries below were re-resolved from those tables and their full
instruction sequences through return compared across the two controllers.
They match after normalizing image addresses; stack offsets, immediate values,
byte swaps, copy sizes and indirect vtable calls remain identical.

| Operation | Vtable get / set | Wired get / set | Receiver get / set |
| --- | --- | --- | --- |
| Active stage | `538` / `53c` | `2a0e0` / `2e670` | `29cf0` / `2e280` |
| Enabled stages/order | `540` / `544` | `2a4b0` / `2e930` | `2a0c0` / `2e540` |
| Browsing mode | `548` / `54c` | `2a120` / `2e6b0` | `29d30` / `2e2c0` |
| Older custom format | `550` / `554` | `2a530` / `2e9a0` | `2a140` / `2e5b0` |
| Custom configuration | `558` / `55c` | `2a210` / `2e770` | `29e20` / `2e380` |
| Table capacities | `560` / — | `2a430` / — | `2a040` / — |
| Table chunks | `564` / `568` | `2a320` / `2e820` | `29f30` / `2e430` |
| Metadata | `56c` / `570` | `2a160` / `2e6e0` | `29d70` / `2e2f0` |

Both controllers contain the same field encodings below. This supports separate
wired/receiver read-only implementations; neither has live haptic verification.
Bluetooth has packaged defaults and managed feature methods, but its transport
was not recovered here. It remains unsupported. Shared class names/defaults do
not establish Bluetooth feature reports or authorize probes.

## Feature-report operations

These use the established 90-byte Razer body, report-ID-zero prefix and XOR
checksum described in [ONBOARD.md](ONBOARD.md). Native requests store a packed
command word, length byte and payload; generic getter slot `+5c4` sets the read
bit. Wired getter transport `29ac0`, especially `29bb5`–`29c2c`, establishes
that `1500` becomes class/command `15/80` on the wire. Setter slot `+5c8` is
wired `2e1c0`. Do not use native packed command words as literal wire bytes.

Offsets in the following table are relative to payload byte zero. Getter
lengths are the native request's declared length and reply-buffer capacity;
actual firmware reply lengths and echoes still need captures.

| Class/get; set | Native length | Payload and returned fields |
| --- | --- | --- |
| `15/80`; `15/00` | 2 | `profile, active_position` |
| `15/87`; `15/07` | 13 | `profile, active_position, count, stage_ids[10]` |
| `15/88`; `15/08` | 1 | `enabled`; no profile argument |
| `15/82`; `15/02` | 24 | Older custom configuration, described below |
| `15/83`; `15/03` | 26 | Custom configuration, described below |
| `15/85`; — | 6 | Three big-endian u16 table capacities; no profile argument |
| `15/84`; `15/04` | Get 71; set `10 + 8*n` | Chunk prefix plus at most eight point pairs |
| `15/89`; `15/09` | 66 | `profile, metadata_length, metadata[64]` |

Getters initialize output fields to zero and populate the selector fields.
The stage getter copies `count` bytes from offset 3. That native copy lacks a
ten-entry bound; a new reader must enforce actual payload and buffer bounds
instead of copying this behavior. The metadata getter copies the smaller of
caller capacity and returned length, but reports the returned length separately.
Preserve unknown bytes/IDs and reject inconsistent lengths before decoding.

### Profiles, stage order and browsing mode

Managed `ScrollWheelStagesFeature.SetScrollStages` (`1ee68`) and
`OBMStorageFeature.SetScrollStagesToStorage` (`15558`) filter the configured
stage list to enabled entries, retaining list order. They emit each stage as
`ScrollStageMode + 129` and set `ActiveStage` to the active entry's one-based
position **within that enabled list**. It is not the preset's identifier.
The storage reader (`156b8`) subtracts 129 to recover the managed mode.
Numeric mode-to-label assignments have now been recovered from the shared
contract/UI assemblies and English resources as described below. This supersedes
the earlier inference from default display order. Physical results separately
anchor Standard and Smooth Scroll on the user's mouse.

### Verified enum, UI text and wire association

The missing shared UI dependencies were obtained from Razer's official
[Synapse core package](https://cdn.razersynapse.com/1769585343330VJAVqRazerSynapseSetup_v3.11.0228.012810.exe)
(3.11.0228.012810; SHA-256
`8f0cd09b919daf438209073502b494aa83df7009538503350728538e8aa40e20`)
and [translation package](https://cdn.razersynapse.com/1729231680NrXgFZRTRazerStringTranslationsSetup_v3.9.1130.101807.exe)
(3.9.1130.101807; SHA-256
`a364f32aafd0ebb1bb58797ecdd0b8fbe84382b002dbd352969231cedb594d6d`).
These newer shared packages are distinct from the Device167 controller package;
they were extracted statically and never executed or installed. Device167's
viewmodel references `Razer.Synapse3.ScrollingControlVM` assembly version
1.0.0.0, matching the recovered assembly identity. Retain the package-version
distinction rather than implying the UI assemblies came from Device167 itself.

`Contract.ScrollWheelLib.ScrollStageMode` in `Contract.ScrollWheel.dll` and
`Razer.Synapse3.ScrollingModels.HapticsMode` define identical values 0–5.
Each HapticsMode field has a string-value attribute selecting a translation key:

| Enum | Internal name | Wire list ID | UI name | UI resource key | Description summary |
| --- | --- | --- | --- | --- | --- |
| 0 | Standard | `81` | Standard | `Standard` | Default wheel behavior |
| 1 | Distinct | `82` | Distinct | `Distinct` | Firm ticks for precise selections |
| 2 | UltraFine | `83` | Ultra-fine | `UltraFine` | Softer movement with many small steps |
| 3 | Adaptive | `84` | Adaptive | `Adaptive` | Smoother movement at higher scroll speeds |
| 4 | FreeScroll | `85` | Smooth Scroll | `SmoothScroll` | Smooth movement for browsing |
| 5 | Custom | `86` | Custom | `CustomSmall` | User-selected resistance and steps |

The description resource key is the listed key plus `Description`. This is
established by `ScrollWheelStagesViewModel.UpdateTranslations` at RVA `2720`
and its key-selection callbacks at `318b` (name) and `31ae` (description).
`LoadScrollWheelStages` at `224c` assigns the contract Mode directly to the
model's HapticsMode. This connects the visible strings to actual enum values;
it is not merely a list of nearby strings in a binary.

The English `.g.resources` BAML string-info IDs and resource dictionary offsets
were followed to the corresponding text records, checking their record and
length framing. Description text record offsets in the extracted English BAML
are `403b8`, `4032c`, `4036e`, `402e5`, `403df`, `40416`, in enum order.
Only independent summaries are reproduced above; proprietary resource payloads
and full extracted evidence stay in ignored `inspection/payload/haptic-shared/`.

| Shared assembly | SHA-256 |
| --- | --- |
| Contract.ScrollWheel.dll (WPF common dependency) | `1752c79d11f46d53ed859b8ff94406ebaad57f4a4b13195e255d619b76cfe828` |
| Razer.Synapse3.ScrollingModels.dll | `31beebfd73c1b0167ccdf981bdbbc26ce858b7e285369d6e9a519885b1c49456` |
| Razer.Synapse3.ScrollingControlVM.dll | `292b339b8675d3aa94813299c438dd5864f794857e55170102eb3d0f332051a3` |
| Razer.Synapse3.StringTranslations.dll | `b03e874894a17d63d8673b5afd462eceb3080e60d517a7750ce5036915014037` |

The Device167 encoder's `Mode + 129` then establishes the wire column. Enum
numbers, wire IDs and enabled-list positions are three distinct things: enum 1
is Distinct (`82`), while list position 1 selects whichever preset is first in
the currently enabled order. Guided tests select by name and locate that ID in
the existing list, without assuming a position or silently reordering stages.

Managed profile indices are converted to `ProfileIndex + 1` before native
dispatch. No evidence here establishes special profile zero behavior. Use a
known initialized slot for initial inspection, and retain the requested profile
and any returned selector as separate evidence.

Defaults for IDs 167/168/169 list Standard, Distinct, UltraFine, Adaptive,
FreeScroll and Custom. The first five are enabled; Custom is disabled. These
are packaged application defaults, not the current mouse state.

Browsing mode is a separate byte exposed as JSON `Enable`, without a profile
selector in the native request. The packaged `ScrollWheel.xml` also stores
`BrowsingModeApplicationList`. A one-byte device value cannot recover that
host-side list; do not promise automatic application switching from this getter.

### Custom configuration and curve tables

The Ghidra follow-up in [HAPTIC_HOST_LIFECYCLE.md](HAPTIC_HOST_LIFECYCLE.md)
traces live versus storage dispatch, managed-index to wire-selector conversion,
the storage selector-1 skip, and the more precise curve-generation pipeline.
It finds no additional commit in the traced per-edit handlers; firmware save
lifecycle remains unresolved and Custom apply routes remain gated.

The active JSON custom handler uses `15/83`, not the older `15/82` entry:

| Offset | Type | Meaning from handler and JSON field |
| --- | --- | --- |
| 0 | u8 | ProfileIndex |
| 1 | u8 | Custom stage selector, fixed 6 in the JSON path |
| 2 | u8 | Format/mode byte, emitted as 1 by the setter; full semantics unresolved |
| 3 | u8 | AlternateCurrent |
| 4 | f32 LE | DeadzoneReductionAngleCW |
| 8 | f32 LE | TickIndexCountAngleCW |
| 12 | f32 LE | DeadzoneReductionAngleCCW |
| 16 | f32 LE | TickIndexCountAngleCCW |
| 20 | u16 BE | AngleCurrentTableCW point count |
| 22 | u16 BE | AngleCurrentTableCCW point count |
| 24 | u16 BE | VelocityFactorTable point count |

`15/85` returns the corresponding three capacities. The JSON get/set paths
check counts against these capacities before allocating/transferring tables.
Those are point counts, not byte counts, and must be bounded independently of
allocation size in a future implementation.

The `15/84` chunk prefix is:

```text
0: profile (u8)
1: stage selector (u8, 6 in this path)
2: table selector (u8: 1=CW, 2=CCW, 3=velocity)
3: starting point index (u16 BE)
5: number of points in this chunk (u16 BE, up to 8)
7: point pairs, each X then Y as two little-endian float32 values
```

The getter loops from point zero, advancing by the requested chunk count. It
declares 71 bytes even on the final short chunk. The setter computes length as
`10 + 8*n`, although the prefix plus points occupies `7 + 8*n` bytes. This
three-byte discrepancy is present in both controllers and must stay documented;
do not silently replace it with a guessed corrected write format. Read-only
work does not need to resolve that setter discrepancy.

The older `15/82` layout has the same first four bytes, then five f32 LE
values (offsets 4, 8, 12, 16, 20), with no table counts. It is not selected by
the traced JSON custom handler. Do not use it as an automatic fallback.

Managed custom generation (`OBMStorageFeature` callback `21990`) treats Up as
CW and Down as CCW. It discretizes the editable curve, scales current using
`0.2 * tension / 100`, and scales angle using `360 / steps`. The emitted
velocity table contains (-720, 1), (0, 1), (720, 1). These host-generated values
explain why firmware tables are distinct from the UI's control points; they
are not evidence of device electrical limits or a universal factory curve.
Curve interpolation/rounding still needs an independent specification and tests
before implementing custom writes.

### Metadata is a separate part of the state

`OBMStorageFeature.SetCustomScrollStageMetaDataToStorage` (`15948`) creates a
40-byte array and sends it through the separate metadata operation. Its layout:

| Metadata offset | Value |
| --- | --- |
| 0 | Custom stage Order |
| 1 | IsActive |
| 2 | IsLink (up/down editor linkage) |
| 3, 4 | Up ScrollSteps, ScrollTension |
| 5, 6 | Down ScrollSteps, ScrollTension |
| 7 onward | Up points, then Down points: each center X/Y and control X/Y as four bytes |

The packaged custom default has three points in each direction, which occupies
bytes 7–30; remaining bytes in this 40-byte allocation are initially zero.
Missing coordinates are initialized to -1 before byte conversion. Preserve
their original bytes rather than treating them as valid editable coordinates.
There are no per-direction point counts in this encoding; do not infer a
general variable-point format from the managed loop.

The native metadata envelope can carry up to 64 bytes. Forty bytes is the
managed producer's format, not a firmware guarantee: retain other lengths and
unknown tails verbatim. Metadata records intent for the editor; it does not
prove the current tables were generated from that intent. Report metadata
tension/steps as such, alongside the actual configuration and tables.

## Next chunk: bounded read-only inspection

The reader is now implemented in `src/onboard/haptic.rs` and exposed by
`haptic-read`. `scripts/inspect_haptic.py` durably checkpoints all-slot paired
mappings before the first haptic getter and verifies them afterward. The user
completed an active-slot capture over wired USB: declared reply lengths matched
the table above (including 71-byte final chunks and 66-byte metadata envelope),
stage IDs were 81–85 with active position 5, capacities were 80/80/80, actual
custom counts were 45/45/3, and metadata length was 40. Configuration mode/flags
were 1/1 and tick angles were 12 degrees in both directions. Raw payloads and
unknown metadata/table bytes are preserved; the export hash was checked locally.
No physical wheel behavior is established by this capture.

Preparing the first stage trial subsequently received a status-3 rejection for
15/89 during the all-slot sweep and stopped before writes. Inactive-slot metadata
can now retain that exact validated rejection as negative evidence; it is not
treated as successful empty data. Active-slot rejection, other status codes,
timeouts, bad lengths and bad echoes still fail. Two sweeps must agree on the
negative evidence as well as readable data. No fallback selector is queried.
The original active-slot metadata remains required for any settings transaction.
Thus the backup scope is complete active-slot state and readable inactive-slot
state, with missing metadata identified explicitly. Inactive metadata contents
cannot be verified or restored. Receiver haptic queries remain gated.

Stage-only transactions in `src/onboard/haptic_transaction.rs` use established
15/00 and 15/07 setters, require an initialized active slot, and preserve the
captured custom state. Mock tests cover unchanged saves, stale raw bytes, lost
save/restore acknowledgements, failed rollback and other-slot changes. A fresh
wired active-slot stage-position-1 trial subsequently passed save/readback and
exact restoration; its backup/engine hashes and restoration receipt were
independently checked. The user reported chunkier, less defined ratcheting.
Inactive slots 2 and 3 rejected metadata explicitly with status 3. The user
confirmed normal click behavior and reconnect persistence. After restoration,
they reported a possibly different wheel feel with normal operation. Exact
stored restoration does not settle that physical observation; a getter-only
follow-up compares current state with the completed trial's original backup.
Original tactile restoration and stage-order testing remain open. Custom
framing, bounds, generated curves and custom recovery remain unresolved.

The subsequent getter-only post-restoration check passed for all three backed-up
slots: current wheel fields, identity/state and paired mappings matched the
original, with stable repeated reads and active positions 5/1/1. Its private
receipt and original backup/helper hashes were independently checked. This is
additional readback evidence, not confirmation of identical physical feel.

The native 15/07 setter zero-initializes its ten-entry array before copying the
enabled list. Normal saves now zero unused entries when changing that list;
preserving obsolete enabled IDs beyond a reduced count would differ from native
framing. Explicit backup restoration instead uses the exact original 13-byte
record, verifies it byte-for-byte, and preserves nonstandard unused bytes. A
regression covers shortening/reordering to [85,81], manual cycling before
restoration and a lost acknowledgement, including nonzero original padding.

The user completed that fresh [85,81]/position-2 trial: save/readback and exact
original restoration passed; backup/helper hashes and applied/restored receipts
were independently checked. They reported defined chunky ratcheting for `81`,
confirmed reconnect persistence, identified their original `85` feel as free/
smooth scrolling, and confirmed original scrolling worked after restoration.
This anchors the two named preset identities physically. The result does not
separately confirm cycling between the two entries. Guided testing of the five
built-in modes and physical cycle/restore observations is the next step; Custom
remains outside that suite until its settings work is complete.

The original read-only design requirements follow for reference:

Implement a separate diagnostic snapshot, initially for wired 00a7, containing
raw reports and decoded fields for active stage/order, browsing mode, table
capacities, `15/83` custom configuration, all three bounded tables and metadata.
Receiver inspection should be gated and tested independently. Reuse descriptor
discovery and strict transport validation; preserve actual reply lengths and
echoes, without guessed commands, fallback selectors or any setters.

Before live inspection, establish device identity and durably back up existing
mapping state under the standing hardware procedure. Double-read haptic state
with identity/mode/active-slot/inventory/plate guards. Treat stage cycling or
external-controller changes as an unstable capture, not a reason to accept
mixed state. Test malformed lengths/counts, oversized capacities, truncated
chunks, unknown IDs, non-finite floats and state changes using synthetic
reports; retain actual captures for later regression coverage.

This export must not be accepted as a restorable settings backup until write,
verification and recovery contracts exist. Existing mapping backups contain
none of these wheel settings. Future basic writes must preserve the enabled
list and its active position together. Custom recovery additionally needs the
configuration, all tables and complete metadata; UI defaults are insufficient.

Hardware work must establish getter reply shapes/echoes, slot/global scope,
the mode byte, firmware bounds, setter framing, acknowledged/partial-write
recovery, tactile behavior and power-cycle persistence. Research completion
does not close any of those later roadmap chunks.

## Guided built-ins and next bounded setter check (2026-10-20)

The user completed all five named built-in feel checks, five-button-press
cycling back to Standard, and return to original Smooth Scroll feel with normal
scrolling/clicks after each restore. Each completed child has exact stored-state
restoration and verified backup/helper hashes. Ultra-fine explicitly persisted
across USB reconnect; other individual yes-to-feel responses do not independently
establish persistence. No trial is outstanding.

`scripts/probe_haptic_table.py` now prepares a durable full captured-state backup,
then invokes a hidden bounded replay helper. It sends only the original first
eight CW points to 15/04 with native declared payload length 74 (7 header + 64
point bytes + 3 deterministic zero bytes). It neither generates a curve nor
changes configuration, metadata, enabled stages, active stage or mappings.
After the attempted replay, it checks state, replays original bytes and checks
all captured state exactly. A fsynced helper journal precedes any write. Failed
acknowledgements cannot suppress restoration; recovery accepts differences only
within those eight point records and verifies final state without masking.
Recovery-only invocation cannot repeat an already completed journal. Fault tests
include NaN point corruption, lost acknowledgements, refused restoration,
unrelated changes, stale state, existing journal and changed device-node path.

An acknowledged idempotent replay would establish
accepted framing and unchanged readback, not support for generated values,
configuration/metadata writes, firmware parameter bounds or Custom tactile output.
No alternative packet lengths or command variants are attempted.

### Rejected table replay and upload sequencing

The first live unchanged-point replay returned a validated `15/04` status-3
rejection. The original-byte replay also returned status 3. Initial readback
and final verification found the complete captured original wheel state and
paired mappings unchanged. The completed private result is restored_exactly
with probe_passed false; original backup/helper hashes match. This does not
prove table writes are unsupported, nor identify the rejection's cause. No
recovery or retry is outstanding.

The generic native setter at wired RVA `2e1c0` copies the length byte from its
command structure directly into the feature report and copies exactly that
many payload bytes (`2e2c9`–`2e302`); there is no special length correction for
the table command. The CustomStage JSON handler invokes configuration `+55c`
at `26e60` before table `+568` calls at `26f07` (CW), `26fc7` (CCW) and `27077`
(velocity). Thus the isolated replay omitted the preceding configuration
operation used by the complete native handler. Whether firmware requires that
sequence is unresolved. Replaying configuration is not assumed harmless: it
could reset table contents and would require working table restoration.

Use evidence from a working Synapse transaction to distinguish packet framing,
sequence prerequisites and software-version differences. Do not guess another
packet length, copy native stack padding or enable broader custom writers on
the basis of this rejection. Custom editing remains unavailable.

Firmware-side analysis is now available in [HAPTIC_FIRMWARE.md](HAPTIC_FIRMWARE.md).
It independently identifies an explicit configuration-first upload context,
CW/CCW completion flags and final velocity-stage gate in the official mouse
firmware image. This replaces the earlier ordering hypothesis with a concrete
firmware mechanism for that image; installed-version identity and live complete
upload/recovery remain unverified. A partial replay after configuration is unsafe
because the first CW chunk can clear the destination/staging buffer.
