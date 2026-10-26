const test = require('node:test');
const assert = require('node:assert/strict');
const kit = require('../scripts/cua_workflow.js');
const url = i => `https://chatgpt.com/c/synthetic-${i}`;

const {fixture} = require('./fixtures/cua_fixture.cjs');

test('recent batch excludes pinned rows and freezes original order', async () => {
  const f = fixture({reorderOnSave: true});
  const w = kit.create(f.adapter, {mode: 'apply', batchAuthorized: true});
  const items = await w.freezeRecent(3);
  assert.deepEqual(items.map(x => x.url), f.frozenOrder.slice(0, 3));
  await w.context(url(0));
  assert.equal((await w.apply(url(0), 'Project Alpha | Research design')).status, 'RENAMED');
  assert.deepEqual(w.results().map(x => x.url), items.map(x => x.url));
  assert.equal(f.rows.find(r => r.url === url(1)).title, 'Project1 | Literature review');
});
test('a batch needs explicit scope authorization', async () => {
  const f = fixture(); const w = kit.create(f.adapter);
  await assert.rejects(w.freezeRecent(10), /batch authorization/);
  assert.equal(f.log.length, 0);
});
test('skip-to-content and body reference links are not sidebar rows', async () => {
  const f = fixture();
  const p = kit.parse(await f.adapter.observe());
  assert.equal(p.rows.length, 11);
  assert.equal(p.recentRows.length, 10);
  assert.equal(kit.rowFor(p, url(0)).title, 'Project0 | Literature review');
});
test('out-of-scope URL is rejected before any action', async () => {
  const f = fixture(); const w = kit.create(f.adapter, {mode: 'apply'});
  await w.freezeRecent(1);
  await assert.rejects(w.apply(url(8), 'Wrong target'), /outside frozen batch/);
  assert.equal(f.log.length, 0);
});
test('inspect preview cannot perform an edit', async () => {
  const f = fixture(); const w = kit.create(f.adapter);
  await w.freezeRecent(1); await w.context(url(0));
  assert.equal(w.preview(url(0), 'Project Alpha | Research design').changeNeeded, true);
  await assert.rejects(w.apply(url(0), 'Project Alpha | Research design'), /Inspect mode/);
  assert.equal(f.log.length, 0);
});
test('current title must be checked against the frozen title', async () => {
  const f = fixture(); const w = kit.create(f.adapter, {mode: 'apply'});
  await w.freezeRecent(1); await w.context(url(0)); f.changeTitle(0, 'User-edited title');
  assert.equal((await w.apply(url(0), 'Project Alpha | Research design')).status, 'BLOCKED');
  assert.equal(f.log.length, 0);
});
test('same title exits without menu, input, or save', async () => {
  const f = fixture(); const w = kit.create(f.adapter, {mode: 'apply'});
  await w.freezeRecent(1); await w.context(url(0));
  assert.equal((await w.apply(url(0), f.rows[0].title)).status, 'ALREADY CORRECT');
  assert.deepEqual(f.log, []);
});
test('ten-chat repeat keeps all ten and only navigates', async () => {
  const f = fixture(); const w = kit.create(f.adapter, {mode: 'apply', batchAuthorized: true});
  const frozen = await w.freezeRecent(10);
  for (const x of frozen) { await w.context(x.url); await w.apply(x.url, x.originalTitle); }
  assert.equal(w.results().filter(x => x.status === 'ALREADY CORRECT').length, 10);
  assert.ok(f.log.every(x => x.kind === 'navigate'));
  assert.equal(w.metrics().inputWrites, 0);
});
test('terminal results resume without reading or writing again', async () => {
  const f = fixture(); const w = kit.create(f.adapter, {mode: 'apply'});
  await w.freezeRecent(1); await w.context(url(0)); await w.apply(url(0), f.rows[0].title);
  const before = w.metrics();
  assert.equal((await w.context(url(0))).cached, true);
  await w.apply(url(0), 'Do not apply again');
  assert.deepEqual(w.metrics(), before);
});
test('delayed rename menu is observed without opening it twice', async () => {
  const f = fixture({menuDelay: 2}); const w = kit.create(f.adapter, {mode: 'apply'});
  await w.freezeRecent(1); await w.context(url(0));
  assert.equal((await w.apply(url(0), 'Project Alpha | Research design')).status, 'RENAMED');
  assert.equal(f.log.filter(x => x.kind === 'menu').length, 1);
});
test('dialog disappearance with empty sidebar does not establish success', async () => {
  const f = fixture({saveDelay: 4}); const w = kit.create(f.adapter, {mode: 'apply'});
  await w.freezeRecent(1); await w.context(url(0));
  const pending = await w.apply(url(0), 'Project Alpha | Research design');
  assert.equal(pending.phase, 'AWAITING_VERIFICATION'); assert.equal(pending.status, null);
  const confirmed = await w.verify(url(0));
  assert.equal(confirmed.status, 'RENAMED'); assert.equal(confirmed.displayedTitle, 'Project Alpha | Research design');
  assert.equal(f.log.filter(x => x.kind === 'save').length, 1);
});
test('repeating apply after a save only verifies; it never submits twice', async () => {
  const f = fixture({saveDelay: 4}); const w = kit.create(f.adapter, {mode: 'apply'});
  await w.freezeRecent(1); await w.context(url(0)); await w.apply(url(0), 'Project Alpha | Research design');
  assert.equal((await w.apply(url(0), 'Different proposal')).status, 'RENAMED');
  assert.equal(f.log.filter(x => x.kind === 'save').length, 1);
});
test('failed save reports observed old title and never resubmits', async () => {
  const f = fixture({failSave: true}); const w = kit.create(f.adapter, {mode: 'apply'});
  await w.freezeRecent(1); await w.context(url(0)); await w.apply(url(0), 'Project Alpha | Research design');
  const failed = await w.verify(url(0));
  assert.equal(failed.status, 'VERIFICATION FAILED'); assert.equal(failed.displayedTitle, 'Project0 | Literature review');
  assert.equal(f.log.filter(x => x.kind === 'save').length, 1);
});
test('unreadable post-save state is unknown, not an asserted rollback', async () => {
  const f = fixture({stuckSave: true}); const w = kit.create(f.adapter, {mode: 'apply'});
  await w.freezeRecent(1); await w.context(url(0)); await w.apply(url(0), 'Project Alpha | Research design');
  const failed = await w.verify(url(0));
  assert.equal(failed.status, 'VERIFICATION FAILED'); assert.equal(failed.displayedTitle, null);
});
test('unknown save click outcome can be verified but cannot trigger another save', async () => {
  const f = fixture({saveThrows: true}); const w = kit.create(f.adapter, {mode: 'apply'});
  await w.freezeRecent(1); await w.context(url(0)); await w.apply(url(0), 'Project Alpha | Research design');
  assert.equal((await w.apply(url(0), 'Project Alpha | Research design')).status, 'RENAMED');
  assert.equal(f.log.filter(x => x.kind === 'save').length, 1);
});
test('target switch before save blocks submission', async () => {
  const f = fixture({switchBeforeSave: true}); const w = kit.create(f.adapter, {mode: 'apply'});
  await w.freezeRecent(1); await w.context(url(0));
  assert.equal((await w.apply(url(0), 'Project Alpha | Research design')).status, 'BLOCKED');
  assert.equal(f.log.filter(x => x.kind === 'save').length, 0);
});
test('missing rename action never clicks archive or delete', async () => {
  const f = fixture({missingRename: true}); const w = kit.create(f.adapter, {mode: 'apply'});
  await w.freezeRecent(1); await w.context(url(0));
  assert.equal((await w.apply(url(0), 'Project Alpha | Research design')).status, 'BLOCKED');
  assert.deepEqual(f.log.map(x => x.kind), ['menu']);
});
test('missing save button does not guess a keyboard shortcut', async () => {
  const f = fixture({missingSave: true}); const w = kit.create(f.adapter, {mode: 'apply'});
  await w.freezeRecent(1); await w.context(url(0));
  assert.equal((await w.apply(url(0), 'Project Alpha | Research design')).status, 'BLOCKED');
  assert.equal(f.log.filter(x => x.kind === 'save').length, 0);
});
test('duplicate titles are resolved by exact URL, not row position', async () => {
  const f = fixture({duplicateTitles: true}); const w = kit.create(f.adapter, {mode: 'apply', batchAuthorized: true});
  await w.freezeRecent(2); await w.context(url(1));
  assert.equal((await w.apply(url(1), 'Project Beta | Research design')).status, 'RENAMED');
  assert.equal(f.rows.find(x => x.url === url(0)).title, 'Analyze');
});
test('matching address with an old document cannot supply another chat body', async () => {
  const f = fixture({wrongDocument: true}); const w = kit.create(f.adapter);
  await w.freezeRecent(1);
  await assert.rejects(w.context(url(0)), /body not ready/);
  assert.equal(w.metrics().contextCharsEmitted, 0);
});
test('outline returns project clues within a bounded model payload', async () => {
  const f = fixture({largeBody: true}); const w = kit.create(f.adapter);
  await w.freezeRecent(1);
  const summary = await w.context(url(0));
  assert.ok(summary.userPrompts.some(x => x.includes('Project Alpha')));
  assert.ok(summary.artifacts.some(x => x.includes('.pdf')));
  assert.ok(JSON.stringify(summary).length < 4500);
  assert.ok(w.metrics().snapshotCharsRead > w.metrics().contextCharsEmitted * 20);
});
test('unsupported destinations are not interpreted as target conversations', () => {
  for (const x of ['https://example.org/c/a', 'https://chatgpt.com/share/a', 'http://chatgpt.com/c/a', 'chatgpt.com/local/a']) assert.equal(kit.canonical(x), null);
});
test('footer and composer text never become user prompts or headings', async () => {
  const f = fixture({pendingReply: true}); const w = kit.create(f.adapter);
  await w.freezeRecent(1); const c = await w.context(url(0));
  assert.ok(c.userPrompts.includes('drp'));
  assert.ok(!JSON.stringify(c).includes('Reviewed'));
  assert.ok(!JSON.stringify(c).includes('Latest response'));
  assert.ok(!JSON.stringify(c).includes('entry area'));
});
test('ellipsis URL requires supported metadata plus matching selected tab and title', async () => {
  const f = fixture({ellipsisDocument: true, metadata: true}); const w = kit.create(f.adapter);
  await w.freezeRecent(1); const c = await w.context(url(0));
  assert.equal(c.url, url(0)); assert.equal(c.identitySource, 'supported-tab-metadata');
});
test('ellipsis URL without metadata cannot be assumed from address alone', async () => {
  const f = fixture({ellipsisDocument: true}); const w = kit.create(f.adapter);
  await w.freezeRecent(1); await assert.rejects(w.context(url(0)), /body not ready/);
});
test('conflicting selected tab or metadata title does not repair an ellipsis URL', async () => {
  for (const extra of [{wrongSelectedTitle: true}, {wrongMetadataTitle: true}]) {
    const f = fixture({ellipsisDocument: true, metadata: true, ...extra}); const w = kit.create(f.adapter);
    await w.freezeRecent(1); await assert.rejects(w.context(url(0)), /body not ready/);
  }
});
test('selected native tab value is not part of the page title', async () => {
  const f = fixture({ellipsisDocument: true, metadata: true, noMemoryLabel: true});
  const w = kit.create(f.adapter); await w.freezeRecent(1);
  assert.equal((await w.context(url(0))).identitySource, 'supported-tab-metadata');
});
test('pending save prevents navigation to another frozen chat', async () => {
  const f = fixture({saveDelay: 4}); const w = kit.create(f.adapter, {mode: 'apply', batchAuthorized: true});
  await w.freezeRecent(2); await w.context(url(0)); await w.apply(url(0), 'Project Alpha | Research design');
  const count = f.log.length;
  await assert.rejects(w.context(url(1)), /Unresolved save/);
  assert.equal(f.log.length, count);
  assert.equal((await w.verify(url(0))).status, 'RENAMED');
  assert.equal((await w.context(url(1))).url, url(1));
});
test('blocked editor must be closed before another chat can be opened', async () => {
  const f = fixture({missingSave: true}); const w = kit.create(f.adapter, {mode: 'apply', batchAuthorized: true});
  await w.freezeRecent(2); await w.context(url(0)); await w.apply(url(0), 'Project Alpha | Research design');
  const count = f.log.length;
  await assert.rejects(w.context(url(1)), /Close observed title editor/);
  assert.equal(f.log.length, count);
});
