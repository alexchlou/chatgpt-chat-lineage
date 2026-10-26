# Sourced relationships and incremental graphs

The journal remains the source of observations. `knowledge_graph/relationship_registry.json` stores analyst assertions and optional domain coding. Derived exports never overwrite that registry.

## Evidence

| Tier | Meaning | Display |
|---|---|---|
| E0 | Identical recorded tag on two distinct conversation URLs | Solid; deterministically computed |
| E1 | Explicit metadata overlap or compatible topic | Solid; analyst-coded |
| H | Candidate theoretical, comparative, or applied relation | Dashed; PENDING_VALIDATION |

Shared task types, title similarity, or graph proximity do not create semantic edges. Synonyms are not automatically merged. E0/E1 do not validate arguments, mechanisms, causality, or factual conclusions. More observations, successful renames, and exports never promote a tier. `live_ui` describes where metadata was observed, not whether a theory is true.

Each edge binds both exact URLs, terminal Observation IDs, result Event IDs, source type/ref, coding basis, date/time, source-time title, and SHA-256 fingerprints. A corrected source quarantines the old edge as SOURCE_CORRECTED. A same-tier explicit replacement preserves the old assertion as SUPERSEDED_ASSERTION. Missing times remain null.

## Register E1 or H

Only register when the authorized metadata supports a specific connection. Do not open extra chats to fill the graph or invent edges for appearance. Hypotheses must state needed evidence and possible counterexamples.

```sh
python3 scripts/register_research_relation.py --root DATASET --input RELATION.json
python3 scripts/research_journal.py export --root DATASET
```

Required fields: `id`, `source_url`, `target_url`, `tier`, `relation`, `label`, `evidence`, `validation_needed`, `support_observation_ids`, and `source_ref`. E1 relation types are EXPLICIT_METADATA_OVERLAP or METADATA_SUBJECT_OVERLAP; H types begin CANDIDATE_. E0 is computed, never manually registered. Text fields are bounded summaries, not body excerpts.

The registrar derives fingerprints from existing terminal observations at both endpoints. Identical registration is a no-op; changes require a new ID and optional same-tier `supersedes`. Mechanical validation cannot establish the semantic correctness of an analyst assertion.

## Exports

`graph.json`, GraphML, and nodes/edges CSV include workflow provenance and active research relations. `research_relationships.json`/CSV also retain quarantined records and domain coding. `updates.jsonl` records added/changed/removed IDs once per distinct logical snapshot; revisions preserve earlier edge sets. The final `manifest.json` binds shipped hashes and `update_id`.

Open the populated dataset file `knowledge_graph/rename-knowledge-graph.html`, not the empty template in assets. It is offline and uses no CDN. The default network has no invented central task node. Search includes direct neighbors; evidence/source filters, one-hop focus, provenance, historical titles, run denominators, and CSV export support inspection. E0/E1/H are visually and textually distinguished. Domain coding is a separate analyst layer.

Disconnected components and isolated nodes are legitimate data limits. Position, distance, and degree are not evidence or priority measures. The graph describes authorized metadata, not full conversation semantics. [Obsidian](OBSIDIAN.md) preserves this distinction in relation notes.

If export or registration fails, repair metadata or retry export only. Never replay browser saves to repair a graph.
