# Incremental research metadata

Storage requires explicit user opt-in and a private local dataset. The public example config is disabled. Titles and exact URLs remain potentially identifying; omitting bodies is not anonymization.

## Units and provenance

- A run has one stable `run_id`, one frozen ordered target list, and a requested denominator.
- A target is one URL within that run. The same URL on another day can produce another observation; do not deduplicate globally by URL.
- Events append plans, pending saves, results, and corrections. Replaying identical serialized input is idempotent. Corrections reference the latest prior event and never erase it.
- Source types are `live_ui`, `historical_artifact`, `historical_transcript`, and `synthetic`. Synthetic data belongs only in isolated demo/test datasets. Historical claims never become live browser evidence.
- `recorded_at` is insertion time; `observed_at` stays null when unknown. `event_date` uses the configured timezone and original run date. Import time cannot replace observation time.
- Labels are analyst codes with `annotation_basis`, not objective truths. Unknown models, metrics, and times remain null. A title-only historical source stays title-only.

Allowed fields and structure are in [RESEARCH_SCHEMA.json](RESEARCH_SCHEMA.json). Python validators additionally enforce semantic consistency. Bodies, excerpts, credentials, raw AX, and screenshots are rejected as extra fields. Rationales are short single-line summaries (at most 600 characters); up to eight topic labels are permitted.

## Order of operations

Follow [RECOVERY.md](RECOVERY.md): resume first; freeze only a new run; wait for start; commit PLANNED before edit; arm before one save dispatch; immediately record every result, including no-ops, blocks, and failures. If the recorder is unavailable, stop new browser writes. Retry metadata, never the browser save.

COMPLETE requires the full requested denominator to succeed. Use PARTIAL for blocked/failed/missing outcomes and INTERRUPTED for an early stop. Loading recovery appends a correction within the original run. Previously sent reports keep their original snapshot.

```sh
python3 scripts/research_journal.py start --root DATASET --input RUN.json
python3 scripts/research_journal.py record --root DATASET --run-id RUN_ID --input EVENT.json
python3 scripts/research_journal.py finish --root DATASET --run-id RUN_ID --state COMPLETE
python3 scripts/research_journal.py export --root DATASET
python3 scripts/research_journal.py stats --root DATASET
```

`ingest` imports a provenance-bearing bundle or retries identical metadata. It does not operate a browser. Build live events from the helper, not hand-authored boolean success flags. RENAMED requires a known save, changed title, and four fresh positive checks. ALREADY CORRECT requires matching original/proposed/actual names and no save. Inspect results use INSPECTED.

## Outputs and limits

SQLite is the canonical single-writer store. CSV, JSONL, and run JSON are derivatives. CSV escapes formula-leading text; SQLite and JSON retain raw approved metadata. An enabled graph uses the same consistent database snapshot and publishes its manifest last. Obsidian follows that commit.

`outcomes` counts frozen targets, including pending placeholders. `terminal_outcomes` and `pending_targets` are separate. A target without a terminal result has no observed title or observation date. Terminal includes blocked outcomes and does not mean success.

Helper counters do not cover unmeasured manual work. Mark `partial`/`helper_only` as appropriate. Item elapsed time is cumulative since batch freeze. A recent-chat list is a convenience sample, may reflect previous renames, and does not represent the full account. A successful UI check proves a displayed state at that time, not future persistence, retrieval improvement, or research validity.
