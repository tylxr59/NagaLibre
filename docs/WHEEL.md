# Standard wheel modes

NagaLibre supports the Naga V2 Pro's five standard HyperScroll Pro modes over
USB with the twelve-button plate attached:

| Mode | Intended feel |
| --- | --- |
| Standard | Normal, default wheel movement |
| Distinct | Firm, clearly separated ticks |
| Ultra-fine | Softer movement with many small steps |
| Adaptive | Smoother scrolling as you turn faster |
| Smooth Scroll | Smooth movement with little tactile resistance |

These names and descriptions follow the device's preset associations. All five
feels and mode-button cycling were physically checked. USB persistence was
explicitly confirmed for Standard, Ultra-fine and a reordered two-mode list.
The new desktop workflow has automated Qt coverage; separate physical GUI
verification remains outstanding. Receiver/Bluetooth wheel programming is disabled.

## Choose and save modes

1. Build the source engine with `cargo build --release --locked`, then launch
   NagaLibre using the normal unprivileged launcher.
2. Connect/rescan the mouse and open **Wheel settings…**. Opening this dialog
   stops software remaps and releases their held outputs/grabs.
3. Read the wheel. **Stored** shows the active slot, current mode and cycle order.
4. Check the standard modes to include in cycling, drag them into the desired
   order, and choose the active mode. The description follows your choice.
   These edits change only the local draft.
5. Click **Save wheel stages to mouse**. NagaLibre durably saves a private backup,
   checks that the mouse still matches the read snapshot, writes the stage
   selection/order and verifies the result. Wait for completion before closing.

Keep at least one standard mode enabled. An unchanged draft does not write.
Invalid selections keep the last read so you can correct the draft. Unknown
stored stages make the dialog read-only rather than dropping them.

A successful save stops the helper and leaves the selection on the mouse.
Click **Read wheel** before another save. After closing the dialog, reconnect
through the main window if you want to read/edit button bindings again. Check
physical feel, scrolling and primary clicks separately from reported readback.

**Use wheel stage defaults as draft** enables the five standard modes in their
normal order and selects Standard locally. It does not write until saved and
does not reset button bindings. Existing Custom entries remain preserved.

## Backups and failures

Wheel stage backups are separate from binding backups. **Restore wheel backup…**
accepts the wheel transaction format and restores captured selection/order.
It does not restore firmware, generate curves or restore unknown macro contents.
Backups are stored privately beside your profile under `backups/`; retain them.

Preparation captures paired mappings and readable wheel state across initialized
slots before any stage write. A stale snapshot or backup/fsync failure prevents
writes. A failed write acknowledgement triggers rollback because it may have
landed. If rollback cannot be verified, retain the backup and reported error;
do not assume stopping the app restores mouse memory.

Only stage selection/order is changed. Existing Custom curves/metadata, bindings,
other slots and device mode are preserved within the captured readback scope.
Inactive Custom metadata can be unreadable, and stored Custom table getters can
alias; these stage backups are not complete independent curve/firmware images.

## Custom editing is deferred

Custom tension, steps and up/down curve editing are a later TODO. The dialog
preserves an existing Custom entry as read-only. If Custom is already active,
that fact remains visible until you choose a standard mode; it is not silently
replaced when reading. Custom is not offered as a new selectable mode.

**Show read-only wheel details** exposes diagnostic metadata and reported table
counts. Metadata may describe editor intent without proving the actual waveform.
Changed Custom uploads acknowledged but did not produce matching readback, so
new Custom upload experiments are blocked pending the save/commit investigation.
Use the standard modes normally; see [CLI diagnostics](CLI.md#hyperscroll-pro-standard-modes)
for read-only inspection when needed.
