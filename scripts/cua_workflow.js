/* Load this source into cua_repl after its initialization/documentation call.
 * The injected adapter must use documented cua APIs. No browser, network or
 * filesystem connection is opened here. Node export exists for offline tests.
 */
var ChatTitleWorkflow = (() => {
  const terminal = new Set(['RENAMED', 'ALREADY CORRECT', 'BLOCKED', 'VERIFICATION FAILED']);
  const names = {
    recent: /^(?:sortable 最近項目|sortable 最近项目|sortable Recents|heading Recents)(?:,.*)?$/,
    actions: /^pop up button (?:對話動作|对话动作|Conversation actions)$/,
    rename: /^(?:menu item )?(?:重新命名|重命名|Rename)$/,
    input: /^text field \(settable\) (?:對話標題|对话标题|Chat title), Value: (.*?)(?:, Placeholder:.*)?$/,
    save: /^button (?:儲存|保存|Save)$/,
  };
  function ensure(value, message) { if (!value) throw new Error(message); }
  function canonical(value) {
    try {
      const u = new URL(/^https?:\/\//.test(value) ? value : 'https://' + value);
      if (u.protocol !== 'https:' || u.hostname !== 'chatgpt.com' ||
          !/^\/(?:g\/[^/]+\/)?c\/[a-z0-9-]+\/?$/i.test(u.pathname)) return null;
      return u.origin + u.pathname.replace(/\/$/, '');
    } catch (_) { return null; }
  }
  function parse(snapshot) {
    const text = typeof snapshot === 'string' ? snapshot : snapshot.ax;
    const identity = typeof snapshot === 'string' ? null : snapshot.documentIdentity;
    const nodes = [];
    const stack = [];
    for (const line of text.split('\n')) {
      const m = line.match(/^(\s*)(\d+) (.+)$/);
      if (!m) continue;
      const indent = m[1].replace(/\t/g, '    ').length;
      while (stack.length && nodes[stack.at(-1)].indent >= indent) stack.pop();
      nodes.push({id: Number(m[2]), body: m[3], indent, parent: stack.at(-1)});
      stack.push(nodes.length - 1);
    }
    const end = index => {
      let j = index + 1;
      while (j < nodes.length && nodes[j].indent > nodes[index].indent) j++;
      return j;
    };
    const address = nodes.find(n => n.body.includes('Address and search bar,') && n.body.includes('Value: '));
    const doc = nodes.find(n => n.body.startsWith('HTML content '));
    const docParts = doc?.body.match(/^HTML content (.*), URL: ([^\s,]+)/);
    const rows = [];
    nodes.forEach((n, index) => {
      const m = n.body.match(/^link (.*), Value: ([^\s,]+)$/);
      const url = m && canonical(m[2]);
      if (!url) return;
      const parent = n.parent;
      if (parent === undefined || nodes[parent].body !== 'container ' + m[1]) return;
      const siblings = parent === undefined ? [] : nodes.slice(parent + 1, end(parent));
      const menuId = siblings.find(x => names.actions.test(x.body))?.id;
      if (menuId === undefined) return;
      rows.push({url, title: m[1], id: n.id, index, menuId});
    });
    const recentAt = nodes.findIndex(n => names.recent.test(n.body));
    const listAt = recentAt < 0 ? -1 : nodes.findIndex((n, i) => i > recentAt && n.body === 'content list');
    const recentRows = listAt < 0 ? [] : rows.filter(r => r.index > listAt && r.index < end(listAt));
    const mainAt = nodes.findIndex(n => /^(?:container 對話|container 对话|container Conversation)$/.test(n.body));
    let main = mainAt < 0 ? [] : nodes.slice(mainAt + 1, end(mainAt));
    const footerAt = main.findIndex(n => /^text (?:ChatGPT 可能會出錯|ChatGPT 可能会出错|ChatGPT can make mistakes)/.test(n.body));
    if (footerAt >= 0) main = main.slice(0, footerAt);
    const addressUrl = canonical(address?.body.match(/Value: ([^,\s]+)/)?.[1] || '');
    let documentUrl = canonical(docParts?.[2] || '');
    let identitySource = documentUrl ? 'native-ax' : null;
    const selected = nodes.find(n => /^tab \([^)]*selected[^)]*\) /.test(n.body));
    const selectedTitle = selected?.body.replace(/^tab \([^)]*\) /, '').replace(/, Value:.*$/, '');
    if (!documentUrl && ['…', '...'].includes(docParts?.[2]) && identity &&
        canonical(identity.url) === addressUrl && identity.title === docParts?.[1] &&
        (selectedTitle === identity.title || selectedTitle?.startsWith(identity.title + ' - '))) {
      documentUrl = canonical(identity.url); identitySource = 'supported-tab-metadata';
    }
    return {nodes, rows, recentRows, main, addressUrl,
      documentUrl, identitySource, documentTitle: docParts?.[1], chars: text.length};
  }
  function rowFor(p, url) {
    const matches = p.rows.filter(r => r.url === url);
    ensure(matches.length, 'Target row unavailable');
    ensure(new Set(matches.map(r => r.title)).size === 1, 'Conflicting titles for target URL');
    return p.recentRows.find(r => r.url === url) || matches[0];
  }
  function active(p, url) { return p.addressUrl === url && p.documentUrl === url; }
  function ready(p, url) {
    const loadError = p.nodes.some(n => /^(?:text|heading) (?:無法載入此 ChatGPT 對話|无法加载此 ChatGPT 对话|Unable to load (?:this ChatGPT )?conversation)(?:,.*)?$/i.test(n.body));
    return active(p, url) && !loadError && p.main.some(n => /^text (?!field\b|entry area\b)/.test(n.body) &&
      !/^text (?:You said:|你說：|你说：|ChatGPT said:|ChatGPT 說：|ChatGPT 说：|正在載入|正在加载|Loading)/.test(n.body));
  }
  function compactContext(p, {level = 'outline', budget = 3500} = {}) {
    ensure(['outline', 'expanded'].includes(level), 'Unknown context level');
    const prompts = [], headings = [], artifacts = [], paragraphs = [];
    let inUser = false;
    for (const n of p.main) {
      if (/^heading (?:You said:|你說：|你说：)/.test(n.body)) inUser = true;
      else if (/^heading (?:ChatGPT said:|ChatGPT 說：|ChatGPT 说：)/.test(n.body)) inUser = false;
      else if (/^button (?:複製訊息|复制消息|Copy message)(?:,.*)?$/.test(n.body)) inUser = false;
      if (n.body.startsWith('heading ') && !/^heading (?:You said:|你說：|你说：|ChatGPT)/.test(n.body))
        headings.push(n.body.slice(8).replace(/, Value:.*$/, ''));
      if (!/^text (?!field\b|entry area\b)/.test(n.body)) continue;
      const t = n.body.slice(5);
      if (/^(?:You said:|你說：|你说：|ChatGPT said:|ChatGPT 說：|ChatGPT 说：|正在載入|正在加载)/.test(t)) continue;
      if (inUser) prompts.push(t);
      if (/\.(?:pdf|docx|zip|md|txt)\b/i.test(t)) artifacts.push(t);
      if (t.length >= 80) paragraphs.push(t);
    }
    const sample = (xs, head, tail) => [...new Set([...xs.slice(0, head), ...xs.slice(-tail)])];
    let remaining = Math.max(500, budget);
    const pack = values => values.map(v => {
      const t = v.slice(0, Math.min(600, remaining)); remaining -= t.length; return t;
    }).filter(Boolean);
    const result = {url: p.documentUrl, title: p.documentTitle, identitySource: p.identitySource, level,
      userPrompts: pack(sample(prompts, 2, 4)), headings: pack(sample(headings, 3, 6)),
      artifacts: pack(sample(artifacts, 2, 2)), sampled: true};
    if (level === 'expanded') result.excerpts = pack(sample(paragraphs, 1, 2));
    return result;
  }
  const protocol = 'rename-recovery/1';
  const editorOpen = p => p.nodes.some(n => names.input.test(n.body));
  // Pure metadata conversion: callers cannot rebuild verification from a mutable lastView.
  function toEvent(outcome, annotation = {}) {
    const o = outcome.observation;
    ensure(outcome.delivery === 'fresh', 'Cached result is not fresh evidence');
    const allowed = new Set(['rationale', 'reason_codes', 'topic_labels', 'task_type', 'annotation_basis', 'context_level']);
    ensure(Object.keys(annotation).every(k => allowed.has(k)), 'Annotation cannot override verification');
    const event = {conversation_url: outcome.url, stage: outcome.status ? 'RESULT' : 'SAVE_PENDING',
      status: outcome.status, decision: outcome.proposedTitle === outcome.originalTitle ? 'keep' : 'rename',
      proposed_title: outcome.proposedTitle, displayed_title: outcome.displayedTitle,
      save_attempted: outcome.saveAttempted, rationale: outcome.rationale || outcome.reason || 'Metadata outcome',
      ...annotation};
    if (!o || o.fresh !== true) {
      ensure(['BLOCKED', 'VERIFICATION FAILED'].includes(outcome.status), 'Cached result is not fresh evidence');
      return {...event, displayed_title: null, observed_at: null, verification: {
        address_url_matches:null, document_url_matches:null, sidebar_title_matches:null,
        editor_closed:null, identity_source:'unknown'}};
    }
    ensure(o.run_id === outcome.runId && o.target_url === outcome.url, 'Evidence target/run mismatch');
    return {...event, observed_at:o.observed_at, observation:{...o}, verification:{...outcome.verification}};
  }
  function toCorrection(outcome, recovery, annotation = {}) {
    ensure(outcome.delivery === 'fresh', 'Cached result is not fresh evidence');
    ensure(recovery?.protocol === protocol && recovery.committed === true &&
      recovery.run_id === outcome.runId && recovery.state === 'OPEN',
      'Use the committed reopened acknowledgement of the original run');
    const prior = recovery.targets.find(t => t.conversation_url === outcome.url);
    ensure(prior?.action === 'REVIEW_BLOCKED' && prior.latest_event?.status === 'BLOCKED' &&
      prior.latest_event.save_attempted === false && prior.save_intent === null &&
      /^[a-f0-9]{64}$/.test(prior.latest_event_id), 'Correction needs the exact no-save blocked target');
    ensure(outcome.originalTitle === prior.original_title &&
      ['ALREADY CORRECT', 'RENAMED'].includes(outcome.status), 'Only a successfully recovered target can be corrected');
    const event = toEvent(outcome, annotation);
    ensure(event.observation?.binding_key === recovery.binding_key &&
      event.displayed_title === event.observation.sidebar_title &&
      event.proposed_title === event.displayed_title && event.observation.editor_closed === true,
      'Recovery correction requires the actual title from the same fresh observation');
    return {...event, stage: 'CORRECTION', supersedes_event_id: prior.latest_event_id};
  }
  function create(adapter, {mode = 'inspect', batchAuthorized = false, maxObservations = 3,
    durable = false, runId = null, bindingKey = null, sessionEpoch = null, now = () => Date.now()} = {}) {
    ensure(['inspect', 'apply'].includes(mode), 'Unknown mode');
    ensure(Number.isInteger(maxObservations) && maxObservations > 0 && maxObservations <= 5, 'Invalid observation bound');
    if (durable) ensure(runId && bindingKey && sessionEpoch, 'Durable run needs run/binding/session identity');
    const items = new Map();
    let sequence = 0, journalAck = !durable, journalState = null, paused = false;
    const totals = {observations: 0, clicks: 0, inputWrites: 0, snapshotCharsRead: 0, contextCharsEmitted: 0};
    const result = (item, cached = false) => ({...item, runId, delivery: cached ? 'cached' : 'fresh',
      observation: item.observation ? {...item.observation, fresh: !cached && item.observation.fresh === true} : null,
      verification: item.verification ? {...item.verification} : null,
      metrics: {...item.metrics}, elapsedMs: now() - item.startedAt});
    function capture(item, p) {
      let sidebar = null; try { sidebar = rowFor(p, item.url).title; } catch (_) {}
      item.observation = {protocol, run_id: runId, target_url: item.url,
        session_epoch: sessionEpoch, binding_key: bindingKey, snapshot_id: p.snapshotId,
        observed_at: p.observedAt, fresh: true, address_url: p.addressUrl,
        document_url: p.documentUrl, document_title: p.documentTitle || null,
        sidebar_title: sidebar, editor_closed: !editorOpen(p), identity_source: p.identitySource || 'unknown'};
      item.verification = {address_url_matches: p.addressUrl === item.url,
        document_url_matches: p.documentUrl === item.url,
        sidebar_title_matches: sidebar !== null && sidebar === item.proposedTitle,
        editor_closed: !editorOpen(p), identity_source: p.identitySource || 'unknown'};
    }
    function connected() { ensure(!paused, 'Connection invalidated; rediscover binding and restore journal in a new session'); }
    async function observe(item) {
      connected();
      let snapshot;
      try {
        snapshot = await adapter.observe();
        if (durable) ensure(typeof snapshot === 'object' && snapshot.bindingKey === bindingKey,
          'Browser binding changed; do not reuse numeric browser IDs');
      } catch (error) { paused = true; throw error; }
      const text = typeof snapshot === 'string' ? snapshot : snapshot.ax;
      totals.observations++; totals.snapshotCharsRead += text.length;
      if (item) { item.metrics.observations++; item.metrics.snapshotCharsRead += text.length; }
      const p = parse(snapshot);
      p.snapshotId = `${sessionEpoch || 'memory'}:${++sequence}`;
      p.observedAt = new Date(now()).toISOString();
      return p;
    }
    async function waitFor(item, predicate) {
      let p;
      for (let i = 0; i < maxObservations; i++) { p = await observe(item); if (predicate(p)) return p; }
      return p;
    }
    async function click(item, id) { totals.clicks++; item.metrics.clicks++; await adapter.click(id); }
    function itemFor(value) {
      const item = items.get(canonical(value));
      ensure(item, 'URL outside frozen batch'); return item;
    }
    function noUnresolvedSave(except) {
      ensure(![...items.values()].some(x => x !== except && (x.saveIntent || x.saveAttempted) && x.status !== 'RENAMED'),
        'Unresolved save; verify it before reading or navigating');
    }
    function acknowledged() { ensure(journalAck, 'Await committed journal start/resume acknowledgement first'); }
    function freeze(rows, count) {
      ensure(!items.size, 'Batch is already frozen');
      ensure(count === 1 || batchAuthorized, 'Explicit batch authorization required');
      ensure(rows.length >= count, 'Not enough uniquely identified visible conversations');
      const selected = rows.slice(0, count);
      ensure(new Set(selected.map(r => r.url)).size === count, 'Duplicate target URLs');
      selected.forEach((r, index) => items.set(r.url, {
        order: index + 1, url: r.url, originalTitle: r.title, proposedTitle: null,
        displayedTitle: r.title, status: null, phase: 'PENDING', contextRead: false,
        saveAttempted: false, saveIntent: false, verifyOnly: false, verifyRounds: 0, startedAt: now(),
        metrics: {observations: 0, clicks: 0, inputWrites: 0, snapshotCharsRead: 0, contextCharsEmitted: 0},
      }));
      return [...items.values()].map(x => result(x));
    }
    async function freezeRecent(count) {
      ensure(Number.isInteger(count) && count > 0, 'Positive count required');
      return freeze((await observe()).recentRows, count);
    }
    async function freezeUrls(urls) {
      const p = await observe();
      ensure(urls.length > 0 && urls.every(u => canonical(u)), 'Exact conversation URLs required');
      return freeze(urls.map(u => rowFor(p, canonical(u))), urls.length);
    }
    async function context(url, options) {
      acknowledged();
      const item = itemFor(url);
      if (terminal.has(item.status)) return {cached: true, result: result(item, true)};
      ensure(!item.verifyOnly, 'Recovered uncertain state permits verification only');
      noUnresolvedSave();
      let p = await observe(item);
      ensure(!p.nodes.some(n => /text field.*(?:對話標題|对话标题|Chat title)/.test(n.body)),
        'Close observed title editor before changing context');
      if (p.addressUrl !== item.url) {
        await click(item, rowFor(p, item.url).id);
        p = await waitFor(item, q => ready(q, item.url));
      } else if (!ready(p, item.url)) p = await waitFor(item, q => ready(q, item.url));
      ensure(ready(p, item.url), 'Target body not ready; do not infer a topic from another document');
      item.contextRead = true; item.phase = 'CONTEXT_READY';
      const outline = compactContext(p, options);
      const size = JSON.stringify(outline).length;
      item.metrics.contextCharsEmitted += size; totals.contextCharsEmitted += size;
      return outline;
    }
    function preview(url, title, rationale = '') {
      const item = itemFor(url);
      ensure(item.contextRead, 'Read target context first');
      ensure(typeof title === 'string' && title.trim() && !/[\r\n]/.test(title), 'One-line title required');
      item.proposedTitle = title; item.rationale = rationale;
      return {...result(item), mode: 'inspect', changeNeeded: title !== item.originalTitle};
    }
    async function verify(url) {
      acknowledged();
      const item = itemFor(url);
      if (terminal.has(item.status)) return result(item, true);
      ensure(item.saveAttempted || item.saveIntent || item.verifyOnly, 'No save to verify');
      item.verifyRounds++;
      const isSaved = p => {
        try { return active(p, item.url) && rowFor(p, item.url).title === item.proposedTitle &&
          !p.nodes.some(n => /text field.*(?:對話標題|对话标题|Chat title)/.test(n.body)); }
        catch (_) { return false; }
      };
      const p = await waitFor(item, isSaved);
      capture(item, p);
      if (isSaved(p)) {
        // An armed-but-undispatched crash does not prove a save attempt by this workflow.
        if (item.saveAttempted === true) { item.status = 'RENAMED'; item.phase = 'VERIFIED'; }
        else { item.status = 'VERIFICATION FAILED'; item.phase = 'STOPPED'; item.reason = 'Save dispatch unknown; observed title alone cannot establish RENAMED'; }
        item.displayedTitle = item.proposedTitle;
      } else {
        item.phase = 'AWAITING_VERIFICATION'; item.displayedTitle = null;
        if (active(p, item.url)) { try { item.displayedTitle = rowFor(p, item.url).title; } catch (_) {} }
        if (item.verifyRounds >= 2) { item.status = 'VERIFICATION FAILED'; item.phase = 'STOPPED'; }
      }
      return result(item);
    }
    async function apply(url, title, rationale = '') {
      acknowledged(); connected();
      const item = itemFor(url);
      if (terminal.has(item.status)) return result(item, true);
      ensure(mode === 'apply', 'Inspect mode cannot edit');
      if (item.saveAttempted || item.saveIntent || item.verifyOnly) return verify(url);
      try {
        noUnresolvedSave(item);
        preview(url, title, rationale);
        let p = await observe(item);
        const original = () => active(p, item.url) && p.documentTitle === item.originalTitle;
        let row = rowFor(p, item.url);
        ensure(original() && row.title === item.originalTitle, 'Target URL/title changed before edit');
        if (title === item.originalTitle) {
          ensure(!editorOpen(p), 'Close observed title editor before no-op verification');
          capture(item, p); item.displayedTitle = row.title;
          item.status = 'ALREADY CORRECT'; item.phase = 'VERIFIED'; return result(item);
        }
        ensure(row.menuId !== undefined, 'Target menu missing');
        await click(item, row.menuId);
        p = await waitFor(item, q => q.nodes.some(n => names.rename.test(n.body)));
        ensure(original(), 'Target changed while opening menu');
        let control = p.nodes.find(n => names.rename.test(n.body));
        ensure(control, 'Rename action missing; never substitute an adjacent action');
        await click(item, control.id);
        p = await waitFor(item, q => q.nodes.some(n => names.input.test(n.body)));
        ensure(original(), 'Target changed while opening editor');
        control = p.nodes.find(n => names.input.test(n.body));
        ensure(control && control.body.match(names.input)[1] === item.originalTitle, 'Editor value mismatch');
        item.phase = 'EDITING'; totals.inputWrites++; item.metrics.inputWrites++;
        await adapter.setValue(control.id, title);
        p = await waitFor(item, q => q.nodes.some(n => n.body.match(names.input)?.[1] === title));
        ensure(original(), 'Target changed before save');
        ensure(p.nodes.some(n => n.body.match(names.input)?.[1] === title), 'Input value not confirmed');
        control = p.nodes.find(n => names.save.test(n.body));
        ensure(control, 'Explicit save button missing');
        if (durable) {
          capture(item, p); item.phase = 'READY_FOR_SAVE';
          item.prepareSnapshotId = p.snapshotId;
          // There is deliberately no save here. arm must commit in SQLite first.
          return result(item);
        }
        item.saveAttempted = true; item.phase = 'AWAITING_VERIFICATION';
        await click(item, control.id);
        return verify(url);
      } catch (error) {
        item.reason = error.message;
        if (paused && item.observation) item.observation.fresh = false;
        if (item.saveAttempted || item.saveIntent) { item.phase = 'AWAITING_VERIFICATION'; return result(item); }
        item.status = 'BLOCKED'; item.phase = 'STOPPED'; return result(item);
      }
    }
    async function commit(url, receipt) {
      acknowledged(); connected();
      const item = itemFor(url);
      ensure(durable && item.phase === 'READY_FOR_SAVE' && !item.saveIntent, 'Prepared unsaved item required; never replay commit');
      ensure(receipt.protocol === protocol && receipt.run_id === runId && receipt.conversation_url === item.url &&
        receipt.proposed_title === item.proposedTitle && receipt.session_epoch === sessionEpoch &&
        receipt.binding_key === bindingKey && receipt.snapshot_id === item.prepareSnapshotId,
        'Save acknowledgement does not match prepared target/session');
      item.saveIntent = true; item.verifyOnly = true; item.intentId = receipt.intent_id;
      item.saveAttempted = null; item.phase = 'AWAITING_VERIFICATION';
      if (receipt.dispatch_authorized !== true) return result(item);
      try {
        noUnresolvedSave(item);
        const receiptAge = now() - Date.parse(receipt.armed_at);
        ensure(Number.isFinite(receiptAge) && receiptAge >= -5000 && receiptAge <= 120000,
          'Save acknowledgement expired; verification only');
        // The durable acknowledgement invalidates the previous AX indices.
        const p = await observe(item);
        ensure(active(p, item.url) && p.documentTitle === item.originalTitle &&
          p.nodes.some(n => n.body.match(names.input)?.[1] === item.proposedTitle),
          'Target/editor changed after arming; verification only');
        const control = p.nodes.find(n => names.save.test(n.body));
        ensure(control, 'Save control disappeared after arming');
        item.saveAttempted = true; // set before dispatch, including unknown click outcomes
        await click(item, control.id);
        return verify(url);
      } catch (error) { item.reason = error.message; item.observation = null; item.verification = null; return result(item); }
    }
    function acceptJournal(state, restore = false) {
      ensure(durable && state.protocol === protocol && state.run_id === runId && state.committed === true,
        'Committed recovery acknowledgement required');
      if (state.recovery_protocol === protocol) ensure(state.binding_key === bindingKey, 'Frozen browser identity mismatch');
      if (restore) {
        ensure(!items.size, 'Restore before freezing; never refreeze a recovered batch');
        freeze(state.targets.map(t => ({url: t.conversation_url, title: t.original_title})), state.targets.length);
      }
      ensure(JSON.stringify([...items.values()].map(x => [x.url, x.originalTitle])) ===
        JSON.stringify(state.targets.map(x => [x.conversation_url, x.original_title])), 'Frozen journal scope mismatch');
      for (const t of state.targets) {
        const item = itemFor(t.conversation_url);
        if (restore) {
          const e = t.latest_event;
          if (e) {
            item.proposedTitle = e.proposed_title; item.displayedTitle = e.displayed_title;
            item.rationale = e.rationale; item.status = e.status;
            item.observation = e.observation || null; item.verification = e.verification;
          }
          item.saveIntent = !!t.save_intent;
          item.saveAttempted = e?.save_attempted ?? (item.saveIntent ? null : false);
          item.verifyOnly = t.action === 'VERIFY_ONLY';
          item.phase = t.action === 'SKIP_VERIFIED' ? 'VERIFIED' : item.verifyOnly ? 'AWAITING_VERIFICATION' : 'PENDING';
          if (item.verifyOnly && item.status !== 'VERIFICATION FAILED') item.status = null;
          if (t.save_intent) item.proposedTitle = t.save_intent.proposed_title;
        }
      }
      journalAck = true; journalState = state.state;
      return [...items.values()].map(x => result(x, true));
    }
    async function recoverBlocked(url) {
      acknowledged(); const item = itemFor(url);
      ensure(journalState === 'OPEN', 'Explicitly reopen the original partial run before recovery');
      ensure(item.status === 'BLOCKED' && !item.saveIntent && item.saveAttempted === false,
        'Only a confirmed no-save blocked item can be recovered');
      const p = await observe(item);
      ensure(active(p, item.url) && rowFor(p, item.url).title === item.originalTitle &&
        p.documentTitle === item.originalTitle && !editorOpen(p), 'Restore target and close editor before recovery');
      ensure(ready(p, item.url), 'Target body not ready; preserve the blocked record');
      item.status = null; item.phase = 'PENDING'; item.contextRead = false;
      item.observation = null; item.verification = null;
      return result(item);
    }
    return {freezeRecent, freezeUrls, context, preview, apply, verify, commit, recoverBlocked,
      acceptJournal: state => acceptJournal(state), restore: state => acceptJournal(state, true),
      results: () => [...items.values()].map(x => result(x, true)), metrics: () => ({...totals})};
  }
  return {canonical, parse, rowFor, active, ready, compactContext, create, toEvent, toCorrection, protocol};
})();
if (typeof module !== 'undefined' && module.exports) module.exports = ChatTitleWorkflow;
