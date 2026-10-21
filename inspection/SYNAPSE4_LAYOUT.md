# Synapse 4 device layout: second binary/UI inspection

Inspected 2026-10-21 after the user flagged the redundant launcher page and
separate macro-target selector. This pass traces the actual retained Windows
package to the **Naga V2 Pro device frontend**, extending the earlier
[macro-module inspection](SYNAPSE4_MACRO_UI.md).

## Binary and route provenance

Read the ASAR header and embedded package/JavaScript directly from the retained
`app-engine.exe` extraction. No Windows executable or downloaded JavaScript was
executed.

| Artifact | Identity / SHA-256 |
| --- | --- |
| `app-engine.exe` | `56b7865f424fb4f0c92d3abd210b128a6429df9b8b026cbb6c0f80945bdf4b06` |
| `win-unpacked\resources\app.asar` | `b2ce8c54dc5c991feef3a24e1880ced57ba88a0f40a687a5b082187ac0a1cca6` |
| Embedded `package.json` | `razerappengine`, **4.0.827** |

Embedded `electron/main.js` identifies `https://apps.razer.com` as the production
host; `electron/constants.js` identifies `/synapse/dashboard` as the Synapse
route. The dashboard's shipped `App.70b4a4e6.chunk.js` module `39709` constructs
`/synapse/products/${productId}/ui/index.html?containerId=…` for the selected device.
Followed that exact template with the already established Naga V2 Pro product ID
167. The resulting device bundle explicitly identifies vendor 5426, product 167,
dongle 168, BLE 169, `isNaga: true`, and `deviceName: "Razer Naga V2 Pro"`.
The package version is the App Engine host version, not an invented version of
its separately served frontend.

Fetched the device entry page from
[the official Device167 route](https://apps.razer.com/synapse/products/167/ui/index.html).
Its script/style links and Webpack runtime resolve these assets:

| Official asset (under `/synapse/products/167/ui/static/`) | SHA-256 |
| --- | --- |
| [js/main.05d42904.js](https://apps.razer.com/synapse/products/167/ui/static/js/main.05d42904.js) | `ca2c2662375a15677d2a453fd96e9620362c7184f8c68032cb9768f69302326b` |
| [css/main.5703083b.css](https://apps.razer.com/synapse/products/167/ui/static/css/main.5703083b.css) | `b5741bc7c5052f5937f94650b941ebf4ee067769d641bc9b9235576461804aa3` |
| [js/ButtonPanelComponent.01e092db.chunk.js](https://apps.razer.com/synapse/products/167/ui/static/js/ButtonPanelComponent.01e092db.chunk.js) | `64bdb274c95a7ebc38fcff18e5581e6dee6bc7f74381d27632925daad0250956` |
| [js/977.94d0439b.chunk.js](https://apps.razer.com/synapse/products/167/ui/static/js/977.94d0439b.chunk.js) | `73fea031fddc46a2f5768bd107c03eb2e2bff1fbc13d1a5d464eb1e24e4856d2` |
| [js/MapMacro.ab756bc2.chunk.js](https://apps.razer.com/synapse/products/167/ui/static/js/MapMacro.ab756bc2.chunk.js) | `e3f7abc50157d90c16480dcead048a1286eae129cf445391d714bfcdcee2c0f4` |

The fetched drawer/mapping chunks reported Last-Modified
**Wed, 21 Oct 2026 04:32:55 GMT**. Payloads and retrieval metadata remain ignored
under `inspection/payload/haptic-synapse4/layout-pass/`. No Razer fonts, images,
JavaScript, installers or compiled binaries are included in NagaLibre's sources.

## Confirmed structure and interpretation

| Shipped implementation evidence | Meaning for NagaLibre |
| --- | --- |
| Device `nav-tabs` contains `profile-wrapper` and `navs-wrapper`; `visibleNavs` renders selected local views. Constants include Customize, Performance, Scrolling, Lighting, Calibration and Power. | Use device-local tabs and a shared profile/slot context. Show the functions we actually implement; constants alone do not establish supported hardware behavior. |
| `config-wrapper`, `config-ctx`, physical button callouts, `sidepad-clickarea` and `config-btns` connect a selected mouse control to assignment state. | Assignment belongs to the selected physical control in Customize. Keep our supported plate grid usable beside the assignment pane. |
| Lazy drawer chunk 652 is `ButtonPanelComponent`; its `activeButton`, `updateActiveButton` and `clickBtn` connect the selected control to the drawer. | Do not require a second target-button selector inside a macro window. |
| Device CSS positions `.config-drawer` at the left, width 230 px, with a scrolling `.config-drawer-content`. | Put the selected button's assignment pane to the left of the grid. Adapt width to Qt controls and supported screen sizes. |
| Device `MapMacro` reads `activeButton`, uses `selectedMacro`, `selectedPlayback`, `playbackTimes`, `changeMacro`, `changePlayback` and `enableSave`. | Macro is an assignment category alongside key/shortcut actions. Select a saved macro and playback there. |
| The separately served Macro module has its own searchable explorer and event authoring area, as traced in the earlier inspection. | The Macros workspace itself should contain the library/editor, rather than another launcher. |
| Main device stylesheet uses a `#222` main container, dark drawer and controls, and green active accents. | Use a neutral dark palette and green selection/save accents while retaining independent branding. |

The earlier pass correctly separated **macro identity** from **button assignment**,
but placed the assignment in the wrong part of our navigation. A reusable macro
should remain independent of one target; assigning it should happen immediately
from the selected button, as other action types do. Razer's
[Synapse 4 assignment transcript](https://dl.razerzone.com/videos/transcripts/How%20to%20assign%20macros%20in%20Razer%20Synapse%204.pdf)
corroborates that device → button → Macro → saved macro/playback → Save flow.

This is static layout and state-flow evidence. It does not establish native
request counts, device timing, Linux authentication policy, arbitrary firmware
macro editing/deletion or runtime fidelity of every Windows screen. NagaLibre
continues to use its own tested fresh-upload/backup/undo protocol. Its physical
mapping allowlist and unverified-feature limitations remain in force.
