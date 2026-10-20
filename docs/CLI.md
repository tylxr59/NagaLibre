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
two processes do not compete for feature replies. Twelve-button detection also
succeeded through the receiver; other receiver plate IDs/swaps remain unverified.

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
Wheel/scroll-mode getters have succeeded on the user's wired mouse. Left
and right tilt remaps to B were physically confirmed and exactly restored.
The DPI getter returned category 6/data
[6] from wired slots 1 and 2. Scroll-mode remapping to B, USB reconnect
persistence, and wheel-mode cycling after exact restoration were physically
confirmed. Both factory horizontal tilt directions were physically confirmed
during the desktop defaults test, followed by exact original mapping restoration.
Ctrl+A, modifier release and side-button right-click output were physically
confirmed on both USB and receiver, with other tracked records/slots preserved
and exact original restoration. The receiver test also passed mouse power-off
and receiver reconnect persistence. This verifies those specific assignments,
not every supported action or receiver software-remapping behavior.

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

### Inspect Hypershift records

With the twelve-button plate attached, fully quit the GUI and run:

```sh
python3 scripts/inspect_layers.py --slot 1
```

This uses `sudo ./target/release/naga-macros onboard-layers --slot 1`, which
only sends getters. It reads the normal and secondary banks twice, checks the
plate and tracked state, and saves a private diagnostic export under the
NagaLibre config directory. Omit `--slot` to use the same selection as
`onboard-read`. Raw CLI output includes the serial; the wrapper prints action
summaries and a checksum instead.

The envelope contains `normal` (the existing snapshot with primary-click checks)
`normal_echoes` (the sixteen actual returned layer bytes for scoped normal
requests), and `hypershift` (requested layer 1 grid and auxiliary records,
`primary_inspected: false`, plus per-control `echoes`).
Secondary primary records are omitted because their getter timed out in the
first hardware attempt; their state remains unknown. Unknown encodings retain raw bytes.
This export is not accepted by Restore backup. The [desktop Hypershift flow](HYPERSHIFT.md)
uses separate paired backups and transactions. The controlled wired trial below
also implements bounded trigger/secondary writes and paired restoration. Getter
success will not prove physical hold/release behavior or persistence. See the
[protocol investigation](../inspection/HYPERSHIFT.md) for evidence limits.

Both tested connections echo layer 0 for a layer-1 request. A wired capture
established stable, distinct tilt records despite that echo. The V2 Pro layer
reader handles this bounded quirk and retains the observed echoes; ordinary
mapping reads remain strict. To collect explicitly unverified raw evidence:

```sh
python3 scripts/inspect_layers.py --probe --slot 1
```

This separately labeled, read-only diagnostic records requested/returned layers
and exact reply records, comparing them with the normal bank. It saves a private
`unverified-replies.json`; it never identifies these bytes as verified secondary
bindings and is not accepted by any save/restore path. Fully quit the GUI first.


### Controlled wired Hypershift trial

Keep USB and the twelve-button plate attached; fully quit the GUI. Begin with:

```sh
python3 scripts/hypershift_test.py prepare
```

Preparation sends getters only and saves both scoped banks of every initialized
slot, normal primary-click checks and normal middle click under the private
`hypershift-test` config directory. A parsed diagnostic export is not this backup.
Use `--directory PATH` on every stage to select a fresh trial directory.

The following stages change secondary grid 1 to B and the normal DPI button to
the traced Hypershift trigger, leaving grid 1's normal action unchanged:

```sh
python3 scripts/hypershift_test.py apply
```

With the helper exited, check grid 1's original output, hold DPI and press grid 1
for B, release DPI and check the original output again. Check left/right/middle
clicks. Unplug/reconnect USB and repeat those observations before running:

```sh
python3 scripts/hypershift_test.py verify
python3 scripts/hypershift_test.py restore
```

Check restored grid 1 output, DPI cycling and primary clicks afterward. Report
physical results separately; readback alone cannot prove hold/release behavior.
If apply fails, keep backups and run restore instead of repeating apply. The
runner journals attempts and fsyncs recovery data before acknowledging a commit.
Changing the engine or runner after preparation invalidates the saved trial.

This initial writer requires wired 00a7, an active slot in normal mode and the
twelve-button plate. It does not activate slots or change device mode. Receiver
layer writes remain unverified. Wired physical held/release, primary clicks, USB
reconnect and exact paired restoration passed. The GUI now restores paired and
legacy normal-only backups with their respective scopes.

Session clients use `onboard_layers_read` (`slot` optional),
`onboard_layers_prepare` (`edits`: objects with `layer` 0/1 and `action`), or
`onboard_layers_restore` (`backup`: paired envelope). Preparation returns
`onboard_layers_prepared` with a backup covering all initialized slots and a
one-shot token. Durably persist and fsync that backup before `onboard_commit`;
success returns `onboard_layers_saved` with the paired target snapshot. The
`hypershift_transactions` hello capability advertises the wired path. Existing
normal-only commands and backups retain their meaning.


If a failed layer trial reports a normal request echoing layer 1, restoration is
not verified. Do not retry apply or overwrite its backups. Release all buttons,
reconnect USB, and try the saved trial's restore stage first. Keep its original
release helper and runner unchanged because their checksums bind the saved plan.

For read-only recovery evidence if strict restore still fails, build the **debug**
helper (`cargo build --locked`, without `--release`) and run:

```sh
python3 scripts/inspect_layer_recovery.py
```

This separate script uses `target/debug/naga-macros onboard-selector-inspect`.
It double-reads the active slot's three normal primary records and sixteen scoped
controls for each selector, retaining actual returned selectors and raw bytes.
It checks identity, plate, inventory and mode stability and compares observations
with the saved trial backup. It writes only a new private evidence file; it does
not write mouse settings, change the trial files or claim restoration/bank identity.
Other slots are not captured. Pass `--directory PATH` for a nondefault trial.


When selector evidence shows the specific slot-1/grid-1 echo mismatch while all
observed action bytes match the original backup, use the guarded recovery:

```sh
python3 scripts/recover_layer_echo.py
```

It selects the latest private selector capture (or `--evidence PATH`), checks it
against fresh reads and the all-slot paired backup, saves durable recovery data,
and sends one original normal-bank grid-1 record. It never applies a new
Hypershift action. The helper verifies both banks and normal primary clicks in
all backed-up slots exactly before reporting restoration. This can take about
30 seconds. If it fails, keep its journal and collect new selector evidence;
do not repeat recovery. After success, check grid 1, DPI cycling and primary
clicks before and after USB reconnect. Physical observations remain separate
from the verified stored records. Keep the original release helper unchanged.


### Automatic secondary-write diagnostic

After a previous trial is fully restored, the narrower protocol diagnostic is:

```sh
python3 scripts/probe_layer_write.py
```

Use USB, the twelve-button plate, active slot 1 and normal mode; close the GUI.
The script uses the debug source build (`cargo build --locked`). It saves a fresh
private paired backup for all initialized slots, writes secondary grid 1 = B,
observes both requested selectors twice, and restores the exact original
secondary and normal grid-1 records before the helper exits. No Hypershift trigger
is assigned. It prints only the grid-1 observations and restoration summary;
full evidence stays in the private `layer-write-probe` config directory.
Allow roughly a minute including backup preparation. This tests stored-record selection, not physical
hold/release behavior. Check original outputs and primary clicks afterward.

Do not repeat `run` in that directory. If interrupted or restoration is unverified,
keep all backups and use the restoration-only continuation:

```sh
python3 scripts/probe_layer_write.py restore
```

Pass the same `--directory PATH` to both stages for a custom directory. Restoration
requires the original attempt journal and refuses changed identity or unrelated
tracked state. It does not write B again. Keep the helper and runner unchanged
until the attempt is restored; their hashes bind the saved probe plan.


A successful isolated wired write probe confirmed selector-1 B with selector-0
key 1 unchanged while both replies reported layer 1. The paired snapshot therefore
retains normal-request echo metadata separately from action records. Wired paired
control reads accept 0/1 and compare the actual values across reads; primary and
normal-only reads remain strict. Receiver normal reads retain their earlier policy.
Changed-control tag values are verified after saves and restored exactly from the
paired backup. This may require replaying an unchanged original normal record.
The wired GUI now uses paired snapshots. Keep it closed while running controlled
trials, and restore those trials before starting unrelated desktop edits.
Use a fresh `--directory ~/.config/NagaLibre/hypershift-held-test` for all stages;
completed earlier plans and their helper checksums must not be reused.


### Desktop Hypershift verification and protocol additions

See [the desktop guide](HYPERSHIFT.md) for UI editing and the getter-only
`check_hypershift_gui.py prepare|staged|saved|restored` sequence. This independent
checker verifies all initialized slots and normal primary/middle records. GUI
profile schema v2 adds sixteen secondary drafts; v1 migrates without writing
files on load or changing settings. Secondary defaults preserve stored actions.

`onboard_layers_restore_normal` accepts a legacy normal `Snapshot`, prepares an
all-slot paired recovery backup and restores only its normal records. Fresh
secondary actions are preserved exactly. It uses `onboard_layers_prepared` and
`onboard_layers_saved`, with the existing durable-backup/token handshake.

After a wired paired read, `onboard_activate` prepares
`onboard_layers_activation_prepared` with an all-slot paired backup and token.
`onboard_commit` then returns `onboard_layers_activated`. Both banks and actual
echoes are checked for all initialized slots; activation writes no mappings.
Paired slot creation adds `paired_backup` to `onboard_creation_prepared`; save
both it and the original allocation backup before acknowledging the token. The
allocator still requires zero normal tags and refuses configured Hypershift
states before allocation. Existing secondary banks are verified after allocation
and cleanup. Receiver and legacy protocol paths retain their earlier behavior.

## HyperScroll Pro standard modes

Use **Wheel settings…** in the GUI for Standard, Distinct, Ultra-fine, Adaptive
and Smooth Scroll. Wired Naga V2 Pro and its twelve-button plate are required.
The dialog supports enabled cycle order, active mode, draft-only defaults and
stage-backup restoration. It preserves existing Custom curves/metadata and
button bindings. See [the desktop wheel guide](WHEEL.md).

The JSON-lines helper supports `haptic_read`, `haptic_prepare`, `haptic_commit`
and `haptic_restore` for stage selection/order only. A prepare response supplies
a backup and token; the unprivileged caller must atomically save, fsync and read
back the backup before acknowledging the token. Do not confuse a local draft
with the mouse's active settings. A failed read invalidates stored values.

### Read-only inspection

```sh
sudo ./target/debug/naga-macros haptic-read
python3 scripts/inspect_haptic.py
python3 scripts/inspect_haptic.py --firmware-version
python3 scripts/inspect_haptic_views.py
python3 scripts/backup_haptic_independent.py
```

The scripts retain private paired-mapping checkpoints and compare reported state.
They send no settings writes. Firmware reports major/minor only; patch is unknown.
Stored-profile CCW/velocity table replies can alias the CW table. Selector-zero
views retain subtable offsets but can expose flash rather than uncommitted cache.
Editor metadata describes intent, not proof of actual curves. Inactive metadata
may explicitly reject reads and remains unknown. These exports are not full
firmware images or substitutes for stage transaction backups.

Close other mouse controllers first. If OpenRazer is running as the user service
`openrazer-daemon.service`, this Bash wrapper temporarily stops it and starts it
again on exit; it also works when pasted into fish:

```sh
bash -c '
trap "systemctl --user start openrazer-daemon.service" EXIT
systemctl --user stop openrazer-daemon.service || exit
python3 scripts/inspect_haptic.py --firmware-version
'
```

Use that wrapper only when the service was running beforehand; preserve its prior
state otherwise. Close Polychromatic too. Strict command/echo/checksum matching
remains enabled; an unrelated reply is not accepted as a response. Full paired
and wheel sweeps can take tens of seconds because each HID exchange waits before
polling and state is read repeatedly. Progress output identifies the current phase.

### Controlled standard-mode tests

Close the GUI before these trials. Each backs up current state before writes,
collects physical observations and restores the captured stage list/selection:

```sh
python3 scripts/haptic_test.py guided
python3 scripts/haptic_test.py trial --position 1
python3 scripts/haptic_test.py trial --order 85 81 --position 2
```

Order arguments are hexadecimal preset IDs; position is one-based within that
list. These are stage-only operations. Hardware observations cover all five
named preset feels/cycling and explicit Standard/Ultra-fine/reordered-list USB
persistence. The desktop flow is implemented and covered by automated Qt tests;
it has not had a separate physical GUI trial.

After any interruption, read the printed private directory's `plan.json`. Use
only the same helper and that trial's recovery route if restoration is pending:

```sh
python3 scripts/haptic_test.py restore --directory /path/to/pending/trial
```

Keep the twelve-button plate attached. Do not rebuild the helper during an
outstanding trial. Readback does not prove physical feel, click output or USB
persistence; record those observations separately.

### Deferred Custom research

Custom editing is not available. The historical `haptic-table-probe`,
`haptic-upload-replay`, `haptic-independent-replay` and
`haptic-unit-velocity-trial` CLI apply routes are blocked before file/device
access. Their `--restore` routes remain for existing matching private journals;
do not start new Custom trials. Research scripts and fault tests are retained
for future work, not as a supported editing API.

The unchanged replays acknowledged transfers and matched existing visible data,
but changed velocity uploads read back unchanged. A separate save/flash gate is
still unresolved. Unknown pre-replay originals cannot be reconstructed from
aliased backups; neither host defaults nor another slot's curves are an assumed
original. See [protocol findings](../inspection/HAPTIC_WHEEL.md) and
[firmware findings](../inspection/HAPTIC_FIRMWARE.md). Custom work is deferred;
TODO #4 is next.
