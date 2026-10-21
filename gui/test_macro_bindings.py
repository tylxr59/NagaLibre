"""Stored macro names and references remain distinct from authoring drafts."""
import copy
import unittest
from macro_bindings import binding_rows
from test_macro_storage import snapshot
from test_gui_hypershift import paired_state


def bindings_snapshot():
    state = snapshot()
    mapping = paired_state()
    mapping['normal']['buttons'][0].update(category=3, data=[0, 7, 3])
    mapping['hypershift']['controls'][3].update(category=4, data=[0, 8])
    other = copy.deepcopy(mapping)
    other['normal']['slot'] = 2
    other['normal']['buttons'][0].update(category=5, data=[0, 7])
    state['mappings'] = [mapping, other]
    metadata = list(bytes(20) + b'Same name' + bytes(221))
    state['storage'].update(stored_count=2, entries=[
        {'id': identity, 'metadata': metadata, 'data': [1, 5]} for identity in (7, 8)])
    return state


class MacroBindingsTests(unittest.TestCase):
    def test_equal_names_stay_distinct_and_all_slots_layers_and_controls_are_listed(self):
        rows, unknown = binding_rows(bindings_snapshot())
        self.assertEqual(len(rows), 4)
        self.assertEqual({r['id'] for r in rows}, {7, 8})
        self.assertEqual({r['name'] for r in rows}, {'Same name'})
        self.assertEqual({r['slot'] for r in rows}, {1, 2})
        self.assertEqual({r['layer'] for r in rows}, {0, 1})
        self.assertEqual(rows[0]['playback'], 'Repeat 3 times')
        self.assertEqual(rows[1]['playback'], 'While held')
        self.assertEqual(rows[2]['playback'], 'Toggle repeat')
        self.assertEqual(rows[1]['button'], 16)
        self.assertEqual(unknown, 4)  # Captured unknown records in both banks/slots.

    def test_primary_dangling_and_malformed_references_are_not_misrepresented(self):
        state = bindings_snapshot()
        state['mappings'][0]['normal']['primary'][0].update(category=15, data=[0, 9])
        state['mappings'][0]['normal']['buttons'][1].update(category=3, data=[0])
        rows, unknown = binding_rows(state)
        primary = next(r for r in rows if r['primary'])
        self.assertEqual(primary['name'], 'Missing stored macro')
        self.assertEqual(primary['control'], 'Left click')
        self.assertEqual(primary['playback'], 'Sequence')
        self.assertEqual(unknown, 5)
