# Performance audit, 2026-10-21

This audit uses local source and deterministic transport fixtures. There are no
new hardware timing measurements or measured comparisons with Synapse 4.

## Hardware transactions

The largest avoidable cost was nested repeated reads. `inspect_macros` performed
two complete mapping sweeps, each invoking `read_layers`, which itself read each
bank twice. It now compares two single-pass sweeps. Both still read every scoped
slot and both layers; comparison includes opaque records and layer echoes.
Macro storage is still read twice, with surrounding identity/state guards.

Likewise, `capture_layer_backup` now compares two single-pass mapping sweeps,
including independent middle-click reads, instead of nesting double reads in
both passes. Standalone `read_layers` and commit-time `check_layer_backup` retain
their repeated bank reads. This shared backup change applies to button saves,
slot creation/activation, wheel settings and macro transactions that call it.

Measured getter counts before/after this patch:

| Fixture operation | Before | After | Reduction |
| --- | ---: | ---: | ---: |
| Strict macro inspection, two slots, empty storage | 331 | 179 | 46% |
| Paired mapping backup, two slots | 316 | 164 | 48% |
| Macro preparation, two slots, one existing short macro | 663 | 359 | 46% |
| Macro commit, same fixture | 1,095 | 639 | 42% |
| Preparation plus commit | 1,758 | 998 | 43% |
| Macro recovery, same fixture after upload | 2,244 | 1,484 | 34% |

Counts exclude the initial GUI inventory read from preparation/commit, and do
not count setters as getters. The identical mock workload was run before and
after the changes. `transaction_getter_budgets` guards against regressing the
shared-backup and macro transaction counts. Tests inject changes into the second
pass, including trailing wire bytes on inactive-slot Hypershift bindings, primary
records and middle clicks. Existing storage freshness, lost acknowledgement,
unrelated-state, rollback and owned-allocation recovery tests remain applicable.

At the existing minimum 30 ms wait per transport exchange, the 760 eliminated
getter requests in this macro save fixture remove 22.8 seconds of deliberate
waits. This is arithmetic from request counts, not an observed save duration.
Actual cost also depends on initialized slots, stored macro sizes, USB response
polls, writes and filesystem synchronization.

## Software input

Runtime remapping and session input monitoring previously attempted nonblocking
reads followed by a fixed 2 ms sleep. They now wait on source descriptors with
`poll`, waking for input or the next macro action deadline. Idle waits are capped
at 50 ms so helper shutdown still promptly releases output and evdev grabs.
This changes the idle timer wake rate from approximately 500/s to at most 20/s;
it is not a measured CPU utilization reduction. Input readiness interrupts the
wait, eliminating the deliberate 2 ms input polling delay. The runtime also
reuses its input event batch allocation across sources/frames.

Tests cover macro deadlines, overdue actions, idle wait bounds, input readiness
and disconnected descriptors without opening evdev/uinput devices. Physical
input latency, compositor behavior and power use have not been measured here.

## GUI and discovery

Every three seconds the main Qt thread previously ran `list --json --all-razer`
through blocking `subprocess.run`, with a one-second timeout. Passive inventory
now runs through `QProcess`; scans cannot overlap, timeout kills the child, and
shutdown drains it. Inventory does not borrow the privileged hardware session.

Process tests hold a mock inventory process until Qt has serviced a timer,
verify that a second scan does not start another process, and exercise malformed
output, failure, missing executable, timeout, retry and shutdown. Existing device
support UI tests still cover the resulting unknown/experimental device display.

Local macro authoring stays offline. Existing single-pass display readers and
deferred assignment refreshes remain in place; no new background hardware reads
or caches claiming to represent mouse state were added.

## Remaining opportunities

- Measure per-phase wall time and transport polling on the wired mouse before
  choosing a lower feature-report wait. The 30 ms delay remains unchanged; source
  inspection alone does not establish safe device timing.
- Save/recovery still inspect all initialized slots and complete stored sequences
  at transaction boundaries. Further narrowing needs evidence of allocation and
  reference behavior, plus tests for unrelated changes and recovery.
- The GUI's explicit config check before Apply still uses a blocking subprocess
  with a three-second timeout. Unlike passive discovery, this needs a separate
  pending-apply state so edits, disconnects and destination changes cannot apply
  the wrong configuration.
- Startup retains the 500 ms virtual-device discovery delay. Removing it needs
  compositor/input discovery evidence. No changes were made to durable backup
  or ownership-journal fsync, exact restoration, stale-snapshot checks, primary
  click write exclusions, or rollback after lost write acknowledgements.

Reproduce the request counts with:

```sh
cargo test --locked transaction_getter_budgets -- --nocapture
cargo test --locked display_reads_match_stable_inspections_with_fewer_getters -- --nocapture
```
