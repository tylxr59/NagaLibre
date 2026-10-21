"""Versioned local macro catalog. No hardware or helper access."""
import copy
import fcntl
import json
import os
from pathlib import Path
import uuid

from model import save_profile, key_code


def validate_macro(name, steps):
    if not isinstance(name, str) or not name.strip() or len(name.encode('utf-8')) > 100 or '\0' in name:
        raise ValueError('Name must contain 1–100 UTF-8 bytes without NUL.')
    if not isinstance(steps, list) or not steps:
        raise ValueError('Add at least one macro action.')
    for step in steps:
        if not isinstance(step, dict) or len(step) != 1:
            raise ValueError('Invalid macro action.')
        kind, value = next(iter(step.items()))
        if kind == 'wait_ms':
            if type(value) is not int or not 0 <= value <= 60000:
                raise ValueError('Delays must be between 0 and 60000 ms.')
        elif kind == 'chord':
            if not isinstance(value, list) or not value or len(set(value)) != len(value):
                raise ValueError('Invalid shortcut.')
            for key in value:
                if not isinstance(key, str) or key_code(key) != key:
                    raise ValueError('Invalid key.')
        elif kind in ('tap', 'down', 'up'):
            if not isinstance(value, str) or key_code(value) != value:
                raise ValueError('Invalid key.')
        else:
            raise ValueError('Unknown macro action.')


class MacroLibrary:
    def __init__(self, path):
        self.path = Path(path)
        self.original = self._read()
        self.data = json.loads(self.original) if self.original is not None else {'version': 1, 'macros': []}
        if not isinstance(self.data, dict) or self.data.get('version') != 1 or not isinstance(self.data.get('macros'), list):
            raise ValueError('Unsupported macro library. The file was left untouched.')
        seen = set()
        for entry in self.entries:
            if not isinstance(entry, dict) or not isinstance(entry.get('id'), str) or entry['id'] in seen:
                raise ValueError('Invalid macro library identity.')
            seen.add(entry['id'])
            validate_macro(entry.get('name'), entry.get('steps'))
            if not isinstance(entry.get('folder', ''), str):
                raise ValueError('Invalid macro folder.')

    def _read(self):
        try:
            return self.path.read_bytes()
        except FileNotFoundError:
            return None

    @property
    def entries(self):
        return copy.deepcopy(self.data['macros'])

    def put(self, name, steps, folder='', identity=None):
        validate_macro(name, steps)
        entry = {'id': identity or str(uuid.uuid4()), 'name': name, 'steps': copy.deepcopy(steps), 'folder': folder.strip()}
        updated = copy.deepcopy(self.data)
        updated['macros'] = [item for item in updated['macros'] if item['id'] != entry['id']] + [entry]
        self._write(updated)
        return entry['id']

    def remove(self, identity):
        updated = copy.deepcopy(self.data)
        updated['macros'] = [item for item in updated['macros'] if item['id'] != identity]
        self._write(updated)

    def _write(self, updated):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Serialize writers and reject a stale editor instead of losing another window's work.
        descriptor = os.open(str(self.path) + '.lock', os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(descriptor, 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if self._read() != self.original:
                raise ValueError('The macro library changed in another window. Reopen the library before saving.')
            save_profile(self.path, updated)
            directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            self.original = self._read()
            self.data = updated
