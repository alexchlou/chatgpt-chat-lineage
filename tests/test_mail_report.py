import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('mail_report', Path(__file__).resolve().parents[1]/'scripts/mail_report.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def edge(i, tier='H', active=True, layer='cross_topic'):
    return {'id': i, 'source': 'c1', 'target': 'c2', 'properties': {
        'layer': layer, 'tier': tier, 'active': active, 'label': '<unsafe>',
        'evidence': 'only metadata', 'validation_needed': 'full text', 'support': []}}


class MailReportTests(unittest.TestCase):
    def test_timezone_is_configurable_and_utc_is_the_default(self):
        stamp='2025-01-01T23:30:00Z'
        self.assertEqual(m.local_date(stamp),'2025-01-01')
        self.assertEqual(m.local_date(stamp,'Asia/Tokyo'),'2025-01-02')
        self.assertEqual(m.local_date(stamp,'America/New_York'),'2025-01-01')

    def test_calendar_delta_excludes_baseline_reexports_and_reintroduced_edges(self):
        relations = [edge('old'), edge('new', 'E1'), edge('inactive', active=False), edge('domain', layer='domain_coding')]
        updates = [dict(update_id='base', exported_at='2025-01-01T15:59:59Z', added=['old']),
                   dict(update_id='u1', exported_at='2025-01-01T16:00:00Z', added=['new','inactive','domain']),
                   dict(update_id='u2', exported_at='2025-01-02T02:00:00Z', added=['old','new']),
                   dict(update_id='u3', exported_at='2025-01-02T03:00:00Z', added=[])]
        d = m.daily_delta(updates, relations, '2025-01-02', 'u3', timezone='Asia/Shanghai')
        self.assertEqual([e['id'] for e in d['added']], ['new'])
        self.assertEqual(d['added_counts'], {'E1': 1})
        self.assertEqual(d['baseline_cross_topic_count'], 0)
        updates[0]['exported_at'] = '2025-01-02T00:00:00Z'
        self.assertEqual(m.daily_delta(updates, relations, '2025-01-02', 'u3', timezone='Asia/Shanghai')['baseline_cross_topic_count'], 1)

    def test_missing_time_is_unknown_not_today_and_wrong_update_blocks(self):
        u = [dict(update_id='base', added=[]), dict(update_id='last', added=['x'], exported_at='2025-01-02T12:00:00')]
        d = m.daily_delta(u, [edge('x')], '2025-01-02', 'last')
        self.assertEqual(d['added'], []); self.assertEqual(d['missing_export_times'], 2)
        with self.assertRaises(ValueError): m.daily_delta(u, [], '2025-01-02', 'wrong')

    def test_paper_candidates_never_inherit_e1_and_changed_fingerprint_quarantines(self):
        nodes = [{'id': 'o1', 'properties': {'conversation_url': 'https://chatgpt.com/c/abc'}},
                 {'id': 'o2', 'properties': {'conversation_url': 'https://chatgpt.com/c/def'}},
                 {'id': 'c1', 'properties': {'url': 'https://chatgpt.com/c/abc'}},
                 {'id': 'c2', 'properties': {'url': 'https://chatgpt.com/c/def'}}]
        c = {'id': 'P1', 'support_observation_ids': ['o1','o2'],
             'support_fingerprints': {n['id']: m.digest(n['properties']) for n in nodes[:2]}, 'tier': 'E1'}
        result = m.candidate_brief({'candidates': [c]}, {'nodes': nodes}, [edge('e1','E1')], ['https://chatgpt.com/c/abc'])
        self.assertEqual(result['candidates'][0]['tier'], 'H')
        self.assertEqual(result['candidates'][0]['relation_evidence'][0]['tier'], 'E1')
        nodes[0]['properties']['corrected'] = True
        result = m.candidate_brief({'candidates': [c]}, {'nodes': nodes}, [], [])
        self.assertEqual(result['stale_ids'], ['P1']); self.assertEqual(result['candidates'], [])

    def summary(self):
        return {'run_id': 'sample', 'event_date': '2025-01-02', 'graph_update_id': 'last',
                'run_state': 'PARTIAL', 'source_type': 'historical_artifact', 'requested_count': 10,
                'frozen_count': 1, 'research_relation_counts': {'H': 1}, 'stale_research_relations': 1,
                'status_counts': {'BLOCKED': 1}, 'targets': [{'position': 1,
                    'conversation_url': 'javascript:alert(1)', 'original_title': '<script>alert(1)</script>',
                    'proposed_title': 'Proposed', 'displayed_title': None, 'status': 'BLOCKED', 'rationale': 'account unclear'}]}

    def test_incomplete_denominators_and_unknown_titles_are_not_success(self):
        s = self.summary(); b = m.build_brief(s, {'nodes': []}, [], [{'update_id':'last','exported_at':'2025-01-02T00:00:00Z'}], {})
        self.assertTrue(any('Requested 10' in x for x in b['issues']))
        self.assertTrue(any('BLOCKED' in x for x in b['issues']))
        body = m.render(s, b, {'nodes': []}, 'key', sample=True)
        for value in ['Naming results', 'Graph additions', 'Integrative paper', 'Anomalies', 'report-bundle.zip', 'Observed title unknown', 'Preview validation']:
            self.assertIn(value, body)
        self.assertNotIn('<script>', body); self.assertNotIn('href="javascript:', body)
        self.assertIn('&lt;script&gt;', body)

    def test_success_with_missing_verification_is_flagged(self):
        s = self.summary(); s['targets'][0]['status'] = 'RENAMED'; s['targets'][0]['displayed_title'] = 'title'
        b = m.build_brief(s, {'nodes': []}, [], [{'update_id':'last'}], {})
        self.assertTrue(any('incomplete verification fields' in x for x in b['issues']))

    def test_relation_title_uses_pinned_support_without_ordering_ambiguous_same_day(self):
        n = {'label': 'Multiple same-day titles', 'properties': {'url': 'https://chatgpt.com/c/abc'}}
        s = [{'conversation_url': 'https://chatgpt.com/c/abc', 'displayed_title': 'Source title'}]
        text = m.endpoint_link(n, s)
        self.assertIn('Source title (title at source observation)', text)
        self.assertNotIn('Multiple same-day', text)
        self.assertEqual(len(s), 1)


if __name__ == '__main__': unittest.main()
