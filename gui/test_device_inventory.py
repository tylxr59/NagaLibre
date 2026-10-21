"""Passive discovery must leave Qt responsive and terminate failed scans."""
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import QProcess, QTimer
from backend import DeviceInventory
from test_macro_storage import APP


class DeviceInventoryTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.engine = Path(self.root.name) / 'inventory'
        self.scanner = DeviceInventory()
        self.results, self.errors = [], []
        self.scanner.inventory.connect(self.results.append)
        self.scanner.failed.connect(self.errors.append)

    def tearDown(self):
        self.scanner.stop()
        self.root.cleanup()

    def script(self, code):
        self.engine.write_text(f'#!{sys.executable}\n' + code)
        self.engine.chmod(0o700)

    def wait(self, predicate):
        deadline = time.monotonic() + 3
        while not predicate() and time.monotonic() < deadline:
            APP.processEvents()
            time.sleep(.002)
        self.assertTrue(predicate())

    def test_slow_scan_leaves_qt_responsive_and_does_not_overlap(self):
        marker = Path(self.root.name) / 'started'
        release = Path(self.root.name) / 'release'
        self.script('import sys,time,pathlib\n'
                    "assert sys.argv[1:] == ['list', '--json', '--all-razer']\n"
                    f'pathlib.Path({str(marker)!r}).touch()\n'
                    f'while not pathlib.Path({str(release)!r}).exists(): time.sleep(.002)\n'
                    "print('[{\"vendor\":5426,\"product\":167}]', flush=True)\n")
        with patch('backend.backend_path', return_value=self.engine):
            self.scanner.scan()
            ticks = []
            QTimer.singleShot(0, lambda: ticks.append(True))
            self.wait(lambda: marker.exists() and ticks)
            self.assertEqual(self.results, [])
            pid = self.scanner.process.processId()
            self.scanner.scan()
            self.assertEqual(self.scanner.process.processId(), pid)
            release.touch()
            self.wait(lambda: bool(self.results))
        self.assertEqual(self.results, [[{'vendor': 5426, 'product': 167}]])
        self.assertEqual(self.errors, [])
        self.assertFalse(self.scanner.timer.isActive())

    def test_invalid_output_and_exit_failure_are_reported_and_can_retry(self):
        with patch('backend.backend_path', return_value=self.engine):
            for output in ('not json', '{}', '[1]'):
                self.script(f'print({output!r})\n')
                count = len(self.errors)
                self.scanner.scan()
                self.wait(lambda: len(self.errors) > count)
            self.script("import sys\nsys.stderr.write('scan failed')\nsys.exit(2)\n")
            self.scanner.scan()
            self.wait(lambda: len(self.errors) == 4)
            self.assertIn('scan failed', self.errors[-1])
            self.script("print('[]')\n")
            self.scanner.scan()
            self.wait(lambda: bool(self.results))
            self.assertEqual(self.results, [[]])

    def test_timeout_missing_engine_and_shutdown_stop_background_process(self):
        with patch('backend.backend_path', return_value=self.engine):
            self.scanner.scan()
            self.wait(lambda: bool(self.errors))
            self.assertFalse(self.scanner.timer.isActive())
            self.script('import time\ntime.sleep(10)\n')
            self.scanner.scan()
            self.scanner.timer.start(20)
            self.wait(lambda: len(self.errors) == 2)
            self.assertIn('timed out', self.errors[-1])
            self.scanner.scan()
            self.scanner.stop()
            self.assertEqual(self.scanner.process.state(), QProcess.ProcessState.NotRunning)
            self.assertFalse(self.scanner.timer.isActive())
            self.assertEqual(len(self.errors), 2)
