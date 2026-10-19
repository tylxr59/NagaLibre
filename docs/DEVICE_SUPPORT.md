# Request device support or help verify hardware

Use the [device support issue form](https://github.com/tylxr59/NagaLibre/issues/new?template=device-support.yml)
for a new model, an unrecognized connection or receiver, faceplate detection
problems, or results from testing an experimental model. You can also open it
with **Request device support…** in NagaLibre. The app highlights experimental
and unrecognized Razer devices; the button remains available for other cases.
The form is also listed when you click **New issue** on GitHub.

The app prefills registry model names and USB IDs only. It opens the form in your
browser; you review and submit it yourself. Logs and diagnostics are not uploaded
automatically. An unrecognized Razer device might be a keyboard or receiver;
identify the mouse model yourself rather than assuming every interface is a mouse.

## 1. Identify the source and connection

Build the current source as described in the README, then run these commands
from the repository root:

```sh
git rev-parse --short HEAD
./target/release/naga-macros --version
./target/release/naga-macros diagnose > nagalibre-diagnostics.json
```

Attach the reviewed JSON file and paste the source revision and engine version
into the issue. If a command fails, include its error instead. Say whether your
build includes local changes. The package version alone does not identify the
source revision.

`diagnose` works for unknown Razer products and unsupported connection types.
It reads sysfs metadata, input capability bitmaps and HID report descriptors,
plus distro ID/version and kernel release. It does not open `/dev/input` or
`/dev/hidraw`, grab input, send feature reports, capture button events, or change
settings. It excludes serial/unique IDs, physical paths, hostname, local drafts,
backups and non-Razer devices. Review device names and error text before posting.

A missing descriptor is still useful information: report the error rather than
changing device permissions. No sudo is needed for the normal report. The JSON
contains a `warnings` list if a sysfs inventory could not be read.

Record the exact model/revision, side-button layout, connection type, firmware
version if already known, and what you want supported. For swappable plates,
list every physical side-button count you own. Repeat diagnostics separately
for cable and receiver if both are relevant. Bluetooth can be inventoried but
is not enabled for automatic remapping or onboard programming.

For a shorter inventory including unknown Razer products:

```sh
./target/release/naga-macros list --all-razer --json
./target/release/naga-macros models
```

## 2. Optional faceplate check

Only run this for a Naga V2 Pro identified as `naga_v2_pro` with `faceplate: true`
in the report. Other models should skip the vendor query and report the
physical layouts and app behavior instead. Pro/Trinity candidate queries remain
disabled until their transport and replies are verified.

Fully quit NagaLibre and other mouse controllers, connect one mouse, then run:

```sh
sudo ./target/release/naga-macros faceplate --watch
```

Leave each plate attached for several seconds, include a detached interval, and
write down which physical plate corresponds to each reported `module_id` and
`buttons` value. Include errors or unexpected values. On the verified wired
V2 Pro, IDs are 3 → twelve buttons, 4 → six, 1 → two, and 0 → detached.
This is an enabled read-only getter. Stop with Ctrl+C before reopening the app
so controllers do not compete for feature replies.

Report the app separately: connection type, physical plate, detected layout,
approximate delay, and whether detach/reattach was recognized. Successful getter
replies do not prove that software bindings or saved mappings work physically.

## 3. Optional side-button input and software check

Fully quit NagaLibre and other remappers first. With one recognized mouse:

```sh
sudo ./target/release/naga-macros monitor
```

For an unknown model, use only the mouse event paths listed in the passive
report. Replace `eventN` and repeat `--device` for its other interfaces:

```sh
sudo ./target/release/naga-macros monitor --device /dev/input/eventN
```

Do not select your regular keyboard. Skip this step if you cannot confidently
identify the mouse interfaces. The monitor does not grab input: side buttons
still reach the focused application. Use an empty scratch document rather than
a terminal or an application with destructive shortcuts. Do not type passwords
or unrelated text during capture.

Press each side button once and record physical position → event code and
press/release values. Values 1 and 0 mean press and release; 2 means repeat.
Stop with Ctrl+C. Repeat for each plate or connection you actually test. If a
button produces no event, report that rather than guessing its input code.

For experimental models, you may then use **Software → Learn input** in the app
and test a simple binding in a scratch document. Record the source button,
configured output and actual physical result, including normal primary clicks.
This is optional and changes only software remapping while its helper runs.
Stop remapping after the check. No onboard saves, resets or restoration are
needed for this report.

## 4. Further protocol evidence

A public Razer support/download URL or firmware version can help locate the
correct controller package. Do not upload proprietary installers or DLLs.
If you already have a focused Windows USB capture, describe its scope first;
broad captures may contain unrelated keyboard traffic.

Do not run `onboard-read` or `onboard-probe` merely to complete this form:
they contain your mouse serial number and apply only to the enabled onboard
implementation. Do not post private backups or profiles. Maintainers can ask
for a narrower follow-up once the device and missing capability are understood.
Binary research and diagnostic reports can guide implementation, but additional
hardware testing is needed to verify behavior and persistence.
