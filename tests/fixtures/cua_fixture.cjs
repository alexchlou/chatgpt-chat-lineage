const assert = require('node:assert/strict');
const url = i => `https://chatgpt.com/c/synthetic-${i}`;
// A UI fixture, not a browser client. Every observation assigns new AX IDs.
// Invalid/stale IDs fail, and successful saves can reorder the entire sidebar.
function fixture(options = {}) {
  const rows = Array.from({length: options.count || 10}, (_, i) => ({url: url(i), title: options.duplicateTitles ? 'Analyze' : `Project${i} | Literature review`}));
  const pinned = [{url: 'https://chatgpt.com/c/pinned-chat', title: 'Pinned project'}];
  let active = options.active || rows[0].url, phase = 'PAGE', epoch = 0, actions = new Map();
  let pending = '', menuDelay = 0, saveDelay = 0;
  let bodyLoaded = !options.loadError;
  const log = [], frozenOrder = rows.map(r => r.url);
  const current = () => rows.find(r => r.url === active);
  async function observe() {
    epoch++;
    if (phase === 'SAVING' && !options.stuckSave) {
      if (saveDelay > 0) saveDelay--;
      else {
        if (!options.failSave) current().title = pending;
        phase = 'PAGE';
        if (options.reorderOnSave) rows.reverse();
      }
    }
    actions = new Map();
    let id = epoch * 1000;
    const lines = [];
    const add = (indent, text, action) => {
      const index = ++id;
      lines.push(' '.repeat(indent) + index + ' ' + text);
      if (action) actions.set(index, action);
    };
    add(0, 'standard window Chrome');
    add(2, `text field (settable) Address and search bar, Value: ${active.replace('https://', '')}, Placeholder: Address`);
    const documentUrl = options.wrongDocument ? url(999) : active;
    add(2, `HTML content ${current().title}, URL: ${options.ellipsisDocument ? '…' : documentUrl.replace('https://', '')}`);
    if (!['EDITOR', 'SAVING'].includes(phase)) {
      add(4, `link Skip to content, Value: ${active.replace('https://', '')}#_r_synthetic_`);
      add(4, 'container Home');
      add(6, 'sortable Pinned'); add(6, 'content list');
      pinned.forEach(r => { add(8, 'container ' + r.title); add(10, `link ${r.title}, Value: ${r.url.replace('https://', '')}`, {kind: 'navigate', url: r.url}); add(10, 'container'); add(12, 'pop up button Conversation actions', {kind: 'menu', url: r.url}); });
      add(6, 'container'); add(8, 'sortable Recents');
      add(6, 'content list');
      rows.forEach(r => {
        add(8, 'container ' + r.title);
        add(10, `link ${r.title}, Value: ${r.url.replace('https://', '')}`, {kind: 'navigate', url: r.url});
        add(10, 'container');
        add(12, 'pop up button Conversation actions', {kind: 'menu', url: r.url});
      });
      add(4, 'container Conversation');
      if (!bodyLoaded) {
        add(6, 'text Unable to load this ChatGPT conversation');
        add(6, 'button Try again');
      } else {
      add(6, 'heading You said:, Value: 4');
      add(6, 'text You said:'); add(6, 'text Review Project Alpha literature and research design');
      add(6, 'text project-alpha-manuscript.pdf PDF');
      add(6, 'button Copy message');
      add(6, 'heading ChatGPT said:, Value: 4');
      add(6, 'heading Project Alpha: literature review and research design, Value: 1');
      add(6, `link Reference this conversation, Value: ${active.replace('https://', '')}`);
      for (let k = 0; k < (options.largeBody ? 150 : 1); k++) add(6, 'text ' + 'This synthetic paragraph tests bounded outline extraction without emitting the full body.'.repeat(12));
      if (options.pendingReply) { add(6, 'heading You said:'); add(6, 'text drp'); add(6, 'button Copy message'); add(6, 'text Reviewed'); }
      add(6, 'container'); add(8, 'text ChatGPT can make mistakes. Check important info.');
      add(6, 'container'); add(8, 'heading Latest response');
      add(8, 'text entry area (settable) Ask ChatGPT, Value: Ask ChatGPT');
      }
    }
    if (phase === 'MENU') {
      add(4, 'menu Conversation actions');
      if (menuDelay > 0) menuDelay--;
      else if (!options.missingRename) add(6, 'Rename', {kind: 'rename'});
      add(6, 'Archive', {kind: 'archive'}); add(6, 'Delete', {kind: 'delete'});
    }
    if (phase === 'EDITOR') {
      add(4, 'container Rename conversation');
      add(6, `text field (settable) Chat title, Value: ${pending}, Placeholder: Add a title...`, {kind: 'input'});
      add(6, 'button Cancel', {kind: 'cancel'});
      if (!options.missingSave) add(6, 'button Save', {kind: 'save'});
    }
    add(2, `tab (selected, settable, boolean) ${options.wrongSelectedTitle ? 'Other conversation' : current().title}${options.noMemoryLabel ? '' : ' - High memory usage - 1 GB'}, Value: on`);
    const ax = lines.join('\n');
    return options.metadata ? {ax, documentIdentity: {url: active, title: options.wrongMetadataTitle ? 'Other conversation' : current().title}} : ax;
  }
  async function click(id) {
    const action = actions.get(id);
    assert.ok(action, 'must use an ID from the freshest observation');
    log.push(action);
    switch (action.kind) {
      case 'navigate': active = action.url; phase = 'PAGE'; break;
      case 'menu': assert.equal(action.url, active); phase = 'MENU'; menuDelay = options.menuDelay || 0; break;
      case 'rename': phase = 'EDITOR'; pending = current().title; break;
      case 'save': phase = 'SAVING'; saveDelay = options.saveDelay || 0; if (options.saveThrows) throw new Error('Unknown click outcome'); break;
      default: throw new Error('Unexpected action ' + action.kind);
    }
  }
  async function setValue(id, title) {
    assert.equal(actions.get(id)?.kind, 'input'); log.push({kind: 'input', value: title}); pending = title;
    if (options.switchBeforeSave) active = rows[1].url;
  }
  return {adapter: {observe, click, setValue}, rows, log, frozenOrder,
    changeTitle: (i, title) => { rows.find(r => r.url === url(i)).title = title; },
    setBodyLoaded: value => { bodyLoaded = value; },
    switchTo: i => { active = url(i); }};
}

module.exports = {fixture, url};
