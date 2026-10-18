"""Headless integration tests; no real input devices are opened or grabbed."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtCore import QCoreApplication, QEvent
from app import Window, MacroDialog
from model import DEFAULT_KEYS, load_profile, new_profile, reset_plate, runtime_config, save_profile

ENGINE = Path(os.environ.get("NAGALIBRE_TEST_BACKEND", "target/debug/naga-macros")).resolve()


class Profiles(unittest.TestCase):
    def validate(self, profile):
        text = runtime_config(profile)
        with tempfile.NamedTemporaryFile(mode="w") as file:
            file.write(text)
            file.flush()
            result = subprocess.run([str(ENGINE), "check", file.name], capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 0, result.stderr)
        return text

    def test_defaults_are_passthrough_and_reset_preserves_other_plates(self):
        p = new_profile()
        self.assertIn("binding = []", self.validate(p))
        p["plates"]["12"][0].update(mode="key", value="A")
        p["plates"]["6"][0].update(trigger="BTN_SIDE", mode="shortcut", value="Ctrl+C")
        self.assertIn('key = "KEY_A"', self.validate(p))
        reset_plate(p, "12")
        self.assertEqual([b["trigger"] for b in p["plates"]["12"]], DEFAULT_KEYS)
        self.assertEqual(p["plates"]["6"][0]["mode"], "shortcut")
        p["plate"] = "6"
        self.assertIn('"KEY_LEFTCTRL", "KEY_C"', self.validate(p))
        reset_plate(p, "6")
        self.assertEqual(p["plates"]["6"][0]["trigger"], "BTN_SIDE")
        self.assertIn("binding = []", self.validate(p))

    def test_profile_round_trip_and_reject_duplicate_inputs(self):
        p = new_profile()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.json"
            save_profile(path, p)
            self.assertEqual(load_profile(path), p)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        p["plates"]["12"][1]["trigger"] = "KEY_1"
        with self.assertRaises(ValueError):
            runtime_config(p)

    def test_gui_macro_serializes_to_rust(self):
        p = new_profile()
        p["plates"]["12"][0].update(mode="macro", steps=[{"down": "Ctrl"}, {"tap": "C"}, {"up": "Ctrl"}, {"wait_ms": 50}, {"tap": "Enter"}])
        self.validate(p)


class Session(unittest.TestCase):
    def test_eof_shuts_down_helper_and_bad_commands_are_reported(self):
        result = subprocess.run([str(ENGINE), "session"], input='{"command":"apply","config":"not toml"}\n{"command":"bad"}\n', capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 0, result.stderr)
        events = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(events[0]["type"], "hello")
        self.assertEqual(len([e for e in events if e["type"] == "error"]), 2)


MOCK = '''#!/usr/bin/env python3
import sys,json
if sys.argv[1:]==["list","--json"]:
 print(json.dumps([{"path":"/dev/input/event23","name":"Test Naga"}]))
elif sys.argv[1]=="check":
 sys.exit(0)
else:
 print(json.dumps({"type":"hello","protocol":1}),flush=True)
 for line in sys.stdin:
  message=json.loads(line)
  if message["command"]=="shutdown":break
  print(json.dumps({"type":"state","state":"monitoring" if message["command"]=="monitor" or "binding = []" in message.get("config","") else "running"}),flush=True)
'''


class QtFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        # These tests drive processEvents rather than app.exec: explicitly drain
        # deferred deletion before Python tears down the shared QApplication.
        for widget in self.app.topLevelWidgets():
            if isinstance(widget, Window):
                widget.quitting = True
            widget.close()
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def spin_until(self, predicate):
        deadline = time.monotonic() + 3
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertTrue(predicate())

    def test_edit_apply_learn_switch_plate_and_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            mock = path / "mock-backend"
            mock.write_text(MOCK)
            mock.chmod(0o755)
            previous = os.environ.get("NAGALIBRE_BACKEND")
            previous_access = os.environ.get("NAGALIBRE_NO_PKEXEC")
            os.environ["NAGALIBRE_BACKEND"] = str(mock)
            os.environ["NAGALIBRE_NO_PKEXEC"] = "1"
            window = Window(path / "profile.json")
            try:
                window.connect_mouse()
                self.spin_until(lambda: window.backend.ready and "Connected" in window.status.text())
                window.mode.setCurrentIndex(window.mode.findData("key"))
                window.key_value.setText("F13")
                window.apply()
                self.spin_until(lambda: window.status.text().startswith("Active"))
                self.assertEqual(load_profile(window.path)["plates"]["12"][0]["value"], "F13")
                window.plate.setCurrentIndex(window.plate.findData("6"))
                self.assertEqual(len(window.tiles), 6)
                window.learn_input()
                self.spin_until(lambda: window.learning)
                window.on_event({"type": "input", "key": "BTN_SIDE", "value": 1})
                self.assertEqual(window.current()["trigger"], "BTN_SIDE")
                self.assertFalse(window.learning)
                window.plate.setCurrentIndex(window.plate.findData("12"))
                self.assertEqual(window.current()["value"], "F13")
                window.reset_defaults()
                self.spin_until(lambda: not window.applying)
                self.assertTrue(all(b["mode"] == "default" for b in window.buttons()))
                self.assertEqual(window.profile["plates"]["6"][0]["trigger"], "BTN_SIDE")
            finally:
                window.quitting = True
                window.close()
                for name, value in [("NAGALIBRE_BACKEND", previous), ("NAGALIBRE_NO_PKEXEC", previous_access)]:
                    if value is None:
                        os.environ.pop(name, None)
                    else:
                        os.environ[name] = value

    def test_macro_dialog_roundtrip(self):
        steps = [{"chord": ["KEY_LEFTCTRL", "KEY_C"]}, {"wait_ms": 40}, {"tap": "KEY_ENTER"}]
        dialog = MacroDialog(steps)
        self.assertEqual(dialog.steps(), steps)
        dialog.table.setCurrentCell(2, 1)
        dialog.move(-1)
        self.assertEqual(dialog.steps(), [steps[0], steps[2], steps[1]])
        dialog.close()

    def test_bad_saved_profile_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            path.write_text("[]")
            window = Window(path)
            self.assertIsNotNone(window.load_error)
            window.save()
            window.quitting = True
            window.close()
            self.assertEqual(path.read_text(), "[]")


if __name__ == "__main__":
    unittest.main()
