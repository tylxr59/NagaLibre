"""Private diagnostic exports preserve opaque banks; failed getters save nothing."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "inspect_layers", Path(__file__).resolve().parent.parent / "scripts/inspect_layers.py")
inspect = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inspect)


class LayerCaptureTests(unittest.TestCase):
    def test_private_durable_export_preserves_raw_bytes_and_uses_only_layer_getter(self):
        bank = {"primary": [{"button": n} for n in (1, 2)],
                "buttons": [{"button": n, "category": 0, "data": []} for n in range(1, 13)],
                "controls": [{"button": n} for n in range(13, 17)]}
        bank["buttons"][0] = {"button": 1, "category": 0x7e, "data": [0xde, 0xad],
                              "raw_record": [0x7e, 2, 0xde, 0xad, 1, 2, 3]}
        secondary = {key: value for key, value in bank.items() if key != "primary"}
        export = {"format": 1, "normal": dict(bank, slot=2),
                  "hypershift": dict(secondary, layer=1, primary_inspected=False,
                                     echoes=[{"button": n, "layer": 0} for n in range(1, 17)])}
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "new"
            with patch.object(inspect.subprocess, "run", return_value=subprocess.CompletedProcess(
                    [], 0, stdout=json.dumps(export))) as run:
                path, result = inspect.capture(Path("engine"), target, 2)
            run.assert_called_once_with(["sudo", "engine", "onboard-layers", "--slot", "2"],
                                        check=True, stdout=subprocess.PIPE, text=True)
            self.assertEqual(result, export)
            self.assertEqual(json.loads(path.read_text()), export)
            self.assertNotIn("primary", result["hypershift"])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(target.stat().st_mode & 0o777, 0o700)

    def test_getter_failure_does_not_create_an_export(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "new"
            with patch.object(inspect.subprocess, "run", side_effect=subprocess.CalledProcessError(1, [])):
                with self.assertRaises(subprocess.CalledProcessError):
                    inspect.capture(Path("engine"), target)
            self.assertFalse(target.exists())

    def test_probe_keeps_wrong_echo_and_raw_record_as_unverified_evidence(self):
        normal = {"slot": 1, "primary": [{"button": n} for n in (1, 2)],
                  "buttons": [{"button": n} for n in range(1, 13)],
                  "controls": [{"button": n} for n in range(13, 17)]}
        replies = [{"button": n, "wire_id": wire, "requested_layer": 1, "echoed_layer": 0,
                    "record": [0x7e, 2, 0xde, 0xad, 1, 2, 3], "matches_normal_wire": False}
                   for n, wire in enumerate([*range(0x40, 0x4c), 0x34, 0x35, 0x6d, 0x60], 1)]
        export = {"format": 1, "kind": "unverified_layer_replies", "secondary_verified": False,
                  "normal": normal, "replies": replies}
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "new"
            with patch.object(inspect.subprocess, "run", return_value=subprocess.CompletedProcess(
                    [], 0, stdout=json.dumps(export))) as run:
                path, result = inspect.capture(Path("engine"), target, probe=True)
            run.assert_called_once_with(["sudo", "engine", "onboard-layer-probe"],
                                        check=True, stdout=subprocess.PIPE, text=True)
            self.assertEqual(path.name, "unverified-replies.json")
            self.assertEqual(result, export)
            self.assertEqual(json.loads(path.read_text()), export)
            self.assertNotIn("hypershift", result)
            export["secondary_verified"] = True
            with patch.object(inspect.subprocess, "run", return_value=subprocess.CompletedProcess(
                    [], 0, stdout=json.dumps(export))):
                with self.assertRaisesRegex(ValueError, "unverified"):
                    inspect.capture(Path("engine"), Path(directory) / "invalid", probe=True)
            self.assertFalse((Path(directory) / "invalid").exists())


if __name__ == "__main__":
    unittest.main()
