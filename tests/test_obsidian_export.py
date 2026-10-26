# -*- coding: utf-8 -*-
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import obsidian_export as oe
import test_research_journal as fixture
import test_knowledge_graph as graph_fixture


class ObsidianTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'data'
        self.vault = self.root / 'vault'
        fixture.j.init(self.root, allow_synthetic=True)
        fixture.j.ingest(self.root, {'run': fixture.run_spec(), 'events': [fixture.event()], 'final_state': 'COMPLETE'})
        graph_fixture.kg.build(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def files(self):
        return {str(p.relative_to(self.vault)): p.read_bytes() for p in self.vault.rglob('*') if p.is_file()}

    def note(self):
        return next((self.vault / '10_Conversations').glob('*.md'))

    def test_initial_export_and_exact_retry_keep_bytes_and_manual_tail(self):
        first = oe.sync(self.root, self.vault, True)
        note = self.note()
        note.write_text(note.read_text(encoding='utf-8') + 'my independent research\n', encoding='utf-8')
        before = self.files()
        second = oe.sync(self.root, self.vault)
        self.assertEqual((second['created'], second['updated']), (0, 0))
        self.assertEqual(first['notes'], second['unchanged'])
        self.assertEqual(before, self.files())

    def test_managed_edit_blocks_entire_sync_without_overwriting_manual_work(self):
        oe.sync(self.root, self.vault, True)
        note = self.note()
        note.write_text(note.read_text(encoding='utf-8').replace('kg_kind:', 'my_kg_kind:', 1), encoding='utf-8')
        before = self.files()
        with self.assertRaisesRegex(ValueError, 'Managed note edited'):
            oe.sync(self.root, self.vault)
        self.assertEqual(before, self.files())

    def test_same_title_new_url_remains_distinct_and_existing_manual_text_survives(self):
        oe.sync(self.root, self.vault, True)
        old = self.note()
        old.write_text(old.read_text(encoding='utf-8') + 'keep me\n', encoding='utf-8')
        run = fixture.run_spec('later', '2025-01-03')
        other_url = 'https://chatgpt.com/c/synthetic-b'
        run['targets'][0]['conversation_url'] = other_url
        fixture.j.ingest(self.root, {'run': run, 'events': [fixture.event(conversation_url=other_url)], 'final_state': 'COMPLETE'})
        graph_fixture.kg.build(self.root)
        result = oe.sync(self.root, self.vault)
        self.assertEqual(len(list((self.vault / '10_Conversations').glob('*.md'))), 2)
        self.assertIn('keep me', old.read_text(encoding='utf-8'))
        self.assertGreater(result['created'], 0)

    def test_renamed_managed_note_does_not_create_a_duplicate(self):
        oe.sync(self.root, self.vault, True)
        note = self.note()
        note.rename(note.with_name('my-renamed-note.md'))
        before = self.files()
        with self.assertRaisesRegex(ValueError, 'missing or renamed'):
            oe.sync(self.root, self.vault)
        self.assertEqual(before, self.files())

    def test_uncommitted_source_and_unmanaged_collision_are_rejected(self):
        oe.sync(self.root, self.vault, True)
        before = self.files()
        source = self.root / 'knowledge_graph/graph.json'
        source.write_text(source.read_text(encoding='utf-8') + ' ', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Uncommitted graph file'):
            oe.sync(self.root, self.vault)
        self.assertEqual(before, self.files())
        graph_fixture.kg.build(self.root)
        (self.vault / '.kg-sync.json').unlink()
        before = self.files()
        with self.assertRaisesRegex(ValueError, 'Unmanaged note collision'):
            oe.sync(self.root, self.vault)
        self.assertEqual(before, self.files())

    def test_hypothesis_tier_and_inactive_history_are_never_promoted(self):
        graph, _ = graph_fixture.kg.derive(graph_fixture.kg.snapshot(self.root))
        first = next(n for n in graph['nodes'] if n['type'] == 'Conversation')
        second = copy.deepcopy(first); second['id'] += '-other'; second['properties']['url'] = 'https://chatgpt.com/c/other'
        graph['nodes'].append(second)
        edge = {'id': 'edge:test', 'source': first['id'], 'target': second['id'], 'relation': 'CANDIDATE_METHOD', 'properties': {
            'tier': 'H', 'layer': 'cross_topic', 'active': True, 'validation_status': 'PENDING_VALIDATION', 'label': 'candidate',
            'evidence': 'metadata only', 'validation_needed': 'read the underlying sources', 'support': [], 'stale_reasons': []}}
        manifest = {'update_id': 'test', 'terminal_observations': 1, 'excluded_pending_targets': 0, 'research_relation_counts': {'E0': 0, 'E1': 0, 'H': 1}}
        notes = oe.render(graph, [edge], manifest, {})
        self.assertIn('PENDING_VALIDATION', notes[edge['id']]['prefix'])
        edge['properties']['validation_status'] = 'CONFIRMED'
        with self.assertRaisesRegex(ValueError, 'promoted'):
            oe.render(graph, [edge], manifest, {})
        edge['properties'].update(active=False, validation_status='PENDING_VALIDATION', stale_reasons=['SOURCE_CORRECTED'])
        manifest['research_relation_counts']['H'] = 0
        notes = oe.render(graph, [edge], manifest, {})
        self.assertTrue(notes[edge['id']]['path'].startswith('90_Historical_Relations'))
        self.assertNotIn('[[', notes[edge['id']]['prefix'])
        self.assertIn('SOURCE_CORRECTED', notes[edge['id']]['prefix'])

    def test_daily_export_hook_is_read_only_and_uses_committed_graph(self):
        oe.sync(self.root, self.vault, True)
        settings = self.root / 'knowledge_graph/config.json'
        settings.write_text(json.dumps({'enabled': True, 'obsidian': {'enabled': True, 'vault_root': str(self.vault)}}), encoding='utf-8')
        before = (self.root / 'research.sqlite3').read_bytes()
        result = fixture.j.export(self.root)
        self.assertEqual(result['obsidian']['updated'], 0)
        self.assertEqual(before, (self.root / 'research.sqlite3').read_bytes())
        self.assertEqual(result['obsidian']['update_id'], result['knowledge_graph']['update_id'])


if __name__ == '__main__':
    unittest.main()
