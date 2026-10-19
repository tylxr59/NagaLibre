# NagaLibre

<p align="center">
  <img src="assets/nagalibre-hero.png" alt="Naga Libre project artwork" width="420">
</p>

**Your Naga. Your buttons. Linux native.**

NagaLibre is a free and open-source reimplementation of the Razer Naga side-button
system for Linux. It lets you bind the thumb buttons to keys, shortcuts, and
macros through a Qt desktop app, with a Rust engine handling the mouse.

The current focus is the **Razer Naga V2 Pro**. You can save supported bindings to
the mouse's onboard memory so they keep working after you close the app, or use
software mode for macro sequences. NagaLibre works independently of Synapse and
OpenRazer. It is an independent project, unaffiliated with Razer.

## What works today

| Feature | Support |
| --- | --- |
| 12-button plate | Main development and testing target |
| Onboard key bindings | USB save, app exit/reconnect persistence, and exact backup restore tested on one mouse and slot |
| Onboard shortcuts and mouse-button outputs | Implemented; physical testing still needed |
| Software keys, shortcuts, and macro sequences | Available while the background helper runs |
| 6- and 2-button plates | Manual selection and input learning in software mode; physical testing still needed |
| 2.4 GHz receiver | Recognized; onboard behavior still needs testing |
| Bluetooth onboard programming | Unsupported |
| Automatic plate detection, new onboard slots, DPI, and RGB | Not implemented |
| Multi-step macros stored on the mouse | Not implemented; use software mode |

This is a project under active development. Start with the USB cable and the
12-button plate for the best-tested setup.

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

### Save bindings on the mouse

1. Connect the mouse by USB and choose **Mouse memory**.
2. Click **Connect mouse** / **Read slots**, then select an existing slot.
3. Choose a numbered button and edit its key or shortcut in the draft editor.
4. Click **Save 12 bindings to mouse** to apply the draft to the selected slot.

Each tile distinguishes **Stored** (read from that slot) from **Draft** (your
local edits). Reading the mouse leaves your draft unchanged. The selected slot
may be inactive; saving activates it. Saving compares all twelve draft actions
and writes only changed bindings, preserving the original bytes of unchanged
bindings. Review the entire draft before saving.

The app saves a backup before writing and reads the result back to check it.
After a successful save, it stops the helper. Saved bindings then work without
NagaLibre running.

**Reset 12 buttons** restores `1…9, 0, -, =` in the selected slot.
**Restore backup…** restores saved side-button records on the same mouse and
connection type, then activates their slot. Primary left/right click mappings
are never rewritten. Only existing slots can be edited.

### Run software macros

Choose **Software** for sequences such as a shortcut, a delay, and another key.
Select the attached plate manually; use **Learn input** to identify side-button
inputs, then **Apply bindings**. Learning ignores primary mouse clicks.

Software mode needs the helper to stay running. Closing to the system tray keeps
it active; **Quit** stops it. With the window focused, **Esc** stops software
remapping and **Ctrl+Q** quits. Stopping software remapping leaves any saved
onboard bindings in place.

**Save draft** saves your edits locally without applying them to the mouse.
Drafts and backups normally live in `~/.config/NagaLibre/`, or under
`$XDG_CONFIG_HOME/NagaLibre/` if configured.

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
