# Media and scrolling assignments

On the wired Naga V2 Pro with the twelve-button plate, **Media / scrolling**
offers volume up/down, mute, play/pause, stop, next/previous track and scrolling
in four directions. These assignments are experimental: automated save/recovery
tests pass, but their new physical outputs and hold/release behavior have not
been independently verified on the mouse.

1. Connect by USB, choose **Mouse memory**, and connect the mouse. Wait for the
   stored bindings to appear, then select the active slot.
2. Click **Use stored bindings as draft** to start from the current assignments.
3. Select a side button or auxiliary control in either layer. Choose
   **Media / scrolling** and the desired action.
4. **Save draft** stores only local edits. **Save bindings to mouse** backs up
   both layers in every initialized slot before applying the changes. Keep the
   backup path shown in the log; **Restore backup…** restores the exact mappings.

Successful saving stops the helper. Firmware handles the stored assignment;
the helper does not need to remain running. Media output still depends on the
desktop/player handling it. No custom repeat rate is configured for scrolling.

Receiver connections, Bluetooth, smaller plates and Software mode cannot save
these new actions. Existing key, shortcut and mouse-click choices are unchanged.
Sensitivity and profile-navigation records may now have readable stored labels,
but cannot be newly assigned here. A temporary-DPI label reports its raw X/Y
values and unverified release behavior. Unknown actions remain preserved.

Protocol findings and the remaining verification work are in
[the native-action research](../inspection/NATIVE_ACTIONS.md).
