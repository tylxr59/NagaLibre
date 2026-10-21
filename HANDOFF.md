# NagaLibre development handoff

Read [AGENTS.md](AGENTS.md) for standing instructions. User setup is in
[README.md](README.md); CLI usage is in [docs/CLI.md](docs/CLI.md).

## Macro assignment sizing and long-save feedback (2026-10-21)

Follow-up: the embedded macro panel retained the global QDialog background
(`#222222`) inside the assignment group's `#252525` background. Scoped its
background to transparent; offscreen pixel samples now match the surrounding
pane. Standalone dialogs retain their existing styling. Embedded workspace tests
and whitespace checks passed.

The user reported a failed macro save with a greyed UI, then clarified that it
completed after a very long wait. This is a user-reported completion, without
separate physical playback or persistence evidence. Inspection confirms that
prepare and commit perform repeated recovery/stale-state and final readbacks;
this change does not reduce those checks or claim a latency improvement.

The inline macro form now explicitly grows fields across desktop styles, giving
the saved-macro selector the available width and its full name as a tooltip.
Operation feedback lives in the workspace footer with an activity indicator,
read/backup/save-verification phases, elapsed time, and notice that mouse checks
can take several minutes. During the operation, the stored-binding label explains
that assignments will refresh when it finishes. Standalone macro tools also get
elapsed/phase feedback. Timers stop on completion, error and disconnect; controls
remain locked during the transaction. No forced timeout or protocol change.

All 216 Python/Qt tests and whitespace checks passed, including desktop-style
selector geometry, phase transitions, elapsed display and success/error cleanup.
Idle/busy offscreen views were inspected. No live mouse access was performed.

## Missing button assignment dropdown (2026-10-21)

Reproduced the user's missing Action dropdown with a Qt style reporting
`FieldsStayAtSizeHint`: the combo's Ignored horizontal size policy gave it zero
width. The assignment form now explicitly uses `AllNonFixedFieldsGrow` so the
dropdown fills the available field width across desktop styles. A regression
uses that style hint and checks visible geometry and keyboard assignment edits
in both destinations at normal/minimum window sizes and multiple grid positions.
All 215 Python/Qt tests and whitespace checks passed; the corrected dropdown was
also inspected in an offscreen render. No hardware/protocol behavior changed and
no live mouse test was performed. Restart the GUI to load the Python change.

## Macro table control geometry (2026-10-21)

The user's desktop still reported dropdown/text overlap after the first column
size-hint override. The shared macro editor now uses a fixed action-column resize
mode and explicitly measures polished dropdowns when adding rows, showing the
view and changing fonts/styles. It no longer relies on ResizeToContents to honor
embedded widget width. The existing row-height sizing remains. A table-owned
single-shot timer handles deferred restyling and is cancelled on destruction.
Geometry regressions exercise a header-only width hint, hidden insertion/show,
editing/focus changes and larger fonts. All 214 Python/Qt tests passed without Qt
callback errors; whitespace checks passed. No engine rebuild or protocol change.

## Explicit macro folder controls (2026-10-21)

Replaced the editable Folder dropdown with a read-only Location label. New folder
sits beside New macro; folders, including empty ones, are visible in the library
tree. Selecting a folder or Uncategorized sets the destination for New macro without
moving or discarding the sequence currently being edited. A macro's context menu
offers Move to folder; the move stays in its draft until Save macro.

The version-1 catalog now accepts an optional folders array and derives folders
from legacy macro entries. Empty folders survive reopen and deleting their final
macro. Atomic writes, conflict checks, existing entry identities and firmware
assignment behavior remain unchanged. Folder creation/cancellation, legacy
migration, selected-folder creation, searching, unsaved-draft preservation and
saved/discarded moves are covered by the Python/Qt suite. No hardware behavior
changed.

## Device layout and inline assignment pass (2026-10-21)

The user flagged that Macros was a launcher for another window and that macro
assignment was detached from the selected grid button. They explicitly requested
actual Synapse 4 binary inspection and closer organization across the supported UI.
Re-read the retained `app-engine.exe`/ASAR package and embedded production routes;
followed the dashboard's product-window URL to the actual **Device167 Naga V2 Pro**
frontend. Inspected its main JS/CSS, lazy ButtonPanelComponent, shared drawer chunk
and device-specific MapMacro chunk. Hashes, route provenance, state/property and
CSS anchors, corroboration and limits are in
[inspection/SYNAPSE4_LAYOUT.md](inspection/SYNAPSE4_LAYOUT.md). Payloads remain ignored.
No Windows code, downloaded frontend code or hardware requests were executed.

The sidebar now groups Mouse, Macros and Diagnostics. Mouse has local Customize,
Scrolling and Mouse memory tabs sharing a device/slot bar. The assignment pane is
left of the physical grid. Colors/selection accents follow the inspected neutral
dark/green styling; branding remains independent. Unsupported Razer features and
proprietary artwork/fonts are not introduced. Macros contains the persistent
library/event editor itself (`gui/macro_library_view.py`), with no launcher or
Key Binds window; the previous `gui/macro_workspace.py` is removed. Navigation keeps
unsaved authoring; switching library entries or quitting handles Save/Discard/Cancel.

Macro is available directly on supported hardware grid/extra-control assignments
and on software buttons. `gui/macro_assignment.py` selects the saved library entry
and playback for the already selected button/layer. Native Save reads storage then
prepares the existing fresh-upload transaction; no duplicate target selector or
manual read-before-save step. The selected active slot must still match readback.
Unsaved library changes are never uploaded. Firmware assignment remains separate
from the ordinary key-binding draft/writer; a successful upload makes that button's
ordinary draft Keep stored so a later bulk save preserves it. Main tiles receive
actual final paired readback and retain it through the intentional helper exit.
Software Use macro copies the saved steps into that button's software draft, with
once-per-press playback. No new firmware macro modes/editing/deletion are implied.

Scrolling now embeds `WheelPanel` rather than launching another window. Its
existing stage transaction is unchanged. Macro inventory/undo and wheel backup
restoration are under Mouse memory; expanded details remain optional. Embedded
panels borrow the shared helper only while busy, block conflicting navigation/
close, restore ownership on completion/failure and stop the helper on successful
firmware save/undo. Disconnect/error clears a pending macro upload so a later
inventory read cannot accidentally resume it. Library navigation sends no helper
requests and leaves software output alone.

All 208 Python/Qt tests passed, including new embedded navigation, saved-version
software/native assignment, selected Hypershift/DPI-control targeting, private
backup-before-commit, stale active slot, backup failure, disconnect cancellation,
quit cancellation and inline wheel ownership/deferred refresh. Existing persistence,
protocol-fixture, transaction/rollback and shared-helper tests remain covered.
Offscreen normal/minimum-size views were inspected; the library retains visible
save controls at 920x640, with its own event/tree scrolling. Whitespace checks
passed. Rust/device protocol is unchanged. No live mouse testing was performed.

## Persistent macro library and separate assignment (2026-10-21)

Implemented the Synapse 4 research direction in `gui/macro_library.py` and
`gui/macro_workspace.py`. The main Macros launcher now opens My Macros offline:
named sequences, searchable folder tree, folder selection/creation through an
editable Folder field, rename through Name, duplicate, local deletion, inline
editing, Save and Discard. Switching entries or closing with edits offers Save,
Discard or Cancel. A selected button's existing macro draft seeds an unsaved item.

The versioned local catalog is `macros.json` beside the base `profiles.json`,
shared across device profiles. Writes use atomic replacement and file/directory
fsync, with a file lock and stale-file comparison to avoid overwriting another
window. Invalid/future catalogs are left untouched and disable local writes.
Key Binds selects a saved catalog entry independently of unsaved editor changes;
button/layer/playback apply to a fresh upload through the existing transaction
implementation. Editing/deleting catalog entries never rewrites existing firmware
allocations. On mouse inventory and Undo upload remain separate tools. No
recorder, import/export, arbitrary firmware editing/deletion or USB performance
parity is implied.

Opening/closing local authoring does not start/read the helper or stop running
software remaps. Read mouse is explicit in Key Binds; authentication reuses the
shared helper when available. Hardware access still stops software output and
invalidates main-window readback on return. Upload/undo preserves the existing
backup-before-commit contract and ends the helper on success. Main Apply stays
disabled while the modal workspace owns helper events.

All 200 Python/Qt tests passed, including reopen/rename/duplicate/delete,
atomic-write failure, corrupt/future/stale catalog preservation, offline helper
isolation, unsaved cancellation/discard, saved-version assignment, shared helper
lifecycle and backup-before-commit regressions. Offscreen renders checked both
views at normal and minimum sizes; whitespace checks passed. Rust and device
protocol behavior are unchanged. No live mouse operation was performed.

## Actual Synapse 4 macro UI follow-up (2026-10-21)

The user explicitly corrected the Synapse 3-only research and requested actual
Synapse 4 inspection. The retained App Engine 4.0.827 ASAR identifies the Synapse 4
host and its served dashboard route. Traced its live Webpack mapping chunks to
the distinct `/synapse/macro/` frontend and statically inspected the current
authoring, key-bind, assignment and CSS bundles. The macro route's Last-Modified
was 2026-10-21 04:26:42 GMT. Full provenance, hashes, routes, component/action
anchors and the NagaLibre comparison are in
[inspection/SYNAPSE4_MACRO_UI.md](inspection/SYNAPSE4_MACRO_UI.md).

Synapse 4 has separate My Macros, Key Binds and Help views. My Macros is a named
host-side library with folders and an event editor; assignment selects an existing
macro plus playback. The repetition field is conditional. The recent NagaLibre
two-panel redesign matches the latter detail but still combines single-draft
authoring with fresh onboard upload; it does not implement a reusable macro
library. Next design direction is a persistent local catalog and separate
assignment, retaining inventory/recovery as tools. Do not claim that adding a local
library enables arbitrary existing-allocation editing/deletion or that frontend
code proves native firmware behavior/performance.

This follow-up changed research docs only. Verified artifact hashes, source
references and local links; no Windows/frontend code execution, mouse requests or
runtime changes. Existing user edits and the prior GUI redesign were preserved.

## Macro editor organization (2026-10-21)

The user requested a macro-menu cleanup guided by binary inspection. Direct
metadata/CIL analysis of the retained official Synapse 3 shared UI assemblies
confirmed separate authoring/assignment concerns and repeat-count visibility only
for counted playback. Provenance, method RVAs, limits and design interpretation
are in [inspection/MACRO_UI.md](inspection/MACRO_UI.md). The configured Ghidra
project was locked and left untouched; managed IL was inspected directly. Do not
claim this establishes current Synapse 4 screens or its firmware behavior.

The onboard macro window now pairs an inline sequence editor with a compact
button/layer/playback assignment panel. Stored inventory and diagnostics/support
notes are behind On mouse and Details controls. Repeat count and the toggle stop
hint are contextual. `gui/macro_editor.py` is shared with the existing software
macro dialog; no new recorder, existing-macro editing or deletion is implied.
Local form errors retain readback so correcting input does not trigger another
mouse scan. Shared helper ownership, fresh-upload planning, durable backups,
journals, scoped undo and hardware failure invalidation remain unchanged.

Qt tests explicitly destroy closed standalone macro windows before QApplication
teardown; the inline table exposed a shutdown crash when tests left Qt objects
alive until interpreter cleanup. Offscreen renders were checked at normal and
minimum window sizes. All 192 Python/Qt tests passed, including inline editing,
contextual playback fields, local-error correction, shared helper lifecycle and
backup-before-commit regressions. Whitespace checks passed. Rust behavior is
unchanged. No live mouse operation was performed for this UI change.

## Editor read performance (2026-10-21)

The user clarified that runtime latency, rather than transparent diagnostic text,
is the priority and wants responsiveness comparable to Synapse. Opening Macros
previously used the full diagnostic path: two complete bank reads per slot,
followed by another complete sweep of those repeated reads, plus duplicate macro
contents. Each transport exchange currently waits at least 30 ms before polling.

GUI session `macro_read`, `haptic_read` and `onboard_layers_read` now use single-pass
display readers and return `preview: true` alongside the existing snapshot shape.
Getter address/length/resource/echo validation and surrounding identity/plate
checks remain. These views are never accepted directly as recovery checkpoints:
save preparation still captures and verifies fresh full backups, and commit
continues strict stale-state comparison and exact-wire recovery. Standalone CLI
diagnostic/inspection paths retain their repeated reads. Macro freshness checks
reuse the exact paired mapping readback from their full inspection instead of
starting another redundant sweep; middle clicks still get independent comparisons.

The GUI defers background assignment reads while Macros, Scrolling or Diagnostics
is visible. Connecting, faceplate notifications and closing an editor no longer
force an unseen assignment refresh. Entering Customize/Mouse memory loads missing
state once and does not duplicate an in-flight request. Drafts remain separate and
saving stays disabled without applicable readback. Only the now-inaccurate
"reading twice" status text changed; the broader copy cleanup was dropped after
the user's clarification.

Measured getter counts in deterministic fixtures (not physical timings):

| Operation | Previous | Current |
| --- | ---: | ---: |
| Macro display, two slots, empty inventory | 331 | 92 |
| Button layer display, one slot | 78 | 40 |
| Wheel display, standard mock data | 33 | 19 |
| Macro freshness check, two slots, one entry | 503 | 347 |

Validation: 180 Rust and 190 Python/Qt tests passed, including display/inspection
equivalence, getter counts, malformed payload rejection, changed-plate rejection,
stale preview refusal before layer/macro/wheel writes, middle-click freshness,
failure/rollback/recovery and deferred GUI reads. Formatting, Clippy with warnings
denied and debug/release builds were checked. No live mouse request or timing
comparison with Synapse was performed; request reductions are not measured wall
time or a claim of parity. Restart the app to use the rebuilt release engine.

## Shared GUI authentication helper (2026-10-21)

Button assignments, native macro storage and wheel settings now reuse the main
window's Backend/QProcess. Modal editors borrow the connection rather than
shutting it down on entry or ordinary close. Their initial read commands already
stop the software worker in the engine. No new protocol or firmware request was
added. Standalone dialogs still own their helper by default.

The main window defers event handling and connection initialization while an
editor owns the session, retaining the latest faceplate event for return. Closed
editors explicitly disconnect their event/log/connection handlers. Returning to
hardware assignments invalidates prior snapshots and requests fresh readback;
software remapping stays stopped. Main-window close and tray Stop cannot interrupt
an editor transaction. Durable backup failure still closes the helper without
acknowledging a commit. Successful onboard save/undo still ends the engine session;
the GUI does not start a replacement automatically. Reconnecting then may require
authentication again, as before.

Validation: 189 Python/Qt tests passed, including a real QProcess bridge to a
simulated helper that records one process across Connect → Macros → Scrolling →
assignments, exclusive event handling, fresh reads and draft preservation.
Additional regressions cover borrowed close/detach, busy close, disconnect,
backup failure and no automatic reconnect after successful saves. No live mouse
writes or desktop authentication tests were performed. The user should restart
the GUI to exercise the changed Python code; Rust behavior is unchanged.

## UI workspace refresh (2026-10-21)

The Qt window now uses persistent sidebar navigation: Customize, Mouse memory,
Scrolling, Macros and Diagnostics. Device connection, status, draft destination
and slot selection stay visible; slot management/recovery and session logs no
longer crowd the binding editor. Local draft saving and mouse/software application
remain separate actions on Customize; Stop remapping remains global. Hardware
mode hides the software-only input-learning row. Support hints mark Diagnostics.

Organization was informed by the device/profile context and separate Customize
and Scrolling areas in Razer's official
[Naga V2 Pro guide](https://dl.razerzone.com/master-guides/RazerSynapse3/NAGAV2PRO-00000167-en.pdf).
NagaLibre's wheel and native macro editors retain their existing backup/commit
boundaries; the new pages launch those editors. Their originally independent
helper sessions are superseded by the shared connection described above.
Sidebar navigation preserves drafts and refreshes missing assignment state when
needed, as described above. Presentation helpers and
theme live in `gui/workspace.py`; transaction behavior remains in existing modules.

Validation: all 184 Python/Qt tests passed using the available system PySide6 and
debug engine, including navigation/draft preservation, no-command navigation,
fresh-read save gating and small-window scrolling. Offscreen renders of all five
pages were inspected during development. No live mouse writes or desktop physical
validation were performed for this UI change. Existing hardware evidence and
limitations below still apply.

## Current checkpoint and next chat

**Current work is TODO #4: onboard macros and richer playback.** Software
implementation now includes the native compiler/planner, journaled fresh uploads,
readback-before-binding, original-only recovery and a dedicated Qt dialog with
inventory, playback controls, durable backup and undo. Hardware testing resumed
on 2026-10-21: a small B/wait timeline passed wired upload/readback, once playback,
counted playback at 3, held repetition and toggle start/stop, primary clicks,
USB-reconnect persistence and exact scoped cleanup. The held trial's saved wording
does not explicitly describe cessation on release; no failure was reported.
Sequence mode progressed B, C, silent, B across taps on the tested fixture.
The repeated Shift+B/C shortcut passed immediate output and explicit modifier
release. The desktop save/app-exit/playback/undo flow also passed per the user's
physical observations. Mouse outputs, explicit power-cycle persistence and other
target/layer combinations remain unverified. Custom haptic implementation remains deferred; static research below
is separate. No macro allocation is currently pending cleanup. The first shortcut trial failed
immediate playback but worked after USB reconnect; investigate the open issue below
before declaring #4 complete.

## Macro hardware trial: readback and recovery passed (2026-10-21)

The user resumed testing and ran `macro_controlled_test.py --readback-only`.
The fresh upload and nonempty metadata/data readback matched the independently
saved plan; binding apply completed. Inventory changed from zero to one entry
(ID 15672), slot 1 active, scoped slots [1, 2, 3]. Physical output was not tested.
Recovery failed during a guarded normal-bank getter for grid 6 (wire45): expected
02/8c, but the last valid reply was 07/80 with matching transaction1f. Cleanup
is unconfirmed; do not create another upload until recovery succeeds.

Private durable evidence and helper-owned journal remain under
`~/.config/NagaLibre/macro-trial-1792587462502048157/`. No new hardware requests
were sent by the agent. A local OpenRazer daemon was still running; the agent
stopped it cleanly using `openrazer-daemon --stop`. This is a plausible source of
the conflicting reply, not a proven cause. The agent has no passwordless sudo.
The user then ran the existing journal's `--restore` route successfully. Saved
`recovered-1792588081253632500.json` independently matches the original entries
(zero), scoped paired mappings/echoes, identity/state and active slot 1. The helper
also verified normal middle clicks. Fresh upload, nonempty getter fidelity for
this small sequence, binding readback and scoped recovery now have wired evidence.
Free/reclaimable accounting is not treated as an exact flash restore. Physical
playback/release, reconnect and power-cycle persistence remain unverified.
Keep OpenRazer and other controllers stopped for subsequent trials. Next is the
interactive `--playback once` trial, followed by counted/held/toggle modes if it
passes. The earlier deferred/empty-inventory-only statements are superseded by
this hardware evidence; no physical behavior should be inferred from it.

The subsequent interactive once-playback trial passed. The user observed the
expected output/release ("It works"), unchanged primary clicks ("All good") and
USB-reconnect persistence ("It persisted"), after the upload helper had exited.
Private evidence: `~/.config/NagaLibre/macro-trial-1792588281357273198/`.
The agent independently compared `recovered.json` against `before.json`: original
entries (zero), scoped paired records/echoes and identity/state match. This verifies
one small B/wait timeline in once mode on wired slot 1, normal grid 1. Other
playback modes and explicit power-cycle persistence remain pending. Next: counted
playback with count 3, then while-held and toggle if earlier trials pass.

Counted playback with count 3 also passed: the user observed "three distinct b
presses", primary clicks "all good" and "persistence worked" after USB reconnect.
Private evidence: `~/.config/NagaLibre/macro-trial-1792588752745467832/`.
The agent independently compared recovered contents/scoped paired mappings,
echoes and guard against the original checkpoint; original inventory is zero.
Evidence covers count 3, not every count or physical timing bounds. Next is
while-held repeat/release, then toggle. Sequence semantics and explicit
power-cycle checks remain pending.

While-held playback trial completed with exact recovery to zero entries and
original scoped paired mappings/echoes/guard, independently compared by the agent.
Private evidence: `~/.config/NagaLibre/macro-trial-1792589780645868451/`.
User observations: "a press of 1 gives one b, 1 held keeps outputting b as expected";
primary clicks "good"; "All good with reconnect". The test instructions included
release/stop checks and the user reported no failure, but the saved wording does
not explicitly describe cessation on release. Keep that distinction if a specific
release guarantee is needed. Next: toggle start/stop with explicit silence/no stuck
key observations. Sequence and explicit power-cycle checks remain pending.

Toggle playback also passed: user observed "starting and stopping the repition
works as expected", primary clicks "all good" and "reconnect works". Evidence:
`~/.config/NagaLibre/macro-trial-1792590946861708309/`. The agent independently
compared recovered entries (zero), scoped paired mappings/echoes and guard against
the original. Next is sequence: the trial script now uses distinguishable B then
C taps in that mode and requests per-press observations without assuming firmware
advancement semantics. Other modes retain the same original B/wait fixture.

Sequence mode trial passed readback, primary clicks, USB-reconnect persistence
and exact scoped cleanup (zero original entries). The B/wait/C/wait fixture
produced user-observed `b`, `c`, no output, then `b` on four separate taps.
Do not label the third silent press a failure or infer its cause yet. This
establishes press-wise progression for this fixture, not arbitrary segmentation.
Evidence: `~/.config/NagaLibre/macro-trial-1792591645384056043/`; agent independently
compared recovered contents/scoped paired mappings/echoes/guard with the original.
The controlled trial now has `--timeline shortcut` (once only): Shift+B, wait,
unmodified C. It requests `Bc` plus a manually typed lowercase d to check modifier
release. Next is that richer native timeline before desktop physical validation.

### Open macro issue: shortcut inactive until USB reconnect

The first shortcut trial (`--playback once --timeline shortcut`) did not produce
output before reconnect. After USB reconnect, the same uploaded timeline emitted
`Bc`. Primary clicks remained good. The user did not explicitly record the manual
lowercase-d modifier-release check. This is a failed immediate-activation test,
not a clean shortcut pass; do not describe richer timelines as hardware verified.
Private evidence: `~/.config/NagaLibre/macro-trial-1792593193440314779/`.
The agent independently verified exact uploaded metadata/data against the plan,
then original zero entries, scoped paired mappings/echoes and guard after recovery.
Metadata event count is 10; bytes 120..131 are zero, as in the prior small fixtures.
No OpenRazer process was running at investigation time. No allocation is pending.

Matching wired DLL/hash was reconfirmed through GhidraMCP. Rechecked SetMacroData
RVA58810, queue wrapper247c0 and upload routine2f020: the examined successful path
allocates, writes metadata, uploads data chunks and returns; no additional finalize
request was found in those routines. This does not establish that broader device
lifecycle handling is irrelevant. No guessed flush/reset/mode request was added.
Possible live playback/cache/transition behavior is a hypothesis, not established
cause. Next diagnostic is the same shortcut fixture with multiple pre-reconnect
presses and a delayed retry, then explicit output and modifier-release observations
before and after reconnect. Keep exact undo and ownership rules intact.

The repeated shortcut fixture passed immediate playback: user observed `Bc` and
manual D-key input yielded lowercase `d`; primary clicks and USB reconnect also
passed. Evidence: `~/.config/NagaLibre/macro-trial-1792593866545586390/`. The agent
independently verified original zero entries, scoped mappings/echoes and guard
from recovered.json. This establishes working modifier/chord output and release
for this run, but does not explain or erase the first run's activation failure.
Treat it as intermittent/unresolved until its cause is established. No allocation
is pending. Next is the desktop physical save/app-exit/undo flow using a single B
tap and its automatically created private journal.

### Desktop macro physical trial passed

The user completed the prescribed desktop list and reported "Everything worked
as expected": wired slot 1, Grid 1 / Normal / Once, one B tap, private backup and
journal creation, successful save, full NagaLibre exit, physical B output and
primary clicks, then reopening and journal-based Undo upload. This is user-reported
physical GUI evidence, distinct from mock Qt checks. The agent confirmed the
private GUI backup exists (0600), captures zero baseline entries and the intended
target/playback, and has a corresponding helper-owned journal. The journal is
protected and not readable by the unprivileged agent; do not claim an independent
post-GUI inventory read or journal audit. The UI's successful undo reports the
engine's scoped recovery verification, and no cleanup failure was reported.

Representative #4 software and desktop functionality are now physically exercised.
Keep the first intermittent shortcut activation failure open; its successful
retest is not a fix. Remaining coverage includes explicit power cycling, native
mouse outputs, broader targets/layers, existing shared content and more timing/
sequence boundaries. No new live hardware request was sent by the agent here.

## Custom wheel Ghidra follow-up

The user requested more static research into Razer's Custom implementation.
GhidraMCP confirmed the wired DLL/hash and decompiled its Custom setter, storage
wrapper, queue worker and separate metadata/selection paths. Named MCP tools were
not exposed in that chat, so a local MCP client used the configured launcher with
a separate private project (the existing project was locked). No device requests,
Windows execution, firmware updates or application behavior changes occurred.

New details are in
[inspection/HAPTIC_HOST_LIFECYCLE.md](inspection/HAPTIC_HOST_LIFECYCLE.md).
Razer queues stored-profile edits separately from live edits. Its live managed
API index0 becomes wire selector1; the storage dispatcher explicitly skips literal
selector1 for Custom/metadata and logs it as Active Profile. This is not a dynamic
active-slot test. The failed NagaLibre candidate already used wire selector1, so
this does not by itself fix the trial. Neither the traced Custom handler nor its
storage worker adds a Custom-only final commit packet. Initialization/mode/power
lifecycle and the firmware flash gate remain unresolved; Custom apply gates stay.

The follow-up also documents WPF flattened-path length sampling (51 samples),
forward simplification, float32 scale factors/five-decimal rounding and first
maximum-Y tick-index selection. These improve the host generator specification
but still need cross-platform golden fixtures and do not establish device bounds.
Private decompilation/projects remain outside tracked source. Only research docs
changed, checked for whitespace and valid local links; no new hardware test is
needed from the user for this checkpoint. Onboard macro physical tests remain
deferred as requested.

The user then authorized further binary research. The 2026-10-21 continuation
traced the wired DriverMode and GenericFeature libraries, plus the newer mouse
firmware directly in Ghidra and the older image's flash worker in Thumb assembly.
Ordinary DriverMode enables wire mode3/disables mode0; it does not use the mode1
flush/reset path. The generic JSON bridge adds no wheel commit. The newer Custom
flash gates are one-shot permissions consumed by curve/metadata flushing; power
and connection transitions reopen them. The older image also gates curve writes
but differs for metadata. Do not assume the installed1.2 image matches either.

Active-profile upload completion can prepare distinct working tables from RAM
cache while selector-zero readback still follows a flash source pointer. Thus
the previous mismatch does not establish a failed live transfer, and unchanged
flash after recovery does not prove pending cache equality. A verified live-data
and persistent-save/recovery contract is still missing. No new command or safe
USB-reconnect contract was established. Custom apply gates stay; no mouse request,
mode switch, firmware flash or physical test was performed. Details, provenance,
addresses and next requirements are in HAPTIC_HOST_LIFECYCLE.md above.

## Macro transaction and desktop implementation

`src/onboard/macro_transaction.rs` captures existing contents and all scoped paired
mappings plus normal middle-click guards. The GUI fsyncs the unprivileged backup
before sending its commit token. The helper creates a private ownership journal,
rechecks freshness, journals each request before mutation and verifies exact
uploaded bytes before binding. Existing entries are never overwritten/deleted;
no compaction/format route exists. The hidraw control interface uses an advisory
lock to serialize NagaLibre helpers; other controllers must still be closed.

Recovery opens only a helper-owned protected journal. It verifies original
contents and allocation ownership, restores original target records, checks exact
paired mappings and removes only its fresh allocation after checking references.
Recovery never uses generic mapping-save rollback, which could reinstall an
uploaded binding after restoration failure. Lost restore/delete acknowledgements
are resolved through readback. Torn journal tails can be reopened; journal I/O
failure attempts reference restoration but retains the allocation. Known target
bank aliasing can be restored; unrelated state changes block recovery. Contents
can be restored while free/reclaimable accounting changes. Reference coverage
is still incomplete; the backup is not a complete profile image.

CLI: `onboard-macro-prepare CONFIG REQUEST`, `onboard-macro-apply BACKUP JOURNAL`,
`onboard-macro-recover JOURNAL`. Session protocol 4 advertises `onboard_macros`
only on wired 00a7. The Qt **Onboard macros…** dialog exposes inventory/storage,
sequences and once/counted/held/toggle/sequence modes. It reuses the sequence
editor, keeps drafts distinct from readback and invalidates on errors/plate changes.
The ordinary mapping-save action still refuses macro sequences and directs users
to the dedicated dialog. The experimental notice remains visible.

`scripts/macro_controlled_test.py --readback-only` is ready for a future local
sudo session. It creates durable private backup/evidence, uploads one fresh B
sequence, verifies bytes, restores bindings and removes its allocation. Without
the flag it separately records physical output/release/primary-click/reconnect
observations. `--restore JOURNAL` resumes only recovery. Do not run the hardware
trial until the user resumes testing. User documentation: [docs/MACROS.md](docs/MACROS.md).

Validation: 174 Rust and 181 Python/Qt tests passed, including mock QProcess
read/prepare/durable-backup/commit/exit/reconnect/undo. Formatting, Clippy with
warnings denied, debug/release builds, example config validation and offline
macro compilation passed. Recovery regressions include each upload/binding
lost ACK, pre-write failures, interrupted selector-echo restoration, aliasing,
journal I/O failure, shared-reference/foreign-GUID refusal and idempotent cleanup.
No live trial was run. Hardware testing remains deferred at the user's request.

The historical sections below describe earlier implementation stages; their
statements about absent setters/recovery are superseded by this section. The
diagnostic export and offline plan remain non-executable and cannot authorize
cleanup; only the new transaction journal does so.

## Ghidra metadata and upload planner follow-up

The matching official Ghidra 12.1.4 and GhidraMCP 2.0 are installed privately
outside the checkout. Codex's `ghidra` entry runs a headless launcher under
`~/.local/share/ghidra-mcp`; its project lives in `~/ghidra-projects/NagaLibre`.
Paseo reloaded this conversation successfully. The exposed MCP tools now identify
the expected wired DLL/hash and decompile its native routines directly. The GUI
does not have to remain open. Keep projects/proprietary decompilation private.

Ghidra confirmed the 250-byte metadata assembly: Windows-layout GUID at 0,
little-endian expanded event count at 16, UTF-8 name at 20, initial movement X/Y
at 120/124 and a managed combined-key reconstruction hint at 128. The post-name
region is not a second GUID. Reserved/padding semantics and firmware acceptance
remain unverified. New non-movement entries use deterministic zero initialization;
existing metadata is never normalized. Native padding is not necessarily canonical.
Evidence RVAs and the initialization distinction are in inspection/MACROS.md.

`onboard-macro-plan INSPECTION CONFIG REQUEST` builds an offline proposal using
`examples/onboard-macro-plan.json`. It validates the retained getter checkpoint,
compiles one TOML trigger, rejects an existing GUID and selects among the five
native hash candidates while excluding stored/shared/dangling scoped IDs. It
checks entry capacity and available storage without compaction, builds ordered
allocation/64-byte metadata/72-byte sequence packets and keeps the proposed
playback binding separate from upload. Once, counted 1..255, held, toggle and
sequence encodings are implemented; their physical behavior is not verified.
The exact original target record and contents remain in the private plan.

The plan is explicitly non-executable and hardware-unverified; it is not an
ownership/recovery journal and cannot be deserialized as a mapping snapshot.
Unknown/malformed references block planning. Middle/secondary primary clicks and
other plates remain outside reference coverage. No macro setter, cleanup, format
or compaction transport route is enabled. No device requests were sent in this
follow-up; testing uses the historical capture offline and synthetic contents.

Validation: 161 Rust and 168 Python/Qt tests passed; formatting, Clippy with
warnings denied and debug/release builds passed. Regression cases cover Windows
GUID layout, UTF-8 byte bounds, metadata endianness, partial upload chunks, all
playback encodings, shared/dangling IDs, collision exhaustion, full capacity,
compaction rejection, target scope and inconsistent checkpoint evidence.
The release CLI generated a private offline plan from the user's historical
empty-inventory export (250 metadata bytes, 10 sequence bytes, six packets);
the original export checksum is unchanged. The plan was saved with 0600 mode
and file/directory fsync beside that export as `macro-upload-plan-offline.json`.
CLI rejection checks covered extra playback fields, count zero, absent trigger
and disallowed target wire IDs. None of these invocations opened a mouse.

## Macro compiler and checkpoint follow-up

The next offline chunk is implemented. `onboard-macro-compile CONFIG` uses existing
software TOML steps to produce native key/mouse/delay bytes with explicit
`hardware_verified: false`. It preserves chord ordering, independent modifier
events, cumulative mouse state and trailing waits; canonicalizes mouse aliases;
and rejects unsupported, unbalanced or invalid timelines. Bounds are 16,384
encoded records and five minutes, not claims about device limits. The structural
decoder retains original record bytes/nonminimal delay widths and opaque unknown
tails. Nothing submits compiled sequences to a hardware writer.

Static tracing of archived shared Synapse dependencies resolved the host delay
unit (direct `MacroEvent.Delay` -> `Thread.Sleep(Int32)`, milliseconds). The
Device167 bridge copies it without scaling. Native metadata names are UTF-8 in
100 bytes; expanded event count is little endian at offset 16. Construction of
remaining metadata fields remains unresolved. JSON labels now establish counted,
while-held, toggle-until-pressed and sequence associations independently of the
different generic/UI enums. See inspection/MACROS.md for RVAs, hashes and limits.

`onboard-macro-checkpoint INSPECTION [--fresh INSPECTION]` validates saved content
by replaying every retained getter record offline and checking parsed values,
mapping scope, guard and slot coverage. Optional fresh comparison permits only
hidraw-path changes. The existing private empty-inventory export passed. The
release validator saved `macro-checkpoint.json` beside that earlier export with
0600 permissions and file/directory fsync; the original export checksum is unchanged.
This was offline validation of the historical capture, not a fresh hardware read.
The private capture script durably saves the resulting content checkpoint as the
unprivileged user, retaining raw evidence and final mapping checks on failure.
It explicitly has `complete_profile: false` and `restoration_implemented: false`.
This is backup validation/stale checking, not the journaled recovery transaction.
Allocation/upload/binding/deletion remain absent; no new device requests were sent.

Validation passed 155 Rust and 168 Python/Qt tests, formatting, Clippy with warnings
denied and debug/release builds. Coverage includes native delay-width boundaries,
chords/modifiers, overlapping mouse state/aliases, unsupported/unbalanced actions,
raw unknown sequence preservation, getter-evidence tampering, missing/extra data,
stale mapping/storage/identity, reconnect paths and checkpoint failure handling.
Offline example compilation and the user's captured-export validation passed.

## Onboard macro research and inspection (2026-10-20)

[inspection/MACROS.md](inspection/MACROS.md) documents native count/capacity,
enumeration, metadata/data chunking, ID hashing, allocation, upload, deletion,
event conversion and playback binding records. The ten direct storage functions
match across wired/receiver controllers after normalizing image addresses. The
managed/native OBM bridge inserts explicit delay records before non-movement
events and copies low-32-bit delay values without scaling. Shared contract delay
units and storage mode labels are now resolved in the follow-up above. Remaining
metadata details, device release/timing behavior and firmware acceptance remain
unverified; do not claim autonomous playback from static encoder evidence.

Razer's CStorage enumeration can delete empty-GUID entries; its defragmentation
formats/rebuilds storage. These algorithms are not safe diagnostic paths and are
not implemented. The new `onboard-macros` uses an explicit direct-getter allowlist
for wired/normal/twelve-button scope. It double-reads capacity, count, IDs, sizes,
250-byte metadata and sequence bytes, retains exact request/reply records and
opaque contents, and checks all initialized slots' paired mappings and state.
Unknown contents and empty metadata are preserved; inconsistent reads abort.
Secondary primary clicks and other plates' references are outside this scope.
The diagnostic has `restorable: false`; there is no macro writer or restore route.

`python3 scripts/inspect_macros.py` uses the release engine and local sudo to
save a private durable all-slot mapping checkpoint before the first macro getter,
then the diagnostic and final mapping checks. Exports contain private sequence
contents and identity; keep them local. The user completed this capture through
local sudo authentication. Capacity (`06/8e`) and count (`06/80`) repeated exactly:
100 macro entries maximum, 0 stored, 126,976 storage bytes, 125,696 available and
1,024 reclaimable. Do not infer completely unused/erased storage from count zero
or explain the remaining 256 bytes without evidence. Slots [1,2,3], active 1,
normal mode and twelve-button plate were preserved; independent file comparison
confirmed before/export/after paired mappings equal with no scoped macro-category
records. Serial/path and mapping contents remain private. The export checksum
matches the user's supplied value. No ID/size/metadata/sequence queries were
needed, so those getters, actual playback and writes remain unverified.
Private evidence directory: `macro-inspection-1792531564209263577`.
Stop GUI/OpenRazer/Polychromatic controllers before future captures; retain strict
framing/correlation if firmware replies differ.

Validation: 148 Rust and 167 Python/Qt tests passed. New coverage includes empty
metadata/unknown data, 32-ID pagination, final partial chunks, invalid lengths,
echoes/counts/resource bounds, changing storage/mappings/plate, receiver gating,
durable checkpoint ordering/failure and final mapping checks after getter failure.
Synthetic macro replies establish host construction only, not hardware behavior.
The capacity/count regression additionally uses the non-identifying live reply.
Formatting, Clippy with warnings denied, debug/release builds, example config,
CLI/script help and diff whitespace checks also passed. Release helper is rebuilt.

## Standard wheel modes

Wired Naga V2 Pro with its twelve-button plate now has a separate **Wheel settings**
dialog for Standard (`0x81`), Distinct (`0x82`), Ultra-fine (`0x83`), Adaptive (`0x84`)
and Smooth Scroll (`0x85`). It reads current active mode and enabled cycle order, supports
checking/reordering standard modes and choosing the active mode, and shows a
plain-language description. Stage IDs differ from enabled-list positions.
Defaults are a local draft; button-binding defaults are separate. Unchanged saves
are skipped. Invalid drafts preserve the last read. Unknown stages make the
snapshot read-only. Existing Custom entries remain enabled/read-only and are
preserved by standard defaults/saves; a currently active Custom mode is reported
without silently replacing the draft with a standard mode. It cannot be newly
selected through this standard-only UI. Read-only diagnostics are collapsed.

The GUI stops software remaps before opening wheel settings. The engine/session
prepares a durable all-slot paired-mapping and readable wheel backup, rechecks
stale snapshots before writes, and verifies exact untouched records. Only the
stage list/selection setters are used; curves, metadata, bindings and device mode
are not written by this flow. Failed acknowledgements trigger rollback, because
the write may have landed. Closing is prevented during a wheel operation. A
successful save stops the helper and retains actual readback until the next read.
Inactive metadata status3 is explicit negative evidence, not verified empty data.

User hardware observations establish all five named preset feels, five-press
cycling back to Standard, normal primary clicks/scrolling and return to original
Smooth feel after restoration. Standard and Ultra-fine USB persistence were
explicitly confirmed; do not generalize that to every mode. Reordered [85,81]
position2 persistence was confirmed. The dialog's full desktop physical flow has
not been separately tested; Qt tests cover the five choices, drafts, cycle
positions, Custom preservation, backup-before-commit and failures.
See [docs/WHEEL.md](docs/WHEEL.md) for the standard-mode workflow.

## Custom haptics: deferred, apply routes blocked

Host/firmware findings are in [inspection/HAPTIC_WHEEL.md](inspection/HAPTIC_WHEEL.md)
and [inspection/HAPTIC_FIRMWARE.md](inspection/HAPTIC_FIRMWARE.md). Firmware reports
major/minor 1.2 (raw `01 02`); patch/exact image identity is unknown. The two extracted
official images are not claimed to match it. No updater was executed/flashed.

Stored-profile CCW/velocity getters alias CW in the tested device. Selector zero
returned distinct CCW/velocity on untouched slot 2 (43/43/5 points), while stored
replies aliased. Original slot 1 and all captured state were restored exactly.
Selector-zero offsets are retained but its source can point to flash, not a
newly changed RAM cache. Capture format haptic_independent_checkpoint preserves
both sources plus all-slot paired/reported state. It is not a full firmware image
or an independent backup of inactive curves/unavailable metadata.

The earlier full replay used aliased bytes before that limitation was resolved.
Historical independent CCW/velocity were never captured and cannot be claimed
restorable. Current slot 1 has CW-prefix velocity through both getters; do not
replace it with slot 2 curves or host defaults as an assumed original. Metadata
records editor intent, not proof of a corresponding waveform.

Changed-value trials received all upload acknowledgements but selector-zero
velocity remained the original prefix instead of (-720,1),(0,1),(720,1). Only
table index 2 and its exact `15/84` record differed. Verification stopped BEFORE
Custom selection; no changed-value feel test occurred. Original recovery packets
acknowledged and visible captured state matched. Pending cache/driver buffers
were not independently read. Unchanged replays prove acknowledged transfers and
matching existing readback, not that changed values are applied or committed.

Extracted 2.61.01 copies upload data into RAM cache and schedules dirty-page work,
but Custom flash writes require a separate gate at RAM200050c0 bit0. The save
lifecycle is unresolved. Do not guess reset/mode/factory-reset commands, packet
lengths, metadata changes or alternate selectors to bypass this. All historical
Custom apply/probe/replay CLI routes are blocked before files/device access;
--restore remains available for existing journals. Stage-only standard saves
remain enabled. The experiment code and fault tests are retained as research,
not a supported Custom editor. New mismatch diagnostics preserve exact expected/
observed State in user-owned 0600 applied.json before recovery, without serials
or unrelated mapping payloads. Never loosen exact comparisons to accept a trial.

## Private hardware evidence index

All paths below are directory basenames under the user's private NagaLibre config
directory; they are untracked and must stay local. No outstanding write/recovery
plan was found during cleanup: eight restored_exactly, one restored_captured_state,
and one preparation-only plan that never reached a write. Preserve the evidence.

| Private directory suffix | Evidence |
| --- | --- |
| haptic-inspection-1792499161590139308 | Initial active1, position5, IDs81..85, 45/45/3 reported points, metadata40; paired mappings unchanged |
| haptic-stage-trial-1792500518847200835 | Standard ratcheting, clicks/reconnect passed; exact captured restoration |
| haptic-stage-trial-1792501208155478224 | [85,81] position2, defined ratcheting and persistence; original scrolling restored |
| haptic-stage-trial-1792502191055814000 | Guided five named feels/cycling; original Smooth/scroll/clicks returned between presets |
| haptic-table-replay-1792503875132265771 | Isolated table write rejected status3; captured readback unchanged; do not rerun |
| haptic-inspection-1792504804230433475 | Repeated firmware bytes01 02; no patch getter |
| haptic-upload-replay-1792506242913409977 | Legacy unchanged full upload acknowledged; independent preservation NOT established |
| haptic-stage-trial-1792506565035451711 | Existing Custom selection felt smooth; normal scrolling/clicks, reconnect and original Smooth return confirmed |
| haptic-table-views-1792521064666936169 | Empty failed read-only attempt; unrelated07/80 reply during02/8c, likely competing controller |
| haptic-table-views-1792521370834215784 | Stored/zero views stable/equal on slot 1, both velocity prefixes; mappings unchanged |
| haptic-slot-comparison-1792524816142847278 | Slot2 stored/zero equality[true,false,false], independent velocity/CCW; exact original-slot restoration |
| haptic-independent-checkpoint-1792525289956879242 | Current active1 checkpoint,45/45/3, both views equal; SHA256 b8644306e433033cbb06dde03f6d50537a4d6dfef82240300700eefb32e8d416 |
| haptic-independent-replay-1792525948540335436 | Two14-packet sequences acknowledged, existing visible readback exact; no changed-save proof |
| haptic-custom-trial-1792526784193479822 | Generic candidate mismatch before selection, acknowledged exact visible restoration |
| haptic-custom-trial-1792527201929626567 | Exact expected/observed velocity mismatch captured; safe stop before selection and visible restoration |

Live control requests conflict with OpenRazer/Polychromatic. Keep strict report
correlation; close other controllers for any future authorized test. The user
shell is fish, so service/trap snippets must be wrapped in bash -c. The execution
environment currently reports CachyOS/Arch; inspect it before package/service
commands. Never assume the global Fedora guidance describes this runtime.

## TODO #4 constraints

Native storage/event/lifecycle research is in [inspection/MACROS.md](inspection/MACROS.md);
the current implementation and next capture are described at the top of this
handoff. Managed macro models are not the wire protocol.
Current mapping/wheel backups do NOT back up macro payloads; establish
a separate durable recovery contract before writes. Never delete existing slots,
macros or shared references. Limit cleanup to allocations made by the experiment.
Keep software macros supported while determining hardware capabilities.

## Validation for this checkpoint

Use the standard commands in AGENTS.md with the current stable toolchain.
Final validation passed: 141 Rust tests, 164 Python/Qt tests, cargo fmt --check,
Clippy with warnings denied, debug/release builds, example-config validation and
diff whitespace checks. The Qt process bridge covers read/save/helper exit/
reconnect/restore with mock hardware; the offscreen dialog layout was inspected.
Prior counts in historical sections belong to their earlier checkpoints.
Build artifacts, private plans/backups, Python caches and proprietary inspection
payloads remain ignored and must not enter the commit. Distribution stays
source-only; no releases, binary assets, history rewriting or firmware updates.

## Existing bindings and Hypershift (previous checkpoint)

GUI implementation is complete for the wired twelve-button active-slot scope.
Normal/Hypershift drafts, normal-bank trigger action, sparse keep/disabled actions,
stored/draft separation and explicit stored-to-draft copy are implemented.
Secondary drafts start as Keep stored binding. Version-1 local profiles migrate
in memory to v2 without rewriting files or changing hardware; normal edits,
learned inputs, other plates and macro drafts survive. Unsupported secondary
macros/nested triggers are rejected. See docs/HYPERSHIFT.md for user workflows.

Wired GUI reads/saves use paired session commands; receiver/older helpers keep
their normal-only path and cannot send Hypershift writes. Saves fsync all-slot
paired backups before token acknowledgement and stop the helper after success.
Restore backup accepts paired backups or routes legacy normal backups through a
normal-only paired transaction preserving fresh secondary actions. Diagnostic
exports cannot be used as backups. Unknown actions stay Keep stored binding.

Paired existing-slot activation now captures/verifies every initialized bank,
retains actual selector tags and rolls back lost acknowledgements without mapping
writes. Creation backs up/verifies existing secondary banks too; zero normal tags
are still required, with an explicit refusal before allocation otherwise. New
secondary allocation defaults remain unverified; no existing slots are deleted.
These extended slot paths have software fault coverage, not new hardware proof.

The desktop is covered through real QProcess mock-helper save, exit, reconnect
and restore; tests cover migration, independent drafts, nested-trigger rejection,
unknown raw preservation, receiver gating, paired activation and failed fsync.
`check_hypershift_gui.py` supplies getter-only independent all-slot checks for
prepare/staged/saved/restored, including normal primary/middle checks. The user
completed all four checks through the GUI: staging left the mouse unchanged,
saved DPI trigger/secondary grid-1 B matched with every other scoped record and
slot exact, and GUI restoration recovered every original paired record, echo,
primary check, slot and device state exactly. The user confirmed physical
hold/release, primary clicks, USB reconnect persistence and original outputs/DPI
cycling after restoration all passed. This closes section 2 for wired 00a7 with
the twelve-button plate and this trigger/action combination. Receiver Hypershift
and other combinations remain unverified. Current tests: 91 Rust, 101 Python/Qt. Formatting,
Clippy, debug/release builds, example-config validation and diff whitespace checks
all passed. The updated release helper is built for the launcher. No new live settings writes were performed
by the agent while implementing this GUI.

Earlier firmware-only physical result: wired 00a7/twelve-button Hypershift held trial passed.
The user confirmed Hypershift produced the expected results: normal grid 1 = key 1,
hold DPI + grid 1 = B, release back to normal. Apply and verify readbacks passed;
all other scoped records/slots were exact. Restore reported exact original paired
records and actual echoes; persisted status is `restored`, and backup/plan hashes
were independently checked. The user subsequently confirmed primary clicks, Hypershift after USB reconnect,
and original physical outputs after restoration all passed. This completes the
wired physical checks for this trigger/action combination. Receiver Hypershift
remains unverified.
GUI normal/secondary editing, profile migration and desktop verification are
complete for the scope described above. Do not rerun the completed trial plans. The historical failures below are
resolved and are retained for protocol/recovery provenance.

Latest hardware result: the smaller automatic write probe passed. On wired 00a7,
secondary grid 1 returned B (`02 02 00 05 00 00 00`) while selector 0 retained key 1
(`02 02 00 1e 00 00 00`). Both replied with selector byte 1. All other tracked state
was unchanged; exact original paired records and echoes across backed-up slots
were restored before helper exit. Private status/result and backup/plan hashes
were independently checked. No trigger was assigned. This proves distinct
requested action records despite the shared returned tag for this control/write.
It does not prove physical held/release behavior or a universal tag rule.

The paired reader now retains `normal_echoes` alongside secondary echoes. Only
wired scoped normal controls accept 0/1; ordinary normal snapshots, receiver
normal reads and primary queries remain strict. Both passes compare every actual
echo, and stale checks preserve them. Early paired exports omitted normal echoes
because the normal reader required all-zero echoes; deserialization supplies
that documented legacy meaning. Writers predict last-selector tags only for
intentionally changed controls and compare the final metadata exactly. Restore
and rollback can replay an unchanged original record to restore its tag; saved
normal/secondary tags must agree before such a replay. Changed/untouched action
verification rules remain semantic/exact respectively. Lost acknowledgements
are still restored and checked, including when the saved starting tag was 1.

The physical held trial runner is updated to check both sets of echoes. Use a
fresh directory (`hypershift-held-test`), keep GUI closed, and never rerun the old
completed plans. The wired trigger/held trial has now passed as recorded above.
GUI support and the remaining explicitly separated observations are next. Current
validation: 85 Rust and 86 Python tests, formatting, Clippy and source builds.

**Recovery result:** persisted runner state now reports `restored_exactly`, and
the original trial status is `restored`, referencing its private echo-recovery
attempt. These statuses are written only after successful helper verification
of the complete paired backup. The root-owned helper journal could not be read
without sudo. The user subsequently confirmed original grid-1 output, DPI cycling,
left/right/middle clicks and repeated checks after USB reconnect all passed.
Recovery is complete. Hypershift hold/release behavior remains unverified. Do not
retry the old apply or echo recovery; resolve selector-write semantics before a
new trial.

Current follow-up: native storage setter/canonical keyboard encoder and actual
transport vtables were re-traced; see inspection/HYPERSHIFT.md for RVAs and the
unresolved runtime transaction flag. No simple argument-order or length mismatch
was found. Shared per-control returned selector metadata is a hypothesis, not yet
proven; existing normal reads remain strict.

A new smaller diagnostic is built in the debug helper:
`python3 scripts/probe_layer_write.py`. It creates a NEW private all-slot paired
backup, performs one secondary grid-1 B write, observes both requested selectors,
then always restores original secondary followed by original normal grid-1
records and verifies the full paired backup before helper exit. No trigger is
assigned. It uses the existing established mapping addresses/transaction only.
Its user checkpoint and create-new root journal precede writes; run cannot be
repeated in the same directory. `restore` is a separate restoration-only path
for interrupted attempts, with fresh identity/unrelated-state/plate guards and
no new B write. Current validation: 81 Rust/85 Python tests, formatting, Clippy
and debug build at that point. Both earlier trial statuses were subsequently
checked restored before rebuilding the release helper for the fresh held trial.
Do not reuse the old completed plans with the rebuilt helper.
This probe subsequently passed as recorded above. Physical held/release testing
and GUI feature work remain pending.

Previous failure and recovery implementation details follow:

The first Hypershift apply was attempted and failed.
Normal slot-1/grid-1 getter (request selector 0) received a valid reply echoing
selector 1. The strict normal reader blocked verification and exact rollback;
At that point restoration was not established and the trial journal was
`applying`; the successful recovery above supersedes that state. Original
and pre-write recovery backups were independently compared equal, covering slots
1/2/3; original engine/runner/session/backup hashes still match the saved plan.
Keep `target/release/naga-macros`, `scripts/hypershift_test.py` and
`scripts/onboard_controlled_test.py` unchanged until recovery: rebuilding the
release helper or editing the runner would invalidate the existing trial.
No apply retries. User was instructed to release buttons, reconnect USB and run
the existing `hypershift_test.py restore`. Reconnect/restore failed with the
same normal grid-1 echo mismatch. The subsequent selector capture passed in 2.5s:
all 35 scoped action records matched their respective backup bytes, including
normal primary clicks. Grid 1 echoed 1 for both requested selectors; all other
echoes were 0. Capture checksum was independently verified. This narrows the
observed active-slot difference to grid-1 echo metadata; it does not prove the
other slots or physical behavior restored.

A separate read-only recovery path is built at `target/debug/naga-macros`:
`python3 scripts/inspect_layer_recovery.py`. It queries the active slot's three
normal primary records and all sixteen permitted addresses with selectors 0/1,
repeats the sweeps, checks identity/mode/inventory/plate stability, and retains
requested/returned selectors plus exact raw bytes. It never infers bank identity,
never writes settings, and its envelope cannot be accepted by any restore path.
It saves separate private evidence without modifying the active trial. Use this
if reconnect-and-restore still fails. Other slots are not captured by this probe.
The release helper remains the original checksum-bound build; do not run a
release rebuild while this recovery is pending. Recovery diagnostic validation:
73 Rust and 79 Python/Qt tests, formatting, Clippy and debug build passed.
Reverse echoes remain preserved evidence, never normal-bank readback acceptance.

A narrowly scoped recovery is now built in the debug helper:
`python3 scripts/recover_layer_echo.py`. It preserves the original checksum-bound
trial/release helper and uses a separate unprivileged fsynced input/checkpoint
plus a helper-side create-new fsynced journal. The engine rechecks the supplied
capture against fresh double sweeps, requires every action byte to match the
paired backup with only grid-1 echoes 1, and checks both banks/middle click in
other initialized slots. It repeats the guard after the journal, then writes
ONLY the original normal slot-1/grid-1 record with selector 0. It never replays a
selector-1 write. All backed-up banks, actual echo metadata and normal primary
checks must verify exactly before success. A failed acknowledgement still runs
the full verification; failed verification cannot report restoration or retry.
The unprivileged runner marks the old trial restored only after engine success.
Persisted runner status now records successful exact recovery as noted above. Validation: 77 Rust/82 Python tests,
formatting, Clippy and debug build passed; original release/runner/backup hashes
were kept intact. User sudo and physical checks are still required.

The long apply duration follows from many redundant all-slot double reads plus
strict-echo timeouts during verification/recovery. Optimize after restoration,
without weakening stale checks. The reverse-echo failure is new hardware evidence;
selector-1 writes and exact recovery are not hardware verified.

Historical implementation status follows (superseded by the failure above):

Hypershift research, read-only tooling and the bounded transaction engine are
implemented. GUI editing remains disabled. The controlled write trial failed as described above. See [inspection/HYPERSHIFT.md](inspection/HYPERSHIFT.md)
for controller hashes, addresses, provenance and limits. Native wired/receiver
encoders use mapping layer 0/1 with unchanged wire IDs; the trigger encoder emits
category 0c, length 1, data 01. These are host protocol traces, not proof of
firmware bank selection, restrictions, held/release behavior or persistence.

Latest hardware evidence: both wired 00a7 and receiver 00a8 returned valid
status-2, transaction-1f, 02/8c, length-10, checksum-valid responses echoing layer 0
for layer-1 requests. The initial strict reader rejected these, first at primary
left click and then at grid 1. Secondary primary queries stay outside scope;
normal primary checks remain. No settings writes were requested.

The wired forensic capture subsequently completed both passes of all sixteen
scoped records and checked normal state/plate unchanged. Its private checksum
was independently checked. Twelve records matched normal exactly. Grid 1/2
returned the same keys with declared length 1 instead of 2. The wheel tilts
returned category 0e records (native repeated horizontal scroll, parameter 0014)
instead of normal F13/F14. Their nonstandard length and trailing bytes are retained
exactly. This demonstrates selector-dependent record data; physical Hypershift
hold/release behavior is still unverified.

The official getter copies payloads after header/status/checksum validation
without checking argument echoes. Combined with the captured distinct data, this
supports a model-specific zero-echo reader for 00a7/00a8. The layer reader now
permits echo 0/1 and preserves each actual echo alongside request-selected records;
other echoes fail, and all transport/slot/button/length/state/plate checks remain.
Normal readers and writers retain their strict echo checks. The parsed wired export subsequently passed all sixteen scoped records with
all zero-layer echoes retained; its checksum was independently verified. Grid
keys, repeated horizontal tilt records and the wheel-mode/DPI bindings parsed
correctly. This is readback evidence, not physical held/release verification.

The transaction engine now backs up both banks and normal middle click in every
initialized slot. Its initial scope is wired 00a7, active slot, normal mode and
twelve-button plate. Sparse edits allow supported keyboard/mouse/disabled actions
and the traced category-0c trigger in the normal bank only. Unknown untouched
records remain exact. Mode, activation and inventory writers are absent from this
path. Secondary primary records remain unknown and are never written.

Paired backups use a distinct `paired_mapping_backup` envelope. All-slot stale
checks precede commit; changed actions verify semantically while untouched and
restored records verify exact bytes. Secondary writes precede the normal trigger.
Lost acknowledgements enter recovery; recovery compares both banks/all slots,
restores secondary before normal to handle unexpected setter aliasing, and checks
all original records exactly. Primary/state changes or failed recovery remain
explicit failures; those records are never rewritten.

Session layer commands use the existing one-shot commit-token handshake.
`scripts/hypershift_test.py prepare|apply|verify|restore` is the unprivileged
staged client: private fsynced original/all-slot and per-attempt recovery backups,
engine/runner/checksum binding, durable apply-attempt journal and no apply retries.
It tests secondary grid 1 = B and normal DPI button = held Hypershift, then exact
restoration. Preparation sends getters only. Next: run its preparation, then
apply, physical hold/release/click checks, reconnect, verify and restore. A secondary write was attempted; see the active recovery task above.

Tools and boundaries:

- `onboard-layers [--slot 1..5]` double-reads the normal snapshot and sixteen
  request-selected secondary records, retaining per-control echo metadata. The
  V2 Pro-specific zero-echo handling is described above. Normal primary records
  stay included; the
  secondary export has `primary_inspected: false` and no invented primary data.
  Unknown record encodings preserve raw metadata. Existing normal snapshots and
  legacy session saves are unchanged and remain layer 0. Layer transactions use
  separate session commands and a distinct paired backup envelope.
- `onboard-layer-probe [--slot N]` is a separate forensic path for these mismatched
  replies. It retains transport/header/status/checksum and slot/button checks,
  recording requested versus echoed layer and all seven raw record bytes.
  Comparisons with normal records and repeat reads are exact; normal state and
  plate must remain unchanged. Its envelope is always `unverified_layer_replies`
  with `secondary_verified: false`, without a Hypershift-bank field. It cannot
  deserialize as a Snapshot or LayerReadback and no writer accepts it.
- `python3 scripts/inspect_layers.py [--probe] [--slot N]` invokes only the
  corresponding getter through local sudo. It saves fsynced private evidence,
  prints a checksum and summaries without printing the serial. `--probe` stores
  `unverified-replies.json`; ordinary mode parses the request-selected bank and
  retains the observed echo metadata under the bounded V2 Pro policy above.
  Fully quit the GUI before either. Both forensic and parsed wired captures are
  complete. No guessed selector values or mode changes
  have been introduced.

Validation: 71 Rust and 77 Python/Qt tests passed, including ordinary-reader
rejection of wrong echoes, product-scoped zero-echo handling, actual captured
encoding/action differences, unverified preservation of both normal-identical and differing
candidate records, rejection of unstable bytes/state/plates, envelope separation,
legacy normal-only writes, paired-bank stale checks, lost acknowledgements,
setter aliasing, failed recovery, exact raw restoration and backup-before-token
client failures.
Formatting, Clippy, debug/release builds and the example config check also passed.
Sudo still requires the user's local terminal authentication.

TODO section 1 is complete for the requested session scope. The user explicitly
deferred six-/two-button physical mapping tests; those remain unverified and
should not block Hypershift work. Receiver software
remapping and untested action/connection combinations remain outside this evidence.

Verified on the user's Naga V2 Pro with the twelve-button plate:

- DPI-cycle getter returned category 6/data [6] on wired slots 1/2. The user
  confirmed sensitivity cycling, remapping to B and cycling after exact restore.
  DPI stage values were not read; no stage table or sensor settings were written.
- Right tilt -> B and primary clicks physically passed with exact restore. Its
  original binding was F14; left tilt's original was F13. A reconnect getter
  failed, so right-tilt B persistence remains unverified. The earlier left-tilt
  physical B result remains applicable.
- Scroll-mode cycling, remapping to B, primary clicks, USB reconnect persistence
  and restored cycling/clicks all passed. Other tracked records/slots stayed exact.
- Desktop Restore defaults was verified draft-only before saving. All sixteen
  saved defaults read back correctly, and the user confirmed the grid keys, both
  horizontal tilt directions, wheel-mode/DPI cycling and primary clicks. Exact
  original mappings and other slots were restored afterward.
- Desktop activation of existing slot 2, return to slot 1 and creation of slot 3
  passed independent readback. Creation left slot 1 active and original slots'
  mappings exact. New-slot activation, all twelve outputs, primary clicks and
  persistence after USB unplug/replug were confirmed. Final state is slot 1
  active, inventory [1, 2, 3]; slot 3 is retained. The desktop authentication
  prompt succeeded. No existing slots were deleted.
- Onboard Ctrl+A on grid 1 and right click on grid 2 physically passed over USB,
  including Ctrl release and primary clicks. Readbacks checked every other
  tracked record and initialized slot exactly; exact restoration passed.
- The same output test passed through receiver 00a8: active/all-slot backups,
  twelve-button detection, GUI save, physical output/primary clicks, persistence
  after the requested mouse power-off/receiver reconnect sequence, and GUI exact
  backup restoration. The user confirmed all requested physical steps worked.
  Private restored readbacks for slots 1/2/3 were independently compared with
  their originals. Plan and original-backup integrity were checked. Receiver
  slot creation remains disabled; receiver slot activation and smaller-plate
  swaps were not tested.

Final hardware state from the receiver restoration: original tracked mappings,
mode and active slot 1 restored; initialized slots [1, 2, 3]. Local drafts remain
separate and may still contain the Ctrl+A/right-click experiment. Do not infer
active firmware state from those drafts. All private captures/backups stay local.

New source test tools:

- `scripts/verify_wheel.py` wraps the existing controlled runner with fresh
  per-control backups and explicit yes/no/skip physical observations. It checks
  B readback after reconnect and attempts exact restoration after interruptions
  or lost commit replies. It displays original binding labels and offers explicit
  retries only for unmatched-reply read failures; writes/state mismatches are
  never retried. Restore failure stops the run and preserves recovery evidence.
- `scripts/check_defaults.py prepare|staged|saved|restored` sends only getters.
  It durably backs up all slots and a GUI-restorable original snapshot, checking
  all sixteen defaults or `--test outputs` (Ctrl+A/right click). Unchanged actions
  retain exact wire bytes; changed actions verify semantically. Output staging
  validates the persisted GUI draft before the save. Fully quit the GUI first.
  Readbacks, including failed checks, are saved privately. Explicit
  `--connection receiver` requires 00a8 and separate receiver evidence paths;
  normal preparation requires wired 00a7. Later checks stay identity-bound.
- `scripts/check_slots.py` sends only getters around GUI activation/creation.
  It permits only planned active/inventory changes and preserves exact original
  mapping records. New grid/primary defaults and later tracked new-slot records
  are checked. It has no settings writers or deletion commands.

Two informative failures were recovered. The first output attempt also saved
factory tilt drafts, changing F13/F14 to horizontal scroll. Its unchanged-record
check rejected this; exact restore passed. Persisted-draft validation now catches
that configuration before another GUI save. A mode getter (00/84) failed during
right-tilt reconnect verification and a button getter (02/8c) failed during slot
verification. A GUI helper was still running after the latter failure; concurrent
polling is a possible cause, not a proven diagnosis. Fully quitting the GUI and
retrying its read-only check passed. Keep CLI getters and GUI polling separate.

Final validation: 52 Rust and 70 Python/Qt tests passed, formatting, Clippy with
warnings denied, debug/release builds, example config check and diff whitespace
checks. Regressions cover interrupted observation/accepted-write lost replies,
read-only retries, strict other-slot/raw-record preservation, incorrect shortcut
modifiers, unexpected factory drafts, evidence retention, slot-state changes and
explicit receiver identity binding. No compiled assets are added to distribution.

## Earlier implementation and protocol context

These entries preserve implementation-stage evidence. The completed physical
checks above supersede earlier statements that those paths were unverified.

Added the second top button, DPI-cycle, as logical 16 -> wire 0x60. The official
Device167 defaults identify DKM_SB_03 with DPI_CycleUp; managed EMwDKMKeys gives
DKMID_DKMKEY_SB03 = 82. The native input dispatch at RVA 0x67790 sends 82 to
0x67809 -> 0x60. DPI action category 6/data [6] decodes at 0x55084 to abstract
action 11, mapped through table 0x6003c to 0x5f6a1 (DPI/CycleUp). The default
cycles the existing DPI stage table; no stage values, primary clicks or sensor
configuration are written. The fresh control-16 trial preparation read category
6/data [6] from both initialized wired slots (1 and 2), with slot 1 active and
the twelve-button plate attached. The user ran the sudo preparation; the private
plan checksum and unchanged engine were independently checked. The plan remains
prepared without settings writes. The user confirmed that pressing the DPI
button cycles pointer sensitivity through different speeds and back to the
starting speed. The user then ran the apply stage and reported that it works:
physical DPI-button output as B is confirmed. The private status is applied and
its saved readback has category 2/data [0, 5]; the runner checked other tracked
records and slots unchanged. The restore stage subsequently completed: plan
integrity was checked, status is restored, and the saved final snapshot matches
the original exactly (excluding the transient device path), including DPI category
6/data [6]. The runner also checked other initialized slots unchanged. The user
confirmed physical DPI cycling works again after restoration. Reconnect persistence
and primary-click behavior were not separately reported for this trial.
This mapping backup does not read DPI stage values,
so it cannot establish that the stage table is unchanged.

Per-device `defaults` now live in devices/models.json: plate trigger keys and
verified onboard bindings, extra-control labels/IDs/addresses/default actions.
Both Python and Rust consume it, including creation's grid-default validation.
The writer retains a separate safe address set and only accepts each registry
factory action on its declared position. Unknown model defaults remain empty;
experimental model capabilities and input learning are unchanged. See
devices/README.md for the schema. Existing three-control drafts append a fourth
Keep stored binding control without replacing edits; old three-control hardware
backups preserve the current DPI record. New backups include all four controls.
Restore defaults now covers sixteen supported bindings. No live writes were made.
Validation passed 52 Rust and 47 Python/Qt tests, including DPI-only writes/raw
rollback, legacy backup preservation, profile migration and registry integrity.

The reset button is now Restore defaults. In hardware mode it stages all twelve
grid defaults plus wheel left/right horizontal scroll and scroll-mode cycling;
it sends no device requests until Save bindings to mouse is clicked. It works
offline and preserves other plates. Software mode retains its existing stop/reset/
apply-pass-through behavior. Each wheel control has a separate Factory default
mode and per-control Use default stages that preset; Keep stored binding remains
a separate option and is still the initial draft state for existing profiles.
Factory actions are explicit position-scoped presets: logical 13 -> category 1
data [0x68], 14 -> 1/[0x69], 15 -> 18/[4]. The native decoder confirms the earlier
captured 18/[4] is Haptic_CycleUp; it is now labeled Cycle wheel modes. See the
native trace in inspection/ONBOARD.md. These presets restore binding functions,
not device settings such as wheel tension, stages, DPI, RGB or Synapse turbo rate.
Physical horizontal output/cycling remains unverified; no live writes were made.
Validation passed 51 Rust and 46 Python/Qt tests, including scoped preset
validation, rollback, offline draft-only restoration and profile round trips.

The user reported "That works" after left tilt -> B, confirming physical B
output. Local wheel-test-13 status now reports restored, so the runner verified
exact original tracked records after restoration. Physical original Back behavior,
primary clicks and reconnect persistence have not been separately reported.

At the user's request, removed separate authorization requirements from repository
instructions, runners and CLI flags. Test stages now use their saved plans directly;
checksums, durable backups, stale-state checks, repeat prevention and recovery
remain. Sudo/polkit authentication remains. scripts/wheel_test.py is a convenience
entry point; wheel_controlled_test.py also runs directly without approval arguments.
Existing completed plan files remain historical evidence and are not reused.
This cleanup passed 50 Rust tests, 45 Python/Qt tests, formatting, Clippy,
debug/release builds and example config validation. CLI help confirms that the
wheel/slot runners and hidden slot-trial engine command have no approval flags.

The user asked to run the wheel remapping test. Added scripts/wheel_controlled_test.py
with prepare/apply/verify/restore stages, initially logical control 13 (left tilt)
to B on the currently active wired slot. Preparation is read-only and saves all
initialized snapshots in a private checksummed plan. The saved plan hash, engine/runner/session hashes, stable state and a 12-button
plate are checked before test stages. The prepared active-slot backup must be durably written before
commit. Apply is consumed before the commit, so a lost reply cannot invite a
repeat apply. Verify reads only; restore accepts either the original state or
exactly the intended target-to-B change and verifies exact original tracked
records afterward. All other slots are checked before and after writes. The
target slot is re-read after inspecting other slots so helper selection cannot
accidentally address a different slot. Helper exits after each stage. Physical
input, reconnect persistence and restored behavior must be recorded separately.
The runner's six simulated
tests and four existing controlled-test regressions pass. The shared Session now
accepts supported protocols 2/3/4; the wheel-specific session requires protocol 4,
wheel_controls capability and watches the plate, aborting on non-12-button events.

The user subsequently ran the read-only controls query on the wired mouse.
All three getters succeeded: logical 13 returned category 1/data [4], logical 14
category 1/data [5], and logical 15 category 18/data [4]. The first two decode as
Back/Forward using the existing mouse-action decoder. Keep the last action as an
opaque firmware assignment until its meaning is independently established; do
not infer physical behavior from readback. Added a captured-state regression for
preserving all three during a grid-only save and restoring category 18 via backup.
At that stage writes and physical behavior remained unverified; the subsequent
left-tilt test and restoration are recorded above. The readback command did not modify any mappings.

Wheel controls added to Mouse memory mode: tilt left/right and the scroll-mode
button below the wheel. Official Device167 DefaultMappings.xml uses Mouse
Button6/Button7 and DKM_57 (scroll stage cycle). Managed ConvertDKMKeystoMw maps
DKM_57 to 87; native converter RVA 0x67790 maps mouse buttons 6/7 to wire
0x34/0x35 and DKM 87 to 0x6d. See inspection/ONBOARD.md for the trace.
Logical positions 13/14/15 have explicit allowlisted addresses; left/right/middle
remain unwritable. Snapshots retain the twelve grid records and add a default-empty
controls array for compatibility. New reads get all three control records;
backup/restore/stale checks/rollback include them. Legacy backups preserve current
wheel records. Normal saves only write controls explicitly edited in the draft;
Keep stored binding preserves exact firmware actions, including unknown encodings.
Initially Reset 12 buttons left wheel drafts intact; the Restore defaults behavior
above supersedes this. Software mode retains its
existing plate triggers and leaves firmware wheel behavior intact. No onboard
sequence support or wheel tension/scroll-stage settings were added.
New GUI controls and drafts are isolated from other models. The protocol-4 hello
advertises wheel_controls and onboard_prepare accepts an optional controls list.
Read/write/output of these three IDs still needs a user-run hardware check; no
agent-driven live writes were performed. New read requests are statically derived
getters, not guessed probes. Validation passed 49 Rust and 39 Python/Qt tests,
including each address, raw unknown-record rollback after lost acknowledgement,
legacy backup preservation, modern backup restoration, GUI translation/persistence
and storage-mode switches. Debug/release builds, Clippy and formatting passed.

Standalone slot activation is now implemented. Select any initialized inactive
slot and click Activate slot; it can read an unread target without changing the
draft. The protocol-4 hello advertises slot_activation. Preparation reads/checks
the target and previous active slot; the GUI fsyncs both backups before commit.
Commit rechecks both snapshots, writes only 05/04, and verifies both complete
tracked snapshots with only active changed. No mapping/mode writes occur. Normal
mode, standard target primary/middle clicks and the detected 12-button plate are
required. A failed acknowledgement triggers restoration of the old active slot
and unchanged-record checks; incomplete rollback is explicit. Successful activation
updates the dropdown and stored tiles while leaving the helper connected for
further reads/switches; quitting does not request any restoration. No new hardware
writes or live activation tests were performed in this implementation turn.
Validation passed 46 Rust tests and 38 Python/Qt tests, including lost-switch
acknowledgement, failed rollback, unsafe/stale targets, two durable backups before
commit, second-backup failure, and draft preservation. Prior creation evidence
and tests below remain applicable.

Slot creation now has a desktop path for wired 00a7 with the detected 12-button
plate. The user completed the slot-3 trial: creation returned standard
left/right/middle mappings and the twelve expected grid keys, all grid records
with declared length 1. The runner removed slot 3, verified original slots 1/2,
active slot 1 and normal mode. No physical new-slot output, reconnect/power-cycle
persistence or desktop creation transaction has been tested on hardware.

The GUI's Create slot button chooses the next unused ID, prepares snapshots of
all existing slots, durably saves the complete creation plan, then acknowledges
the commit token. Session protocol 4 advertises slot_creation only for wired
00a7. Creation rechecks every snapshot immediately before allocation, reads and
validates new primary/middle/grid defaults and verifies original slots with only
the added inventory entry allowed. No button mappings, mode or metadata are
written; the previous active slot stays active. Success selects the new inactive
slot and keeps the local draft. Save remains a separate action that activates the
selected slot. On any allocation/verification failure, cleanup only removes the
new target, including after a failed allocation acknowledgement; unexpected
activation first restores the previous active slot. Incomplete cleanup is an
explicit error, never a silent retry. Existing-slot deletion and first-profile
creation remain unsupported. Receiver creation remains disabled.

The hidden onboard-slot-trial CLI and scripts/slot_trial.py remain available for
temporary experiments. The completed plan is consumed and must not be repeated.
New experiments require fresh snapshots and a new plan.
Private snapshots cover only the established read contract, not complete profile
images. Creation backup files contain a plan with all original snapshots and a
target; the ordinary Restore backup command accepts individual mapping snapshots,
not the complete creation plan. See inspection/ONBOARD.md for evidence and limits.

Validation passed 43 Rust tests, 36 Python/Qt tests, formatting, Clippy with
warnings denied, debug/release builds and example config validation. Coverage
includes stale/existing targets, lost allocation acknowledgements, unexpected
activation, invalid primary defaults, failed cleanup, durable GUI backups before
commit, backup failure, unchanged drafts, and receiver/plate capability gates.

NagaLibre is an independent FOSS Linux reimplementation of Razer Naga side-button
bindings. Target mouse: Naga V2 Pro. The user's hardware machine runs Arch/KDE;
earlier development used a VM without the mouse. In the 2026-10-19 session,
the current execution environment reports CachyOS/Arch and the wired mouse is
visible. Direct hidraw access still requires local sudo authentication. Do not
assume one machine’s toolchain, device paths, sudo access, or private files exist
on another.

The GUI uses PySide6 and a locally built Rust engine. The source-only distribution
policy replaces the earlier binary-preview workflow. No compiled executables or
bundled application archives should be uploaded. scripts/package.py was removed.
The GUI now uses target/release/naga-macros unless NAGALIBRE_BACKEND is set,
preventing old root/dist preview executables from overriding a fresh source build.
At the user's subsequent request, all five historical GitHub preview releases
(v0.2.0 through v0.3.1) and their downloadable assets were removed. Source commits
and git tags were retained. Publishing releases is postponed until the user asks
to resume it; build from source in the meantime.

The README was rewritten for users, with requirements, source build commands,
support limits and app usage. AGENTS.md holds architecture, checks and hardware
invariants. The obsolete inspection/VALIDATION.md was removed; current validation
and hardware evidence belong here. Protocol research remains in inspection/.

Cargo package version remains 0.3.1; version alone does not identify whether a
local executable includes these source fixes. Rebuild from the intended commit.

## Hardware evidence

The latest completed onboard-write test is recorded in commit 8def909 and preceding
commits deb2668, dd0d727 and 594fea9. Device: USB 1532:00a7, 12-button plate,
active slot 1, normal mode [0, 0]. Receiver 1532:00a8 is recognized but unverified.
Bluetooth onboard access is unsupported. Slot inventory reports initialized
slots [1, 2]; physical behavior of slot 2 is untested.

Verified on the user's wired mouse:

- Serial/mode/inventory/active getters and button-table reads for slots 1 and 2.
- All twelve active-slot outputs: KEY_1..KEY_9, KEY_0, KEY_MINUS, KEY_EQUAL.
- Durable active-slot backup: private file, file/directory fsync, checksum, and
  preservation of the ten original nonstandard keyboard encodings.
- Change of button 1 (firmware ID 0x40) from 1 to B through
  the real session using canonical GUI actions. Save and independent readback
  showed B, the other eleven exact records, standard primary mappings, unchanged
  mode and unchanged active slot.
- User confirmed physical B output, fully quitting NagaLibre, reconnecting/
  power-cycling, B still working, and normal left/right/middle clicks. A fresh
  read-only session verified the saved B and other records.
- Backup restore: save response and independent readback matched all
  original wire records, primary mappings, mode, active slot and identity.
  Transient hidraw path was excluded. Restore receipt and backup hash checked;
  user confirmed button 1 typed 1 again.

There was no hardware transport write counter. The only-0x40 assertion is backed
by regression tests and the code path, plus final unchanged records on hardware.
Post-restore physical primary clicks were not separately reported, although their
stored mappings matched. Hardware failure rollback, unknown-action restore,
modifier/mouse outputs, inactive-slot activation, receiver behavior, factory reset,
other plates and multi-step macros remain unverified or unsupported.

Private backups, checksums, engine checksum, recovery records, receipts and user
confirmations remain on the hardware machine under ~/.config/NagaLibre/. Its
controlled-hardware-test.json status was restored_exactly_button_1_confirmed.
Do not commit the private files or mouse serial. That test is complete. A new apply requires fresh backups and a prepared plan.

Local sudo authentication was needed. The user ran staged commands because
noninteractive sudo required a password and an earlier pkexec getter attempt
timed out. Do not describe the live test as a full Qt/polkit end-to-end test.

## Protocol details that caused earlier bugs

The control interface is selected by its HID descriptor: report ID zero and a
90-byte feature body (91 bytes with the report-ID prefix). Never hardcode a USB
interface, hidraw node or event number.

The mouse returned inventory payload `05 01 02`, length 3: capacity 5 followed by
existing slot IDs. The original fixed-six-byte decoder rejected it. The current
parser accepts compact inventories bounded by capacity, retaining range,
duplicate and empty-list checks. This correction was verified on hardware.

Keyboard records on grid buttons 1/2 used declared data length 2. Buttons 3–12
used length 1 while still carrying modifier and usage bytes. Example complete
payload for button 3: `01 42 00 02 01 00 20 00 00 00`. Reading only the declared
length discarded the HID usage and produced [0]. The decoder now reads both
keyboard bytes in this case and retains raw_record when the canonical bytes
would differ. Hardware readback matched all twelve observed factory outputs.

raw_record holds the original category, length and all five data bytes. It must
round-trip unknown categories, nonstandard lengths and trailing data. Metadata
is checked against decoded category/data before writing. Old snapshots without
raw metadata remain supported.

Review of commit 50c43dd found ten unnecessary writes when GUI canonical actions
were compared to whole Button structs. Fix deb2668 separates decoded-action
comparison from exact-wire comparison:

- Normal prepare retains original records for unchanged actions and skips writes.
- Changed normal actions verify semantically, allowing firmware re-encoding.
- Unchanged records, explicit restore and rollback verify exact bytes.
- Stale snapshot checks remain strict, including raw data.

Regressions establish zero button writes for unchanged captured factory bindings,
only 0x40 for button 1 to B, exact rollback after an accepted write with failed
acknowledgement, unknown-action preservation, and exact restore when only encoding
differs. The unprivileged GUI durably saves a backup before commit acknowledgement.

## Software engine and UI context

Software macros and the composite-interface fix were confirmed on the user's
mouse. Its pointer/keyboard/consumer interfaces overlap; prefer an ordinary
keyboard node when sufficient, while preserving required absolute-axis metadata.

An early preview let users learn left click as a trigger. Both Python and Rust
now reject BTN_LEFT/RIGHT/MIDDLE/BTN_MOUSE as triggers and learning ignores primary
clicks. Clicks remain valid outputs. Emergency software recovery is to stop the
helper (`sudo pkill -x naga-macros`); this never undoes saved onboard bindings.

Stored and Draft values are separate. Read failure or selecting an unread slot
invalidates stored display and disables saves/reset. Reading leaves the draft
unchanged. Saving compares all twelve draft actions and activates the selected
slot; it is not limited to the currently selected tile. A verified saved snapshot
remains displayed after the helper exits; another save needs a fresh read.

Closing software mode to tray keeps the helper running. Session EOF, Quit and
process termination release software input grabs. Onboard saves stop the helper
and remain in firmware. Plate selection is now automatic while connected; six- and two-button inputs
still require learning in software mode. Do not infer plate identity from one
shared key event.

## Research and provenance

- [Initial installer inspection](inspection/REPORT.md): statically extracted,
  never executed; bootstrap lacks the full controller.
- [Onboard protocol](inspection/ONBOARD.md): official Device167 package, native/
  managed investigation and independent protocol references. Proprietary payloads
  and decompiled code stay outside version control.
- [Faceplates](inspection/FACEPLATES.md): model-specific native/managed trace
  recovered hardware-module getter `00/b9`, one-byte payload/reply. Wired physical
  swaps verified IDs 3 (twelve), 4 (six), 1 (two), 0 (detached), then 3 again.
  This supersedes the inconclusive generic `00/86` layout investigation.

The managed module exposes macro conversion/storage handlers but its host event
structures are not the USB wire format. Native multi-step allocation/upload/
delete encodings are now traced in [inspection/MACROS.md](inspection/MACROS.md),
with a getter-only inspector awaiting hardware capture. Do not claim onboard sequences are implemented;
the software engine remains the available sequence path.

## Historical validation and local environment

The source-only cleanup passed 28 Rust and 23 Python/Qt tests, Clippy with
warnings denied and formatting. New lookup regressions ensure old root/dist
executables cannot override the source build, while an explicit backend override
still works. Local documentation links and tracked ELF/PE exclusion were checked.
A native release build, example-config check and offscreen launch through
./nagalibre also passed. Live evidence is limited to the completed test above,
separate from these automated results.

For this VM only, the temporary toolchain is available through:

```sh
RUSTUP_HOME=/tmp/naga-rustup CARGO_HOME=/tmp/naga-cargo /tmp/naga-cargo/bin/cargo
```

The existing .venv has PySide6; use .venv/bin/python for offscreen GUI tests here.
These are development conveniences, not installation instructions for users.
Use the portable build/check commands in AGENTS.md on other machines.

## Remaining work

The prioritized, session-sized feature backlog is in [TODO.md](TODO.md), including
Synapse gaps beyond OpenRazer's current Naga V2 Pro API. Use it to select the next
chunk and keep the hardware evidence in this handoff current.

1. Broaden controlled hardware coverage: reset, failure rollback, shortcuts/mouse
   outputs, inactive slots and receiver behavior, plus the Qt/polkit workflow.
2. Recover and verify native multi-step macro storage before offering it in UI.
3. Verify 6/2-button software outputs and receiver detection. Faceplate detection
   and swaps are verified on USB; the helper currently polls once per second.
4. Exercise hotplug, cleanup and simultaneous external controller access.
5. Keep builds source-only; never revive the old binary-packaging workflow.

## Automatic faceplate detection (2026-10-19)

Pulled main fast-forward from 8def909 to ee84ce0 before this work. Re-extracted
the supplied bootstrap and official Device167 package without running Windows
code. The Naga-specific hardware-module trace and physical readings are in
inspection/FACEPLATES.md. User ran the existing durable backup script and the
new `faceplate --watch` diagnostic through sudo, then confirmed each plate swap.
No mouse settings were written. The backup and raw capture remain private/local.

The engine adds `faceplate [--watch]` and JSON session protocol 3. A `faceplate`
session command enables polling and emits changes with `module_id` and `buttons`.
Known IDs select the corresponding GUI draft automatically; switches stop active
software remaps and learning, preserve drafts and invalidate mouse snapshots.
Read errors show manual fallback; detached/unknown modules block Apply.
Software Apply carries an optional module_id checked immediately before starting;
onboard prepare/commit recheck the twelve-button plate when detection is enabled.
Older protocol-1/2 engines retain manual GUI behavior. Successful onboard saves
still terminate the helper, so detection resumes on the next connection.

Automated validation passed 29 Rust and 25 Python/Qt tests, formatting, Clippy
with warnings denied, debug/release builds and the example config check.
Regressions cover draft preservation, no-plate/unknown/error handling and queued
config cancellation. After launching the rebuilt app and being asked to connect
and swap plates, the user confirmed that desktop detection worked. This is a
user-reported GUI result; the exact plate sequence and authentication flow were
not separately recorded. The CLI watcher independently verified all three plates
and detach/reattach transitions.
The current environment has Cargo and PySide6 directly available; the older
/tmp toolchain and .venv instructions above describe a previous environment.
Receiver/Bluetooth and physical six-/two-button remapping remain unverified.

## Automatic stored-binding refresh (2026-10-19)

The user reported that the detected twelve-button plate still showed Stored:
unread. Plate detection invalidated the previous snapshot but did not request a
replacement on return to the supported plate. In Mouse memory mode, detecting
the twelve-button plate now automatically reads the selected slot when connected
and idle. The existing connection read remains automatic; an in-flight read/save
prevents duplicate automatic requests. Other plates and Software mode do not
trigger onboard reads. Stored values refresh without changing local drafts or
writing settings. A regression covers initial read/detection ordering, detach,
six-button detection, return to twelve buttons, and preserving draft B beside
stored 1. All 26 Python/Qt tests passed, along with diff whitespace validation.
The new automatic refresh has not yet been separately confirmed on hardware.

## Experimental multi-model software support (2026-10-19)

At the user's request, inspected available Razer binaries without additional
hardware. `inspection/MODELS.md` records seven official CDN packages, hashes,
USB identities, layout evidence and candidate Pro/Trinity hardware-module
getters. Do not equate static evidence with hardware-verified support.

Added the shared `devices/models.json` registry and `models` CLI. Discovery now
recognizes Naga Pro/Trinity/X/Left-Handed/Chroma/V2 HyperSpeed and Viper V2 Pro USB
variants. New models use Software mode with learned inputs; their GUI memory
option is disabled and the helper rejects vendor/onboard operations independently.
V2 Pro HID transport/writers remain unchanged. Bluetooth and unknown receivers
are not included. Multiple physical mice are rejected for automatic selection;
composite interfaces are grouped by USB ancestor. Session workers pin model and
physical path to prevent applying a stale draft after changing models.

The protocol-3 hello adds device metadata. The GUI selects the model's layouts
(including Trinity's seven-button plate), labels unverified models, and keeps
separate per-model draft files and an in-memory draft cache. Existing V2 Pro
profiles retain their path/schema. New models begin with empty triggers, and
reset preserves learned inputs instead of inventing factory outputs.

Validation: 31 Rust tests and 29 Python/Qt tests passed, plus Clippy with warnings
denied. Regressions cover unique IDs/capabilities, composite vs multiple mice,
experimental profile roundtrips/reset, model/draft isolation, and a real QProcess
session learning/applying on a simulated Trinity without any vendor commands.
No live writes or new model hardware tests were performed in this session.

## Device-support issue workflow (2026-10-19)

Added `.github/ISSUE_TEMPLATE/device-support.yml` and chooser config with a
structured GitHub form for new models, detection problems, and experimental
hardware results. It asks for exact model/connection, source revision, passive
inventory, layouts, optional faceplate/input observations, and follow-up testing.
`docs/DEVICE_SUPPORT.md` and a README section link directly to the form. GitHub
will expose it after these files reach the repository's default branch; no issue
was created or submitted during development.

Added `diagnose`: passive sysfs input/HID inventories for all Razer products,
including unknown/unsupported connections, capability masks, HID descriptors,
OS ID/version and kernel release. No device nodes, vendor requests, input capture,
serial/unique IDs, physical paths, hostname, drafts or backups are included.
Missing inventories/descriptors are reported. The default JSON filename is ignored.
`list --all-razer --json` includes unknown Razer products without enabling them.

The GUI always offers Request device support and highlights unknown/experimental
Razer devices. The link only prefills registry names and numeric USB IDs; raw
names, logs, profiles and serials are never put in the URL. Opening it requires
the user's click and submission stays in the browser. Unknown Razer interfaces
are described as devices rather than assumed to be mice.

The form and guide only recommend faceplate polling for the enabled V2 Pro.
Other models provide passive metadata and optional explicit input monitoring;
no arbitrary vendor probes, onboard saves, resets, backups or restoration are
requested. Physical observations are distinguished from getter results.

Validation: 32 Rust tests and 31 Python/Qt tests passed, plus Clippy and formatting.
Regressions cover unknown-device inclusion and private/unrelated data exclusion,
encoded issue URLs, duplicate interfaces, contextual UI hints and click-only
browser opening. YAML was parsed and checked locally against the used GitHub
issue-form fields; live GitHub rendering awaits publication to the default branch.

## Device-reported onboard capacity (2026-10-19)

At the user's request, preserve inventory capacity separately from initialized
IDs. The captured V2 Pro `05 01 02` reply now yields `slot_capacity: 5` and
`slots: [1, 2]` in snapshots. Old backups default the optional capacity field to
unknown and still restore through fresh snapshots. Capacity changes participate
in strict stale-state checks.

The new read-only `onboard-slots` CLI returns capacity, initialized IDs and active
slot without serial/button reads, including an empty inventory. Existing V2 Pro
mode/inventory/active getters are used; other models stay disabled. Compact and
six-byte padded inventories support capacities 1–5, with invalid/duplicate IDs
and active IDs outside capacity rejected. No profiles are created or activated.

The dropdown shows all slots within reported capacity and disables uninitialized
entries. A summary says e.g. “2 of 5 slots initialized”; older helper snapshots
retain initialized-only lists and explicitly unknown capacity. Read failures
invalidate the summary. At that stage slot creation was unimplemented; the current
desktop creation path is described above. README, CLI/support
guides and issue form explain the distinction and optional serial-free inventory.

Validation covers captured capacity 5/IDs 1,2, sparse IDs, smaller capacities,
padded replies, empty inventories, getter-only transport calls, stale-capacity
save rejection, legacy restores and disabled UI entries. New capacity display
has not yet been separately confirmed by the user on hardware.
All 34 Rust and 32 Python/Qt tests passed, along with formatting, Clippy with
warnings denied, debug/release builds, whitespace and support-form YAML checks.
