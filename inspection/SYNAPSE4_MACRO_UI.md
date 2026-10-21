# Synapse 4 macro UI: package and served frontend

Inspected on 2026-10-21 following the user's correction that the earlier WPF
investigation covered Synapse 3 rather than Synapse 4. This follow-up traces the
actual Synapse 4 host and its currently served macro/assignment frontend. It is
static analysis, not a recording of the Windows application running.

## Source trail

The retained Razer App Engine installer extracts an Electron application:

| Artifact | Identity / SHA-256 |
| --- | --- |
| `app-engine.exe` | `56b7865f424fb4f0c92d3abd210b128a6429df9b8b026cbb6c0f80945bdf4b06` |
| `app.asar` | package name `razerappengine`, version **4.0.827**; `b2ce8c54dc5c991feef3a24e1880ced57ba88a0f40a687a5b082187ac0a1cca6` |
| Packaged `electron/main.js` | `0e3b84c11dd3e6d06072f54fb3295404894afcd7d2f7cce814ac20d9cd7d074e` |
| Packaged `electron/constants.js` | `7df3eed519fb81696dae3e7d7ac0773150758dbfbf8bce3cc88a6ca766b3eee6` |

The package identity was read from the ASAR header/data, without loading its
JavaScript. The packaged host defaults to `https://apps.razer.com` and launches
Synapse at `/synapse/dashboard/`; the constants also identify the Windows
application as `Razer.Synapse.4`. Thus looking only for a macro editor inside a
Windows DLL misses the served React application.

The dashboard HTML was fetched from that exact public route. Its Webpack runtime
identifies the `MapMacro` and `MapMacroKey` assignment chunks. `MapMacro.openMacro`
opens or activates `/synapse/macro/`, which serves a distinct frontend bundle.
The macro route's HTTP Last-Modified was **2026-10-21 04:26:42 GMT**. App Engine
4.0.827 is the packaged host version, not a claimed version of the independently
served UI.

| Official served artifact | SHA-256 |
| --- | --- |
| [Dashboard bundle](https://apps.razer.com/synapse/dashboard/static/js/main.d1d8c15b.js) | `3810e0d1af87caa449d3ecb128afdb3b4dc74ee575299041bc250a76fa496c37` |
| [Macro assignment](https://apps.razer.com/synapse/dashboard/static/js/MapMacro.d9b6a0fc.chunk.js) | `18e0ef35b40d1eac91d62f091d46a94a0023e31c41f9bd515602beedaab818f5` |
| [Macro key assignment](https://apps.razer.com/synapse/dashboard/static/js/MapMacroKey.a22f20f7.chunk.js) | `b51497de91cf50e31a6e7d43aa877bbdc8fa6d77f9165d078e0554614e39b910` |
| [Macro module](https://apps.razer.com/synapse/macro/static/js/main.f7cc2d30.js) | `9b889d4faf90703df318fdc4e81fbe4476956c02d485ede395ee0cbe2f2ede33` |
| [My Macros editor chunk](https://apps.razer.com/synapse/macro/static/js/8190.a1e2b107.chunk.js) | `228c2e033632ca23586ca5811611f915c04d243eb6589d8f35ceeabd482b87a7` |
| [Key Binds chunk](https://apps.razer.com/synapse/macro/static/js/1700.978c1608.chunk.js) | `e72f3e177ad2b3f286ff8925911c52a6ed4a1f270b2e460d6b2733bfd2f26c39` |
| [Editor CSS](https://apps.razer.com/synapse/macro/static/css/8190.5ef5dbbc.chunk.css) | `fae96b1ea43dc90da9654e1fd8816daab4a3aa92e4428e8a0f947c19410bf911` |

Downloaded code, styles, ASAR data, retrieval receipts and complete artifact hashes
remain in ignored `inspection/payload/haptic-synapse4/`. Nothing was executed in
Windows or as a frontend application. No mouse connection, native bridge call,
macro import, allocation, upload or deletion was performed. Source maps referenced
by the bundles returned 404; findings below come from the shipped minified code
and styles, not an assumed recovered original source tree.

## Confirmed organization

### My Macros is a library and authoring view

The macro module's page state explicitly defines `my-macro`, `key-binds` and
`help`, with `my-macro` as the default. The English translation bundle resolves
the first two labels as **My Macros** and **key binds**. The root component loads
module `58190` from chunk `8190` for authoring and module `21700` from chunk
`1700` for key binds.

The macro explorer has a searchable file/folder tree, new-macro and new-folder
controls, and per-item menus. Its state/actions distinguish adding, duplicating,
renaming, deleting and importing macros, adding/updating/removing event rows,
saving a macro, and discarding unsaved changes. Names and GUIDs are independent
of the later button assignment. Saved and edited macro collections are tracked
separately. The frontend uses host/window storage and local persistent state;
onboard storage diagnostics are not the primary editing UI.

The authoring component includes record/stop controls, delay settings, event
insertion and drag/drop, row editing, and undo/redo controls. The CSS gives the
event editor its own scrolling area alongside the library. Standard, Sequence
and Phased macro types appear in the frontend model; their presence does not
establish autonomous Naga V2 Pro firmware support.

### Assignment chooses a saved macro and playback

`MapMacro` maintains selected-macro, selected-playback and repetition-count state.
Its render path shows a macro dropdown followed by playback controls. Repetition
input is rendered only when the selected playback index is 1. The stepper in this
particular UI has bounds 1–99; that is a frontend constraint, not evidence of a
device limit or a reason to reduce NagaLibre's tested/requested native count range.

Its mapping payload carries the macro's name/GUID, playback option and repeat
count. A Configure/Open Macro action opens or activates the separate macro route.
`MapMacroKey` uses the current macro when constructing a key assignment. The macro
module's Key Binds view lists device/profile/button bindings and supports choosing
a device to add a binding.

Playback options are filtered by device/input capabilities and macro type. The
assignment code also distinguishes macros that require the running Synapse host.
This frontend evidence does not establish which native storage requests Synapse
uses, whether any particular macro persists in firmware, or its USB request count.

Razer's [current assignment guide](https://mysupport.razer.com/app/answers/detail/a_id/1751/kw/button%20assignments)
and [macro creation guide](https://mysupport.razer.com/app/answers/detail/a_id/1483/kw/Starting%20macro)
corroborate the create/save-first, select-macro/playback-second workflow. These
documents are corroboration, not substitutes for inspecting the Synapse 4 assets.

## Comparison before the library and device-layout passes

| Concern | Synapse 4 evidence | Current NagaLibre |
| --- | --- | --- |
| Macro identity | Named reusable library items | One sequence draft copied into a fresh upload |
| Authoring | Dedicated My Macros view and event editor | Inline table in the onboard dialog |
| Assignment | Select saved macro, button/profile and playback | Authoring and assignment share one dialog |
| Repeat count | Appears for counted playback | Contextual count already implemented |
| Stored device contents | Distinct from host authoring state | Read-only inventory hidden under On mouse |
| Diagnostics/recovery | Separate from normal authoring | Details and journal-based Undo upload |

The previous cleanup improved inline editing and contextual controls, but a
two-panel upload dialog is not the same workflow as Synapse 4's reusable macro
library. The most consequential next UI work is a persistent local macro catalog,
with selection/create/rename/duplicate and an editor, followed by a separate
assignment step choosing the local macro and playback. Onboard inventory and
recovery should remain distinct tools. Local catalog edits must not rewrite
existing mouse allocations or imply that an unchanged local draft is active.

This is a concrete design direction derived from the current frontend. A local
catalog would be a new NagaLibre feature, not a claim that reusing, editing or
deleting arbitrary existing firmware entries has been implemented. This follow-up
changes research documentation only; it does not add a recorder or change the
already implemented upload/backup/undo contract.

The subsequent [Device167 layout pass](SYNAPSE4_LAYOUT.md) traces the actual device frontend and corrects assignment placement: Macros now embeds authoring, while Customize assigns a saved macro to the selected physical button.
