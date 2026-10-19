# Additional mouse models

## Scope and evidence

The model registry is `devices/models.json`, compiled into the Rust engine and
read by the Python GUI. The additional models below are **experimental software
support**, derived from static inspection on 2026-10-19. No additional physical
mice were available. Recognition, layouts and software integration are covered
by automated checks; actual input events and outputs remain unverified.

The supplied installer is the same bootstrap documented in REPORT.md. Managed
IL decoding recovered its discovery and manifest request format, including the
WINDOWS OS selector. Current manifests supplied Synapse 4 bootstraps rather than
the older model controllers. An external public package index was used only to
locate direct Razer CDN URLs. All device evidence came from the downloaded Razer
packages, not third-party binaries or protocol claims. Nothing was installed or
executed from the Windows packages.

NSIS extraction exposes each model's `.rzdd` device descriptions and nested
`PIDxxxxMW` controller packages. Their paired vendor/product fields contain the
little-endian VID `32 15` and PID; the middleware filenames and controller names
corroborate these identities. DefaultMappings.xml supplies button groups and
managed UI modules describe swappable layouts. Layout counts were cross-checked
against Razer's documentation where internal names were misleading, notably
[Naga Pro's six-button plate](https://www.razer.com/mena-en/gaming-mice/razer-naga-pro).
These Windows mapping descriptions do not establish Linux evdev trigger codes;
experimental profiles deliberately start with no learned inputs.

| Model | Accepted USB PIDs (VID 1532) | Side layouts | Enabled tier |
| --- | --- | --- | --- |
| Razer Naga V2 Pro | 00a7, 00a8 | 12, 6, 2 | Existing V2 Pro support; wired hardware verified |
| Razer Naga Pro | 008f, 0090 | 12, 6, 2 | Experimental software, Learn input required |
| Razer Naga Trinity | 0067 | 12, 7, 2 | Experimental software, Learn input required |
| Razer Naga X | 0096 | 12 | Experimental software, Learn input required |
| Razer Naga Left-Handed | 008d | 12 | Experimental software, Learn input required |
| Razer Naga Chroma | 0053 | 12 | Experimental software, Learn input required |
| Razer Naga V2 HyperSpeed | 00b4 | 12 | Experimental software, Learn input required |
| Razer Viper V2 Pro | 00a5, 00a6 | 2 | Experimental software, Learn input required |

USB receivers are included where their identities occur in the packages. This
does not verify receiver operation, even for the V2 Pro. Bluetooth identities
`0092`, `00b5` and `00a9` are excluded from automatic discovery. Unknown products
and alternate receiver revisions are not inferred from marketing names.

## Candidate faceplate protocol

Native Capstone/objdump inspection found `CProtocol25` hardware-module getter
implementations in these preferred-image virtual addresses (base 0x10000000):

| Controller | Vtable | Slot +4c method | Request construction |
| --- | --- | --- | --- |
| RzCtl_0067.dll (Trinity) | 10077620 | 10027aa0 | Command word 0039, length 1, zero payload |
| RzCtl_008F.dll (Pro wired) | 10077610 | 10027af0 | Command word 0039, length 1, zero payload |

This matches the V2 Pro getter construction that produces wire `00/b9` through
its getter transport. Managed `Razer.103_0.UI.dll` at method RVA `13500` maps
module 1 to two buttons, 2 to seven, and 3 to twelve. `Razer.143_0.UI.dll` at
method RVA `13ca8` maps module 1 to two, 4 to the internally named SevenButton
view (the marketed six-button layout), and 3 to twelve. These are candidate
protocol facts, **not hardware verification**. Automatic vendor queries remain
disabled for both models until their transport and replies are tested.

## Runtime boundaries

- New models use evdev/uinput software remapping only. The GUI disables Mouse
  memory; the helper independently rejects all onboard commands for them before
  connecting to a feature-report interface. Faceplate commands for these models
  return unavailable without issuing vendor reports.
- Trinity exposes 12/7/2 layouts; Pro exposes 12/6/2. Other added models have
  fixed layouts. Switching layouts pauses software bindings; inputs are learned.
- Drafts are isolated by model under `NagaLibre/devices/<model-id>/profiles.json`.
  Existing V2 Pro profiles retain their original location. In-memory drafts also
  survive model changes. Unknown/corrupt files are not overwritten automatically.
- Automatic input discovery requires exactly one supported physical USB device.
  Composite interfaces share their USB ancestor. Multiple units, including two of
  the same model, are rejected. A session pins its original USB path and model;
  changing models requires reconnecting. Explicit CLI event paths remain available.
- V2 Pro onboard transport and writable button IDs remain restricted to the
  existing implementation. Shared commands never grant another model write access.

## Razer package sources

Each URL below was downloaded directly from Razer, extracted statically, and
hashed locally. Extracted binaries, decoded IL, disassembly, fetched manifests
and analysis tools remain ignored under `inspection/payload/`.

- Razer Naga V2 Pro: [Device167 package](https://cdn.razersynapse.com/1709508222Kov7zCpDRazer_167_0_Setup_v3.9.0331.030402.exe). SHA-256 `564279d02e021a3ab3df1824d192cfc3781ed917dadfc5661189dbf84ccf6c25`.
- Razer Naga Pro: [Device143 package](https://cdn.razersynapse.com/17095082227nB9L24DRazer_143_0_Setup_v3.9.0331.030402.exe). SHA-256 `d034d674d0fad52e7a1dae9813317e22c39ca968de9c7d9e942b7a71838a1409`.
- Razer Naga Trinity: [Device103 package](https://cdn.razersynapse.com/1709511092Aoc6w5mhRazerNagaTrinitySetup_v3.9.0331.030402.exe). SHA-256 `b19f185c01d25164c6de4dd8d4ee328a9fb016ea3c7c2078814549d4b53a7f19`.
- Razer Naga X: [Device150 package](https://cdn.razersynapse.com/1709508458lS4C4mXvRazer_150_0_Setup_v3.9.0331.030402.exe). SHA-256 `9cb8067062f767def754ce5ccf4b799b0310f39f8fe1e6a32ea4533bb9125ea1`.
- Razer Naga Left-Handed: [Device141 package](https://cdn.razersynapse.com/1709521770otHylIR8Razer_141_0_Setup_v3.9.0331.030402.exe). SHA-256 `9741a80839d35fe1a20c3a14051075597d050bb30c920c8f5bfdd27e76da41ee`.
- Razer Naga Chroma: [Device83 package](https://cdn.razersynapse.com/1709511092KrAPXJv9Razer_83_0Setup_v3.9.0331.030402.exe). SHA-256 `3f5f9346ab92e555bae165bb0d49bfbe978de64227416511b2b41fa65ba3bfde`.
- Razer Naga V2 HyperSpeed: [Device180 package](https://cdn.razersynapse.com/1709508222NquWPPuZRazer_180_0Setup_v3.9.0331.030402.exe). SHA-256 `3ebb2294e08382401c0f60081f60b54928483cf05958feeac66f77007ddccc2e`.
- Razer Viper V2 Pro: [Device166 package](https://cdn.razersynapse.com/1728899625ttWPvEueRazerAvaT1RefreshSetup_v3.9.1130.101413.exe). SHA-256 `0a7556ac95c022c66b0c20afe5c5d351f218de9c60c3f9392816e9fafbd36fe7`.
