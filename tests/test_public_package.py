import copy
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import build_demo
import build_release
import check_release
import configure
import install_skill


class PublicPackageTests(unittest.TestCase):
    def test_private_email_controls_include_unusual_tld_and_json_escapes(self):
        for value in ['person'+'@'+'research.md', 'checkout'+'@'+'private.net',
                      'user'+r'\u0040'+'private.net', 'user'+'%4'+'0'+'private.net']:
            self.assertIn('non_example_email', check_release.scan_text(value))
        self.assertEqual(check_release.scan_text('fixture'+'@'+'example.com'), [])

    def test_home_chat_id_and_secret_positive_controls(self):
        home='/'+'Users'+'/'+'fictional-person/report.json'
        url='https://chatgpt.com/c/'+'12345678'+'-1234-4321-9876-'+'123456789abc'
        token='gh'+'p_'+'aB7xQ9mK2pR5sV8wY1zD4fH6jL0nT3uE7cA9'
        for text, rule in [(home,'private_home_path'),(url,'real_looking_chat_id'),(token,'secret_pattern')]:
            self.assertIn(rule,check_release.scan_text(text))

    def test_language_exception_does_not_exempt_private_data(self):
        label=chr(0x4e2d)
        self.assertIn('non_english_prose',check_release.scan_text(label,'README.md'))
        self.assertNotIn('non_english_prose',check_release.scan_text(label,'scripts/cua_workflow.js'))
        token='sk-'+'q7Vr9Pk3Bm5Nw8Hx2Jc6Df4St0Ya1Le9'
        self.assertIn('secret_pattern',check_release.scan_text(token,'scripts/cua_workflow.js'))

    def test_runtime_paths_and_symlinks_fail_before_publication(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'research_config.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'Unexpected release path'):check_release.source_files(root)
            (root/'research_config.json').unlink();(root/'README.md').symlink_to(ROOT/'README.md')
            with self.assertRaisesRegex(ValueError,'Symlink'):check_release.source_files(root)

    def test_disabled_example_configuration_and_empty_candidates(self):
        config=json.loads((ROOT/'research_config.example.json').read_text())
        self.assertFalse(config['enabled']);self.assertIsNone(config['dataset_root'])
        self.assertFalse(config['email_archive']['enabled'])
        self.assertIsNone(config['email_archive']['recipient'])
        self.assertEqual(json.loads((ROOT/'assets/email-paper-candidates.json').read_text())['candidates'],[])

    def test_installer_refuses_existing_skill_and_excludes_private_config(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);target=root/'skill'
            result=install_skill.install(ROOT,target)
            self.assertTrue(result['installed']);self.assertFalse((target/'research_config.json').exists())
            self.assertTrue((target/'SKILL.md').is_file());self.assertFalse((target/'tests').exists())
            original=(target/'SKILL.md').read_bytes()
            with self.assertRaisesRegex(ValueError,'exists'):install_skill.install(ROOT,target)
            self.assertEqual(original,(target/'SKILL.md').read_bytes())

    def test_configuration_requires_a_private_new_dataset(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);skill=root/'skill';skill.mkdir()
            shutil.copyfile(ROOT/'research_config.example.json',skill/'research_config.example.json')
            with self.assertRaisesRegex(ValueError,'outside'):configure.configure(skill,skill/'data')
            occupied=root/'occupied';occupied.mkdir();(occupied/'keep.txt').write_text('keep')
            with self.assertRaisesRegex(ValueError,'empty'):configure.configure(skill,occupied)
            self.assertEqual((occupied/'keep.txt').read_text(),'keep')
            config=configure.configure(skill,root/'private-data','America/New_York')
            self.assertFalse(config['email']);self.assertFalse(config['obsidian'])
            current=json.loads((skill/'research_config.json').read_text())
            self.assertEqual(current['timezone'],'America/New_York')
            with self.assertRaisesRegex(ValueError,'exists'):configure.configure(skill,root/'another')

    def test_demo_is_synthetic_and_replays_without_new_events_graphs_or_notes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'demo';result=build_demo.build(root)
            self.assertEqual(result['real_saves'],0);self.assertEqual(result['emails_sent'],0)
            self.assertEqual(result['relation_counts'],{'E0':4,'E1':2,'H':3})
            self.assertEqual(set(result['idempotency'].values()),{'PASS'})
            relations=json.loads((root/'knowledge_graph/research_relationships.json').read_text())
            for edge in relations:
                self.assertTrue(all(s['source_type']=='synthetic' for s in edge['properties']['support']))
                if edge['properties']['tier']=='H':
                    self.assertEqual(edge['properties']['validation_status'],'PENDING_VALIDATION')
            with self.assertRaisesRegex(ValueError,'empty'):build_demo.build(root)

    def test_zip_verifier_checks_inventory_hash_and_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            archive=Path(temp)/'source.zip'
            records=[{'path':'README.md','sha256':build_release.sha(b'public')}]
            manifest={'commit':'synthetic','files':records}
            def write(files):
                with zipfile.ZipFile(archive,'w') as z:
                    z.writestr('SOURCE_MANIFEST.json',json.dumps(manifest))
                    for name,value in files:z.writestr(name,value)
            write([('README.md','public')]);self.assertTrue(build_release.verify(archive)['verified'])
            write([('README.md','changed')])
            with self.assertRaisesRegex(ValueError,'hash'):build_release.verify(archive)
            write([('README.md','public'),('extra.txt','extra')])
            with self.assertRaisesRegex(ValueError,'manifest'):build_release.verify(archive)
            write([('../escape','public')])
            with self.assertRaisesRegex(ValueError,'Unsafe'):build_release.verify(archive)

    def test_routing_contract_has_inspect_apply_and_negative_cases(self):
        cases=json.loads((ROOT/'references/ROUTING_CASES.json').read_text())
        self.assertEqual({c['mode'] for c in cases},{None,'inspect','apply'})
        self.assertTrue(any(c['query'].startswith('$chatgpt-conversation-rename') for c in cases))
        self.assertTrue(all(c['expected'] in {None,'chatgpt-conversation-rename'} for c in cases))
        self.assertIn('name: chatgpt-conversation-rename',(ROOT/'SKILL.md').read_text())


if __name__=='__main__': unittest.main()
