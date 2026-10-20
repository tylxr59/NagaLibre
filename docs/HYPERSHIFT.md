# Hypershift in the desktop app

Hypershift gives a control a second assignment while you hold a designated mouse
button. NagaLibre supports editing it on the **wired Naga V2 Pro with the
twelve-button plate**, in the active onboard slot and normal device mode.
The desktop flow has passed draft-only, save and exact paired-restoration checks.
The user confirmed physical hold/release, primary clicks, USB reconnect persistence
and restored original outputs for a DPI-button/grid-1 test.

Receiver Hypershift programming, other plates and software Hypershift are not
enabled. Normal-only receiver support is unchanged; use USB for Hypershift profiles.

## Edit both layers

1. Connect by USB, launch `./nagalibre`, choose **Mouse memory**, and click
   **Connect mouse**. Authenticate in the desktop prompt. Wait for the plate and
   both stored layers to be read.
2. Select the active slot. If you want to start from its current assignments,
   click **Use stored bindings as draft**. Reading alone preserves your local
   edits; this explicit copy updates both drafts while retaining learned inputs.
   Unknown actions become **Keep stored binding** and retain their exact bytes.
3. In **Normal layer**, select a button, such as **DPI button**, and choose
   **Hold for Hypershift**. Scroll the button grid to reach auxiliary controls.
4. Select **Hypershift · while held**, select a control, and choose a key,
   shortcut or disabled action. Trigger assignments are only available in the
   normal layer. Nested triggers and onboard macros are unsupported.
5. Click **Save bindings to mouse**. The app prepares both drafts, durably backs
   up both banks in every initialized slot, then acknowledges the save. Backup
   failure prevents settings writes. Successful readback stops the helper; the
   assignments remain in firmware after the app exits.

Each tile separates its stored binding from the draft. Hover a tile for its full
label. **Save draft** writes only the local profile. **Keep stored binding** sends
no edit for that control. **Clear Hypershift draft** sets all secondary drafts to
Keep stored binding; it does not erase stored secondary assignments. Normal
**Restore defaults** changes the normal draft only and preserves secondary edits.
To disable a stored secondary assignment, choose **Disabled** and save to mouse.

Local V2 Pro profiles migrate from version 1 to version 2 in memory, preserving
normal edits, other plates, macros and learned inputs. New secondary drafts all
keep stored bindings. Opening a file does not rewrite it or change the mouse;
the migrated profile is written on the next explicit save.

## Backups and slots

The save log shows the private paired backup path under the profile's `backups`
directory. **Restore backup…** accepts those paired backups and older normal-only
mapping backups. Paired restore requires the original active slot, inventory,
mode and unchanged other slots. A legacy normal backup restores its normal
records while preserving freshly read secondary actions; it never invents a
secondary default bank. Diagnostic exports are not restoration backups.

Existing-slot activation on the wired paired path backs up and verifies both
banks, without writing bindings. Slot creation also backs up and checks existing
secondary records. Create new slots before configuring Hypershift, or restore
the paired backup first: the allocator still requires normal zero-tag records.
No existing slot is deleted.

## Physical desktop verification

Keep USB and the twelve-button plate attached. Quit NagaLibre with **Ctrl+Q**
before each independent check below; closing to the tray is not quitting.

```sh
python3 scripts/check_hypershift_gui.py prepare
./nagalibre
```

The read-only prepare backs up all initialized slots and prints an `original.json`
path. In the GUI, connect, click **Use stored bindings as draft**, set normal DPI
to **Hold for Hypershift**, and set secondary grid 1 to **B**. Click **Save draft**
only, quit, then check that the mouse is unchanged:

```sh
python3 scripts/check_hypershift_gui.py staged
./nagalibre
```

Connect again and click **Save bindings to mouse**. Once the save completes,
check the normal grid-1 output, B while holding DPI, return to normal on release,
and left/right/middle clicks. Quit, unplug/reconnect USB and repeat. Then run:

```sh
python3 scripts/check_hypershift_gui.py saved
./nagalibre
```

Connect and use **Restore backup…** to select the `original.json` printed by
prepare. Wait for exact restoration, quit and check:

```sh
python3 scripts/check_hypershift_gui.py restored
```

Confirm original grid-1 output, DPI cycling and primary clicks. Optionally
reconnect in the GUI, click **Use stored bindings as draft**, then **Save draft**
to replace the local test edits with the restored bindings. All four verification
commands send getters only and retain private evidence. Report physical results
separately from readback. Keep all backups if a check fails.
