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
import backend
from onboard import hardware_buttons, write_backup, stored_label
from unittest.mock import patch
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from support import device_issue_url
from model import DEFAULT_KEYS, DEVICE_MODELS, load_profile, new_profile, reset_plate, runtime_config, save_profile

ENGINE = Path(os.environ.get("NAGALIBRE_TEST_BACKEND", "target/debug/naga-macros")).resolve()


class SourceBuildLookup(unittest.TestCase):
    def test_support_link_prefills_only_public_ids_and_registry_names(self):
        devices = [
            {"vendor": 0x1532, "product": 0xa7},
            {"vendor": 0x1532, "product": 0x67, "name": "PRIVATE_SERIAL"},
            {"vendor": 0x1532, "product": 0xffff, "name": "PRIVATE_NAME&body=secret"},
            {"vendor": 0x1532, "product": 0xffff},
            {"vendor": 0x1234, "product": 1, "name": "PRIVATE_KEYBOARD"},
        ]
        url = device_issue_url(devices)
        fields = parse_qs(urlparse(url).query)
        self.assertEqual(urlparse(url).netloc, "github.com")
        self.assertEqual(fields["template"], ["device-support.yml"])
        self.assertTrue(fields["title"][0].startswith("[Device support]: Unrecognized"))
        self.assertEqual(fields["model"][0].count("1532:ffff"), 1)
        self.assertNotIn("PRIVATE", url)
        self.assertNotIn("body", fields)
        self.assertEqual(parse_qs(urlparse(device_issue_url()).query), {"template": ["device-support.yml"]})
    def test_source_build_takes_precedence_over_legacy_preview_binaries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "gui").mkdir()
            (root / "dist").mkdir()
            (root / "naga-macros").touch()
            (root / "dist/naga-macros").touch()
            with patch.object(backend, "__file__", str(root / "gui/backend.py")), patch.dict(os.environ, {"NAGALIBRE_BACKEND": ""}):
                # Even with no build yet, report the source build path rather
                # than silently executing an obsolete preview.
                self.assertEqual(backend.backend_path(), root / "target/release/naga-macros")
                (root / "target/release").mkdir(parents=True)
                (root / "target/release/naga-macros").touch()
                self.assertEqual(backend.backend_path(), root / "target/release/naga-macros")

    def test_explicit_backend_override_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Path(directory) / "custom-engine"
            with patch.dict(os.environ, {"NAGALIBRE_BACKEND": str(engine)}):
                self.assertEqual(backend.backend_path(), engine.resolve())


class Profiles(unittest.TestCase):
    def test_experimental_profiles_require_learning_and_keep_layouts_on_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            for device in DEVICE_MODELS:
                if device == "naga_v2_pro":
                    continue
                p = new_profile(device)
                self.assertEqual(list(p["plates"]), DEVICE_MODELS[device]["plates"])
                self.assertTrue(all(not b["trigger"] for buttons in p["plates"].values() for b in buttons))
                self.validate(p)
                p["plates"][p["plate"]][0].update(trigger="BTN_SIDE", mode="key", value="F13")
                self.validate(p)
                path = Path(directory) / f"{device}.json"
                save_profile(path, p)
                self.assertEqual(load_profile(path, device), p)
                with self.assertRaises(ValueError):
                    load_profile(path)
                reset_plate(p, p["plate"])
                self.assertEqual(p["plates"][p["plate"]][0]["trigger"], "BTN_SIDE")

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

    def test_stored_record_labels_use_firmware_data(self):
        self.assertEqual(stored_label({"category": 2, "data": [0, 0x1e]}), "1")
        self.assertEqual(stored_label({"category": 2, "data": [3, 5]}), "Ctrl+Shift+B")
        self.assertEqual(stored_label({"category": 0x12, "data": [7]}), "Action 12: 07")

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
if sys.argv[1]=="list":
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

    def test_unknown_and_experimental_devices_offer_user_opened_support_form(self):
        with tempfile.TemporaryDirectory() as directory:
            window = Window(Path(directory) / "profiles.json")
            unknown = {"vendor": 0x1532, "product": 0xffff, "name": "Razer unknown", "model": None}
            def scan(devices):
                result = SimpleNamespace(returncode=0, stdout=json.dumps(devices), stderr="")
                with patch("app.subprocess.run", return_value=result) as run:
                    window.scan_devices()
                self.assertIn("--all-razer", run.call_args.args[0])
            with patch("app.QDesktopServices.openUrl") as open_url:
                scan([unknown])
                self.assertIn("Unrecognized", window.support_hint.text())
                open_url.assert_not_called()
                window.support_button.click()
                self.assertIn("1532%3Affff", open_url.call_args.args[0].toString())
                experimental = dict(unknown, product=0x67, model=DEVICE_MODELS["naga_trinity"])
                scan([experimental])
                self.assertIn("Experimental", window.support_hint.text())
                scan([])
                self.assertEqual(window.support_hint.text(), "")
                self.assertEqual(window.support_devices, [])

    def test_model_switch_isolates_drafts_and_excludes_vendor_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            window = Window(Path(directory) / "profiles.json")
            window.mode.setCurrentIndex(window.mode.findData("key"))
            window.key_value.setText("B")
            window.pending_onboard = {"command": "onboard_read"}
            window.backend.device = DEVICE_MODELS["naga_trinity"]
            window.backend.protocol = 3
            window.backend.ready = True
            with patch.object(window.backend, "send") as send:
                window.connection_changed(True)
                self.assertFalse(window.is_hardware())
                self.assertEqual([window.plate.itemData(i) for i in range(window.plate.count())], ["12", "7", "2"])
                self.assertFalse(window.storage.model().item(0).isEnabled())
                self.assertIn("unverified", window.device_label.text())
                self.assertEqual(send.call_args.args[0], {"command": "monitor"})
                self.assertEqual(send.call_count, 1)
                window.plate.setCurrentIndex(window.plate.findData("7"))
                self.assertEqual(len(window.tiles), 7)
                window.current().update(trigger="BTN_SIDE", mode="key", value="F13")
                window.select_button(0, commit=False)
                window.persist()
                trinity_path = window.path
                self.assertIn("naga_trinity", str(trinity_path))
                self.assertEqual(load_profile(trinity_path, "naga_trinity")["plate"], "7")
                with self.assertRaises(ValueError):
                    window.hardware_command({"command": "onboard_read"})
                window.backend.device = DEVICE_MODELS["naga_v2_pro"]
                window.connection_changed(True)
                self.assertEqual(window.path, window.base_profile_path)
                self.assertEqual(window.key_value.text(), "B")
                self.assertTrue(window.storage.model().item(0).isEnabled())
                window.backend.device = DEVICE_MODELS["naga_trinity"]
                window.connection_changed(True)
                self.assertEqual(window.path, trinity_path)
                self.assertEqual(window.key_value.text(), "F13")
                window.backend.device = DEVICE_MODELS["viper_v2_pro"]
                window.connection_changed(True)
                self.assertEqual(len(window.tiles), 2)
                self.assertFalse(window.plate.isEnabled())
            window.backend.ready = False

    def test_experimental_model_through_real_process_stays_in_software_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trace = root / "commands.jsonl"
            mock = root / "engine"
            mock.write_text("#!/usr/bin/env python3\n" + "\n".join([
                "import sys,json,pathlib",
                "if sys.argv[1]=='list': print('[]');sys.exit(0)",
                "if sys.argv[1]=='check': sys.exit(0)",
                f"print(json.dumps({dict(type='hello', protocol=3, device=DEVICE_MODELS['naga_trinity'])!r}),flush=True)",
                f"trace=pathlib.Path({str(trace)!r})",
                "for line in sys.stdin:",
                " m=json.loads(line)",
                " with trace.open('a') as f:f.write(line)",
                " c=m['command']",
                " if c=='shutdown':break",
                " assert c in ('monitor','apply'),c",
                " print(json.dumps({'type':'state','state':'running' if c=='apply' else 'monitoring'}),flush=True)",
            ]))
            mock.chmod(0o755)
            with patch.dict(os.environ, {"NAGALIBRE_BACKEND": str(mock), "NAGALIBRE_NO_PKEXEC": "1"}):
                window = Window(root / "profiles.json")
                window.connect_mouse()
                self.spin_until(lambda: window.backend.ready and "Connected" in window.status.text())
                self.assertEqual(window.device_model["id"], "naga_trinity")
                self.assertFalse(window.is_hardware())
                window.learn_input()
                self.spin_until(lambda: window.learning)
                window.on_event({"type": "input", "key": "BTN_SIDE", "value": 1})
                window.mode.setCurrentIndex(window.mode.findData("key"))
                window.key_value.setText("F13")
                window.apply()
                self.spin_until(lambda: window.status.text().startswith("Active"))
                window.backend.shutdown()
                commands = [json.loads(line) for line in trace.read_text().splitlines()]
                self.assertTrue(all(m["command"] in ("monitor", "apply", "shutdown") for m in commands))
                apply = next(m for m in commands if m["command"] == "apply")
                self.assertNotIn("module_id", apply)
                self.assertIn("BTN_SIDE", apply["config"])

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

    def test_detected_plate_switch_keeps_drafts_cancels_learning_and_guards_apply(self):
        with tempfile.TemporaryDirectory() as directory:
            window = Window(Path(directory) / "profile.json")
            window.storage.setCurrentIndex(window.storage.findData("software"))
            window.mode.setCurrentIndex(window.mode.findData("key"))
            window.key_value.setText("F13")
            window.learning = True
            window.pending_config = "old config"
            window.backend.ready = True
            window.backend.protocol = 3
            with patch.object(window.backend, "send") as send:
                window.on_event({"type": "faceplate", "module_id": 4, "buttons": 6})
                self.assertEqual(window.profile["plate"], "6")
                self.assertEqual(len(window.tiles), 6)
                self.assertEqual(window.profile["plates"]["12"][0]["value"], "F13")
                self.assertFalse(window.learning)
                self.assertIsNone(window.pending_config)
                self.assertFalse(window.plate.isEnabled())
                self.assertEqual(send.call_args.args[0], {"command": "monitor"})
                send.reset_mock()
                window.on_event({"type": "faceplate", "module_id": 0, "buttons": None})
                self.assertFalse(window.apply_button.isEnabled())
                window.apply()
                self.assertFalse(any(c.args[0]["command"] == "apply" for c in send.call_args_list))
                window.on_event({"type": "faceplate", "module_id": 2, "buttons": None})
                self.assertEqual(window.profile["plate"], "6")
                self.assertIn("Unrecognized", window.plate_hint.text())
                window.on_event({"type": "faceplate", "module_id": 1, "buttons": 2})
                self.assertEqual(len(window.tiles), 2)
                window.on_event({"type": "faceplate", "module_id": 3, "buttons": 12})
                self.assertEqual(window.key_value.text(), "F13")
                window.apply()
                self.assertEqual(send.call_args.args[0]["module_id"], 3)
                window.on_event({"type": "faceplate", "module_id": None, "buttons": None, "message": "Disconnected"})
                self.assertTrue(window.plate.isEnabled())
                self.assertIn("unavailable", window.plate_hint.text())
            window.backend.ready = False

    def test_initial_detection_discards_config_built_for_previous_plate(self):
        with tempfile.TemporaryDirectory() as directory:
            window = Window(Path(directory) / "profile.json")
            window.storage.setCurrentIndex(window.storage.findData("software"))
            window.backend.ready = True
            window.backend.protocol = 3
            window.pending_config = "stale twelve-button config"
            with patch.object(window.backend, "send") as send:
                window.connection_changed(True)
                self.assertEqual([c.args[0]["command"] for c in send.call_args_list], ["faceplate", "monitor"])
                self.assertIsNone(window.pending_config)
                self.assertFalse(window.plate.isEnabled())
                window.on_event({"type": "faceplate", "module_id": 4, "buttons": 6})
                self.assertEqual(window.profile["plate"], "6")
            window.backend.ready = False

    def test_memory_detection_reads_stored_bindings_without_replacing_draft(self):
        with tempfile.TemporaryDirectory() as directory:
            window = Window(Path(directory) / "profile.json")
            window.backend.ready = True
            window.backend.protocol = 3
            window.mode.setCurrentIndex(window.mode.findData("key"))
            window.key_value.setText("B")
            snapshot = {"device": {"serial": "TEST"}, "slot": 1, "active": 1,
                        "slots": [1, 2], "buttons": hardware_buttons(new_profile())}
            with patch.object(window.backend, "send") as send:
                window.on_event({"type": "faceplate", "module_id": 3, "buttons": 12})
                self.assertEqual(send.call_args.args[0], {"command": "onboard_read", "slot": None})
                self.assertTrue(window.hardware_busy)
                # A detection arriving during the initial connection read must
                # leave that request in flight without sending a duplicate.
                window.on_event({"type": "faceplate", "module_id": 3, "buttons": 12})
                self.assertEqual(send.call_count, 1)
                window.on_event({"type": "onboard_snapshot", "snapshot": snapshot})
                self.assertIn("Stored: 1", window.tiles[0].text())
                self.assertIn("Draft: B", window.tiles[0].text())
                self.assertFalse(window.hardware_busy)
                window.on_event({"type": "faceplate", "module_id": 0, "buttons": None})
                self.assertIsNone(window.snapshot)
                window.on_event({"type": "faceplate", "module_id": 4, "buttons": 6})
                self.assertEqual(send.call_count, 1)
                window.on_event({"type": "faceplate", "module_id": 3, "buttons": 12})
                self.assertEqual(send.call_count, 2)
                self.assertEqual(send.call_args.args[0], {"command": "onboard_read", "slot": 1})
                window.on_event({"type": "onboard_snapshot", "snapshot": snapshot})
                self.assertIn("Stored: 1", window.tiles[0].text())
                self.assertIn("Draft: B", window.tiles[0].text())
                self.assertEqual([c.args[0]["command"] for c in send.call_args_list], ["onboard_read", "onboard_read"])
            window.backend.ready = False

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
            self.assertEqual(window.snapshot, snapshot)

    def test_activate_unread_slot_backs_up_both_slots_and_preserves_draft(self):
        with tempfile.TemporaryDirectory() as directory:
            window = Window(Path(directory) / "profiles.json")
            window.backend.ready = True
            window.backend.protocol = 4
            window.backend.slot_activation = True
            window.detected_module = 3
            before = {"device": {"serial": "TEST"}, "slot": 1, "active": 1, "slots": [1, 2],
                      "buttons": hardware_buttons(new_profile())}
            target = dict(before, slot=2)
            draft = json.loads(json.dumps(window.profile))
            with patch.object(window.backend, "send") as send:
                window.on_event({"type": "onboard_snapshot", "snapshot": before})
                self.assertFalse(window.activate_button.isEnabled())
                window.slots.setCurrentIndex(1)
                self.assertTrue(window.activate_button.isEnabled())
                window.activate_button.click()
                send.assert_called_once_with({"command": "onboard_activate", "slot": 2})
                self.assertFalse(window.activate_button.isEnabled())
                send.reset_mock()
                def verify_backups(command):
                    backups = list((Path(directory) / "backups").glob("*.json"))
                    self.assertEqual(len(backups), 2)
                    self.assertEqual({json.loads(p.read_text())["slot"] for p in backups}, {1, 2})
                send.side_effect = verify_backups
                window.on_event({"type": "onboard_activation_prepared", "backup": target,
                                 "previous": before, "token": "910"})
                send.assert_called_once_with({"command": "onboard_commit", "token": "910"})
                window.on_event({"type": "onboard_activated", "snapshot": dict(target, active=2)})
                self.assertEqual(window.profile, draft)
                self.assertIn("Slot 2 active", window.status.text())
                self.assertIn("active", window.slots.currentText())
                self.assertFalse(window.activate_button.isEnabled())
            window.backend.ready = False

    def test_activation_second_backup_failure_prevents_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            window = Window(Path(directory) / "profiles.json")
            with patch("app.write_backup", side_effect=[Path(directory) / "first.json", OSError("fsync failed")]), \
                    patch.object(window.backend, "send") as send, \
                    patch.object(window.backend, "shutdown") as shutdown:
                window.on_event({"type": "onboard_activation_prepared", "backup": {},
                                 "previous": {}, "token": "910"})
                send.assert_not_called()
                shutdown.assert_called_once()

    def test_create_slot_backs_up_all_slots_before_commit_and_keeps_draft(self):
        with tempfile.TemporaryDirectory() as directory:
            window = Window(Path(directory) / "profiles.json")
            window.backend.ready = True
            window.backend.protocol = 4
            window.backend.slot_creation = True
            window.detected_module = 3
            snapshot = {"device": {"serial": "TEST", "product": 0xA7}, "slot": 1,
                        "active": 1, "slots": [1, 2], "slot_capacity": 5,
                        "buttons": hardware_buttons(new_profile())}
            plan = {"format": 1, "target": 3, "snapshots": [snapshot, dict(snapshot, slot=2)]}
            draft = json.loads(json.dumps(window.profile))
            with patch.object(window.backend, "send") as send:
                window.on_event({"type": "onboard_snapshot", "snapshot": snapshot})
                self.assertTrue(window.create_button.isEnabled())
                window.create_button.click()
                send.assert_called_once_with({"command": "onboard_create", "slot": 3})
                self.assertFalse(window.create_button.isEnabled())
                send.reset_mock()
                def verify_backup(command):
                    backups = list((Path(directory) / "backups").glob("*-create-slot-3-*.json"))
                    self.assertEqual(len(backups), 1)
                    self.assertEqual(json.loads(backups[0].read_text()), plan)
                    self.assertEqual(backups[0].stat().st_mode & 0o777, 0o600)
                send.side_effect = verify_backup
                window.on_event({"type": "onboard_creation_prepared", "backup": plan, "token": "789"})
                send.assert_called_once_with({"command": "onboard_commit", "token": "789"})
                window.on_event({"type": "onboard_created", "snapshot": dict(snapshot, slot=3, slots=[1, 2, 3])})
                self.assertEqual(window.profile, draft)
                self.assertEqual(window.slots.currentData(), 3)
                self.assertIn("slot 1 remains active", window.status.text())
                self.assertTrue(window.slots.model().item(2).isEnabled())
                self.assertEqual(window.create_button.text(), "Create slot 4")
            window.backend.ready = False

    def test_creation_backup_failure_never_commits_and_capabilities_gate_button(self):
        with tempfile.TemporaryDirectory() as directory:
            window = Window(Path(directory) / "profiles.json")
            window.backend.ready = True
            snapshot = {"slot": 1, "active": 1, "slots": [1, 2], "slot_capacity": 5,
                        "buttons": hardware_buttons(new_profile())}
            window.on_event({"type": "onboard_snapshot", "snapshot": snapshot})
            self.assertFalse(window.create_button.isEnabled())
            window.backend.slot_creation = True
            window.detected_module = 3
            window.refresh_hardware_view()
            self.assertTrue(window.create_button.isEnabled())
            window.detected_module = 4
            window.refresh_hardware_view()
            self.assertFalse(window.create_button.isEnabled())
            with patch("app.write_creation_backup", side_effect=OSError("fsync failed")), \
                    patch.object(window.backend, "send") as send, \
                    patch.object(window.backend, "shutdown") as shutdown:
                window.on_event({"type": "onboard_creation_prepared", "backup": {}, "token": "789"})
                send.assert_not_called()
                shutdown.assert_called_once()
            window.backend.ready = False

    def test_slot_capacity_shows_uninitialized_entries_without_enabling_them(self):
        with tempfile.TemporaryDirectory() as directory:
            window = Window(Path(directory) / "profiles.json")
            window.backend.ready = True
            snapshot = {"slot": 1, "active": 1, "slots": [1, 2], "slot_capacity": 5,
                        "buttons": hardware_buttons(new_profile())}
            with patch.object(window.backend, "send") as send:
                window.on_event({"type": "onboard_snapshot", "snapshot": snapshot})
                self.assertEqual(window.slots.count(), 5)
                self.assertIn("2 of 5 slots initialized", window.slot_summary.text())
                self.assertEqual(window.slots.currentData(), 1)
                for i in range(5):
                    self.assertEqual(window.slots.model().item(i).isEnabled(), i < 2)
                self.assertIn("uninitialized", window.slots.itemText(2))
                self.assertTrue(window.apply_button.isEnabled())
                send.assert_not_called()
                # Capacity is device data, not a fixed five-entry UI assumption.
                smaller = dict(snapshot, slot_capacity=1, slots=[1])
                window.on_event({"type": "onboard_snapshot", "snapshot": smaller})
                self.assertEqual(window.slots.count(), 1)
                self.assertIn("1 of 1 slots initialized", window.slot_summary.text())
                # Older helpers/backups retain initialized IDs without guessing capacity.
                older = dict(snapshot)
                older.pop("slot_capacity")
                window.on_event({"type": "onboard_snapshot", "snapshot": older})
                self.assertEqual(window.slots.count(), 2)
                self.assertIn("capacity unavailable", window.slot_summary.text())
                window.on_event({"type": "error", "message": "Read failed"})
                self.assertEqual(window.slot_summary.text(), "Slot capacity: unread")
            window.backend.ready = False

    def test_stale_draft_is_never_presented_as_stored_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.json"
            profile = new_profile()
            profile["plates"]["12"][0].update(mode="key", value="B")
            save_profile(path, profile)
            window = Window(path)
            self.assertIn("Stored: unread", window.tiles[0].text())
            self.assertIn("Draft: B", window.tiles[0].text())
            self.assertFalse(window.apply_button.isEnabled())
            snapshot = {"device": {"serial": "TEST"}, "slot": 1, "active": 1, "slots": [1, 2], "buttons": hardware_buttons(new_profile())}
            window.backend.ready = True
            window.on_event({"type": "onboard_snapshot", "snapshot": snapshot})
            self.assertIn("Stored: 1", window.tiles[0].text())
            self.assertIn("Draft: B", window.tiles[0].text())
            self.assertIn("(active): 1", window.stored_binding.text())
            self.assertTrue(window.apply_button.isEnabled())
            window.slots.setCurrentIndex(window.slots.findData(2))
            self.assertIn("Stored: unread", window.tiles[0].text())
            self.assertFalse(window.apply_button.isEnabled())
            window.slots.setCurrentIndex(window.slots.findData(1))
            window.on_event({"type": "error", "message": "Invalid onboard profile inventory"})
            self.assertIn("Stored: unread", window.tiles[0].text())
            self.assertIn("Draft: B", window.tiles[0].text())
            self.assertFalse(window.apply_button.isEnabled())
            self.assertIn("not active bindings", window.status.text())
            window.backend.ready = False

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
