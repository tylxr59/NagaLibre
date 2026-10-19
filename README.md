# NagaLibre

<p align="center">
  <img src="assets/nagalibre-hero.png" alt="Naga Libre project artwork" width="420">
</p>

NagaLibre is a Qt 6 desktop app backed by the `naga-macros` Rust input engine.

Development status and next steps: [project handoff](HANDOFF.md).

**Use version 0.2.2 or newer.** Version 0.2.0 could accidentally learn a main
mouse click as a side-button input. If clicking now types a key, switch to a
terminal using the keyboard and run `sudo pkill -x naga-macros` to restore normal
input. Quit the old GUI, update, and use **Reset 12 buttons** to clear the bad
mapping from the saved profile.

Version 0.2.2 also fixes the `exposes absolute axes` failure when applying a
side-button binding: it prefers the ordinary keyboard interface over redundant
composite interfaces and preserves absolute-axis data if an interface needs it.
No manual event-device selection or profile reset is needed for this fix.

## Desktop app

Extract `NagaLibre-linux-x86_64.tar.gz`, open the `NagaLibre` folder, and launch:

```sh
sudo pacman -S --needed pyside6
./nagalibre
```

Stop any earlier CLI remapping process with Ctrl+C before connecting.
Run the app as your normal desktop user. **Connect mouse** requests access using
your desktop's polkit password dialog. The GUI stays unprivileged; only the Rust
input helper opens the mouse and uinput. The desktop needs polkit (`pkexec`) and
a running authentication agent. No system service or permissions rule is installed.

Version **0.3.1** distinguishes stored mouse bindings from local drafts. A failed
read displays **Stored: unread** and disables hardware saves. The old B shown
in a draft is not evidence that the mouse is mapped to B. If inventory reading
fails, obtain the raw getter replies with:

```sh
sudo ./naga-macros onboard-probe
```

The physical USB probe returned the compact inventory `05 01 02` (capacity 5,
slots 1 and 2). The source parser now accepts this reply; the released 0.3.1
binary still requires six bytes and rejects it. The source fix builds and passes
automated tests; physical `onboard-read` now succeeds for slots 1 and 2.
Raw probing found keyboard records with declared length 1 but both modifier
and HID usage bytes present. The source now decodes these and preserves original
bytes in backups; physical monitoring confirmed all twelve factory key outputs
in active slot 1. A fresh physical read verified the corrected decoding for
all twelve buttons and preservation of the original nonstandard records.
Settings writes remain unverified. The probe changes no settings.

To inspect complete button getter payloads from an existing slot with a local
build, use `sudo ./target/release/naga-macros onboard-probe --slot 1`.
This adds primary and side-button reads without changing settings.

For a durable backup of the active slot before controlled hardware testing, run
`python3 scripts/backup_onboard.py` as your normal user from the source checkout.
It requests sudo only for the Rust getter, saves a private snapshot with the
original wire records, and prints its path and checksum. It performs no writes
to the mouse.

The approved controlled hardware test uses
`python3 scripts/onboard_controlled_test.py apply`, then a physical input and
quit/reconnect check, then the read-only `verify` stage, followed by `restore`.
It requires a previously verified private test plan with explicit write approval;
it checks backup/engine checksums and live state, saves a recovery backup before
commit, and only changes side button 1 to B. Restore verifies the original wire
records exactly. Hardware outcomes are recorded in `HANDOFF.md`; a successful
script readback alone does not establish physical clicks or reconnect persistence.

Version **0.3.0** adds an experimental **Mouse memory** mode for existing
onboard profile slots. Read-only slot discovery and button-record retrieval
have succeeded on a physical mouse; settings writes remain unverified. Start
with this read-only diagnostic:

```sh
sudo ./naga-macros onboard-read
```

In **Mouse memory** mode:

- Connect / **Read slots** discovers initialized slots. Select a slot to edit.
  Tiles show its stored bindings alongside the draft; your local draft stays unchanged.
- Edit the twelve side buttons, then **Save 12 bindings to mouse**. This writes
  changed actions from the twelve-button draft and activates that slot. Unchanged
  actions retain their original firmware encoding. Standard keys,
  modifier shortcuts (Ctrl+C), and mouse-button outputs are supported.
- The app saves a private backup before writing, checks every binding by reading
  it back, and stops the helper after success. The intended result is bindings
  that work after quitting the app and reconnecting the mouse.
- **Reset 12 buttons** writes the factory `1…9, 0, -, =` actions to the selected
  slot. Primary left/right clicks are never written.
- **Restore backup…** restores saved side-button records to their original slot
  on the same mouse and connection type, then activates it. Backups live under
  `~/.config/NagaLibre/backups/`.

Only existing initialized slots are edited; creation/deletion is unavailable.
Use the USB cable or 2.4 GHz receiver; Bluetooth is unsupported. Multi-step
onboard macro storage remains under investigation and is rejected before writes.
See [protocol evidence and limitations](inspection/ONBOARD.md).

In **Software** mode, keys, shortcuts and macro sequences run through evdev and
uinput while the background helper is active:

- **Learn input** observes a side button; primary clicks are ignored. Live input
  highlights tiles. The 6- and 2-button plates require manual input learning.
- **Apply bindings** activates the draft. **Stop remapping** stops software
  remapping. The input emitted by firmware passes through again; previously saved
  onboard settings remain active.
- Closing to the tray keeps software remapping running. **Ctrl+Q** quits;
  **Esc** stops software remapping with the window focused.

**Save draft** only saves local edits. Drafts are stored at
`~/.config/NagaLibre/profiles.json` (or under `$XDG_CONFIG_HOME`). Invalid files
are preserved. Automatic faceplate detection is not implemented; see
[the investigation](inspection/FACEPLATES.md).

The Arch download includes the GUI source and the static Rust input engine;
it uses your system Python and Qt so it follows your Plasma setup. It requires
no Rust installation or compilation. Arch's packages are
[pyside6](https://archlinux.org/packages/extra/x86_64/pyside6/) and
[polkit-kde-agent](https://archlinux.org/packages/extra/x86_64/polkit-kde-agent/)
(the latter is normally installed with Plasma).
Native source installation for other distributions is also available:

```sh
python3 -m venv .venv
.venv/bin/pip install -r gui/requirements.txt
cargo build --release --locked
./nagalibre
```

The launch script uses the local venv when present. The GUI finds `naga-macros`
beside the executable, in `dist/`, or in `target/release/`. Set
`NAGALIBRE_BACKEND=/absolute/path/to/naga-macros` to override it. Users who already
have narrowly scoped device permissions can set `NAGALIBRE_NO_PKEXEC=1` to run
the helper without elevation. Do not run the Qt GUI using sudo.

To test the GUI without real devices:

```sh
cargo build --locked
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s gui -p 'test_*.py' -v
```

The tests use a mock session for Qt interactions and the real Rust executable for
configuration validation and protocol lifecycle checks. For a distributable build,
see `scripts/package.py`. It packages source and the static engine, excluding
build caches and extracted proprietary installer components.

## Command-line tool

A standalone Rust command-line program that runs mouse macros on Linux. Intended
for the **Razer Naga V2 Pro**, with no Synapse or OpenRazer dependency. It reads
Linux evdev input and emits keyboard shortcuts, sequences, delays, and mouse
button actions through uinput. It works below the Wayland/X11 display layer.

The initial macro engine was confirmed working by the user with a physical
Naga V2 Pro's 12-button plate. The user also confirmed the 0.2.2 composite-interface fix works. Onboard
programming, other plates and power-cycle persistence still need device testing. The development machine has neither the mouse
nor permission to access uinput.

## First test on your main machine

The release archive contains a static **Linux x86-64** binary. Extract it, open
a terminal in that folder, and run:

```sh
./naga-macros list
sudo ./naga-macros monitor
```

Press each side button once, in order. Output looks like:

```text
/dev/input/event12 KEY_1 1
/dev/input/event12 KEY_1 0
```

`1` means pressed, `0` released, and `2` repeat. Send back the `list` output and
the monitor output, with which printed mouse button you pressed. Monitor only
observes events: normal button actions still reach applications. Use a harmless
window while checking the buttons. Ctrl+C stops monitoring.

Automatic selection uses vendor `1532` with product `00a7`/`00a8`, or a matching
Naga V2 Pro name. All matching event interfaces are selected, because the mouse
can expose separate pointer, keyboard, and consumer-control interfaces. If
automatic discovery misses an interface, select it explicitly:

```sh
sudo ./naga-macros monitor --device /dev/input/event12 --device /dev/input/event13
```

Bluetooth discovery and saved firmware mappings may differ. Start with the USB
cable or 2.4 GHz receiver if possible. A button must actually emit a Linux input
event to be usable by this program. This program cannot activate buttons hidden
by firmware or turn a firmware-only DPI/profile action into an input event.

## Configure and run

Copy `examples/macros.toml` to `macros.toml` and replace the triggers with names
observed in monitor. Example bindings are illustrative, not verified physical
button numbers. Linux `KEY_1` is the key code emitted by the mouse, not necessarily
the button printed “1”.

```sh
cp examples/macros.toml macros.toml
./naga-macros check macros.toml
sudo modprobe uinput
sudo ./naga-macros run macros.toml
```

The examples map `KEY_1` to Ctrl+C, `KEY_2` to Ctrl+V, and `KEY_3` to an
Alt, F, I sequence. Use `--device` with `run` to restrict the selected interfaces.
Use `/dev/input/by-id/...-event-kbd` or `...-event-mouse` paths where available
for stable selections across restarts. Do not select your regular keyboard.

While running, mapped button presses, repeats, and releases are suppressed.
Unmapped keys, pointer movement, and scrolling pass through virtual devices.
Only a fresh press launches a macro; holding a button does not loop it.
Held-key remaps instead follow the original press, release, and repeat events.
Macros run one at a time. Additional presses while busy are discarded, so
actions cannot pile up and execute later. Physical input continues during delays.

Ctrl+C or SIGTERM stops playback, releases macro-held keys, destroys virtual
devices, and relinquishes input grabs. Disconnection exits with an error;
reconnect and restart the program. The kernel also releases grabs when the
process exits. Restart to load configuration edits or discover reconnected
devices. There is no autostart installation or system configuration change.

## Macro format

For a key that stays held while the mouse button is down:

```toml
[[binding]]
trigger = "KEY_1"
key = "KEY_LEFTCTRL"
```

A binding must have exactly one of `key` or `steps`. An empty `binding = []`
configuration represents defaults. The desktop session handles this by monitoring
without grabbing the mouse.

For a sequence:

```toml
tap_ms = 20  # optional; default key/chord hold time

[[binding]]
trigger = "BTN_SIDE"
steps = [
  { chord = ["KEY_LEFTCTRL", "KEY_C"] },
  { wait_ms = 150 },
  { tap = "KEY_ENTER" },
  { down = "KEY_LEFTSHIFT" },
  { tap = "KEY_A" },
  { up = "KEY_LEFTSHIFT" },
  { tap = "BTN_LEFT" },
]
```

Each step has exactly one field: `tap`, `chord`, `down`, `up`, or `wait_ms`.
Chords press keys in order and release them in reverse order. Every explicit
`down` requires a later `up`. Unknown fields/key names, duplicate triggers,
unbalanced key holds, and chords with duplicate/held keys fail validation before
input is grabbed. Limits: tap time 1–1000 ms, each wait at most 60 seconds,
macro duration at most five minutes, at most 4096 steps per binding.

Key names follow Linux input codes, such as `KEY_F13`, `KEY_LEFTMETA`,
`KEY_LEFTCTRL`, and `BTN_EXTRA`. Events are key positions interpreted by your
desktop's keyboard layout. Physical modifiers you hold can affect macro output.
Timing is best effort, with a 2 ms polling interval; it is not real time.

## Permissions and scope

Reading selected `/dev/input/event*` nodes and writing `/dev/uinput` requires
permissions; `sudo` is the initial test path above. `list` and `check` need no
input-device access. A later installation can grant narrowly scoped device
access to a dedicated group rather than running the process as root. No broad
input permission rules are installed by this project.

Software macros execute in the background process. Mouse-memory mode instead
writes side-button records to existing onboard slots. Multi-step onboard macros,
DPI/RGB settings, shell commands and Razer software installation are unsupported.
Applications that reject synthetic input may not accept software macros.

## Build and verify

Requires a current Rust toolchain on Linux:

```sh
cargo test --locked
cargo clippy --all-targets --locked -- -D warnings
cargo build --release --locked
./target/release/naga-macros check examples/macros.toml
```

To build the portable static binary:

```sh
rustup target add x86_64-unknown-linux-musl
CARGO_TARGET_X86_64_UNKNOWN_LINUX_MUSL_LINKER=rust-lld \
  cargo build --release --locked --target x86_64-unknown-linux-musl
```

The Rust and Qt tests exercise key/chord ordering, delays, rejection of invalid
macros, suppression of trigger edges, shared held-key ownership, configuration
round trips, learning, reset behavior, profile switching, and helper EOF shutdown.
The CLI macros and 0.2.2 GUI fix worked on the user's mouse. The onboard path,
other plates and disconnection cleanup still need physical testing.

The uploaded installer inspection is documented in
[inspection/REPORT.md](inspection/REPORT.md). No proprietary DLLs are included in
the release. Technical references:
[Linux uinput](https://www.kernel.org/doc/html/latest/input/uinput.html),
[evdev](https://docs.rs/evdev/0.13.2/evdev/), and
[OpenRazer device IDs](https://github.com/openrazer/openrazer).
