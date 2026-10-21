# NagaLibre

<p align="center">
  <img src="assets/nagalibre-hero.png" alt="Naga Libre project artwork" width="420">
</p>

**Your Naga. Your buttons. Linux native.**

NagaLibre is a free and open-source reimplementation of the Razer Naga side-button
system for Linux. It lets you bind the thumb buttons to keys, shortcuts, and
macros through a Qt desktop app, with a Rust engine handling the mouse.

The verified target is the **Razer Naga V2 Pro**. Experimental software support
also recognizes the Naga Pro, Trinity, X, Left-Handed, Chroma, V2 HyperSpeed,
and Viper V2 Pro. On the V2 Pro, you can save supported bindings to the mouse’s
onboard memory so they keep working after you close the app. Software mode
supports macro sequences and experimental models. NagaLibre works independently of Synapse and
OpenRazer. It is an independent project, unaffiliated with Razer.

## What works today

Hardware verification below refers to the Naga V2 Pro.

| Feature | Support |
| --- | --- |
| 12-button plate | Main development and testing target |
| Onboard key bindings | USB save, app exit/reconnect persistence, and exact backup restore tested on one mouse and slot |
| Onboard shortcuts and mouse-button outputs | Ctrl+A, modifier release and right-click output physically tested over USB and receiver, with exact backup restore |
| Software keys, shortcuts, and macro sequences | Available while the background helper runs |
| Automatic faceplate detection | USB detection verified for 12-, 6-, and 2-button plates, including swaps |
| 6- and 2-button bindings | Input learning in software mode; remapping still needs physical testing |
| 2.4 GHz receiver | Twelve-button onboard save, physical shortcut/mouse outputs, power/reconnect persistence and exact restore tested |
| Bluetooth onboard programming | Unsupported |
| New onboard slots | Wired Naga V2 Pro, 12-button plate |
| Standard wheel modes | Five HyperScroll presets, active selection and cycle order over USB; preset feels/cycling physically tested, desktop flow covered by automated tests; Custom editing deferred |
| DPI stage values and RGB settings | Not implemented |
| Multi-step macros stored on the mouse | Not implemented; use software mode |
| Hypershift assignments | Normal/Hypershift GUI drafts and paired backups; wired twelve-button GUI save, hold/release, reconnect and exact restore verified |

See [the Hypershift desktop guide](docs/HYPERSHIFT.md) for layer editing, migration,
backups and the verification procedure. The [standard wheel guide](docs/WHEEL.md)
covers preset selection, cycle order and wheel-stage backups.

This is a project under active development. Start with the USB cable and the
12-button plate for the best-tested setup.

See [TODO.md](TODO.md) for the prioritized roadmap and remaining Synapse features.

## Experimental mouse models

The additional models are identified from Razer's device packages and have not
been tested on physical hardware. Connect one supported mouse and choose
**Software**. The app selects the model's layouts; use **Learn input** for each
side button before applying custom bindings. Trinity includes a seven-button
layout; fixed-layout mice select their layout automatically. Naga Pro and Trinity
plate selection is manual for now. Mouse-memory access and vendor faceplate
queries are disabled for these experimental models.

Each model keeps separate drafts. Your V2 Pro draft stays in its existing file;
other models use `~/.config/NagaLibre/devices/<model-id>/profiles.json` (or the
corresponding XDG config directory). Connect one mouse at a time for automatic
selection. Bluetooth and alternate receiver variants are unverified and excluded.

Run `./target/release/naga-macros models` to see the exact identities and
capabilities. The [model research notes](inspection/MODELS.md) record package
sources, USB IDs and evidence limits.

## Required software

- Linux with evdev, hidraw, and uinput support.
- A current stable Rust toolchain, including Cargo, and a C linker/compiler.
- Python 3.10 or newer and **PySide6 6.8 or newer** (Qt for Python).
- Git to clone the repository.
- **polkit**, including `pkexec`, and a running desktop authentication agent for
  the mouse-access prompt. KDE Plasma normally supplies an agent.

NagaLibre is distributed as source. Build the Rust engine locally; no prebuilt
executable or Razer software is needed.

### Arch Linux / KDE Plasma

Install the dependencies below. If you already manage Rust with rustup, keep
that toolchain and omit `rust` from this command.

```sh
sudo pacman -S --needed base-devel git rust python pyside6 polkit
```

The GUI uses the distribution's [PySide6 package](https://archlinux.org/packages/extra/x86_64/pyside6/).
If your Plasma session has no authentication agent, install
[polkit-kde-agent](https://archlinux.org/packages/extra/x86_64/polkit-kde-agent/)
and ensure it runs in your desktop session.

### Other distributions

Install Rust/Cargo, a C compiler, Git, Python with venv/pip support, and polkit
through your distribution or your preferred toolchain manager. Install PySide6
from your distribution, or create a virtual environment after cloning:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r gui/requirements.txt
```

The launcher automatically uses `.venv` when present. Your desktop also needs
the Qt platform libraries for its Wayland or X11 session.

## Build and launch

```sh
git clone https://github.com/tylxr59/NagaLibre.git
cd NagaLibre
cargo build --release --locked
./nagalibre
```

Run `./nagalibre` as your regular desktop user. **Connect mouse** opens the
password prompt for the Rust helper; the Qt app stays unprivileged. The launcher
uses the engine you built at `target/release/naga-macros`.

To update an existing checkout, pull the latest source and rebuild:

```sh
git pull --ff-only
cargo build --release --locked
./nagalibre
```

## Set up your buttons

The sidebar groups tasks into **Customize**, **Mouse memory**, **Scrolling**,
**Macros** and **Diagnostics**. Connection status, draft destination and the
selected mouse slot stay at the top. Changing pages keeps your edits; it does
not read or write the mouse.

Use **Customize** for the button grid and draft editor. **Mouse memory** holds
slot reading, activation, creation and backup restoration. **Scrolling** opens
the wheel editor; **Macros** opens native sequence storage and playback.
**Diagnostics** contains connection logs and the device support form.
**Save draft** only saves local edits; the separate apply/save-to-mouse button
activates them. **Stop remapping** and the Esc shortcut remain available on every page.

### Save bindings on the mouse

1. Connect the mouse by USB and choose **Mouse memory** as the draft destination.
2. Click **Connect mouse**, then select an existing slot. Use **Mouse memory → Read slots** to refresh it.
3. In **Customize**, choose a numbered button and edit its key or shortcut in the draft editor.
4. Click **Save bindings to mouse** to apply the draft to the selected slot.

Each tile distinguishes **Stored** (read from that slot) from **Draft** (your
local edits). Connecting reads stored bindings automatically. Returning to the twelve-button
plate after a swap refreshes the selected slot automatically. Reading the mouse
leaves your draft unchanged. The selected slot may be inactive; saving activates it. Saving compares all twelve draft actions
and writes only changed bindings, preserving the original bytes of unchanged
bindings. Review the entire draft before saving.

The app saves a backup before writing and reads the result back to check it.
After a successful save, it stops the helper. Saved bindings then work without
NagaLibre running.

For experimental native sequences, open **Macros → Onboard macros…** to edit playback,
inspect storage and save a fresh macro with journaled undo. Representative wired uploads, playback and desktop undo have passed physical
tests; support remains experimental, with an intermittent activation issue under
investigation. See [the macro guide](docs/MACROS.md)
for supported steps, storage limits and recovery.

To switch to a slot's stored bindings, select it in the dropdown and click
**Activate slot**. This leaves your draft and the stored bindings unchanged.
The app reads the target, backs up the target and previous active slot, then
switches and verifies the result. Selecting the dropdown or clicking **Read slots**
alone does not activate it. Activation currently requires normal device mode and
the detected 12-button plate; it refuses slots with unexpected primary clicks.

**Restore defaults** updates your draft to `1…9, 0, -, =` on the side plate,
horizontal scroll left/right on the wheel tilts, cycling wheel modes on the
scroll-mode button, and cycling DPI stages on the DPI button. Click **Save bindings to mouse** to apply these bindings to
the selected slot. Other plate drafts are preserved.
Mouse memory mode also has **Wheel tilt left**, **Wheel tilt right**,
**Scroll-mode button**, and **DPI button** tiles. Assign a key, shortcut,
or mouse-button action and click **Save bindings to mouse**. These controls default
to **Keep stored binding**, which preserves their existing firmware behavior.
**Factory default** and **Use default for this button** restore an individual
wheel control's standard function in the draft. These bindings are derived from
the official driver; horizontal scrolling in both directions, wheel-mode cycling
and DPI cycling have been physically verified over USB on one mouse and slot,
with exact original mapping restoration afterward. Software mode leaves their firmware
behavior intact; onboard macro sequences for these controls are unsupported.
The DPI binding uses the mouse's existing DPI stages; it does not change their
values. Device defaults and control definitions live in [devices/models.json](devices/models.json),
shared by the GUI and backend. See [the registry format](devices/README.md).
**Restore backup…** restores saved side-button records on the same mouse and
connection type, then activates their slot. Primary left/right click mappings
are never rewritten. The slot list shows the device-reported capacity and distinguishes initialized
slots from disabled, uninitialized entries—for example, “2 of 5 slots initialized.”
On the wired Naga V2 Pro with the 12-button plate, **Create slot** initializes the
next unused slot with factory bindings and leaves the current slot active. The
app backs up existing slots and checks the new defaults before selecting the new
slot. Your draft stays unchanged; **Save bindings to mouse** saves it to the new
slot and activates it. Creation is unavailable when all slots are initialized,
over the receiver, or without a successful fresh read. Creating the first profile
on a device with no initialized slots and deleting existing slots are unsupported.

### Run software macros

Choose **Software** for sequences such as a shortcut, a delay, and another key.
After **Connect mouse**, the attached plate is selected automatically and checked
once per second while the helper is connected. Swapping plates stops software
bindings and selects that plate’s draft; click **Apply bindings** when ready.
Use **Learn input** to identify side-button inputs, especially on the six- and
two-button plates. Learning ignores primary mouse clicks.

If detection is unavailable, the app allows manual selection. A detached or
unrecognized plate blocks Apply until a supported plate is attached. Detection
has been verified over USB. The twelve-button plate was also detected through
the receiver; receiver plate swaps and six-/two-button detection remain unverified.

Software mode needs the helper to stay running. Closing to the system tray keeps
it active; **Quit** stops it. With the window focused, **Esc** stops software
remapping and **Ctrl+Q** quits. Stopping software remapping leaves any saved
onboard bindings in place.

**Save draft** saves your edits locally without applying them to the mouse.
Drafts and backups normally live in `~/.config/NagaLibre/`, or under
`$XDG_CONFIG_HOME/NagaLibre/` if configured.

## Request device support

Have an unrecognized mouse, a faceplate detection problem, or an experimental
model to test? Open the [device support issue form](https://github.com/tylxr59/NagaLibre/issues/new?template=device-support.yml).
It includes diagnostic commands and asks for the model, connection, layouts,
and observed results. The same form appears under **New issue** on GitHub and
**Request device support…** in the app. Unrecognized and experimental devices
get a hint beside that button.

Start with this passive report, which also includes unknown Razer devices:

```sh
./target/release/naga-macros diagnose > nagalibre-diagnostics.json
```

Review the file, then attach it to the issue. It omits serial numbers and reads
metadata without sending vendor commands or capturing button presses. The app
does not upload it automatically. See the [diagnostics guide](docs/DEVICE_SUPPORT.md)
for optional faceplate and input checks and what information to include.

## Troubleshooting

- **No password prompt:** check that `pkexec` is installed and your desktop's
  polkit authentication agent is running. Run the GUI without sudo.
- **Stored: unread:** the selected slot has not been read successfully. Check
  the connection log and read it again; the draft is not the active binding.
- **Software macros produce no output:** ensure uinput is available with
  `sudo modprobe uinput`, then reconnect and apply again.
- **A software remap interferes with input:** quit the app, or use
  `sudo pkill -x naga-macros` to stop its helper. This does not undo onboard saves.
- **After unplugging or changing connections:** reconnect and read the mouse
  again. Software remapping does not resume automatically.

For a read-only diagnostic from your source build:

```sh
sudo ./target/release/naga-macros onboard-read
sudo ./target/release/naga-macros onboard-probe --slot 1
```

Diagnostic output and backups can contain your mouse serial number. Remove it
before posting output publicly.

The [command-line guide](docs/CLI.md) covers software macro configuration and
monitoring. Bugs and contributions are welcome through
[GitHub issues](https://github.com/tylxr59/NagaLibre/issues) and pull requests.

## License

NagaLibre's source is available under the [MIT license](LICENSE).
