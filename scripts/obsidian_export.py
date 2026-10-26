# -*- coding: utf-8 -*-
"""One-way, evidence-preserving Markdown projection of a committed graph.

No browser, database mutation, mail transport, or Obsidian plugin is used.
Manual tails survive synchronization; edited managed content blocks the batch.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import html
import json
import os
from pathlib import Path
import re
import tempfile

VERSION = "1.0.0"
MARKER = "\n<!-- KG-MANUAL -->\n"


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode("utf-8")).hexdigest()


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".kg-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(value if isinstance(value, bytes) else value.encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def safe(value):
    return re.sub(r'[\\/:*?"<>|#^\[\]%\x00-\x1f]', "_", value)[:36].strip(" ._") or "Untitled"


def text(value):
    return html.escape(str(value if value is not None else "Unknown"), quote=False).replace("[", "&#91;").replace("]", "&#93;")


def fence(value):
    content = dump(value)
    size = max([2] + [len(m) for m in re.findall(r"`+", content)]) + 1
    ticks = "`" * size
    return ticks + "json\n" + content + "\n" + ticks


def front(values):
    return "---\n" + "\n".join(k + ": " + json.dumps(v, ensure_ascii=False) for k, v in values.items()) + "\n---\n\n"


def committed(root):
    folder = Path(root).resolve() / "knowledge_graph"
    manifest_raw = (folder / "manifest.json").read_bytes()
    manifest = json.loads(manifest_raw)
    hashes = {f["path"]: f["sha256"] for f in manifest["files"]}
    raw = {}
    for name in ("graph.json", "research_relationships.json", "rename-knowledge-graph.html"):
        raw[name] = (folder / name).read_bytes()
        if sha(raw[name]) != hashes.get(name):
            raise ValueError("Uncommitted graph file: " + name)
    graph = json.loads(raw["graph.json"])
    if graph["metadata"]["source_snapshot_sha256"] != manifest["source_snapshot_sha256"]:
        raise ValueError("Graph snapshot mismatch")
    if (folder / "manifest.json").read_bytes() != manifest_raw:
        raise ValueError("Graph changed during read; retry export only")
    raw["manifest.json"] = manifest_raw
    return graph, json.loads(raw["research_relationships.json"]), manifest, raw


def render(graph, relations, manifest, previous):
    nodes = {n["id"]: n for n in graph["nodes"]}
    selected = {k: n for k, n in nodes.items() if n["type"] in {"Conversation", "ResearchDomain"}}
    entities = dict(selected)
    for edge in relations:
        if edge["source"] not in selected or edge["target"] not in selected:
            raise ValueError("Dangling relationship endpoint")
        prop = edge["properties"]
        if prop["tier"] not in {"E0", "E1", "H"}:
            raise ValueError("Unknown evidence tier")
        if prop.get("active") and prop["tier"] == "H" and prop["validation_status"] != "PENDING_VALIDATION":
            raise ValueError("Hypothesis evidence was promoted")
        entities[edge["id"]] = dict(edge, type="Relation", label=prop["label"])
    actual = Counter(e["properties"]["tier"] for e in relations if e["properties"].get("active") and e["properties"]["layer"] == "cross_topic")
    if {k: actual[k] for k in ("E0", "E1", "H")} != {k: manifest["research_relation_counts"].get(k, 0) for k in ("E0", "E1", "H")}:
        raise ValueError("Research relationship denominator mismatch")
    old = previous.get("records", {})
    paths = {}
    for key, node in entities.items():
        prop = node["properties"]
        if node["type"] == "Conversation":
            folder = "10_Conversations"
        elif node["type"] == "ResearchDomain":
            folder = "15_Research_Domains"
        elif not prop.get("active"):
            folder = "90_Historical_Relations"
        elif prop["layer"] == "domain_coding":
            folder = "20_Relations/Domain_Coding"
        else:
            folder = "20_Relations/" + prop["tier"]
        paths[key] = old.get(key, {}).get("path") or folder + "/" + safe(node["label"]) + "--" + sha(key)[:10] + ".md"
    if len(set(paths.values())) != len(paths):
        raise ValueError("Stable note path collision")
    def link(key):
        return "[[" + paths[key][:-3] + "|" + safe(entities[key]["label"]) + "]]"
    adjacency = defaultdict(list)
    for edge in relations:
        if edge["properties"].get("active"):
            for end in (edge["source"], edge["target"]):
                adjacency[end].append(edge)
    observations, events = defaultdict(list), defaultdict(list)
    runs = {n['label']: n for n in nodes.values() if n['type'] == 'Run'}
    for node in nodes.values():
        if node["type"] == "Observation":
            observations[node["properties"]["conversation_url"]].append(node)
        if node["type"] == "Event":
            events[node["properties"]["conversation_url"]].append(node)
    notes = {}
    for key, node in entities.items():
        prop = node["properties"]
        fields = {"kg_id": key, "kg_kind": node["type"], "kg_active": prop.get("active", True),
                  "aliases": [node["label"]], "tags": ["kg/" + node["type"].lower()]}
        body = "# " + text(node["label"]) + "\n\n"
        if node["type"] == "Relation":
            fields.update(kg_tier=prop["tier"], kg_layer=prop["layer"], kg_validation_status=prop["validation_status"],
                          kg_source_observations=[s["observation_id"] for s in prop.get("support", [])])
            if not prop.get("active"):
                body += "> [!warning] Historical relation; excluded from the active layer\n> " + text(", ".join(prop.get("stale_reasons", []))) + "\n\n"
                body += "Endpoint IDs: " + text(edge_id_list(node)) + "\n\n"
            else:
                body += "Endpoints: " + link(node["source"]) + " ↔ " + link(node["target"]) + "\n\n"
            semantics = {"E0": "Shared recorded tags do not establish a common argument or causality.", "E1": "Metadata compatibility or analyst coding does not validate a theory or mechanism.", "H": "Pending hypothesis; repetition, successful saves, and synchronization never promote evidence."}
            body += "> [!info] " + prop["tier"] + "\n> " + semantics[prop["tier"]] + "\n\n"
            body += "## Evidence basis\n\n" + text(prop.get("evidence")) + "\n\n## Validation needs and limitations\n\n" + text(prop.get("validation_needed")) + "\n\n"
            body += "## Full sources, fingerprints, and assertions\n\n" + fence(node) + "\n"
        else:
            if node["type"] == "Conversation":
                url = prop["url"]
                if not re.fullmatch(r"https://chatgpt\.com/(?:g/[^/]+/)?c/[a-zA-Z0-9-]+", url):
                    raise ValueError("Unexpected conversation URL")
                fields.update(kg_url=url, kg_titles=prop["latest_observed_titles"],
                              kg_same_day_ambiguity=prop["same_day_title_ambiguity"], kg_observation_count=prop["observation_count"])
                body += "[Open original conversation](" + url + ")\n\n"
                body += "Title candidates in the snapshot: " + "; ".join(text(v) for v in prop["latest_observed_titles"]) + ". Historical observations do not establish current browser state.\n\n"
                if prop["same_day_title_ambiguity"]:
                    body += "> [!warning] Multiple same-day title candidates\n> Candidates are retained; ordering does not establish chronology.\n\n"
                body += "## Observations and event history\n\nBlocked results, corrections, pending saves, and unknown times are retained. Pending placeholders are not observations.\n\n"
                run_ids = {n['properties']['run_id'] for n in observations[url] + events[url]}
                body += fence({"conversation": node, "observations": sorted(observations[url], key=lambda n: n["id"]),
                               "events": sorted(events[url], key=lambda n: n["id"]),
                               "runs": [runs[k] for k in sorted(run_ids) if k in runs]}) + "\n\n"
            else:
                body += "> Domains are analyst metadata classifications, not confirmed papers, theoretical coherence, or priorities.\n\n" + fence(node) + "\n\n"
            body += "## Related connections\n\n" + ("\n".join("- " + e["properties"]["tier"] + " · " + link(e["id"]) for e in sorted(adjacency[key], key=lambda e: e["id"])) or "No active relations; this node remains isolated.") + "\n"
        notes[key] = {"path": paths[key], "prefix": front(fields) + body}
    groups = [("E0", "E0 Shared Tags"), ("E1", "E1 Metadata Compatibility"), ("H", "H Pending Hypotheses"), ("domain_coding", "Domain Coding"), ("inactive", "Quarantined History")]
    index_links = []
    for group, label in groups:
        matched = [e for e in relations if (not e["properties"].get("active") if group == "inactive" else
                   e["properties"].get("active") and (e["properties"]["layer"] == group if group == "domain_coding" else
                   e["properties"]["layer"] == "cross_topic" and e["properties"]["tier"] == group))]
        path = "00_Navigation/" + label + ".md"
        index_links.append("[[" + path[:-3] + "]]: " + str(len(matched)))
        notes["index:" + group] = {"path": path, "prefix": front({"kg_kind": "Index"}) + "# " + label + "\n\n" + "\n".join("- " + link(e["id"]) for e in matched) + "\n"}
    notes['index:conversations'] = {'path': '00_Navigation/Conversations.md', 'prefix': front({'kg_kind': 'Index'}) + '# Conversations\n\n' + '\n'.join('- ' + link(k) for k, n in selected.items() if n['type'] == 'Conversation') + '\n'}
    home = "# ChatGPT Chat Lineage\n\n[[00_Navigation/Conversations]]\n\n"
    home += "Source update: `" + manifest["update_id"] + "`. Conversations:  " + str(len([n for n in selected.values() if n["type"] == "Conversation"])) + "; terminal observations:  " + str(manifest["terminal_observations"]) + "; historical pending targets:  " + str(manifest["excluded_pending_targets"]) + ".\n\n"
    home += "## Evidence tiers\n\n" + "\n".join("- " + s for s in index_links) + "\n\n## Research domains\n\n"
    home += "\n".join("- " + link(k) for k, n in selected.items() if n["type"] == "ResearchDomain") + "\n\n"
    home += "## Usage\n\nNative graph lines represent note links. E0/E1/H are properties of relation notes; domain coding is separate. Filter the graph with `-path:00_Navigation -path:90_Historical_Relations`; search individual directories such as `path:20_Relations/H` . No community plugins are required.\n\n"
    home += "The interactive report retains evidence filters and source details: [Full offline report](../_sources/" + manifest["update_id"] + "/rename-knowledge-graph.html).\n\n"
    home += "Add personal research after each KG-MANUAL marker; synchronization preserves that section. Edits to generated sections stop synchronization to prevent overwrites. File names remain stable while titles and aliases change. SQLite retains the transaction journal; this vault receives one-way incremental updates from committed snapshots.\n"
    notes["index:home"] = {"path": "00_Navigation/Knowledge_Lineage.md", "prefix": front({"kg_kind": "Index", "kg_source_update": manifest["update_id"]}) + home}
    for key, record in old.items():
        if key not in notes:
            notes[key] = {"path": record["path"], "prefix": front({"kg_id": key, "kg_active": False, "kg_kind": "Retired"}) + "# Retired from the current source snapshot\n\nOriginal records remain in historical snapshots. They are not deleted or treated as active relations.\n", "retired": True}
    return notes


def edge_id_list(node):
    return node["source"] + " ↔ " + node["target"]


def sync(root, vault, initialize=False):
    root, vault = Path(root).resolve(), Path(vault).resolve()
    if vault == root or root.is_relative_to(vault) or vault == root / "knowledge_graph":
        raise ValueError("Use a dedicated vault directory, not a source ancestor")
    graph, relations, manifest, source_files = committed(root)
    state_file = vault / ".kg-sync.json"
    previous = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
    if previous and previous.get('source_root') != str(root):
        raise ValueError('Vault is managed by a different source dataset')
    if not (vault / ".obsidian").is_dir() and not initialize:
        raise ValueError("Vault not initialized; select an existing vault or explicitly initialize a new one")
    if initialize and not previous and vault.exists() and any(vault.iterdir()):
        raise ValueError("New vault destination must be empty")
    notes = render(graph, relations, manifest, previous)
    changes, records, counts = [], {}, Counter()
    for key, note in notes.items():
        path = vault / note["path"]
        if not path.resolve().is_relative_to(vault) or path.is_symlink():
            raise ValueError("Unsafe vault path")
        manual = "\n## My research notes\n\n"
        existing = path.read_text(encoding="utf-8") if path.exists() else None
        if existing is None and key in previous.get('records', {}):
            raise ValueError('Managed note missing or renamed; no files written: ' + str(path))
        if existing is not None:
            prior = previous.get("records", {}).get(key)
            if not prior or existing.count(MARKER) != 1:
                raise ValueError("Unmanaged note collision; no files written: " + str(path))
            prefix, manual = existing.split(MARKER, 1)
            if sha(prefix) != prior["managed_sha256"]:
                raise ValueError("Managed note edited; no files written: " + str(path))
        content = note["prefix"] + MARKER + manual
        records[key] = {"path": note["path"], "managed_sha256": sha(note["prefix"]), "retired": note.get("retired", False)}
        counts["created" if existing is None else "unchanged" if existing == content else "updated"] += 1
        if content != existing:
            changes.append((path, content))
    snapshot_dir = vault / "_sources" / manifest["update_id"]
    if not snapshot_dir.resolve().is_relative_to(vault):
        raise ValueError('Unsafe source snapshot path')
    for name, raw in source_files.items():
        path = snapshot_dir / name
        if path.exists() and name != "manifest.json" and path.read_bytes() != raw:
            raise ValueError("Immutable snapshot conflict; no files written")
    if initialize and not (vault / ".obsidian").exists():
        atomic(vault / ".obsidian/app.json", "{}\n")
    for path, content in changes:
        atomic(path, content)
    for name, raw in source_files.items():
        path = snapshot_dir / name
        if not path.exists():
            atomic(path, raw)
    state = {"version": VERSION, "source_root": str(root), "update_id": manifest["update_id"], "records": records}
    encoded = dump(state) + "\n"
    if not state_file.exists() or state_file.read_text(encoding="utf-8") != encoded:
        atomic(state_file, encoded)
    return {"vault": str(vault), "index": str(vault / notes["index:home"]["path"]), "update_id": manifest["update_id"],
            "notes": len(notes), "created": counts["created"], "updated": counts["updated"], "unchanged": counts["unchanged"],
            "evidence_tiers": manifest["research_relation_counts"], "stale_relations": manifest["stale_research_relations"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--vault", required=True)
    parser.add_argument("--init-vault", action="store_true")
    args = parser.parse_args()
    print(json.dumps(sync(args.root, args.vault, args.init_vault), ensure_ascii=False))
