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

## Current implementation and next evidence

NagaLibre supports manually selected 12-, 6-, and 2-button profiles. The
12-button inputs were confirmed on the user's mouse as `KEY_1` through
`KEY_9`, `KEY_0`, `KEY_MINUS`, and `KEY_EQUAL`. The other plates require
learning their actual input events; the app does not invent factory mappings.

There is no reliable plate identification in ordinary button presses alone:
pressing a button shared by multiple layouts does not establish which plate
is attached. The UI therefore labels plate selection as manual.

Further automatic-detection work needs one of:

- The installed Synapse Naga V2 Pro device module and the code that handles
  plate attachment changes, with enough associated DLLs to trace its calls.
- A Windows USB capture while Synapse is running, covering attachment of each
  known plate, to correlate requests/replies with known physical state.
- A validated open protocol implementation for this exact mouse/firmware.

No firmware/onboard profile writes are required for the current Linux input
remapping approach. The Qt app talks to an independently written Rust engine.
