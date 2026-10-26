"""Library links come only from recorded upload GUIDs, never from names."""
import json
from pathlib import Path
import tempfile
import unittest

from macro_links import MacroLinks, catalog, stored_guid, steps_digest, summary
from test_macro_bindings import bindings_snapshot

GUID = "00112233-4455-6677-8899-aabbccddeeff"
# Device167 memory order, as produced by src/onboard/macro_plan.rs::guid_bytes.
GUID_BYTES = [0x33, 0x22, 0x11, 0x00, 0x55, 0x44, 0x77, 0x66, 0x88, 0x99, 0xaa, 0xbb, 0xcc, 0xdd, 0xee, 0xff]


def metadata(guid_bytes, name):
    return list(bytes(guid_bytes) + bytes(4) + name.encode() + bytes(230 - len(name)))


class MacroLinkTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.path = Path(self.root.name) / "macro_links.json"

    def tearDown(self):
        self.root.cleanup()

    def test_stored_guid_matches_native_layout_and_ignores_empty_metadata(self):
        self.assertEqual(stored_guid(metadata(GUID_BYTES, "x")), GUID)
        self.assertIsNone(stored_guid([0] * 250))
        self.assertIsNone(stored_guid([1, 2, 3]))

    def test_record_persists_and_unreadable_file_is_left_untouched(self):
        entry = {"id": "lib-1", "name": "Combo", "steps": [{"tap": "KEY_B"}]}
        MacroLinks(self.path).record(GUID.upper(), entry)
        link = MacroLinks(self.path).lookup(GUID)
        self.assertEqual(link["library_id"], "lib-1")
        self.assertEqual(link["digest"], steps_digest(entry["steps"]))
        self.path.write_text("{not json")
        broken = MacroLinks(self.path)
        self.assertIsNotNone(broken.error)
        with self.assertRaises(ValueError):
            broken.record(GUID, entry)
        self.assertEqual(self.path.read_text(), "{not json")

    def test_catalog_states_uses_and_name_never_links(self):
        state = bindings_snapshot()
        other = list(GUID_BYTES)
        other[-1] = 0x01
        state["storage"]["entries"] = [
            {"id": 7, "metadata": metadata(GUID_BYTES, "Combo"), "data": [1, 5]},
            {"id": 8, "metadata": metadata(other, "Combo"), "data": [1, 5, 9]},
        ]
        entries = [{"id": "lib-1", "name": "Combo", "steps": [{"tap": "KEY_B"}]},
                   {"id": "lib-2", "name": "Combo", "steps": [{"tap": "KEY_C"}]}]
        links = MacroLinks(self.path)
        links.record(GUID, entries[0])
        result = catalog(state, entries, links)
        copies = {c["id"]: c for c in result["copies"]}
        self.assertEqual(copies[7]["state"], "current")
        self.assertEqual(copies[7]["library_id"], "lib-1")
        self.assertEqual(len(copies[7]["uses"]), 2)  # Slot 1 normal grid 1 and slot 2 toggle.
        self.assertEqual(copies[8]["state"], "unlinked")  # Same name, different GUID.
        self.assertEqual(summary(result["status"]["lib-1"]), ("On mouse · 2 buttons", "live"))
        self.assertEqual(summary(result["status"]["lib-2"]), ("Not on mouse", "idle"))

        entries[0] = dict(entries[0], steps=[{"tap": "KEY_X"}])
        result = catalog(state, entries, links)
        self.assertEqual({c["id"]: c["state"] for c in result["copies"]}[7], "differs")
        self.assertEqual(summary(result["status"]["lib-1"])[1], "warn")
        result = catalog(state, entries[1:], links)
        self.assertEqual({c["id"]: c["state"] for c in result["copies"]}[7], "orphaned")


if __name__ == "__main__":
    unittest.main()
