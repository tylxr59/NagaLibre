# Command-line guide

Build with `cargo build --release --locked` from the repository root. Commands
below use the resulting `target/release/naga-macros` executable. The CLI works
below the Wayland/X11 display layer and can be used without the desktop app.

## Find and monitor the mouse

```sh
./target/release/naga-macros list
sudo ./target/release/naga-macros monitor
```

Monitor prints input events without grabbing or changing the mouse. Values are
`1` for press, `0` for release, and `2` for repeat. Ctrl+C stops it.

Automatic discovery selects Naga V2 Pro interfaces. To select specific nodes:

```sh
sudo ./target/release/naga-macros monitor --device /dev/input/event12 --device /dev/input/event13
```

Use the paths reported on your own machine; event numbers can change. Stable
`/dev/input/by-id/` links are useful when available. Do not select your regular
keyboard. A physical button must emit an input event to be a software trigger;
firmware-only DPI or profile actions cannot be captured this way.

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
sudo ./target/release/naga-macros onboard-read
sudo ./target/release/naga-macros onboard-read --slot 1
sudo ./target/release/naga-macros onboard-probe --slot 1
```

These are read-only settings queries. `onboard-read` prints a decoded snapshot;
`onboard-probe` prints raw getter payloads for diagnosis. The optional probe slot
adds primary and twelve side-button queries. Serial numbers appear in output;
redact them before sharing publicly.

To save a durable private backup of the active slot:

```sh
python3 scripts/backup_onboard.py
```

Run this as your regular user. It invokes sudo only for the Rust getter, writes
the backup under your NagaLibre config directory, and prints its checksum.
Use the Qt app to edit bindings, reset the grid, or restore a backup.
