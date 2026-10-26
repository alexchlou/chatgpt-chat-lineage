# Validation plan

## Deterministic regression

Run Python unit tests and Node fixture tests from CONTRIBUTING.md. Cover identity drift, target changes, unreadable bodies, control absence, one-save dispatch, uncertain saves, reset recovery, append-only corrections, duplicate records, graph idempotency, source quarantine, unchanged H tiers, Obsidian manual sections, immutable mail, and one send dispatch.

The demo builds only synthetic observations. Re-ingest the same bundle and re-export it; event counts, update history, edge IDs, and Obsidian note bytes must stay unchanged. Synthetic source provenance must remain synthetic in all views.

The offline browser test checks actual relation counts, evidence/source filters, provenance details, search, one-hop focus, domain/history views, isolates, zoom, dragging, CSV export, denominators, responsive layouts, dark mode, and zero network requests. It uses a fresh unsigned-in browser.

## Routing contract

ROUTING_CASES.json contains English natural-language invocation cases and negative cases. Check that the installed skill name and trigger description match the intended task. Deterministic contract validation is not a test of every model's real skill selection; unexecuted model routing remains NOT_RUN.

## Privacy release checks

Use the source checker and negative controls for home paths, real-looking chat IDs, private email addresses, credentials, runtime files, symlinks, and non-English prose. Non-English AX selector literals are explicitly exempt from the language check only. They are never exempt from privacy scans.

Run independent Gitleaks source/history scans and a synthetic positive-control leak outside the repository. Reopen the source ZIP and validate actual bytes against the complete manifest. Verify public Git metadata and release assets after publication. Record the versions, scope, exclusions, and remaining limits.

## Live validation is separate

A release test does not rename real chats, access private datasets, send email, or operate native Obsidian. A live smoke test needs its own identified target and authorization. Keeping a correct title does not test saving. A sent-message ID does not prove raw attachment integrity or inbox rendering. Record these layers separately and never report RENAMED from a fixture.
