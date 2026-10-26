#!/usr/bin/env python3
"""Prepare immutable report mail, guard one dispatch, and verify Gmail raw bytes.
No Gmail/network calls, credential access or research-journal writes occur here.
"""
import argparse
import base64
import csv
import errno
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
import zipfile

SCHEMA = '1.1.0'
DDL = '''CREATE TABLE IF NOT EXISTS deliveries (
 delivery_key TEXT PRIMARY KEY,run_id TEXT NOT NULL,recipient TEXT NOT NULL,
 state TEXT NOT NULL,package_json TEXT NOT NULL,claimed_at TEXT,message_id TEXT,
 verification_json TEXT,UNIQUE(run_id,recipient));'''
DDL += '''CREATE TABLE IF NOT EXISTS prepared_history (
 revision_id TEXT PRIMARY KEY,delivery_key TEXT NOT NULL,retired_at TEXT NOT NULL,
 reason TEXT NOT NULL,retired_folder TEXT NOT NULL,package_json TEXT NOT NULL);'''


def require(ok, message):
    if not ok:
        raise ValueError(message)


def dump(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_source(path):
    # iCloud may cancel a hydration read. Retry the same bytes; never substitute
    # a previous report or weaken the manifest/snapshot checks.
    for attempt in range(3):
        try:
            return Path(path).read_bytes()
        except OSError as error:
            if error.errno not in {errno.ECANCELED,errno.ETIMEDOUT,errno.EAGAIN,errno.EBUSY} or attempt==2:
                raise
            time.sleep(.2)


def research_snapshot(dataset, state_root, kg):
    """Read a stable classic-journal image off iCloud before SQLite page reads."""
    database=Path(dataset)/'research.sqlite3'
    for suffix in ('-wal','-journal'):
        sidecar=Path(str(database)+suffix)
        require(not sidecar.exists() or sidecar.stat().st_size==0,
                'Research database has an active journal; wait for its writer before archival')
    image=read_source(database)
    require(len(image)>100 and image.startswith(b'SQLite format 3\x00') and image[18:20]==b'\x01\x01',
            'Stable classic-journal research database required')
    with tempfile.TemporaryDirectory(prefix='.source-copy-',dir=state_root) as tmp:
        local=Path(tmp)/'research.sqlite3';local.write_bytes(image)
        with sqlite3.connect(local.as_uri()+'?mode=ro',uri=True) as db:
            require(db.execute('PRAGMA integrity_check').fetchone()[0]=='ok','Research copy integrity failed')
        source=kg.snapshot(Path(tmp))
        require(sha(image)==sha(read_source(database)), 'Research database changed during archival read')
    return source


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.mail-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def connect(state_root):
    root = Path(state_root).resolve(); root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(root / 'deliveries.sqlite3'), timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA synchronous=FULL'); db.executescript(DDL)
    return db


def key_for(run_id, recipient, sample_id=None):
    require(bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,119}', run_id)), 'Unsafe run_id')
    require(bool(re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', recipient)), 'Exact recipient email required')
    identity = run_id + '\n' + recipient
    if sample_id is not None:
        require(bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}', sample_id)), 'Unsafe sample_id')
        identity += '\nsample:' + sample_id
    return 'CGRENAME-' + sha(identity.encode())[:24]


def package_files(package):
    folder = Path(package['folder'])
    for a in package['attachments']:
        path = folder / a['filename']
        require(path.name == a['filename'] and sha(path.read_bytes()) == a['sha256'], 'Archived attachment changed')
    require(sha((folder / 'body.html').read_bytes()) == package['body_sha256'], 'Archived email body changed')


def info(state_root, delivery_key):
    with connect(state_root) as db:
        row = db.execute('SELECT * FROM deliveries WHERE delivery_key=?', (delivery_key,)).fetchone()
    require(row is not None, 'Unknown delivery key')
    return dict(row)


def status(state_root, delivery_key):
    r = info(state_root, delivery_key)
    return {k:r[k] for k in ('delivery_key','run_id','recipient','state','claimed_at','message_id')}


def prepare(dataset_root, state_root, run_id, recipient, node=None, node_modules=None, pdf_renderer=None, sample_id=None):
    delivery_key = key_for(run_id, recipient, sample_id)
    root, dataset = Path(state_root).resolve(), Path(dataset_root).resolve()
    if sample_id is not None:
        root = root / 'samples' / sample_id
    with connect(root) as db:
        db.execute('BEGIN IMMEDIATE')
        existing = db.execute('SELECT package_json FROM deliveries WHERE delivery_key=?', (delivery_key,)).fetchone()
        if existing:
            package = json.loads(existing[0]); package_files(package)
            return dict(package, prepared_new=False)
        gspec = importlib.util.spec_from_file_location('rename_mail_graph', Path(__file__).with_name('knowledge_graph.py'))
        kg = importlib.util.module_from_spec(gspec); gspec.loader.exec_module(kg)
        source = research_snapshot(dataset, root, kg)
        row = next((r for r in source['runs'] if r['run_id'] == run_id), None)
        require(row is not None and row['state'] in {'COMPLETE','PARTIAL','INTERRUPTED'}, 'Archive a finalized existing run only')
        run = json.loads(row['metadata_json'])
        require(run['source_type'] != 'synthetic', 'Synthetic runs cannot enter the real mail archive')
        out = dataset / 'knowledge_graph'
        manifest_bytes = read_source(out / 'manifest.json'); manifest = json.loads(manifest_bytes)
        for f in manifest['files']:
            relative = Path(f['path'])
            require(not relative.is_absolute() and '..' not in relative.parts, 'Invalid graph manifest path')
            require(sha(read_source(out / relative)) == f['sha256'], 'Graph manifest mismatch; export before mailing')
        registry = json.loads(read_source(out / 'relationship_registry.json'))
        graph, view = kg.derive(source, registry)
        require(graph['metadata']['source_snapshot_sha256'] == manifest['source_snapshot_sha256'], 'Stale graph; export before mailing')
        require(graph['metadata']['relationship_registry_sha256'] == manifest['relationship_registry_sha256'], 'Registry changed; export before mailing')
        require(sha(manifest_bytes) == sha(read_source(out / 'manifest.json')), 'Graph changed during mail preparation')
        targets = []
        for r in sorted((r for r in source['outcomes'] if r['run_id'] == run_id), key=lambda r:r['position']):
            payload = json.loads(r['payload_json']) if r['payload_json'] else {}
            targets.append({'position':r['position'],'conversation_url':r['conversation_url'],
                            'original_title':r['original_title'],'proposed_title':payload.get('proposed_title'),
                            'displayed_title':payload.get('displayed_title'),'status':r['status'],
                            'verification':payload.get('verification'), 'result_event_id':r.get('event_id'),
                            'rationale':payload.get('rationale')})
        counts = dict(sorted(__import__('collections').Counter(t['status'] for t in targets).items()))
        summary = {'schema_version':SCHEMA,'delivery_key':delivery_key,'run_id':run_id,'event_date':run['event_date'],'timezone':run.get('timezone','UTC'),
                   'run_state':row['state'],'source_type':run['source_type'],'requested_count':run['requested_count'],
                   'frozen_count':len(run['targets']),'status_counts':counts,'limitations':run.get('limitations',[]),
                   'targets':targets,'graph_update_id':manifest['update_id'],
                   'source_snapshot_sha256':manifest['source_snapshot_sha256'],
                   'research_relation_counts':manifest['research_relation_counts'],
                   'stale_research_relations':manifest['stale_research_relations']}
        bspec = importlib.util.spec_from_file_location('rename_mail_report', Path(__file__).with_name('mail_report.py'))
        mail_report = importlib.util.module_from_spec(bspec); bspec.loader.exec_module(mail_report)
        candidate_path = out / 'paper_candidates.json'
        candidate_bytes = read_source(candidate_path if candidate_path.exists() else Path(__file__).resolve().parents[1]/'assets/email-paper-candidates.json')
        updates = [json.loads(line) for line in read_source(out/'updates.jsonl').decode().splitlines() if line.strip()]
        brief = mail_report.build_brief(summary, graph, view['relationship_records'], updates, json.loads(candidate_bytes))
        summary.update(email_body_version=mail_report.VERSION, sample_id=sample_id)
        folder = root / run_id
        require(not folder.exists(), 'Orphan archive folder; reconcile before preparing, never overwrite')
        temp = Path(tempfile.mkdtemp(prefix='.prepare-', dir=root))
        try:
            report = read_source(out / 'rename-knowledge-graph.html')
            expected_report = next(f['sha256'] for f in manifest['files'] if f['path']=='rename-knowledge-graph.html')
            require(sha(report)==expected_report, 'Report changed during copy; export and prepare again')
            (temp / 'report.html').write_bytes(report)
            (temp / 'run-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
            (temp / 'mail-brief.json').write_text(json.dumps(brief,ensure_ascii=False,indent=2)+'\n')
            buf = io.StringIO(newline=''); columns=['position','conversation_url','original_title','proposed_title','displayed_title','status','verification','result_event_id','rationale']
            writer=csv.DictWriter(buf,fieldnames=columns);writer.writeheader()
            for t in targets:
                cells={k:(dump(v) if isinstance(v,dict) else '' if v is None else str(v)) for k,v in t.items()}
                writer.writerow({k:("'"+v if v.lstrip().startswith(('=','+','-','@')) else v) for k,v in cells.items()})
            (temp / 'daily-results.csv').write_text('\ufeff'+buf.getvalue())
            renderer=Path(pdf_renderer) if pdf_renderer else Path(__file__).with_name('render_archive_pdf.cjs')
            require(node and node_modules, 'Provide bundled Node and node_modules paths for offline PDF rendering')
            env=dict(os.environ,NODE_PATH=str(node_modules))
            rendered=subprocess.run([str(node),str(renderer),str(temp/'report.html'),str(temp/'report.pdf'),run_id],env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60)
            require(rendered.returncode==0, 'PDF render failed: '+rendered.stderr[-300:])
            require((temp/'report.pdf').read_bytes().startswith(b'%PDF-'), 'PDF bytes unverified')
            internal=['report.html','daily-results.csv','run-summary.json','mail-brief.json']
            archive_manifest={'schema_version':SCHEMA,'delivery_key':delivery_key,'run_id':run_id,
                              'files':[{'filename':name,'sha256':sha((temp/name).read_bytes())} for name in internal],
                              'separate_pdf_attachment':{'filename':'report.pdf','sha256':sha((temp/'report.pdf').read_bytes())},
                              'email_body_version':mail_report.VERSION,'paper_candidate_asset_sha256':sha(candidate_bytes),
                              'evidence_semantics':'E0 recorded tag overlap; E1 metadata compatibility; H pending validation'}
            (temp/'archive-manifest.json').write_text(json.dumps(archive_manifest,ensure_ascii=False,indent=2)+'\n')
            with zipfile.ZipFile(temp/'report-bundle.zip','w',zipfile.ZIP_DEFLATED) as z:
                for name in internal+['archive-manifest.json']:
                    item=zipfile.ZipInfo(name,date_time=(2020,1,1,0,0,0));item.compress_type=zipfile.ZIP_DEFLATED;z.writestr(item,(temp/name).read_bytes())
            subject=f'ChatGPT {"Report Preview" if sample_id else "Naming report"} | {run["event_date"]} | {delivery_key}'
            body=mail_report.render(summary,brief,graph,delivery_key,sample=sample_id is not None)
            require(len(body.encode())<90000,'Email body exceeds conservative Gmail clipping budget')
            (temp/'body.html').write_text(body)
            package={'schema_version':SCHEMA,'delivery_key':delivery_key,'run_id':run_id,'recipient':recipient,
                     'subject':subject,'folder':str(folder),'body_sha256':sha(body.encode()),
                     'email_body_version':mail_report.VERSION,'sample_id':sample_id,'state_root':str(root),
                     'attachments':[{'filename':f'report{ext}','mime_type':mime,'sha256':sha((temp/f'report{ext}').read_bytes()),'size':(temp/f'report{ext}').stat().st_size} for ext,mime in [('.pdf','application/pdf'),('-bundle.zip','application/zip')]],
                     'source_snapshot_sha256':manifest['source_snapshot_sha256'],'graph_update_id':manifest['update_id']}
            os.replace(temp,folder)
            db.execute('INSERT INTO deliveries VALUES (?,?,?,?,?,?,?,?)',(delivery_key,run_id,recipient,'PREPARED',dump(package),None,None,None))
        finally:
            if temp.exists():shutil.rmtree(temp)
    return dict(package,prepared_new=True)


def claim(state_root, delivery_key):
    with connect(state_root) as db:
        db.execute('BEGIN IMMEDIATE');r=db.execute('SELECT * FROM deliveries WHERE delivery_key=?',(delivery_key,)).fetchone()
        require(r is not None,'Unknown delivery key');package=json.loads(r['package_json']);package_files(package)
        if r['state']!='PREPARED':return {'delivery_key':delivery_key,'dispatch_authorized':False,'state':r['state']}
        db.execute("UPDATE deliveries SET state='SEND_INTENT',claimed_at=? WHERE delivery_key=?",(now(),delivery_key))
    return {'delivery_key':delivery_key,'dispatch_authorized':True,'state':'SEND_INTENT'}


def retire_prepared(state_root, delivery_key, reason):
    """Preserve an unsent candidate for an explicit pre-dispatch artifact repair."""
    require(isinstance(reason,str) and 0<len(reason)<=300,'A bounded repair reason is required')
    with connect(state_root) as db:
        db.execute('BEGIN IMMEDIATE');r=db.execute('SELECT * FROM deliveries WHERE delivery_key=?',(delivery_key,)).fetchone()
        require(r is not None and r['state']=='PREPARED' and not r['claimed_at'] and not r['message_id'],
                'Only an unclaimed unsent preparation may be retired')
        package=json.loads(r['package_json']);package_files(package)
        revision=sha(r['package_json'].encode());old=Path(package['folder']);retired=old.with_name(old.name+'.unsent-'+revision[:12])
        require(not retired.exists(),'Retired preparation already exists; reconcile instead of overwriting')
        os.replace(old,retired)
        db.execute('INSERT INTO prepared_history VALUES (?,?,?,?,?,?)',(revision,delivery_key,now(),reason,str(retired),r['package_json']))
        db.execute('DELETE FROM deliveries WHERE delivery_key=?',(delivery_key,))
    return {'retired_unsent':True,'retired_folder':str(retired),'delivery_key':delivery_key}


def payload(state_root, delivery_key):
    with connect(state_root) as db:
        db.execute('BEGIN IMMEDIATE');r=db.execute('SELECT * FROM deliveries WHERE delivery_key=?',(delivery_key,)).fetchone()
        require(r is not None and r['state']=='SEND_INTENT','Send payload was already issued or no new dispatch claim exists; verify only')
        p=json.loads(r['package_json']);package_files(p);folder=Path(p['folder'])
        parts=[{'mime_type':'text/html','charset':'UTF-8','body':{'content':(folder/'body.html').read_text()}}]
        for a in p['attachments']:
            parts.append({'mime_type':a['mime_type'],'filename':a['filename'],'content_disposition':'attachment',
                          'body':{'base64_url_content':base64.urlsafe_b64encode((folder/a['filename']).read_bytes()).decode().rstrip('=')}})
        # Lost payload/tool responses are ambiguous. Reissuing is never a resend strategy.
        db.execute("UPDATE deliveries SET state='DISPATCH_STARTED' WHERE delivery_key=?",(delivery_key,))
    return {'to':p['recipient'],'subject':p['subject'],'payload':{'mime_type':'multipart/mixed','parts':parts},'response_fields':['id','thread_id','label_ids']}


def receipt(state_root, delivery_key, message_id):
    require(bool(re.fullmatch(r'[A-Za-z0-9_-]+',message_id or '')),'Exact Gmail message ID required')
    with connect(state_root) as db:
        db.execute('BEGIN IMMEDIATE');r=db.execute('SELECT * FROM deliveries WHERE delivery_key=?',(delivery_key,)).fetchone()
        require(r is not None and r['state'] in {'PREPARED','SEND_INTENT','DISPATCH_STARTED','SENT','VERIFIED'},'No archive to reconcile')
        require(r['message_id'] in {None,message_id},'Different message ID; reconcile possible duplicate without sending')
        if r['state']!='VERIFIED':db.execute("UPDATE deliveries SET state='SENT',message_id=? WHERE delivery_key=?",(message_id,delivery_key))
    return status(state_root,delivery_key)


def verify_raw(state_root, delivery_key, message_id, raw):
    r=info(state_root,delivery_key);p=json.loads(r['package_json']);package_files(p)
    require(r['state'] in {'SEND_INTENT','DISPATCH_STARTED','SENT','VERIFIED'} and r['message_id'] in {None,message_id},'Readback not bound to this send intent')
    data=base64.urlsafe_b64decode(raw+'='*((-len(raw))%4));m=BytesParser(policy=policy.default).parsebytes(data)
    require(len(m.get_all('Subject', [])) == 1, 'Exactly one subject is required')
    # Header folding can introduce leading FWS in Python's MIME parser. Only
    # trim surrounding header whitespace; all meaningful subject bytes must match.
    require(str(m['Subject']).strip(' \t')==p['subject'],'Sent subject mismatch')
    require([a.lower() for _,a in getaddresses(m.get_all('To',[]))]==[p['recipient'].lower()],'Sent recipient mismatch')
    require(not m.get_all('Cc') and not m.get_all('Bcc'),'Unexpected additional recipients')
    attachments={}
    for part in m.walk():
        if part.get_filename():
            require(part.get_filename() not in attachments,'Duplicate attachment filename')
            attachments[part.get_filename()]=part.get_payload(decode=True)
    require(set(attachments)=={a['filename'] for a in p['attachments']},'Attachment set mismatch')
    hashes={}
    for a in p['attachments']:
        hashes[a['filename']]=sha(attachments[a['filename']]);require(hashes[a['filename']]==a['sha256'],'Sent attachment bytes mismatch')
    bodies=[part.get_content() for part in m.walk() if part.get_content_type()=='text/html' and not part.get_filename()]
    require(len(bodies)==1,'One HTML report summary required')
    expected=(Path(p['folder'])/'body.html').read_text()
    require(bodies[0].replace('\r\n','\n').rstrip('\n')==expected.replace('\r\n','\n').rstrip('\n'),'Sent body mismatch')
    report={'verified_at':now(),'message_id':message_id,'delivery_key':delivery_key,'recipient':p['recipient'],
            'subject_matches':True,'body_matches':True,'attachment_sha256':hashes,'raw_sha256':sha(data),
            'evidence':'Gmail raw MIME byte readback; mailbox receipt/read status not asserted'}
    with connect(state_root) as db:
        db.execute('BEGIN IMMEDIATE');db.execute("UPDATE deliveries SET state='VERIFIED',message_id=?,verification_json=? WHERE delivery_key=?",(message_id,dump(report),delivery_key))
    atomic(Path(p['folder'])/'verification.json',(json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode())
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['prepare','retire-prepared','status','claim','payload','receipt','verify'])
    parser.add_argument('--state-root',required=True);parser.add_argument('--dataset-root');parser.add_argument('--run-id');parser.add_argument('--recipient');parser.add_argument('--key');parser.add_argument('--message-id');parser.add_argument('--input');parser.add_argument('--output');parser.add_argument('--reason');parser.add_argument('--node');parser.add_argument('--node-modules');parser.add_argument('--sample-id',help='Explicitly requested one-off sample only; separate durable namespace, never a retry bypass')
    a=parser.parse_args()
    try:
        require(a.sample_id is None or a.command=='prepare','sample-id is only valid for explicit sample preparation; use returned state_root for later gates')
        if a.command=='prepare':result=prepare(a.dataset_root,a.state_root,a.run_id,a.recipient,a.node,a.node_modules,sample_id=a.sample_id)
        elif a.command=='retire-prepared':result=retire_prepared(a.state_root,a.key,a.reason)
        elif a.command=='status':result=status(a.state_root,a.key)
        elif a.command=='claim':result=claim(a.state_root,a.key)
        elif a.command=='payload':result=payload(a.state_root,a.key)
        elif a.command=='receipt':result=receipt(a.state_root,a.key,a.message_id)
        else:result=verify_raw(a.state_root,a.key,a.message_id,json.loads(Path(a.input).read_text())['raw'])
        if a.output:
            encoded=json.dumps(result,ensure_ascii=False).encode();atomic(a.output,encoded)
            print(json.dumps({'path':str(Path(a.output).resolve()),'bytes':len(encoded),'sha256':sha(encoded)},ensure_ascii=False))
        else:
            print(json.dumps(result,ensure_ascii=False))
    except (ValueError,KeyError,TypeError,sqlite3.Error,OSError,subprocess.TimeoutExpired) as e:
        parser.exit(1,'Mail archive stopped: '+str(e)+'\n')


if __name__=='__main__':main()
