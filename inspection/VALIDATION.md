# Validation of version 0.2.0

Build environment: Linux x86-64, Rust 1.99.1. Release target:
`x86_64-unknown-linux-musl`, linked with `rust-lld`.

Passed:

- Six Rust unit tests covering chord/release order, scheduler timing, trigger event
  filtering, rejection of invalid configurations, empty defaults, held mappings,
  and reference counting when mappings share a key.
- Seven Python/Qt tests: conversion to real Rust configs, default resets,
  independent plate profiles, persistence, corruption preservation, macro editor
  round trips/reordering, the edit/apply/learn/reset Qt flow using a mock helper,
  and real JSON-session error/EOF handling.
- `cargo clippy --all-targets --locked -- -D warnings`.
- `cargo fmt --check`.
- Release binary CLI smoke checks: help, version, example configuration
  validation, device listing, and expected errors for absent hardware/invalid
  configurations.
- ELF inspection identifies the release as a stripped, static PIE executable.

The user confirmed all 12 side-button inputs and the initial CLI copy/paste
macros work on the physical mouse. The new GUI and held-key output, hot unplug
cleanup, other plates, and Bluetooth still need testing on that machine.
The development machine has no attached Naga V2 Pro and its input/uinput nodes
are not accessible to the development account.

The next device test is to connect from the Qt app on Arch/KDE, observe the
12-button highlights, apply a shortcut and a held-key binding, and reset to
defaults. Use Learn input to calibrate the other plates. Automatic physical
plate detection remains unimplemented; see FACEPLATES.md.
