# Validation of version 0.3.0

Linux x86-64, Rust 1.99.1; release target x86_64-unknown-linux-musl,
linked with rust-lld. These are local software checks, not hardware validation.

- Sixteen Rust tests pass. New coverage exercises report framing/checksums,
  stale reply rejection, HID descriptor parsing, side-only writes, readback,
  stale-plan rejection, activation/normal mode, device-bound restoration, and
  rollback of a failed acknowledgement after the device accepted a write.
  Existing scheduler/config/interface selection regressions also pass.
- Thirteen Python/Qt tests pass. New checks cover HID key/chord translation,
  rejection of unsupported macros/plates, private backups, backup-failure commit
  prevention, helper shutdown on success, and a full read/prepare/commit/shutdown
  flow through a real QProcess with a fake hardware helper, including reconnect.
- Clippy passes for all targets with warnings denied; Rust formatting passes.
- The Qt window was rendered offscreen and visually inspected.

The user's physical 12-button inputs, initial CLI macros and 0.2.2 composite
interface fix are confirmed. **The new hidraw transport, firmware profile writes,
readback, rollback on a real device, and persistence after quitting or reconnecting
are not hardware-tested.** No Naga is attached to the development machine.
The new build is a prerelease for controlled hardware testing, not evidence that
all of Synapse has been reimplemented. Multi-step onboard macros remain absent.

First test: `sudo ./naga-macros onboard-read` over the USB cable. It requests
serial, mode, slot inventory, active slot, primary clicks and twelve side records
without changing settings. Inspect that output before testing a single key save.
Then quit, reconnect/power-cycle, check all primary controls, test factory reset
and backup restoration. See ONBOARD.md for protocol provenance and limits.
