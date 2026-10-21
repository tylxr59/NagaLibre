# Experimental onboard macros

NagaLibre can upload a fresh key/mouse sequence and bind it to a grid button or
supported extra control on wired Naga V2 Pro with the twelve-button plate.
The implementation is experimental. Small wired timelines have passed native
upload/readback, once, counted (3), held and toggle playback, primary-click checks,
USB reconnect and exact cleanup. Other timelines, targets and layer combinations
still need verification.
A shortcut timeline (Shift+B, then C) failed to play immediately after upload but
worked after USB reconnect. A repeat passed immediately and confirmed modifier
release, but the first activation failure remains unexplained. Stored
byte verification alone does not prove that a newly saved timeline is active.

## Create a macro

1. Open **Macros → My Macros**. No mouse connection or authentication is needed to author macros.
2. Use **New folder** beside **New macro** to create a folder. Select a folder (or **Uncategorized**) in the library tree, then choose **New macro**. Empty folders are saved and remain available after reopening the app.
3. Enter a name, use **Add step** to enter keys, shortcuts and delays, then **Save macro**. **Location** shows the macro’s folder. Right-click a macro and choose **Move to folder…**, then save to keep the move. Search, rename through Name, duplicate or delete local macros from this view.
4. Connect a wired Naga V2 Pro with its twelve-button plate. Select and activate the intended slot in Mouse memory.
5. Open **Mouse → Customize**, choose the Normal or Hypershift layer and select a grid button or supported extra control. Choose **Macro** as its action, then select a saved macro and playback. Repeat count appears for counted playback only.
6. Choose **Save macro to mouse** in that button’s pane. The app reads macro storage, prepares a fresh upload, saves the backup and assigns it to that button in the active slot. It reuses the connected helper.

After saving a library macro, **Assign to mouse…** opens Customize with that
saved sequence selected for the current button. Review the selected button and
playback before saving the assignment. **Configure macro** opens the selected
library entry for editing; switching away from another unsaved macro offers
Save, Discard or Cancel. These links do not write mouse settings.

**Macros → Key Binds → Read mouse assignments** lists macro bindings from mouse
readback across inspected slots and layers. Filter by stored macro ID, select a
row and choose **Show button in Customize** to inspect it. Opening an inactive
slot does not activate it or change your drafts. Primary click rows are read-only.
The overview shows stored copies rather than assuming they match a similarly
named library item. Other plates, primary clicks in Hypershift and unrecognized
assignments are outside the displayed coverage. **Manage mouse storage…** opens
the separate inventory/deletion/recovery tools under Mouse memory.

The reusable library is stored in `macros.json` beside the main `profiles.json`
(by default `~/.config/NagaLibre/`). It is shared across device profiles.
**Save macro** changes only the local library. Button assignment uses the saved version;
unsaved editor changes are not uploaded. Local edits and deletion never change
existing mouse allocations. Switching library entries or quitting offers Save, Discard or
Cancel for unsaved edits. Navigating between pages keeps the current draft. A corrupt or concurrently changed library is not overwritten.

Under **Mouse → Mouse memory → Macro storage**, **Read macro storage** reads the
macro inventory. Storage usage and stored entries appear directly below it.
**Details** contains support notes, backup/journal paths and operation logs.
**Restore macro backup…** restores the button assignments from before a
NagaLibre upload and removes the macro that upload added, using its recovery
journal. It does not delete the selected inventory row.

**Delete selected macro…** removes the selected mouse entry without restoring
old button assignments or deleting anything from your local library. Read macro
storage, select a row, and choose Delete selected macro. Confirm the displayed
name and ID. If it is still assigned, the app reports the slot, layer and buttons;
change those assignments and save them before trying again.

Deletion is currently limited to unassigned NagaLibre uploads whose original
helper-owned journal remains under `backups/macros/`. Entries created by Synapse,
entries with missing journals, unknown references, and changed contents are
refused. The current reader does not establish complete reference coverage for
other plates or secondary primary clicks, so it cannot safely authorize arbitrary
existing-entry deletion. The GUI also requires the rebuilt helper to advertise
deletion support.

A private deletion backup and separate helper intent journal are saved before
the delete request. Only that ID is removed, with all inspected assignments and
other entries verified unchanged. A lost acknowledgement is resolved by readback
without blindly repeating the deletion. If readback fails, status is uncertain:
keep the backup/journal and read storage again. Deletion has no GUI undo or
automatic re-upload action; the deletion backup is retained evidence, not a
restore file accepted by Restore macro backup. This new selected-delete path
has automated coverage but has not yet been separately tested on a live mouse.

Library navigation does not start or stop the helper. Device operations share the
main window's authenticated helper; software remapping stops when storage is read.
Successful uploads and undo still end the helper session.
In Software mode, the same Macro action selects a saved sequence with **Use macro**; **Apply bindings** runs it once per press through the helper. The ordinary **Save bindings to mouse** action does not upload macro drafts.
Primary clicks are never available as mapping targets. This editor does not yet
provide event recording or import/export.

Supported timelines contain standard keyboard keys/modifiers, shortcuts, five
mouse-button outputs and millisecond waits. Every held output must be released.
Mouse movement, wheel events, text entry and program launch are not native macro
outputs in this implementation. The compiler rejects unsupported sequences.
Compilation is bounded to five minutes and 16,384 encoded records; those are
implementation bounds, not measured firmware limits. Names allow 100 UTF-8 bytes.

| Playback | Requested behavior |
| --- | --- |
| Once | Play the timeline once |
| Repeat a fixed count | Play 1–255 times |
| Repeat while held | Repeat while the target is held |
| Toggle repeat | Press to start repeating, press again to stop |
| Sequence | Advance on button presses; segmentation depends on the timeline |

A B/wait/C/wait sequence produced B on the first press, C on the second, no
output on the third and B again on the fourth. Other sequence segmentation and
the reason for the silent press remain unverified.

These modes come from the Razer host implementation. Precise timing and arbitrary
interruption/release cases still need verification. Stop toggled playback with its
button, or release held playback, before changing bindings or undoing an upload.
Waits determine timeline delays; no separate hardware turbo/rate setting is exposed.

## Storage and undo

The inventory shows actual readback and available storage. Saving always creates
a fresh entry; it preserves existing macros, including unknown contents and shared
references. Insufficient available space or unknown references cause failure.
Compaction and deletion of unfamiliar entries are unavailable. Repeated saves
consume entries; unassign old NagaLibre uploads and delete them, or restore the
matching transaction's backup rather than trying to replace an existing ID.

Before writing, the app saves a private backup under the profile directory's
`backups/macros/` folder. The helper creates a separate protected journal. Both
paths appear in the dialog log. Keep them: they contain private macro contents
and device identity. A failed backup prevents the commit.

**Restore macro backup…** selects that upload's `.journal.jsonl` file and restores original
bindings before removing only its own allocation. The helper handles protected
journal access; do not edit its ownership or contents. Recovery refuses unrelated
state changes or ambiguous allocation ownership. After a disconnect or failed
operation, preserve the journal and retry undo with the same mouse, slot and plate.
Undo is scoped to the captured controls; it is not complete profile restoration.
Free/reclaimable storage counters may change even after exact content restoration.

After a successful save, the helper exits. Representative wired physical trials
passed with the helper exited and after USB reconnect. The desktop save, full app
exit, B playback and reopening/undo flow also passed a physical trial. Explicit
power-cycle persistence remains unverified. Software mode remains available for
its supported macros and requires the helper to stay running.

The [CLI guide](CLI.md#experimental-onboard-macro-uploads) describes the controlled
hardware trial and recovery commands. [Protocol research](../inspection/MACROS.md)
records the evidence and remaining limits.
