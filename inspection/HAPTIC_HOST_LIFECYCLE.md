# Custom wheel: Ghidra host lifecycle follow-up

This is static research, requested after the standard-mode implementation and
onboard-macro checkpoint. No device was opened, no Windows binary was executed,
and no apply gate was removed. Custom remains unavailable for new writes.
See [HAPTIC_WHEEL.md](HAPTIC_WHEEL.md) for packet layouts and
[HAPTIC_FIRMWARE.md](HAPTIC_FIRMWARE.md) for the unresolved flash gate and the
installed-device readback limitations.

## Method and provenance

The configured GhidraMCP was used through a local Python MCP client because its
tools were not exposed directly in this conversation. `get_program_info`
confirmed `RzCtl_00A7.dll`, x86 little-endian 32-bit, Windows compiler layout,
image base `10000000`, SHA-256
`dc7dcf529731e95ce6f712e7ce5166423b80ea26087648061cf343e7594578d7`.
`decompile_function_by_address`, cross-reference and disassembly queries were
used. The existing project was locked by another session, so a separate private
project was created under `~/ghidra-projects/NagaLibre-HapticResearch` without
interrupting that session or changing the configured launcher.

Managed call sites were checked against retained `Configurator.167_0.dll` CIL,
whose hash is recorded in HAPTIC_WHEEL.md. Native vtable targets and the selector-1
branch were also checked against x86 instructions. Native addresses below are
RVAs; add `10000000` for the MCP address. Managed addresses are assembly RVAs.
Raw decompilation, MCP receipts and proprietary inputs remain private/untracked.

## Live edits and stored-profile updates are separate paths

`AriaT1V2WiredFeatureImpl.SetCustomScrollWheelStage` at managed `de54`:

1. Reads the active application profile and its wheel-stage model.
2. Copies the edited up/down curves and link flag into its Custom entry, makes
   that entry the model's active stage and updates the application data/cache.
3. Enqueues metadata and Custom-table updates for matching onboard profiles via
   `SubmitCustomScrollStageMetaDataInQueue` and `SubmitCustomScrollStageInQueue`.
4. Separately calls `SetCustomScrollStageMetaData(device, 0, custom)` followed by
   `SetCustomStage(device, custom, 0)` on the live wheel feature.

The last argument is a **managed profile index**, not the wire selector. The
live Custom JSON builder (`23ee4`, IL `23f`–`247`) adds one before writing
`ProfileIndex`. The live metadata builder (`1f0c0`, IL `306`–`313`) does the same.
Thus these explicit API-index-zero calls emit **wire selector 1**. They do not
establish a selector-zero write path. The helper that copies the managed index
is `ObjectExtensions.Copy`; the other clones are `Serializer.DeepClone`.

The stored-profile callback (`21990`) also adds one to the managed storage index,
but wraps the result in `Storage_Profile_Data` with a `ProfileItem`. The live
feature instead uses `HapticScroll_GenericJson`. These are distinct host
dispatch paths even when a selector value is numerically equal.

The assignment to the managed `ActiveScrollStage` property is not itself evidence
of a `15/00` request. The traced top-level method does not separately call the
active-stage transport setter. Queue scheduling, model notifications and actual
device requests must not be treated as one synchronous transaction.

## The storage dispatcher deliberately skips selector 1

The native storage setter registration (`66320`) maps `Storage_Profile_Data` to
thunk `2344b`, which dispatches virtual slot `9c`. Both `CStorage` and
`CStorageEx` resolve that slot to `65ac0`. It parses the requested profile/item
and dispatches virtual slot `a0`:

| Component | RVA | Behavior relevant to Custom |
| --- | --- | --- |
| `CStorageEx` item submission | `248c0` | Depending on request flags, calls the base implementation directly or copies the request into an asynchronous queue; the queued submission returns before device work completes. |
| Storage worker | `24130` | Handles event `07010015` through base item writer `58b90`, then publishes a completion status and frees the copied request. |
| Base item writer | `58b90` | Custom item `0c` and metadata item `0d` have explicit selector-1 skip branches. |
| Custom skip | `59ac0`–`59ae1` | Compares the profile byte with literal 1; logs that Custom is being skipped on “Active Profile”, reports success and advances. |
| Custom forwarding | `59ae6`–`59c71` | For other selectors, rebuilds a `HapticScroll_CustomStage` JSON request using that profile byte and forwards it through the generic feature interface. |

The metadata case has the analogous skip and forwarding behavior. The literal
test is **selector == 1**; it is not a query of whichever physical slot happens
to be active. Do not generalize the log wording into an active-slot rule.

This explains why tracing only storage writes misses part of Razer's Custom
implementation: the separate live feature is needed for selector 1. It does
not establish the firmware durability of that selector or authorize a new write.
The older NagaLibre changed-value trial already used wire selector 1, so the
managed-index conversion alone does not explain or fix its failed verification.

## No additional commit in the traced per-edit handlers

The Custom JSON handler at `26b60` queries capacities (`vtable +560`), submits
configuration (`+55c`) with stage 6 and format byte 1, then submits complete CW,
CCW and velocity tables (`+568`, table selectors 1, 2, 3), in that order. It
returns the final transport result after freeing its temporary arrays. No extra
commit, mode switch, metadata write, active-stage write or getter appears in
this handler after the last table call.

The native chunk wrapper `2e820` sends at most eight points per request through
the ordinary feature-report setter. It retains `10 + 8*n` as declared length,
with big-endian point offset/count and little-endian float pairs. This confirms
the earlier framing evidence; it does not justify changing the packet length.
Metadata at `27140` calls its own transport method (`+570`); active-stage JSON
at `267e0` calls its separate method (`+53c`).

The storage worker also has no special Custom commit after its forwarded call:
it reports completion. This rules out a hidden Custom-only final packet in the
specific handlers traced here. It does **not** rule out device initialization,
driver-mode lifecycle, other queued operations, or power transitions establishing
the firmware's separate flash-enable state before an edit. Nor does a host
success return establish that changed tables were persisted or activated.

## More precise host curve generation

The managed storage and live implementations have corresponding helpers:

| Helper | Storage RVA | Live-feature RVA |
| --- | --- | --- |
| `NominalToLinePoints` | `18008` | `1f5e8` |
| `Discretization_Forward` | `181c4` | `1f7a4` |
| `NormalizeToLinearScale` | `18320` | `1f900` |

The Custom builders call them independently for CW/up and CCW/down:

- Build WPF `PathGeometry` with a `PolyBezierSegment`. Start at the first
  center point. In model order, append a center for every point after the first,
  then append that point's control point when present. Preserve this exact
  ordering rather than assuming a different editor convention for Bézier handles.
- Flatten the path using WPF's default `GetFlattenedPathGeometry()`. Sample
  `GetPointAtFractionLength(i/50)` for `i = 0..50` inclusive: 51 samples at
  fractions of the flattened path length, not evenly spaced X coordinates or
  uniformly spaced Bézier parameter values. A negative tangent X causes a null
  result; exception paths return an empty list.
- Simplify forward using a maximum vertical deviation test against a candidate
  chord. Compare `Math.Round(abs(predictedY - actualY), 4)` with the double
  threshold `0.20000000298023224`. Extend the candidate while every interior
  point passes; on failure retain the previous candidate endpoint and restart
  there. Preserve the first and last samples. This is a forward greedy procedure,
  not proof of recursive Ramer–Douglas–Peucker or perpendicular-distance fitting.
- Normalize retained coordinates: `angle = (360 / steps) * X / 100` and
  `current = (0.2f * tension / 100f) * Y / 100`, rounding each result to five
  decimal places via the two-argument `Math.Round` overload. The scale factors
  are calculated in float32 before conversion to double. Native JSON conversion
  ultimately stores float32 pairs. A future reproduction must retain those
  conversion/rounding boundaries.
- Compute each tick-index angle from the **first maximum-Y point of the
  simplified, unscaled samples**, using `(360f / steps) * X / 100`. It is not
  inferred from the largest rounded uploaded current. `Enumerable.Max` and
  `List.Find` with exact Y equality establish the selection order.
- Emit the three constant unit-velocity points `(-720,1), (0,1), (720,1)`.
  Deadzone-reduction fields and AlternateCurrent come from the model separately.

WPF's default flattening/tolerance and edge-case floating-point behavior still
need independent golden fixtures before claiming an exact cross-platform curve
generator. These are host construction rules, not electrical safety bounds or
proof that installed firmware accepts arbitrary editor values.

## Additional libraries and firmware lifecycle trace

The follow-up on 2026-10-21 inspected two more wired Device167 libraries with
GhidraMCP and their managed/native bridges:

| Input | SHA-256 | Relevant routines |
| --- | --- | --- |
| `RSy3_DriverMode.dll` | `7d6db694a9ff57a0a14bbdd9a61c2f4ddb8d51a26f2c07665fdff16e73a698d4` | Managed `DriverModeResolverM.Set` at `33fc8`; native `DriverMode_SetEnabled` at `1e660`, implementation `1e6b0` |
| `RSy3_GenericFeature.dll` | `38001e12577b85f81bc0461fb1a804ec5666e3936a6ad5f39af0968706da7d14` | Managed `GenericFeatureResolverM.Set`; native `GenericFeature_SetJson` at `21430` |

The generic JSON bridge resolves a feature name to its registered operation,
gets the device interface and forwards one generic JSON setter call. The traced
success path releases its objects and returns the result; it does not append a
mode change or a separate wheel commit. `RSy3_OnboardMem3.dll` was also surveyed
for entry-point names; it is not the Custom JSON bridge, and that survey is not a
claim to have traced all of its native code.

The firmware was also imported into a separate private Ghidra project. A derived
analysis-only ELF maps the unchanged `dev2.bin` bytes at `27000`, declares Thumb
entry `273c1`, and provides an uninitialized RAM address space for cross-references.
The payload still hashes to `8adbdbdd...e7d392` as recorded in HAPTIC_FIRMWARE.md.
The RAM block is an analysis aid, not a dump or evidence of runtime RAM contents.
An initial relocatable wrapper had incorrect analysis placement and was discarded
as evidence; the subsequent executable wrapper retained the proper addresses.
No firmware image or wrapper is tracked or distributed.

### Ordinary driver mode is not the reset/flush mode

Managed DriverMode accepts its model states 3 and 4 and turns them into an
enabled boolean. The native bridge submits internal operation `20001` with
that boolean and a separate lighting flag. In the wired controller, registration
`1f9a0` maps that operation to `1e1a0`, which converts enabled to wire mode **3**
and disabled to wire mode **0**. Its protocol slot `+34` resolves to `2de40`.
That wrapper first reads the current mode and skips an unchanged setting; when
needed it emits `00/04` with two payload bytes, mode and argument zero.

This path does not request mode 1. In the extracted firmware, mode 3 selects
profile 1 through `4d228(3,1)`; mode 0 performs override cleanup through
`3a94c(0)`. Neither branch directly writes the Custom flash-enable byte. The
mode-1 branch at `45044`–`45074` instead clears the countdown, opens both gates,
waits for pending writes, performs further shutdown work, writes `aaaaaaaa` to
RAM `2003fffc`, and continues to reset. Do not reclassify it as an ordinary save
or send it as a shortcut. No mode request was issued during this research.

### The flash permission is consumed, not permanently enabled

Ghidra's RAM cross-references and the raw Thumb instructions agree on these
2.61.01 paths:

| Condition/path | Absolute firmware address | Effect |
| --- | --- | --- |
| Completed curve upload | `3a730`–`3a79c` | Copies staging data into the per-profile cache, marks its page dirty and schedules event `200`; does not open the flash gate. |
| Scheduled curve event | `49208` / `492de` | Sets pending bit `40` and a countdown; this is distinct from permission to flush. |
| Curves allowed to flush | `47870`–`4787a` | Requires gate byte `200050c0` bit 0 plus pending bit `40`. |
| Curves finish | `478f2`–`47900` | Clears pending bit `40` when all dirty pages finish and clears gate bit 0. If permission was set with no curve pending, it clears the permission too. |
| Metadata allowed to flush | `47902`–`4790c` | Separately requires gate bit 1 plus pending bit `80`; success clears that pending bit and gate bit 1. |
| Transition helper | `3e3bc` | Writes 3 to the gate byte and waits through `3bd70(0)` for pending work; called from connection/power transition code. |
| Power/connection state machine | `3e484`, writes at `3e714` and `3e802` | Opens both permissions before synchronous pending-write processing and shutdown/sleep work. |

The state machine observes hardware input/status and enters paths containing
peripheral shutdown, waits and sleep. Its internal state values have not all
been assigned authoritative physical meanings. In particular this does **not**
prove that a plain USB reconnect, while the battery remains connected, is a
complete and safe flush/rollback contract on the installed device.

The older official mouse image has a related **one-shot curve permission** at
RAM `20002ec8`: its flash worker starts at `45380`, tests the byte at
`45502`–`45506`, handles pending bit `40`, and clears the permission at `45586`.
Its metadata path at `4558a`–`455c6` does not use the newer separate bit-1 gate.
This was cross-checked against its raw Thumb instructions and literal addresses.
Therefore the general deferred-curve-save mechanism appears in both extracted
versions, but the precise two-bit implementation is not universal. Neither image
is established as identical to the installed firmware reporting 1.2.

### RAM preparation and persistent readback can legitimately disagree

The active-profile completion branch at `463fe`–`46428` copies the Custom
configuration and calls `3b050` for stage 6. `3b050` selects a source according to
connection/profile context. In the nonzero-profile cache path it translates the
**combined** source to a cache page, copies the complete combined table into a
working buffer, then builds distinct CW/CCW/velocity pointers. The selected-Custom
check controls the subsequent active-stage application. Other contexts use a
different staging/direct source; retain that distinction.

In contrast, selector-zero getter `3a414` reads through configuration source
pointer `+3c`, retaining subtable offsets but not necessarily following the new
working buffer. The configuration parser `3b2c0` sets that source to a flash
address for a nonzero profile; configuration-copy helper `3b17c` preserves it.
The stored getter translates into cache but loses the subtable remainder, as
documented earlier. These are different read sources with different limitations.

Consequently, the observed changed-upload/old-selector-zero-readback mismatch
is consistent with new cached or working data and old persistent flash. It is
not proof that the table transfer failed, nor proof of correct tactile output.
Custom was not selected in the stopped trials, and no operational-buffer read
or changed-curve feel test established what would have happened. Do not bypass
the comparison merely because the firmware offers a plausible explanation.

## Remaining requirement before a new trial

The missing contract now has two explicit parts: verify the changed live data,
and flush/verify its durable counterpart with exact recovery. Razer's ordinary
driver-mode wrapper and generic JSON bridge do not supply a newly discovered
commit packet. The confirmed transition/reset flush paths have broader effects;
their physical behavior and installed-version correspondence remain unverified.
No new hardware trial or apply-route change follows from this static research.
