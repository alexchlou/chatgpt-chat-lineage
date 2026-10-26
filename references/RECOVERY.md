# Durable recovery: rename-recovery/1

This protocol controls save dispatch by this helper. SQLite transactions and browser clicks are not one atomic transaction. If dispatch is uncertain, preserve uncertainty and verify without repeating it.

## Identity and initialization

Discover Chrome and the user-confirmed profile from the current supported inventory. Build a credential-free `bindingKey` from stable identity fields. Verify the account in the visible UI. A new connection receives a new `sessionEpoch`; old browser IDs, tab IDs, handles, and AX indices are invalid.

The native App surface may follow the foreground window. Every adapter observation must return fresh `{ax, bindingKey, documentIdentity?}` for the verified window. A foreground change stops new writes; do not repeatedly seize focus. Restore the exact frozen target before proceeding. See [CUA_WORKFLOW.md](CUA_WORKFLOW.md) for the restricted ellipsis fallback.

## Start or resume

1. Derive a stable logical run ID from the explicitly configured schedule and timezone. Call `research_journal.py resume` **before** selecting chats. Only an explicit `Unknown run_id` permits a new selection; an unreadable database does not.
2. A new run freezes ordered exact URLs once. Include the actual `manifest.json` version, `recovery_protocol: "rename-recovery/1"`, and `browser_binding`. Preserve the requested denominator even when discovery fails; targets can be empty, URLs cannot be invented.
3. Create the helper with `{mode:'apply', durable:true, runId, bindingKey, sessionEpoch, batchAuthorized:true}`. Wait for `start` to commit, then `run.acceptJournal(ack.recovery)`. Do not run start, record, or arm concurrently.
4. After reset, create a fresh helper and call `run.restore(resumeAcknowledgement)`. Never freeze another list. Explicitly reopen PARTIAL/INTERRUPTED when justified; COMPLETE only reuses old outcomes. Save intents survive reopen.

Recovery actions are `SKIP_VERIFIED`, `VERIFY_ONLY`, `READ_CONTEXT`, and `REVIEW_BLOCKED`. Legacy plans lacking a dispatch gate are verification-only. Missing old evidence is never fabricated.

## Before a save

```text
read context -> commit PLANNED event -> apply returns READY_FOR_SAVE
-> commit journal arm -> commit(first authorized receipt) -> fresh checks
-> one save dispatch -> verify -> record the atomic outcome
```

`apply` in durable mode prepares the editor but does not save. A suitable existing title returns a fresh ALREADY CORRECT outcome without opening the menu. Pass the READY_FOR_SAVE bundle's `url`, `proposedTitle`, and `observation` to journal arm:

```json
{"conversation_url":"EXACT_TARGET_URL","proposed_title":"SUPPORTED_TITLE","observation":{}}
```

The empty observation above is a structural illustration, not a valid request. Use the actual helper envelope. Arm checks a committed matching plan, binding, fresh preparation snapshot (within 120 seconds), open editor, and no unresolved save. SQLite enforces one intent per `(run_id, conversation_url)`.

Only the first committed `dispatch_authorized=true` receipt may be passed to `run.commit(url, receipt)`. Commit reobserves identity, title, editor value, and Save. Duplicate arm, lost/expired receipt, reset, or changed foreground permits verification only. Never retry authorization to obtain another save. If recording fails, stop new UI writes and retry only the already serialized metadata.

If dispatch definitely happened but confirmation is pending, record SAVE_PENDING with `save_attempted=true`. If dispatch itself is unknown, retain `save_attempted=null`. Seeing the proposed title cannot establish who saved it. Pending verification blocks all next-target navigation. Two bounded rounds without confirmation end as VERIFICATION FAILED.

## Recover a loading failure in the original run

1. Resume the specified original run, frozen list, and latest event IDs. A later date does not create a replacement run. Skip verified targets without new observations.
2. Verify the original account, URL, original title, and closed editor. With any save intent or unknown save, verify only. Otherwise one explicit visible "Try again" action and bounded observations are allowed.
3. If the body is still unreadable or only the title is visible, keep the original BLOCKED event and PARTIAL/INTERRUPTED state. Do not append identical blocked events or move their timestamps.
4. Once sufficient context is visibly restored, explicitly reopen the same run. Wait for the OPEN acknowledgement. Restore it into a new-epoch durable helper, call `recoverBlocked(url)`, then `context(url)`.
5. If the original title remains adequate, `apply` returns a no-op with the actual title from the same fresh sidebar observation. A change still requires PLANNED/arm/commit; recovery never bypasses the gate.
6. Use `ChatTitleWorkflow.toCorrection(result, reopenedAcknowledgement, annotation)`. It binds the original run and URL and the latest `supersedes_event_id`. Cached data, missing actual titles, wrong runs, save intents, and unknown saves cannot become no-save recovery corrections. A recovery involving a real save must use the normal guarded path and explicit correction validation; do not force it through the no-save helper.
7. Serialize once; retry the exact correction JSON on failure. If the latest event changed, resume and reconcile first. Preserve the old BLOCKED event. Finish according to all original requested outcomes, then export. Recovered metrics are `partial`/`helper_only`, not a fresh validation of skipped successes.
8. Verify manifest hashes, update ID, source provenance, stale relations, and E0/E1/H. Duplicate export must not add an update. Source changes quarantine relationships; they do not promote or silently rebind them.
9. If a report was already sent, keep its original delivery key and immutable attachments. A local correction does not authorize another email or a sample-ID bypass. Describe the distinction between the updated local report and the previously sent snapshot.

## Atomic evidence and idempotency

Use `ChatTitleWorkflow.toEvent(result, annotation)`. The atomic envelope binds run, URL, binding, session epoch, snapshot ID, observation time, actual sidebar title, and editor state. The journal recomputes the four verification checks and rejects mismatches. Never reconstruct evidence from global cached views.

A cached outcome is historical and is skipped. An exact serialized event retry returns `inserted=false`; changing its time or rationale would create a new event and is not a retry. Save intents are recovery metadata, not research observations, and never generate topic edges.

Commands (run from the installed skill):

```sh
python3 scripts/research_journal.py resume --root DATASET --run-id RUN_ID
python3 scripts/research_journal.py reopen --root DATASET --run-id RUN_ID
python3 scripts/research_journal.py arm --root DATASET --run-id RUN_ID --input READY.json
python3 scripts/research_journal.py record --root DATASET --run-id RUN_ID --input EVENT.json
```
