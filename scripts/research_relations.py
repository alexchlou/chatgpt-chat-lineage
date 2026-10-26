"""Evidence-bounded research projection; never infer content links from layout."""
from collections import Counter, defaultdict
import hashlib
import itertools
import json
import re


TIERS = {"E0": "Exact recorded-tag overlap", "E1": "Metadata compatibility", "H": "Pending hypothesis"}
VERSION = "1.0.0"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def ident(kind, value):
    return kind + ":" + hashlib.sha256(value.encode()).hexdigest()


def support_record(node, runs):
    p = node["properties"]
    return {"observation_id": node["id"], "result_event_id": p["result_event_id"],
            "signature": sha(p), "conversation_url": p["conversation_url"],
            "run_id": p["run_id"], "event_date": p["event_date"],
            "observed_at": p.get("observed_at"), "source_type": p["source_type"],
            "source_ref": runs[p["run_id"]].get("source_ref"),
            "annotation_basis": p.get("annotation_basis"),
            "displayed_title": p.get("displayed_title")}


def validate_registry(registry):
    if registry.get("schema_version") != VERSION:
        raise ValueError("Unsupported relationship registry schema")
    seen = set()
    for a in registry.get("assertions", []):
        required = ("id", "source_url", "target_url", "tier", "relation", "label", "evidence",
                    "validation_needed", "support", "source_documents", "validation_status")
        if any(k not in a for k in required):
            raise ValueError("Incomplete research assertion")
        if a["id"] in seen or a["tier"] not in TIERS or a["source_url"] == a["target_url"]:
            raise ValueError("Invalid or duplicate research assertion: " + a["id"])
        seen.add(a["id"])
        if ((a["tier"] == "E0" and a["relation"] != "SHARED_RECORDED_TAG") or
            (a["tier"] == "E1" and a["relation"] not in {"EXPLICIT_METADATA_OVERLAP", "METADATA_SUBJECT_OVERLAP"}) or
            (a["tier"] == "H" and not a["relation"].startswith("CANDIDATE_"))):
            raise ValueError("Relationship type conflicts with evidence tier")
        if not a["source_documents"] or not a["support"] or not a["validation_needed"]:
            raise ValueError("Missing assertion provenance: " + a["id"])
        covered = {s["conversation_url"] for s in a["support"]}
        if {a["source_url"], a["target_url"]} != covered:
            raise ValueError("Both endpoints require source observations: " + a["id"])
        for s in a["support"]:
            if not all(s.get(k) for k in ("observation_id", "result_event_id", "signature")):
                raise ValueError("Missing source signature: " + a["id"])
            if not re.fullmatch(r"[0-9a-f]{64}", s["signature"]):
                raise ValueError("Invalid source signature")
        for doc in a["source_documents"]:
            if not doc.get("path") or not re.fullmatch(r"[0-9a-f]{64}", doc.get("sha256", "")):
                raise ValueError("Invalid source document fingerprint")
        allowed = {"E0": "RECORDED_LABEL_OVERLAP", "E1": "METADATA_COMPATIBILITY_ONLY", "H": "PENDING_VALIDATION"}
        if a["validation_status"] != allowed[a["tier"]]:
            raise ValueError("Evidence tier cannot upgrade validation: " + a["id"])
        if a["tier"] == "E0" and not a.get("shared_tag"):
            raise ValueError("E0 requires an exact stored tag")
    by_id = {a["id"]: a for a in registry.get("assertions", [])}
    for a in by_id.values():
        if a.get("superseded_by"):
            replacement = by_id.get(a["superseded_by"])
            if not replacement or replacement.get("supersedes") != a["id"] or replacement["tier"] != a["tier"]:
                raise ValueError("Invalid assertion replacement lineage")


def enrich(graph, view, registry=None):
    registry = registry or {"schema_version": VERSION, "assertions": [], "conversation_annotations": [], "domains": []}
    validate_registry(registry)
    nodes = {n["id"]: n for n in graph["nodes"]}
    runs = {n["label"]: n["properties"] for n in nodes.values() if n["type"] == "Run"}
    observations = {n["id"]: n for n in nodes.values() if n["type"] == "Observation"}
    conversations = {n["properties"]["url"]: n for n in nodes.values() if n["type"] == "Conversation"}
    records = {oid: support_record(n, runs) for oid, n in observations.items()}
    relations = []

    def validity(support, urls):
        reasons = []
        if not set(urls) <= set(conversations):
            reasons.append("MISSING_ENDPOINT")
        for s in support:
            current = records.get(s["observation_id"])
            if current is None:
                reasons.append("MISSING_OBSERVATION")
            elif any(current[k] != s[k] for k in ("signature", "result_event_id", "conversation_url")):
                reasons.append("SOURCE_CORRECTED")
        return sorted(set(reasons))

    def relation(key, a, b, kind, properties):
        item = {"id": ident("edge", "research\n" + key), "source": a, "target": b,
                "relation": kind, "properties": properties}
        relations.append(item)
        return item

    # A shared label is a reproducible annotation overlap, never semantic equivalence.
    tags = defaultdict(dict)
    for e in graph["edges"]:
        if e["relation"] == "TAGGED_WITH":
            tags[nodes[e["target"]]["label"]][e["source"]] = e
    curated_e0 = {}
    for a in registry["assertions"]:
        if a["tier"] == "E0":
            curated_e0[(tuple(sorted((ident("Conversation", a["source_url"]), ident("Conversation", a["target_url"])))), a["shared_tag"])] = a
    for tag, endpoints in sorted(tags.items()):
        for a, b in itertools.combinations(sorted(endpoints), 2):
            support_ids = sorted(set(endpoints[a]["properties"]["support_observation_ids"] + endpoints[b]["properties"]["support_observation_ids"]))
            annotation = curated_e0.get(((a, b), tag))
            relation("tag\n" + a + "\n" + b + "\n" + tag, a, b, "SHARED_RECORDED_TAG", {
                "layer": "cross_topic", "tier": "E0", "label": "Shared recorded tag: " + tag,
                "shared_tag": tag, "origin": "deterministic_exact_tag_rule", "active": True,
                "validation_status": "RECORDED_LABEL_OVERLAP", "stale_reasons": [],
                "evidence": "Both terminal observations record exactly the same topic tag.",
                "validation_needed": "A shared tag does not establish a common argument, method, causality, or project.",
                "support": [records[i] for i in support_ids],
                "original_edge_ids": [endpoints[a]["id"], endpoints[b]["id"]],
                "source_documents": annotation["source_documents"] if annotation else [],
                "registry_id": annotation["id"] if annotation else None})

    for a in registry["assertions"]:
        if a["tier"] == "E0":
            # Exact-tag rules already publish the active relation; retain invalid seeds as stale.
            key = (tuple(sorted((ident("Conversation", a["source_url"]), ident("Conversation", a["target_url"])))), a["shared_tag"])
            if key[0][0] in tags.get(a["shared_tag"], {}) and key[0][1] in tags.get(a["shared_tag"], {}):
                continue
        reasons = validity(a["support"], [a["source_url"], a["target_url"]])
        if a.get("superseded_by"):
            reasons.append("SUPERSEDED_ASSERTION")
        if a["tier"] == "E0":
            reasons.append("TAG_NO_LONGER_SHARED")
        relation("registry\n" + a["id"], ident("Conversation", a["source_url"]), ident("Conversation", a["target_url"]), a["relation"], {
            "layer": "cross_topic", "tier": a["tier"], "label": a["label"],
            "origin": "analyst_metadata_curation", "active": not reasons, "registry_id": a["id"],
            "validation_status": a["validation_status"], "stale_reasons": sorted(set(reasons)),
            "evidence": a["evidence"], "validation_needed": a["validation_needed"],
            "support": a["support"], "source_documents": a["source_documents"]})

    domain_nodes = []
    domain_ids = set()
    for d in registry.get("domains", []):
        if d["id"] in domain_ids:
            raise ValueError("Duplicate research domain")
        domain_ids.add(d["id"])
        node = {"id": ident("ResearchDomain", d["id"]), "type": "ResearchDomain", "label": d["label"],
                "properties": dict(d, evidence_status="ANALYST_METADATA_CODING")}
        domain_nodes.append(node)
        nodes[node["id"]] = node
    annotations = {}
    for a in registry.get("conversation_annotations", []):
        if a["url"] in annotations or not set(a["domains"]) <= domain_ids:
            raise ValueError("Invalid domain coding")
        annotations[a["url"]] = a
        for domain in a["domains"]:
            reasons = validity(a["support"], [a["url"]])
            if not a["support"] or not a.get("source_documents"):
                raise ValueError("Missing domain coding provenance")
            relation("domain\n" + a["url"] + "\n" + domain, ident("Conversation", a["url"]), ident("ResearchDomain", domain), "ANALYST_CLASSIFIED_IN", {
                "layer": "domain_coding", "tier": "E1", "label": "Analyst classification", "active": not reasons,
                "validation_status": "ANALYST_METADATA_CODING", "origin": "analyst_metadata_curation",
                "evidence": registry.get("basis", "Title and metadata coding"), "stale_reasons": reasons,
                "validation_needed": "Domain coding does not establish theoretical coherence, priority, or a paper project.",
                "support": a["support"], "source_documents": a["source_documents"]})

    # Stale relationships are exported for audit, but cannot assert graph endpoints or active support.
    valid_edges = [e for e in relations if e["properties"]["active"]]
    for e in valid_edges:
        if e["source"] not in nodes or e["target"] not in nodes:
            raise ValueError("Dangling research edge")
    graph["nodes"] = sorted(nodes.values(), key=lambda n: n["id"])
    graph["edges"] = sorted(graph["edges"] + valid_edges, key=lambda e: e["id"])
    cross = [e for e in relations if e["properties"]["layer"] == "cross_topic"]
    graph["metadata"].update(
        node_counts=dict(sorted(Counter(n["type"] for n in nodes.values()).items())),
        node_count=len(nodes), edge_count=len(graph["edges"]),
        relationship_registry_sha256=sha(registry),
        research_relation_counts=dict(sorted(Counter(e["properties"]["tier"] for e in cross if e["properties"]["active"]).items())),
        stale_research_relations=sum(not e["properties"]["active"] for e in relations),
        research_semantics="E0 exact recorded tag overlap; E1 metadata compatibility only; H pending hypotheses; no automatic promotion")
    view["research"] = {"nodes": [{**n, "coding": annotations.get(n["properties"]["url"], {})} for n in view["conversations"]] + domain_nodes,
                        "edges": sorted(valid_edges, key=lambda e: e["id"]),
                        "stale_relations": [e for e in relations if not e["properties"]["active"]],
                        "tiers": TIERS}
    return sorted(relations, key=lambda e: e["id"])


def update_record(previous, relations, metadata):
    """Pure delta calculation: replaying an identical export has no new update."""
    old = {e["id"]: sha(e) for e in previous}
    new = {e["id"]: sha(e) for e in relations}
    return {"update_id": sha({"source": metadata["source_snapshot_sha256"],
                              "registry": metadata["relationship_registry_sha256"], "relations": relations,
                              "builder": metadata["schema_version"], "build_code_sha256": metadata.get("build_code_sha256")}),
            "source_snapshot_sha256": metadata["source_snapshot_sha256"],
            "registry_sha256": metadata["relationship_registry_sha256"],
            "build_code_sha256": metadata.get("build_code_sha256"),
            "added": sorted(new.keys() - old.keys()), "removed": sorted(old.keys() - new.keys()),
            "changed": sorted(k for k in old.keys() & new.keys() if old[k] != new[k]),
            "active_cross_topic_counts": metadata["research_relation_counts"],
            "stale_relations": metadata["stale_research_relations"]}
