const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const kit = require('../scripts/cua_workflow.js');
const {fixture, url} = require('./fixtures/cua_fixture.cjs');
const script = path.resolve(__dirname, '../scripts/research_journal.py');
const title = 'Synthetic project | Research design';

function setup(t, options = {}, count = 2) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'rename-recovery-'));
  t.after(() => fs.rmSync(root, {recursive:true, force:true}));
  fs.writeFileSync(path.join(root, 'dataset.json'), JSON.stringify({schema_version:'1.0.0',allow_synthetic:true}));
  const f = fixture(options);
  let binding = 'Chrome/TestProfile/synthetic-extension', fault = false, epoch = 0;
  const adapter = {...f.adapter, observe: async () => {
    if (fault) throw new Error('Synthetic connection reset');
    const observed = await f.adapter.observe();
    return {...(typeof observed === 'string' ? {ax:observed} : observed), bindingKey:binding};
  }};
  const journal = (command, value, extra=[]) => {
    const args = [script, command, '--root', root, '--run-id', 'recovery-test', ...extra];
    if (value) { fs.writeFileSync(path.join(root, 'input.json'), JSON.stringify(value)); args.push('--input',path.join(root,'input.json')); }
    return JSON.parse(execFileSync('python3', args, {encoding:'utf8',stdio:['ignore','pipe','pipe']}));
  };
  journal('init');
  const workflow = () => kit.create(adapter, {mode:'apply', batchAuthorized:true, durable:true,
    runId:'recovery-test', bindingKey:'Chrome/TestProfile/synthetic-extension', sessionEpoch:'connection-'+(++epoch)});
  const start = async w => {
    const frozen = await w.freezeRecent(count);
    const spec = {run_id:'recovery-test',event_date:'2025-01-02',mode:'apply',source_type:'synthetic',
      source_ref:'isolated synthetic recovery regression',skill_version:'1.5.0',recovery_protocol:kit.protocol,
      browser_binding:'Chrome/TestProfile/synthetic-extension',
      scope_kind:'recent_top_n',selection_rule:'synthetic first N, pinned excluded',requested_count:count,exclude_pinned:true,
      targets:frozen.map(x=>({conversation_url:x.url,original_title:x.originalTitle}))};
    const ack = journal('start',spec); w.acceptJournal(ack.recovery); return ack;
  };
  const prepare = async (w, i=0) => {
    await w.context(url(i));
    journal('record',{conversation_url:url(i),stage:'PLANNED',status:null,decision:'rename',
      proposed_title:title,displayed_title:null,save_attempted:null,rationale:'Synthetic plan'});
    const r = await w.apply(url(i), title);
    assert.equal(r.phase, 'READY_FOR_SAVE');
    return {r, input:{conversation_url:url(i),proposed_title:title,observation:r.observation}};
  };
  return {root,f,journal,workflow,start,prepare,
    binding:value=>binding=value, fault:value=>fault=value};
}

test('durable mode gates context on committed frozen scope and gates save on arm', async t => {
  const x=setup(t), w=x.workflow();
  await w.freezeRecent(2);
  await assert.rejects(w.context(url(0)),/acknowledgement/);
  assert.equal(x.f.log.length,0);
  const w2=x.workflow(); await x.start(w2);
  const p=await x.prepare(w2);
  assert.equal(x.f.log.filter(a=>a.kind==='save').length,0);
  const ack=x.journal('arm',p.input);
  const r=await w2.commit(url(0),ack);
  assert.equal(r.status,'RENAMED');
  const e=kit.toEvent(r,{topic_labels:['Synthetic'],annotation_basis:'visible_context'});
  assert.equal(x.journal('record',e).inserted,true);
  assert.equal(x.journal('record',e).inserted,false);
  assert.equal(x.f.log.filter(a=>a.kind==='save').length,1);
  await assert.rejects(w2.commit(url(0),ack),/never replay/);
});

test('lost arm acknowledgement never authorizes another dispatch or another target', async t => {
  const x=setup(t), w=x.workflow(); await x.start(w);
  const p=await x.prepare(w); x.journal('arm',p.input);
  const retry=x.journal('arm',p.input);
  assert.equal(retry.dispatch_authorized,false);
  const r=await w.commit(url(0),retry);
  assert.equal(r.saveAttempted,null);
  await assert.rejects(w.context(url(1)),/Unresolved save/);
  const recovered=x.workflow(); recovered.restore(x.journal('resume'));
  await assert.rejects(recovered.context(url(0)),/verification only/);
  await recovered.verify(url(0)); await recovered.verify(url(0));
  assert.equal(x.f.log.filter(a=>a.kind==='save').length,0);
});

test('foreground change after arm blocks save and cannot be cleared by retrying apply', async t => {
  const x=setup(t), w=x.workflow(); await x.start(w);
  const p=await x.prepare(w), ack=x.journal('arm',p.input);
  x.f.switchTo(1);
  const r=await w.commit(url(0),ack);
  assert.equal(r.phase,'AWAITING_VERIFICATION'); assert.equal(r.saveAttempted,null);
  assert.match(r.reason,/changed after arming/);
  await w.apply(url(0),title); await w.apply(url(0),title);
  await assert.rejects(w.context(url(1)),/Unresolved save/);
  assert.equal(x.f.log.filter(a=>a.kind==='save').length,0);
});

test('connection reset after dispatched save resumes verification without replay', async t => {
  const x=setup(t,{saveDelay:4}), w=x.workflow(); await x.start(w);
  const p=await x.prepare(w), ack=x.journal('arm',p.input);
  const pending=await w.commit(url(0),ack);
  assert.equal(pending.phase,'AWAITING_VERIFICATION');
  x.journal('record',kit.toEvent(pending));
  x.fault(true); await assert.rejects(w.verify(url(0)),/connection reset/);
  x.fault(false); await assert.rejects(w.verify(url(0)),/Connection invalidated/);
  const next=x.workflow(), state=x.journal('resume');
  assert.deepEqual(state.targets.map(t=>t.conversation_url),[url(0),url(1)]);
  next.restore(state);
  const result=await next.verify(url(0)); assert.equal(result.status,'RENAMED');
  const event=kit.toEvent(result); x.journal('record',event);
  const before=x.journal('stats');
  assert.equal(x.journal('record',event).inserted,false);
  assert.deepEqual(x.journal('stats'),before);
  assert.equal(x.f.log.filter(a=>a.kind==='save').length,1);
});

test('crash after dispatch before result checkpoint stays unknown and never repeats save', async t => {
  const x=setup(t), w=x.workflow(); await x.start(w);
  const p=await x.prepare(w); await w.commit(url(0),x.journal('arm',p.input));
  // Deliberately lose the live result instead of inventing a save-attempt checkpoint.
  const next=x.workflow(); next.restore(x.journal('resume'));
  const r=await next.verify(url(0));
  assert.equal(r.status,'VERIFICATION FAILED'); assert.equal(r.displayedTitle,title);
  assert.equal(r.saveAttempted,null);
  assert.equal(x.f.log.filter(a=>a.kind==='save').length,1);
});

test('binding ID reuse invalidates connection; stable rediscovery uses a new epoch', async t => {
  const x=setup(t), w=x.workflow(); await x.start(w);
  x.binding('MCPApps/reused-numeric-id');
  await assert.rejects(w.context(url(0)),/binding changed/);
  x.binding('Chrome/TestProfile/synthetic-extension');
  await assert.rejects(w.context(url(0)),/Connection invalidated/);
  const next=x.workflow(); next.restore(x.journal('resume'));
  await next.context(url(0));
  assert.equal(x.f.log.filter(a=>a.kind==='save').length,0);
});

test('a stale acknowledgement and an old session acknowledgement cannot dispatch', async t => {
  const x=setup(t), w=x.workflow(); await x.start(w);
  const p=await x.prepare(w), ack=x.journal('arm',p.input);
  const wrong={...ack,session_epoch:'previous-session'};
  await assert.rejects(w.commit(url(0),wrong),/target\/session/);
  const expired={...ack,armed_at:'2020-01-01T00:00:00Z'};
  const r=await w.commit(url(0),expired);
  assert.match(r.reason,/expired/);
  assert.equal(x.f.log.filter(a=>a.kind==='save').length,0);
});

test('restore refuses a different stable profile even if numeric IDs look reusable', async t => {
  const x=setup(t), w=x.workflow(); await x.start(w);
  const wrong=kit.create(x.f.adapter,{mode:'apply',batchAuthorized:true,durable:true,
    runId:'recovery-test',bindingKey:'Chrome/a/another-extension',sessionEpoch:'new-connection'});
  assert.throws(()=>wrong.restore(x.journal('resume')),/identity mismatch/);
  assert.equal(x.f.log.length,0);
});

test('a no-save foreground interruption can recover only on the original clean target', async t => {
  const x=setup(t), w=x.workflow(); await x.start(w); await w.context(url(0));
  x.f.switchTo(1);
  const blocked=await w.apply(url(0),title);
  assert.equal(blocked.status,'BLOCKED'); assert.equal(blocked.saveAttempted,false);
  await assert.rejects(w.recoverBlocked(url(0)),/Restore target/);
  const old=x.journal('record',{conversation_url:url(0),status:'BLOCKED',decision:'undetermined',
    proposed_title:null,displayed_title:null,save_attempted:false,rationale:'Synthetic foreground interruption'});
  x.f.switchTo(0); await w.recoverBlocked(url(0)); await w.context(url(0));
  const r=await w.apply(url(0),x.f.rows[0].title);
  const e=kit.toEvent(r); e.stage='CORRECTION'; e.supersedes_event_id=old.event_id;
  assert.equal(x.journal('record',e).inserted,true);
  assert.equal(x.f.log.filter(a=>a.kind==='save').length,0);
});

test('atomic evidence ignores a poisoned global cache and rejects cached deliveries and overrides', async t => {
  const x=setup(t), w=x.workflow(); await x.start(w);
  await w.context(url(0));
  const result=await w.apply(url(0),x.f.rows[0].title);
  global.lastView={addressUrl:url(9),documentUrl:null};
  const e=kit.toEvent(result);
  assert.equal(e.observation.address_url,url(0));
  assert.ok(e.verification.address_url_matches);
  assert.throws(()=>kit.toEvent(result,{verification:{}}),/override/);
  x.journal('record',e);
  assert.throws(()=>kit.toEvent(w.results()[0]),/Cached/);
  const changed=structuredClone(e); changed.observation.target_url=url(1);
  assert.throws(()=>x.journal('record',changed),/target\/run mismatch/);
  const conflict=structuredClone(e); conflict.verification.document_url_matches=false;
  assert.throws(()=>x.journal('record',conflict));
  delete global.lastView;
});

test('restored blocked unknown title recovers to a fresh no-save correction exactly once', async t => {
  const x=setup(t,{},1), initial=x.workflow(); await x.start(initial);
  const old=x.journal('record',{conversation_url:url(0),status:'BLOCKED',decision:'undetermined',
    proposed_title:null,displayed_title:null,save_attempted:false,rationale:'Synthetic load failure'});
  x.journal('finish',null,['--state','PARTIAL']);
  const state=x.journal('reopen'), recovered=x.workflow(); recovered.restore(state);
  await recovered.recoverBlocked(url(0)); await recovered.context(url(0));
  const result=await recovered.apply(url(0),x.f.rows[0].title);
  assert.equal(result.displayedTitle,result.observation.sidebar_title);
  assert.equal(result.displayedTitle,x.f.rows[0].title);
  const event=kit.toCorrection(result,state);
  assert.equal(event.supersedes_event_id,old.event_id);
  assert.equal(x.journal('record',event).inserted,true);
  assert.equal(x.journal('finish',null,['--state','COMPLETE']).finalized,true);
  assert.equal(x.journal('record',event).inserted,false);
  const replay=x.workflow(); replay.restore(x.journal('resume'));
  assert.equal((await replay.apply(url(0),x.f.rows[0].title)).delivery,'cached');
  assert.equal(replay.metrics().observations,0);
  assert.equal(x.f.log.filter(a=>a.kind==='save').length,0);
});

test('load recovery resumes item seven in the original ten and cannot turn replay into new evidence', async t => {
  const x=setup(t,{},10), initial=x.workflow(); await x.start(initial);
  const ids=[];
  for(let i=0;i<10;i++) {
    if(i===6) {
      ids.push(x.journal('record',{conversation_url:url(i),status:'BLOCKED',decision:'undetermined',
        proposed_title:null,displayed_title:null,save_attempted:false,rationale:'Synthetic body load failure',
        reason_codes:['BODY_NOT_READY'],context_level:'not_ready'}).event_id);
    } else {
      await initial.context(url(i));
      ids.push(x.journal('record',kit.toEvent(await initial.apply(url(i),x.f.rows[i].title))).event_id);
    }
  }
  x.journal('finish',null,['--state','PARTIAL']);
  x.f.switchTo(6); x.f.setBodyLoaded(false);
  const closed=x.workflow(); closed.restore(x.journal('resume'));
  await assert.rejects(closed.recoverBlocked(url(6)),/reopen/);
  const ack=x.journal('reopen'), resumed=x.workflow(); resumed.restore(ack);
  await assert.rejects(resumed.recoverBlocked(url(6)),/body not ready/);
  const partial=x.journal('resume');
  assert.equal(partial.targets[6].latest_event_id,ids[6]);
  x.f.setBodyLoaded(true); await resumed.recoverBlocked(url(6)); await resumed.context(url(6));
  const result=await resumed.apply(url(6),x.f.rows[6].title);
  const correction=kit.toCorrection(result,ack,{reason_codes:['EXISTING_TITLE_ADEQUATE']});
  assert.equal(correction.stage,'CORRECTION'); assert.equal(correction.displayed_title,x.f.rows[6].title);
  assert.equal(correction.supersedes_event_id,ids[6]);
  assert.equal(x.journal('record',correction).inserted,true);
  x.journal('finish',null,['--state','COMPLETE']);
  const before=x.journal('stats'), committed=x.journal('resume');
  assert.equal(committed.state,'COMPLETE'); assert.equal(committed.targets.length,10);
  committed.targets.forEach((item,i)=>{if(i!==6)assert.equal(item.latest_event_id,ids[i]);});
  assert.equal(x.journal('record',correction).inserted,false);
  assert.deepEqual(x.journal('stats'),before);
  const replay=x.workflow(); replay.restore(committed);
  for(const item of committed.targets) {
    const cached=await replay.apply(item.conversation_url,item.original_title);
    assert.equal(cached.delivery,'cached');
    assert.throws(()=>kit.toCorrection(cached,ack),/Cached/);
  }
  assert.equal(replay.metrics().observations,0);
  assert.equal(x.f.log.filter(a=>a.kind==='save'||a.kind==='input').length,0);
  assert.throws(()=>kit.toCorrection(result,{...ack,run_id:'another-run'}),/original run/);
  const armed=structuredClone(ack); armed.targets[6].save_intent={intent_id:'existing-intent'};
  assert.throws(()=>kit.toCorrection(result,armed),/no-save blocked/);
  const unknown=structuredClone(ack); unknown.targets[6].latest_event.save_attempted=null;
  assert.throws(()=>kit.toCorrection(result,unknown),/no-save blocked/);
  assert.throws(()=>kit.toCorrection({...result,displayedTitle:null},ack),/actual title/);
});

test('blocked controls can be recorded with unknown evidence without claiming a fresh title', async t => {
  const x=setup(t,{missingRename:true}), w=x.workflow(); await x.start(w); await w.context(url(0));
  const r=await w.apply(url(0),title); assert.equal(r.status,'BLOCKED');
  const e=kit.toEvent(r); assert.equal(e.displayed_title,null); assert.equal(e.observed_at,null);
  assert.equal(e.verification.document_url_matches,null); assert.ok(!e.observation);
  assert.equal(x.journal('record',e).inserted,true);
  assert.equal(x.f.log.filter(a=>a.kind==='save').length,0);
});

test('full ten-item persisted replay skips all targets without new saves or events', async t => {
  const x=setup(t,{},10), w=x.workflow(); await x.start(w);
  for(let i=0;i<10;i++) {
    await w.context(url(i)); const r=await w.apply(url(i),x.f.rows[i].title);
    x.journal('record',kit.toEvent(r));
  }
  x.journal('finish',null,['--state','COMPLETE']);
  const before=x.journal('stats'), calls=x.f.log.length;
  const next=x.workflow(), state=x.journal('resume'); next.restore(state);
  assert.ok(state.targets.every(t=>t.action==='SKIP_VERIFIED'));
  for(const t of state.targets) {
    const r=await next.apply(t.conversation_url,t.original_title);
    assert.equal(r.delivery,'cached'); assert.throws(()=>kit.toEvent(r),/Cached/);
  }
  assert.deepEqual(x.journal('stats'),before); assert.equal(x.f.log.length,calls);
  assert.equal(x.f.log.filter(a=>a.kind==='save').length,0);
});
