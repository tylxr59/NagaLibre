# Faceplate investigation

## What was inspected

The user-provided installer was extracted without executing its contents.
`rzS3detmgr.dll` is a native PE32 DLL with SHA-256:
`4ca752372003046759b38778425efeb1bb3508c7d7bc756ed8f97100c2a15ccf`.

PE metadata, ASCII/UTF-16 strings, string cross-references, MSVC RTTI/vtables,
and x86 instructions were inspected using pefile and Capstone. The addresses
below are preferred-image virtual addresses (image base `0x10000000`). This is
manual reconstruction from disassembly, not recovered original source.

## A recovered query

The log string `GetDeviceLayoutNew start` points into a function at
`0x10027880`. It checks cached detection records, obtains a protocol object
through `0x10025200`, configures routing through `0x10034130`, and calls virtual
slot `+0x14` or `+0x2c`, selected by a routing argument of `0xff`. Successful
execution copies a returned byte to the caller's layout result.

MSVC RTTI identifies a `CProtocol25` vtable at `0x100ad2b4`. Relevant methods:

| Address | Role inferred from call path |
|---|---|
| `0x1004bbf0` | Normal layout query, vtable slot `+0x14` |
| `0x1004c000` | Alternate layout query, vtable slot `+0x2c` |
| `0x1004bcb0` | Transport called at slot `+0x44` |

Both query methods construct a small request containing a 16-bit value `6`,
payload length `2`, and two initially zero bytes. They call the transport with
routing argument `0` or `0xff`. On success, the first output pointer receives
the second returned payload byte; the second receives the first payload byte.
The wrapper uses the latter as the layout value.

Reconstructed pseudocode, with descriptive names supplied by this project:

```text
query_layout(out_other, out_layout, alternate):
    request.command = 6
    request.length = 2
    request.payload = [0, 0]
    result = transact(request, alternate ? 0xff : 0)
    if result >= 0:
        *out_other = request.payload[1]
        *out_layout = request.payload[0]
    return result
```

The transport allocates a `0x5b`-byte buffer (report ID plus 90-byte report),
sets a transaction/routing field, ORs `0x80` into the command, converts 16-bit
fields via a virtual method, adds a checksum, sends the request, and reads a
response. It checks the transaction field, returned command, response status
`2`, and length before copying the payload back. The resulting command is
consistent with command class `0x00`, command ID `0x86`, and a two-byte payload.

This is **not yet a verified faceplate query**. In particular, the installer
has a generic device-variant detection role and this routine can apply to
multiple device families. No mapping from the returned layout byte to the
Naga V2 Pro's 2-, 6-, or 12-button plates has been established. A nonzero
layout value must not be treated as a faceplate count without validation.

The installer advertises an additional detection-manager download at
`https://manifest-assets.razersynapse.com/lwi/manifest.json`. The manifest
retrieved during analysis identified `DetectManager-v1.1.0.76.zip`; it does
not by itself document a mouse faceplate protocol. No Windows executable was
run and no vendor HID request was sent to the user's mouse.

## Naga-specific hardware-module getter (2026-10-19)

The generic layout getter above was superseded by a model-specific trace through
[Device167 from Razer's CDN](https://cdn.razersynapse.com/1709508222Kov7zCpDRazer_167_0_Setup_v3.9.0331.030402.exe).
Package SHA-256: `564279d02e021a3ab3df1824d192cfc3781ed917dadfc5661189dbf84ccf6c25`.
Static NSIS extraction exposes `PID00a7MW_v24.0.0.030115.exe`, which contains
`RzCtl_00A7.dll`. Controller SHA-256:
`dc7dcf529731e95ce6f712e7ce5166423b80ea26087648061cf343e7594578d7`.
No Windows payload was executed. Native disassembly used objdump and Capstone;
managed IL was decoded with dnfile/dncil. Proprietary extraction, disassembly,
and tooling remain local under ignored `inspection/payload/`.

All native addresses below use preferred image base `0x10000000`:

- `RSy3_HardwareModule.dll`: `HardwareModule_GetHardwareModule` at `0x10020be0`
  requests controller operation `0x28004` and returns its one-byte module value.
- `RzCtl_00A7.dll`: operation registration at `0x1001f606` selects `0x1001c540`.
  That handler invokes protocol vtable slot `+0x4c`.
- The `CProtocol25` vtable at `0x1007ab1c` maps this slot to `0x1002a0a0`.
  It initializes command word `0x0039`, length one, payload zero, then calls
  vtable slot `+0x5c4`, the getter transport at `0x10029ac0`.
- This transport ORs `0x80` into the command word, byte-swaps the word, and sends
  the standard 91-byte feature buffer. Thus the wire getter is **class `00`,
  command `b9`, payload `[00]`**, with one returned byte. No settings write is
  needed. NagaLibre uses its existing independently implemented framing,
  transaction, checksum and response validation.
- Managed `Razer.167_0.UI.dll` handles module changes in
  `MainControl.<AnimateHardwareModule>b__255_0` (method RVA `0x148c4`):
  module 1 selects the two-button view, module 3 the twelve-button view, module
  4 the internally named `SevenButton` view, and zero the detached view.
  The six-button identification below comes from the user's physical swap,
  resolving that misleading internal view name. ID 2 remains unrecognized.

## Physical verification

On 2026-10-19 the connected wired Naga V2 Pro (`1532:00a7`) was sampled once
per second with the read-only CLI while the user identified and swapped plates.
A durable active-slot backup was saved with the existing backup script first.
Observed sequence:

| User-identified state | Module ID | Consecutive samples before next swap |
| --- | --- | --- |
| Twelve buttons | 3 | 75 |
| Detached | 0 | 2 |
| Six buttons | 4 | 30 |
| Detached | 0 | 2 |
| Two buttons | 1 | 33 |
| Detached | 0 | 4 |
| Twelve buttons again | 3 | At least 9 |

Only getters were used; no mode, profile, mapping or firmware writes were made.
The capture is local at `/tmp/nagalibre-faceplate-readings.jsonl`, not committed.
This verifies detection and detach/reattach transitions on one wired mouse.
The user subsequently confirmed desktop detection worked after being asked to
connect the rebuilt app and swap plates. The exact GUI swap sequence was not
separately recorded. This does not verify software outputs for the other plates
or receiver operation.

## Implementation

`src/faceplate.rs` implements the getter and explicit ID mapping. Unknown IDs
retain their raw value and have no inferred button count. The `faceplate` CLI
prints one reading, or polls every second with `--watch`.

The GUI requests monitoring after connecting to a protocol-3 helper. The helper
serializes detection with onboard transactions on its main thread and emits
only changes. Before publishing a change or read failure it stops software
workers, releasing held output and grabs, and invalidates prepared saves and
snapshots. The GUI cancels learning, retains each plate's draft, and selects
known plates automatically. Detached/unknown plates block Apply; read errors
allow an explicitly labeled manual fallback. Software Apply includes the
expected module ID, checked again before starting its worker. Onboard prepare
and commit require a fresh twelve-button detection when monitoring is enabled.
Polling stops when the helper exits, including after an onboard save.

Button events are still insufficient to identify plates or infer their mappings.
Six- and two-button software inputs still require learning. Receiver detection
uses the same getter but remains unverified; Bluetooth is unsupported.
