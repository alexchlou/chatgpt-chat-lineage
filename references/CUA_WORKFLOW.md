# Supported visible-UI workflow

All live browser interaction must occur inside the host's `cua_repl` using documented `cua` APIs. On initialization or reset, make exactly the entry call required by that tool and read its returned documentation. This file does not override current tool contracts.

Reuse one verified Chrome binding. Select the user-confirmed profile from the current inventory and verify a unique signed-in account. Never guess or log in automatically. If a supported tab binding fails, refresh the inventory; use a proven native Chrome accessibility surface when available. Do not repeatedly retry a failed binding for every item.

The helper in `scripts/cua_workflow.js` parses the observed native AX format. Load its source directly into a subsequent `cua_repl` invocation after initialization, using only source-loading methods that the host actually supports. Its Node export is for offline tests, not an alternative live driver. Do not use shell automation, external Playwright, private endpoints, cookies, or browser databases for real renaming.

## Adapter

Bind methods from the currently observed Chrome App object:

```javascript
var run = ChatTitleWorkflow.create({
  observe: async () => ({
    ax: await chromeApp.getAXState({emit: false, disableDiffing: true}),
    bindingKey: verifiedCurrentBindingKey
  }),
  click: id => chromeApp.click(id),
  setValue: (id, title) => chromeApp.setValue(id, title)
}, {mode: 'inspect', batchAuthorized: true});
var frozen = await run.freezeRecent(10);
```

Use `batchAuthorized: true` only for an explicitly authorized batch. Use `freezeUrls([exactUrl])` for a specified single target. The binding key must represent the currently verified profile, not a constant attached to an unknown foreground window. Reconnects invalidate numeric browser IDs, tab IDs, object handles, and AX indices.

If AX renders the document URL as a literal ellipsis, an observation may include `documentIdentity: {url, title}` obtained from the current supported tab inventory. It is accepted only when address, document title, and native selected-tab title agree. Never replace a conflicting document URL. Record `identity_source` accurately.

## Reading and decisions

`await run.context(url)` returns a bounded outline of user prompts, headings, and artifact names. If needed, request `{level: 'expanded'}`. If early messages are absent from a virtualized page, navigate the visible UI and read fresh context. A partial visible sample is not the full thread. The default outline budget is 3,500 characters; do not discard decisive context merely to meet it.

Use `run.preview(url, title, rationale)` for inspection. In apply mode use `await run.apply(url, title, rationale)` and follow the durable gate in [RECOVERY.md](RECOVERY.md) when journaling. No-op titles never open an editor. Never use a temporary title to test saving.

Observe between actions. Open only the exact target row's menu; identify Rename and the editor semantically. Verify its current value, then fill. Before the single save, recheck the exact URL, old title, proposed value, binding, and explicit Save control. No controls are inferred from proximity or stale indices.

## Verification and metrics

Require the address and document URL to match, the exact displayed title outside the editor, and a closed editor. A click receipt, vanished dialog, empty sidebar, or stale document is insufficient. Pending verification forbids navigation to the next target. Only two bounded rounds are allowed; unresolved saves become `VERIFICATION FAILED` without another save.

`run.results()` returns metadata in frozen order. Completed results return `delivery=cached`, `fresh=false`; they cannot become new observations. Use `ChatTitleWorkflow.toEvent` on the atomic fresh result, never a global `lastView` cache.

Metrics cover helper operations only. Partial/manual fallback counts remain `partial` or `helper_only`; unknown is not zero. Per-item elapsed time is cumulative since freeze, not isolated item latency. Do not claim a speed improvement without a controlled comparison on the same targets and reading requirements.
