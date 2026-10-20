"""Recovery evidence never changes the checksum-bound trial or claims restoration."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_hypershift_trial import initial

SPEC = importlib.util.spec_from_file_location(
    "layer_recovery_inspection", Path(__file__).resolve().parent.parent / "scripts/inspect_layer_recovery.py")
inspect = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inspect)


class RecoveryEvidenceTests(unittest.TestCase):
    def fixture(self, root):
        state = initial()
        state["normal"]["primary"] = [{"button": n, "category": 1, "data": [n]} for n in (1, 2)]
        middle = {"button": 3, "category": 1, "data": [3]}
        backup = {"slots": [{"state": state, "middle": middle}]}
        for name, value in [("original.json", backup),
                            ("plan.json", {"backup_sha256": ""}),
                            ("status.json", {"plan_sha256": ""})]:
            (root / name).write_text(json.dumps(value))
        (root / "plan.json").write_text(json.dumps({"backup_sha256": inspect.checksum(root / "original.json")}))
        (root / "status.json").write_text(json.dumps({"plan_sha256": inspect.checksum(root / "plan.json")}))
        records = [{"logical": None, "wire": n, "requested_layer": 0, "echoed_layer": 0,
                    "record": [1, 1, n, 0, 0, 0, 0]} for n in (1, 2, 3)]
        for layer in (0, 1):
            bank = state["hypershift"] if layer else state["normal"]
            for button, wire in zip(bank["buttons"] + bank["controls"],
                                    [*range(0x40, 0x4c), 0x34, 0x35, 0x6d, 0x60]):
                records.append({"logical": button["button"], "wire": wire, "requested_layer": layer,
                                "echoed_layer": 1 if wire == 0x40 else 0, "record": inspect.wire(button)})
        evidence = {"format": 1, "kind": "unverified_selector_observations", "bank_identity_verified": False,
                    "slot": 1, "records": records,
                    "metadata": {"serial_bytes": [*b"TEST", *([0] * 18)], "device": {"product": 167}}}
        return evidence

    def test_private_capture_keeps_original_files_unchanged_and_preserves_reverse_echo(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = self.fixture(root)
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            with patch.object(inspect.subprocess, "run", return_value=subprocess.CompletedProcess(
                    [], 0, stdout=json.dumps(evidence))) as run, patch("builtins.print"):
                path = inspect.capture(root, Path("separate-debug-helper"))
            run.assert_called_once_with(["sudo", "separate-debug-helper", "onboard-selector-inspect"],
                                        check=True, stdout=subprocess.PIPE, text=True)
            self.assertEqual(json.loads(path.read_text()), evidence)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            for name, content in before.items():
                self.assertEqual((root / name).read_bytes(), content)

    def test_failed_or_incomplete_reply_saves_nothing_and_cannot_be_promoted_to_verified(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = self.fixture(root)
            cases = [dict(original, bank_identity_verified=True), dict(original, records=[])]
            wrong_device = copy.deepcopy(original)
            wrong_device["metadata"]["device"]["product"] = 168
            cases.append(wrong_device)
            for evidence in cases:
                with patch.object(inspect.subprocess, "run", return_value=subprocess.CompletedProcess(
                        [], 0, stdout=json.dumps(evidence))), patch("builtins.print"):
                    with self.assertRaises(ValueError):
                        inspect.capture(root, Path("separate-debug-helper"))
                self.assertFalse(list(root.glob("selector-evidence-*")))


if __name__ == "__main__":
    unittest.main()
