# NagaLibre roadmap

Work through this in small, independently reviewable chunks across sessions.
Start with the first unfinished chunk in the chosen feature; completing the
whole feature in one session is not required. No session-length estimates are
implied: protocol research and physical testing can take unpredictable time.

Read [AGENTS.md](AGENTS.md) before implementation and [HANDOFF.md](HANDOFF.md)
before changing hardware behavior. This file tracks planned work; HANDOFF.md
records implementation status and actual hardware evidence. Update both as work
lands, distinguishing implemented, readback-verified and physically tested.

## Scope and priorities

Focus on mouse functionality beyond OpenRazer's current Naga V2 Pro API.
OpenRazer coverage varies by model: some other mice already expose wheel modes
and related settings. Recheck upstream before implementing overlapping controls.

Suggested order: finish existing control verification, then Hypershift, haptic
wheel settings, onboard macros, and broader profile management. Sensor settings
and automatic application profiles can be developed separately.

Already implemented: USB faceplate detection, supported onboard button bindings,
stored/draft separation, device-reported slot capacity, slot creation/activation,
software one-shot macros, per-device defaults, and device-support diagnostics.
Implementation does not imply every hardware path is verified.

## 1. Finish existing controls and slot verification

- [x] Read and physically verify the DPI-cycle button (logical 16, wire 0x60).
      Wired slots 1/2 read category 6/data [6]. User confirmed physical sensitivity
      cycling, remapping to B, and cycling again after exact mapping restoration.
      Other tracked records/slots checked unchanged; DPI stage values themselves
      were not read, so unchanged stage-table values remain unverified.
- [x] Verify factory horizontal tilt actions on both sides, right-tilt remapping,
      and the scroll-mode button. Left tilt -> B was physically confirmed and
      exact original records were restored. Factory horizontal scroll in both
      directions was confirmed during the desktop defaults test.
      Right tilt -> B and primary clicks are now physically confirmed, followed
      by exact mapping restoration. Reconnect getter failed; persistence remains
      unverified. Original right tilt was F14, not factory horizontal scroll.
      Scroll-mode cycling, remapping to B, USB reconnect persistence, restored
      cycling and primary clicks passed; exact restoration/readback verified.
- [x] Exercise Restore defaults as a draft-only operation, then save and verify
      the supported defaults with exact restoration afterward. It currently
      restores bindings, not wheel tension, DPI tables or other device settings.
      Draft-only unchanged-state check, all sixteen saved defaults, physical
      outputs/primary clicks and exact original-slot restoration passed over USB.
- [x] Test standalone slot activation and desktop slot creation, including
      app exit/reconnect persistence and unchanged original slots. The temporary
      slot-3 allocation/read/removal trial already succeeded.
      Desktop activation of slot 2, switching back to 1 and creation of slot 3
      passed independent readback with both original slots' mappings exact.
      New-slot activation, physical grid/primary clicks before and after USB
      reconnect, and final return to slot 1 passed. Slot 3 remains initialized.
- [x] Verify representative onboard shortcuts/mouse outputs and the Qt/polkit
      workflow. Ctrl+A, modifier release, side-button right click and primary
      clicks passed over USB, with other records/slots exact and exact restore.
- [x] Verify receiver onboard operation with the twelve-button plate. Detection,
      all-slot backup, GUI save, physical shortcut/mouse outputs, power/reconnect
      persistence and exact restoration passed on 00a8. Slot 1 is active again;
      initialized slots remain [1, 2, 3]. Receiver software remapping and other
      plate/slot/action combinations are not established by this test.
- [ ] Deferred at the user's request: six-/two-button software mapping checks.
      Existing software-engine evidence remains valid; these physical plate
      mappings are unverified. Continue with section 2 rather than revisiting
      this deferred item automatically.

## 2. Hypershift

Goal: a secondary assignment layer available while holding a designated button.

- [x] Research chunk: document normal/Hypershift bank selection and trigger
      encoding from both Device167 wired/receiver controllers. Layer byte is
      0/1 with unchanged button IDs; trigger category 0c/length 1/data 01.
      [Protocol findings and unresolved firmware limits](inspection/HYPERSHIFT.md)
      distinguish static evidence from unverified held/release behavior.
- [x] Read-only chunk: enumerate secondary-layer records and preserve unknown
      actions in snapshots without changing existing normal-layer behavior.
      Implemented `onboard-layers` and private `scripts/inspect_layers.py` export;
      both-bank double reads, raw preservation and state/plate guards tested.
      Wired forensic capture passed all sixteen scoped records twice; both
      connections echo layer 0. Captured tilt actions differ from normal while
      grid 1/2 differ only in wire encoding. Implemented a V2 Pro-specific
      zero-echo reader that preserves observed echoes and exact raw bytes.
      Secondary primary state is unknown. Legacy normal-only commands retain
      their scope; the new wired GUI uses paired transactions.
      Parsed wired export passed all sixteen records with echo 0 retained.
      Wired held/release behavior subsequently passed the physical trial below.
- [x] Engine chunk: add layer-aware preparation, durable backups, stale checks,
      changed-action writes, readback and exact rollback within permitted IDs.
      Initial scope: wired active slot, normal mode, twelve-button plate.
      Both banks/all initialized slots backed up and checked. Session token and
      private staged trial implemented. Wired isolated write and physical held
      trial passed, followed by exact original paired restoration.
- [x] UI chunk: normal/secondary drafts, normal-layer Hypershift trigger, sparse
      keep/disabled actions, stored-to-draft copy, paired save/restore and v1→v2
      profile migration implemented. Unknown raw actions are preserved. Backup
      fsync failure prevents commit. Mock QProcess save/reconnect/restore passed.
- [x] Hardware chunk: one wired secondary assignment plus its trigger, release
      back to normal, and exact paired restoration. User confirmed expected
      Hypershift physical results; apply/verify readbacks and restored status passed.
      The reverse-echo failure, guarded recovery and successful isolated write
      probe are documented in inspection/HYPERSHIFT.md.
- [x] Confirm primary clicks, physical USB-reconnect persistence and physical
      post-restore outputs for the held trial. User explicitly confirmed all
      passed. Receiver Hypershift remains unverified.
- [x] Final desktop physical check: `scripts/check_hypershift_gui.py`
      prepare/staged/saved/restored passed through GUI edits and backup
      restoration. Staging changed nothing; saved trigger/B and untouched state
      verified; every original paired record, echo, slot and device state restored
      exactly. User confirmed hold/release, primary clicks, USB reconnect and
      original outputs/DPI cycling after restore. Wired twelve-button scope is
      complete; receiver Hypershift remains unverified. See docs/HYPERSHIFT.md.

## 3. HyperScroll Pro haptic wheel

Goal: configure wheel feel, beyond remapping the scroll-mode button.
**Standard modes are implemented. Custom editing is deferred at the user's request.**
Custom remains deferred; #4 is complete. Continue with #5 when roadmap work resumes.

- [x] Research and read-only capture: wired native formats, preset names, mixed
      endian fields, table chunking, stage IDs versus enabled-list positions,
      metadata and receiver gating documented. Unknown bytes are retained.
      Inactive metadata rejection is explicit unknown state. Firmware reports
      1.2 with no patch. See [wheel protocol](inspection/HAPTIC_WHEEL.md) and
      [firmware investigation](inspection/HAPTIC_FIRMWARE.md).
- [x] Standard mode engine/session: Standard, Distinct, Ultra-fine, Adaptive and
      Smooth Scroll selection, enabled cycle list/order, durable paired/wheel
      checkpoints, stale checks, failed-ack rollback and exact restoration.
      Saving standard modes writes no curve, metadata or binding values.
- [x] Standard mode desktop UI: descriptions, enable/reorder, active selection,
      draft-only wheel defaults, stored/draft separation and backup restoration.
      Existing Custom entries are preserved/read-only; unknown modes block saves.
      Invalid drafts keep the last read, unchanged saves skip writes, and closing
      cannot interrupt an operation. See [desktop wheel guide](docs/WHEEL.md).
- [x] Built-in tactile trial: all five named feels and five-press cycling passed,
      with normal scrolling/primary clicks and original Smooth feel restored.
      Standard/Ultra-fine reconnect and reordered [85,81] persistence explicitly
      passed; do not infer every mode's persistence from these observations.
- [ ] Additional desktop physical verification of the new Wheel settings dialog.
      The engine paths have controlled hardware evidence; desktop interactions
      have automated Qt/failure coverage, not a separate physical GUI trial.
- [ ] **Deferred Custom:** establish the save/commit lifecycle and independently
      verify changed cached/flash/operational data plus recovery before exposing
      tension, steps or up/down curves. Stored-profile table getters alias CW;
      selector-zero reads can expose flash rather than uncommitted cache.
      Candidate velocity uploads acknowledged but read back unchanged, so Custom
      selection was blocked and current visible state restored. Historical
      pre-replay independent values are unknown. Do not substitute defaults.
      New custom probe/upload/replay applies are disabled; recovery routes remain.
- [ ] **Deferred Custom UI/physical checks:** implement verified bounds and curve
      generation, separate metadata intent from actual tables, and test one
      changed parameter at a time with physical/reconnect/restoration observations.
      Synapse's 0–100 tension and8–96 steps are UI ranges, not proven device bounds.

## 4. Onboard macros and richer playback (complete)

Complete for the implemented wired V2 Pro/twelve-button scope. Representative
CLI and desktop hardware trials passed. Broader coverage remains experimental.
See [the macro guide](docs/MACROS.md) and
[protocol evidence](inspection/MACROS.md).

- [x] Research: inventory, capacity, IDs, compact events, delays, metadata,
      allocation/upload, bindings and deletion traced through Device167.
      Unsafe native empty-GUID deletion and format/rebuild compaction excluded.
- [x] Read-only inspection: double content reads, opaque preservation and
      scoped all-slot paired mapping/state checks. Capacity/count and nonempty
      ID/size/metadata/data getters passed wired trials. Reported capacity 100;
      arbitrary firmware event/storage limits are not established.
- [x] Transaction: fresh allocation, chunked upload, exact readback before binding,
      durable private backup, protected ownership journal and interrupted undo.
      Restore original references before deleting only its own allocation.
      Existing macros remain intact; reference coverage is explicitly incomplete.
- [x] Playback: once, counted 1–255, held, toggle and sequence implemented.
      Keys/modifiers, chords, mouse-button outputs and waits compile; unsupported
      or unbalanced timelines fail. No dedicated turbo/rate capability claimed.
- [x] Desktop: inventory/storage, sequence editing, playback, durable backup,
      journal-based undo and draft/readback separation implemented. Physical
      save, full app exit, B playback, primary clicks and reopening/undo passed.
- [x] Representative wired trials: once, count 3, held repetition and toggle
      start/stop passed with primary clicks, USB reconnect and exact scoped
      cleanup. B/wait/C/wait sequence yielded b, c, silent, b on four presses.
      A repeated Shift+B/C trial passed Bc and manual lowercase d, confirming
      modifier release. The earlier held trial reported no failure, but its saved
      wording did not explicitly describe cessation on release.

Completion accepted on 2026-10-21 after successful shortcut retesting and desktop
save/app-exit/playback/restore testing. The user removed the earlier activation
observation as an open blocker; its evidence remains in HANDOFF.md.

Coverage limits: explicit power cycling, native mouse outputs, additional targets/
layers, existing shared contents and more timing/sequence boundaries are not all
hardware-verified. Compaction, complete-profile recovery and other connections
remain outside this completed scope. Broader verification continues under #9.

The initial recovery timeout received an unrelated reply while OpenRazer was
running. Recovery succeeded after stopping its daemon; keep other controllers
closed during these transactions. Detailed observations and private-evidence
locations are retained in HANDOFF.md.

## 5. Richer native button actions

Static research and the first media/scroll implementation chunk are complete;
the feature remains open. See [native-action findings](inspection/NATIVE_ACTIONS.md)
and [desktop usage and limits](docs/NATIVE_ACTIONS.md).

- [x] Decode wired sensitivity records: up/down, stage selector, temporary X/Y
      DPI and cycle directions. Native encoder/decoder, named JSON and managed
      on-press conversion agree. Stored labels implemented; this is static
      evidence, not firmware release-behavior verification.
- [ ] Establish sensitivity bounds/stage numbering and current-DPI readback;
      implement bounded assignments and physically verify temporary DPI restores
      on release. Only the existing factory DPI-cycle assignment is writable.
- [x] Investigate firmware profile cycling/selection as button assignments.
      Four category-07 navigation records traced. They encode no slot/GUID;
      managed keymap selection/clutch is a separate host path. Direct firmware
      slot selection and navigation/release semantics remain unverified.
- [ ] Implement profile navigation after establishing active-slot guards and a
      recovery/test procedure that returns to the original slot before restore.
- [x] Add seven traced consumer/media actions and four scrolling directions with
      explicit labels and position-scoped validation. Wired twelve-button paired
      saves support both banks; receiver/legacy/software paths reject the new
      drafts. Exact records, lost-ack recovery and draft/Qt behavior tested.
      Other native mouse actions/repeat encodings remain outside authoring.
- [x] Consider software text entry, program launch and additional repeat modes.
      Design constraints recorded: layout/Unicode strategy and unprivileged
      desktop execution need separate work. No new software action is added;
      existing native macro playback already supplies counted/held/toggle modes.
      The new native-action UI explains that the helper stops after saving.
- [ ] Verify each newly exposed action independently; keep unknown stored actions
      intact. Media/scroll output, hold/release, app-exit/reconnect persistence and
      exact restoration need physical trials. Other mouse actions need their own
      semantic/timing verification. Primary-click writer restrictions remain.

## 6. Complete onboard profile management

Slot enumeration, creation and activation already exist; these extend them.

- [ ] Research chunk: document profile names/GUID metadata and upload framing.
- [ ] Naming chunk: read/display names first, then support verified rename writes.
- [ ] Cloning chunk: define everything a clone must include: supported plate
      banks, both layers, macro dependencies and applicable device settings.
- [ ] Backup chunk: version a complete profile export/import format once those
      components can be read and restored. Keep existing mapping-only backups
      explicitly labeled; they are not complete firmware/profile images.
- [ ] Plate chunk: research and verify onboard mappings for the six-/two-button
      plates; detection alone does not establish their mapping-bank addresses.
- [ ] Recovery chunk: test interrupted metadata/clone operations without deleting
      existing slots. Existing-slot deletion remains outside current scope.

## 7. Sensor calibration

- [ ] Research chunk: trace SensorCalibrationV2, Smart Tracking and asymmetric
      cutoff handlers; identify which settings this model actually supports.
- [ ] Read-only chunk: expose current tracking, lift-off and landing settings.
- [ ] Settings chunk: implement bounded edits with backups, readback and restore.
- [ ] Hardware/UI chunk: verify physical behavior and persistence; explain the
      effect of each setting without promising performance improvements.

## 8. Automatic application/game profiles

- [ ] Design chunk: distinguish named application profiles from mouse slots and
      existing per-model/per-plate drafts. Define matching and fallback rules.
- [ ] Detection chunk: investigate reliable application detection on the user's
      KDE/Wayland setup, with a documented fallback where access is restricted.
- [ ] Software chunk: switch software profiles on application changes, release
      held outputs, and restore the intended fallback when the application exits.
- [ ] Hardware chunk: evaluate optional activation of existing onboard slots;
      avoid rewriting flash settings on every focus change and coordinate with
      manual edits, disconnects and other controllers.
- [ ] UI chunk: add explicit opt-in associations, visible active-profile status
      and a way to suspend automatic switching.

## 9. Broader device coverage and reliability

- [ ] Extend native macro hardware coverage: explicit power cycling, mouse outputs,
      additional targets/layers, existing shared contents and timing/sequence
      boundaries beyond the representative #4 trials.

- [ ] Collect user diagnostics through the existing device-support issue form;
      promote experimental capabilities only after model-specific evidence.
- [ ] Verify receiver operation separately from wired USB. Bluetooth remains
      unsupported; do not infer its protocol from USB identities.
- [ ] Test hotplug, plate changes during operations, helper shutdown, held-output
      cleanup and simultaneous access by external controllers.
- [ ] For new writes, test stale state, lost acknowledgements, partial failure,
      exact restoration and interrupted operations where meaningful.

## Overlap with OpenRazer: lower priority

DPI values/stage editing, polling rate, RGB and battery/power settings are absent
from NagaLibre but already exposed by OpenRazer for the Naga V2 Pro. Revisit as
optional integration/convenience work after the gaps above; do not duplicate
these merely to claim Synapse parity.

## Research starting points

- Local evidence: [onboard protocol](inspection/ONBOARD.md),
  [faceplates](inspection/FACEPLATES.md), [models](inspection/MODELS.md),
  [device registry schema](devices/README.md).
- [OpenRazer mouse implementations](https://github.com/openrazer/openrazer/blob/master/daemon/openrazer_daemon/hardware/mouse.py)
  (comparison checked 2026-10-19; upstream coverage can change).
- [Naga V2 Pro Synapse manual](https://dl.razerzone.com/master-guides/RazerSynapse3/NAGAV2PRO-00000167-en.pdf).
- [Razer haptic wheel guide](https://dl.razerzone.com/videos/transcripts/How%20to%20customize%20the%20HyperScroll%20Pro%20Wheel%20of%20the%20Razer%20Naga%20V2%20Pro-9757.pdf).
- [Razer Hypershift guide](https://dl.razerzone.com/videos/transcripts/How%20to%20activate%20and%20use%20Razer%20Hypershift%20on%20a%20Razer%20mouse-1789.pdf).

Keep proprietary payloads, private hardware captures and backups untracked.
Publish source and protocol findings, following the repository's source-only
distribution policy.

## Future: firmware version checking and updates

- [ ] Show the device-reported firmware version and distinguish it from an
      updater package version. The wired wheel-research diagnostic now reads
      `00/81` twice with identity/state guards; it exposes two raw bytes and
      does not invent a patch number. Wired hardware returned 01 02 (1.2),
      with unchanged wheel/mapping checks. GUI integration remains pending. Other connections/models need their own verification.
- [ ] Add an explicit Check for firmware updates action using official model-
      and connection-specific Razer metadata. Show source, target version and
      package identity; handle stale/offline metadata and partial version reports.
      Never equate a newer package with a compatible image automatically.
- [ ] Research Linux firmware-update transport and recovery independently of
      settings writes. Document mouse/receiver images, bootloader identities,
      package/image integrity, update order, power-loss recovery, version checks
      and settings preservation before implementing any flashing support.
- [ ] If a safe supported update path is established, offer an explicit user-
      initiated update with progress, interruption handling and post-update
      verification. No background flashing, automatic bootloader entry or
      proprietary updater execution. Distribution remains source-only; firmware
      payloads are not committed or bundled.

[Firmware research and remaining limits](inspection/HAPTIC_FIRMWARE.md) records
current static findings. Adding this roadmap does not enable firmware writes.
