#!/usr/bin/env python3
"""Deterministic, provenance-preserving graph derived from journal snapshots."""
import argparse
import csv
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import io
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import xml.etree.ElementTree as ET

VERSION = "2.0.0"
TERMINAL = {"RENAMED", "ALREADY CORRECT", "BLOCKED", "VERIFICATION FAILED", "INSPECTED"}
TASK_LABELS = {"research": "Research", "monitoring": "Monitoring", "submission_preparation": "Submission preparation",
               "reading_review": "Reading review", "translation": "Translation", "document_workflow": "Document workflow",
               "device_instructions": "Device instructions", "other": "Other", "undetermined": "Undetermined"}


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def identity(kind, value):
    return kind + ":" + digest(value)


def atomic(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".graph-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def snapshot(root):
    uri = (Path(root).resolve() / "research.sqlite3").as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        return {"runs": [dict(r) for r in db.execute("SELECT * FROM runs ORDER BY run_id")],
                "events": [dict(r) for r in db.execute("SELECT * FROM events ORDER BY event_id")],
                "outcomes": [dict(r) for r in db.execute("SELECT * FROM v_outcomes ORDER BY run_id,position")]}


def relation_engine():
    spec = importlib.util.spec_from_file_location("rename_research_relations", Path(__file__).with_name("research_relations.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def derive(source, registry=None):
    """No title-based NLP or synonym merging; topic/task assertions retain support."""
    source = {k: sorted((dict(r) for r in source[k]), key=lambda r: dump(r))
              for k in ("runs", "events", "outcomes")}
    nodes, edges = {}, {}
    runs = {r["run_id"]: r for r in source["runs"]}
    outcomes = [r for r in source["outcomes"] if r["status"] in TERMINAL]
    excluded = [r for r in source["outcomes"] if r["status"] not in TERMINAL]
    history = defaultdict(list)
    events_for_url = defaultdict(list)

    def node(kind, value, label, **properties):
        key = identity(kind, value)
        item = {"id": key, "type": kind, "label": label, "properties": properties}
        if key in nodes and nodes[key] != item:
            raise ValueError("Conflicting properties for stable node: " + key)
        nodes[key] = item
        return key

    def edge(start, relation, end, **properties):
        key = identity("edge", start + "\n" + relation + "\n" + end)
        item = {"id": key, "source": start, "relation": relation, "target": end, "properties": properties}
        if key in edges and edges[key] != item:
            raise ValueError("Conflicting graph assertion: " + key)
        edges[key] = item

    pending_counts = Counter(r["run_id"] for r in excluded)
    for rid, row in runs.items():
        meta = json.loads(row["metadata_json"])
        props = {k: meta.get(k) for k in ("event_date", "mode", "source_type", "source_ref", "source_sha256",
                 "skill_version", "scope_kind", "selection_rule", "requested_count", "exclude_pinned",
                 "triggered_at", "scheduled_at", "limitations")}
        props.update(state=row["state"], pending_target_count=pending_counts[rid],
                     frozen_target_count=len(meta["targets"]))
        node("Run", rid, rid, **props)

    projections = []
    for row in outcomes:
        payload = json.loads(row["payload_json"])
        props = {k: payload.get(k) for k in ("status", "decision", "proposed_title", "displayed_title", "rationale",
                 "reason_codes", "topic_labels", "task_type", "annotation_basis", "context_level",
                 "observed_at", "save_attempted", "verification", "metrics")}
        if "observation" in payload:
            props["observation"] = payload["observation"]
        props.update(run_id=row["run_id"], conversation_url=row["conversation_url"],
                     original_title=row["original_title"], position=row["position"], event_date=row["event_date"],
                     source_type=row["source_type"], result_event_id=row["event_id"], run_state=row["run_state"])
        obs_id = node("Observation", row["run_id"] + "\n" + row["conversation_url"], row["status"], **props)
        props = dict(props, id=obs_id)
        projections.append(props)
        history[row["conversation_url"]].append(props)

    # Plans are retained as events, but never used to assert a topic or a completed observation.
    urls = set(history) | {e["conversation_url"] for e in source["events"]}
    for url in sorted(urls):
        observed = history[url]
        dates = [r["event_date"] for r in observed]
        latest_day = max(dates, default=None)
        latest = [r for r in observed if r["event_date"] == latest_day]
        candidates = sorted({r["displayed_title"] for r in latest if r["displayed_title"]})
        label = candidates[0] if len(candidates) == 1 else ("Multiple observed titles on the same date" if candidates else "No terminal observation")
        node("Conversation", url, label, url=url, latest_observed_titles=candidates,
             same_day_title_ambiguity=len(candidates) > 1, observation_count=len(observed),
             first_observed_date=min(dates, default=None), last_observed_date=latest_day,
             has_terminal_observation=bool(observed))

    for erow in source["events"]:
        p = json.loads(erow["payload_json"])
        props = {k: p.get(k) for k in ("stage", "status", "decision", "proposed_title", "displayed_title",
                 "save_attempted", "observed_at", "verification", "annotation_basis", "context_level",
                 "rationale", "reason_codes", "topic_labels", "task_type", "metrics", "supersedes_event_id")}
        if "observation" in p:
            props["observation"] = p["observation"]
        props.update(event_id=erow["event_id"], run_id=erow["run_id"], sequence=erow["sequence"],
                     conversation_url=erow["conversation_url"], recorded_at=erow["recorded_at"],
                     source_type=runs[erow["run_id"]]["source_type"])
        eid = node("Event", erow["event_id"], erow["stage"], **props)
        edge(eid, "ABOUT", identity("Conversation", erow["conversation_url"]))
        edge(eid, "IN_RUN", identity("Run", erow["run_id"]))
        if p.get("supersedes_event_id"):
            edge(eid, "SUPERSEDES", identity("Event", p["supersedes_event_id"]))
        events_for_url[erow["conversation_url"]].append(dict(props, id=eid))

    supported = defaultdict(list)
    for obs in projections:
        oid = obs["id"]
        cid = identity("Conversation", obs["conversation_url"])
        edge(oid, "ABOUT", cid)
        edge(oid, "IN_RUN", identity("Run", obs["run_id"]))
        edge(oid, "RESULT_EVENT", identity("Event", obs["result_event_id"]))
        edge(oid, "HAS_OUTCOME", node("Outcome", obs["status"], obs["status"]))
        support = {"source_type": obs["source_type"], "annotation_basis": obs["annotation_basis"],
                   "observed_at": obs["observed_at"], "event_date": obs["event_date"]}
        for tag in obs.get("topic_labels") or []:
            tid = node("Topic", tag, tag, identity_policy="exact stored label; no synonym inference")
            edge(oid, "ANNOTATED_TOPIC", tid, **support)
            supported[(cid, "TAGGED_WITH", tid)].append(obs)
        task = obs.get("task_type")
        if task:
            tid = node("TaskType", task, TASK_LABELS.get(task, task), code=task)
            edge(oid, "TASK_TYPE", tid, **support)
            supported[(cid, "RECORDED_TASK", tid)].append(obs)
        for key, relation in (("original_title", "ORIGINAL_TITLE"), ("proposed_title", "PROPOSED_TITLE"),
                              ("displayed_title", "DISPLAYED_TITLE")):
            if obs.get(key):
                edge(oid, relation, node("Title", obs[key], obs[key]))
    for (cid, relation, tid), evidence in supported.items():
        edge(cid, relation, tid, evidence_kind="annotation aggregation, not independent semantic validation",
             support_observation_ids=sorted(r["id"] for r in evidence),
             source_types=sorted({r["source_type"] for r in evidence}),
             annotation_bases=sorted({r["annotation_basis"] for r in evidence}),
             first_recorded_event_date=min(r["event_date"] for r in evidence),
             last_recorded_event_date=max(r["event_date"] for r in evidence))

    # Validate endpoints before publishing any derived files.
    for e in edges.values():
        if e["source"] not in nodes or e["target"] not in nodes:
            raise ValueError("Dangling graph relation: " + e["id"])
    counts = dict(sorted(Counter(n["type"] for n in nodes.values()).items()))
    metadata = {"schema_version": VERSION, "source_snapshot_sha256": digest(dump(source)),
                "node_counts": counts, "node_count": len(nodes), "edge_count": len(edges),
                "terminal_observations": len(outcomes), "excluded_pending_targets": len(excluded),
                "source_counts": dict(sorted(Counter(r["source_type"] for r in outcomes).items())),
                "topic_semantics": "Stored agent annotations; exact labels only; no inferred similarity or causal edges",
                "title_semantics": "Last observed title candidates, not a claim of current live UI state",
                "time_semantics": "Missing observed_at stays null; same-day display sorting does not establish sequence"}
    graph = {"metadata": metadata, "nodes": sorted(nodes.values(), key=lambda x: x["id"]),
             "edges": sorted(edges.values(), key=lambda x: x["id"])}
    view = {"metadata": metadata, "tasks": TASK_LABELS,
            "conversations": [n for n in graph["nodes"] if n["type"] == "Conversation" and n["properties"]["has_terminal_observation"]],
            "observations": sorted(projections, key=lambda x: (x["event_date"], x["run_id"], x["position"])),
            "events": sorted([e for es in events_for_url.values() for e in es], key=lambda x: (x["run_id"], x["sequence"]))}
    view["relationship_records"] = relation_engine().enrich(graph, view, registry)
    # Presentation summary from the same read snapshot. It never changes graph
    # observations, source signatures or relationship evidence levels.
    report_runs = []
    for rid, row in sorted(runs.items()):
        meta = json.loads(row["metadata_json"])
        targets = []
        for target in sorted((r for r in source["outcomes"] if r["run_id"] == rid), key=lambda r: r["position"]):
            payload = json.loads(target["payload_json"]) if target.get("payload_json") else {}
            targets.append({k: target[k] for k in ("position", "conversation_url", "original_title", "status")})
            targets[-1]["displayed_title"] = payload.get("displayed_title")
        terminal_count = sum(t["status"] in TERMINAL for t in targets)
        report_runs.append({"run_id": rid, "event_date": meta["event_date"], "state": row["state"],
                            "source_type": meta["source_type"], "triggered_at": meta.get("triggered_at"),
                            "requested_count": meta["requested_count"], "frozen_count": len(meta["targets"]),
                            "terminal_count": terminal_count, "pending_count": meta["requested_count"] - terminal_count,
                            "status_counts": dict(sorted(Counter(t["status"] for t in targets).items())),
                            "targets": targets})
    view["report"] = {"schema_version": "1.0.0", "runs": report_runs}
    return graph, view


def csv_content(rows, columns):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    for row in rows:
        safe = {}
        for k in columns:
            value = row.get(k)
            text = dump(value) if isinstance(value, (dict, list)) else ("" if value is None else str(value))
            safe[k] = "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text
        writer.writerow(safe)
    return "\ufeff" + output.getvalue()


def build(root, source=None):
    root = Path(root).resolve()
    source = snapshot(root) if source is None else source
    output = root / "knowledge_graph"
    registry_path = output / "relationship_registry.json"
    registry = json.loads(registry_path.read_text()) if registry_path.exists() else None
    graph, view = derive(source, registry)
    template = Path(__file__).resolve().parents[1] / "assets" / "knowledge-graph-view.html"
    graph["metadata"]["build_code_sha256"] = digest(dump({str(p.name): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (Path(__file__), Path(__file__).with_name("research_relations.py"), template)}))
    relations = view.pop("relationship_records")
    previous_path = output / "research_relationships.json"
    previous = json.loads(previous_path.read_text()) if previous_path.exists() else []
    delta = relation_engine().update_record(previous, relations, graph["metadata"])
    updates_path = output / "updates.jsonl"
    update_lines = updates_path.read_text() if updates_path.exists() else ""
    updates = [json.loads(line) for line in update_lines.splitlines() if line.strip()]
    # A repeated snapshot does not duplicate either relationships or export history.
    if not updates or updates[-1]["update_id"] != delta["update_id"]:
        delta["exported_at"] = datetime.now(timezone.utc).isoformat()
        update_lines += dump(delta) + "\n"
    payloads = {
        "graph.json": json.dumps(graph, ensure_ascii=False, indent=2) + "\n",
        "nodes.csv": csv_content(graph["nodes"], ["id", "type", "label", "properties"]),
        "edges.csv": csv_content(graph["edges"], ["id", "source", "relation", "target", "properties"]),
        "research_relationships.json": json.dumps(relations, ensure_ascii=False, indent=2) + "\n",
        "research_relationships.csv": csv_content([{**e, **e["properties"]} for e in relations],
            ["id", "source", "target", "relation", "layer", "tier", "label", "active", "validation_status",
             "origin", "registry_id", "evidence", "validation_needed", "stale_reasons", "support", "source_documents"]),
        "updates.jsonl": update_lines}
    namespace = "http://graphml.graphdrawing.org/xmlns"
    ET.register_namespace("", namespace)
    doc = ET.Element("{" + namespace + "}graphml")
    for key, target in (("type", "node"), ("label", "node"), ("properties", "all"), ("relation", "edge")):
        ET.SubElement(doc, "key", {"id": key, "for": target, "attr.name": key, "attr.type": "string"})
    content = ET.SubElement(doc, "graph", {"id": "rename-knowledge-graph", "edgedefault": "directed"})
    for n in graph["nodes"]:
        element = ET.SubElement(content, "node", {"id": n["id"]})
        for key in ("type", "label", "properties"):
            ET.SubElement(element, "data", {"key": key}).text = dump(n[key]) if key == "properties" else n[key]
    for e in graph["edges"]:
        element = ET.SubElement(content, "edge", {"id": e["id"], "source": e["source"], "target": e["target"]})
        for key in ("relation", "properties"):
            ET.SubElement(element, "data", {"key": key}).text = dump(e[key]) if key == "properties" else e[key]
    payloads["graph.graphml"] = '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(doc, encoding="unicode") + "\n"
    fragment = template.read_text(encoding="utf-8")
    if fragment.count("__KG_DATA__") != 1:
        raise ValueError("Expected exactly one visualization data placeholder")
    fragment = fragment.replace("__KG_DATA__", dump(view).replace("<", "\\u003c").replace("&", "\\u0026"))
    if len(fragment.encode("utf-8")) >= 1_000_000:
        raise ValueError("Visualization exceeds the inline size limit")
    # The published report must also work as an offline file without host CSS.
    payloads["rename-knowledge-graph.html"] = (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light dark">'
        '<title>Chat Lineage: research relationship graph</title>'
        '<style>body{margin:0;background:#f5f7f8} '
        '@media(prefers-color-scheme:dark){body{background:#141d22}}</style>'
        '</head><body>\n' + fragment + '\n</body></html>\n')
    # Keep a content-addressed relationship snapshot for each logical export.
    payloads["revisions/" + delta["update_id"] + ".json"] = json.dumps({
        "update_id": delta["update_id"], "metadata": graph["metadata"], "relationships": relations},
        ensure_ascii=False, indent=2) + "\n"
    manifest = dict(graph["metadata"], generated_at=datetime.now(timezone.utc).isoformat(),
                    update_id=delta["update_id"], files=[{"path": name, "sha256": hashlib.sha256(value.encode()).hexdigest()}
                                                      for name, value in sorted(payloads.items())])
    # Construct and validate everything before touching published files; manifest is commit marker.
    for name, value in payloads.items():
        atomic(output / name, value)
    atomic(output / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return {k: manifest[k] for k in ("node_count", "edge_count", "terminal_observations", "excluded_pending_targets",
                                   "source_snapshot_sha256", "research_relation_counts", "stale_research_relations", "update_id")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    print(json.dumps(build(parser.parse_args().root)))
