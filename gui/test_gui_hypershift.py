"""Layer drafts, migration, and the paired-backup commit boundary; no real hardware."""
import copy
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
from app import Window
from model import new_profile, load_profile, save_profile, keep_binding, runtime_config, DEVICE_MODELS
from onboard import layer_edits, hardware_buttons, draft_from_record, stored_label, write_layer_backup


def paired_state():
    normal = {"format": 1, "device": {"serial": "TEST", "product": 167, "path": "fake"},
              "slots": [1, 2], "slot_capacity": 5, "active": 1, "slot": 1, "mode": [0, 0],
              "primary": [{"button": n, "category": 1, "data": [n]} for n in (1, 2)],
              "buttons": hardware_buttons(new_profile()),
              "controls": [{"button": c["button"], **copy.deepcopy(c["binding"])}
                           for c in DEVICE_MODELS["naga_v2_pro"]["defaults"]["controls"]]}
    unknown = {"button": 3, "category": 126, "data": [222, 173], "raw_record": [126, 2, 222, 173, 1, 2, 3]}
    normal["buttons"][2] = copy.deepcopy(unknown)
    echoes = [{"button": n, "layer": 0} for n in range(1, 17)]
    secondary = {"layer": 1, "primary_inspected": False, "echoes": copy.deepcopy(echoes),
                 "buttons": copy.deepcopy(normal["buttons"]), "controls": copy.deepcopy(normal["controls"])}
    secondary["controls"][0] = {"button": 13, "category": 14, "data": [104], "raw_record": [14, 1, 104, 0, 20, 0, 0]}
    return {"format": 1, "normal": normal, "normal_echoes": echoes, "hypershift": secondary}


def paired_backup(state):
    slots = []
    for slot in state["normal"]["slots"]:
        snapshot = copy.deepcopy(state)
        snapshot["normal"]["slot"] = slot
        slots.append({"state": snapshot, "middle": {"button": 3, "category": 1, "data": [3]}})
    return {"format": 1, "kind": "paired_mapping_backup", "slots": slots}


class LayerProfiles(unittest.TestCase):
    def test_v1_migration_preserves_all_edits_and_adds_keep_secondary_without_rewriting_file(self):
        profile = new_profile()
        profile.pop("hypershift")
        profile.update(version=1, extra={"preserve": True})
        profile["plates"]["12"][0].update(mode="shortcut", value="Ctrl+B")
        profile["plates"]["6"][0].update(mode="macro", steps=[{"tap": "F13"}])
        profile["controls"] = [{"trigger": "", "mode": "key", "value": key, "steps": []} for key in ("F13", "F14", "F15")]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "profiles.json"
            save_profile(path, profile)
            original_bytes = path.read_bytes()
            migrated = load_profile(path)
            self.assertEqual(migrated["version"], 2)
            self.assertEqual(migrated["plates"], profile["plates"])
            self.assertEqual(migrated["controls"][:3], profile["controls"])
            self.assertEqual(migrated["controls"][3]["mode"], "default")
            self.assertTrue(all(b["mode"] == "keep" for b in migrated["hypershift"]))
            self.assertEqual(migrated["extra"], profile["extra"])
            self.assertEqual(path.read_bytes(), original_bytes)
            migrated["hypershift"][0].update(mode="key", value="B")
            migrated["controls"][3]["mode"] = "hypershift"
            save_profile(path, migrated)
            self.assertEqual(load_profile(path), migrated)

    def test_unknown_records_are_kept_and_nested_trigger_profiles_are_rejected(self):
        state = paired_state()
        self.assertEqual(draft_from_record(state["hypershift"]["controls"][0], secondary=True)["mode"], "keep")
        self.assertEqual(draft_from_record(state["normal"]["buttons"][2])["mode"], "keep")
        self.assertEqual(stored_label({"category": 12, "data": [1]}), "Hold for Hypershift")
        profile = new_profile()
        profile["hypershift"][0]["mode"] = "hypershift"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "profile.json"
            save_profile(path, profile)
            with self.assertRaises(ValueError):
                load_profile(path)
        with self.assertRaises(ValueError):
            layer_edits(profile)

    def test_sparse_translation_and_software_exclusion(self):
        profile = new_profile()
        profile["plates"]["12"] = [keep_binding() for _ in range(12)]
        profile["controls"][3]["mode"] = "hypershift"
        profile["hypershift"][0].update(mode="key", value="B")
        self.assertEqual(layer_edits(profile), [
            {"layer": 0, "action": {"button": 16, "category": 12, "data": [1]}},
            {"layer": 1, "action": {"button": 1, "category": 2, "data": [0, 5]}}])
        profile["plates"]["12"][0]["mode"] = "hypershift"
        with self.assertRaisesRegex(ValueError, "Mouse memory"):
            runtime_config(profile)


class LayerGui(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        for widget in self.app.topLevelWidgets():
            if isinstance(widget, Window):
                widget.quitting = True
            widget.close()
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def window(self, path):
        window = Window(path)
        window.backend.ready = True
        window.backend.protocol = 4
        window.backend.hypershift_transactions = True
        window.backend.slot_activation = True
        window.detected_module = 3
        window.plate_detection = "auto"
        window.on_event({"type": "onboard_layers_snapshot", "snapshot": paired_state()})
        return window

    def test_layer_switching_and_local_save_keep_independent_drafts(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "profiles.json"
            window = self.window(path)
            window.mode.setCurrentIndex(window.mode.findData("key"))
            window.key_value.setText("F13")
            window.layer.setCurrentIndex(1)
            self.assertIn("Keep stored binding", window.tiles[0].text())
            window.mode.setCurrentIndex(window.mode.findData("key"))
            window.key_value.setText("B")
            window.layer.setCurrentIndex(0)
            self.assertEqual(window.key_value.text(), "F13")
            window.save()
            saved = load_profile(path)
            self.assertEqual(saved["plates"]["12"][0]["value"], "F13")
            self.assertEqual(saved["hypershift"][0]["value"], "B")
            window.slots.setCurrentIndex(window.slots.findData(2))
            self.assertFalse(window.apply_button.isEnabled())
            self.assertIn("unread", window.stored_text(0))

    def test_read_preserves_draft_and_copy_stored_keeps_unknown_actions(self):
        with tempfile.TemporaryDirectory() as temporary:
            window = self.window(Path(temporary) / "profile.json")
            window.mode.setCurrentIndex(window.mode.findData("key"))
            window.key_value.setText("F13")
            window.on_event({"type": "onboard_layers_snapshot", "snapshot": paired_state()})
            self.assertEqual(window.key_value.text(), "F13")
            with patch.object(window.backend, "send") as send:
                window.use_stored_button.click()
                self.assertEqual(window.profile["plates"]["12"][2]["mode"], "keep")
                self.assertEqual(window.profile["hypershift"][2]["mode"], "keep")
                self.assertEqual(window.profile["hypershift"][12]["mode"], "keep")
                window.layer.setCurrentIndex(1)
                self.assertIn("Action 7e", window.stored_text(2))
                self.assertFalse(window.mode.model().item(window.mode.findData("hypershift")).isEnabled())
                window.reset_defaults()
                self.assertTrue(all(b["mode"] == "keep" for b in window.profile["hypershift"]))
                send.assert_not_called()

    def test_paired_prepare_persists_all_slot_raw_backup_before_commit_and_stops_helper(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "profile.json"
            window = self.window(path)
            window.use_stored_draft()
            window.select_button(15)
            window.mode.setCurrentIndex(window.mode.findData("hypershift"))
            window.layer.setCurrentIndex(1)
            window.select_button(0)
            window.mode.setCurrentIndex(window.mode.findData("key"))
            window.key_value.setText("B")
            with patch.object(window.backend, "send") as send:
                window.apply()
                message = send.call_args.args[0]
                self.assertEqual(message["command"], "onboard_layers_prepare")
                self.assertIn({"layer": 0, "action": {"button": 16, "category": 12, "data": [1]}}, message["edits"])
                self.assertIn({"layer": 1, "action": {"button": 1, "category": 2, "data": [0, 5]}}, message["edits"])
                self.assertFalse(any(e["action"]["button"] == 3 for e in message["edits"]))
                backup = paired_backup(paired_state())
                window.on_event({"type": "onboard_layers_prepared", "token": "1234", "backup": backup})
                self.assertEqual(send.call_args.args[0], {"command": "onboard_commit", "token": "1234"})
                files = list((path.parent / "backups").glob("*.json"))
                self.assertEqual(len(files), 1)
                self.assertEqual(json.loads(files[0].read_text()), backup)
                self.assertEqual(files[0].stat().st_mode & 0o777, 0o600)
            with patch.object(window.backend, "shutdown") as shutdown:
                window.on_event({"type": "onboard_layers_saved", "snapshot": paired_state()})
            shutdown.assert_called_once()
            self.assertEqual(window.hardware_saved, 1)

    def test_failed_backup_or_error_invalidates_commit_and_stored_layer_view(self):
        with tempfile.TemporaryDirectory() as temporary:
            window = self.window(Path(temporary) / "profile.json")
            with patch.object(window.backend, "send") as send, patch.object(window.backend, "shutdown"), patch(
                    "app.write_layer_backup", side_effect=OSError("fsync failed")):
                window.on_event({"type": "onboard_layers_prepared", "token": "1234", "backup": paired_backup(paired_state())})
                send.assert_not_called()
                self.assertIn("mouse was not changed", window.status.text())
            window.on_event({"type": "error", "message": "stale paired state"})
            self.assertIsNone(window.paired_snapshot)
            self.assertIsNone(window.snapshot)
            self.assertFalse(window.apply_button.isEnabled())

    def test_restore_routes_paired_and_legacy_backups_and_rejects_diagnostics(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            window = self.window(root / "profile.json")
            for backup, command in ((paired_backup(paired_state()), "onboard_layers_restore"),
                                    (paired_state()["normal"], "onboard_layers_restore_normal")):
                path = root / "backup.json"
                path.write_text(json.dumps(backup))
                with patch("app.QFileDialog.getOpenFileName", return_value=(str(path), "")), patch.object(window.backend, "send") as send:
                    window.restore_backup()
                    self.assertEqual(send.call_args.args[0]["command"], command)
            path.write_text(json.dumps(paired_state()))
            with patch("app.QFileDialog.getOpenFileName", return_value=(str(path), "")), patch.object(window.backend, "send") as send:
                window.restore_backup()
                send.assert_not_called()
                self.assertIn("not a restorable", window.status.text())

    def test_receiver_keeps_secondary_draft_but_cannot_send_layer_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            window = self.window(Path(temporary) / "profile.json")
            window.profile["hypershift"][0].update(mode="key", value="B")
            window.layer.setCurrentIndex(1)
            window.backend.hypershift_transactions = False
            with patch.object(window.backend, "send") as send:
                window.connection_changed(True)
                self.assertEqual(window.layer.currentData(), 0)
                self.assertEqual(window.profile["hypershift"][0]["value"], "B")
                self.assertFalse(window.layer.model().item(1).isEnabled())
                self.assertFalse(any("layers" in c.args[0]["command"] for c in send.call_args_list))
            with self.assertRaises(ValueError):
                window.connected_hardware_command({"command": "onboard_layers_restore", "backup": {}})


    def test_paired_activation_saves_all_banks_and_keeps_layer_draft_while_switching(self):
        with tempfile.TemporaryDirectory() as temporary:
            window = self.window(Path(temporary) / "profile.json")
            window.layer.setCurrentIndex(1)
            window.mode.setCurrentIndex(window.mode.findData("key"))
            window.key_value.setText("B")
            backup = paired_backup(paired_state())
            with patch.object(window.backend, "send") as send:
                window.on_event({"type":"onboard_layers_activation_prepared","backup":backup,"token":"777"})
                self.assertEqual(send.call_args.args[0],{"command":"onboard_commit","token":"777"})
                after = paired_state();after["normal"].update(slot=2,active=2)
                window.on_event({"type":"onboard_layers_activated","snapshot":after})
                self.assertEqual(window.profile["hypershift"][0]["value"],"B")
                self.assertEqual(window.snapshot["active"],2)
                self.assertIsNotNone(window.paired_snapshot)
                self.assertTrue(window.apply_button.isEnabled())

    def test_creation_does_not_commit_if_additional_paired_backup_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            window = self.window(Path(temporary) / "profile.json")
            pair = paired_backup(paired_state())
            old = {"format":1,"target":3,"snapshots":[s["state"]["normal"] for s in pair["slots"]]}
            with patch.object(window.backend,"send") as send, patch.object(window.backend,"shutdown"), patch(
                    "app.write_layer_backup",side_effect=OSError("paired fsync failed")):
                window.on_event({"type":"onboard_creation_prepared","backup":old,"paired_backup":pair,"token":"778"})
                send.assert_not_called()
                self.assertIn("mouse was not changed",window.status.text())

    def test_paired_save_and_restore_through_real_qprocess_keep_local_draft_and_opaque_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_path, trace = root / "mouse.json", root / "trace.jsonl"
            original = paired_state()
            state_path.write_text(json.dumps(original))
            engine = root / "engine"
            engine.write_text("#!/usr/bin/env python3\n" + "\n".join([
                "import json,sys,pathlib,copy,time",
                f"state_path=pathlib.Path({str(state_path)!r})",
                f"trace=pathlib.Path({str(trace)!r})",
                "if sys.argv[1]=='list': print('[]');sys.exit(0)",
                "state=json.loads(state_path.read_text());pending=None",
                "def emit(value): print(json.dumps(value),flush=True)",
                "def backup():",
                " slots=[]",
                " for slot in state['normal']['slots']:",
                "  item=copy.deepcopy(state);item['normal']['slot']=slot",
                "  slots.append({'state':item,'middle':{'button':3,'category':1,'data':[3]}})",
                " return {'format':1,'kind':'paired_mapping_backup','slots':slots}",
                "emit({'type':'hello','protocol':4,'wheel_controls':True,'slot_activation':True,'hypershift_transactions':True})",
                "for line in sys.stdin:",
                " m=json.loads(line)",
                " with trace.open('a') as out:out.write(line)",
                " command=m['command']",
                " if command=='shutdown':break",
                " if command=='faceplate':emit({'type':'faceplate','module_id':3,'buttons':12})",
                " elif command=='onboard_layers_read':emit({'type':'onboard_layers_snapshot','snapshot':state})",
                " elif command in ('onboard_layers_prepare','onboard_layers_restore'):",
                "  pending=m;emit({'type':'onboard_layers_prepared','token':str(time.time_ns()),'backup':backup()})",
                " elif command=='onboard_commit':",
                "  if pending['command']=='onboard_layers_restore':state=copy.deepcopy(pending['backup']['slots'][0]['state'])",
                "  else:",
                "   for edit in pending['edits']:",
                "    layer=edit['layer'];action=edit['action'];bank=state['hypershift'] if layer else state['normal']",
                "    key='buttons' if action['button']<=12 else 'controls'",
                "    index=next(i for i,b in enumerate(bank[key]) if b['button']==action['button'])",
                "    old=bank[key][index]",
                "    if old['category']==action['category'] and old['data']==action['data']:continue",
                "    bank[key][index]=action",
                "    for echoes in (state['normal_echoes'],state['hypershift']['echoes']):next(e for e in echoes if e['button']==action['button'])['layer']=layer",
                "  state_path.write_text(json.dumps(state));emit({'type':'onboard_layers_saved','snapshot':state})",
            ]))
            engine.chmod(0o700)

            def wait(predicate):
                deadline = time.monotonic()+5
                while not predicate() and time.monotonic()<deadline:
                    self.app.processEvents()
                    time.sleep(0.005)
                self.assertTrue(predicate())

            with patch.dict(os.environ, {"NAGALIBRE_BACKEND":str(engine),"NAGALIBRE_NO_PKEXEC":"1"}):
                window = Window(root / "profile.json")
                window.connect_mouse()
                wait(lambda: window.paired_snapshot is not None and not window.hardware_busy)
                self.assertTrue(window.backend.hypershift_transactions)
                window.use_stored_draft()
                window.select_button(15)
                window.mode.setCurrentIndex(window.mode.findData("hypershift"))
                window.layer.setCurrentIndex(1)
                window.select_button(0)
                window.mode.setCurrentIndex(window.mode.findData("key"))
                window.key_value.setText("B")
                window.apply()
                wait(lambda: not window.backend.ready and window.hardware_saved == 1)
                applied = json.loads(state_path.read_text())
                self.assertEqual(applied['normal']['controls'][3]['category'],12)
                self.assertEqual(applied['hypershift']['buttons'][0]['data'],[0,5])
                self.assertEqual(applied['hypershift']['controls'][0],original['hypershift']['controls'][0])
                paths = list((root/'backups').glob('*.json'))
                self.assertEqual(len(paths),1)
                self.assertEqual(json.loads(paths[0].read_text()),paired_backup(original))
                with patch('app.QFileDialog.getOpenFileName',return_value=(str(paths[0]),'')):
                    window.restore_backup()
                wait(lambda: not window.backend.ready and not window.hardware_busy and json.loads(state_path.read_text())==original)
                self.assertEqual(window.profile['hypershift'][0]['value'],'B')
                self.assertEqual(window.profile['controls'][3]['mode'],'hypershift')
                window.use_stored_draft()
                window.save()
                self.assertEqual(load_profile(root/'profile.json')['controls'][3]['mode'],'factory')
                self.assertEqual(window.profile['hypershift'][2]['mode'],'keep')
            commands=[json.loads(line)['command'] for line in trace.read_text().splitlines()]
            self.assertEqual(commands.count('onboard_commit'),2)
            self.assertIn('onboard_layers_restore',commands)
            self.assertNotIn('onboard_prepare',commands)
            self.assertNotIn('onboard_restore',commands)
