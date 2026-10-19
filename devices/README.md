# Device definitions and defaults

`models.json` is shared by the Python GUI and compiled into the Rust backend.
Each model keeps its USB products, layouts, capability flags and `defaults`:

- `plates` has one entry per supported layout. `keys` lists default Linux input
  triggers in physical order; empty strings mean learning is required. `bindings`
  lists decoded onboard actions (`category`, `data`) in the same order, or an empty
  list when onboard defaults have not been established for that model/layout.
- `controls` lists extra controls with a stable `id`, UI `name`, logical `button`,
  `wire_id`, factory `binding` and `default_label`. Current V2 Pro positions 13–16
  are left tilt, right tilt, scroll-mode and DPI-cycle buttons. Keep their order
  stable: saved drafts refer to those positions.

An initial extra-control draft preserves its stored mapping. Restore defaults
selects each declared factory binding. Existing three-control drafts retain all
edits and append the DPI control with its stored mapping preserved. Legacy mouse
backups omit newer controls; restoring them preserves those controls' current
records.

Unknown defaults remain empty rather than copying another model's assignments.
Adding data does not enable vendor access: the `onboard` and `faceplate` capability
flags remain independent, and the backend retains an explicit safe address set
excluding primary clicks. Receiver and physical verification limits remain in
HANDOFF.md. DPI-cycle is a button assignment using the existing stage table, not
a DPI-value configuration feature. Rebuild the engine after changing this file.
