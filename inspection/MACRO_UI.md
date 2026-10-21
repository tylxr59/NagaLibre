# Macro authoring and assignment UI

**Synapse 4 follow-up:** [SYNAPSE4_MACRO_UI.md](SYNAPSE4_MACRO_UI.md) traces the
actual Electron host and current served macro/assignment bundles. Use that report
for current UI organization. The older WPF evidence below remains Synapse 3 only.

Static inspection on 2026-10-21 used the previously extracted official Synapse
core package **3.11.0228.012810**, SHA-256
`8f0cd09b919daf438209073502b494aa83df7009538503350728538e8aa40e20`.
Package provenance is in [HAPTIC_WHEEL.md](HAPTIC_WHEEL.md#verified-enum-ui-text-and-wire-association).
These are shared Synapse 3 WPF assemblies, newer than Device167. They do not
establish the current Synapse 4 layout or any native firmware behavior.

| Assembly | SHA-256 |
| --- | --- |
| `Razer.Synapse3.AssignMacro.dll` | `7bea165f677fd6ac1c111989fd180c09321f8fa3e814ed08612d45a3df2d8772` |
| `Razer.Synapse3.MacroModel.dll` | `aeeadffa24ef143298ff9368ce7d205de6828eca5b5b6ddfb836d86b958102fb` |
| `Razer.Synapse3.MacroKeybindControl.dll` | `64c6ed50d8ba6309de2c38cd769c5cee31218a2d289f438bdfeaee8d84ebdf01` |
| `Razer.Synapse3.MacroPropertiesControl.dll` | `657faa78ceaf9b01d4001b8a13e3af521812798abb9e5ba8ced1094004b2aac8` |

Managed metadata and CIL method bodies were read directly using the existing
private dnfile/dncil environment. Windows code was not executed. The configured
Ghidra MCP project reported a lock; it was left untouched. Managed UI assemblies
were inspected through CIL instead. Raw IL and proprietary binaries stay under
ignored `inspection/payload/`; this document contains only findings and provenance.

## Direct findings

- `AssignMacro.ComboBox_SelectionChanged` (RVA `2074`) updates the selected macro
  and enables/disables playback controls based on macro type. The model exposes
  separate available-macro, selected-macro, new-macro and playback properties.
- `AssignMacro.ddlPlayback_SelectionChanged` (RVA `20e0`) updates the selected
  playback option, then makes the repetition-count container visible only for
  option ID 1. Other options collapse that container rather than leave an
  irrelevant disabled count field on screen.
- `AssignMacro.btnAddMacro_Click` (RVA `254c`) creates a macro through the macro
  client, adds it to the available-macro collection and selects the macro module
  in the host's plugin menu. Authoring is a separate concern from assigning an
  existing macro to a button.
- `MacrosConfigrationModel.PreparePlaybackOption` (RVA `2458`) constructs ordinary
  playback options from supported enum values. Device-specific handling also
  exists; this does not justify enabling every option on every model.
- `KeyBindControl.btnMacroSave_Click` (RVA `2814`) signals the keybind viewmodel's
  Save action. Its playback-selection handler (RVA `2838`) separately controls
  repetition visibility. These UI handlers do not establish onboard allocation,
  deletion or firmware persistence semantics.
- `PropertiesControl` and `KeyBindControl` are distinct shared controls with
  separate layout/viewmodel responsibilities. No complete macro editor plugin
  implementation was recovered in this inspection.

## NagaLibre presentation decisions

The sequence editor and button-assignment controls are now separate adjacent
panels. This is a layout interpretation of the separation above, not a recovered
pixel-for-pixel Razer screen. Sequence rows are editable directly; a nested modal
is no longer needed to enter each macro. Software macro dialogs share the same
sequence widget.

The repeat count is shown only for counted playback. A toggle-specific stop hint
appears only for toggle playback. Name byte limits move to a tooltip; validation
still enforces them. Inventory, raw IDs/sizes, storage accounting, support notes
and logs are available through explicit On mouse/Details controls rather than
dominating the authoring form. Visible errors still report failures.

Existing onboard entries remain a read-only inventory. NagaLibre still uploads
a fresh macro with its original backup/journal/undo transaction; it does not
pretend to support Razer's existing-macro library editing, in-place updates,
deletion or a recording feature. No new hardware operations or repeat scans were
added. Local field-validation errors now retain valid mouse readback so users can
correct the form without an unnecessary refresh.
