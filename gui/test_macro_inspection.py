"""Getter-only macro export recovery checkpoints; no device or Qt required."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import inspect_macros


class MacroInspectionTests(unittest.TestCase):
    def setUp(self):
        self.mapping = {"normal": {"slot": 1, "device": {"product": 0xa7, "path": "mock"}}}
        self.result = {"format": 1, "kind": "onboard_macro_diagnostic", "restorable": False,
                       "mappings": [self.mapping], "storage": {"entries": []}}
        self.checkpoint_patch = patch.object(inspect_macros, "build_checkpoint", side_effect=lambda engine, path: {
            "format": 1, "kind": "onboard_macro_storage_checkpoint", "complete_profile": False,
            "restoration_implemented": False, "inspection": json.loads(path.read_text())})
        self.checkpoint_patch.start()
        self.addCleanup(self.checkpoint_patch.stop)

    def test_checkpoint_precedes_query_and_private_export(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "capture"

            def query(engine, command):
                self.assertEqual(command, "onboard-macros")
                self.assertTrue((directory / "mappings-before.json").is_file())
                return self.result

            with patch.object(inspect_macros, "mappings", return_value=[self.mapping]), \
                    patch.object(inspect_macros, "query", side_effect=query):
                path, result = inspect_macros.capture(Path("engine"), directory)
            self.assertEqual(json.loads(path.read_text()), result)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
            self.assertTrue((directory / "mappings-after.json").is_file())
            checkpoint_path = directory / "macro-checkpoint.json"
            self.assertEqual(checkpoint_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(checkpoint_path.read_text())["inspection"], result)

    def test_failed_offline_validation_preserves_raw_export_and_checks_final_mappings(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "capture"
            with patch.object(inspect_macros, "mappings", return_value=[self.mapping]) as mappings, \
                    patch.object(inspect_macros, "query", return_value=self.result), \
                    patch.object(inspect_macros, "build_checkpoint", side_effect=ValueError("invalid evidence")):
                with self.assertRaises(ValueError):
                    inspect_macros.capture(Path("engine"), directory)
                self.assertTrue((directory / "macros.json").is_file())
                self.assertFalse((directory / "macro-checkpoint.json").exists())
                self.assertEqual(mappings.call_count, 2)

    def test_failed_checkpoint_prevents_macro_requests(self):
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(inspect_macros, "mappings", return_value=[self.mapping]), \
                patch.object(inspect_macros, "durable_plan", side_effect=OSError("fsync failed")), \
                patch.object(inspect_macros, "query") as query:
            with self.assertRaises(OSError):
                inspect_macros.capture(Path("engine"), Path(temp) / "capture")
            query.assert_not_called()

    def test_failed_getter_still_checks_mappings_and_changed_references_fail(self):
        for failure in (True, False):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                changed = copy.deepcopy(self.result)
                changed["mappings"][0]["normal"]["slot"] = 2
                with patch.object(inspect_macros, "mappings", return_value=[self.mapping]) as mappings, \
                        patch.object(inspect_macros, "query", side_effect=ValueError("getter") if failure else None,
                                     return_value=changed):
                    with self.assertRaises((ValueError, RuntimeError)):
                        inspect_macros.capture(Path("engine"), Path(temp) / "capture")
                    self.assertEqual(mappings.call_count, 2)


if __name__ == "__main__":
    unittest.main()
