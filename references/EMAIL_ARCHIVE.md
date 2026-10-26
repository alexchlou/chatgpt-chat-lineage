# Optional self-addressed Gmail archive

Disabled by default. Enable only after the user explicitly authorizes one report per logical run to their own exact configured address. Use `research_config.json` locally; never commit it. Configure `email_archive.enabled`, `recipient`, `account_email`, and a private `state_root`. Do not infer permission from this file or from a conversation's contents.

After finish and graph export, discover the supported Gmail connector and call get_profile. Its current email must exactly match the configured account and recipient; otherwise stop email actions. No CC, BCC, third-party replies, or alternative recipients. The helper contains no network sender and reads the research database without writing it.

## One dispatch

1. Prepare an immutable package with `email_archive.py prepare`, using the finalized run and matching committed graph snapshot. Supply Node and a Playwright node_modules directory for offline PDF rendering. Use an isolated unsigned-in browser, never the authenticated rename browser. The report includes a previewable PDF and a ZIP containing full offline HTML, the run CSV, summary, structured mail brief, and SHA-256 inventory.
2. Search sent mail for the exact stable `delivery_key`, recipient, and subject. One matching message is verified; multiple matches are a duplicate incident, not permission to send again. Local SEND_INTENT/DISPATCH_STARTED/SENT states permit only reconciliation, even if search returns zero results.
3. Only PREPARED with no matching sent message may be claimed. Wait for the claim transaction. Only that first `dispatch_authorized=true` receipt permits one `payload` call followed by one connector send_email call using the returned structured MIME arguments unchanged.
4. Payload issuance persists DISPATCH_STARTED first. Lost receipts, timeout, or reconnect never authorize another send. Record the actual message ID with `receipt`. Read Gmail full to check To/Subject/SENT/attachments, then raw MIME to verify exact body and PDF/ZIP hashes with `verify`. Delete temporary raw data after verification; retain IDs and conclusions.
5. VERIFIED is skipped. Local corrections, graph changes, PARTIAL-to-COMPLETE recovery, or a template upgrade never create another email for the same run and recipient. The sent attachment remains the original snapshot.

Use `python3 scripts/email_archive.py --help` for CLI details. The sender is a host connector orchestration step, not cron invoking this Python file. No passwords, OAuth tokens, or cookies belong in configuration.

## Body contract

Five English sections directly show:

1. All requested run outcomes: original, proposed, observed title, and status.
2. Newly added cross-topic edges by the run's configured calendar timezone, separately from the initial baseline and cumulative stock. IDs deduplicate repeated exports. Every new edge includes E0/E1/H, basis, source type, and supporting Observation references; full refs and fingerprints are in mail-brief.json.
3. Up to three already registered paper candidates whose source fingerprints still match. Each remains H and states existing metadata support, pending inference, required materials, and stop conditions. No candidates are fabricated to fill a quota.
4. Blocks, verification gaps, missing denominators, quarantined sources, and data limitations.
5. Complete PDF and ZIP attachments. Local file links are never represented as attachments.

Optional paper candidates are read from the dataset's `knowledge_graph/paper_candidates.json`; the installed default asset is empty. Do not place personal candidates in public source. The body must stay below 90,000 UTF-8 bytes or preparation stops rather than silently truncating it.

A sample ID is allowed only when the user separately asks for a sample. Scheduled runs must never use sample IDs to bypass deduplication. Synthetic demos cannot enter the real archive. Offline tests use fake MIME messages and do not establish Gmail delivery or inbox rendering.
