"""The volatile getter comparison stays diagnostic and follows a durable checkpoint."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("inspect_haptic_views", Path(__file__).resolve().parent.parent / "scripts/inspect_haptic_views.py")
views = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(views)


class ViewsTests(unittest.TestCase):
    def data(self):
        normal = {"device": {"product": 167, "path": "mock", "serial": "TEST"}, "slots": [1], "active": 1,
                  "slot_capacity": 5, "mode": [0, 0]}
        before = [{"normal": normal}]
        report = {"format": 1, "kind": "unverified_haptic_table_views", "stable": True,
                  "guard": {"device": normal["device"], "slots": [1], "active": 1, "capacity": 5, "mode": [0, 0], "module_id": 3}}
        return before, report

    def test_private_durable_checkpoint_precedes_only_readonly_diagnostic(self):
        before, report = self.data()
        with tempfile.TemporaryDirectory() as tmp:
            engine = Path(tmp) / "engine"
            engine.write_bytes(b"helper")
            directory = Path(tmp) / "views"
            def query(_engine, name):
                self.assertEqual(name, "haptic-table-views")
                self.assertEqual(json.loads((directory / "mappings-before.json").read_text())["slots"], before)
                return report
            with patch.object(views, "mappings", return_value=before) as mappings, patch.object(views, "query", side_effect=query):
                self.assertEqual(views.capture(engine, directory), report)
            self.assertEqual(mappings.call_count, 2)
            self.assertEqual((directory / "table-views.json").stat().st_mode & 0o777, 0o600)
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)

    def test_failed_or_different_device_read_preserves_checkpoint_and_rechecks_mappings(self):
        for rejected in [False, True]:
            with self.subTest(rejected=rejected), tempfile.TemporaryDirectory() as tmp:
                before, report = self.data()
                report["guard"]["active"] = 2
                engine = Path(tmp) / "engine"
                engine.write_bytes(b"helper")
                directory = Path(tmp) / "views"
                with patch.object(views, "mappings", return_value=before) as mappings, patch.object(views, "query", side_effect=ValueError("rejected") if rejected else None, return_value=report):
                    with self.assertRaises(ValueError):
                        views.capture(engine, directory)
                self.assertEqual(mappings.call_count, 2)
                self.assertTrue((directory / "mappings-before.json").exists())
                self.assertTrue((directory / "mappings-after.json").exists())
                self.assertFalse((directory / "table-views.json").exists())

    def test_failed_durable_checkpoint_prevents_table_view_queries(self):
        before, _ = self.data()
        with tempfile.TemporaryDirectory() as tmp, patch.object(views, "mappings", return_value=before), patch.object(views, "durable_plan", side_effect=OSError("fsync")), patch.object(views, "query") as query:
            with self.assertRaisesRegex(OSError, "fsync"):
                views.capture(Path("engine"), Path(tmp) / "views")
            query.assert_not_called()
