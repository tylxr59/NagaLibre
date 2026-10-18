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
from onboard import hardware_buttons, write_backup
from unittest.mock import patch
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

    def test_primary_click_cannot_be_bound_and_reset_clears_old_bad_inputs(self):
        p = new_profile()
        for trigger in ("BTN_LEFT", "BTN_RIGHT", "BTN_MIDDLE", "BTN_MOUSE"):
            p["plates"]["12"][0].update(trigger=trigger, mode="key", value="A")
            with self.assertRaises(ValueError):
                runtime_config(p)
        reset_plate(p, "12")
        self.assertEqual(p["plates"]["12"][0]["trigger"], "KEY_1")
        p["plate"] = "2"
        p["plates"]["2"][0].update(trigger="BTN_LEFT", mode="key", value="A")
        reset_plate(p, "2")
        self.assertEqual(p["plates"]["2"][0]["trigger"], "")
        self.validate(p)


class HardwareTranslation(unittest.TestCase):
    def test_factory_keys_shortcuts_and_rejection_before_writes(self):
        p = new_profile()
        bindings = hardware_buttons(p)
        self.assertEqual([b["data"][1] for b in bindings], list(range(0x1e, 0x28)) + [0x2d, 0x2e])
        p["plates"]["12"][0].update(mode="shortcut", value="Ctrl+Shift+B", trigger="BTN_LEFT")
        self.assertEqual(hardware_buttons(p)[0], {"button": 1, "category": 2, "data": [3, 5]})
        p["plates"]["12"][1].update(mode="macro", steps=[{"tap": "A"}])
        with self.assertRaises(ValueError):
            hardware_buttons(p)
        p["plate"] = "6"
        with self.assertRaises(ValueError):
            hardware_buttons(p)

    def test_durable_private_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = {"device": {"serial": "../TEST"}, "slot": 1}
            path = write_backup(Path(directory) / "profiles.json", snapshot, "123")
            self.assertEqual(path.parent, Path(directory) / "backups")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(path.read_text()), snapshot)
            with self.assertRaises(ValueError):
                write_backup(Path(directory) / "profiles.json", snapshot, "../bad")


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
                window.storage.setCurrentIndex(window.storage.findData("software"))
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
                for code in ("BTN_LEFT", "BTN_RIGHT", "BTN_MIDDLE"):
                    window.on_event({"type": "input", "key": code, "value": 1})
                    self.assertEqual(window.current()["trigger"], "")
                    self.assertTrue(window.learning)
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

    def test_onboard_save_through_real_qprocess_and_reconnect(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trace = root / "commands.jsonl"
            mock = root / "engine"
            mock.write_text("#!/usr/bin/env python3\n" + "\n".join([
                "import sys,json,pathlib",
                f"trace=pathlib.Path({str(trace)!r})",
                "snapshot={'device':{'serial':'TEST'},'slot':1,'active':1,'slots':[1,2],'buttons':[]}",
                "if sys.argv[1]=='list': print('[]');sys.exit(0)",
                "print(json.dumps({'type':'hello','protocol':2}),flush=True)",
                "for line in sys.stdin:",
                " m=json.loads(line)",
                " with trace.open('a') as f:f.write(line)",
                " c=m['command']",
                " if c=='shutdown':break",
                " if c=='onboard_read': event={'type':'onboard_snapshot','snapshot':snapshot}",
                " elif c=='onboard_prepare': event={'type':'onboard_prepared','backup':snapshot,'token':'123'}",
                " elif c=='onboard_commit': event={'type':'onboard_saved','snapshot':snapshot}",
                " else:raise Exception(c)",
                " print(json.dumps(event),flush=True)",
            ]))
            mock.chmod(0o755)
            with patch.dict(os.environ, {"NAGALIBRE_BACKEND": str(mock), "NAGALIBRE_NO_PKEXEC": "1"}):
                window = Window(root / "profiles.json")
                window.mode.setCurrentIndex(window.mode.findData("key"))
                window.key_value.setText("B")
                window.apply()
                self.spin_until(lambda: window.hardware_saved == 1 and not window.backend.ready)
                commands = [json.loads(line) for line in trace.read_text().splitlines()]
                self.assertEqual([m['command'] for m in commands], ['onboard_read','onboard_prepare','onboard_commit','shutdown'])
                self.assertEqual(commands[1]['buttons'][0], {'button':1,'category':2,'data':[0,5]})
                self.assertTrue(list((root / "backups").glob("*.json")))
                # A second save starts a fresh helper and reads state again.
                window.apply()
                self.spin_until(lambda: window.hardware_saved == 1 and not window.backend.ready)
                self.assertEqual(len(trace.read_text().splitlines()), 8)

    def test_hardware_prepare_backs_up_before_commit_and_stops_helper(self):
        with tempfile.TemporaryDirectory() as directory:
            window = Window(Path(directory) / "profiles.json")
            snapshot = {"device": {"serial": "TEST"}, "slot": 1, "active": 1, "slots": [1, 2], "buttons": []}
            window.on_event({"type": "onboard_snapshot", "snapshot": snapshot})
            self.assertEqual(window.slots.count(), 2)
            sent = []
            def send(command):
                self.assertTrue(list((window.path.parent / "backups").glob("*.json")))
                sent.append(command)
            with patch.object(window.backend, "send", side_effect=send):
                window.on_event({"type": "onboard_prepared", "backup": snapshot, "token": "123"})
            self.assertEqual(sent, [{"command": "onboard_commit", "token": "123"}])
            with patch.object(window.backend, "shutdown") as shutdown:
                window.on_event({"type": "onboard_saved", "snapshot": snapshot})
                shutdown.assert_called_once()
            window.connection_changed(False)
            self.assertIn("helper stopped", window.status.text())
            self.assertIsNone(window.snapshot)

    def test_failed_hardware_backup_never_commits(self):
        with tempfile.TemporaryDirectory() as directory:
            window = Window(Path(directory) / "profiles.json")
            with patch("app.write_backup", side_effect=OSError("disk full")), patch.object(window.backend, "send") as send, patch.object(window.backend, "shutdown"):
                window.on_event({"type": "onboard_prepared", "backup": {}, "token": "123"})
                send.assert_not_called()
                self.assertIn("mouse was not changed", window.status.text())
            self.assertFalse(window.hardware_busy)

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
