# Privacy and security

## Data boundary

This public project ships code, English documentation, and fictional fixtures. It does not include a personal research dataset, browser profile, credentials, email archive, or production automation configuration. Public repository attribution is intentional; private home paths, email addresses, and chat identifiers are not.

The runtime needs no private ChatGPT API, session copying, cookie extraction, or browser database editing. Live work uses the host's documented visible UI only. The helper bounds its own operations; it is not an operating-system sandbox.

Research storage is opt-in. Approved metadata includes exact chat URLs, titles, short abstract rationales, topic codes, outcomes, timestamps, and provenance. These can identify a person or reveal private research. Reports and Obsidian exports preserve them; they are private derivatives, not public-safe anonymizations. The agent may read visible context transiently to choose a title but must not persist bodies, excerpts, raw AX, screenshots, or credentials.

Do not commit `research_config.json`, datasets, SQLite files, vaults, `.env` files, access tokens, delivery ledgers, or exported personal reports. Store private datasets outside the repository. `.gitignore` is convenience, not a security boundary. The package builder uses an explicit allowlist, and `check_release.py` scans actual included bytes.

## Failure behavior

- A wrong account, conflicting URL, unreadable body, or unidentified control blocks the affected action.
- A foreground change stops new writes. Reconnect with fresh handles; never reuse old numeric IDs.
- An uncertain save is verified without resaving. An uncertain email is reconciled without resending.
- Browser clicks and database transactions are not atomic. The ledger favors at-most-one dispatch with an explicit unknown result over silent retry.
- Graph fingerprints establish consistency with recorded sources, not truth. Evidence levels never increase due to successful execution or repetition.
- Local data is not encrypted by this project. Use appropriate filesystem access controls and backups. SQLite is single-writer; do not concurrently write a cloud-synced database from several devices.

## Reporting

Do not put private conversation URLs, screenshots, tokens, or raw logs in public issues. Use the repository's private vulnerability-reporting channel if available; otherwise open a minimal, sanitized issue asking for a private contact route. This document does not claim such a channel is configured.

## Release review

A release must pass the project privacy checker, its negative controls, and independent Gitleaks scanning of source and reachable Git history. Inspect Git author/committer and tag metadata separately. Build the release ZIP from a clean tracked tree; reopen it and validate path safety, duplicate entries, CRC, complete file inventory, and SHA-256 hashes. Scan the actual archive bytes after unpacking to an isolated directory. Never publish an audit report containing the secrets it detected.

A clean scan is a result for the tested bytes and rules. It is not proof of universal confidentiality, erasure of historical copies, publisher identity, or legal compliance. A source manifest is an integrity record, not independent certification.
