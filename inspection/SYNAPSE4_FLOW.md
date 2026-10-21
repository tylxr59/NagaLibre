# Synapse 4 macro lifecycle follow-up, 2026-10-21

This pass extends [macro frontend provenance](SYNAPSE4_MACRO_UI.md) and
[Device167 assignment provenance](SYNAPSE4_LAYOUT.md). It inspects shipped assets
statically and independently adapts supported interaction patterns in PySide6.
It does not execute Razer JavaScript, native bridge calls or Windows binaries.

## Rechecked sources

Re-fetched the public Macro and Device167 entry pages. They still reference
`main.f7cc2d30.js` and `main.05d42904.js`, respectively. Their Last-Modified values
remain 2026-10-21 04:26:42 GMT and 04:32:55 GMT. Entry-page hashes are
`027608f3850a70746505f1a3e3c258fa5b7d6b91f740cc4cb41b9485a508f8ee` and
`d7e01a1d785a9a4689dd5ba811c1263f6c086c2135a421800185f7d167543e0e`.
Inspected the retained main, authoring, Key Binds, Device167 MapMacro and
ButtonPanel chunks whose hashes are recorded in the earlier research.

Razer's [Synapse 4 master guide](https://dl.razerzone.com/master-guides/RazerSynapse4/Blade16-00000736-en.pdf),
pages 26–28, corroborates separate authoring and binding views. Its screenshots
show the macro selector/menu, authoring controls and device assignment entry
point. Retrieved PDF SHA-256:
`3c5d232c2dc7c8c28b320d47035e7d132e4a3ba22e25860315305d4205a3b8ed`.
This is UI corroboration from a Blade guide, not Naga firmware evidence.

Retrieval receipts, static anchor offsets, downloaded HTML/PDF and all retained
proprietary payloads remain ignored under `inspection/payload/haptic-synapse4/`.
No proprietary code, screenshots, fonts or artwork are added to source control.

## Observed flow and limits

| Evidence | Interpretation |
| --- | --- |
| Macro module navigation defines authoring and Key Binds pages. The Key Binds chunk uses a connected-device list and an assignment popup. | Users can move between editing a reusable macro and reviewing/creating device bindings. |
| Device167 MapMacro's mapping payload uses name/GUID plus playback/count; its configuration link opens/activates the macro module. | Assignment and authoring are linked, with a saved definition independent of the selected physical button. |
| Macro deletion uses a confirmation component before dispatching the library delete action. The `zs` reducer removes GUIDs from the folder/profile tree, edited macro list and saved macro list. | Library deletion changes the host catalog, rather than selecting an arbitrary raw storage ID. |
| `Js` serializes saved definitions and `qs` writes host storage, persistent macro data and config. The reducer's persistence path references a macro-deleted notification. | Device/host synchronization exists, but these functions alone do not establish every resulting firmware write or button reset. |
| The authoring chunk contains low-level macro deletion methods, among many device APIs. | Merely finding a delete method does not prove that the library delete UI invokes it for a particular device. |

Reproducible anchors in the retained macro main bundle, measured as UTF-8-decoded
character offsets: delete reducer `zs` at 737346, delete dispatch case at 754050,
and the persistence tail following the macro-deleted notification around 755805.
The Device167 MapMacro save/configuration path is around 2850–4850; rendering of
macro/playback selection and the configuration link begins around 7470. These
are identifiers/positions for research, not copied implementation code.

There is no evidence here to equate deleting a host macro with verified deletion
of every Naga V2 Pro storage allocation or to replace NagaLibre's ownership,
reference, stale-state, backup and recovery checks. Running application behavior,
native request ordering, performance and complete firmware reference coverage
remain separate questions.

## Independent NagaLibre adaptation

Macros now contains **My Macros** and **Key Binds**. Saved authoring exposes
**Assign to mouse…**, which opens Customize for the selected button with the
saved library entry selected; it sends no helper command. Edits must be saved
before this action is enabled. **Configure macro** in the assignment pane opens
the chosen library entry, honoring Save/Discard/Cancel for another unsaved draft.

Key Binds uses actual mouse readback, showing stored macro names/IDs, slot,
layer, physical control and playback. Equal names stay distinct by ID. Filtering
does not guess a relationship to a local catalog item: NagaLibre's fresh-upload
GUID and the reusable local catalog identity are different. Missing stored IDs
and unknown assignments remain visible or explicitly reported, rather than
implying a complete reference census.

Reading is explicit and reuses the existing shared helper/preview operation;
opening the page sends no requests. A row can open the corresponding scoped
button in Customize, including an inactive slot or Hypershift control, without
activating, copying drafts, uploading or writing settings. Primary click rows are
read-only. Readback clears on failed reads, disconnects, new connections and
subsequent onboard mapping events. Intentional successful-save helper exit keeps
the verified snapshot with a last-readback indication.

Mouse memory retains explicit inventory deletion and backup recovery. Local
library deletion does not rewrite mouse memory. This pass does not add recording,
global input capture, arbitrary firmware editing, automatic library-to-firmware
updates or a Synapse native bridge. Those require their own implementation and
evidence; no unsupported controls are shown as working features.
