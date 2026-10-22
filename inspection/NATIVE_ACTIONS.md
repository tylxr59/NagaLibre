# Device167 native button actions

Static research and the first implementation chunk for TODO #5 (2026-10-21).
No device requests or proprietary executables were run for this investigation.
New media/scroll writes have software transaction coverage, not physical proof.

## Provenance and method

GhidraMCP 2.0 / Ghidra 12.1.4 `get_program_info` identified the wired
`RzCtl_00A7.dll`, SHA-256
`dc7dcf529731e95ce6f712e7ce5166423b80ea26087648061cf343e7594578d7`,
x86 little-endian 32-bit Windows, image base `10000000`. The configured MCP
project was locked; a separate private copy under
`~/ghidra-projects/NagaLibre-ActionsResearch` was used through the installed MCP's
Python stdio client, without removing locks or stopping another session.
`decompile_function_by_address`, string/xref queries and `disassemble_function`
were used. Addresses below are RVAs; add `10000000` for MCP queries.

The main evidence chain is:

| Operation | Wired RVA | Role |
| --- | --- | --- |
| Stored-record decoder | `54bf0` | Seven-byte record → native group/action/parameters |
| Stored-record encoder | `57e50` | Native group/action → category, length, five data bytes |
| Mapping JSON serializer | `5f0e0` | Native group/action → named JSON action |
| Profile JSON parser | `600b0` | Named JSON → native profile item |
| Profile JSON serializer | `61930` | Additional corroborating named profile-item paths |

Retained managed CIL corroborates the names: `CMapTypeM.ConvertMapping`
(`11f10` / `114c8` for sensitivity, `112a4` for mouse assignments) and
`MappingBaseV2.SetMapping` (`8a4cc` for sensitivity, `8a714` for keymaps).
These managed RVAs are in the previously extracted shared mapping assemblies,
not addresses in the wired controller. `OBMMappingConverter.GetOBMMappingForDPI`
at Device167 Configurator RVA `12a54` reconstructs TempDPI's separate X/Y fields.
Package provenance is in [ONBOARD.md](ONBOARD.md) and [HYPERSHIFT.md](HYPERSHIFT.md).
Inputs, MCP receipts and raw decompilation stay private/untracked.

Receiver equivalence was not established in this investigation. The new authoring
path is wired-only. Existing receiver key/shortcut support is unchanged.

## Record framing and preservation

The existing `02/0c` setter carries
`slot, wire_button, layer, category, length, five_data_bytes`. Getter is `02/8c`.
The wire button and layer are independent of the assigned action. None of these
action encodings grant permission to write main clicks or additional controls.

Canonical records below zero unused data bytes. Existing records are never
canonicalized just because their decoded action is recognized. Ordinary saves
skip equal decoded actions and retain their original length/trailing bytes;
explicit restoration and rollback compare exact records. A label is not evidence
that a particular firmware accepts, executes or persists that action.

## Sensitivity

Decoder category `06` selects native group `4`. Serializer `5f0e0` names that
group `DPI` and supplies the action names below. The encoder agrees on the
following shapes (all bytes hexadecimal):

| Action | Length | Data | Native action |
| --- | --- | --- | --- |
| DPI up | `01` | `01` | `1`, JSON `Up` |
| DPI down | `01` | `02` | `2`, JSON `Down` |
| Select a DPI stage | `02` | `03 stage` | `3`, JSON `Stage` |
| Temporary X/Y DPI | `05` | `05 X_hi X_lo Y_hi Y_lo` | `4`, JSON `TempDPI` |
| Cycle DPI stages up | `01` | `06` | `0b`, JSON `CycleUp` |
| Cycle DPI stages down | `01` | `07` | `0c`, JSON `CycleDown` |

The cycle actions are gated by native capability bit `20` at capability offset
`+10`. The existing physical DPI-cycle evidence proves category `06` / data
`06` for the tested normal DPI button, not every action or target in this table.

Disassembly independently confirms the nontrivial fields: `58177` writes
`0302` at record `+1` (length 2, selector 3); `5818f` writes `0505` there for
temporary DPI, followed by high/low byte stores through `581b0`. For example,
800 × 1600 becomes the seven-byte record `06 05 05 03 20 06 40`.
Stage numbering/range and firmware DPI bounds are not established by these stores.
Do not silently treat the stage byte as a one-based UI index or truncate DPI
parameters to the native 16-bit fields.

Managed sensitivity assignment 2 maps to `MAP_DPI_ONPRESS`, copies X/Y and
`Independent`, and the onboard JSON path calls it `TempDPI`. This supports an
intended temporary/pressed action. It does **not** establish firmware restoration
on release, layer changes, reconnect, app exit or interrupted input. No separate
release binding occurs in this stored record. Physical press/release testing and
an independent current-DPI read contract are still required before exposing it.
The GUI now labels exact known shapes; sensitivity authoring remains unavailable
apart from the existing position-scoped factory DPI-cycle preset.

## Firmware profile navigation versus host profile selection

Category `07` / length `01` maps to native group `3`, JSON `Profile`:

| Data | Native action | JSON action |
| --- | --- | --- |
| `01` | `1` | `Prev` |
| `02` | `2` | `Next` |
| `04` | `10` | `CycleUp` |
| `05` | `11` | `CycleDown` |

Encoder branch `581f3` emits category/length `07/01`; the shared branch table
selects the listed byte. None of these branches encodes a target slot number or
GUID. The decoder and named serializer agree. Exact traversal order, wrapping,
uninitialized-slot behavior and held/release behavior remain unknown.

Managed keymap assignment at `MappingBaseV2.SetMapping` RVA `8a714` constructs
an `sRSy3Mapping_Profile` with a GUID for the ID selection case, an `IsClutch`
flag, and `MAP_KEYMAP_UP` / `MAP_KEYMAP_DOWN` alternatives. It calls
`MappingV2_SetProfileSw`. This is separate evidence for host keymap/profile
functionality; it does not prove a firmware button record for selecting slot N,
a named desktop application profile or a profile clutch. Do not invent
`07 02 ...`, put a slot ID after `07/01`, or reuse Hypershift for this purpose.

The GUI labels the four known stored shapes but cannot assign them. An eventual
trial needs all-slot paired backups, independently observed active-slot changes,
safe return to the original slot before restoration, primary-click checks and
reconnect/release observations. Mapping readback alone cannot verify navigation.

## Media actions

Native group `10` maps to category `0a`, length `02`, and a **big-endian**
two-byte usage. The encoder explicitly supports only these seven actions:

| Label | Data | Native action | Serializer name |
| --- | --- | --- | --- |
| Volume up | `00 e9` | `3` | `VolUp` |
| Volume down | `00 ea` | `4` | `VolDown` |
| Mute audio | `00 e2` | `5` | `VolMute` |
| Play / pause | `00 cd` | `7` | `Play` |
| Stop playback | `00 b7` | `9` | `Stop` |
| Next track | `00 b5` | `a` | `Forward` |
| Previous track | `00 b6` | `b` | `Backward` |

The shared serializer also names action `6` `PausePlay` and action `8` `Pause`.
**They are absent from this controller's record encoder.** Do not derive extra
firmware actions from that shared UI/JSON enum. No arbitrary consumer usages,
separate Play/Pause records, launch/browser keys or guessed lengths are enabled.
Disassembly shows word stores such as `e900`, `cd00`, `b700`, `b500`, `b600`
at record `+2`; x86's little-endian stores produce the wire bytes above.
Decoder category `0a` examines the low usage byte; NagaLibre's labels/authoring
require the exact two-byte shapes, so an unknown high byte is not discarded.

## Additional mouse actions and repetition

The existing category `01` encoder/decoder agree on vertical scrolling
`09` / `0a` and horizontal scrolling `68` / `69`, all length `01`.
Their abstract actions are respectively `6`, `7`, `8`, `9`.
Managed mouse conversion `112a4` separately names `MAP_SCROLL_UP`,
`MAP_SCROLL_DOWN`, `MAP_SCROLL_LEFT` and `MAP_SCROLL_RIGHT`; the existing
[default-control trace](ONBOARD.md#default-binding-presets) corroborates direction.
These four are now editable on supported positions in either wired bank.

Other branches remain outside authoring: native mouse action `0d` becomes
category `0b`, length `01`, data `01`; category `01` bytes `06` / `07` decode to
abstract `0e` / `0f`. The shared managed enum includes `MAP_DBCLICK`, but its
availability does not independently verify all native mouse semantics or timing.
Those records remain preserved. No extra physical address is authorized.

Native repeated mouse actions use category `0e`, length `03`, with
`mouse_action, interval_hi, interval_lo`. Keyboard repetition uses category
`0d`, length `04`, with modifier, keyboard usage and a big-endian interval.
The encoder/decoder retain the repeat distinction; they are not ordinary
category `01` / `02` actions. Managed repeated scrolling supplies a delay of
100, and turbo uses `1000 / KeysPerSecond` (falling back to 20 when zero).
These are host encoding choices, not established firmware timing bounds.
No new repeat writer or rate UI is enabled. Existing held/toggle/counted native
macro playback remains the tested option documented in [MACROS.md](MACROS.md).

## Implementation and remaining verification

`devices/native-actions.json` is the shared editable subset: seven media and
four scroll actions. The Qt **Media / scrolling** selector works in the wired
V2 Pro/twelve-button paired transaction path, both layers, logical positions
1–16 only. Receiver/legacy and software conversions reject these drafts.
They use the existing backup-fsync, stale-state, changed-only write, immediate
readback and exact rollback/restore machinery. No new vendor commands were added.

Tests cover independently transcribed native records, malformed lengths/usages,
unchanged unknown trailing bytes, normal/secondary lost acknowledgements,
position/connection scope, local draft roundtrips and GUI routing. Successful
mock readback proves neither physical media/scroll output nor persistence.
Each new action still needs a controlled independent physical trial, held/release
checks where applicable, app-exit/reconnect observations and exact restoration.

Software text entry and launching programs were considered separately. Text
needs an explicit keyboard-layout/Unicode strategy; launching programs needs
unprivileged execution in the user's desktop session rather than the privileged
input helper. Neither is a native record in the evidence above. No new software
action mode is added here. Existing software sequences and native macro repeat
modes remain available; any future held-output mode must retain stop/failure
cleanup. These optional features should receive their own design before coding.
