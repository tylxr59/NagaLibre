# Command-line guide

Build with `cargo build --release --locked` from the repository root. Commands
below use the resulting `target/release/naga-macros` executable. The CLI works
below the Wayland/X11 display layer and can be used without the desktop app.

## Find and monitor the mouse

```sh
./target/release/naga-macros models
./target/release/naga-macros list
sudo ./target/release/naga-macros monitor
```

Monitor prints input events without grabbing or changing the mouse. Values are
`1` for press, `0` for release, and `2` for repeat. Ctrl+C stops it.

Automatic discovery selects recognized models from the built-in registry.
Experimental models support software remapping with learned inputs; only the
V2 Pro has vendor/onboard access enabled. Composite event interfaces are grouped
by physical USB device, and automatic selection requires exactly one mouse.
`models` prints the registry; `list --json` includes model capabilities.
To select specific nodes:

```sh
sudo ./target/release/naga-macros monitor --device /dev/input/event12 --device /dev/input/event13
```

Use the paths reported on your own machine; event numbers can change. Stable
`/dev/input/by-id/` links are useful when available. Do not select your regular
keyboard. A physical button must emit an input event to be a software trigger;
firmware-only DPI or profile actions cannot be captured this way.

## Collect support diagnostics

```sh
./target/release/naga-macros diagnose > nagalibre-diagnostics.json
./target/release/naga-macros list --all-razer --json
```

`diagnose` reads passive sysfs metadata and report descriptors for all Razer
products, including unknown models. It omits serial/unique IDs and does not open
device nodes, capture input or send vendor reports. Review device names and
errors before sharing. `--all-razer` includes unknown Razer input interfaces in
the JSON list; it does not enable their remapping or any vendor commands.

Use the [support guide](DEVICE_SUPPORT.md) and
[device support form](https://github.com/tylxr59/NagaLibre/issues/new?template=device-support.yml)
to submit results. Faceplate queries below apply only to the enabled V2 Pro.

## Detect the attached faceplate

```sh
sudo ./target/release/naga-macros faceplate
sudo ./target/release/naga-macros faceplate --watch
```

This read-only query prints JSON with `module_id` and `buttons`. Wired hardware
verified IDs `1` = two buttons, `3` = twelve buttons, `4` = six buttons, and
`0` = detached. Unknown IDs retain their raw value with `buttons: null`.
`--watch` samples once per second until Ctrl+C. It does not grab input or change
mouse settings. Stop the watcher before connecting the desktop helper so the
two processes do not compete for feature replies. Receiver detection is untested.

The desktop helper uses protocol 4 and publishes `faceplate` events on changes.
It advertises `slot_creation` for wired V2 Pro devices. The GUI's `onboard_create`
request prepares an unused slot and returns `onboard_creation_prepared` with all
existing snapshots. Only after durably saving that backup does the GUI acknowledge
the token through `onboard_commit`. Success returns `onboard_created` with the new
slot selected and the previous slot still active. Creation verifies firmware
defaults and existing records; failures attempt removal of only the new slot.
No public CLI command creates permanent profiles; use the desktop flow.

The protocol-4 hello also advertises `slot_activation`. `onboard_activate` accepts
an initialized `slot`, reads it and the previous active slot, and returns
`onboard_activation_prepared` with `backup`, `previous` and `token`. The GUI durably
saves both snapshots before sending `onboard_commit`. `onboard_activated` returns
the verified active snapshot. This changes only the active-profile selector;
it writes neither mappings nor device mode. Stale state, non-normal mode,
unexpected primary/middle clicks and an absent 12-button plate prevent switching.
A failed switch attempts restoration of the previous active slot, including after
a failed acknowledgement. Old helpers without the capability disable the button.

Fresh `onboard-read` snapshots now include `controls`: logical positions 13–16
for wheel tilt left/right, scroll-mode and DPI-cycle buttons. Their
firmware IDs are 34, 35, 6d and 60 in hexadecimal, recovered from Device167. The hello
capability `wheel_controls` allows an optional `controls` array on `onboard_prepare`.
Only explicit edits are sent; omitted controls retain exact stored records.
Backups include raw records for these controls. Older snapshots without the field
still restore their grid bindings while preserving the current wheel controls.
Wheel/scroll-mode getters have succeeded on the user's wired mouse, and a left
tilt remap to B was physically confirmed. The DPI getter returned category 6/data
[6] from wired slots 1 and 2. Other control writes/output remain unverified.

The desktop Restore defaults button stages grid defaults and factory control
actions in the local draft, without sending hardware commands. Saving uses the
existing prepared transaction. Factory wheel actions are category 1/data [104] (0x68) on
logical 13, category 1/data [105] (0x69) on logical 14, and category 18/data [4] on logical
15, plus category 6/data [6] on logical 16 for cycling DPI stages. Normal prepare accepts these functions only on those positions; arbitrary
firmware actions remain unsupported. Keep stored binding continues to omit that
control from the save request. Restoring an old hardware backup remains separate.
Defaults and control IDs come from `devices/models.json`; three-control local
drafts migrate by preserving their edits and appending a pass-through DPI control.
The user confirmed physical DPI cycling with the stored factory binding;
DPI remapping to B and cycling after exact mapping restoration were also
physically confirmed on the wired mouse.
Its binding uses the
existing DPI stages; the mapping writer does not edit their values. Mapping
snapshots do not include the DPI stage table.

The GUI automatically selects the corresponding draft and stops remapping on
a change; Apply rechecks the module ID before starting software bindings.
The standalone `run` command uses its supplied config and does not select
plate-specific drafts.

## Configure software macros

Copy the example and choose triggers from the monitor output:

```sh
cp examples/macros.toml macros.toml
./target/release/naga-macros check macros.toml
sudo modprobe uinput
sudo ./target/release/naga-macros run macros.toml
```

The example provides copy, paste, and a key sequence. It is a starting point;
input codes describe emitted events, not guaranteed physical button numbers.
Main mouse buttons cannot be triggers. Clicks are allowed as macro outputs.

For a key held while the side button is held:

```toml
[[binding]]
trigger = "KEY_1"
key = "KEY_LEFTCTRL"
```

For a sequence:

```toml
tap_ms = 20

[[binding]]
trigger = "KEY_2"
steps = [
  { chord = ["KEY_LEFTCTRL", "KEY_C"] },
  { wait_ms = 150 },
  { tap = "KEY_ENTER" },
  { down = "KEY_LEFTSHIFT" },
  { tap = "KEY_A" },
  { up = "KEY_LEFTSHIFT" },
]
```

A binding has exactly one of `key` or `steps`. Each step has one action: `tap`,
`chord`, `wait_ms`, `down`, or `up`. Every `down` needs a later `up`. Chords release
in reverse order. Key names use Linux input codes, such as `KEY_F13`,
`KEY_LEFTMETA`, and `BTN_EXTRA`. Your keyboard layout and held modifiers affect
output.

Validation rejects duplicate triggers, unknown fields/keys, and unbalanced
holds before grabbing input. Tap time is 1–1000 ms, each wait is at most
60 seconds, and a macro is limited to five minutes and 4096 steps. Timing is
best effort. Only a fresh press starts a sequence; it does not loop while held.
Macros run one at a time and extra presses while busy are discarded.

Mapped input is suppressed while the helper runs; unmapped movement, scrolling,
and keys pass through. Ctrl+C or SIGTERM releases held output and input grabs.
Disconnection stops the process; reconnect and restart manually. `check` and
`list` need no elevated access. No autostart service or device-permission rule
is installed. Applications that reject synthetic input may reject these macros.

These software macros require the process to stay running. They do not upload
macro sequences to the mouse.

## Read onboard settings

```sh
sudo ./target/release/naga-macros onboard-slots
sudo ./target/release/naga-macros onboard-read
sudo ./target/release/naga-macros onboard-read --slot 1
sudo ./target/release/naga-macros onboard-probe --slot 1
```

These are read-only settings queries for the enabled onboard implementation.
`onboard-slots` prints the device-reported `capacity`, `initialized` slot IDs and
`active` slot, without reading bindings or serial numbers. It can enumerate an
empty inventory without creating slots. `onboard-read` prints a decoded snapshot;
`onboard-probe` prints raw getter payloads for diagnosis. The optional probe slot
adds primary and twelve side-button queries. Serial numbers appear in read/probe output;
redact them before sharing publicly.

To save a durable private backup of the active slot:

```sh
python3 scripts/backup_onboard.py
```

Run this as your regular user. It invokes sudo only for the Rust getter, writes
the backup under your NagaLibre config directory, and prints its checksum.
Use the Qt app to edit bindings, reset the grid, or restore a backup.
