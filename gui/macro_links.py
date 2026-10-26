"""Local links between library macros and the copies NagaLibre uploads.

Each fresh upload carries a random GUID, which Device167 stores in the first
16 metadata bytes (Windows GUID memory order). Recording that GUID with the
library entry and a digest of its steps lets a later read match stored copies
exactly. Names are display metadata only and never establish a link.

This file is display bookkeeping. It is not a backup or recovery journal and
never authorizes a mouse write.
"""
from __future__ import annotations

import datetime
import hashlib
import json
from pathlib import Path
import uuid

from macro_bindings import binding_rows
from macro_storage import inventory_rows
from model import save_profile


def steps_digest(steps):
    canonical = json.dumps(steps, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def stored_guid(metadata):
    raw = bytes(metadata[:16])
    if len(raw) != 16 or raw == bytes(16):
        return None
    return str(uuid.UUID(bytes_le=raw))


class MacroLinks:
    def __init__(self, path):
        self.path = Path(path)
        self.uploads = {}
        self.error = None
        try:
            data = json.loads(self.path.read_text())
            if data.get("format") != 1 or not isinstance(data.get("uploads"), dict):
                raise ValueError("unrecognized macro link file")
            self.uploads = data["uploads"]
        except FileNotFoundError:
            pass
        except (OSError, ValueError, AttributeError) as error:
            # Keep an unreadable file untouched; links are only display metadata.
            self.error = str(error)

    def record(self, guid, entry):
        if self.error:
            raise ValueError(f"Macro link file left untouched: {self.error}")
        uploads = dict(self.uploads)
        uploads[str(uuid.UUID(guid))] = {
            "library_id": entry["id"], "name": entry["name"], "digest": steps_digest(entry["steps"]),
            "recorded": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        }
        save_profile(self.path, {"format": 1, "uploads": uploads})
        self.uploads = uploads

    def lookup(self, guid):
        return self.uploads.get(guid) if guid else None


def catalog(snapshot, entries, links):
    """Describe stored copies and per-library status from one macro read.

    Copy states: "current" (steps match the library), "differs" (the library
    entry changed since upload), "orphaned" (the library entry was deleted) and
    "unlinked" (not uploaded by this NagaLibre install, or uploaded before links
    were recorded).
    """
    library = {e["id"]: e for e in entries}
    uses, unknown = binding_rows(snapshot)
    copies = []
    for entry, (name, identity, size) in zip(snapshot["storage"]["entries"], inventory_rows(snapshot)):
        guid = stored_guid(entry["metadata"])
        link = links.lookup(guid)
        state, library_id = "unlinked", None
        if link is not None:
            library_id = link["library_id"]
            source = library.get(library_id)
            state = ("orphaned" if source is None else
                     "current" if steps_digest(source["steps"]) == link["digest"] else "differs")
        copies.append({"id": entry["id"], "name": name, "size": int(size), "guid": guid,
                       "library_id": library_id, "state": state,
                       "uses": [u for u in uses if u["id"] == entry["id"]]})
    by_library = {}
    for copy in copies:
        if copy["library_id"] in library:
            by_library.setdefault(copy["library_id"], []).append(copy)
    status = {}
    for identity in library:
        linked = by_library.get(identity, [])
        status[identity] = {
            "copies": linked,
            "uses": [u for c in linked for u in c["uses"]],
            "differs": any(c["state"] == "differs" for c in linked),
        }
    return {"copies": copies, "status": status, "uses": uses, "unknown": unknown}


def summary(status, compact=False):
    """Label and tone for a library entry's mouse status."""
    if status is None:
        return "", "idle"
    count = len(status["uses"])
    if not status["copies"]:
        return ("Not stored" if compact else "Not on mouse"), "idle"
    if status["differs"]:
        return ("Changed" if compact else "Changed since upload"), "warn"
    if count == 0:
        return ("Unused" if compact else "On mouse · unused"), "idle"
    buttons = f"{count} button{'s' if count != 1 else ''}"
    return (buttons if compact else f"On mouse · {buttons}"), "live"
