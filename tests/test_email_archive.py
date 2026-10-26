import base64
import errno
from email.message import EmailMessage
from email import policy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from test_knowledge_graph import kg, j
import test_research_journal as fixture

spec=importlib.util.spec_from_file_location('email_archive',Path(kg.__file__).with_name('email_archive.py'))
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)

class MailArchiveTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name);self.data=self.root/'data';self.state=self.root/'state';self.data.mkdir();j.init(self.data,allow_synthetic=True)
  r=fixture.run_spec('mail-test');r['source_type']='historical_transcript'
  j.ingest(self.data,{'run':r,'events':[fixture.event(annotation_basis='historical_record')],'final_state':'COMPLETE'})
  (self.data/'knowledge_graph').mkdir();(self.data/'knowledge_graph/relationship_registry.json').write_text('{"schema_version":"1.0.0","assertions":[],"domains":[],"conversation_annotations":[]}');kg.build(self.data)
  self.renderer=self.root/'fake-pdf.py';self.renderer.write_text('from pathlib import Path\nimport sys\nPath(sys.argv[2]).write_bytes(b"%PDF-isolated-test-only")\n')
 def tearDown(self):self.t.cleanup()
 def prepare(self):return a.prepare(self.data,self.state,'mail-test','archive@example.com',sys.executable,str(self.root),self.renderer)
 def raw(self,p,change=None):
  m=EmailMessage(policy=policy.SMTP);m['Subject']=p['subject'];m['To']=p['recipient'];m['From']='archive@example.com';m.set_content((Path(p['folder'])/'body.html').read_text(),subtype='html',charset='utf-8')
  for x in p['attachments']:
   content=(Path(p['folder'])/x['filename']).read_bytes()
   if change=='attachment' and x['filename'].endswith('.pdf'):content+=b'bad'
   mt,st=x['mime_type'].split('/');m.add_attachment(content,maintype=mt,subtype=st,filename=x['filename'])
  if change=='recipient':m.replace_header('To','wrong@example.com')
  if change=='subject':m.replace_header('Subject','Different report subject')
  return base64.urlsafe_b64encode(m.as_bytes()).decode()
 def test_prepare_is_immutable_and_replay_does_not_change_research_db(self):
  before=hashlib.sha256((self.data/'research.sqlite3').read_bytes()).hexdigest();p=self.prepare();self.assertTrue(p['prepared_new']);again=self.prepare();self.assertFalse(again['prepared_new']);self.assertEqual(p['delivery_key'],again['delivery_key']);self.assertEqual(before,hashlib.sha256((self.data/'research.sqlite3').read_bytes()).hexdigest())
  with zipfile.ZipFile(Path(p['folder'])/'report-bundle.zip') as z:
   manifest=json.loads(z.read('archive-manifest.json'))
   for f in manifest['files']:self.assertEqual(hashlib.sha256(z.read(f['filename'])).hexdigest(),f['sha256'])
 def test_one_claim_and_one_payload_even_after_reconnection(self):
  p=self.prepare();k=p['delivery_key'];self.assertTrue(a.claim(self.state,k)['dispatch_authorized']);self.assertFalse(a.claim(self.state,k)['dispatch_authorized']);payload=a.payload(self.state,k);self.assertEqual(payload['to'],'archive@example.com');self.assertEqual(len(payload['payload']['parts']),3)
  with self.assertRaisesRegex(ValueError,'already issued'):a.payload(self.state,k)
  self.assertFalse(a.claim(self.state,k)['dispatch_authorized'])
 def test_raw_mime_checks_exact_body_recipient_and_attachment_bytes(self):
  p=self.prepare();k=p['delivery_key'];a.claim(self.state,k);a.payload(self.state,k);a.receipt(self.state,k,'msg123');r=a.verify_raw(self.state,k,'msg123',self.raw(p));self.assertTrue(r['body_matches']);self.assertEqual(a.status(self.state,k)['state'],'VERIFIED');self.assertFalse(a.claim(self.state,k)['dispatch_authorized'])
 def test_corrupt_or_misaddressed_readback_never_reports_verified(self):
  p=self.prepare();k=p['delivery_key'];a.claim(self.state,k);a.payload(self.state,k)
  for bad in ['attachment','recipient','subject']:
   with self.subTest(bad=bad),self.assertRaises(ValueError):a.verify_raw(self.state,k,'msg123',self.raw(p,bad))
  self.assertEqual(a.status(self.state,k)['state'],'DISPATCH_STARTED');self.assertFalse(a.claim(self.state,k)['dispatch_authorized'])
 def test_tampered_package_and_stale_graph_block_before_send_intent(self):
  p=self.prepare();(Path(p['folder'])/'report.pdf').write_bytes(b'%PDF-tampered')
  with self.assertRaisesRegex(ValueError,'changed'):a.claim(self.state,p['delivery_key'])
  self.assertEqual(a.status(self.state,p['delivery_key'])['state'],'PREPARED')
 def test_unfinalized_or_synthetic_run_cannot_be_mailed(self):
  r=fixture.run_spec('unfinalized');j.start_run(self.data,r)
  with self.assertRaisesRegex(ValueError,'finalized'):a.prepare(self.data,self.state,'unfinalized','archive@example.com')
  j.ingest(self.data,{'run':fixture.run_spec('synthetic'),'events':[fixture.event()],'final_state':'COMPLETE'})
  with self.assertRaisesRegex(ValueError,'Synthetic'):a.prepare(self.data,self.state,'synthetic','archive@example.com')
 def test_message_id_conflict_does_not_authorize_resend(self):
  p=self.prepare();k=p['delivery_key'];a.claim(self.state,k);a.payload(self.state,k);a.receipt(self.state,k,'first')
  with self.assertRaisesRegex(ValueError,'Different message'):a.receipt(self.state,k,'second')
  self.assertFalse(a.claim(self.state,k)['dispatch_authorized'])
 def test_stale_source_requires_new_export(self):
  j.record_event(self.data,'mail-test',fixture.event(stage='CORRECTION',supersedes_event_id=j.resume_run(self.data,'mail-test')['targets'][0]['latest_event_id'],annotation_basis='historical_record',rationale='new metadata correction'))
  j.finish_run(self.data,'mail-test','COMPLETE')
  with self.assertRaisesRegex(ValueError,'Stale graph'):self.prepare()
 def test_repair_can_retire_only_an_unsent_unclaimed_preparation(self):
  p=self.prepare();k=p['delivery_key'];r=a.retire_prepared(self.state,k,'synthetic PDF repair');self.assertTrue(Path(r['retired_folder']).exists());p2=self.prepare();a.claim(self.state,k)
  with self.assertRaisesRegex(ValueError,'unclaimed'):a.retire_prepared(self.state,k,'must not reset a possible send')
  self.assertFalse(a.claim(self.state,k)['dispatch_authorized'])
 def test_canceled_cloud_read_retries_identical_source_without_fallback(self):
  with patch.object(Path,'read_bytes',side_effect=[OSError(errno.ECANCELED,'synthetic hydration cancel'),b'expected source']) as reader:
   self.assertEqual(a.read_source('/synthetic/source'),b'expected source');self.assertEqual(reader.call_count,2)
  with patch.object(Path,'read_bytes',side_effect=OSError(errno.ECANCELED,'still canceled')) as reader:
   with self.assertRaises(OSError):a.read_source('/synthetic/source')
   self.assertEqual(reader.call_count,3)
 def test_explicit_sample_has_stable_separate_dedup_scope_and_keeps_daily_immutable(self):
  daily=self.prepare();k=daily['delivery_key'];before=(Path(daily['folder'])/'body.html').read_bytes()
  p=a.prepare(self.data,self.state,'mail-test','archive@example.com',sys.executable,str(self.root),self.renderer,sample_id='body-v2')
  self.assertNotEqual(p['delivery_key'],k);self.assertIn('samples/body-v2',p['state_root'])
  self.assertIn('Preview',p['subject']);self.assertEqual(a.status(self.state,k)['state'],'PREPARED')
  self.assertEqual(before,(Path(daily['folder'])/'body.html').read_bytes())
  again=a.prepare(self.data,self.state,'mail-test','archive@example.com',sample_id='body-v2')
  self.assertFalse(again['prepared_new']);self.assertTrue(a.claim(p['state_root'],p['delivery_key'])['dispatch_authorized']);a.payload(p['state_root'],p['delivery_key'])
  self.assertFalse(a.claim(p['state_root'],p['delivery_key'])['dispatch_authorized'])
  with zipfile.ZipFile(Path(p['folder'])/'report-bundle.zip') as z:
   self.assertIn('mail-brief.json',z.namelist());brief=json.loads(z.read('mail-brief.json'));self.assertEqual(brief['body_version'],'2.0.0')
  with self.assertRaises(ValueError):a.key_for('mail-test','archive@example.com','../escape')

 def test_load_recovery_keeps_original_ten_blocked_event_graph_tiers_and_sent_archive(self):
  # An isolated historical-metadata fixture, fake PDF and fake MIME delivery;
  # neither an authenticated browser nor Gmail is connected by this test.
  for mail_state in ('DISPATCH_STARTED','VERIFIED'):
   with self.subTest(mail_state=mail_state):
    rid='load-recovery-'+mail_state.lower().replace('_','-');recipient='archive@example.com'
    run=fixture.run_spec(rid);run['source_type']='historical_transcript'
    run['requested_count']=10
    run['targets']=[{'conversation_url':f'https://chatgpt.com/c/{rid}-{i}',
                     'original_title':f'Synthetic project{i} | Usage guide','position':i+1} for i in range(10)]
    entries=[]
    for i,target in enumerate(run['targets']):
     common=dict(conversation_url=target['conversation_url'],annotation_basis='historical_record')
     if i==6:
      value=fixture.event('BLOCKED',**common,decision='undetermined',proposed_title=None,
                          displayed_title=None,save_attempted=False,verification={},
                          reason_codes=['BODY_NOT_READY'],context_level='not_ready',topic_labels=[])
     else:
      value=fixture.event('ALREADY CORRECT',**common,decision='keep',save_attempted=False,
                          proposed_title=target['original_title'],displayed_title=target['original_title'],
                          topic_labels=['Shared synthetic topic'] if i<2 else [f'Synthetic topic{i}'])
     entries.append(value)
    j.ingest(self.data,{'run':run,'events':entries,'final_state':'PARTIAL'})
    partial=j.resume_run(self.data,rid);old_id=partial['targets'][6]['latest_event_id']
    with j.connect(self.data,readonly=True) as db:
     old_payload=db.execute('SELECT payload_json FROM events WHERE event_id=?',(old_id,)).fetchone()[0]
    graph,_=kg.derive(kg.snapshot(self.data))
    runs={n['label']:n['properties'] for n in graph['nodes'] if n['type']=='Run'}
    urls={run['targets'][i]['conversation_url'] for i in (0,1)}
    support=[kg.relation_engine().support_record(n,runs) for n in graph['nodes']
             if n['type']=='Observation' and n['properties']['conversation_url'] in urls]
    registry={'schema_version':'1.0.0','assertions':[]}
    for tier,relation in [('H','CANDIDATE_COMPARISON'),('E1','METADATA_SUBJECT_OVERLAP')]:
     registry['assertions'].append({'id':rid+'-'+tier,'source_url':run['targets'][0]['conversation_url'],
      'target_url':run['targets'][1]['conversation_url'],'tier':tier,'relation':relation,
      'label':'Synthetic recovery relation','evidence':'Temporary synthetic metadata test','validation_needed':'Full text and counterexamples',
      'validation_status':'PENDING_VALIDATION' if tier=='H' else 'METADATA_COMPATIBILITY_ONLY',
      'support':support,'source_documents':[{'path':'synthetic-only','sha256':'a'*64}]})
    g=self.data/'knowledge_graph';(g/'relationship_registry.json').write_text(json.dumps(registry))
    (g/'config.json').write_text('{"enabled":true}')
    j.export(self.data)
    relations=json.loads((g/'research_relationships.json').read_text())
    registry_hash=hashlib.sha256((g/'relationship_registry.json').read_bytes()).hexdigest()
    package=a.prepare(self.data,self.state,rid,recipient,sys.executable,str(self.root),self.renderer)
    key=package['delivery_key'];self.assertTrue(a.claim(self.state,key)['dispatch_authorized'])
    a.payload(self.state,key)  # one simulated dispatch; no mail transport
    if mail_state=='VERIFIED':
     a.receipt(self.state,key,'fake-recovery-message')
     a.verify_raw(self.state,key,'fake-recovery-message',self.raw(package))
    archived={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(package['folder']).iterdir() if p.is_file()}
    delivery=a.status(self.state,key);reopened=j.reopen_run(self.data,rid)
    self.assertEqual(reopened['targets'],partial['targets'])
    target=run['targets'][6]
    correction=fixture.event('ALREADY CORRECT',conversation_url=target['conversation_url'],
       decision='keep',save_attempted=False,proposed_title=target['original_title'],
       displayed_title=target['original_title'],annotation_basis='historical_record',
       topic_labels=['Synthetic device instructions'],stage='CORRECTION',supersedes_event_id=old_id)
    self.assertTrue(j.record_event(self.data,rid,correction)['inserted'])
    self.assertTrue(j.finish_run(self.data,rid,'COMPLETE')['finalized'])
    db_hash=hashlib.sha256((self.data/'research.sqlite3').read_bytes()).hexdigest()
    self.assertFalse(j.record_event(self.data,rid,correction)['inserted'])
    self.assertFalse(j.finish_run(self.data,rid,'COMPLETE')['finalized'])
    complete=j.resume_run(self.data,rid)
    self.assertEqual(complete['state'],'COMPLETE');self.assertEqual(len(complete['targets']),10)
    for i,item in enumerate(complete['targets']):
     self.assertEqual(item['action'],'SKIP_VERIFIED')
     if i!=6:self.assertEqual(item['latest_event_id'],partial['targets'][i]['latest_event_id'])
    with j.connect(self.data,readonly=True) as db:
     self.assertEqual(db.execute('SELECT payload_json FROM events WHERE event_id=?',(old_id,)).fetchone()[0],old_payload)
     self.assertEqual(db.execute('SELECT count(*) FROM events WHERE run_id=?',(rid,)).fetchone()[0],11)
     self.assertEqual(db.execute('SELECT count(*) FROM save_intents').fetchone()[0],0)
    updated=j.export(self.data)['knowledge_graph'];history=(g/'updates.jsonl').read_bytes()
    self.assertEqual(updated,j.export(self.data)['knowledge_graph'])
    self.assertEqual(history,(g/'updates.jsonl').read_bytes())
    after={edge['id']:edge for edge in json.loads((g/'research_relationships.json').read_text())}
    for edge in relations:
     updated_edge=after[edge['id']]
     self.assertEqual(edge['properties']['tier'],updated_edge['properties']['tier'])
     self.assertEqual(edge['properties']['validation_status'],updated_edge['properties']['validation_status'])
     if edge['properties']['tier'] in {'E1','H'}:
      self.assertEqual(edge['properties']['support'],updated_edge['properties']['support'])
      # A changed source fingerprint is quarantined, never silently rebound.
      if not updated_edge['properties']['active']:
       self.assertIn('SOURCE_CORRECTED',updated_edge['properties']['stale_reasons'])
    self.assertEqual(registry_hash,hashlib.sha256((g/'relationship_registry.json').read_bytes()).hexdigest())
    self.assertEqual(db_hash,hashlib.sha256((self.data/'research.sqlite3').read_bytes()).hexdigest())
    # A correction must not regenerate the earlier PARTIAL body or grant another send.
    again=a.prepare(self.data,self.state,rid,recipient)
    self.assertFalse(again['prepared_new']);self.assertEqual(again['delivery_key'],key)
    self.assertFalse(a.claim(self.state,key)['dispatch_authorized'])
    with self.assertRaisesRegex(ValueError,'already issued'):a.payload(self.state,key)
    self.assertEqual(delivery,a.status(self.state,key))
    self.assertEqual(archived,{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(package['folder']).iterdir() if p.is_file()})

if __name__=='__main__':unittest.main()
