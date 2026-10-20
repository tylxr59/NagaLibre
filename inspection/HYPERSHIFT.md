# Naga V2 Pro Hypershift investigation

## Evidence and limits

Static analysis uses the official Device167 package identified in
[ONBOARD.md](ONBOARD.md). Payloads were extracted and inspected, never executed.
This document describes independently reconstructed protocol facts; proprietary
payloads and disassembly remain in the ignored local extraction directory.
Addresses below are RVAs (preferred image base `0x10000000`), not file offsets.

| Controller | SHA-256 |
| --- | --- |
| Wired `RzCtl_00A7.dll` | `dc7dcf529731e95ce6f712e7ce5166423b80ea26087648061cf343e7594578d7` |
| Receiver `RzCtl_00A8.dll` | `1a9543ae2a71aa3b2e8ae028e2de10dfa3df44cfac907885a621e087680c9cc3` |

Razer's [Hypershift guide](https://dl.razerzone.com/videos/transcripts/How%20to%20activate%20and%20use%20Razer%20Hypershift%20on%20a%20Razer%20mouse-1789.pdf)
describes assigning a second function to a button, choosing another button as
the modifier in Standard mode, and holding that modifier while using the
secondary assignment. That establishes the intended interaction, not autonomous
onboard execution or Linux support. The [model manual](https://dl.razerzone.com/master-guides/RazerSynapse3/NAGAV2PRO-00000167-en.pdf)
is additional product context, not a wire-format specification.

The first live inspection attempt failed on an unmatched `02/8c` reply before
exporting a snapshot. That original error lacked bank/control context; a successful
secondary-bank read has not been established. Hypershift writes and physical
held/release tests have not been performed. Getter errors now identify bank,
pass, slot and button for the next read-only attempt.
A second attempt completed normal-bank reading, then timed out specifically on
slot 1, wire ID `01` (primary left click), layer `01`. This does not establish
whether secondary grid/auxiliary records are readable. Since primary clicks
cannot reach any NagaLibre mapping writer, secondary diagnostics now exclude
them. Primary state remains checked in the normal bank. No alternate layer value,
normal-bank fallback or weakened response matching was introduced.
Firmware restrictions such as nested modifiers, modifier self-assignments,
secondary disabled-action behavior, supported outputs and persistence still
require independent tests. Static encoding is not permission to broaden the
primary-click or mapping-address writer limits.

## Native host bank selector

The existing ten-byte mapping payload is:

```text
slot, wire_button_id, layer, category, declared_length, five_data_bytes
```

The native encoder keeps the wire button ID unchanged between banks. Its layer
is a separate byte: normal `00`, Hypershift `01`. It does not OR `80` into the
wire button ID. The
native host representation uses a high bit that is converted into this separate
byte; the host flag itself is not sent as the layer selector.

Wired input converter `0x67790` clears its layer-output byte first. Its DKM,
thumb-grid and mouse-input branches inspect bit `80` of source-input byte `+4`,
at `0x67823`, `0x67878` and `0x678c2`. If present, the output layer byte becomes
`01`; the same converter still returns the usual wire ID. Receiver converter
`0x6c430` has corresponding checks at `0x6c4c3`, `0x6c518`, `0x6c562`.

The wired storage caller at `0x56402` passes an output pointer for that layer
byte to the input converter. At `0x56448` it forwards the resulting layer,
converted button ID and slot to protocol vtable slot `+274`.

| Native operation | Wired RVA | Receiver RVA | Vtable slot |
| --- | --- | --- | --- |
| Mapping getter | `28ca0` | `288b0` | `+274` |
| Mapping setter | `2d930` | `2d540` | `+270` |

Both getters construct command header `020c`, length `0a`, and copy three
independent arguments into payload offsets 0, 1, 2. The getter transport supplies
the read bit, yielding `02/8c`. The returned record is seven bytes beginning at
payload offset 3. The setter uses the same argument order and seven-byte record
with `02/0c`. Existing transport framing, checksum and the three echoed getter
arguments continue to apply to ordinary mapping reads. The later capture below
establishes a V2 Pro-specific zero-echo exception in the layer reader.

The packaged default mapping tables for device IDs 167 and 168 contain 30 normal
and 30 `IsHyperShift=true` entries each. They corroborate the two banks and shared
input definitions, not the live firmware contents. They include inputs beyond
NagaLibre's permitted mapping set; those entries do not expand this project's
writers or establish the six-/two-button bank addresses.

## Hypershift modifier action

The trigger is distinct from the source bank selector:

```text
category = 0c
declared_length = 01
data = 01
canonical seven-byte record = 0c 01 01 00 00 00 00
```

Wired mapping decoder `0x54bf0` dispatches category `0c` through the table at
`0x55230` to `0x55172`. It sets the abstract mapping group to `80000000` and the
associated action value to 1. The JSON conversion at `0x5f0e0` recognizes that
group and selects the `Hypershift` string, providing an independent name link.
The reverse encoder at `0x57e50`, block `0x57e96`, recognizes `80000000` and
emits category/length `0c/01` plus data `01`. Receiver equivalents include decoder
block `0x56fe2` and encoder block `0x59d06`.

Thus this action should eventually be assigned in the normal bank on an allowed
button, while the alternate action belongs to layer 1. This is the intended
interaction inferred from the native encoding and official guide; hold/release
behavior without Synapse remains a physical-test requirement. Existing action
validation still rejects new trigger assignments. No writer was enabled here.

## Read-only implementation

`onboard-layers [--slot 1..5]` reads the existing normal snapshot (including its
left/right primary records) plus twelve secondary grid and four auxiliary records. It
requires the twelve-button plate. It reads each bank twice and rechecks the
plate, rejecting observed record/state changes. This is not an atomic firmware
snapshot or a lock against another controller; fully quit the GUI before using
it. No mode, activation, mapping, slot-allocation or deletion writes are sent.

Its separate diagnostic envelope is:

```text
format: 1
normal: existing normal-only Snapshot (including slot and device identity)
hypershift: { layer: 1, primary_inspected: false, echoes: [{button, layer}, ...], buttons: [...], controls: [...] }
```

Unknown categories, short keyboard length fields and trailing bytes use the
existing `raw_record` representation. This envelope deliberately cannot deserialize
as an ordinary mapping-restoration Snapshot. It is not accepted by Restore backup
and does not claim that the engine can restore the secondary bank. Existing
normal reads, snapshots, session protocol and saves retain their old behavior;
all current mapping writes continue to send layer 0.
Secondary primary records remain unknown; neither their absence nor the failed
query proves their contents, firmware restrictions or fallback behavior.

### First grid retry

After excluding secondary primary queries, the next user-run diagnostic completed
the normal bank and timed out on slot 1, grid button 1 (`40`), layer `01` too.
There is still no validated secondary export. The native structures describe
the intended request encoding, but this failed getter does not establish whether
the mouse supports onboard secondary reads in this mode or connection.

Timeout errors now show last-response transport metadata. When a reply has a
valid checksum, successful status and the requested mapping command/transaction,
they also show its slot/button/layer echo. This exposes a possible wrong-bank
echo without accepting it. Raw action and serial payloads are never included in
the timeout message. Compare the same scoped getter over wired and receiver
before drawing conclusions; do not try guessed layer bytes or change device mode
to make this diagnostic succeed.

### Matched replies with a zero layer echo on both connections

The user subsequently ran the diagnostic over both wired `00a7` and receiver
`00a8`. Both requests for slot 1, wire `40`, layer 1 received a successful
status-2 reply with transaction `1f`, command `02/8c`, payload length 10 and valid
checksum. Both replies echoed slot 1, wire `40`, **layer 0**. The strict reader
correctly rejected them; no verified secondary snapshot was exported and no
settings writes were requested. This does not distinguish an ignored selector
from incorrect echo metadata on otherwise distinct data.

Rechecking the wired getter transport at `29ac0` found header/status checks near
`29d2c`–`29d86`, checksum processing at `29da7`–`29e92`, and payload copying at
`29e57`–`29e64`. That path does not compare the returned mapping-argument echo
with the request before copying the payload. The mapping wrapper at `28cf8`
then copies the seven record bytes. This explains why the official code can
consume such replies; it does not prove which bank those bytes represent.

### Unverified reply capture

`onboard-layer-probe [--slot N]`, wrapped by
`python3 scripts/inspect_layers.py --probe [--slot N]`, uses only the same
sixteen scoped mapping getters. The transport still requires a successful
status, valid checksum, matching report/transaction/class/command, and slot/button
echoes. It records the requested layer and returned layer separately, preserving
all seven record bytes and comparing them with the exact normal record.

The result is explicitly tagged `kind: unverified_layer_replies` and
`secondary_verified: false`, even if every echo matches or some records differ.
It contains `normal` and `replies`, never a `hypershift` bank. It cannot deserialize
as either a regular Snapshot or a strict LayerReadback. Neither preparation nor
restoration accepts it. Ordinary mapping reads still check all three address
bytes. The layer-specific exception described below retains the observed echo
metadata rather than rewriting it as 1.

Replies are captured twice and must be identical; normal state and plate are
rechecked before exporting. Same bytes as normal would be consistent with the
selector being ignored, but would not prove that conclusion. Different bytes
would justify further investigation, not automatic acceptance or writes. No
guessed requests, mode changes or Hypershift writes are introduced.

### Successful wired capture and bounded zero-echo handling

The first wired forensic capture completed both passes of all sixteen scoped
requests, with unchanged normal state and plate. Its private checksum was checked.
All responses echoed layer 0. Twelve records were wire-identical to normal;
four differed:

| Control | Normal record | Requested-layer-1 reply | Interpretation |
| --- | --- | --- | --- |
| Grid 1 | `02 02 00 1e 00 00 00` | `02 01 00 1e 00 00 00` | Same key 1, different declared length |
| Grid 2 | `02 02 00 1f 00 00 00` | `02 01 00 1f 00 00 00` | Same key 2, different declared length |
| Tilt left | `02 02 00 68 00 00 00` | `0e 01 68 00 14 00 00` | F13 versus native repeated horizontal-left action |
| Tilt right | `02 02 00 69 00 00 00` | `0e 01 69 00 14 00 00` | F14 versus native repeated horizontal-right action |

The category-0e decoder at `54cea` dispatches 68/69 to `54d5a`/`54d63`, setting
mouse actions 8/9 with the repetition flag. It also consumes bytes beyond the
declared length: `54d71` combines bytes 3/4 as parameter `0014`. These bytes must
remain in `raw_record`; the current UI should not invent a repeat-rate setting
or present this as a plain category-1 scroll assignment.

Changing only the request selector yields stable, functionally different tilt
records while the normal table stays unchanged. Together with the native request
encoding and getter's lack of layer-echo validation, this supports a bounded
V2 Pro zero-echo reader. It still does not prove physical Hypershift behavior.

The layer-specific reader now permits echoed layers 0 or 1 only on product
00a7/00a8, retains every observed echo in the export, and requires all other
transport/address/length/state/plate checks. Unexpected layer values fail.
Normal mapping readers and existing normal-only writers retain their previous checks.
Both passes compare echo metadata as well as exact records. The forensic envelope
stays explicitly unverified regardless of the improved reader. The parsed wired export subsequently passed with all sixteen zero echoes
retained, including the raw repeated-tilt records. Physical behavior is pending.

`python3 scripts/inspect_layers.py [--slot N]` runs that getter through local
sudo and durably saves a private export, keeping the GUI unprivileged. It prints
secondary action summaries and a checksum, without printing the device serial.
The bounded transaction path below includes both banks in stale checks, durable
backups, semantic verification of changed records, exact preservation of untouched
records and exact rollback, including writes whose acknowledgements are lost.
Legacy normal-only backups retain their existing scope and do not restore the
secondary bank.

## Bounded transaction implementation

`src/onboard/layer_transaction.rs` implements the initial wired active-slot trial
without mode/activation/inventory writes. Paired backups contain both scoped banks
and normal middle click for every initialized slot; secondary primary records
remain outside scope. Sparse changed actions are semantically verified; untouched
and restored records retain exact bytes. The normal trigger is installed after
secondary assignments. Nested secondary triggers and arbitrary raw user edits
are rejected; raw unknown records can only be restored from validated backups.

All-slot stale checks run before writes. Lost acknowledgement recovery includes
attempted records and observed collateral changes, restores secondary then normal,
and verifies the complete paired backup. Main clicks are checked but never
rewritten. Simulated setter aliasing and failed recovery have regression coverage;
these tests do not establish the firmware's physical behavior.

The session's separate layer preparation event returns the paired backup before
issuing a one-shot commit token. `scripts/hypershift_test.py` persists recovery
and apply-attempt state before acknowledging it. No live trigger/secondary write
has yet been performed. Existing diagnostic/forensic exports and legacy snapshots
are not accepted as paired restoration backups.

## First write attempt: reverse selector echo, recovery pending

The first controlled wired apply failed after a secondary write attempt. A
normal-bank grid-1 request (slot 1, wire 40, selector 0) received a valid status-2,
transaction-1f, command 02/8c, length-10, checksum-valid reply echoing selector 1.
The same mismatch blocked exact rollback verification. Neither restored state
nor physical Hypershift operation is established. It is not safe to treat this
reply as a normal bank merely by relaxing that check.

The original paired backup and per-attempt recovery checkpoint match exactly
and cover slots 1/2/3. The existing restore runner remains bound to its original
release-helper checksum. Reconnect/strict restore was requested first. Separate
`onboard-selector-inspect` diagnostic sweeps retain the raw request/response
selectors for both requested banks, without relying on the normal snapshot path
or asserting a verified bank. They double-read and check metadata/plate stability,
including normal primary records; they issue no writes. The normal reader remains
strict. This diagnostic is built as the debug helper so the saved release-helper
checksum and trial remain intact.

## Selector capture after reconnect/restore failure

The active-slot diagnostic completed in 2.5 seconds. All 35 observed raw action
records matched the corresponding saved selector records: three normal primary
clicks, sixteen selector-0 controls and sixteen selector-1 controls. Grid 1 echoed
1 for both selectors; all other controls echoed 0. This distinguishes the echo
metadata difference from an action-data difference. It does not establish why
the firmware stores/returns this selector or prove physical behavior.

`echo_recovery.rs` therefore implements a one-record repair from the **paired
original backup**, using the diagnostic only as a fresh-state guard. Both captured
selectors must still contain their original action bytes; only grid-1 echoes 1
are permitted. Other initialized slots must match their complete paired backups.
A durable create-new journal and a second guard precede one normal-bank write of
the original slot-1/grid-1 record. Primary clicks and selector-1 records are never
written by this repair. Strict full-bank readback, including original echoes,
checks every backed-up slot afterward, even if the write acknowledgement failed.
No automatic retries or unverified success claims are allowed. This recovery
method passed live recovery: persisted runner statuses report complete exact
restoration. The user then confirmed original grid-1 output, DPI cycling and
left/right/middle clicks, including repeated checks after USB reconnect. The
root-owned engine journal was not independently read without sudo. This verifies
the recovery result; Hypershift hold/release behavior remains unverified.

## Follow-up native setter and transport trace

After the successful recovery, the wired storage write caller was traced through
`591f6`–`5927f`. It initializes a layer-output byte at `ebp-144`, calls converter
`67790`, encodes the action through `57e50`, and passes slot, converted wire ID,
converted layer and seven-byte action to protocol vtable `+270`. This confirms
the setter uses the same source-layer conversion as the previously traced read
caller. Keyboard encoder `57f8c` writes category/length `02/02`, then modifier
and HID usage at record offsets 2/3 (`57faa`, `57fd3`). The trial's canonical
keyboard encoding is consistent with this native encoder; captured length-one
records still require exact preservation during restoration.

The base protocol table at `7ab1c` points `+5c8` to transport setter `2e1c0`.
The device's subclass table at `7d550` retains that setter. It overrides getter
`+5c4` with `55480`, which adjusts the delay and calls base getter `29ac0` without
changing the mapping payload. No extra Hypershift-enable request was found in
these traced mapping-call blocks. This does not rule out broader initialization
requirements elsewhere in Synapse.

Setter wrapper `2d9b4`–`2d9bb` supplies transport arguments `(packet,1,0)`.
Transport `2e2c3` constructs transaction `object[14] | 1f`; getter `29b98` does the
same. Initialization `57560`–`5758d` chooses object byte 14 as 80 when descriptor
field `+8` equals 2, otherwise 0. The meaning/value of that runtime descriptor
field has not been independently established here. Therefore this trace does
not justify guessing another transaction ID on hardware. The follow-up probe
retains the existing tested transaction 1f and mapping commands only.

The remaining hypothesis is that returned selector metadata can follow the last
write for that physical address while request selection still chooses distinct
actions. The earlier evidence was collected **after rollback**, so matching
original action bytes cannot prove what the first B write did. It is insufficient
to justify weakening the normal reader or declaring shared metadata proven.

`layer_write_probe.rs` and `scripts/probe_layer_write.py` isolate that question:
fresh durable all-slot paired backups; one secondary grid-1 B write; two sweeps
of both requested selectors retaining echoes; verification that only selector-1
returns B and selector-0 actions remain original; unconditional original secondary
then original normal writes; full exact backup verification before exit. No
trigger is installed. Lost acknowledgements, bank aliasing, shared-echo metadata,
failed recovery and restoration-only continuation are simulated in tests.
The probe records private observations and checks all other backed-up slots.
It does not establish physical Hypershift behavior. Its live result is pending.

## Successful isolated write observation

The subsequent wired probe returned normal grid-1 key 1 as
`02 02 00 1e 00 00 00` and requested-secondary B as `02 02 00 05 00 00 00`.
Both replies reported selector 1. Other tracked state/slots stayed unchanged;
original secondary then normal writes restored the complete exact paired backup,
including returned tags, before helper exit. Saved result/status and backup/plan
hashes were independently checked. No Hypershift trigger was assigned.

This directly establishes distinct requested action records while the returned
selector metadata is shared for this tested address/write. A normal request
returning selector 1 does not alone show that the normal action changed. It is
not a universal statement about all controls, devices or transaction flags.

Paired snapshots now retain `normal_echoes` as well as secondary `echoes`. Only
wired scoped controls use the bounded 0/1 normal-return policy; normal-only and
primary readers remain strict, as do receiver normal reads. Repeat reads and
stale checks compare actual tags. Legacy missing normal echoes mean zero because
the early normal reader required that value. Transaction verification predicts
the last selector only for changed controls, rejecting unrelated metadata changes.
Exact restore/rollback may replay an unchanged original bank record to restore
its saved returned tag. A previously saved shared tag 1 is preserved as well;
inconsistent saved tags cannot be synthesized by a tag-restoration write.
Physical Hypershift hold/release behavior is the remaining hardware check.

## Successful wired physical held trial

On wired 00a7 with the twelve-button plate, the staged DPI-trigger/secondary
B trial completed prepare, apply, verify and restore. The user confirmed expected
physical Hypershift behavior: grid 1's normal key, B while holding DPI, and return
to normal on release. All other scoped records and initialized slots verified
unchanged. Exact original paired restoration was reported, and private restored
status plus backup/plan hashes were independently checked.

The user subsequently explicitly confirmed primary clicks, physical Hypershift
persistence after USB reconnect, and original physical outputs after restoration
all passed. These user observations are separate from the stored-state checks.
Receiver operation and other trigger/action combinations remain unverified.
GUI layer editing/profile migration were subsequently implemented; see below.

## Desktop integration

Normal and secondary drafts, a normal-layer trigger, keep/disabled actions,
explicit stored-to-draft copy and local profile migration are implemented. Wired
saves/restores use paired backups and the strict stale/readback/recovery path.
Legacy normal backups restore only normal actions while preserving fresh
secondary records. Receiver Hypershift writes remain disabled.

Slot activation in a paired session backs up and checks every initialized bank
and metadata without mapping writes. Creation also backs up/checks secondary
banks, but still refuses nonzero normal tags before allocation rather than
relaxing the legacy allocator's checks. New-slot secondary defaults remain
unverified. Fault tests cover these paths; no additional hardware slot behavior
is claimed.

The wired twelve-button desktop walkthrough subsequently passed independent
prepare/staged/saved/restored checks. Draft-only staging left both banks and all
slots unchanged; the saved normal DPI trigger and secondary grid-1 B matched,
with all other scoped records/slots exact. GUI backup restoration recovered all
original paired records, echoes, primary checks, slots and device state exactly.
The user confirmed physical hold/release, clicks, USB reconnect persistence and
original outputs/DPI cycling after restoration. These desktop observations are
separate from the earlier firmware trial and do not establish receiver behavior
or other trigger/action combinations. User instructions are in docs/HYPERSHIFT.md.
