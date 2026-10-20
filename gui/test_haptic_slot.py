"""Slot comparison failure cases: durable backup, lost acknowledgements, recovery."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("haptic_slot", Path(__file__).resolve().parent.parent / "scripts/compare_haptic_slot.py")
slot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(slot)


class SlotTests(unittest.TestCase):
    def fixture(self, tmp):
        engine = Path(tmp) / "engine"
        engine.write_bytes(b"helper")
        self.directory = Path(tmp) / "trial"
        self.active = 1
        self.commits = []
        self.fail_view = False
        self.fail_ack = False
        self.stale = False
        self.base = [{"normal": {"device": {"product": 167, "serial": "TEST", "path": "mock"},
                                  "slots": [1, 2], "slot_capacity": 5, "slot": n,
                                  "active": 1, "mode": [0, 0]}, "opaque": [255, n]} for n in (1, 2)]
        return engine

    def pairs(self, engine, expected=None):
        result = copy.deepcopy(self.base)
        for state in result:
            state["normal"]["active"] = self.active
        if expected is not None:
            self.assertEqual(result, expected)
        return result

    def query(self, engine, name, *args):
        self.assertIn(name, ("haptic-read", "haptic-table-views"))
        guard = {"device": self.base[0]["normal"]["device"], "slots": [1, 2], "capacity": 5,
                 "active": self.active, "mode": [0, 0], "module_id": 3}
        if name == "haptic-read":
            return {"format": 1, "kind": "haptic_diagnostic", "guard": guard,
                    "state": {"slot": int(args[1]), "configuration": [int(args[1]), 6], "tables": [[1], [2], [3]]}}
        if self.fail_view and self.active == 2:
            raise ValueError("table read failed")
        return {"format": 1, "kind": "unverified_haptic_table_views", "stable": True, "guard": guard,
                "stored": {"configuration": [self.active, 6], "tables": [[1], [2], [3]]}}

    def session_factory(self, engine):
        owner = self

        class Session:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

            def command(self, name, **kwargs):
                owner.assertIn(name, ("onboard_layers_read", "onboard_activate", "onboard_commit"))
                pairs = owner.pairs(engine)
                if name == "onboard_layers_read":
                    return {"type": "onboard_layers_snapshot", "snapshot": pairs[owner.active - 1]}
                if name == "onboard_activate":
                    self.target = kwargs["slot"]
                    if owner.stale:
                        pairs[1]["opaque"] = [99]
                    return {"type": "onboard_layers_activation_prepared", "token": "123",
                            "backup": {"format": 1, "kind": "paired_mapping_backup",
                                       "slots": [{"state": p, "middle": [1, 3]} for p in pairs]}}
                plan = json.loads((owner.directory / "plan.json").read_text())
                checkpoint = owner.directory / "checkpoint.json"
                owner.assertEqual(slot.digest(checkpoint), plan["checkpoint_sha256"])
                owner.assertIn(plan["status"], ("switching", "restoring"))
                backup = json.loads((owner.directory / plan["activation_backup"]).read_text())
                owner.assertEqual([s["state"] for s in backup["slots"]], pairs)
                owner.commits.append(self.target)
                owner.active = self.target
                if owner.fail_ack and self.target == 2:
                    raise ValueError("acknowledgement lost")
                return {"type": "onboard_layers_activated", "snapshot": owner.pairs(engine)[owner.active - 1]}

        return Session()

    def patches(self):
        return (patch.object(slot, "mappings", side_effect=self.pairs),
                patch.object(slot, "query", side_effect=self.query),
                patch.object(slot, "WheelSession", side_effect=self.session_factory))

    def test_success_only_activates_and_restores_with_durable_backups(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = self.fixture(tmp)
            a, b, c = self.patches()
            with a, b, c:
                slot.run(engine, self.directory, 2)
            self.assertEqual(self.commits, [2, 1])
            self.assertEqual(json.loads((self.directory / "plan.json").read_text())["status"], "restored_captured_state")
            self.assertEqual((self.directory / "checkpoint.json").stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.directory.stat().st_mode & 0o777, 0o700)

    def test_failed_read_and_lost_ack_both_restore_original_slot(self):
        for failure in ("fail_view", "fail_ack"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                engine = self.fixture(tmp)
                setattr(self, failure, True)
                a, b, c = self.patches()
                with a, b, c, self.assertRaises(ValueError):
                    slot.run(engine, self.directory, 2)
                self.assertEqual(self.active, 1)
                self.assertEqual(self.commits, [2, 1])
                self.assertEqual(json.loads((self.directory / "plan.json").read_text())["status"], "restored_captured_state")

    def test_stale_pair_or_failed_backup_prevents_commit(self):
        for failure in ("stale", "backup"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                engine = self.fixture(tmp)
                self.stale = failure == "stale"
                durable = slot.durable_plan

                def save(path, data):
                    if failure == "backup" and path.name == "switching-paired-backup.json":
                        raise OSError("fsync failed")
                    durable(path, data)

                a, b, c = self.patches()
                with a, b, c, patch.object(slot, "durable_plan", side_effect=save), self.assertRaises((OSError, ValueError)):
                    slot.run(engine, self.directory, 2)
                self.assertEqual(self.commits, [])
                self.assertEqual(self.active, 1)

    def test_recovery_tampering_stops_before_hardware(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = self.fixture(tmp)
            a, b, c = self.patches()
            with a, b, c:
                slot.run(engine, self.directory, 2)
            checkpoint = self.directory / "checkpoint.json"
            checkpoint.write_text(checkpoint.read_text() + " ")
            with patch.object(slot, "mappings") as hardware, self.assertRaisesRegex(ValueError, "checksum"):
                slot.restore(self.directory)
            hardware.assert_not_called()

    def test_changed_wheel_after_restore_is_reported_without_curve_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = self.fixture(tmp)
            real_query = self.query

            def changed(*args):
                report = real_query(*args)
                if self.commits == [2, 1] and args[1] == "haptic-read":
                    report["state"]["tables"][2] = [99]
                return report

            a, b, c = self.patches()
            with a, b, c, patch.object(slot, "query", side_effect=changed), self.assertRaisesRegex(ValueError, "captured state differs"):
                slot.run(engine, self.directory, 2)
            self.assertEqual(self.commits, [2, 1])
            self.assertEqual(self.active, 1)
            self.assertEqual(json.loads((self.directory / "plan.json").read_text())["status"], "verification_failed")
            self.assertTrue((self.directory / "after-restoration.json").exists())

    def test_recovery_is_available_after_failed_restore_ack(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = self.fixture(tmp)
            session_factory = self.session_factory
            fail_once = True

            def factory(helper):
                session = session_factory(helper)
                command = session.command

                def lost_ack(name, **kwargs):
                    nonlocal fail_once
                    event = command(name, **kwargs)
                    if name == "onboard_commit" and self.active == 1 and fail_once:
                        fail_once = False
                        raise ValueError("restore acknowledgement lost")
                    return event

                session.command = lost_ack
                return session

            a, b, c = self.patches()
            with a, b, c, patch.object(slot, "WheelSession", side_effect=factory):
                with self.assertRaisesRegex(ValueError, "restore acknowledgement lost"):
                    slot.run(engine, self.directory, 2)
                self.assertEqual(json.loads((self.directory / "plan.json").read_text())["status"], "restoring")
                slot.restore(self.directory)
            self.assertEqual(self.commits, [2, 1])
            self.assertEqual(json.loads((self.directory / "plan.json").read_text())["status"], "restored_captured_state")


if __name__ == "__main__":
    unittest.main()
