# Optional Obsidian vault

Choose a new dedicated vault explicitly. The exporter reads committed graph manifests and performs one-way synchronization; SQLite and the relationship registry remain authoritative. It neither controls Chrome nor sends mail.

```sh
python3 scripts/obsidian_export.py --root DATASET --vault DEDICATED_VAULT --init-vault
```

After initial creation, add `"obsidian": {"enabled": true, "vault_root": "ABSOLUTE_PRIVATE_VAULT_PATH"}` to the dataset's `knowledge_graph/config.json`. The regular journal export then updates this vault. It will not guess or create a different vault during a scheduled run.

## Layout

- `00_Navigation`: home, conversation index, E0/E1/H, domains, quarantined history.
- `10_Conversations`: exact URL, observed title candidates, observations, and all events, including blocked results and corrections.
- `15_Research_Domains`: analyst classifications, not established papers or theories.
- `20_Relations`: active E0/E1/H and a separate Domain_Coding folder, with supporting observations and fingerprints.
- `90_Historical_Relations`: assertions already quarantined at first import. Later retirements keep stable filenames and set `kg_active: false`.
- `_sources/<update_id>`: immutable committed graph, relations, manifest, and interactive HTML.

File names are stable once created. Renames update titles and aliases without breaking existing links. The native Obsidian graph displays note links, not typed evidence edges. Inspect relation properties (`kg_tier`, `kg_active`, `kg_validation_status`) and use the original HTML for evidence filters. Navigation and historical notes can be hidden; inactive relations must also be excluded from interpretation.

## Manual notes and conflicts

Write personal research after `<!-- KG-MANUAL -->`. Sync preserves that section exactly. A changed generated prefix, missing/renamed managed file, path collision, or hash mismatch stops synchronization before note writes. Reconcile against the stable ID and original path; do not regenerate a duplicate note.

Repeating a sync does not rewrite unchanged notes or duplicate source snapshots. A crash after some writes but before state commit can require manual hash reconciliation. The exporter is single-writer and is not a transactional multi-file filesystem.

A failed Obsidian sync does not undo committed journal/graph work and does not authorize another browser save or email. Retry export after resolving the conflict. File checks do not constitute native Obsidian graph usability testing.
