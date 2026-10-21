# Experimental onboard macros

NagaLibre can upload a fresh key/mouse sequence and bind it to a grid button or
supported extra control on wired Naga V2 Pro with the twelve-button plate.
The implementation is experimental: capacity/count reads have hardware evidence,
but nonempty contents, uploads, playback and persistence still need verification.

## Create a macro

1. Build the current release engine and open NagaLibre in **Mouse memory** mode.
2. Connect the wired mouse, select the intended slot and activate it.
3. Open **Onboard macros…**. The dialog reads the active slot and macro inventory.
4. Choose the target and Normal or Hypershift layer, then **Edit sequence…**.
5. Set a name and playback mode, then choose **Save macro to mouse**.

Opening the dialog copies the selected button's draft sequence when present.
Editing is local until Save. The ordinary **Save 12 bindings to mouse** action
does not upload macro drafts; use the dedicated dialog for these sequences.
Primary clicks are never available as mapping targets.

Supported timelines contain standard keyboard keys/modifiers, shortcuts, five
mouse-button outputs and millisecond waits. Every held output must be released.
Mouse movement, wheel events, text entry and program launch are not native macro
outputs in this implementation. The compiler rejects unsupported sequences.
Compilation is bounded to five minutes and 16,384 encoded records; those are
implementation bounds, not measured firmware limits. Names allow 100 UTF-8 bytes.

| Playback | Requested behavior |
| --- | --- |
| Once | Play the timeline once |
| Repeat a fixed count | Play 1–255 times |
| Repeat while held | Repeat while the target is held |
| Toggle repeat | Press to start repeating, press again to stop |
| Sequence | Native sequence selector; precise advancement behavior unverified |

These modes come from the Razer host implementation. Physical timing, interruption
and release behavior need independent verification. Stop toggled playback with its
button, or release held playback, before changing bindings or undoing an upload.
Waits determine timeline delays; no separate hardware turbo/rate setting is exposed.

## Storage and undo

The inventory shows actual readback and available storage. Saving always creates
a fresh entry; it preserves existing macros, including unknown contents and shared
references. Insufficient available space or unknown references cause failure.
Compaction and arbitrary deletion are unavailable. Repeated saves consume entries;
use the matching transaction's undo rather than trying to replace an existing ID.

Before writing, the app saves a private backup under the profile directory's
`backups/macros/` folder. The helper creates a separate protected journal. Both
paths appear in the dialog log. Keep them: they contain private macro contents
and device identity. A failed backup prevents the commit.

**Undo upload…** selects that upload's `.journal.jsonl` file and restores original
bindings before removing only its own allocation. The helper handles protected
journal access; do not edit its ownership or contents. Recovery refuses unrelated
state changes or ambiguous allocation ownership. After a disconnect or failed
operation, preserve the journal and retry undo with the same mouse, slot and plate.
Undo is scoped to the captured controls; it is not complete profile restoration.
Free/reclaimable storage counters may change even after exact content restoration.

After a successful save, the helper exits. A readback confirms stored bytes, but
physical playback without the app and persistence after reconnect/power cycling
remain pending hardware tests. Software mode remains available for its supported
macros and requires the helper to stay running.

The [CLI guide](CLI.md#experimental-onboard-macro-uploads) describes the controlled
hardware trial and recovery commands. [Protocol research](../inspection/MACROS.md)
records the evidence and remaining limits.
