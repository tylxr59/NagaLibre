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
- [ ] Verify factory horizontal tilt actions on both sides, right-tilt remapping,
      and the scroll-mode button. Left tilt -> B was physically confirmed and
      exact original records were restored; other physical behavior is pending.
- [ ] Exercise Restore defaults as a draft-only operation, then save and verify
      the supported defaults with exact restoration afterward. It currently
      restores bindings, not wheel tension, DPI tables or other device settings.
- [ ] Test standalone slot activation and desktop slot creation, including
      app exit/reconnect persistence and unchanged original slots. The temporary
      slot-3 allocation/read/removal trial already succeeded.
- [ ] Verify shortcuts/mouse outputs, six-/two-button software mappings, receiver
      behavior, and the full Qt/polkit workflow in separate small test sessions.

## 2. Hypershift

Goal: a secondary assignment layer available while holding a designated button.

- [ ] Research chunk: document normal/Hypershift bank selection and the action
      that activates Hypershift. Existing payloads carry a layer byte currently
      fixed to zero; establish addressing and firmware restrictions first.
- [ ] Read-only chunk: enumerate secondary-layer records and preserve unknown
      actions in snapshots without changing existing normal-layer behavior.
- [ ] Engine chunk: add layer-aware preparation, durable backups, stale checks,
      changed-action writes, readback and exact rollback within permitted IDs.
- [ ] UI chunk: expose normal/secondary drafts and a supported Hypershift trigger;
      preserve both layers across saves and profile migration.
- [ ] Hardware chunk: test one secondary assignment plus its trigger, verify
      release returns to normal, then restore. Check reconnect persistence.

## 3. HyperScroll Pro haptic wheel

Goal: configure wheel feel, beyond remapping the scroll-mode button.

- [ ] Research chunk: trace the native HapticScroll handlers, stage settings and
      metadata. Recover request/reply formats and per-connection capabilities.
- [ ] Read-only chunk: report current stage, enabled stages/order, browsing mode,
      tension, steps and custom curves where supported.
- [ ] Basic settings chunk: support built-in stage selection and enabled-stage
      order, with durable settings backups and verified recovery.
- [ ] Custom settings chunk: expose tension (Synapse documents 0–100), steps
      (8–96 per revolution), and separate upward/downward haptic curves. Verify
      firmware bounds rather than treating UI ranges as a complete wire spec.
- [ ] UI chunk: provide understandable presets and custom controls, with separate
      binding defaults and wheel-settings defaults.
- [ ] Hardware chunk: verify tactile changes, stage cycling and persistence one
      setting at a time; restore original settings between experiments.

## 4. Onboard macros and richer playback

Goal: determine which sequences can run from mouse memory without a helper.
The managed macro structures are not the USB wire format; native macro entry
points exist, but allocation/upload/delete encoding remains unresolved.

- [ ] Research chunk: document macro inventory, capacity, IDs, event encoding,
      delays, allocation, upload, binding, deletion and any checksums/chunking.
- [ ] Read-only chunk: inspect existing macro references and storage without
      modifying or deleting user data. Establish actual firmware limitations.
- [ ] Recovery chunk: back up macro contents and references before writes;
      preserve shared references and remove only allocations created by our
      failed transaction. Current mapping backups are not full macro backups.
- [ ] Minimal write chunk: upload/bind one small supported sequence, read it back,
      physically test it and restore the original state.
- [ ] Playback chunk: investigate supported repeat counts, while-held/toggle
      playback, turbo and repeat rate. Distinguish firmware capabilities from
      software-only behavior; do not assume every Synapse macro works onboard.
- [ ] UI chunk: expose supported onboard sequences and clear storage limits;
      retain software playback for actions that require a running helper.

## 5. Richer native button actions

- [ ] Research and decode sensitivity clutch/temporary DPI and other supported
      sensitivity actions, including release behavior.
- [ ] Investigate firmware profile cycling/selection as button assignments.
- [ ] Add supported consumer/media actions and any missing mouse actions with
      explicit labels and position-scoped validation.
- [ ] Consider software text entry, program launch and additional repeat modes;
      show when the helper is required and release held outputs on stop/failure.
- [ ] Verify each newly exposed action independently; keep unknown stored actions
      intact. Research does not expand the primary-click writer restrictions.

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
