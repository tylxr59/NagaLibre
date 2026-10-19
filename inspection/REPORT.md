# Static inspection of the uploaded installer

File: `RazerSynapseInstaller.exe`, 14,923,464 bytes.

SHA-256:
`e4eabf1a0cf030b773a1a14ed22f4cb337c5f85638863260215b6315d83eb570`

Inspection used `file`, `7z l`, `7z x`, and ASCII/UTF-16 string extraction.
The uploaded EXE and its extracted executables were **not executed**. The
presence of signature data was observed, but signature trust was not validated.

Findings:

- Outer file: Windows PE32 x86 GUI executable, with version metadata identifying
  “Razer Installer”, version `2.6.0.890`.
- A resource (`.rsrc/RCDATA/1337`) contains another PE, with a DotNetZip
  self-extracting ZIP payload. 7-Zip reports 81 packaged files.
- Contents include `RazerInstaller.exe`, `Razer.Installer.Core.dll`,
  `Razer.Installer.UI.dll`, device detection DLLs (`rzS3detmgr.dll` and wrappers),
  BLE components, JSON detection data, configuration, and .NET dependencies.
- `InstallerConfiguration.xml` points to `discovery3.razerapi.com` and
  `manifest3.razerapi.com`. UTF-16 strings in `Razer.Installer.Core.dll` include
  manifest URLs and download/install operations. These support identifying the
  upload as an installer/download bundle.
- The packaged file listing does not expose an obvious Naga-specific macro
  module or a documented macro-programming API. This is a limited static
  inspection, not exhaustive disassembly of every component. No claim is made
  that a mouse protocol has been recovered or that onboard macros are impossible.

This report records the initial installer inspection. The current implementation
is independent of the extracted Razer DLLs. Later onboard HID work and its
evidence are documented in [ONBOARD.md](ONBOARD.md).

`archive-listing.txt` records the full 7-Zip inventory; `endpoints.txt` records
selected endpoint strings. Extracted proprietary files are local inspection
material and excluded from the repository.
