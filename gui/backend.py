"""Qt process bridge. The root helper's stdin pipe owns its lifetime."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal


def backend_path() -> Path:
    override = os.environ.get("NAGALIBRE_BACKEND")
    if override:
        return Path(override).expanduser().resolve()
    root = Path(__file__).resolve().parent.parent
    return root / "target/release/naga-macros"


class Backend(QObject):
    event = Signal(dict)
    log = Signal(str)
    connected = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self.process.readyReadStandardOutput.connect(self.read_stdout)
        self.process.readyReadStandardError.connect(lambda: self.log.emit(bytes(self.process.readAllStandardError()).decode(errors="replace")))
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(self.process_error)
        self.buffer = b""
        self.ready = False
        self.protocol = 0
        self.device = None

    def start(self):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            if self.ready:
                self.send({"command": "monitor"})
            return
        path = backend_path()
        if not path.is_file():
            raise ValueError(f"Input engine missing: {path}. Run cargo build --release --locked from the NagaLibre checkout.")
        self.buffer = b""
        environment = QProcessEnvironment.systemEnvironment()
        # Keep inherited private library paths out of the elevated helper.
        original = environment.value("LD_LIBRARY_PATH_ORIG")
        if original:
            environment.insert("LD_LIBRARY_PATH", original)
        else:
            environment.remove("LD_LIBRARY_PATH")
        self.process.setProcessEnvironment(environment)
        if os.environ.get("NAGALIBRE_NO_PKEXEC") == "1" or os.geteuid() == 0:
            self.process.start(str(path), ["session"])
        else:
            pkexec = shutil.which("pkexec")
            if not pkexec:
                raise ValueError("Install polkit (pkexec) to request mouse access, or configure device permissions and launch with NAGALIBRE_NO_PKEXEC=1.")
            self.process.start(pkexec, ["--disable-internal-agent", str(path), "session"])

    def send(self, message: dict):
        if self.ready:
            self.process.write((json.dumps(message) + "\n").encode())

    def read_stdout(self):
        self.buffer += bytes(self.process.readAllStandardOutput())
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            try:
                message = json.loads(line)
            except (ValueError, UnicodeError):
                self.log.emit("Invalid input-helper response.")
                continue
            if message.get("type") == "hello":
                if message.get("protocol") not in (1, 2, 3):
                    self.log.emit("Input engine version is incompatible. Update both app and engine.")
                    self.process.closeWriteChannel()
                    continue
                self.protocol = message["protocol"]
                self.device = message.get("device")
                self.ready = True
                self.connected.emit(True)
            self.event.emit(message)

    def finished(self, *args):
        self.ready = False
        self.connected.emit(False)

    def process_error(self, error):
        self.log.emit(f"Input helper: {self.process.errorString()}")
        if error == QProcess.ProcessError.FailedToStart:
            self.finished()

    def shutdown(self):
        if self.process.state() == QProcess.ProcessState.NotRunning:
            return
        self.send({"command": "shutdown"})
        self.process.closeWriteChannel()
        # EOF works across the privilege boundary, unlike sending SIGTERM as a user.
        self.process.waitForFinished(3000)
