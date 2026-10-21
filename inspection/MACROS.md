# Naga V2 Pro native onboard macro storage

## Evidence and implementation status

Selected deletion follow-up (2026-10-21): the GUI now exposes a separate scoped
delete transaction using the already traced `06/03` ID setter. It accepts only an
unassigned upload whose exact metadata/data and mouse identity match a validated
helper-owned upload journal. Incomplete reference coverage still prevents general
existing-entry deletion. A complete fresh checkpoint, paired/middle mappings,
durable GUI backup, helper intent journal, stale comparison and final unchanged
reference/content checks surround the single deletion. Lost ACKs are resolved by
readback without repeating the setter. No mapping writes, allocation, compaction
or format requests are introduced by this path. Automated failure/refusal tests
pass; this new selected-delete workflow has not been live-tested.

Static investigation on 2026-10-20 used the official Device167 package described
in [ONBOARD.md](ONBOARD.md). Windows code was extracted and inspected, never run.
Proprietary binaries, IL and disassembly remain in ignored `inspection/payload/`.
Addresses below are PE RVAs, relative to preferred base `10000000`.

| Input | SHA-256 |
| --- | --- |
| Wired `RzCtl_00A7.dll` | `dc7dcf529731e95ce6f712e7ce5166423b80ea26087648061cf343e7594578d7` |
| Receiver `RzCtl_00A8.dll` | `1a9543ae2a71aa3b2e8ae028e2de10dfa3df44cfac907885a621e087680c9cc3` |

The native transport framing, storage lifecycle, compact event representation
and binding conversion are now recovered at the host level. Wired capacity/count
and nonempty content getters have succeeded. Representative wired playback,
modifier release, USB reconnect and scoped recovery passed physical trials;
arbitrary contents, precise timing bounds and power-cycle persistence remain
unverified. Finding a host encoder does not establish that every
encoded event works autonomously on this mouse.

`onboard-macros` implements only direct getters, initially wired/normal mode with
the twelve-button plate. It reads capacity, IDs, sizes, 250-byte metadata and
sequence contents twice, retaining opaque bytes and each request/reply. It also
checks scoped paired mappings across every initialized slot before/after and
device identity, mode, plate, inventory and active slot. It never calls the
native storage-management algorithms below. Unknown sequence opcodes and empty
metadata are retained. This export is explicitly **not restorable**; it is not
accepted by the mapping restoration writer. Secondary primary clicks and other
plates' references remain outside its scope.

Further static work used the already archived Synapse core package identified
in [the wheel provenance](HAPTIC_WHEEL.md#verified-enum-ui-text-and-wire-association).
These shared dependencies are newer than Device167; they establish contract
units and UI enum labels, not device firmware behavior.

| Shared dependency | SHA-256 |
| --- | --- |
| `Contract.Macro.dll` | `7c99ee03197e26396448355c235ea00eacd797523c2a1cfa418b2ecd8082bdbd` |
| `Common.Macro.dll` | `ea8ce773103e858eeda53de956c4e1e4a43deba47f83e70d1eb9527a14d99bb3` |
| `Razer.Synapse3.Common.dll` | `82cc7632ea3a100346fc99a67528e44260ac026578066f9579a6343c9abb0a7d` |

## Wired empty-inventory capture

The user ran `scripts/inspect_macros.py` on wired `1532:00a7`, normal mode,
twelve-button plate, active slot 1 and initialized slots [1,2,3]. Both storage
passes succeeded. Non-identifying reply payloads:

| Getter | Payload | Decoded |
| --- | --- | --- |
| `06/8e` | `00 64 00 01 f0 00 00 01 eb 00 00 00 04 00` | maximum 100 macros; storage 126,976 bytes; available 125,696; reclaimable 1,024 |
| `06/80` | `00 00` | zero stored macro entries |

Independent comparison of private before/export/after files confirmed exact
paired mappings for all three initialized slots. No macro-category records
were found within those scoped normal/secondary controls. Identity, mode,
inventory, active slot and plate guards passed. The private export's checksum
matched the value supplied by the user. No settings writes were requested.

Count zero skips ID, size, metadata and sequence queries; this capture verifies
only the two getters listed above. Available plus reclaimable bytes are 256
less than reported storage; overhead or other storage usage is not established.
Do not interpret zero macros as an erased device or claim contents can already
be safely backed up/restored. Nonempty getter framing remains to be established.

## Direct protocol entry points

The protocol vtables are wired `7ab1c`, receiver `7fc04`, the same tables used by
the established mapping/wheel transports. Getter slot `+5c4` supplies command bit
`80`; setter slot `+5c8` does not. Native packed command `0609` therefore becomes
class/command `06/89` for reading and `06/09` for writing. All integer fields in
the table below are big endian; byte offsets are payload-relative. The common
90-byte body/report-ID-zero prefix and XOR checksum remain unchanged.

| Vtable slot | Operation | Wired RVA | Receiver RVA |
| --- | --- | --- | --- |
| `1a4` | Storage capacity | `2b1c0` | `2add0` |
| `1a8` | Macro count | `2bda0` | `2b9b0` |
| `1ac` | Macro IDs | `2af60` | `2ab70` |
| `1b0` | Allocate/size entry | `28260` | `27e70` |
| `1b4` | Remove entry | `2d1f0` | `2ce00` |
| `1b8` | Write metadata | `2f180` | `2ed90` |
| `1bc` | Read metadata | `2b0d0` | `2ace0` |
| `1c0` | Write sequence | `2f020` | `2ec30` |
| `1c4` | Read sequence | `2adf0` | `2aa00` |
| `1c8` | Read sequence size | `2aee0` | `2aaf0` |

These ten functions have identical instruction sequences through their returns
after normalizing image addresses, including register use, constants, stack
offsets, swaps and copy sizes. This supports a shared protocol description;
receiver commands remain disabled in the new inspector pending separate evidence.

| Class/command | Length | Payload |
| --- | --- | --- |
| `06/8e` | 14 | Reply: maximum macros u16 at 0, storage bytes u32 at 2, available bytes u32 at 6, reclaimable bytes u32 at 10 |
| `06/80` | 2 | Reply: stored macro count u16 |
| `06/8b` | `4 + 2*n` | Request: starting entry index u16 at 0, remaining bytes zero; reply IDs start at 4; native batches at most 32 IDs |
| `06/88` | 6 | ID u16 at 0; reply sequence byte length u32 at 2 |
| `06/08` | 6 | ID u16 at 0, sequence byte length u32 at 2; native allocation/size operation |
| `06/03` | 2 | ID u16; deletes an entry |
| `06/8c` | `6 + n` | ID u16 at 0, metadata byte offset u16 at 2; native getter leaves 4..6 zero, reads data at 6; batches at most 64 bytes |
| `06/0c` | `6 + n` | ID u16 at 0, offset u16 at 2, total metadata length u16 at 4, bytes at 6; batches at most 64 bytes |
| `06/89`, `06/09` | `7 + n` | ID u16 at 0, sequence byte offset u32 at 2, chunk byte count u8 at 6, bytes at 7; batches at most 72 bytes |

The native getter does not validate the extra returned header words at `8b`
offset 2 or `8c` offset 4. Their semantics are not established here. The new
inspector preserves them and compares exact repeated replies; it does not invent
request count fields from setter formats. Getter correlation checks the known
ID/index/offset prefixes and the sequence chunk count. A changed reply, rejection,
truncation or unexpected length stops inspection; none is treated as empty storage.
Resource limits (1,024 entries, 1 MiB per sequence, 4 MiB total) are application
bounds, not claims about firmware capacity. Strict native lengths may need a
capture-backed adjustment if the device returns a different valid framing.

## Razer's complete host storage lifecycle

`CStorage` vtable `7db24` connects macro operations to these transport calls.
Relevant wired routines are `53b00` (add metadata/cache entry and select ID),
`55ad0` (find GUID), `57620` (enumerate/cache metadata), `555d0` (read/convert
sequence), `58810` (convert and persist sequence), `58560` (remove), and `54010`
(storage defragmentation). This separates managed macro events from USB records.

1. The host enumerates stored IDs, reads 250 metadata bytes per ID and caches GUID
   associations. **This is not a read-only algorithm:** `57620` invokes removal
   at `57878` when metadata's GUID compares equal to the empty GUID. A Linux
   inspector must preserve those entries and use the direct getters instead.
2. Add logic looks up the GUID. If already present, Razer can remove its old entry
   before picking a replacement ID. This is unsafe to copy for user-owned/shared
   references; NagaLibre must use a fresh unused ID instead.
3. An ID candidate is a 15-bit hash of the sixteen GUID bytes. With starting seed
   `h`, byte `b` at index `i` updates `h = ((b + 1) * h + b + i) mod 65536`;
   the final candidate is `h & 7fff`. Seeds 0..4 are tried against the cache.
   The binding encoder uses the seed-0 candidate when a GUID is missing. Never
   bind an inferred hash without proving allocation and readback.
4. The sequence converter concatenates variable-length records described below.
   The storage availability check reserves `(floor(data_length / 256) + 2) * 256`
   bytes. This is host accounting, not a proven firmware allocation formula.
5. If contiguous available storage is insufficient but available plus
   reclaimable storage suffices, Razer invokes `54010`. It reads entries/data,
   **formats storage** through vtable `1cc` and recreates cached contents and
   profile metadata. This path is deliberately excluded from NagaLibre. A new
   implementation must fail safely when allocation cannot fit without compaction.
6. Persistence sends `06/08` for the chosen ID/sequence byte length, uploads
   250 metadata bytes via `06/0c`, then uploads sequence bytes via `06/09`.
   Metadata includes the GUID in bytes 0..16; a host event-count field follows,
   along with a 100-byte name region and more metadata. The mixed native bridge
   name encoder `29a40` calls `WideCharToMultiByte` with code page 65001 (UTF-8),
   a 100-byte destination and explicit input length. It appends NUL only if fewer
   than 100 bytes were produced. This is a byte limit, not a character limit.
   `CStorage` writes the expanded native event count directly as a little-endian
   u32 at metadata offset 16 (`58a7c`–`58a7f`). The UTF-8 name begins at offset 20.
   The post-name region and initialization policy are described below. Preserve
   all 250 bytes of an existing entry; a new-entry builder must not normalize
   saved metadata or copy unrelated host padding.
7. A mapping record references the allocated ID using the playback categories
   below. Binding must follow verified content upload. All existing scoped mapping
   restrictions remain; primary clicks never reach the writer.
8. Removal uses `06/03`. Normal cleanup must not remove an existing macro, an
   entry with an unknown reference or an ID merely calculated from a GUID.

No additional macro-content checksum is constructed by these direct upload
functions. This establishes the host transfer behavior, not absence of internal
firmware integrity fields or a separate commit/persistence requirement.

## Metadata layout recovered with Ghidra

Ghidra 12.1.4/MCP analysis of the wired controller confirmed the native upload
assembly at `58a42`–`58a90`. The 250-byte buffer is at VA `10092928`; it starts
zero in the image. The upload routine copies four regions into its first 136
bytes. The final 114 bytes are not populated by this routine. This is static
host evidence; device interpretation of reserved bytes remains unverified.

| Metadata offset | Length | Host representation |
| --- | --- | --- |
| 0 | 16 | Macro GUID in Windows GUID memory order: first u32/u16/u16 little endian, last eight bytes unchanged |
| 16 | 4 | Expanded native event count, little endian; includes inserted delay records |
| 20 | 100 | UTF-8 name, NUL terminated only when fewer than 100 bytes are produced |
| 120 | 4 | Initial movement X coordinate, little endian i32 |
| 124 | 4 | Initial movement Y coordinate, little endian i32 |
| 128 | 1 | Managed event reconstruction hint, set if a keyboard event was supplied as combined press/release |
| 129 | 7 | No established semantic fields; copied as part of the native 16-byte post-name region |
| 136 | 114 | Unpopulated tail of the image-zero buffer in this upload routine |

The sixteen post-name bytes are **not another GUID**. The mixed OBM bridge's
`AddMacro` path (`27570`) puts the first movement coordinates into its cached
descriptor at offsets `94`/`98` (`27aa7`, `27abd`); the storage routine transfers
that descriptor region to metadata offsets 120/124. Before event conversion,
`27962` stores the bridge boolean at descriptor offset `9c`, which becomes
metadata byte 128. Managed `ConvertToKeyEvent` at IL RVA `4254c` accumulates
`previous_hint || State == 2` into that boolean. `ConvertFromMacroEvents` passes
it to key/mouse conversion during reconstruction. It is not established as a
firmware playback switch, movement flag or extra macro identifier.

The bridge constructor `25940` initializes only its common header. The name
conversion appends one NUL rather than clearing its unused buffer. Movement
origins are assigned when a movement event is encountered. Therefore the native
code does not establish a canonical value for every padding byte of a non-movement
macro. NagaLibre's **offline new-entry policy** initializes all 250 bytes to zero,
then writes only GUID/count/name. Its compiler emits explicit key/mouse edges,
no movement, and leaves the reconstruction hint zero. This is deterministic
construction for a proposed new entry, not byte equivalence with every Razer
stack buffer and not hardware verification. Existing metadata stays opaque/exact.

GUID text is accepted as `00112233-4455-6677-8899-aabbccddeeff`; the corresponding
first sixteen bytes are `33 22 11 00 55 44 77 66 88 99 aa bb cc dd ee ff`. The
empty GUID is rejected. Seed collisions can repeat: the native hash does not
guarantee five different IDs. Exhaustion must fail rather than overwrite an entry.

## Compact event stream

Wired `57bd0` converts 40-byte host event records into concatenated USB sequence
bytes; `54820` performs the reverse conversion. The first byte is an opcode.
There is no per-event fixed-size padding. Do not upload the managed structures.

| Opcode | Following bytes | Host conversion |
| --- | --- | --- |
| `01` | Keyboard HID usage u8 | Key make/down, converted from Windows scan code/extended flags |
| `02` | Keyboard HID usage u8 | Key break/up |
| `08` | Mouse button-state bitmask u8 | Cumulative state of five buttons; explicit releases clear bits |
| `0a` | Vertical wheel direction u8 | Host encoder emits `01` for +120 and `ff` otherwise |
| `11` | Unsigned delay u8 | Host delay below 256 |
| `12` | Unsigned delay u16 | Host delay below 65,536 |
| `13` | Unsigned delay u24 | Host delay below 16,777,216 |
| `14` | Unsigned delay u32 | Larger host delay |
| `15` | Signed X i16, signed Y i16 | Movement; an optional following `14` delay record can be emitted with it |

Delay widths and movement values are big endian. The decoder's movement branch
can consume the following `14` record as part of one ten-byte host movement
conversion. Other events remain sequential records. Mouse state must start at
zero and retain all held-button bits until released. A key press is not a
complete tap; a balanced release must be emitted separately. Unknown opcodes
must remain opaque, not be dropped or rewritten.

Managed `CRSy3_OnboardMem3M.ConvertToMacroEvents` at IL RVA `43b48` separately
expands combined press/release events and stores a delay at host offset 32;
`-1` becomes zero. That host field is not itself the compact delay encoding.
The mixed native bridge in the same DLL is now traced too: `OBM3_AddMacro`
(`24b20`) calls `27570`; the conversion loop at `279f1` inserts a type-3 delay
record before each non-movement event with a nonzero 64-bit host delay. It copies
the low 32 bits directly at `27a20`, without scaling. Movement puts that value
in its inline timing field at `27af9`. `OBM3_GetMacroSize` (`24b00` -> `26e70`)
uses the corresponding conversion at `271f0`. Thus a compiler must reject
out-of-range delays rather than reproduce silent high-bit truncation.
`Common.Macro.MacroManager.ExecuteMacroEvent` (IL RVA `3c48`) passes the same
`Contract.MacroLib.MacroEvent.Delay` value directly to
`System.Threading.Thread.Sleep(Int32)`. The shared host contract therefore uses
milliseconds. No scaling is inserted by the Device167 native bridge. This
supports compiling millisecond timelines; zero-delay scheduling accuracy and
physical device timing bounds still need measurement.
The host converter's support for movement is not proof of onboard mouse-motion
playback. Text entry, launch/program actions and other software operations are
not represented by this compact encoder.

## Binding and richer playback

`57e50`, macro branch `58077`, resolves a GUID to a stored u16 ID, then selects
the seven-byte category/length/data record used by `02/0c`:

| Storage playback selector | Category | Length | Data | JSON action |
| --- | --- | --- | --- | --- |
| 1 | `03` | 3 | ID u16, repeat count u8 (host checks count <=255) | `RunMultiple` (count 1 for once) |
| 2 | `04` | 2 | ID u16 | `RepeatWhileDown` |
| 3 | `05` | 2 | ID u16 | `RepeatUntilPressedAgain` |
| 4 | Unsupported here | — | Encoder returns an empty record | — |
| 5 | `0f` | 2 | ID u16 | `Sequence` |

The JSON labels are now traced independently through the native action-selection
jump table `60000` (`5f491`), whose entries lead to `5f4a5`, `5f4ca`, `5f4ef`,
the unsupported branch and `5f514`. Device167's managed
`OBMMappingConverter.ConvertMacro` (IL RVA `111a4`) separately maps UI once/multiple,
toggle, held and sequence to those named JSON actions. The shared UI enum
`PlayBackOptionType` has values once=0, multiple=1, toggle=2, held=3, sequence=4.
Do not confuse this UI enum, the generic mapping bridge enum and the storage
selectors above. Count-zero behavior, actual release/cancel semantics, sequence
segmentation, turbo and repeat-rate controls remain incompletely established.
Once, counted, held, toggle and sequence are now exposed through the scoped
transaction; representative trials are recorded in HANDOFF.md.

## Offline compiler and content checkpoints

`onboard-macro-compile CONFIG` converts existing software TOML `steps` to native
key/mouse/delay bytes without opening hardware. It supports standard keyboard
keys, independent modifier down/up events, five mouse outputs, overlapping
presses, chords and trailing waits. Delays use the smallest native big-endian
width. Held remaps, unsupported keys, duplicate output presses, unmatched
releases, unbalanced sequences and invalid timelines fail before output. Linux
mouse aliases are canonicalized to output bits. Current compilation bounds
are 16,384 encoded events and five minutes; they are application limits, not
firmware capacities. Movement and wheel events have structural decoding only.
Compiled output explicitly states `hardware_verified: false` and cannot be
submitted to any mapping writer.

The structural decoder preserves original event bytes, including nonminimal
delay widths, and stops interpretation at an unknown opcode while retaining the
complete opaque tail. It does not rewrite existing macros through the compiler.

`onboard-macro-checkpoint INSPECTION [--fresh INSPECTION]` validates a diagnostic
offline and emits a separate `onboard_macro_storage_checkpoint`. Every parsed
capacity/ID/metadata/data field must agree with a replay of the complete ordered
getter records; missing, extra, malformed or mismatched evidence fails. Mapping
banks, guard identity and slot coverage are validated too. With `--fresh`, exact
storage/reference state must match, allowing only hidraw path changes on reconnect.
This checks file consistency/staleness, not cryptographic authenticity or getter
fidelity on untested firmware paths.

`inspect_macros.py` now durably saves this checkpoint after the raw export, using
unprivileged offline validation. A validation failure retains the raw evidence
and still checks final paired mappings. The checkpoint has
`complete_profile: false` and `restoration_implemented: false`; it preserves
inventoried contents but does not authorize writes/deletion or claim complete
reference coverage. The user's earlier zero-entry export passed this validator.

`onboard-macro-plan INSPECTION CONFIG REQUEST` builds an offline allocation/upload
proposal from a validated diagnostic, a software TOML timeline and a JSON request
(see `examples/onboard-macro-plan.json`). It uses native GUID/hash/metadata formats,
64-byte metadata chunks and 72-byte sequence chunks. Allocation, metadata and
data packets are ordered; the proposed playback binding is separate and must
only be applied after exact content readback. Once, counted 1..255, while-held,
toggle and sequence bindings are represented without claiming physical behavior.

The planner rejects a GUID already in storage, full entry capacity, all five hash
collisions, insufficient available bytes under Razer's accounting, malformed
macro references and unknown mapping categories. Stored IDs and every recognized
scoped reference (including shared/dangling IDs and normal primary-click reads)
remain occupied. Reclaimable bytes never justify compaction. The original checked
contents, references and exact target record remain embedded in the private plan.
Neither primary clicks nor other wire addresses can be selected as a target.

Plans explicitly report `hardware_verified: false`, `execution_enabled: false`
and `complete_reference_coverage: false`. There is no command to execute them.
They are not a durable transaction journal or a restorable full-profile backup.
Middle and secondary primary/other-plate reference coverage remain incomplete.
Historical diagnostics are not fresh-state checks. Allocation ownership,
failed-ack recovery and interruption journaling remain prerequisites for any
hardware upload/bind/cleanup route.

## Journaled upload and recovery implementation

The experimental wired writer is implemented in `macro_transaction.rs`, with
CLI prepare/apply/recover routes and the **Onboard macros…** dialog. Hardware
verification is pending; the user explicitly deferred hardware testing. No new
hardware reads or writes were performed during this implementation.

Preparation captures and validates every existing entry and scoped paired
mapping, including normal middle-click guards. The GUI atomically saves and
fsyncs its private backup before acknowledging the commit token. Apply creates
an exclusive helper-owned 0600 ownership journal in a private user directory,
fsyncs its header and directory, and rechecks the entire checkpoint. The helper
journals intent before each generated fresh-ID allocation/upload/binding request.
Uploaded metadata/data must read back exactly before binding; existing contents
and unrelated mappings must remain exact. Ordinary NagaLibre helpers serialize
control-interface access with an advisory lock. This does not lock out other
mouse controllers; close those before use.

Recovery accepts only the helper-owned journal, never an offline plan. It checks
identity, original entries, allocation size and (after acknowledged metadata)
GUID ownership. It restores only original target records, resolving lost restore
acknowledgements by exact readback; it never rolls restoration back to an uploaded
binding. Known target-bank aliasing can be repaired while unrelated changes block
cleanup. References are restored and verified before removal. Only the fresh ID
owned by this transaction can be deleted, after another content/reference check.
Lost deletion acknowledgements are resolved through inventory readback. Reopening
an interrupted journal resumes recovery without replaying uploads. A journal I/O
failure still attempts reference restoration but retains the allocation until a
usable journal is reopened. Existing entries are never overwritten or removed;
formatting, compaction and reconstruction of existing storage remain disabled.

This is scoped transaction undo, not arbitrary macro import or a full-profile
restore. Secondary primary clicks and other plates remain outside reference
coverage (`complete_reference_coverage: false`). Free/reclaimable counters may
change after allocation/deletion even when original contents are restored.
The diagnostic checkpoint retains `restoration_implemented: false`: it alone
cannot authorize cleanup. Offline proposals still have `execution_enabled: false`.

Mock transport regressions cover interrupted allocation/upload, lost acknowledgements,
corrupt contents, new shared references, GUID changes, stale state, journal failures,
reconnect paths, wrong-bank aliasing, exact restoration and idempotent cleanup.
`scripts/macro_controlled_test.py` prepares durable private evidence, uploads one
small sequence and recovers its own allocation. `--readback-only` excludes physical
claims; interactive playback/release/reconnect observations are recorded separately.
Nonempty getter fidelity, firmware acceptance, physical outputs, release behavior,
all playback modes and power-cycle persistence still require hardware evidence.

## Wired shortcut activation discrepancy (2026-10-21)

Small key timelines passed once/count3/held/toggle tests with the upload helper
exited. A B/wait/C/wait sequence progressed B, C, silent, B over four presses.
All these trials passed primary clicks, user-observed USB-reconnect persistence
and independent scoped recovery comparisons. The following shortcut fixture did
not play immediately after upload, but did emit `Bc` after USB reconnect:
Shift down, B down, wait80ms, B up, Shift up, wait120ms, C down, wait80ms,
C up, wait120ms. Ten expanded events and exact sequence/metadata readback matched
the plan. Original zero entries and paired mappings/echoes were restored exactly.
Manual lowercase-d verification was not explicitly recorded. The activation
observation is retained as test history; do not infer successful live playback
from getters alone.

Rechecking wired RVA58810,247c0,2f020 found no added finalize command on the
examined successful upload path. Reconnect fixing playback suggests a live-state
or lifecycle distinction, but does not establish its cause or authorize guessed
flush/mode/reset requests. Repeated pre-reconnect playback and a delayed retry
are the next controlled observations; broader lifecycle/firmware analysis may
still be required. Proprietary decompilation remains private.

The identical shortcut fixture subsequently passed immediate `Bc` output and
manual lowercase `d`, confirming modifier release on that run, with primary
clicks, reconnect and exact cleanup. The initial activation failure remains
unexplained. The user then completed the desktop save/full-app-exit/B-playback/
primary-click/reopen/undo flow successfully. Private GUI backup presence and
scope were checked by the agent; the helper-owned journal remains protected,
and no independent post-GUI hardware read was performed by the agent.

### #4 closeout

The user accepted completion of #4 on 2026-10-21 and removed the initial activation
observation as an open blocker after the successful shortcut retest and desktop
save/app-exit/playback/restore trial. Its historical evidence above is preserved;
no cause or corrective protocol change is claimed. The completed scope is the
implemented wired V2 Pro/twelve-button path with representative physical evidence.
Selected-owned deletion, broader target/layer/timeline combinations and explicit
power-cycle coverage keep their separately stated verification limits.
